"""Règles Layer 3 — Hygiène avancée des axes d'applicabilité.

Toutes les actions L3 sont PROPOSÉES — jamais auto-apply.
Trois règles :
  - LowValueAxisRule   : axes à faible valeur de navigation
  - RedundantAxisRule  : axes redondants candidats à fusion
  - MisnamedAxisRule   : axes incohérents (LLM-assisted)
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

from knowbase.hygiene.models import (
    HygieneAction,
    HygieneActionStatus,
    HygieneActionType,
    HygieneRunScope,
)
from knowbase.hygiene.rules.base import HygieneRule

logger = logging.getLogger("[OSMOSE] kg_hygiene_l3_axes")

# ---------------------------------------------------------------------------
# Constantes partagées
# ---------------------------------------------------------------------------

# Clés temporelles sémantiquement distinctes — ne jamais fusionner entre elles.
DISTINCT_TEMPORAL_KEYS = {
    "publication_year", "effective_year", "baseline_year", "study_year",
    "launch_year", "end_of_life_year", "sunset_year",
    "publication_date", "effective_date", "baseline_date",
}

# Clés génériques, souvent symptôme d'extraction basse qualité.
GENERIC_AXIS_KEYS = {
    "date", "temporal", "status", "type", "value", "year",
    "category", "level", "kind", "mode",
}

# Patterns pour classifier les valeurs
YEAR_PATTERN = re.compile(r"^\d{4}$")
DATE_PATTERN = re.compile(r"^\d{4}[-/]\d{2}([-/]\d{2})?$")
MONTH_NAME_PATTERN = re.compile(
    r"(?i)(january|february|march|april|may|june|july|august|"
    r"september|october|november|december|"
    r"janvier|février|mars|avril|mai|juin|juillet|août|"
    r"septembre|octobre|novembre|décembre)"
)
NUMERIC_PATTERN = re.compile(r"^[\d.,]+$")

# Familles sémantiques pour regroupement (RedundantAxisRule)
SEMANTIC_FAMILIES: Dict[str, List[str]] = {
    "temporal": ["year", "date", "temporal"],
    "version": ["version", "release", "edition"],
    "phase": ["phase", "stage"],
}

# Parallélisation LLM
MAX_LLM_WORKERS = 5
BATCH_SIZE = 10
MAX_AXES_PER_RUN = 200


# ---------------------------------------------------------------------------
# Helpers LLM (locaux, comme dans layer2_entities.py)
# ---------------------------------------------------------------------------

def _call_llm(prompt: str, max_tokens: int = 2000) -> str:
    """Appel LLM synchrone — utilisé dans les threads."""
    from knowbase.common.llm_router import get_llm_router, TaskType

    router = get_llm_router()
    return router.complete(
        task_type=TaskType.METADATA_EXTRACTION,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
    )


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


# ---------------------------------------------------------------------------
# Helpers de classification
# ---------------------------------------------------------------------------

def _normalize_axis_key(key: str) -> str:
    """Normalise une clé d'axe pour comparaison."""
    return re.sub(r"[_\-\s]+", "_", key.lower().strip())


def _is_generic_key(axis_key: str) -> bool:
    """Vérifie si la clé est générique (peu informative).

    Seules les clés courtes/exactes sont génériques.
    'publication_year' n'est PAS générique — c'est spécifique.
    """
    normalized = _normalize_axis_key(axis_key)
    # Seule la clé exacte dans le set (pas de match partiel)
    return normalized in GENERIC_AXIS_KEYS


def _classify_value(value: str) -> str:
    """Classifie une valeur : 'year', 'date', 'numeric', 'text'."""
    v = value.strip()
    if YEAR_PATTERN.match(v):
        return "year"
    if DATE_PATTERN.match(v) or MONTH_NAME_PATTERN.search(v):
        return "date"
    if NUMERIC_PATTERN.match(v):
        return "numeric"
    return "text"


def _values_same_type(values: List[str]) -> bool:
    """Vérifie si toutes les valeurs sont du même type."""
    if not values:
        return False
    types = {_classify_value(v) for v in values if v and v.strip()}
    return len(types) <= 1


