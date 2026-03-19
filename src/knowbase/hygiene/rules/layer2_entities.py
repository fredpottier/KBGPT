"""Règles Layer 2 — Entités singleton, faibles, canonical dedup (LLM-driven).

Parallélisation via ThreadPoolExecutor pour les appels LLM.
Cap sur le volume par run pour rester dans un temps raisonnable.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import re
from typing import Dict, List, Optional

from knowbase.hygiene.models import (
    HygieneAction,
    HygieneActionStatus,
    HygieneActionType,
    HygieneRunScope,
)
from knowbase.hygiene.rules.base import HygieneRule

logger = logging.getLogger("[OSMOSE] kg_hygiene_l2_entities")

# Seuil par défaut d'auto-apply pour L2 SUPPRESS
DEFAULT_AUTO_APPLY_THRESHOLD = 0.9

# Parallélisation LLM
MAX_LLM_WORKERS = 5
BATCH_SIZE = 10
MAX_SINGLETONS_PER_RUN = 200
MAX_WEAK_PER_RUN = 100
MAX_CANONICAL_PAIRS_PER_RUN = 50
MAX_SAME_CANON_PAIRS = 100


def _parse_llm_json(text: str) -> list:
    """Extrait un JSON array depuis une réponse LLM (avec ou sans backticks)."""
    if "```" in text:
        match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
        if match:
            text = match.group(1)
    try:
        result = json.loads(text.strip())
        if isinstance(result, list):
            return result
    except (json.JSONDecodeError, ValueError):
        pass
    return []


def _call_llm(prompt: str, max_tokens: int = 2000) -> str:
    """Appel LLM synchrone — utilisé dans les threads."""
    from knowbase.common.llm_router import get_llm_router, TaskType

    router = get_llm_router()
    return router.complete(
        task_type=TaskType.METADATA_EXTRACTION,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
    )


def _load_domain_summary(neo4j_driver, tenant_id: str) -> str:
    """Charge le domain_summary depuis le DomainContext."""
    with neo4j_driver.session() as session:
        result = session.run(
            "MATCH (dc:DomainContextProfile {tenant_id: $tid}) RETURN dc.domain_summary AS ds",
            tid=tenant_id,
        )
        record = result.single()
        return record["ds"] if record and record["ds"] else ""


class SingletonNoiseRule(HygieneRule):
    """Détecte les entités singleton (1 seule claim) potentiellement du bruit."""

    @property
    def name(self) -> str:
        return "singleton_noise"

    @property
    def layer(self) -> int:
        return 2

    @property
    def description(self) -> str:
        return "Détecte les entités singleton (1 seule claim) via évaluation LLM"

    def scan(
        self,
        neo4j_driver,
        tenant_id: str,
        batch_id: str,
        scope: str,
        scope_params: dict | None = None,
        dry_run: bool = False,
        auto_apply_threshold: float = DEFAULT_AUTO_APPLY_THRESHOLD,
    ) -> List[HygieneAction]:
        singletons = self._load_singletons(neo4j_driver, tenant_id, scope, scope_params)

        if not singletons:
            return []

        # Cap pour garder un temps raisonnable
        if len(singletons) > MAX_SINGLETONS_PER_RUN:
            logger.info(
                f"  → {len(singletons)} singletons, cap à {MAX_SINGLETONS_PER_RUN}"
            )
            singletons = singletons[:MAX_SINGLETONS_PER_RUN]

        domain_summary = _load_domain_summary(neo4j_driver, tenant_id)

        # Préparer les batchs
        batches = [
            singletons[i:i + BATCH_SIZE]
            for i in range(0, len(singletons), BATCH_SIZE)
        ]

        # Évaluation parallèle
        all_evaluations: List[List[dict]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_LLM_WORKERS) as pool:
            futures = {
                pool.submit(self._evaluate_batch_llm, batch, domain_summary): idx
                for idx, batch in enumerate(batches)
            }
            results_map: Dict[int, List[dict]] = {}
            for future in concurrent.futures.as_completed(futures):
                idx = futures[future]
                try:
                    results_map[idx] = future.result()
                except Exception as e:
                    logger.warning(f"Batch {idx} failed: {e}")
                    results_map[idx] = [
                        {"is_noise": False, "confidence": 0.0, "reason": "LLM error"}
                    ] * len(batches[idx])

            # Réassembler dans l'ordre
            for idx in range(len(batches)):
                all_evaluations.append(results_map.get(idx, []))

        # Construire les actions
        actions = []
        for batch, evaluations in zip(batches, all_evaluations):
            for entity, evaluation in zip(batch, evaluations):
                if not evaluation.get("is_noise", False):
                    continue

                confidence = evaluation.get("confidence", 0.5)
                # L2 = toujours PROPOSED, jamais auto-apply
                status = HygieneActionStatus.PROPOSED

                action = HygieneAction(
                    action_type=HygieneActionType.SUPPRESS_ENTITY,
                    target_node_id=entity["entity_id"],
                    target_node_type="Entity",
                    layer=2,
                    confidence=confidence,
                    reason=evaluation.get("reason", f"Singleton noise: '{entity['name']}'"),
                    rule_name=self.name,
                    batch_id=batch_id,
                    scope=scope,
                    status=status,
                    decision_source="rule",
                    tenant_id=tenant_id,
                )
                actions.append(action)

        logger.info(
            f"  → {len(actions)} singletons noise détectés "
            f"({sum(1 for a in actions if a.status == HygieneActionStatus.APPLIED)} auto-applied)"
        )
        return actions

    def _load_singletons(
        self, neo4j_driver, tenant_id: str, scope: str, scope_params: dict | None
    ) -> list:
        """Charge les entités singleton (1 seule claim liée)."""
        with neo4j_driver.session() as session:
            base_where = "e._hygiene_status IS NULL"
            if scope == HygieneRunScope.DOCUMENT_SET.value and scope_params and scope_params.get("doc_ids"):
                result = session.run(
                    f"""
                    MATCH (e:Entity {{tenant_id: $tid}})
                    WHERE {base_where}
                    WITH e
                    MATCH (c:Claim)-[:ABOUT]->(e)
                    WHERE c.doc_id IN $doc_ids
                    WITH e, count(c) AS claim_count, collect(c.text)[0] AS sample_text
                    WHERE claim_count = 1
                    RETURN e.entity_id AS entity_id, e.name AS name,
                           e.entity_type AS entity_type, sample_text
                    """,
                    tid=tenant_id,
                    doc_ids=scope_params["doc_ids"],
                )
            else:
                result = session.run(
                    f"""
                    MATCH (e:Entity {{tenant_id: $tid}})
                    WHERE {base_where}
                    WITH e
                    OPTIONAL MATCH (c:Claim)-[:ABOUT]->(e)
                    WITH e, count(c) AS claim_count, collect(c.text)[0] AS sample_text
                    WHERE claim_count = 1
                    RETURN e.entity_id AS entity_id, e.name AS name,
                           e.entity_type AS entity_type, sample_text
                    """,
                    tid=tenant_id,
                )
            return [dict(r) for r in result]

    def _evaluate_batch_llm(
        self, entities: list, domain_summary: str
    ) -> List[dict]:
        """Évalue un batch d'entités via LLM."""
        fallback = [{"is_noise": False, "confidence": 0.0, "reason": "LLM unavailable"}] * len(entities)
        try:
            entities_text = "\n".join(
                f"- {e['name']} (type: {e.get('entity_type', 'unknown')}, "
                f"context: {(e.get('sample_text') or '')[:100]})"
                for e in entities
            )

            prompt = f"""Analyse these entities from a knowledge graph. The domain is: {domain_summary or 'general'}.

For each entity, determine if it is meaningful domain knowledge or noise (fragments, typos, structural artifacts).

Entities to evaluate:
{entities_text}

Return a JSON array with one object per entity:
[{{"name": "...", "is_noise": true/false, "confidence": 0.0-1.0, "reason": "..."}}]

Only mark as noise entities that are clearly not domain-relevant concepts."""

            text = _call_llm(prompt)
            results = _parse_llm_json(text)
            if len(results) == len(entities):
                return results

            logger.warning(f"LLM returned {len(results)} results for {len(entities)} entities")
        except Exception as e:
            logger.warning(f"LLM evaluation failed: {e}")

        return fallback


