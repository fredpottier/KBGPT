"""Module Plan — mapping déterministe sub_goal → tool (cf ADR §2.2 + §4).

100% déterministe : table de correspondance `sub_goal.kind → ToolName` + builders
de paramètres Cypher/Qdrant. **AUCUN LLM** dans ce module.

Si un sub_goal est inmappable (ex: pas de subject pour kg_claims), il est marqué
dans `unmappable_sub_goals` et l'Evaluate décidera (fallback Qdrant ou abstention).

Domain-agnostic : aucun token / regex / mapping spécifique à un corpus métier.
Le mapping est universel sur les types abstraits de sub_goals.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from knowbase.runtime_a3.schemas import (
    ParseInput,
    ParseOutput,
    PlanOutput,
    SubGoal,
    SubGoalKind,
    ToolCall,
    ToolName,
)

logger = logging.getLogger("knowbase.runtime_a3.plan")


# ============================================================================
# Mapping kind → tool (table de correspondance fixe, cf ADR §2.2)
# ============================================================================


# Mapping principal. NB: lifecycle_trace passe par lifecycle_query quel que soit
# le time_filter (le tool retourne déjà la timeline). Pour comparison, on génère
# 2× kg_claims via le tool composite comparison_query.
KIND_TO_TOOL: Dict[SubGoalKind, ToolName] = {
    "fact_lookup": "kg_claims",
    "definition_lookup": "kg_claims",
    "list_enumeration": "kg_claims_list",
    "lifecycle_trace": "lifecycle_query",
    "contradiction_check": "contradiction_surface",
    "comparison": "comparison_query",
}

# Timeouts par tool (cf §2.9 hard caps — 60s pour le pipeline total)
TOOL_TIMEOUTS: Dict[ToolName, float] = {
    "kg_claims": 8.0,
    "kg_claims_list": 12.0,
    "lifecycle_query": 15.0,
    "contradiction_surface": 10.0,
    "comparison_query": 18.0,
    "qdrant_sections": 6.0,
}


# ============================================================================
# Planner
# ============================================================================


class Planner:
    """Construit un PlanOutput à partir d'un ParseOutput.

    Toujours déterministe — aucun appel externe.
    """

    def plan(
        self,
        parse_input: ParseInput,
        parse_output: ParseOutput,
    ) -> PlanOutput:
        """Mappe chaque sub_goal à un ToolCall (ou marque inmappable)."""
        tool_calls: List[ToolCall] = []
        unmappable: List[int] = []
        warnings: List[str] = []

        as_of = self._resolve_as_of(parse_input)

        for idx, sub_goal in enumerate(parse_output.sub_goals):
            mapped_calls, unmappable_reason = self._map_sub_goal(
                idx=idx,
                sub_goal=sub_goal,
                tenant_id=parse_input.tenant_id,
                as_of=as_of,
            )
            if unmappable_reason is not None:
                unmappable.append(idx)
                warnings.append(f"sub_goal_{idx}_unmappable:{unmappable_reason}")
                logger.debug(
                    "plan: sub_goal %d (%s) unmappable: %s",
                    idx, sub_goal.kind, unmappable_reason,
                )
                continue
            tool_calls.extend(mapped_calls)

        # Cas extrême : aucun sub_goal mappable ET parse a produit ≥1 sub_goal
        # → on ajoute un qdrant_sections de fallback sur la question brute
        if not tool_calls and parse_output.sub_goals:
            tool_calls.append(self._build_qdrant_fallback(
                question=parse_output.raw_question,
                tenant_id=parse_input.tenant_id,
                sub_goal_idx=0,  # rattaché au premier sub_goal par convention
            ))
            warnings.append("all_sub_goals_unmappable_qdrant_fallback_added")

        return PlanOutput(
            tool_calls=tool_calls,
            unmappable_sub_goals=unmappable,
            plan_warnings=warnings,
            schema_version="a3.0",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_as_of(self, parse_input: ParseInput) -> datetime:
        """Résout la date as_of (point-in-time) pour les filtres bitemporels."""
        if parse_input.as_of_date is not None:
            return parse_input.as_of_date
        return datetime.now(timezone.utc)

    def _map_sub_goal(
        self,
        idx: int,
        sub_goal: SubGoal,
        tenant_id: str,
        as_of: datetime,
    ) -> Tuple[List[ToolCall], Optional[str]]:
        """Mappe un sub_goal à 1+ ToolCall.

        Returns:
            (tool_calls, unmappable_reason)
            - Si mappable : (list_of_tool_calls, None)
            - Si pas mappable : ([], "raison")
        """
        tool_name = KIND_TO_TOOL.get(sub_goal.kind)
        if tool_name is None:
            return [], f"unknown_kind:{sub_goal.kind}"

        # Routage par tool name (chaque tool a ses contraintes sur les params)
        if tool_name == "kg_claims":
            return self._build_kg_claims(idx, sub_goal, tenant_id, as_of)
        if tool_name == "kg_claims_list":
            return self._build_kg_claims_list(idx, sub_goal, tenant_id, as_of)
        if tool_name == "lifecycle_query":
            return self._build_lifecycle_query(idx, sub_goal, tenant_id, as_of)
        if tool_name == "contradiction_surface":
            return self._build_contradiction_surface(idx, sub_goal, tenant_id, as_of)
        if tool_name == "comparison_query":
            return self._build_comparison_query(idx, sub_goal, tenant_id, as_of)

        # Tool inconnu (ne devrait pas arriver — Literal exhaustif)
        return [], f"unsupported_tool:{tool_name}"

    # ------------------------------------------------------------------
    # Builders par tool
    # ------------------------------------------------------------------

    def _build_kg_claims(
        self,
        idx: int,
        sub_goal: SubGoal,
        tenant_id: str,
        as_of: datetime,
    ) -> Tuple[List[ToolCall], Optional[str]]:
        """Build ToolCall pour kg_claims (fact_lookup, definition_lookup)."""
        # A4.9-bis (23/05/2026) : en mode hybride, subject=None est toléré car
        # Execute.kg_claims utilise BM25/vector sur claim.text sans filtre exact subject.
        # En mode legacy, subject=None reste unmappable (filtre Cypher strict).
        #
        # Chemin « global » (question sans sujet-ancre, ex « y a-t-il un niveau
        # d'alcool sans risque ? »). DÉSACTIVÉ PAR DÉFAUT (baseline sûre = abstention).
        # Raison (revue archi 12/06) : élargir le retrieval aux questions sans sujet
        # rouvre l'over-answering sur les questions HORS-corpus (e5 discrimine mal),
        # ce qui contredit l'abstention calibrée (cœur produit). Réactivation UNIQUEMENT
        # via le routage d'intention (chantier remédiation, étape 1c) avec le toggle
        # dédié `V6_GLOBAL_SUBJECTLESS=1` — jamais en global sans garde-fou.
        import os as _os
        global_subjectless = _os.getenv("V6_GLOBAL_SUBJECTLESS", "0") == "1"
        if not sub_goal.subject_canonical and not global_subjectless:
            return [], "missing_subject_for_kg_claims"

        params: Dict = {
            "subject": sub_goal.subject_canonical,
            "predicate": sub_goal.predicate_hint,  # peut être None — query gère
            "as_of": as_of.date().isoformat(),
            "tenant_id": tenant_id,
        }
        return [
            ToolCall(
                sub_goal_idx=idx,
                tool="kg_claims",
                params=params,
                timeout_s=TOOL_TIMEOUTS["kg_claims"],
            )
        ], None

    def _build_kg_claims_list(
        self,
        idx: int,
        sub_goal: SubGoal,
        tenant_id: str,
        as_of: datetime,
    ) -> Tuple[List[ToolCall], Optional[str]]:
        """Build ToolCall pour kg_claims_list (list_enumeration).

        Note: subject_canonical PEUT être None (cf ADR §4.2 : `$subject_filter IS NULL`
        permet de lister tous les claims sur un predicate donné, voire tout le KG).
        En revanche on exige au moins l'un des deux (subject_canonical ou predicate_hint)
        pour éviter de matériel un cartésien sur tout le KG.
        """
        # P3.1 (28/05/2026) — en mode hybride, le retrieval list_enumeration passe
        # par BM25/vector sur claim.text (la question pilote la requête), donc
        # subject/predicate vides sont tolérés. En legacy (exact-match), on exige
        # toujours au moins l'un des deux pour éviter un balayage de tout le KG.
        import os as _os
        hybrid_mode = _os.getenv("V6_HYBRID_RETRIEVAL", "0") != "0"
        if not sub_goal.subject_canonical and not sub_goal.predicate_hint and not hybrid_mode:
            return [], "missing_subject_and_predicate_for_kg_claims_list"

        params: Dict = {
            "subject_filter": sub_goal.subject_canonical,
            "predicate": sub_goal.predicate_hint,
            "as_of": as_of.date().isoformat(),
            "tenant_id": tenant_id,
        }
        return [
            ToolCall(
                sub_goal_idx=idx,
                tool="kg_claims_list",
                params=params,
                timeout_s=TOOL_TIMEOUTS["kg_claims_list"],
            )
        ], None

    def _build_lifecycle_query(
        self,
        idx: int,
        sub_goal: SubGoal,
        tenant_id: str,
        as_of: datetime,
    ) -> Tuple[List[ToolCall], Optional[str]]:
        """Build ToolCall pour lifecycle_query.

        Exige subject_canonical car le tool fait MATCH centré sur le subject.
        """
        if not sub_goal.subject_canonical:
            return [], "missing_subject_for_lifecycle_query"

        params: Dict = {
            "subject": sub_goal.subject_canonical,
            "tenant_id": tenant_id,
            # PAS de as_of ici (cf §4.3) — lifecycle retourne TOUTES les versions
        }
        return [
            ToolCall(
                sub_goal_idx=idx,
                tool="lifecycle_query",
                params=params,
                timeout_s=TOOL_TIMEOUTS["lifecycle_query"],
            )
        ], None

    def _build_contradiction_surface(
        self,
        idx: int,
        sub_goal: SubGoal,
        tenant_id: str,
        as_of: datetime,
    ) -> Tuple[List[ToolCall], Optional[str]]:
        """Build ToolCall pour contradiction_surface."""
        if not sub_goal.subject_canonical:
            return [], "missing_subject_for_contradiction_surface"

        params: Dict = {
            "subject": sub_goal.subject_canonical,
            "tenant_id": tenant_id,
            "as_of": as_of.date().isoformat(),
        }
        return [
            ToolCall(
                sub_goal_idx=idx,
                tool="contradiction_surface",
                params=params,
                timeout_s=TOOL_TIMEOUTS["contradiction_surface"],
            )
        ], None

    def _build_comparison_query(
        self,
        idx: int,
        sub_goal: SubGoal,
        tenant_id: str,
        as_of: datetime,
    ) -> Tuple[List[ToolCall], Optional[str]]:
        """Build ToolCall pour comparison_query.

        ATTENTION : comparison nécessite 2 sub_goals jumeaux (subject_a et subject_b)
        OU peut être réalisé via 1 sub_goal si Parse a inscrit les 2 entités dans
        un object_hint (rare). Convention pour A3 : on s'attend à 2 sub_goals.

        Si le LLM Parse a généré 2 sub_goals comparison consécutifs (cas standard),
        c'est traité comme 2× kg_claims indépendants par le mapping global. Ce
        builder est appelé pour chaque sub_goal individuellement et émet 1 kg_claims.

        Si jamais subject_canonical et object_hint encodent les 2 entités,
        ce builder n'est PAS adapté (pas de support v1.0).
        """
        if not sub_goal.subject_canonical:
            return [], "missing_subject_for_comparison_query"

        # Convention v1.0 : chaque sub_goal comparison devient 1× kg_claims.
        # Le diff structuré sera réalisé en Evaluate / Synthesize (déterministe).
        params: Dict = {
            "subject": sub_goal.subject_canonical,
            "predicate": sub_goal.predicate_hint,
            "as_of": as_of.date().isoformat(),
            "tenant_id": tenant_id,
        }
        return [
            ToolCall(
                sub_goal_idx=idx,
                tool="kg_claims",
                params=params,
                timeout_s=TOOL_TIMEOUTS["kg_claims"],
            )
        ], None

    def _build_qdrant_fallback(
        self,
        question: str,
        tenant_id: str,
        sub_goal_idx: int,
    ) -> ToolCall:
        """Build un ToolCall qdrant_sections de fallback (cf §2.6)."""
        return ToolCall(
            sub_goal_idx=sub_goal_idx,
            tool="qdrant_sections",
            params={
                "query": question,
                "tenant_id": tenant_id,
                "limit": 20,
                "score_threshold": 0.5,
            },
            timeout_s=TOOL_TIMEOUTS["qdrant_sections"],
        )


# ============================================================================
# Top-level API
# ============================================================================


def plan(
    parse_input: ParseInput,
    parse_output: ParseOutput,
) -> PlanOutput:
    """API top-level (cf ADR §2.2)."""
    return Planner().plan(parse_input, parse_output)