def _values_are_heterogeneous(values: List[str]) -> bool:
    """Vérifie si les valeurs sont hétérogènes (mélange de types)."""
    if len(values) < 2:
        return False
    types = {_classify_value(v) for v in values if v and v.strip()}
    return len(types) >= 2


def _get_semantic_family(axis_key: str) -> Optional[str]:
    """Retourne la famille sémantique d'une clé, ou None."""
    normalized = _normalize_axis_key(axis_key)
    for family, keywords in SEMANTIC_FAMILIES.items():
        if any(kw in normalized for kw in keywords):
            return family
    return None


def _value_subset_ratio(source_values: List[str], target_values: List[str]) -> float:
    """Calcule le ratio de valeurs source contenues dans target."""
    if not source_values:
        return 1.0
    source_set = {v.strip().lower() for v in source_values if v and v.strip()}
    target_set = {v.strip().lower() for v in target_values if v and v.strip()}
    if not source_set:
        return 1.0
    overlap = source_set & target_set
    return len(overlap) / len(source_set)


def _doc_overlap_ratio(source_doc_ids: List[str], target_doc_ids: List[str]) -> float:
    """Calcule le ratio de documents source présents dans target."""
    if not source_doc_ids:
        return 1.0
    source_set = set(source_doc_ids)
    target_set = set(target_doc_ids)
    if not source_set:
        return 1.0
    overlap = source_set & target_set
    return len(overlap) / len(source_set)


# ---------------------------------------------------------------------------
# Chargement Neo4j commun
# ---------------------------------------------------------------------------

def _load_all_axes(neo4j_driver, tenant_id: str) -> List[dict]:
    """Charge tous les axes actifs (non supprimés) du tenant."""
    with neo4j_driver.session() as session:
        result = session.run(
            """
            MATCH (a:ApplicabilityAxis {tenant_id: $tid})
            WHERE a._hygiene_status IS NULL
            RETURN a.axis_id AS axis_id,
                   a.axis_key AS axis_key,
                   a.axis_display_name AS display_name,
                   a.known_values AS known_values,
                   a.doc_count AS doc_count,
                   a.source_doc_ids AS source_doc_ids,
                   a.is_orderable AS is_orderable
            """,
            tid=tenant_id,
        )
        axes = []
        for r in result:
            kv = r.get("known_values")
            if isinstance(kv, str):
                kv = [kv]
            elif kv is None:
                kv = []

            doc_ids = r.get("source_doc_ids")
            if isinstance(doc_ids, str):
                doc_ids = [doc_ids]
            elif doc_ids is None:
                doc_ids = []

            axes.append({
                "axis_id": r["axis_id"],
                "axis_key": r.get("axis_key", ""),
                "display_name": r.get("display_name", ""),
                "known_values": kv,
                "doc_count": r.get("doc_count") or 0,
                "source_doc_ids": doc_ids,
                "is_orderable": r.get("is_orderable", False),
            })
        return axes


def _count_total_axes(neo4j_driver, tenant_id: str) -> int:
    """Compte le nombre total d'axes actifs dans le tenant."""
    with neo4j_driver.session() as session:
        result = session.run(
            """
            MATCH (a:ApplicabilityAxis {tenant_id: $tid})
            WHERE a._hygiene_status IS NULL
            RETURN count(a) AS total
            """,
            tid=tenant_id,
        )
        record = result.single()
        return record["total"] if record else 0


def _load_domain_summary(neo4j_driver, tenant_id: str) -> str:
    """Charge le domain_summary depuis le DomainContext."""
    with neo4j_driver.session() as session:
        result = session.run(
            "MATCH (dc:DomainContextProfile {tenant_id: $tid}) "
            "RETURN dc.domain_summary AS ds",
            tid=tenant_id,
        )
        record = result.single()
        return record["ds"] if record and record["ds"] else ""


# ===================================================================
# Règle 1 : LowValueAxisRule
# ===================================================================

