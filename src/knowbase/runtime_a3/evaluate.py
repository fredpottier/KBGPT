"""Module Evaluate — verdict 4-classes (LLM #2, cf ADR §2.4 + §3.2).

Lightweight ~200-500 tokens d'input + JSON output validé Pydantic.

Verdict ∈ {CORRECT, AMBIGUOUS, INCORRECT, INSUFFICIENT_EVIDENCE}.
re_plan_hint ∈ vocabulaire contrôlé Literal (cf schemas.py).

Stratégie :
    1. Construire un user prompt minimaliste sérialisant sub_goals + résultats agrégés
    2. Appeler LLM via llm_router (TaskType.FAST_CLASSIFICATION ou KNOWLEDGE_EXTRACTION)
    3. Parse JSON, validate Pydantic (Literal types stricts)
    4. Retry 2× sur échec
    5. Fallback déterministe basé sur règles ADR §3.2 si LLM down

Le fallback déterministe est CRITIQUE pour la disponibilité production : il garantit
qu'on retourne toujours un verdict sensé, même sans LLM.

Domain-agnostic : pas de token corpus-spécifique dans prompt ni fallback.
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from knowbase.runtime_a3.schemas import (
    EvaluateError,
    EvaluateInput,
    EvaluateOutput,
    ExecuteOutput,
    ParseOutput,
    PlanOutput,
    RePlanHint,
    SubGoal,
    ToolResult,
    Verdict,
)

logger = logging.getLogger("knowbase.runtime_a3.evaluate")


# ============================================================================
# System prompt (cf ADR §3.2)
# ============================================================================


_SYSTEM_PROMPT_BASE = """You are a result evaluator for a knowledge graph runtime.

Given a user's sub-goals and the aggregated tool results, decide if the system has
enough evidence to answer.

OUTPUT JSON ONLY (no markdown, no commentary). Schema:
{
  "verdict": "CORRECT" | "AMBIGUOUS" | "INCORRECT" | "INSUFFICIENT_EVIDENCE",
  "covered_sub_goals": [<int idx>],
  "uncovered_sub_goals": [<int idx>],
  "re_plan_hint": "broaden_subject" | "add_qdrant_fallback" | "decompose_comparison" | "check_lifecycle" | "narrow_time_filter" | "drop_overspecific_filters" | "none",
  "confidence": 0.0..1.0,
  "reasoning": "<40-80 words>",
  "schema_version": "a3.0"
}

VERDICTS:
- CORRECT: every sub_goal has >=1 relevant claim. ConflictPending presence is OK
  (the synthesizer will expose them transparently).
- AMBIGUOUS: partial coverage OR multiple plausible answers — re-plan can help.
- INCORRECT: results contradict the sub_goals OR no evidence is relevant.
- INSUFFICIENT_EVIDENCE: tools returned almost nothing AND re-plan unlikely to help.

RULES:
- A ConflictPending on a sub_goal subject is NOT automatically AMBIGUOUS. Mark CORRECT
  and let synthesizer expose the conflict transparently.
- If iteration >= 1 and you already re-planned once, DO NOT mark AMBIGUOUS again — force
  a verdict between CORRECT, INCORRECT, INSUFFICIENT_EVIDENCE.
- Coverage signal "empty" on a priority-1 sub_goal + no fallback hint -> INSUFFICIENT_EVIDENCE.
- Coverage signal "partial" + iteration == 0 -> AMBIGUOUS (re-plan).
- Coverage signal "partial" + iteration >= 1 -> CORRECT (with warning).

Be precise and brief. The synthesizer takes care of style.