class CanonicalDedupRule(HygieneRule):
    """Détecte les CanonicalEntity candidates à fusion (variantes sémantiques)."""

    @property
    def name(self) -> str:
        return "canonical_dedup"

    @property
    def layer(self) -> int:
        return 2

    @property
    def description(self) -> str:
        return "Propose la fusion de CanonicalEntity sémantiquement similaires (toujours PROPOSED)"

    def scan(
        self,
        neo4j_driver,
        tenant_id: str,
        batch_id: str,
        scope: str,
        scope_params: dict | None = None,
        dry_run: bool = False,
    ) -> List[HygieneAction]:
        canonicals = self._load_canonicals(neo4j_driver, tenant_id)

        if len(canonicals) < 2:
            return []

        domain_summary = _load_domain_summary(neo4j_driver, tenant_id)
        candidates = self._find_candidate_pairs(canonicals)

        if not candidates:
            return []

        # Évaluation parallèle par batchs de paires
        batches = [
            candidates[i:i + BATCH_SIZE]
            for i in range(0, len(candidates), BATCH_SIZE)
        ]

        all_evaluations: List[List[dict]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_LLM_WORKERS) as pool:
            futures = {
                pool.submit(self._evaluate_pairs_llm, batch, domain_summary): idx
                for idx, batch in enumerate(batches)
            }
            results_map: Dict[int, List[dict]] = {}
            for future in concurrent.futures.as_completed(futures):
                idx = futures[future]
                try:
                    results_map[idx] = future.result()
                except Exception as e:
                    logger.warning(f"Canonical dedup batch {idx} failed: {e}")
                    results_map[idx] = [
                        {"should_merge": False, "confidence": 0.0, "reason": "LLM error"}
                    ] * len(batches[idx])

            for idx in range(len(batches)):
                all_evaluations.append(results_map.get(idx, []))

        actions = []
        for batch, evaluations in zip(batches, all_evaluations):
            for (c1, c2), evaluation in zip(batch, evaluations):
                if not evaluation.get("should_merge", False):
                    continue

                action = HygieneAction(
                    action_type=HygieneActionType.MERGE_CANONICAL,
                    target_node_id=c2["canonical_id"],
                    target_node_type="CanonicalEntity",
                    layer=2,
                    confidence=evaluation.get("confidence", 0.5),
                    reason=evaluation.get("reason", f"Fusion: '{c2['name']}' → '{c1['name']}'"),
                    rule_name=self.name,
                    batch_id=batch_id,
                    scope=scope,
                    status=HygieneActionStatus.PROPOSED,
                    decision_source="rule",
                    tenant_id=tenant_id,
                    after_state={"merge_target_id": c1["canonical_id"]},
                )
                actions.append(action)

        logger.info(f"  → {len(actions)} fusions CanonicalEntity proposées")
        return actions

    def _load_canonicals(self, neo4j_driver, tenant_id: str) -> list:
        with neo4j_driver.session() as session:
            result = session.run(
                """
                MATCH (ce:CanonicalEntity {tenant_id: $tid})
                WHERE ce._hygiene_status IS NULL
                OPTIONAL MATCH (e:Entity)-[:SAME_CANON_AS]->(ce)
                RETURN ce.canonical_entity_id AS canonical_id, ce.name AS name,
                       ce.normalized_name AS normalized_name,
                       ce.entity_type AS entity_type,
                       count(e) AS entity_count
                """,
                tid=tenant_id,
            )
            return [dict(r) for r in result]

    @staticmethod
    def _dehyphenate(name: str) -> str:
        """Supprime les tirets pour normaliser les variantes (pre-eclampsia → preeclampsia)."""
        return name.replace("-", "").replace("–", "").replace("—", "")

    def _find_candidate_pairs(self, canonicals: list) -> list:
        pairs = []
        seen = set()

        for i, c1 in enumerate(canonicals):
            n1 = (c1.get("normalized_name") or c1.get("name", "")).lower()
            n1_dehyph = self._dehyphenate(n1)
            words1 = set(re.findall(r"\b\w+\b", n1))

            for c2 in canonicals[i + 1:]:
                pair_key = tuple(sorted([c1["canonical_id"], c2["canonical_id"]]))
                if pair_key in seen:
                    continue

                n2 = (c2.get("normalized_name") or c2.get("name", "")).lower()
                n2_dehyph = self._dehyphenate(n2)
                words2 = set(re.findall(r"\b\w+\b", n2))

                matched = False
                if words1 and words2:
                    overlap = len(words1 & words2) / min(len(words1), len(words2))
                    if overlap >= 0.5:
                        matched = True

                # Fallback : variantes avec/sans tiret (pre-eclampsia ↔ preeclampsia)
                if not matched and n1_dehyph and n2_dehyph:
                    if n1_dehyph == n2_dehyph:
                        matched = True

                if matched:
                    pairs.append((c1, c2))
                    seen.add(pair_key)

        return pairs[:MAX_CANONICAL_PAIRS_PER_RUN]

    def _evaluate_pairs_llm(self, pairs: list, domain_summary: str) -> List[dict]:
        fallback = [{"should_merge": False, "confidence": 0.0, "reason": "LLM unavailable"}] * len(pairs)
        try:
            pairs_text = "\n".join(
                f"- Pair {i+1}: '{c1['name']}' (type: {c1.get('entity_type', '?')}, "
                f"{c1.get('entity_count', 0)} entities) vs "
                f"'{c2['name']}' (type: {c2.get('entity_type', '?')}, "
                f"{c2.get('entity_count', 0)} entities)"
                for i, (c1, c2) in enumerate(pairs)
            )

            prompt = f"""Analyse these pairs of canonical entities from a knowledge graph. Domain: {domain_summary or 'general'}.

Determine if each pair should be merged (they represent the same concept) or kept separate.

Pairs:
{pairs_text}

Return a JSON array:
[{{"pair": 1, "should_merge": true/false, "confidence": 0.0-1.0, "reason": "..."}}]"""

            text = _call_llm(prompt)
            results = _parse_llm_json(text)
            if len(results) == len(pairs):
                return results
        except Exception as e:
            logger.warning(f"LLM canonical dedup evaluation failed: {e}")

        return fallback


