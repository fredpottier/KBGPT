"""Gold set A3.4-bis — 50 cas synthétiques labellisés pour bench Evaluator.

Cf ADR_PARSE_EVALUATE_RUNTIME §2.4 + §7.3 (gate GA3-2 ≥85%).

Stratification :
    - 12 CORRECT (4 trivial + 4 medium + 4 edge)
    - 13 AMBIGUOUS (5 trivial + 5 medium + 3 edge)
    - 12 INCORRECT (4 trivial + 4 medium + 4 edge)
    - 13 INSUFFICIENT_EVIDENCE (5 trivial + 5 medium + 3 edge)

Domain-agnostic strict : entités placeholder X/Y/Z/alpha/beta — aucun token
SAP/aerospace/médical/légal. La validité du label tient aux signaux structurels
(coverage_signal, iteration, parse_confidence) — pas au domaine sémantique.

Difficulté :
    - trivial = règle ADR §3.2 directement applicable (le fallback déterministe
      devrait passer)
    - medium = mix coverage + 2+ sub_goals, nécessite agrégation
    - edge = piégeux (low confidence + claims, partial+iter0 avec hint pertinent,
      errors partielles, ConflictPending sur sub_goal)

Note annotation : ces cas sont rédigés par le designer du module (Claude). Pour
mesurer Cohen's kappa ≥0.7 (ADR §7.3 protocole), un 2ème annotateur (humain ou
LLM externe) devrait reviewer indépendamment. À faire en post-A3.4-bis si gate
fragile (< 90%).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from knowbase.runtime_a3.schemas import (
    ClaimSummary,
    ConflictPendingSummary,
    ExecuteOutput,
    ParseOutput,
    PlanOutput,
    SubGoal,
    SubGoalKind,
    ToolResult,
)


# ============================================================================
# Helpers de construction (concis)
# ============================================================================


def _sg(
    kind: SubGoalKind,
    subject: Optional[str] = "X",
    predicate: Optional[str] = None,
    priority: int = 1,
    time_filter: str = "current",
) -> SubGoal:
    return SubGoal(
        kind=kind,
        subject_canonical=subject,
        predicate_hint=predicate,
        priority=priority,
        time_filter=time_filter,
    )


def _po(
    sub_goals: List[SubGoal],
    parse_confidence: float = 0.9,
    warnings: Optional[List[str]] = None,
) -> ParseOutput:
    return ParseOutput(
        sub_goals=sub_goals,
        entities=[sg.subject_canonical for sg in sub_goals if sg.subject_canonical],
        language="en",
        raw_question="test",
        parse_confidence=parse_confidence,
        parse_warnings=warnings or [],
        schema_version="a3.0",
    )


def _plo() -> PlanOutput:
    return PlanOutput(
        tool_calls=[],
        unmappable_sub_goals=[],
        plan_warnings=[],
        schema_version="a3.0",
    )


def _tr(
    sub_goal_idx: int = 0,
    n_claims: int = 0,
    coverage: str = "empty",
    tool: str = "kg_claims",
    error: Optional[str] = None,
    n_cp: int = 0,
) -> ToolResult:
    claims = [ClaimSummary(claim_id=f"c_{sub_goal_idx}_{i}") for i in range(n_claims)]
    cps = [
        ConflictPendingSummary(
            conflict_id=f"cp_{sub_goal_idx}_{i}",
            resolution_status="unresolved",
            involved_claim_ids=[c.claim_id for c in claims[: 2]],
            reason="value_divergence",
        )
        for i in range(n_cp)
    ]
    return ToolResult(
        sub_goal_idx=sub_goal_idx,
        tool=tool,
        claims=claims,
        coverage_signal=coverage,
        conflict_pendings=cps,
        duration_s=0.01,
        error=error,
    )


def _eo(results: List[ToolResult]) -> ExecuteOutput:
    return ExecuteOutput(results=results, total_duration_s=0.05, schema_version="a3.0")


def _case(
    cid: str,
    category: str,
    diff: str,
    description: str,
    parse_output: ParseOutput,
    execute_output: ExecuteOutput,
    iteration: int = 0,
    expected_verdict: str = "CORRECT",
    annotator_confidence: float = 0.9,
) -> Dict[str, Any]:
    return {
        "id": cid,
        "category": category,
        "difficulty": diff,
        "description": description,
        "parse_output": parse_output,
        "plan_output": _plo(),
        "execute_output": execute_output,
        "iteration": iteration,
        "expected_verdict": expected_verdict,
        "annotator_confidence": annotator_confidence,
    }


# ============================================================================
# Builder
# ============================================================================


def build_gold_set() -> List[Dict[str, Any]]:
    """Retourne les 50 cas du gold set, ordre stable."""
    cases: List[Dict[str, Any]] = []

    # ========================================================================
    # CORRECT × 12 (4 trivial + 4 medium + 4 edge)
    # ========================================================================

    # --- CORRECT trivial ---
    cases.append(_case(
        cid="GA3-2_001", category="CORRECT", diff="trivial",
        description="Single sub_goal full coverage (n=5 claims).",
        parse_output=_po([_sg("fact_lookup", "X", "p1")]),
        execute_output=_eo([_tr(0, n_claims=5, coverage="full")]),
        expected_verdict="CORRECT",
    ))
    cases.append(_case(
        cid="GA3-2_002", category="CORRECT", diff="trivial",
        description="Two sub_goals both full.",
        parse_output=_po([_sg("fact_lookup", "X"), _sg("fact_lookup", "Y")]),
        execute_output=_eo([
            _tr(0, n_claims=4, coverage="full"),
            _tr(1, n_claims=3, coverage="full"),
        ]),
        expected_verdict="CORRECT",
    ))
    cases.append(_case(
        cid="GA3-2_003", category="CORRECT", diff="trivial",
        description="Definition_lookup full coverage.",
        parse_output=_po([_sg("definition_lookup", "alpha")]),
        execute_output=_eo([_tr(0, n_claims=6, coverage="full")]),
        expected_verdict="CORRECT",
    ))
    cases.append(_case(
        cid="GA3-2_004", category="CORRECT", diff="trivial",
        description="Contradiction_check full with relations traced.",
        parse_output=_po([_sg("contradiction_check", "Z")]),
        execute_output=_eo([_tr(0, n_claims=4, coverage="full",
                                tool="contradiction_surface")]),
        expected_verdict="CORRECT",
    ))

    # --- CORRECT medium ---
    cases.append(_case(
        cid="GA3-2_005", category="CORRECT", diff="medium",
        description="Three sub_goals all full from different tools.",
        parse_output=_po([
            _sg("fact_lookup", "X"), _sg("list_enumeration", "Y"),
            _sg("lifecycle_trace", "Z"),
        ]),
        execute_output=_eo([
            _tr(0, n_claims=3, coverage="full", tool="kg_claims"),
            _tr(1, n_claims=8, coverage="full", tool="kg_claims_list"),
            _tr(2, n_claims=4, coverage="full", tool="lifecycle_query"),
        ]),
        expected_verdict="CORRECT",
    ))
    cases.append(_case(
        cid="GA3-2_006", category="CORRECT", diff="medium",
        description="P1 + P2 sub_goals, both full (different thresholds).",
        parse_output=_po([
            _sg("fact_lookup", "X", priority=1),
            _sg("fact_lookup", "Y", priority=2),
        ]),
        execute_output=_eo([
            _tr(0, n_claims=3, coverage="full"),
            _tr(1, n_claims=1, coverage="full"),  # P2 → 1 claim suffit
        ]),
        expected_verdict="CORRECT",
    ))
    cases.append(_case(
        cid="GA3-2_007", category="CORRECT", diff="medium",
        description="Comparison: 2 kg_claims tool_calls both full.",
        parse_output=_po([_sg("comparison", "A"), _sg("comparison", "B")]),
        execute_output=_eo([
            _tr(0, n_claims=4, coverage="full"),
            _tr(1, n_claims=3, coverage="full"),
        ]),
        expected_verdict="CORRECT",
    ))
    cases.append(_case(
        cid="GA3-2_008", category="CORRECT", diff="medium",
        description="Single sub_goal full with ConflictPending — still CORRECT (synth exposes).",
        parse_output=_po([_sg("fact_lookup", "X")]),
        execute_output=_eo([_tr(0, n_claims=4, coverage="full", n_cp=1)]),
        expected_verdict="CORRECT",
    ))

    # --- CORRECT edge ---
    cases.append(_case(
        cid="GA3-2_009", category="CORRECT", diff="edge",
        description="Iter=1 partial coverage → hard cap forces CORRECT with warning.",
        parse_output=_po([_sg("fact_lookup", "X"), _sg("fact_lookup", "Y")]),
        execute_output=_eo([
            _tr(0, n_claims=4, coverage="full"),
            _tr(1, n_claims=1, coverage="partial"),
        ]),
        iteration=1,
        expected_verdict="CORRECT",
        annotator_confidence=0.85,
    ))
    cases.append(_case(
        cid="GA3-2_010", category="CORRECT", diff="edge",
        description="Multiple tools for same sub_goal — best coverage wins.",
        parse_output=_po([_sg("fact_lookup", "X")]),
        execute_output=_eo([
            _tr(0, n_claims=1, coverage="partial", tool="kg_claims"),
            _tr(0, n_claims=3, coverage="full", tool="qdrant_sections"),
        ]),
        expected_verdict="CORRECT",
        annotator_confidence=0.85,
    ))
    cases.append(_case(
        cid="GA3-2_011", category="CORRECT", diff="edge",
        description="Iter=2 with mostly full + 1 empty → CORRECT (hard cap §2.9).",
        parse_output=_po([
            _sg("fact_lookup", "X"), _sg("fact_lookup", "Y"),
            _sg("fact_lookup", "Z"),
        ]),
        execute_output=_eo([
            _tr(0, n_claims=4, coverage="full"),
            _tr(1, n_claims=3, coverage="full"),
            _tr(2, n_claims=0, coverage="empty"),
        ]),
        iteration=2,
        expected_verdict="CORRECT",
        annotator_confidence=0.8,
    ))
    cases.append(_case(
        cid="GA3-2_012", category="CORRECT", diff="edge",
        description="Sub_goal P2 enrichissement empty mais P1 full → CORRECT (P2 dispensable).",
        parse_output=_po([
            _sg("fact_lookup", "X", priority=1),
            _sg("fact_lookup", "Y", priority=2),
        ]),
        execute_output=_eo([
            _tr(0, n_claims=5, coverage="full"),
            _tr(1, n_claims=0, coverage="empty"),
        ]),
        iteration=1,  # iter=1 pour forcer CORRECT (sinon AMBIGUOUS au iter=0)
        expected_verdict="CORRECT",
        annotator_confidence=0.75,  # cas piégeux
    ))

    # ========================================================================
    # AMBIGUOUS × 13 (5 trivial + 5 medium + 3 edge)
    # ========================================================================

    # --- AMBIGUOUS trivial ---
    cases.append(_case(
        cid="GA3-2_013", category="AMBIGUOUS", diff="trivial",
        description="Single sub_goal empty at iter=0 — re-plan via qdrant.",
        parse_output=_po([_sg("fact_lookup", "X")]),
        execute_output=_eo([_tr(0, n_claims=0, coverage="empty")]),
        iteration=0,
        expected_verdict="AMBIGUOUS",
    ))
    cases.append(_case(
        cid="GA3-2_014", category="AMBIGUOUS", diff="trivial",
        description="Single sub_goal partial at iter=0 — re-plan.",
        parse_output=_po([_sg("fact_lookup", "X")]),
        execute_output=_eo([_tr(0, n_claims=2, coverage="partial")]),
        iteration=0,
        expected_verdict="AMBIGUOUS",
    ))
    cases.append(_case(
        cid="GA3-2_015", category="AMBIGUOUS", diff="trivial",
        description="Two sub_goals — one full + one empty at iter=0.",
        parse_output=_po([_sg("fact_lookup", "X"), _sg("fact_lookup", "Y")]),
        execute_output=_eo([
            _tr(0, n_claims=4, coverage="full"),
            _tr(1, n_claims=0, coverage="empty"),
        ]),
        iteration=0,
        expected_verdict="AMBIGUOUS",
    ))
    cases.append(_case(
        cid="GA3-2_016", category="AMBIGUOUS", diff="trivial",
        description="Two sub_goals — both empty at iter=0 with subjects → qdrant retry.",
        parse_output=_po([_sg("fact_lookup", "X"), _sg("fact_lookup", "Y")]),
        execute_output=_eo([
            _tr(0, n_claims=0, coverage="empty"),
            _tr(1, n_claims=0, coverage="empty"),
        ]),
        iteration=0,
        expected_verdict="AMBIGUOUS",
    ))
    cases.append(_case(
        cid="GA3-2_017", category="AMBIGUOUS", diff="trivial",
        description="Comparison sub_goals both empty iter=0 → decompose hint.",
        parse_output=_po([_sg("comparison", "A"), _sg("comparison", "B")]),
        execute_output=_eo([
            _tr(0, n_claims=0, coverage="empty"),
            _tr(1, n_claims=0, coverage="empty"),
        ]),
        iteration=0,
        expected_verdict="AMBIGUOUS",
    ))

    # --- AMBIGUOUS medium ---
    cases.append(_case(
        cid="GA3-2_018", category="AMBIGUOUS", diff="medium",
        description="3 sub_goals: 1 full + 1 partial + 1 empty at iter=0.",
        parse_output=_po([
            _sg("fact_lookup", "X"), _sg("fact_lookup", "Y"),
            _sg("fact_lookup", "Z"),
        ]),
        execute_output=_eo([
            _tr(0, n_claims=3, coverage="full"),
            _tr(1, n_claims=1, coverage="partial"),
            _tr(2, n_claims=0, coverage="empty"),
        ]),
        iteration=0,
        expected_verdict="AMBIGUOUS",
    ))
    cases.append(_case(
        cid="GA3-2_019", category="AMBIGUOUS", diff="medium",
        description="Lifecycle sub_goal empty iter=0 → narrow_time_filter hint.",
        parse_output=_po([_sg("lifecycle_trace", "X", time_filter="evolution")]),
        execute_output=_eo([_tr(0, n_claims=0, coverage="empty",
                                tool="lifecycle_query")]),
        iteration=0,
        expected_verdict="AMBIGUOUS",
    ))
    cases.append(_case(
        cid="GA3-2_020", category="AMBIGUOUS", diff="medium",
        description="Mixed comparison+factual, all partial iter=0.",
        parse_output=_po([_sg("comparison", "A"), _sg("comparison", "B")]),
        execute_output=_eo([
            _tr(0, n_claims=2, coverage="partial"),
            _tr(1, n_claims=1, coverage="partial"),
        ]),
        iteration=0,
        expected_verdict="AMBIGUOUS",
    ))
    cases.append(_case(
        cid="GA3-2_021", category="AMBIGUOUS", diff="medium",
        description="All sub_goals partial iter=0.",
        parse_output=_po([_sg("fact_lookup", "X"), _sg("fact_lookup", "Y")]),
        execute_output=_eo([
            _tr(0, n_claims=2, coverage="partial"),
            _tr(1, n_claims=1, coverage="partial"),
        ]),
        iteration=0,
        expected_verdict="AMBIGUOUS",
    ))
    cases.append(_case(
        cid="GA3-2_022", category="AMBIGUOUS", diff="medium",
        description="List_enumeration partial iter=0.",
        parse_output=_po([_sg("list_enumeration", "X", "contains")]),
        execute_output=_eo([_tr(0, n_claims=2, coverage="partial",
                                tool="kg_claims_list")]),
        iteration=0,
        expected_verdict="AMBIGUOUS",
    ))

    # --- AMBIGUOUS edge ---
    cases.append(_case(
        cid="GA3-2_023", category="AMBIGUOUS", diff="edge",
        description="Many partials no full iter=0 — re-plan beneficial.",
        parse_output=_po([
            _sg("fact_lookup", "X"), _sg("fact_lookup", "Y"),
            _sg("fact_lookup", "Z"),
        ]),
        execute_output=_eo([
            _tr(0, n_claims=1, coverage="partial"),
            _tr(1, n_claims=2, coverage="partial"),
            _tr(2, n_claims=1, coverage="partial"),
        ]),
        iteration=0,
        expected_verdict="AMBIGUOUS",
        annotator_confidence=0.85,
    ))
    cases.append(_case(
        cid="GA3-2_024", category="AMBIGUOUS", diff="edge",
        description="Empty + ConflictPending on sub_goal sibling iter=0.",
        parse_output=_po([_sg("fact_lookup", "X"), _sg("fact_lookup", "Y")]),
        execute_output=_eo([
            _tr(0, n_claims=2, coverage="partial", n_cp=2),
            _tr(1, n_claims=0, coverage="empty"),
        ]),
        iteration=0,
        expected_verdict="AMBIGUOUS",
        annotator_confidence=0.8,
    ))
    cases.append(_case(
        cid="GA3-2_025", category="AMBIGUOUS", diff="edge",
        description="Empty + iteration=0 — even with low (not<0.3) parse confidence.",
        parse_output=_po([_sg("fact_lookup", "X")], parse_confidence=0.45),
        execute_output=_eo([_tr(0, n_claims=0, coverage="empty")]),
        iteration=0,
        expected_verdict="AMBIGUOUS",
        annotator_confidence=0.75,
    ))

    # ========================================================================
    # INCORRECT × 12 (4 trivial + 4 medium + 4 edge)
    # ========================================================================
    #
    # INCORRECT = "evidence contradicts the sub_goals OR no evidence is relevant"
    # Difficile à distinguer d'AMBIGUOUS sans context sémantique. Pour le
    # fallback DÉTERMINISTE, ces cas sont quasi-impossibles à classer comme
    # INCORRECT (faute de signal structurel). On les ANNOTE INCORRECT et c'est
    # le LLM qui doit les attraper. Le fallback déterministe est attendu de
    # les classer en AMBIGUOUS/CORRECT/INSUFFICIENT (erreur prévue).

    # --- INCORRECT trivial ---
    cases.append(_case(
        cid="GA3-2_026", category="INCORRECT", diff="trivial",
        description="Results pertain to wrong subject (LLM-only detectable).",
        parse_output=_po([_sg("fact_lookup", "alpha", "property_p")]),
        execute_output=_eo([_tr(0, n_claims=3, coverage="full")]),
        iteration=0,
        expected_verdict="INCORRECT",
        annotator_confidence=0.7,  # sémantique, fallback va dire CORRECT
    ))
    cases.append(_case(
        cid="GA3-2_027", category="INCORRECT", diff="trivial",
        description="Contradictory claims without ConflictPending detected.",
        parse_output=_po([_sg("fact_lookup", "X")]),
        execute_output=_eo([_tr(0, n_claims=4, coverage="full")]),
        iteration=0,
        expected_verdict="INCORRECT",
        annotator_confidence=0.65,
    ))
    cases.append(_case(
        cid="GA3-2_028", category="INCORRECT", diff="trivial",
        description="Tool returned irrelevant claims (subject mismatch).",
        parse_output=_po([_sg("fact_lookup", "beta")]),
        execute_output=_eo([_tr(0, n_claims=3, coverage="full")]),
        iteration=0,
        expected_verdict="INCORRECT",
        annotator_confidence=0.7,
    ))
    cases.append(_case(
        cid="GA3-2_029", category="INCORRECT", diff="trivial",
        description="Comparison returned claims for only one side (asymmetry).",
        parse_output=_po([_sg("comparison", "A"), _sg("comparison", "B")]),
        execute_output=_eo([
            _tr(0, n_claims=5, coverage="full"),
            _tr(1, n_claims=0, coverage="empty"),
        ]),
        iteration=1,  # iter=1 pour exclure AMBIGUOUS-via-re-plan
        expected_verdict="INCORRECT",
        annotator_confidence=0.65,
    ))

    # --- INCORRECT medium ---
    cases.append(_case(
        cid="GA3-2_030", category="INCORRECT", diff="medium",
        description="Lifecycle trace returns unrelated entities.",
        parse_output=_po([_sg("lifecycle_trace", "X", time_filter="evolution")]),
        execute_output=_eo([_tr(0, n_claims=6, coverage="full",
                                tool="lifecycle_query")]),
        iteration=0,
        expected_verdict="INCORRECT",
        annotator_confidence=0.6,
    ))
    cases.append(_case(
        cid="GA3-2_031", category="INCORRECT", diff="medium",
        description="Definition lookup returns wrong concept.",
        parse_output=_po([_sg("definition_lookup", "alpha")]),
        execute_output=_eo([_tr(0, n_claims=2, coverage="partial")]),
        iteration=1,
        expected_verdict="INCORRECT",
        annotator_confidence=0.6,
    ))
    cases.append(_case(
        cid="GA3-2_032", category="INCORRECT", diff="medium",
        description="Contradictions surface returned with wrong subject scope.",
        parse_output=_po([_sg("contradiction_check", "Z")]),
        execute_output=_eo([_tr(0, n_claims=4, coverage="full",
                                tool="contradiction_surface")]),
        iteration=0,
        expected_verdict="INCORRECT",
        annotator_confidence=0.55,
    ))
    cases.append(_case(
        cid="GA3-2_033", category="INCORRECT", diff="medium",
        description="List returned items but none match the implicit filter in question.",
        parse_output=_po([_sg("list_enumeration", "X", "supports")]),
        execute_output=_eo([_tr(0, n_claims=8, coverage="full",
                                tool="kg_claims_list")]),
        iteration=0,
        expected_verdict="INCORRECT",
        annotator_confidence=0.55,
    ))

    # --- INCORRECT edge ---
    cases.append(_case(
        cid="GA3-2_034", category="INCORRECT", diff="edge",
        description="Full coverage but tool used was inappropriate (sub_goal kind mismatch).",
        parse_output=_po([_sg("comparison", "A"), _sg("comparison", "B")]),
        execute_output=_eo([
            _tr(0, n_claims=3, coverage="full"),
            _tr(1, n_claims=4, coverage="full"),
        ]),
        iteration=0,
        expected_verdict="INCORRECT",  # claims sur sujet correct mais comparison non agrégée
        annotator_confidence=0.5,
    ))
    cases.append(_case(
        cid="GA3-2_035", category="INCORRECT", diff="edge",
        description="High coverage + many ConflictPending unresolved on critical predicate.",
        parse_output=_po([_sg("fact_lookup", "X", "critical_p")]),
        execute_output=_eo([_tr(0, n_claims=4, coverage="full", n_cp=3)]),
        iteration=0,
        expected_verdict="INCORRECT",
        annotator_confidence=0.5,  # cas sensible
    ))
    cases.append(_case(
        cid="GA3-2_036", category="INCORRECT", diff="edge",
        description="Iter=2 final with mostly wrong-direction evidence.",
        parse_output=_po([_sg("fact_lookup", "X")]),
        execute_output=_eo([_tr(0, n_claims=2, coverage="partial")]),
        iteration=2,
        expected_verdict="INCORRECT",
        annotator_confidence=0.55,
    ))
    cases.append(_case(
        cid="GA3-2_037", category="INCORRECT", diff="edge",
        description="Tool returned semantically opposite to what subject implies.",
        parse_output=_po([_sg("fact_lookup", "X", "is_enabled")]),
        execute_output=_eo([_tr(0, n_claims=3, coverage="full")]),
        iteration=0,
        expected_verdict="INCORRECT",
        annotator_confidence=0.55,
    ))

    # ========================================================================
    # INSUFFICIENT_EVIDENCE × 13 (5 trivial + 5 medium + 3 edge)
    # ========================================================================

    # --- INSUFFICIENT trivial ---
    cases.append(_case(
        cid="GA3-2_038", category="INSUFFICIENT_EVIDENCE", diff="trivial",
        description="Parse confidence very low (<0.3).",
        parse_output=_po([_sg("fact_lookup", "X")], parse_confidence=0.15,
                        warnings=["out_of_scope_for_corpus"]),
        execute_output=_eo([_tr(0, n_claims=0, coverage="empty")]),
        iteration=0,
        expected_verdict="INSUFFICIENT_EVIDENCE",
    ))
    cases.append(_case(
        cid="GA3-2_039", category="INSUFFICIENT_EVIDENCE", diff="trivial",
        description="No sub_goals at all (Parse returned empty).",
        parse_output=_po([], parse_confidence=0.2),
        execute_output=_eo([]),
        iteration=0,
        expected_verdict="INSUFFICIENT_EVIDENCE",
    ))
    cases.append(_case(
        cid="GA3-2_040", category="INSUFFICIENT_EVIDENCE", diff="trivial",
        description="All empty at iter=1 (already re-planned).",
        parse_output=_po([_sg("fact_lookup", "X")]),
        execute_output=_eo([_tr(0, n_claims=0, coverage="empty")]),
        iteration=1,
        expected_verdict="INSUFFICIENT_EVIDENCE",
    ))
    cases.append(_case(
        cid="GA3-2_041", category="INSUFFICIENT_EVIDENCE", diff="trivial",
        description="All tools returned errors (Neo4j down).",
        parse_output=_po([_sg("fact_lookup", "X")]),
        execute_output=_eo([_tr(0, error="Connection lost", coverage="empty")]),
        iteration=0,
        expected_verdict="INSUFFICIENT_EVIDENCE",
    ))
    cases.append(_case(
        cid="GA3-2_042", category="INSUFFICIENT_EVIDENCE", diff="trivial",
        description="Two sub_goals both empty at iter=1.",
        parse_output=_po([_sg("fact_lookup", "X"), _sg("fact_lookup", "Y")]),
        execute_output=_eo([
            _tr(0, n_claims=0, coverage="empty"),
            _tr(1, n_claims=0, coverage="empty"),
        ]),
        iteration=1,
        expected_verdict="INSUFFICIENT_EVIDENCE",
    ))

    # --- INSUFFICIENT medium ---
    cases.append(_case(
        cid="GA3-2_043", category="INSUFFICIENT_EVIDENCE", diff="medium",
        description="Parse confidence 0.25 + multi-tool errors.",
        parse_output=_po([_sg("fact_lookup", "X")], parse_confidence=0.25),
        execute_output=_eo([
            _tr(0, error="Timeout", coverage="empty"),
            _tr(0, error="DB error", coverage="empty", tool="qdrant_sections"),
        ]),
        iteration=0,
        expected_verdict="INSUFFICIENT_EVIDENCE",
    ))
    cases.append(_case(
        cid="GA3-2_044", category="INSUFFICIENT_EVIDENCE", diff="medium",
        description="3 sub_goals all empty at iter=2.",
        parse_output=_po([
            _sg("fact_lookup", "X"), _sg("fact_lookup", "Y"),
            _sg("fact_lookup", "Z"),
        ]),
        execute_output=_eo([
            _tr(0, n_claims=0, coverage="empty"),
            _tr(1, n_claims=0, coverage="empty"),
            _tr(2, n_claims=0, coverage="empty"),
        ]),
        iteration=2,
        expected_verdict="INSUFFICIENT_EVIDENCE",
    ))
    cases.append(_case(
        cid="GA3-2_045", category="INSUFFICIENT_EVIDENCE", diff="medium",
        description="Parse warned out_of_scope + confidence borderline 0.28.",
        parse_output=_po([_sg("fact_lookup", "X")], parse_confidence=0.28,
                        warnings=["out_of_scope_for_corpus"]),
        execute_output=_eo([_tr(0, n_claims=0, coverage="empty")]),
        iteration=0,
        expected_verdict="INSUFFICIENT_EVIDENCE",
    ))
    cases.append(_case(
        cid="GA3-2_046", category="INSUFFICIENT_EVIDENCE", diff="medium",
        description="Multi sub_goals errors mix at iter=1.",
        parse_output=_po([_sg("fact_lookup", "X"), _sg("fact_lookup", "Y")]),
        execute_output=_eo([
            _tr(0, error="Boom", coverage="empty"),
            _tr(1, error="Crash", coverage="empty"),
        ]),
        iteration=1,
        expected_verdict="INSUFFICIENT_EVIDENCE",
    ))
    cases.append(_case(
        cid="GA3-2_047", category="INSUFFICIENT_EVIDENCE", diff="medium",
        description="Empty sub_goals without subject (cannot retry) at iter=0.",
        parse_output=_po([_sg("fact_lookup", subject=None, predicate="p")]),
        execute_output=_eo([_tr(0, n_claims=0, coverage="empty")]),
        iteration=0,
        expected_verdict="INSUFFICIENT_EVIDENCE",
    ))

    # --- INSUFFICIENT edge ---
    cases.append(_case(
        cid="GA3-2_048", category="INSUFFICIENT_EVIDENCE", diff="edge",
        description="Iter=0 all empty but parse_confidence high — fallback ambiguous "
                    "but the right answer is to abstain (corpus genuinely silent).",
        parse_output=_po([_sg("fact_lookup", "X")], parse_confidence=0.85),
        execute_output=_eo([_tr(0, n_claims=0, coverage="empty")]),
        iteration=1,  # iter=1 pour signaler 1 re-plan déjà essayé
        expected_verdict="INSUFFICIENT_EVIDENCE",
        annotator_confidence=0.85,
    ))
    cases.append(_case(
        cid="GA3-2_049", category="INSUFFICIENT_EVIDENCE", diff="edge",
        description="Parse confidence 0.29 (just under threshold) with claims found.",
        parse_output=_po([_sg("fact_lookup", "X")], parse_confidence=0.29),
        execute_output=_eo([_tr(0, n_claims=2, coverage="partial")]),
        iteration=0,
        expected_verdict="INSUFFICIENT_EVIDENCE",
        annotator_confidence=0.7,  # cas piégeux : parse low → abstention même avec claims
    ))
    cases.append(_case(
        cid="GA3-2_050", category="INSUFFICIENT_EVIDENCE", diff="edge",
        description="All errors at iter=0 — re-plan likely useless.",
        parse_output=_po([_sg("fact_lookup", "X"), _sg("fact_lookup", "Y")]),
        execute_output=_eo([
            _tr(0, error="Network", coverage="empty"),
            _tr(1, error="Network", coverage="empty"),
        ]),
        iteration=0,
        expected_verdict="INSUFFICIENT_EVIDENCE",
        annotator_confidence=0.75,
    ))

    return cases


# ============================================================================
# Validations (sanity check au load)
# ============================================================================


def validate_gold_set(cases: List[Dict[str, Any]]) -> None:
    """Sanity checks au moment du chargement.

    Vérifie :
        - 50 cas exactement
        - Distribution : 12 CORRECT / 13 AMBIGUOUS / 12 INCORRECT / 13 INSUFFICIENT
        - IDs uniques
        - Difficulté ∈ {trivial, medium, edge}
        - expected_verdict ∈ verdicts valides
    """
    assert len(cases) == 50, f"Expected 50 cases, got {len(cases)}"

    cat_counts: Dict[str, int] = {}
    diff_counts: Dict[str, int] = {}
    ids_seen = set()
    valid_verdicts = {"CORRECT", "AMBIGUOUS", "INCORRECT", "INSUFFICIENT_EVIDENCE"}
    valid_diffs = {"trivial", "medium", "edge"}

    for case in cases:
        assert case["id"] not in ids_seen, f"Duplicate id: {case['id']}"
        ids_seen.add(case["id"])
        assert case["expected_verdict"] in valid_verdicts, \
            f"{case['id']} invalid verdict {case['expected_verdict']}"
        assert case["difficulty"] in valid_diffs, \
            f"{case['id']} invalid difficulty {case['difficulty']}"
        cat_counts[case["category"]] = cat_counts.get(case["category"], 0) + 1
        diff_counts[case["difficulty"]] = diff_counts.get(case["difficulty"], 0) + 1

    assert cat_counts == {
        "CORRECT": 12,
        "AMBIGUOUS": 13,
        "INCORRECT": 12,
        "INSUFFICIENT_EVIDENCE": 13,
    }, f"Bad category distribution: {cat_counts}"