class LowValueAxisRule(HygieneRule):
    """Détecte les axes à faible valeur de navigation.

    Un axe est considéré de faible valeur si :
    - doc_count <= 1 ET len(known_values) <= 1
    - Ce n'est PAS le seul axe du tenant
    - Il ne partage aucun source_doc_id avec un autre axe de même axis_key
    - Sa clé est générique (peu informative)

    Action : PROPOSE SUPPRESS_AXIS (reason = "low_navigation_value").
    """

    @property
    def name(self) -> str:
        return "low_value_axis"

    @property
    def layer(self) -> int:
        return 3

    @property
    def description(self) -> str:
        return "Détecte les axes à faible valeur de navigation (peu de docs, peu de valeurs)"

    def scan(
        self,
        neo4j_driver,
        tenant_id: str,
        batch_id: str,
        scope: str,
        scope_params: dict | None = None,
        dry_run: bool = False,
    ) -> List[HygieneAction]:
        axes = _load_all_axes(neo4j_driver, tenant_id)
        total_axes = _count_total_axes(neo4j_driver, tenant_id)

        if total_axes <= 1:
            logger.info("  → Un seul axe dans le tenant, rien à évaluer")
            return []

        # Index par axis_key pour le guard-fou partage de docs
        axes_by_key: Dict[str, List[dict]] = defaultdict(list)
        for ax in axes:
            axes_by_key[_normalize_axis_key(ax["axis_key"])].append(ax)

        actions: List[HygieneAction] = []

        for ax in axes:
            doc_count = ax["doc_count"]
            known_values = ax["known_values"]

            # Condition de base : faible valeur
            if doc_count > 1 or len(known_values) > 1:
                continue

            axis_key_norm = _normalize_axis_key(ax["axis_key"])

            # Guard-fou 1 : pas le seul axe (déjà vérifié au-dessus)

            # Guard-fou 2 : pas de partage de source_doc_ids avec un autre axe
            # de même axis_key
            siblings = axes_by_key.get(axis_key_norm, [])
            shares_docs = False
            source_set = set(ax["source_doc_ids"])
            for sibling in siblings:
                if sibling["axis_id"] == ax["axis_id"]:
                    continue
                sibling_docs = set(sibling["source_doc_ids"])
                if source_set & sibling_docs:
                    shares_docs = True
                    break

            if shares_docs:
                continue

            # Guard-fou 3 : clé générique (si clé spécifique et informative, préserver)
            if not _is_generic_key(ax["axis_key"]):
                continue

            # Toutes les conditions remplies → proposer suppression
            action = HygieneAction(
                action_type=HygieneActionType.SUPPRESS_AXIS,
                target_node_id=ax["axis_id"],
                target_node_type="ApplicabilityAxis",
                before_state={
                    "axis_key": ax["axis_key"],
                    "display_name": ax["display_name"],
                    "known_values": known_values,
                    "doc_count": doc_count,
                    "source_doc_ids": ax["source_doc_ids"],
                },
                after_state={},
                layer=3,
                confidence=0.85,
                reason=(
                    f"low_navigation_value: axe '{ax['axis_key']}' "
                    f"(display: '{ax['display_name']}') — "
                    f"{doc_count} doc(s), {len(known_values)} valeur(s), "
                    f"clé générique sans partage documentaire"
                ),
                rule_name=self.name,
                batch_id=batch_id,
                scope=scope,
                status=HygieneActionStatus.PROPOSED,
                decision_source="rule",
                tenant_id=tenant_id,
            )
            actions.append(action)

        logger.info(
            f"  → {len(actions)} axes à faible valeur de navigation proposés "
            f"(sur {len(axes)} axes évalués)"
        )
        return actions


# ===================================================================
# Règle 2 : RedundantAxisRule
# ===================================================================