"""


@lru_cache(maxsize=1)
def _load_examples() -> List[Dict[str, Any]]:
    """Charge les few-shot examples (cf ADR §3.2.1)."""
    path = Path(__file__).parent / "prompts" / "evaluate_examples.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _format_example_block(idx: int, example: Dict[str, Any]) -> str:
    return (
        f"### Example {idx + 1} — {example.get('case', '')}\n"
        f"INPUT SUMMARY: {example['input_summary']}\n"
        f"OUTPUT:\n{json.dumps(example['expected'], ensure_ascii=False, indent=2)}\n"
    )


@lru_cache(maxsize=1)
def _build_system_prompt() -> str:
    """Assemble base prompt + few-shot examples (cached)."""
    examples = _load_examples()
    parts = [_SYSTEM_PROMPT_BASE, "## EXAMPLES\n"]
    for i, ex in enumerate(examples):
        parts.append(_format_example_block(i, ex))
    return "\n".join(parts)


# ============================================================================
# Helpers de sérialisation
# ============================================================================


def _serialize_input(inp: EvaluateInput) -> str:
    """Construit le user prompt à envoyer au LLM (compact)."""
    sub_goals_desc = []
    for idx, sg in enumerate(inp.parse_output.sub_goals):
        sub_goals_desc.append({
            "idx": idx,
            "kind": sg.kind,
            "subject": sg.subject_canonical,
            "predicate": sg.predicate_hint,
            "priority": sg.priority,
            "time_filter": sg.time_filter,
        })

    # Aggrège results par sub_goal_idx
    by_sub_goal: Dict[int, List[ToolResult]] = {}
    for r in inp.execute_output.results:
        by_sub_goal.setdefault(r.sub_goal_idx, []).append(r)

    results_desc = []
    for idx in range(len(inp.parse_output.sub_goals)):
        tool_summaries = []
        for r in by_sub_goal.get(idx, []):
            tool_summaries.append({
                "tool": r.tool,
                "n_claims": len(r.claims),
                "n_sections": len(r.sections),
                "n_conflict_pendings": len(r.conflict_pendings),
                "coverage_signal": r.coverage_signal,
                "error": r.error,
            })
        results_desc.append({
            "sub_goal_idx": idx,
            "tools": tool_summaries,
        })

    payload = {
        "parse_confidence": inp.parse_output.parse_confidence,
        "parse_warnings": inp.parse_output.parse_warnings,
        "sub_goals": sub_goals_desc,
        "unmappable_sub_goals": inp.plan_output.unmappable_sub_goals,
        "results_per_sub_goal": results_desc,
        "iteration": inp.iteration,
    }
    return (
        "USER INPUT (JSON):\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n\nRespond with JSON only."
    )


_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.DOTALL)


def _strip_markdown_fences(text: str) -> str:
    m = _JSON_BLOCK_RE.search(text)
    return m.group(1).strip() if m else text.strip()


# ============================================================================
# Evaluator
# ============================================================================


class Evaluator:
    """Construit un EvaluateOutput à partir d'un EvaluateInput.

    Dependency injection :
        - `llm_client` : objet exposant `.complete(system, user) -> str`
          En production, on utilise `llm_router` via TaskType. En test, mock.
    """

    def __init__(self, llm_client: Any = None, max_retries: int = 2):
        self._llm_client = llm_client
        self._max_retries = max_retries

    def _get_llm_client(self):
        if self._llm_client is None:
            from knowbase.common.llm_router import LLMRouter, TaskType

            class _RouterClient:
                def __init__(self):
                    self._router = LLMRouter()

                def complete(self, system: str, user: str) -> str:
                    return self._router.complete(
                        task_type=TaskType.FAST_CLASSIFICATION,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        temperature=0.0,
                        max_tokens=600,
                    )
            self._llm_client = _RouterClient()
        return self._llm_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self, inp: EvaluateInput) -> EvaluateOutput:
        """Retourne un EvaluateOutput valide (LLM ou fallback déterministe)."""
        # Court-circuit : aucun sub_goal → INSUFFICIENT direct, pas besoin de LLM
        if not inp.parse_output.sub_goals:
            return _fallback_deterministic(inp)

        try:
            llm_output = self._call_llm_with_retry(inp)
            if llm_output is not None:
                return llm_output
        except Exception:
            logger.exception("evaluate: LLM call raised, falling back to deterministic")

        # Fallback déterministe
        result = _fallback_deterministic(inp)
        # Marque le fallback (pas via reasoning surtout, pour ne pas dépasser la limite)
        if "[fallback]" not in result.reasoning:
            tagged = "[fallback] " + result.reasoning
            result.reasoning = tagged[:600]
        return result

    # ------------------------------------------------------------------
    # LLM call with retry
    # ------------------------------------------------------------------

    def _call_llm_with_retry(self, inp: EvaluateInput) -> Optional[EvaluateOutput]:
        system = _build_system_prompt()
        user = _serialize_input(inp)
        client = self._get_llm_client()

        last_error: Optional[Exception] = None
        for attempt in range(self._max_retries):
            try:
                raw = client.complete(system, user)
                if not raw or not raw.strip():
                    raise EvaluateError("empty LLM response")
                stripped = _strip_markdown_fences(raw)
                parsed = json.loads(stripped)
                # On force schema_version (le LLM peut l'omettre)
                parsed.setdefault("schema_version", "a3.0")
                # On clamp les indices invalides
                parsed = _sanitize_indices(parsed, n_sub_goals=len(inp.parse_output.sub_goals))
                return EvaluateOutput.model_validate(parsed)
            except (json.JSONDecodeError, ValidationError, EvaluateError) as exc:
                last_error = exc
                logger.warning(
                    "evaluate: LLM attempt %d/%d failed: %s",
                    attempt + 1, self._max_retries, exc,
                )

        logger.warning("evaluate: all %d LLM attempts failed (last=%s)",
                       self._max_retries, last_error)
        return None


# ============================================================================
# Fallback déterministe — règles ADR §3.2 strictes
# ============================================================================


def _coverage_for_sub_goal(
    sub_goal_idx: int,
    execute_output: ExecuteOutput,
) -> str:
    """Retourne le meilleur coverage_signal parmi les ToolResult d'un sub_goal.

    Ordre : full > partial > empty.
    """
    best = "empty"
    has_full = False
    has_partial = False
    for r in execute_output.results:
        if r.sub_goal_idx != sub_goal_idx:
            continue
        if r.coverage_signal == "full":
            has_full = True
        elif r.coverage_signal == "partial":
            has_partial = True
    if has_full:
        best = "full"
    elif has_partial:
        best = "partial"
    return best


def _fallback_deterministic(inp: EvaluateInput) -> EvaluateOutput:
    """Verdict basé sur les règles déterministes de l'ADR §3.2 (sans LLM)."""
    sub_goals = inp.parse_output.sub_goals
    n_sub_goals = len(sub_goals)

    # Case 0: parse a renvoyé 0 sub_goal → INSUFFICIENT
    if n_sub_goals == 0:
        return EvaluateOutput(
            verdict="INSUFFICIENT_EVIDENCE",
            covered_sub_goals=[],
            uncovered_sub_goals=[],
            re_plan_hint="none",
            confidence=0.9,
            reasoning=(
                "Parse produced no sub_goals (question likely out of corpus scope "
                "or unparseable). Abstain rather than fabricate."
            ),
            schema_version="a3.0",
        )

    # Case 1: parse_confidence très faible → INSUFFICIENT (cf ADR rules)
    if inp.parse_output.parse_confidence < 0.3:
        return EvaluateOutput(
            verdict="INSUFFICIENT_EVIDENCE",
            covered_sub_goals=[],
            uncovered_sub_goals=list(range(n_sub_goals)),
            re_plan_hint="none",
            confidence=0.85,
            reasoning=(
                f"Parse confidence very low ({inp.parse_output.parse_confidence:.2f}). "
                "Tools likely irrelevant. Abstain."
            ),
            schema_version="a3.0",
        )

    # Calcule coverage par sub_goal
    coverages = {
        idx: _coverage_for_sub_goal(idx, inp.execute_output)
        for idx in range(n_sub_goals)
    }
    covered = [idx for idx, c in coverages.items() if c == "full"]
    partials = [idx for idx, c in coverages.items() if c == "partial"]
    empties = [idx for idx, c in coverages.items() if c == "empty"]

    # Détection d'erreur tout-azimut : si TOUS les ToolResult ont error → INSUFFICIENT
    all_errors = (
        inp.execute_output.results
        and all(r.error is not None for r in inp.execute_output.results)
    )
    if all_errors:
        return EvaluateOutput(
            verdict="INSUFFICIENT_EVIDENCE",
            covered_sub_goals=[],
            uncovered_sub_goals=list(range(n_sub_goals)),
            re_plan_hint="none",
            confidence=0.6,
            reasoning="All tool executions failed with errors. No evidence to evaluate. Abstain.",
            schema_version="a3.0",
        )

    # Case 2: tout est full → CORRECT
    if len(covered) == n_sub_goals:
        return EvaluateOutput(
            verdict="CORRECT",
            covered_sub_goals=covered,
            uncovered_sub_goals=[],
            re_plan_hint="none",
            confidence=0.9,
            reasoning=(
                "All sub_goals have full coverage from tool results. No re-plan needed."
            ),
            schema_version="a3.0",
        )

    # Case 3: tout vide
    if len(empties) == n_sub_goals:
        # Si on est à iteration 0 et tous les sub_goals ont subject_canonical, hint broaden
        if inp.iteration == 0 and any(sg.subject_canonical for sg in sub_goals):
            return EvaluateOutput(
                verdict="AMBIGUOUS",
                covered_sub_goals=[],
                uncovered_sub_goals=empties,
                re_plan_hint="add_qdrant_fallback",
                confidence=0.5,
                reasoning=(
                    "No KG claims for any sub_goal at iteration 0. "
                    "Trying Qdrant fallback before abstaining."
                ),
                schema_version="a3.0",
            )
        # iteration >= 1 ou pas de subject → abstention
        return EvaluateOutput(
            verdict="INSUFFICIENT_EVIDENCE",
            covered_sub_goals=[],
            uncovered_sub_goals=empties,
            re_plan_hint="none",
            confidence=0.85,
            reasoning=(
                f"No evidence retrieved after iteration {inp.iteration}. "
                "Re-plan unlikely to help. Abstain."
            ),
            schema_version="a3.0",
        )

    # Case 4: mix partial / full / empty
    if inp.iteration >= 1:
        # Hard cap §2.9 : iteration ≥ 1 → forcer CORRECT (avec warnings) ou INSUFFICIENT
        if covered:
            return EvaluateOutput(
                verdict="CORRECT",
                covered_sub_goals=covered,
                uncovered_sub_goals=empties + partials,
                re_plan_hint="none",
                confidence=0.55,
                reasoning=(
                    f"Iteration {inp.iteration} hit hard-cap. "
                    f"Partial answer ({len(covered)}/{n_sub_goals} covered). "
                    "Proceeding with warnings."
                ),
                schema_version="a3.0",
            )
        # Aucun full, juste partials → CORRECT avec warning (per ADR rule)
        return EvaluateOutput(
            verdict="CORRECT",
            covered_sub_goals=partials,
            uncovered_sub_goals=empties,
            re_plan_hint="none",
            confidence=0.5,
            reasoning=(
                f"Iteration {inp.iteration}: partial coverage only. "
                "Hard-cap reached, proceeding with caveats."
            ),
            schema_version="a3.0",
        )

    # iteration == 0 : re-plan possible
    # Choix du hint en fonction du contexte
    hint = _choose_re_plan_hint(inp, empties, partials)
    return EvaluateOutput(
        verdict="AMBIGUOUS",
        covered_sub_goals=covered,
        uncovered_sub_goals=empties + partials,
        re_plan_hint=hint,
        confidence=0.6,
        reasoning=(
            f"Partial coverage ({len(covered)} full, {len(partials)} partial, "
            f"{len(empties)} empty). Re-plan with hint='{hint}'."
        ),
        schema_version="a3.0",
    )


