# src/knowbase/claimfirst/extractors/merge_arbiter.py
"""
MergeArbiter — Canonicalisation cross-doc hybride (déterministe + LLM).

Architecture :
1. Phase déterministe : gates safe (prefix-dedup, case-only, version strip)
2. Pré-groupement 2-rail : candidats pour LLM (token overlap + single-token)
3. LLM Merge Arbiter : corpus-grounded verdicts (MERGE/DISTINCT/SIMILAR)
4. SIMILAR_TO : relation non-destructive pour inspection humaine

INV-25: 100% domain-agnostic. Pas de regex SAP, pas de stoplists.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from knowbase.claimfirst.models.entity import Entity, strip_version_qualifier

logger = logging.getLogger(__name__)


# ============================================================================
# Résultats
# ============================================================================

@dataclass
class MergeDecision:
    """Décision de merge pour un groupe d'entités."""
    source_ids: List[str]
    target_id: str
    canonical_name: str
    rule: str  # prefix_duplication, case_only, version_qualifier, llm_*
    confidence: float = 1.0


@dataclass
class SimilarPair:
    """Paire SIMILAR_TO (non-destructive)."""
    entity_id_1: str
    entity_id_2: str
    confidence: float
    reason: str
    evidence: str


@dataclass
class MergeResult:
    """Résultat complet du MergeArbiter."""
    deterministic_merges: List[MergeDecision] = field(default_factory=list)
    llm_merges: List[MergeDecision] = field(default_factory=list)
    similar_pairs: List[SimilarPair] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=lambda: {
        "entities_input": 0,
        "prefix_dedup": 0,
        "case_only": 0,
        "version_strip": 0,
        "llm_merge": 0,
        "llm_distinct": 0,
        "llm_similar": 0,
        "llm_errors": 0,
        "llm_calls": 0,
    })


# ============================================================================
# Prompt LLM
# ============================================================================

MERGE_ARBITER_SYSTEM_PROMPT = """You are an entity resolution expert. For each candidate group, decide if names refer to the SAME real-world entity based ONLY on the corpus evidence provided.

Verdicts:
- MERGE: Same entity. MUST provide rule from: abbreviation, typo, prefix_duplication, format_variant, translation, version_qualifier
- DISTINCT: Different entities despite surface similarity
- SIMILAR: Possibly same, insufficient evidence. Will create soft-link for human review.

IMPORTANT:
- If no corpus evidence supports MERGE → verdict must be SIMILAR (never MERGE)
- Be conservative: when in doubt, choose SIMILAR over MERGE
- Return ONLY valid JSON"""

MERGE_ARBITER_USER_TEMPLATE = """Candidate groups to resolve:

{groups_json}

Return JSON: {{"decisions": [{{"group_index": 0, "verdict": "MERGE|DISTINCT|SIMILAR", "canonical": "best name", "rule": "rule_name", "evidence": "brief explanation"}}]}}"""


# ============================================================================
# MergeArbiter
# ============================================================================