class RedundantAxisRule(HygieneRule):
    """Détecte les axes redondants candidats à fusion au sein d'une même famille.

    Pré-filtre par famille sémantique (temporal, version, phase).
    Propose MERGE uniquement si TOUTES les conditions sont remplies :
      1. known_values du même type (all years, all dates, all numeric)
      2. doc_count de la source significativement inférieur au target (ratio >= 3:1)
      3. Valeurs source sont un sous-ensemble (>=80%) du target
      4. Fort overlap de source_doc_ids (>=50%) OU source avec très peu de docs (<=2)

    Ne propose JAMAIS de merge si les clés sont dans DISTINCT_TEMPORAL_KEYS.

    Action : PROPOSE MERGE_AXIS avec after_state.merge_target_id.
    """

    # Seuils configurables
    DOC_COUNT_RATIO_MIN = 3.0
    VALUE_SUBSET_RATIO_MIN = 0.8
    DOC_OVERLAP_RATIO_MIN = 0.5
    SOURCE_FEW_DOCS_THRESHOLD = 2

    @property
    def name(self) -> str:
        return "redundant_axis"

    @property
    def layer(self) -> int:
        return 3

    @property
    def description(self) -> str:
        return "Détecte les axes redondants par famille sémantique, propose fusion"

    def scan(
        self,
        neo4j_driver,
        tenant_id: str,
        batch_id: str,
        scope: str,
        scope_params: dict | None = None,
        dry_run: bool = False,
    ) -> List[HygieneAction]:
        axes = _load_all_axes(neo4j_driver, tenant_id)

        if len(axes) < 2:
            return []

        # Grouper par famille sémantique
        families: Dict[str, List[dict]] = defaultdict(list)
        for ax in axes:
            family = _get_semantic_family(ax["axis_key"])
            if family:
                families[family].append(ax)

        actions: List[HygieneAction] = []
        merged_ids: Set[str] = set()

        for family_name, family_axes in families.items():
            if len(family_axes) < 2:
                continue

            # Trier par doc_count décroissant pour que le target soit le plus riche
            family_axes.sort(key=lambda a: a["doc_count"], reverse=True)

            for i, target in enumerate(family_axes):
                if target["axis_id"] in merged_ids:
                    continue

                for source in family_axes[i + 1:]:
                    if source["axis_id"] in merged_ids:
                        continue

                    merge_action = self._evaluate_merge(
                        source, target, batch_id, scope, tenant_id
                    )
                    if merge_action:
                        actions.append(merge_action)
                        merged_ids.add(source["axis_id"])

        logger.info(
            f"  → {len(actions)} axes redondants candidats à fusion "
            f"(familles évaluées: {list(families.keys())})"
        )
        return actions

    def _evaluate_merge(
        self,
        source: dict,
        target: dict,
        batch_id: str,
        scope: str,
        tenant_id: str,
    ) -> Optional[HygieneAction]:
        """Évalue si source doit être fusionné dans target."""
        source_key_norm = _normalize_axis_key(source["axis_key"])
        target_key_norm = _normalize_axis_key(target["axis_key"])

        # Veto : clés dans DISTINCT_TEMPORAL_KEYS et différentes
        if (
            source_key_norm in DISTINCT_TEMPORAL_KEYS
            and target_key_norm in DISTINCT_TEMPORAL_KEYS
            and source_key_norm != target_key_norm
        ):
            return None

        # Condition 1 : même type de valeurs
        source_vals = source["known_values"]
        target_vals = target["known_values"]
        if not _values_same_type(source_vals) or not _values_same_type(target_vals):
            return None
        # Les deux doivent être du même type entre eux
        if source_vals and target_vals:
            source_type = _classify_value(source_vals[0])
            target_type = _classify_value(target_vals[0])
            if source_type != target_type:
                return None

        # Condition 2 : doc_count ratio >= 3:1
        source_doc_count = max(source["doc_count"], 1)
        target_doc_count = max(target["doc_count"], 1)
        ratio = target_doc_count / source_doc_count
        if ratio < self.DOC_COUNT_RATIO_MIN:
            return None

        # Condition 3 : valeurs source sont un sous-ensemble (>=80%) du target
        subset_ratio = _value_subset_ratio(source_vals, target_vals)
        if subset_ratio < self.VALUE_SUBSET_RATIO_MIN:
            return None

        # Condition 4 : overlap de docs (>=50%) OU source a très peu de docs
        source_docs = source["source_doc_ids"]
        target_docs = target["source_doc_ids"]
        doc_overlap = _doc_overlap_ratio(source_docs, target_docs)
        few_docs = source["doc_count"] <= self.SOURCE_FEW_DOCS_THRESHOLD

        if doc_overlap < self.DOC_OVERLAP_RATIO_MIN and not few_docs:
            return None

        # Toutes les conditions remplies → proposer le merge
        return HygieneAction(
            action_type=HygieneActionType.MERGE_AXIS,
            target_node_id=source["axis_id"],
            target_node_type="ApplicabilityAxis",
            before_state={
                "source_axis_key": source["axis_key"],
                "source_display_name": source["display_name"],
                "source_known_values": source_vals,
                "source_doc_count": source["doc_count"],
                "source_doc_ids": source_docs,
                "target_axis_key": target["axis_key"],
                "target_display_name": target["display_name"],
                "target_known_values": target_vals,
                "target_doc_count": target["doc_count"],
            },
            after_state={"merge_target_id": target["axis_id"]},
            layer=3,
            confidence=0.75,
            reason=(
                f"Axe redondant: '{source['axis_key']}' "
                f"({source['doc_count']} docs, {len(source_vals)} vals) → "
                f"'{target['axis_key']}' "
                f"({target['doc_count']} docs, {len(target_vals)} vals) — "
                f"subset {subset_ratio:.0%}, doc_overlap {doc_overlap:.0%}"
            ),
            rule_name=self.name,
            batch_id=batch_id,
            scope=scope,
            status=HygieneActionStatus.PROPOSED,
            decision_source="rule",
            tenant_id=tenant_id,
        )

    def apply_action(self, neo4j_driver, action: HygieneAction) -> bool:
        """Applique un MERGE_AXIS : transfère les relations et supprime la source.

        Logique d'application (quand l'admin approuve) :
          1. Transférer les relations HAS_AXIS_VALUE du source vers le target
          2. Ajouter les known_values manquantes au target
          3. Mettre à jour doc_count et source_doc_ids du target
          4. Marquer la source comme supprimée (_hygiene_status = 'suppressed')
        """
        if action.action_type == HygieneActionType.SUPPRESS_AXIS:
            return self._apply_suppress(neo4j_driver, action)

        if action.action_type != HygieneActionType.MERGE_AXIS:
            return False

        merge_target_id = action.after_state.get("merge_target_id")
        if not merge_target_id:
            logger.error(
                f"MERGE_AXIS sans merge_target_id pour action {action.action_id}"
            )
            return False

        source_id = action.target_node_id
        now = datetime.now(timezone.utc).isoformat()

        try:
            with neo4j_driver.session() as session:
                # Étape 1 : Transférer les relations HAS_AXIS_VALUE
                session.run(
                    """
                    MATCH (source:ApplicabilityAxis {
                        axis_id: $source_id, tenant_id: $tid
                    })<-[r:HAS_AXIS_VALUE]-(dc:DocumentContext)
                    MATCH (target:ApplicabilityAxis {
                        axis_id: $target_id, tenant_id: $tid
                    })
                    WHERE NOT (dc)-[:HAS_AXIS_VALUE]->(target)
                    CREATE (dc)-[:HAS_AXIS_VALUE]->(target)
                    """,
                    source_id=source_id,
                    target_id=merge_target_id,
                    tid=action.tenant_id,
                )

                # Étape 2 + 3 : Fusionner known_values, doc_count, source_doc_ids
                session.run(
                    """
                    MATCH (source:ApplicabilityAxis {
                        axis_id: $source_id, tenant_id: $tid
                    })
                    MATCH (target:ApplicabilityAxis {
                        axis_id: $target_id, tenant_id: $tid
                    })
                    WITH source, target,
                         coalesce(source.known_values, []) AS src_vals,
                         coalesce(target.known_values, []) AS tgt_vals,
                         coalesce(source.source_doc_ids, []) AS src_docs,
                         coalesce(target.source_doc_ids, []) AS tgt_docs,
                         coalesce(source.doc_count, 0) AS src_count,
                         coalesce(target.doc_count, 0) AS tgt_count
                    SET target.known_values = apoc.coll.toSet(tgt_vals + src_vals),
                        target.source_doc_ids = apoc.coll.toSet(tgt_docs + src_docs),
                        target.doc_count = tgt_count + src_count
                    """,
                    source_id=source_id,
                    target_id=merge_target_id,
                    tid=action.tenant_id,
                )

                # Étape 4 : Supprimer les relations source et marquer comme supprimé
                session.run(
                    """
                    MATCH (source:ApplicabilityAxis {
                        axis_id: $source_id, tenant_id: $tid
                    })<-[r:HAS_AXIS_VALUE]-()
                    DELETE r
                    """,
                    source_id=source_id,
                    tid=action.tenant_id,
                )

                session.run(
                    """
                    MATCH (source:ApplicabilityAxis {
                        axis_id: $source_id, tenant_id: $tid
                    })
                    SET source._hygiene_status = 'suppressed',
                        source._hygiene_action_id = $action_id,
                        source._hygiene_rule = $rule_name,
                        source._hygiene_at = $now,
                        source._hygiene_merged_into = $target_id
                    """,
                    source_id=source_id,
                    tid=action.tenant_id,
                    action_id=action.action_id,
                    rule_name=action.rule_name,
                    now=now,
                    target_id=merge_target_id,
                )

            action.applied_at = now
            logger.info(
                f"  ✓ MERGE_AXIS appliqué : {source_id} → {merge_target_id}"
            )
            return True

        except Exception as e:
            logger.error(f"Erreur lors du MERGE_AXIS {action.action_id}: {e}")
            return False