def _choose_re_plan_hint(
    inp: EvaluateInput,
    empties: List[int],
    partials: List[int],
) -> RePlanHint:
    """Heuristique simple pour choisir un re_plan_hint sensé.

    1. Si un sub_goal vide est de kind=comparison → decompose_comparison
    2. Sinon si un sub_goal vide est lifecycle_trace → check_lifecycle déjà appliqué, narrow_time_filter
    3. Sinon → add_qdrant_fallback (le fallback universel)
    """
    sub_goals = inp.parse_output.sub_goals
    for idx in empties + partials:
        if idx < len(sub_goals):
            sg = sub_goals[idx]
            if sg.kind == "comparison":
                return "decompose_comparison"
            if sg.kind == "lifecycle_trace":
                return "narrow_time_filter"
    return "add_qdrant_fallback"


# ============================================================================
# Sanitization
# ============================================================================


def _sanitize_indices(parsed: Dict[str, Any], n_sub_goals: int) -> Dict[str, Any]:
    """Filtre les indices invalides de covered/uncovered renvoyés par le LLM."""
    valid_range = set(range(n_sub_goals))
    for key in ("covered_sub_goals", "uncovered_sub_goals"):
        vals = parsed.get(key, [])
        if not isinstance(vals, list):
            parsed[key] = []
            continue
        parsed[key] = [v for v in vals if isinstance(v, int) and v in valid_range]
    return parsed


# ============================================================================
# Top-level API
# ============================================================================


def evaluate(
    parse_output: ParseOutput,
    plan_output: PlanOutput,
    execute_output: ExecuteOutput,
    iteration: int = 0,
    evaluator: Optional[Evaluator] = None,
) -> EvaluateOutput:
    """API top-level (cf ADR §2.4)."""
    inp = EvaluateInput(
        parse_output=parse_output,
        plan_output=plan_output,
        execute_output=execute_output,
        iteration=iteration,
    )
    ev = evaluator or Evaluator()
    return ev.evaluate(inp)