class WeakEntityRule(HygieneRule):
    """Détecte les entités faibles (fragments de phrases, noms trop longs)."""

    @property
    def name(self) -> str:
        return "weak_entity"

    @property
    def layer(self) -> int:
        return 2

    @property
    def description(self) -> str:
        return "Détecte les entités faibles via LLM (fragments, phrases, non-concepts)"

    def scan(
        self,
        neo4j_driver,
        tenant_id: str,
        batch_id: str,
        scope: str,
        scope_params: dict | None = None,
        dry_run: bool = False,
        auto_apply_threshold: float = DEFAULT_AUTO_APPLY_THRESHOLD,
    ) -> List[HygieneAction]:
        weak_candidates = self._load_weak_candidates(neo4j_driver, tenant_id, scope, scope_params)

        if not weak_candidates:
            return []

        if len(weak_candidates) > MAX_WEAK_PER_RUN:
            logger.info(f"  → {len(weak_candidates)} weak candidates, cap à {MAX_WEAK_PER_RUN}")
            weak_candidates = weak_candidates[:MAX_WEAK_PER_RUN]

        domain_summary = _load_domain_summary(neo4j_driver, tenant_id)

        batches = [
            weak_candidates[i:i + BATCH_SIZE]
            for i in range(0, len(weak_candidates), BATCH_SIZE)
        ]

        all_evaluations: List[List[dict]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_LLM_WORKERS) as pool:
            futures = {
                pool.submit(self._evaluate_weak_llm, batch, domain_summary): idx
                for idx, batch in enumerate(batches)
            }
            results_map: Dict[int, List[dict]] = {}
            for future in concurrent.futures.as_completed(futures):
                idx = futures[future]
                try:
                    results_map[idx] = future.result()
                except Exception as e:
                    logger.warning(f"Weak entity batch {idx} failed: {e}")
                    results_map[idx] = [
                        {"is_weak": False, "confidence": 0.0, "reason": "LLM error"}
                    ] * len(batches[idx])

            for idx in range(len(batches)):
                all_evaluations.append(results_map.get(idx, []))

        actions = []
        for batch, evaluations in zip(batches, all_evaluations):
            for entity, evaluation in zip(batch, evaluations):
                if not evaluation.get("is_weak", False):
                    continue

                confidence = evaluation.get("confidence", 0.5)
                # L2 = toujours PROPOSED, jamais auto-apply
                status = HygieneActionStatus.PROPOSED

                action = HygieneAction(
                    action_type=HygieneActionType.SUPPRESS_ENTITY,
                    target_node_id=entity["entity_id"],
                    target_node_type="Entity",
                    layer=2,
                    confidence=confidence,
                    reason=evaluation.get("reason", f"Entité faible: '{entity['name']}'"),
                    rule_name=self.name,
                    batch_id=batch_id,
                    scope=scope,
                    status=status,
                    decision_source="rule",
                    tenant_id=tenant_id,
                )
                actions.append(action)

        logger.info(f"  → {len(actions)} entités faibles détectées")
        return actions

    def _load_weak_candidates(
        self, neo4j_driver, tenant_id: str, scope: str, scope_params: dict | None
    ) -> list:
        with neo4j_driver.session() as session:
            result = session.run(
                """
                MATCH (e:Entity {tenant_id: $tid})
                WHERE e._hygiene_status IS NULL
                  AND (size(e.name) > 50 OR e.name CONTAINS '  ')
                RETURN e.entity_id AS entity_id, e.name AS name,
                       e.entity_type AS entity_type
                LIMIT 200
                """,
                tid=tenant_id,
            )
            return [dict(r) for r in result]

    def _evaluate_weak_llm(self, entities: list, domain_summary: str) -> List[dict]:
        fallback = [{"is_weak": False, "confidence": 0.0, "reason": "LLM unavailable"}] * len(entities)
        try:
            entities_text = "\n".join(
                f"- '{e['name']}' (type: {e.get('entity_type', 'unknown')})"
                for e in entities
            )

            prompt = f"""Evaluate these entity names from a knowledge graph. Domain: {domain_summary or 'general'}.

Determine if each entity name is a real concept or a fragment/phrase that should not be an entity.

Entities:
{entities_text}

Return a JSON array:
[{{"name": "...", "is_weak": true/false, "confidence": 0.0-1.0, "reason": "..."}}]"""

            text = _call_llm(prompt)
            results = _parse_llm_json(text)
            if len(results) == len(entities):
                return results
        except Exception as e:
            logger.warning(f"LLM weak entity evaluation failed: {e}")

        return fallback