# ===================================================================
# Règle 3 : MisnamedAxisRule (LLM-assisted)
# ===================================================================

class MisnamedAxisRule(HygieneRule):
    """Détecte les axes mal nommés ou incohérents via pré-filtre déterministe + LLM.

    Pré-filtre (déterministe — seuls les suspects passent au LLM) :
      - display_name ressemble à une valeur (contient des chiffres, une date, ou > 30 chars)
      - known_values hétérogènes (mélange années + texte libre)
      - axis_key très générique

    Le LLM évalue :
      - axis_key cohérent avec known_values ?
      - display_name = vrai label ou valeur ?
      - Valeurs homogènes ?

    Action : PROPOSE SUPPRESS_AXIS (reason = "incoherent").
    """

    @property
    def name(self) -> str:
        return "misnamed_axis"

    @property
    def layer(self) -> int:
        return 3

    @property
    def description(self) -> str:
        return "Détecte les axes mal nommés ou incohérents (pré-filtre + LLM)"

    def scan(
        self,
        neo4j_driver,
        tenant_id: str,
        batch_id: str,
        scope: str,
        scope_params: dict | None = None,
        dry_run: bool = False,
    ) -> List[HygieneAction]:
        axes = _load_all_axes(neo4j_driver, tenant_id)

        if not axes:
            return []

        # Pré-filtre déterministe : ne soumettre que les suspects au LLM
        suspects = [ax for ax in axes if self._is_suspect(ax)]

        if not suspects:
            logger.info("  → Aucun axe suspect détecté par le pré-filtre")
            return []

        # Cap pour garder un temps raisonnable
        if len(suspects) > MAX_AXES_PER_RUN:
            logger.info(
                f"  → {len(suspects)} axes suspects, cap à {MAX_AXES_PER_RUN}"
            )
            suspects = suspects[:MAX_AXES_PER_RUN]

        domain_summary = _load_domain_summary(neo4j_driver, tenant_id)

        # Évaluation LLM parallèle par batchs
        batches = [
            suspects[i:i + BATCH_SIZE]
            for i in range(0, len(suspects), BATCH_SIZE)
        ]

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
                    logger.warning(f"MisnamedAxis batch {idx} échoué: {e}")
                    results_map[idx] = [
                        {"is_incoherent": False, "confidence": 0.0, "reason": "LLM error"}
                    ] * len(batches[idx])

            for idx in range(len(batches)):
                all_evaluations.append(results_map.get(idx, []))

        # Construire les actions
        actions: List[HygieneAction] = []
        for batch, evaluations in zip(batches, all_evaluations):
            for axis, evaluation in zip(batch, evaluations):
                if not evaluation.get("is_incoherent", False):
                    continue

                confidence = evaluation.get("confidence", 0.5)

                action = HygieneAction(
                    action_type=HygieneActionType.SUPPRESS_AXIS,
                    target_node_id=axis["axis_id"],
                    target_node_type="ApplicabilityAxis",
                    before_state={
                        "axis_key": axis["axis_key"],
                        "display_name": axis["display_name"],
                        "known_values": axis["known_values"],
                        "doc_count": axis["doc_count"],
                        "source_doc_ids": axis["source_doc_ids"],
                    },
                    after_state={},
                    layer=3,
                    confidence=confidence,
                    reason=(
                        f"incoherent: {evaluation.get('reason', '')} — "
                        f"axe '{axis['axis_key']}' "
                        f"(display: '{axis['display_name']}')"
                    ),
                    rule_name=self.name,
                    batch_id=batch_id,
                    scope=scope,
                    status=HygieneActionStatus.PROPOSED,
                    decision_source="rule",
                    tenant_id=tenant_id,
                )
                actions.append(action)

        logger.info(
            f"  → {len(actions)} axes incohérents détectés "
            f"(sur {len(suspects)} suspects pré-filtrés, {len(axes)} total)"
        )
        return actions

    def _is_suspect(self, axis: dict) -> bool:
        """Pré-filtre déterministe : identifie les axes à soumettre au LLM.

        Un axe est suspect si AU MOINS UNE des conditions suivantes est vraie :
          1. display_name ressemble à une valeur (chiffres, date, > 30 chars)
          2. known_values hétérogènes
          3. axis_key très générique
        """
        display_name = axis.get("display_name", "")
        axis_key = axis.get("axis_key", "")
        known_values = axis.get("known_values", [])

        # Condition 1 : display_name ressemble à une valeur
        if display_name:
            # Contient des chiffres
            if re.search(r"\d", display_name):
                return True
            # Trop long pour être un label
            if len(display_name) > 30:
                return True
            # Ressemble à une date
            if DATE_PATTERN.match(display_name.strip()) or YEAR_PATTERN.match(display_name.strip()):
                return True

        # Condition 2 : valeurs hétérogènes
        if _values_are_heterogeneous(known_values):
            return True

        # Condition 3 : clé très générique
        if _is_generic_key(axis_key):
            return True

        return False

    def _evaluate_batch_llm(
        self, axes: List[dict], domain_summary: str
    ) -> List[dict]:
        """Évalue un batch d'axes suspects via LLM."""
        fallback = [
            {"is_incoherent": False, "confidence": 0.0, "reason": "LLM unavailable"}
        ] * len(axes)

        try:
            axes_text = "\n".join(
                f"- Axis {i + 1}: key='{a['axis_key']}', "
                f"display_name='{a.get('display_name', '')}', "
                f"known_values={a['known_values'][:15]}, "
                f"doc_count={a['doc_count']}"
                for i, a in enumerate(axes)
            )

            prompt = f"""Analyse these applicability axes from a knowledge graph.
Domain: {domain_summary or 'general'}.

For each axis, determine if it is INCOHERENT based on these criteria:
1. Is the axis_key coherent with the known_values? (e.g., key="year" but values are product names → incoherent)
2. Is the display_name a proper label, or does it look like a data value? (e.g., display_name="2024-01-15" → incoherent)
3. Are the known_values homogeneous? (e.g., mix of years and free text → incoherent)

An axis is coherent if its key, display_name and values form a logical classification facet.

Axes to evaluate:
{axes_text}

Return a JSON array with one object per axis:
[{{"axis_index": 1, "is_incoherent": true/false, "confidence": 0.0-1.0, "reason": "brief explanation"}}]

Be conservative: only mark as incoherent axes that are clearly problematic."""

            text = _call_llm(prompt, max_tokens=2000)
            results = _parse_llm_json(text)

            if len(results) == len(axes):
                return results

            logger.warning(
                f"LLM a retourné {len(results)} résultats pour "
                f"{len(axes)} axes suspects"
            )
        except Exception as e:
            logger.warning(f"Évaluation LLM MisnamedAxis échouée: {e}")

        return fallback
