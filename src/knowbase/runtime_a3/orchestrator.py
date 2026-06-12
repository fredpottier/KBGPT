"""Orchestrator runtime A3 — Parse → Plan → Execute → Evaluate → Synthesize.

Cf ADR_PARSE_EVALUATE_RUNTIME §2.1-§2.5 + §2.9 (hard caps).

Boucle :
    iter=0 : parse → plan → execute → evaluate
    Si verdict=AMBIGUOUS ET iter<2 ET re_plan_hint != "none" :
        applique re_plan_hint → modifie parse/plan → re-execute → re-evaluate
    iter=1 : idem, mais hard cap §2.9 (Evaluator force CORRECT/INSUFFICIENT)
    Fin → synthesize

Re-plan hint mapping (§2.4) :
    - broaden_subject       → strip qualifiers, garder racine entity
    - add_qdrant_fallback   → ajouter ToolCall qdrant_sections sur sub_goals empty
    - decompose_comparison  → kind='comparison' → kind='fact_lookup'
    - check_lifecycle       → ajouter ToolCall lifecycle_query
    - narrow_time_filter    → time_filter → 'current'
    - drop_overspecific_filters → predicate_hint=None, object_hint=None
    - none                  → terminate sans re-plan

Hard caps (§2.9) :
    - max 2 iterations
    - max 5 sub_goals (déjà borné par Pydantic)
    - max 60s wall-clock (timeout total surveillé)

Domain-agnostic strict : aucune logique corpus-spécifique. La transformation
broaden_subject utilise une heuristique générale (drop trailing token).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from knowbase.runtime_a3.evaluate import Evaluator, evaluate as evaluate_step
from knowbase.runtime_a3.execute import Executor, execute as execute_step
from knowbase.runtime_a3.parse import Parser, parse as parse_step
from knowbase.runtime_a3.plan import TOOL_TIMEOUTS, plan as plan_step
from knowbase.runtime_a3.schemas import (
    EvaluateOutput,
    ExecuteOutput,
    ParseInput,
    ParseOutput,
    PlanOutput,
    RePlanHint,
    ResponseMode,
    SubGoal,
    SynthesizeOutput,
    ToolCall,
)
from knowbase.runtime_a3.synthesize import (
    Synthesizer,
    synthesize as synthesize_step,
)

logger = logging.getLogger("knowbase.runtime_a3.orchestrator")


# Hard caps (cf ADR §2.9)
MAX_ITERATIONS = 2
MAX_WALL_CLOCK_S = 180.0  # A4.14 — était 60s. Trop bas pour Parse Qwen3-235B retries (15-30s) + Synthesize DeepSeek-V3.1 sur 50 claims (30-90s).


# ============================================================================
# Helpers — modification ParseOutput/PlanOutput selon hint
# ============================================================================


def _broaden_subject(subject: str) -> str:
    """Élargit un subject_canonical pour re-plan (heuristique domain-agnostic).

    Stratégie progressive (un seul niveau d'élargissement par appel) :
        1. Si présence de qualifiers entre parenthèses ou après virgule :
           strip ceux-ci. "Product X (v2024), Edition Pro" → "Product X".
        2. Sinon (pas de qualifier), drop le dernier token :
           "Product X v2024" → "Product X" ; "Product X" → "Product".
        3. Si 1 seul token, inchangé.

    Garantie : sortie ⊆ entrée (substring). Pas de néologisme.
    """
    stripped = subject.split(" (")[0].split(",")[0].strip()
    if stripped != subject:
        return stripped  # le stripping a déjà élargi → 1 niveau suffit
    parts = stripped.split()
    if len(parts) >= 2:
        return " ".join(parts[:-1])
    return stripped


def _modify_sub_goals_for_hint(
    hint: RePlanHint,
    parse_output: ParseOutput,
    affected_indices: List[int],
) -> ParseOutput:
    """Retourne un ParseOutput modifié selon le hint (immutable copy)."""
    if hint == "none":
        return parse_output

    new_sub_goals: List[SubGoal] = list(parse_output.sub_goals)
    affected = [i for i in affected_indices if 0 <= i < len(new_sub_goals)]

    for idx in affected:
        sg = new_sub_goals[idx]

        if hint == "broaden_subject":
            if sg.subject_canonical:
                new_sub_goals[idx] = sg.model_copy(update={
                    "subject_canonical": _broaden_subject(sg.subject_canonical),
                })

        elif hint == "narrow_time_filter":
            if sg.time_filter != "current":
                new_sub_goals[idx] = sg.model_copy(update={"time_filter": "current"})

        elif hint == "drop_overspecific_filters":
            new_sub_goals[idx] = sg.model_copy(update={
                "predicate_hint": None,
                "object_hint": None,
            })

        elif hint == "decompose_comparison":
            if sg.kind == "comparison":
                new_sub_goals[idx] = sg.model_copy(update={"kind": "fact_lookup"})

        # Les hints add_qdrant_fallback et check_lifecycle ne modifient PAS les
        # sub_goals — ils ajoutent des ToolCall (cf _augment_plan_for_hint).

    return parse_output.model_copy(update={"sub_goals": new_sub_goals})


def _augment_plan_for_hint(
    hint: RePlanHint,
    new_plan: PlanOutput,
    new_parse: ParseOutput,
    parse_input: ParseInput,
    affected_indices: List[int],
) -> PlanOutput:
    """Ajoute des ToolCall supplémentaires au plan selon le hint.

    Ne modifie PAS new_plan.tool_calls existants — ajoute uniquement.
    """
    affected = [i for i in affected_indices if 0 <= i < len(new_parse.sub_goals)]
    extra_calls: List[ToolCall] = []

    if hint == "add_qdrant_fallback":
        # Un qdrant_sections par sub_goal uncovered (dédup par idx)
        for idx in affected:
            already_qdrant = any(
                tc.sub_goal_idx == idx and tc.tool == "qdrant_sections"
                for tc in new_plan.tool_calls
            )
            if already_qdrant:
                continue
            extra_calls.append(ToolCall(
                sub_goal_idx=idx,
                tool="qdrant_sections",
                params={
                    "query": new_parse.raw_question,
                    "tenant_id": parse_input.tenant_id,
                    "limit": 20,
                    "score_threshold": 0.5,
                },
                timeout_s=TOOL_TIMEOUTS["qdrant_sections"],
            ))

    elif hint == "check_lifecycle":
        # Un lifecycle_query par sub_goal uncovered (si subject présent)
        for idx in affected:
            sg = new_parse.sub_goals[idx]
            if not sg.subject_canonical:
                continue
            already_lc = any(
                tc.sub_goal_idx == idx and tc.tool == "lifecycle_query"
                for tc in new_plan.tool_calls
            )
            if already_lc:
                continue
            extra_calls.append(ToolCall(
                sub_goal_idx=idx,
                tool="lifecycle_query",
                params={
                    "subject": sg.subject_canonical,
                    "tenant_id": parse_input.tenant_id,
                },
                timeout_s=TOOL_TIMEOUTS["lifecycle_query"],
            ))

    if not extra_calls:
        return new_plan

    return new_plan.model_copy(update={
        "tool_calls": list(new_plan.tool_calls) + extra_calls,
    })


def apply_re_plan_hint(
    hint: RePlanHint,
    parse_output: ParseOutput,
    plan_output: PlanOutput,
    evaluate_output: EvaluateOutput,
    parse_input: ParseInput,
) -> Tuple[ParseOutput, PlanOutput]:
    """Applique un re_plan_hint et retourne le couple (parse, plan) modifié.

    1. Modifie ParseOutput.sub_goals selon le hint (si applicable)
    2. Re-plan complet avec le nouveau ParseOutput
    3. Pour add_qdrant_fallback / check_lifecycle : augmente le plan avec des
       ToolCall supplémentaires
    """
    if hint == "none":
        return parse_output, plan_output

    affected = evaluate_output.uncovered_sub_goals
    new_parse = _modify_sub_goals_for_hint(hint, parse_output, affected)
    new_plan = plan_step(parse_input, new_parse)
    new_plan = _augment_plan_for_hint(hint, new_plan, new_parse, parse_input, affected)
    return new_parse, new_plan


# ============================================================================
# Trace structure (pour observability + bench A3.8)
# ============================================================================


class IterationTrace:
    """Trace d'une itération Plan/Execute/Evaluate (1 itération)."""

    def __init__(
        self,
        iteration: int,
        parse_output: ParseOutput,
        plan_output: PlanOutput,
        execute_output: ExecuteOutput,
        evaluate_output: EvaluateOutput,
        duration_s: float,
        re_plan_hint_applied: Optional[RePlanHint] = None,
    ):
        self.iteration = iteration
        self.parse_output = parse_output
        self.plan_output = plan_output
        self.execute_output = execute_output
        self.evaluate_output = evaluate_output
        self.duration_s = duration_s
        self.re_plan_hint_applied = re_plan_hint_applied

    def to_dict(self) -> Dict[str, Any]:
        return {
            "iteration": self.iteration,
            "duration_s": self.duration_s,
            "n_sub_goals": len(self.parse_output.sub_goals),
            "n_tool_calls": len(self.plan_output.tool_calls),
            "n_unmappable": len(self.plan_output.unmappable_sub_goals),
            "n_results": len(self.execute_output.results),
            "verdict": self.evaluate_output.verdict,
            "re_plan_hint": self.evaluate_output.re_plan_hint,
            "re_plan_hint_applied": self.re_plan_hint_applied,
            "covered_sub_goals": self.evaluate_output.covered_sub_goals,
            "uncovered_sub_goals": self.evaluate_output.uncovered_sub_goals,
            "evaluate_confidence": self.evaluate_output.confidence,
            "evaluate_reasoning": self.evaluate_output.reasoning,
        }


class OrchestratorResult:
    """Résultat complet d'une question (réponse + trace)."""

    def __init__(
        self,
        synthesize_output: SynthesizeOutput,
        iterations: List[IterationTrace],
        total_duration_s: float,
        terminated_reason: str,
    ):
        self.synthesize_output = synthesize_output
        self.iterations = iterations
        self.total_duration_s = total_duration_s
        self.terminated_reason = terminated_reason

    def to_dict(self) -> Dict[str, Any]:
        return {
            "answer": self.synthesize_output.model_dump(),
            "iterations": [it.to_dict() for it in self.iterations],
            "total_duration_s": self.total_duration_s,
            "terminated_reason": self.terminated_reason,
            "n_iterations": len(self.iterations),
        }


# ============================================================================
# Orchestrator
# ============================================================================


class Orchestrator:
    """Coordonne Parse → Plan → Execute → Evaluate → Synthesize.

    Injection de toutes les dépendances pour testabilité (par défaut: production
    via llm_router + neo4j_client + qdrant + embedder).
    """

    def __init__(
        self,
        parser: Optional[Parser] = None,
        executor: Optional[Executor] = None,
        evaluator: Optional[Evaluator] = None,
        synthesizer: Optional[Synthesizer] = None,
        max_iterations: int = MAX_ITERATIONS,
        max_wall_clock_s: float = MAX_WALL_CLOCK_S,
    ):
        self._parser = parser
        self._executor = executor
        self._evaluator = evaluator
        self._synthesizer = synthesizer
        self._max_iterations = max_iterations
        self._max_wall_clock_s = max_wall_clock_s
        self._log_runtime_config()

    @staticmethod
    def _log_runtime_config() -> None:
        """P2.1 (23/05/2026) — log config retrieval/LLM/toggles en init Orchestrator.

        Anti-épisode A4.15 : on a découvert que V6_HYBRID_RETRIEVAL n'était jamais
        positionné côté env (défaut "0" silencieux) alors qu'on croyait bencher en RRF.
        Ce log rend la config visible dès le démarrage du pipeline runtime_v6.
        """
        import os as _os
        config = {
            "V6_HYBRID_RETRIEVAL": _os.getenv("V6_HYBRID_RETRIEVAL", "0"),
            "V6_HYBRID_QUERY_MODE": _os.getenv("V6_HYBRID_QUERY_MODE", "question"),
            "V6_QDRANT_CASCADE": _os.getenv("V6_QDRANT_CASCADE", "0"),
            "V6_CROSS_ENCODER_RERANK": _os.getenv("V6_CROSS_ENCODER_RERANK", "0"),
            "V6_CE_RERANK_MODEL": _os.getenv("V6_CE_RERANK_MODEL", "(unset)"),
            "V6_PARSE_LLM_DEEPSEEK": _os.getenv("V6_PARSE_LLM_DEEPSEEK", "0"),
            "V6_CLAIM_FILTER_ENABLED": _os.getenv("V6_CLAIM_FILTER_ENABLED", "1"),
            "MAX_WALL_CLOCK_S": MAX_WALL_CLOCK_S,
            "MAX_ITERATIONS": MAX_ITERATIONS,
        }
        logger.info("[RUNTIME_V6_CONFIG] %s", json.dumps(config, ensure_ascii=False))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        question: str,
        tenant_id: str = "default",
        as_of_date: Optional[datetime] = None,
        response_mode: ResponseMode = "structured",
    ) -> OrchestratorResult:
        """Exécute le pipeline complet sur une question."""
        t0 = time.perf_counter()
        parse_input = ParseInput(
            question=question,
            tenant_id=tenant_id,
            as_of_date=as_of_date,
        )

        # 1. PARSE (1 fois, indépendant des iterations)
        parse_output = self._do_parse(parse_input)

        iterations_trace: List[IterationTrace] = []
        current_parse = parse_output
        current_plan: Optional[PlanOutput] = None
        current_execute: Optional[ExecuteOutput] = None
        current_evaluate: Optional[EvaluateOutput] = None
        last_hint_applied: Optional[RePlanHint] = None
        # Pour add_qdrant_fallback / check_lifecycle : l'augmentation du plan
        # est différée à l'itération suivante (après que plan_step est rejoué
        # sur le ParseOutput modifié).
        pending_augment_hint: Optional[RePlanHint] = None
        pending_augment_uncovered: List[int] = []
        terminated_reason = "max_iterations_reached"

        for iteration in range(self._max_iterations):
            iter_t0 = time.perf_counter()

            # Guard wall-clock (avant de lancer une nouvelle itération)
            elapsed = time.perf_counter() - t0
            if elapsed >= self._max_wall_clock_s:
                terminated_reason = "wall_clock_timeout"
                logger.warning(
                    "orchestrator: wall-clock timeout (%.1fs) at iter=%d",
                    elapsed, iteration,
                )
                break

            # 2. PLAN
            current_plan = plan_step(parse_input, current_parse)

            # 2.bis Augmentation différée (add_qdrant_fallback / check_lifecycle)
            if pending_augment_hint is not None:
                current_plan = _augment_plan_for_hint(
                    pending_augment_hint,
                    current_plan,
                    current_parse,
                    parse_input,
                    pending_augment_uncovered,
                )
                pending_augment_hint = None
                pending_augment_uncovered = []

            # 3. EXECUTE
            current_execute = execute_step(
                parse_input, current_parse, current_plan,
                executor=self._executor,
            )

            # 3.bis Gate de couverture KB-aligned (remédiation 1c) — ABSTENTION DURE.
            # Si le cross-encoder juge la question non couverte par le corpus, on
            # abstient SANS re-plan : le fallback qdrant ne ferait que ré-halluciner sur
            # du hors-corpus (corrige le sur-answering sans sujet ET I7 sujet-présent).
            if getattr(current_execute, "coverage_gate_uncovered", False):
                current_evaluate = EvaluateOutput(
                    verdict="INSUFFICIENT_EVIDENCE",
                    covered_sub_goals=[],
                    uncovered_sub_goals=list(range(len(current_parse.sub_goals))),
                    re_plan_hint="none",
                    confidence=0.9,
                    reasoning="coverage_gate: le corpus ne couvre pas la question (cross-encoder sous le seuil).",
                )
                iterations_trace.append(IterationTrace(
                    iteration=iteration,
                    parse_output=current_parse,
                    plan_output=current_plan,
                    execute_output=current_execute,
                    evaluate_output=current_evaluate,
                    duration_s=time.perf_counter() - iter_t0,
                    re_plan_hint_applied=last_hint_applied,
                ))
                terminated_reason = "coverage_gate_uncovered"
                break

            # 4. EVALUATE
            current_evaluate = evaluate_step(
                current_parse, current_plan, current_execute,
                iteration=iteration,
                evaluator=self._evaluator,
            )

            iter_duration = time.perf_counter() - iter_t0
            iterations_trace.append(IterationTrace(
                iteration=iteration,
                parse_output=current_parse,
                plan_output=current_plan,
                execute_output=current_execute,
                evaluate_output=current_evaluate,
                duration_s=iter_duration,
                re_plan_hint_applied=last_hint_applied,
            ))

            # 5. Décision : continue ou stop ?
            verdict = current_evaluate.verdict
            hint = current_evaluate.re_plan_hint
            is_last_iter = iteration >= self._max_iterations - 1

            if verdict in ("CORRECT", "INSUFFICIENT_EVIDENCE"):
                terminated_reason = f"verdict_{verdict.lower()}"
                break

            if verdict == "AMBIGUOUS":
                if is_last_iter:
                    # Hard cap §2.9 — l'Evaluator devrait avoir forcé CORRECT/
                    # INSUFFICIENT en iter≥1 ; si AMBIGUOUS persiste, on termine
                    # quand même.
                    terminated_reason = "ambiguous_at_hard_cap"
                    logger.warning(
                        "orchestrator: AMBIGUOUS at hard cap iter=%d, terminating",
                        iteration,
                    )
                    break

                if hint == "none":
                    terminated_reason = "ambiguous_no_useful_hint"
                    break

                # Re-plan avec le hint
                logger.info(
                    "orchestrator: re-plan iter=%d→%d hint=%s",
                    iteration, iteration + 1, hint,
                )
                # 1) Appliquer modifications sub_goals (broaden_subject,
                #    narrow_time_filter, drop_overspecific_filters,
                #    decompose_comparison)
                current_parse = _modify_sub_goals_for_hint(
                    hint, current_parse, current_evaluate.uncovered_sub_goals,
                )
                # 2) Pour les hints d'augmentation de plan (add_qdrant_fallback,
                #    check_lifecycle), différer l'ajout des ToolCall à l'itération
                #    suivante (après que plan_step est ré-exécuté)
                if hint in ("add_qdrant_fallback", "check_lifecycle"):
                    pending_augment_hint = hint
                    pending_augment_uncovered = list(
                        current_evaluate.uncovered_sub_goals
                    )
                last_hint_applied = hint
                continue

            # Cas non-prévu (verdict inconnu) — terminate
            terminated_reason = f"unknown_verdict_{verdict}"
            break

        # 6. SYNTHESIZE (toujours, même si erreur)
        if current_evaluate is None:
            # Cas dégénéré : on n'a pas exécuté une seule itération (ex: timeout
            # immédiat). Synthesize un ABSTENTION minimal.
            synth_output = self._build_emergency_abstention(parse_output)
        else:
            synth_output = synthesize_step(
                parse_output if current_parse is None else current_parse,
                current_execute,
                current_evaluate,
                response_mode=response_mode,
                synthesizer=self._synthesizer,
            )

        total_duration = time.perf_counter() - t0
        return OrchestratorResult(
            synthesize_output=synth_output,
            iterations=iterations_trace,
            total_duration_s=total_duration,
            terminated_reason=terminated_reason,
        )

    # ------------------------------------------------------------------
    # Step wrappers
    # ------------------------------------------------------------------

    def _do_parse(self, parse_input: ParseInput) -> ParseOutput:
        if self._parser is not None:
            return self._parser.parse(parse_input)
        return parse_step(parse_input)

    # ------------------------------------------------------------------
    # Fallback emergency
    # ------------------------------------------------------------------

    def _build_emergency_abstention(self, parse_output: ParseOutput) -> SynthesizeOutput:
        """Cas dégénéré : pas même 1 itération exécutée → abstention sans claims."""
        return SynthesizeOutput(
            answer_text=(
                "Unable to process the question (timeout or internal error). "
                "Please retry or rephrase."
            ),
            cited_claims=[],
            uncovered_sub_goals_warning="All sub_goals uncovered (pipeline error).",
            conflict_pending_warning=None,
            mode="ABSTENTION",
            synthesize_warnings=["emergency_abstention_no_iteration_executed"],
            citation_coverage_rate=1.0,
            schema_version="a3.0",
        )


# ============================================================================
# Top-level API
# ============================================================================


def run_question(
    question: str,
    tenant_id: str = "default",
    as_of_date: Optional[datetime] = None,
    response_mode: ResponseMode = "structured",
    orchestrator: Optional[Orchestrator] = None,
) -> OrchestratorResult:
    """API top-level pour exécuter une question."""
    orch = orchestrator or Orchestrator()
    return orch.run(question, tenant_id, as_of_date, response_mode)