class SameCanonEntityDedupRule(HygieneRule):
    """Détecte les Entity dupliquées pointant vers le même CanonicalEntity.

    Quand 2+ Entity partagent le même canonical (via SAME_CANON_AS),
    propose de fusionner les plus petites dans la plus grosse
    (transfert des claims, suppression du doublon).
    """

    @property
    def name(self) -> str:
        return "same_canon_entity_dedup"

    @property
    def layer(self) -> int:
        return 2

    @property
    def description(self) -> str:
        return "Fusionne les Entity dupliquées partageant le même CanonicalEntity"

    def scan(
        self,
        neo4j_driver,
        tenant_id: str,
        batch_id: str,
        scope: str,
        scope_params: dict | None = None,
        dry_run: bool = False,
        auto_apply_threshold: float = DEFAULT_AUTO_APPLY_THRESHOLD,
    ) -> List[HygieneAction]:
        groups = self._find_same_canon_groups(neo4j_driver, tenant_id)

        if not groups:
            return []

        actions = []
        for group in groups[:MAX_SAME_CANON_PAIRS]:
            # Trier par claim_count desc — la plus grosse est le target
            sorted_entities = sorted(group["entities"], key=lambda e: e["claim_count"], reverse=True)
            target = sorted_entities[0]

            for source in sorted_entities[1:]:
                action = HygieneAction(
                    action_type=HygieneActionType.MERGE_ENTITY,
                    target_node_id=source["entity_id"],
                    target_node_type="Entity",
                    before_state={
                        "source_name": source["name"],
                        "source_entity_id": source["entity_id"],
                        "source_claim_count": source["claim_count"],
                        "target_name": target["name"],
                        "target_entity_id": target["entity_id"],
                        "target_claim_count": target["claim_count"],
                        "canonical_id": group["canonical_id"],
                    },
                    after_state={
                        "merge_target_entity_id": target["entity_id"],
                        "canonical_id": group["canonical_id"],
                    },
                    layer=2,
                    confidence=1.0,
                    reason=(
                        f"Entity doublon : '{source['name']}' ({source['claim_count']} claims) "
                        f"→ fusion dans '{target['name']}' ({target['claim_count']} claims) — "
                        f"même CanonicalEntity"
                    ),
                    rule_name=self.name,
                    batch_id=batch_id,
                    scope=scope,
                    status=HygieneActionStatus.PROPOSED,
                    decision_source="rule",
                    tenant_id=tenant_id,
                )
                actions.append(action)

        logger.info(f"  → {len(actions)} entity doublons détectés (même canonical)")
        return actions

    def _find_same_canon_groups(self, neo4j_driver, tenant_id: str) -> list:
        """Trouve les CanonicalEntity liés à 2+ Entity actives."""
        with neo4j_driver.session() as session:
            result = session.run(
                """
                MATCH (e:Entity {tenant_id: $tid})-[:SAME_CANON_AS]->(ce:CanonicalEntity)
                WHERE e._hygiene_status IS NULL
                WITH ce, collect({
                    entity_id: e.entity_id,
                    name: e.name,
                    entity_type: e.entity_type,
                    hub_degree: coalesce(e.hub_degree, 0)
                }) AS entities
                WHERE size(entities) >= 2
                RETURN ce.canonical_entity_id AS canonical_id,
                       ce.name AS canonical_name,
                       entities
                """,
                tid=tenant_id,
            )
            groups = []
            for r in result:
                enriched = []
                for ent in r["entities"]:
                    ent_dict = dict(ent)
                    ent_dict["claim_count"] = ent_dict.get("hub_degree", 0)
                    enriched.append(ent_dict)

                groups.append({
                    "canonical_id": r["canonical_id"],
                    "canonical_name": r["canonical_name"],
                    "entities": enriched,
                })
            return groups