class MergeArbiter:
    """
    Arbitre de fusion cross-doc hybride.

    Phase déterministe (safe, aucune ontologie) + LLM corpus-grounded.
    """

    def __init__(
        self,
        batch_size: int = 15,
        max_concurrent: int = 3,
    ):
        self.batch_size = batch_size
        self.max_concurrent = max_concurrent

    def resolve(
        self,
        entities: List[dict],
        claim_contexts: Dict[str, str],
    ) -> MergeResult:
        """
        Résout les entités en 3 phases.

        Args:
            entities: List[dict] avec entity_id, name, normalized_name, claim_count
            claim_contexts: Dict entity_id → claim excerpt (contexte corpus)

        Returns:
            MergeResult avec deterministic_merges, llm_merges, similar_pairs
        """
        result = MergeResult()
        result.stats["entities_input"] = len(entities)

        if len(entities) < 2:
            return result

        # Phase 1: Gates déterministes
        remaining = self.deterministic_pass(entities, result)

        # Phase 2: LLM Merge Arbiter
        if remaining and len(remaining) >= 2:
            self.llm_pass(remaining, claim_contexts, result)

        return result

    def deterministic_pass(
        self,
        entities: List[dict],
        result: MergeResult,
    ) -> List[dict]:
        """
        Phase déterministe : gates safe.

        Returns:
            Entités restantes (non fusionnées)
        """
        # Index par entity_id
        by_id = {e["entity_id"]: e for e in entities}
        merged_ids: Set[str] = set()

        # --- Gate 1: Prefix dedup ---
        # "SAP SAP S/4HANA" → "SAP S/4HANA"
        for e in entities:
            deduped = self._dedup_prefix(e["name"])
            if deduped != e["name"]:
                # Trouver l'entité cible avec le nom dédupliqué
                target = self._find_entity_by_normalized(
                    entities, Entity.normalize(deduped), exclude_id=e["entity_id"]
                )
                if target and target["entity_id"] not in merged_ids:
                    result.deterministic_merges.append(MergeDecision(
                        source_ids=[e["entity_id"]],
                        target_id=target["entity_id"],
                        canonical_name=target["name"],
                        rule="prefix_duplication",
                    ))
                    merged_ids.add(e["entity_id"])
                    result.stats["prefix_dedup"] += 1

        # --- Gate 2: Case-only ---
        # Noms identiques après normalisation
        norm_groups: Dict[str, List[dict]] = defaultdict(list)
        for e in entities:
            if e["entity_id"] not in merged_ids:
                norm = e.get("normalized_name") or Entity.normalize(e["name"])
                norm_groups[norm].append(e)

        for norm, group in norm_groups.items():
            if len(group) <= 1:
                continue
            # Canonical = celui avec le plus de claims
            canonical = max(group, key=lambda e: e.get("claim_count", 0))
            for e in group:
                if e["entity_id"] != canonical["entity_id"] and e["entity_id"] not in merged_ids:
                    result.deterministic_merges.append(MergeDecision(
                        source_ids=[e["entity_id"]],
                        target_id=canonical["entity_id"],
                        canonical_name=canonical["name"],
                        rule="case_only",
                    ))
                    merged_ids.add(e["entity_id"])
                    result.stats["case_only"] += 1

        # --- Gate 3: Version stripping ---
        version_groups: Dict[str, List[Tuple[dict, Optional[str]]]] = defaultdict(list)
        for e in entities:
            if e["entity_id"] not in merged_ids:
                base_name, version = strip_version_qualifier(e["name"])
                base_norm = Entity.normalize(base_name)
                version_groups[base_norm].append((e, version))

        for base_norm, members in version_groups.items():
            if len(members) <= 1:
                continue
            # Canonical = entity sans version, ou la plus mentionnée
            canonical = None
            for m, version in members:
                if version is None:
                    canonical = m
                    break
            if canonical is None:
                canonical = max([m for m, _ in members], key=lambda m: m.get("claim_count", 0))

            for m, _ in members:
                if m["entity_id"] != canonical["entity_id"] and m["entity_id"] not in merged_ids:
                    result.deterministic_merges.append(MergeDecision(
                        source_ids=[m["entity_id"]],
                        target_id=canonical["entity_id"],
                        canonical_name=canonical["name"],
                        rule="version_qualifier",
                    ))
                    merged_ids.add(m["entity_id"])
                    result.stats["version_strip"] += 1

        # Retourner les entités non fusionnées
        remaining = [e for e in entities if e["entity_id"] not in merged_ids]
        return remaining

    def llm_pass(
        self,
        entities: List[dict],
        claim_contexts: Dict[str, str],
        result: MergeResult,
    ) -> None:
        """
        Phase LLM : pré-groupement 2-rail + arbitrage corpus-grounded.
        """
        # Pré-groupement : identifier les candidats pour LLM
        candidate_groups = self._pregroup_candidates(entities)

        if not candidate_groups:
            return

        logger.info(
            f"[MergeArbiter] {len(candidate_groups)} candidate groups for LLM arbitration"
        )

        # Préparer les groupes avec contexte corpus
        groups_for_llm = []
        for group in candidate_groups:
            group_data = []
            for e in group:
                context = claim_contexts.get(e["entity_id"], "")
                group_data.append({
                    "entity_id": e["entity_id"],
                    "name": e["name"],
                    "claim_excerpt": context[:200] if context else "",
                    "claim_count": e.get("claim_count", 0),
                })
            groups_for_llm.append(group_data)

        # Appeler le LLM par batches
        try:
            decisions = self._call_llm_arbiter(groups_for_llm)
        except Exception as e:
            logger.error(f"[MergeArbiter] LLM arbiter failed (fail-open): {e}")
            result.stats["llm_errors"] += 1
            return

        # Traiter les décisions
        for decision in decisions:
            group_idx = decision.get("group_index", -1)
            if group_idx < 0 or group_idx >= len(candidate_groups):
                continue

            group = candidate_groups[group_idx]
            verdict = decision.get("verdict", "SIMILAR").upper()
            canonical_name = decision.get("canonical", group[0]["name"])
            rule = decision.get("rule", "")
            evidence = decision.get("evidence", "")

            if verdict == "MERGE" and rule:
                # Trouver l'entité canonique
                canonical = None
                for e in group:
                    if e["name"] == canonical_name:
                        canonical = e
                        break
                if canonical is None:
                    canonical = max(group, key=lambda e: e.get("claim_count", 0))

                source_ids = [
                    e["entity_id"] for e in group
                    if e["entity_id"] != canonical["entity_id"]
                ]
                if source_ids:
                    result.llm_merges.append(MergeDecision(
                        source_ids=source_ids,
                        target_id=canonical["entity_id"],
                        canonical_name=canonical["name"],
                        rule=f"llm_{rule}",
                        confidence=0.9,
                    ))
                    result.stats["llm_merge"] += len(source_ids)

            elif verdict == "SIMILAR":
                # Créer SIMILAR_TO entre toutes les paires du groupe
                for i, e1 in enumerate(group):
                    for e2 in group[i + 1:]:
                        result.similar_pairs.append(SimilarPair(
                            entity_id_1=e1["entity_id"],
                            entity_id_2=e2["entity_id"],
                            confidence=0.5,
                            reason=rule or "surface_similarity",
                            evidence=evidence,
                        ))
                        result.stats["llm_similar"] += 1

            elif verdict == "DISTINCT":
                result.stats["llm_distinct"] += 1

    def _pregroup_candidates(
        self,
        entities: List[dict],
    ) -> List[List[dict]]:
        """
        Pré-groupement 2-rail pour candidats LLM.

        Rail A: Token overlap >= 0.5 ET (containment OU Jaccard élevé)
        Rail B: Single-token >= 4 chars, même token normalisé
        """
        groups: List[List[dict]] = []
        used_ids: Set[str] = set()

        # Pré-calculer les tokens
        tokens_by_id: Dict[str, Set[str]] = {}
        for e in entities:
            norm = e.get("normalized_name") or Entity.normalize(e["name"])
            tokens_by_id[e["entity_id"]] = set(norm.split())

        # Rail A: Token overlap
        for i, e1 in enumerate(entities):
            if e1["entity_id"] in used_ids:
                continue
            t1 = tokens_by_id[e1["entity_id"]]
            if not t1:
                continue

            group = [e1]
            for e2 in entities[i + 1:]:
                if e2["entity_id"] in used_ids:
                    continue
                t2 = tokens_by_id[e2["entity_id"]]
                if not t2:
                    continue

                # Token overlap
                intersection = t1 & t2
                union = t1 | t2
                if not union:
                    continue
                jaccard = len(intersection) / len(union)

                # Containment check
                shorter, longer = (t1, t2) if len(t1) <= len(t2) else (t2, t1)
                containment = len(shorter & longer) / len(shorter) if shorter else 0

                if jaccard >= 0.5 or (containment >= 0.8 and len(intersection) >= 1):
                    group.append(e2)

            if len(group) >= 2:
                for e in group:
                    used_ids.add(e["entity_id"])
                groups.append(group)

        # Rail B: Single-token, same normalized token, >= 4 chars
        single_token_groups: Dict[str, List[dict]] = defaultdict(list)
        for e in entities:
            if e["entity_id"] in used_ids:
                continue
            t = tokens_by_id[e["entity_id"]]
            if len(t) == 1:
                token = next(iter(t))
                if len(token) >= 4:
                    single_token_groups[token].append(e)

        for token, group in single_token_groups.items():
            if len(group) >= 2:
                for e in group:
                    used_ids.add(e["entity_id"])
                groups.append(group)

        return groups

    def _call_llm_arbiter(
        self,
        groups_for_llm: List[List[dict]],
    ) -> List[dict]:
        """Appelle le LLM pour arbitrer les groupes candidats."""
        from knowbase.common.llm_router import get_llm_router, TaskType

        all_decisions = []

        # Batch les groupes
        for batch_start in range(0, len(groups_for_llm), self.batch_size):
            batch = groups_for_llm[batch_start:batch_start + self.batch_size]

            # Préparer le JSON des groupes (indexés)
            formatted_groups = []
            for i, group in enumerate(batch):
                formatted_groups.append({
                    "group_index": batch_start + i,
                    "entities": [
                        {
                            "name": e["name"],
                            "claim_excerpt": e.get("claim_excerpt", ""),
                            "claim_count": e.get("claim_count", 0),
                        }
                        for e in group
                    ]
                })

            groups_json = json.dumps(formatted_groups, ensure_ascii=False, indent=2)
            user_prompt = MERGE_ARBITER_USER_TEMPLATE.format(groups_json=groups_json)

            try:
                router = get_llm_router()
                response = router.complete(
                    task_type=TaskType.KNOWLEDGE_EXTRACTION,
                    messages=[
                        {"role": "system", "content": MERGE_ARBITER_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=0.1,
                    max_tokens=2500,
                    response_format={"type": "json_object"},
                ).strip()

                data = json.loads(response)
                decisions = data.get("decisions", [])
                all_decisions.extend(decisions)

            except Exception as e:
                logger.warning(f"[MergeArbiter] LLM batch failed (fail-open): {e}")

        return all_decisions

    # ========================================================================
    # Utilitaires
    # ========================================================================

    @staticmethod
    def _dedup_prefix(name: str) -> str:
        """Détecte et supprime un mot dupliqué en préfixe.

        Ex: "SAP SAP S/4HANA" → "SAP S/4HANA"
        """
        words = name.split()
        if len(words) >= 2 and words[0].lower() == words[1].lower():
            return " ".join(words[1:])
        return name

    @staticmethod
    def _find_entity_by_normalized(
        entities: List[dict],
        target_norm: str,
        exclude_id: str,
    ) -> Optional[dict]:
        """Trouve une entité par son nom normalisé (excluant un ID)."""
        for e in entities:
            norm = e.get("normalized_name") or Entity.normalize(e["name"])
            if norm == target_norm and e["entity_id"] != exclude_id:
                return e
        return None


__all__ = [
    "MergeArbiter",
    "MergeResult",
    "MergeDecision",
    "SimilarPair",
]
