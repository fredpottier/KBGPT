"""Module Synthesize — rédaction finale humaine avec citations (LLM #3).

Cf ADR_PARSE_EVALUATE_RUNTIME §2.5 + §3.3.

**Contrainte non-négociable** : zéro création de fait. Chaque phrase factuelle doit
pointer vers ≥1 CitedClaim. Validation post-synthesis via claim segmenter +
coverage check (garde-fou AX-1).

**Sélection du mode terminal** (cf VISION §4.5 + ADR §2.4.bis) :
- Evaluate.verdict=CORRECT → REASONED (sauf rétrograde post-Verifier → TEXT_ONLY)
- Evaluate.verdict=AMBIGUOUS + iter≥1 → ANCHORED (partial answer)
- Evaluate.verdict=AMBIGUOUS + iter≥2 → TEXT_ONLY (fallback Qdrant)
- Evaluate.verdict=INSUFFICIENT_EVIDENCE → ABSTENTION

**Fallback déterministe** : si LLM down ou validation Pydantic fail, on retourne
un template structurel basé sur les claims disponibles. Garde le pipeline up.

Domain-agnostic : aucun token corpus-spécifique dans prompt ni fallback.
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from pydantic import ValidationError

from knowbase.runtime_a3.schemas import (
    CitedClaim,
    ClaimSummary,
    EvaluateOutput,
    ExecuteOutput,
    ParseOutput,
    ResponseMode,
    SynthesizeError,
    SynthesizeInput,
    SynthesizeMode,
    SynthesizeOutput,
    ToolResult,
)

logger = logging.getLogger("knowbase.runtime_a3.synthesize")


# ============================================================================
# System prompt (cf ADR §3.3)
# ============================================================================


_SYSTEM_PROMPT_BASE = """You are a knowledge synthesizer. Write a clear, factual
response to the user's question, based STRICTLY on the cited claims.

INPUT: question + cited claims (verbatim text + source) + evaluation verdict +
uncovered/conflict warnings.

OUTPUT JSON ONLY (no markdown fences). Schema:
{
  "answer_text": "<natural language answer with inline [claim_id=...] citations>",
  "cited_claims": [
    {
      "claim_id": "<id>",
      "claim_verbatim": "<exact text from input — DO NOT rephrase>",
      "doc_title": "<optional>",
      "section_id": "<optional>",
      "page": <optional int>,
      "charspan_start": <optional int>,
      "charspan_end": <optional int>
    }
  ],
  "uncovered_sub_goals_warning": "<text or null>",
  "conflict_pending_warning": "<text or null>",
  "mode": "REASONED" | "ANCHORED" | "TEXT_ONLY" | "ABSTENTION",
  "synthesize_warnings": [],
  "schema_version": "a3.0"
}

RULES (NON-NEGOTIABLE):
- NEVER invent facts. Every factual statement MUST trace to a cited_claim in
  the input. If no claim supports a statement, do NOT make that statement.
- Quote claims verbatim in `cited_claims[].claim_verbatim`. Do NOT paraphrase
  the source text. Paraphrasing for fluidity is OK in `answer_text`, but the
  verbatim field must be the exact source.
- Inline citation format: `[claim_id=<id>]` after each factual statement.
  Group multiple citations: `[claim_id=c_001][claim_id=c_002]`.
- If sub_goals are uncovered (per input warning), surface them in
  `uncovered_sub_goals_warning` AND in answer_text under "⚠ Sub-goals not
  covered".
- If :ConflictPending exist on the topic, expose both/all versions in
  `conflict_pending_warning` AND in answer_text under "⚠ Conflicting sources".
- For ABSTENTION mode: produce a short motivated message explaining why the
  corpus cannot answer. Empty cited_claims is expected.

MODE selection (based on evaluate_verdict in input):
- CORRECT + claims available -> "REASONED"
- AMBIGUOUS with at least one covered sub_goal -> "ANCHORED"
- INSUFFICIENT_EVIDENCE OR zero claims -> "ABSTENTION"
- (TEXT_ONLY is set by orchestrator post-fallback, not by you directly)

Be concise. Respect AX-1 (every fact traced) and AX-14 (abstain if no evidence).

"""


@lru_cache(maxsize=1)
def _load_examples() -> List[Dict[str, Any]]:
    """Charge les few-shot examples (cf ADR §3.3.1)."""
    path = Path(__file__).parent / "prompts" / "synthesize_examples.json"
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
    """Assemble base + few-shots (cached)."""
    examples = _load_examples()
    parts = [_SYSTEM_PROMPT_BASE, "## EXAMPLES\n"]
    for i, ex in enumerate(examples):
        parts.append(_format_example_block(i, ex))
    return "\n".join(parts)


# ============================================================================
# User prompt — sérialisation
# ============================================================================


def _aggregate_claims(execute_output: ExecuteOutput) -> List[ClaimSummary]:
    """Agrège tous les claims uniques des ToolResult (dédup par claim_id)."""
    seen: Set[str] = set()
    out: List[ClaimSummary] = []
    for r in execute_output.results:
        for c in r.claims:
            if c.claim_id and c.claim_id not in seen:
                seen.add(c.claim_id)
                out.append(c)
    return out


def _aggregate_claims_with_groups(
    execute_output: ExecuteOutput,
) -> Tuple[List[ClaimSummary], List[int]]:
    """Agrège les claims uniques + leur sub_goal_idx d'origine.

    Si un claim apparaît dans plusieurs ToolResult (rare), on garde la première
    occurrence et son sub_goal_idx. Utilisé par A3.11 claim_filter pour
    stratifier le top-K par sub_goal (préserve diversité comparison).
    """
    seen: Set[str] = set()
    claims: List[ClaimSummary] = []
    groups: List[int] = []
    for r in execute_output.results:
        for c in r.claims:
            if c.claim_id and c.claim_id not in seen:
                seen.add(c.claim_id)
                claims.append(c)
                groups.append(r.sub_goal_idx)
    return claims, groups


def _aggregate_conflict_pending_summaries(execute_output: ExecuteOutput) -> List[Dict[str, Any]]:
    """Agrège les :ConflictPending dédupliqués (par conflict_id)."""
    seen: Set[str] = set()
    out: List[Dict[str, Any]] = []
    for r in execute_output.results:
        for cp in r.conflict_pendings:
            if cp.conflict_id in seen:
                continue
            seen.add(cp.conflict_id)
            out.append({
                "conflict_id": cp.conflict_id,
                "resolution_status": cp.resolution_status,
                "involved_claim_ids": cp.involved_claim_ids,
                "reason": cp.reason,
            })
    return out


def _serialize_input(
    inp: SynthesizeInput,
    override_claims: Optional[List[ClaimSummary]] = None,
) -> str:
    """User prompt pour le LLM Synthesize.

    Args:
        override_claims: Si fourni, utilisé au lieu de re-aggregating depuis
            execute_output (point d'injection A3.11 claim_filter).
    """
    if override_claims is not None:
        claims = override_claims
    else:
        claims = _aggregate_claims(inp.execute_output)
    # Limit pour bornage prompt (P0 max ~30 claims, sinon explose)
    claims = claims[:30]

    claims_payload = []
    for c in claims:
        # Le LLM verra `claim_verbatim` via `value` (best-effort) +
        # `subject_canonical`/`predicate` pour contexte
        # FIX BUG #2 — Option ε (24/05/2026) : injecter c.text (verbatim Claim) dans
        # le payload Synthesize. Sans ce champ, le LLM ne voit que (subject, predicate,
        # value) qui peut être incomplet — notamment pour les claims narratifs où la
        # `value` (object_canonical) est None. Ex HUM_0028 : claim CG5Z a
        # subject="Monitor (transaction CG5Z)" et value=None → le LLM ne voit pas
        # clairement "transaction CG5Z" et choisit un autre claim plus structuré
        # (SWI1) malgré CE top-1 score 0.965. Le verbatim text règle le problème.
        extras = c.model_dump() if hasattr(c, "model_dump") else {}
        claim_text = extras.get("text")  # verbatim Neo4j c.text (extra Pydantic)
        claims_payload.append({
            "claim_id": c.claim_id,
            "subject": c.subject_canonical,
            "predicate": c.predicate,
            "value": c.value or c.value_normalized,
            "text": (claim_text[:600] if isinstance(claim_text, str) else None),
            "source_doc_id": c.source_doc_id,
            "marker_type": c.marker_type,
        })

    cps = _aggregate_conflict_pending_summaries(inp.execute_output)

    sub_goals_payload = []
    for idx, sg in enumerate(inp.parse_output.sub_goals):
        sub_goals_payload.append({
            "idx": idx,
            "kind": sg.kind,
            "subject": sg.subject_canonical,
            "predicate": sg.predicate_hint,
            "priority": sg.priority,
            "covered": idx in inp.evaluate_output.covered_sub_goals,
        })

    payload = {
        "question": inp.parse_output.raw_question,
        "response_mode": inp.response_mode,
        "evaluate_verdict": inp.evaluate_output.verdict,
        "evaluate_reasoning": inp.evaluate_output.reasoning,
        "sub_goals": sub_goals_payload,
        "uncovered_sub_goals": inp.evaluate_output.uncovered_sub_goals,
        "claims": claims_payload,
        "conflict_pendings": cps,
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
# Citation coverage check (garde-fou AX-1)
# ============================================================================


# Sentence boundary regex (simple, domain-agnostic) — split sur . ! ? suivi d'espace
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# Match `[claim_id=...]` ou `[doc_id=...]`
_CITATION_RE = re.compile(r"\[(?:claim_id|doc_id)=[^\]]+\]")

# Phrases à ignorer (warnings transparence)
_NON_FACTUAL_MARKERS = ("⚠", "Uncovered", "Conflicting", "Possible next", "No relevant claim")


def _split_sentences(text: str) -> List[str]:
    """Split naïf en phrases (domain-agnostic, multi-langue par ponctuation)."""
    # Strip warnings sections d'abord
    lines = text.split("\n")
    keep_lines: List[str] = []
    in_warning = False
    for line in lines:
        stripped = line.strip()
        if any(marker in stripped for marker in _NON_FACTUAL_MARKERS):
            in_warning = True
            continue
        if not stripped:
            in_warning = False
            continue
        # En section warning, ignorer les bullets (commençant par "-" ou "*"
        # après strip — les espaces avant ont été retirés)
        if in_warning and (stripped.startswith("-") or stripped.startswith("*")):
            continue
        in_warning = False
        keep_lines.append(stripped)
    body = " ".join(keep_lines)
    if not body:
        return []
    sentences = [s.strip() for s in _SENT_SPLIT_RE.split(body) if s.strip()]
    return sentences


def _compute_citation_coverage(answer_text: str) -> float:
    """Retourne le ratio de phrases factuelles avec ≥1 citation.

    Ignore warnings transparence (⚠ sections). Retourne 1.0 si pas de phrase
    factuelle (cas ABSTENTION).
    """
    sentences = _split_sentences(answer_text)
    if not sentences:
        return 1.0
    n_with_cite = sum(1 for s in sentences if _CITATION_RE.search(s))
    return n_with_cite / len(sentences)


# ============================================================================
# Mode selector (déterministe selon Evaluate verdict)
# ============================================================================


def _select_mode_from_verdict(
    evaluate_output: EvaluateOutput,
    n_claims: int,
) -> SynthesizeMode:
    """Sélectionne le mode terminal selon le verdict Evaluate + dispo claims.

    Cf ADR §2.5 + VISION §4.5.
    """
    verdict = evaluate_output.verdict
    if verdict == "INSUFFICIENT_EVIDENCE" or n_claims == 0:
        return "ABSTENTION"
    if verdict == "CORRECT":
        return "REASONED"
    if verdict == "AMBIGUOUS":
        # AMBIGUOUS sans claim → ABSTENTION ; sinon ANCHORED (partial)
        return "ANCHORED" if n_claims > 0 else "ABSTENTION"
    # INCORRECT (rétrograde post-Synthesize) — théoriquement émis seulement APRÈS
    # ce module via GroundingVerifier, mais on gère le cas par robustesse.
    return "TEXT_ONLY"


# ============================================================================
# Synthesizer
# ============================================================================


class Synthesizer:
    """Rédige une SynthesizeOutput via LLM avec fallback template déterministe.

    Dependency injection :
        - `llm_client` : objet exposant `.complete(system, user) -> str`
        - `max_retries` : nombre de retries LLM
    """

    def __init__(
        self,
        llm_client: Any = None,
        max_retries: int = 2,
        claim_filter: Any = None,
        claim_filter_enabled: Optional[bool] = None,
    ):
        self._llm_client = llm_client
        self._max_retries = max_retries
        self._claim_filter = claim_filter
        # Toggle env A3.11 (default ON)
        import os
        if claim_filter_enabled is None:
            self._claim_filter_enabled = (
                os.getenv("V6_CLAIM_FILTER_ENABLED", "1") == "1"
            )
        else:
            self._claim_filter_enabled = claim_filter_enabled
        # Trace observability (filter result du dernier synthesize)
        self._last_filter_result = None

    def _get_claim_filter(self):
        """Lazy init du claim filter (réutilise l'embedder de base)."""
        if self._claim_filter is None:
            from knowbase.runtime_a3.claim_filter import ClaimFilter
            self._claim_filter = ClaimFilter()
        return self._claim_filter

    def _apply_claim_filter(
        self,
        inp: SynthesizeInput,
    ) -> List[ClaimSummary]:
        """Applique le filtre sémantique claim↔question si activé.

        Stratifie par sub_goal_idx pour préserver la diversité (notamment
        comparison qui décompose en 2× kg_claims).

        P2.2 (23/05/2026) — toggle V6_CROSS_ENCODER_RERANK :
            - "1" : cross-encoder reranker (BAAI/bge-reranker-v2-m3) sur top-N RRF
            - "0" (défaut) : bi-encoder ClaimFilter (cosine sentence-transformers)

        Si désactivé, retourne claims inchangés. Si erreur, fail-open (claims bruts).
        """
        claims, groups = _aggregate_claims_with_groups(inp.execute_output)

        if not self._claim_filter_enabled or not claims:
            return claims

        # P2.2 — Cross-encoder reranker prioritaire si activé
        import os as _os
        if _os.getenv("V6_CROSS_ENCODER_RERANK", "0") == "1":
            try:
                from knowbase.runtime_a3.reranker import ClaimReranker
                reranker = ClaimReranker(top_k=5)
                question = inp.parse_output.raw_question
                kept_claims, kept_scores = reranker.rerank(question, claims)
                self._last_filter_result = None  # cross-encoder n'utilise pas le même schema
                logger.info(
                    "[CROSS_ENCODER] kept %d/%d claims (top_score=%.3f)",
                    len(kept_claims), len(claims),
                    kept_scores[0] if kept_scores else 0.0,
                )
                # P2 Option ε debug : logger top-5 envoyé à Synthesize avec subject + score
                if _os.getenv("V6_DEBUG_SYNTHESIZE_TOP5", "0") == "1":
                    for i, (c, s) in enumerate(zip(kept_claims, kept_scores)):
                        text_excerpt = (c.value or c.value_normalized or "")[:80]
                        logger.info(
                            "[SYNTHESIZE_TOP5] rank=%d score=%.3f claim_id=%s subj=%s pred=%s text=%s",
                            i + 1, s, c.claim_id[:14],
                            (c.subject_canonical or "")[:40],
                            (c.predicate or "")[:20],
                            text_excerpt,
                        )
                return kept_claims
            except Exception:
                logger.exception("synthesize: cross_encoder reranker failed, fallback to bi-encoder filter")
                # fall through to bi-encoder

        try:
            question = inp.parse_output.raw_question
            kept, result = self._get_claim_filter().filter(
                question, claims, groups=groups,
            )
            self._last_filter_result = result
            return kept
        except Exception:
            logger.exception("synthesize: claim_filter failed, fallback to unfiltered")
            return claims

    def _get_llm_client(self):
        if self._llm_client is None:
            from knowbase.common.llm_router import LLMRouter, TaskType

            class _RouterClient:
                def __init__(self):
                    self._router = LLMRouter()

                def complete(self, system: str, user: str) -> str:
                    return self._router.complete(
                        task_type=TaskType.LONG_TEXT_SUMMARY,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        temperature=0.1,  # faible créativité, factuel
                        max_tokens=1500,
                    )
            self._llm_client = _RouterClient()
        return self._llm_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def synthesize(self, inp: SynthesizeInput) -> SynthesizeOutput:
        """Rédige et valide la sortie (LLM ou fallback template)."""
        claims = _aggregate_claims(inp.execute_output)

        # Court-circuit ABSTENTION (pas d'evidence → pas besoin LLM)
        if inp.evaluate_output.verdict == "INSUFFICIENT_EVIDENCE" or not claims:
            return self._build_abstention(inp)

        # A3.11 : filtre sémantique claims↔question avant LLM (top-K pertinents).
        # Stratifié par sub_goal_idx pour préserver la diversité (comparison etc.).
        # Fait UNE FOIS ici pour éviter de re-encoder dans les retries.
        filtered_claims = self._apply_claim_filter(inp)

        # Tentative LLM
        try:
            out = self._call_llm_with_retry(inp, override_claims=filtered_claims)
            if out is not None:
                return self._finalize(out, inp)
        except Exception:
            logger.exception("synthesize: LLM call raised, falling back to template")

        # Fallback template déterministe (utilise aussi les claims filtrés
        # pour rester consistant avec ce que le LLM aurait vu)
        return self._build_template_fallback(inp, filtered_claims)

    # ------------------------------------------------------------------
    # LLM call with retry
    # ------------------------------------------------------------------

    def _call_llm_with_retry(
        self,
        inp: SynthesizeInput,
        override_claims: Optional[List[ClaimSummary]] = None,
    ) -> Optional[SynthesizeOutput]:
        system = _build_system_prompt()
        user = _serialize_input(inp, override_claims=override_claims)
        client = self._get_llm_client()

        last_error: Optional[Exception] = None
        for attempt in range(self._max_retries):
            try:
                raw = client.complete(system, user)
                if not raw or not raw.strip():
                    raise SynthesizeError("empty LLM response")
                stripped = _strip_markdown_fences(raw)
                parsed = json.loads(stripped)
                parsed.setdefault("schema_version", "a3.0")
                parsed.setdefault("synthesize_warnings", [])
                # Force mode si LLM produit valeur non-Literal (best-effort)
                allowed_modes = {"REASONED", "ANCHORED", "TEXT_ONLY", "ABSTENTION"}
                if parsed.get("mode") not in allowed_modes:
                    parsed["mode"] = _select_mode_from_verdict(
                        inp.evaluate_output,
                        n_claims=len(_aggregate_claims(inp.execute_output)),
                    )
                return SynthesizeOutput.model_validate(parsed)
            except (json.JSONDecodeError, ValidationError, SynthesizeError) as exc:
                last_error = exc
                logger.warning(
                    "synthesize: LLM attempt %d/%d failed: %s",
                    attempt + 1, self._max_retries, exc,
                )
        logger.warning(
            "synthesize: all %d LLM attempts failed (last=%s)",
            self._max_retries, last_error,
        )
        return None

    # ------------------------------------------------------------------
    # Finalize: post-validation + citation coverage check
    # ------------------------------------------------------------------

    def _finalize(
        self,
        out: SynthesizeOutput,
        inp: SynthesizeInput,
    ) -> SynthesizeOutput:
        """Calcule citation_coverage_rate + ajoute warning si <95%.
        A4.5 : applique GroundingVerifier (NLI mDeBERTa) si activé.
        """
        rate = _compute_citation_coverage(out.answer_text)
        out.citation_coverage_rate = rate
        warnings = list(out.synthesize_warnings)
        if rate < 0.95 and out.mode not in ("ABSTENTION", "TEXT_ONLY"):
            warnings.append(
                f"citation_coverage_below_threshold:{rate:.2f}_(target_0.95)"
            )

        # A4.5 — GroundingVerifier post-Synthesize (anti-hallucination)
        # cf project_a44_root_cause_synthesize_hallucination.md
        try:
            from knowbase.runtime_a3.grounding_verifier import (
                GroundingVerifier,
                apply_grounding_decision,
                is_enabled as gv_enabled,
                get_mode as gv_mode,
            )
            if gv_enabled() and out.mode not in ("ABSTENTION",) and out.cited_claims:
                # Construire dict claim_id → verbatim depuis les cited_claims
                claim_verbatim_by_id = {
                    c.claim_id: c.claim_verbatim
                    for c in out.cited_claims
                    if c.claim_id and c.claim_verbatim
                }
                if claim_verbatim_by_id:
                    if not hasattr(self, "_grounding_verifier"):
                        self._grounding_verifier = GroundingVerifier()
                    report = self._grounding_verifier.verify(
                        out.answer_text, claim_verbatim_by_id,
                    )
                    self._last_grounding_report = report
                    mode = gv_mode()
                    new_text, gv_warnings = apply_grounding_decision(
                        out.answer_text, report, mode=mode,
                    )
                    out.answer_text = new_text
                    warnings.extend(gv_warnings)
                    # Si abstention forcée, marquer le mode
                    if (mode == "ABSTAIN" and report.n_checked > 0
                            and report.hallucination_rate > 0.5):
                        out.mode = "ABSTENTION"
                    logger.info(
                        "[GroundingVerifier] mode=%s n_sentences=%d n_checked=%d "
                        "n_hallucinations=%d dur=%.2fs",
                        mode, report.n_sentences, report.n_checked,
                        report.n_hallucinations, report.duration_s,
                    )
        except Exception:
            logger.exception("[GroundingVerifier] failed (non-fatal)")

        out.synthesize_warnings = warnings
        return out

    # ------------------------------------------------------------------
    # Fallback template déterministe
    # ------------------------------------------------------------------

    def _build_abstention(self, inp: SynthesizeInput) -> SynthesizeOutput:
        """Build une réponse ABSTENTION sans LLM."""
        uncovered_descs = []
        for idx in inp.evaluate_output.uncovered_sub_goals:
            if idx < len(inp.parse_output.sub_goals):
                sg = inp.parse_output.sub_goals[idx]
                subject_desc = f"'{sg.subject_canonical}'" if sg.subject_canonical else "(no subject)"
                pred_desc = f" predicate '{sg.predicate_hint}'" if sg.predicate_hint else ""
                uncovered_descs.append(f"  - sub_goal {idx} ({sg.kind}): {subject_desc}{pred_desc}")

        uncovered_block = ""
        if uncovered_descs:
            uncovered_block = "\n\nUncovered sub-goals:\n" + "\n".join(uncovered_descs)

        answer = (
            "No relevant claim found in the indexed corpus to answer this question."
            + uncovered_block
            + "\n\nPossible next steps:\n"
            "  - Reformulate with more specific terms\n"
            "  - Verify that the indexed corpus covers this topic"
        )

        warning_text = (
            "All sub_goals uncovered (out of corpus scope or evidence missing)."
            if inp.evaluate_output.verdict == "INSUFFICIENT_EVIDENCE"
            else None
        )

        return SynthesizeOutput(
            answer_text=answer,
            cited_claims=[],
            uncovered_sub_goals_warning=warning_text,
            conflict_pending_warning=None,
            mode="ABSTENTION",
            synthesize_warnings=["template_fallback_no_llm"]
            if inp.evaluate_output.verdict != "INSUFFICIENT_EVIDENCE"
            else [],
            citation_coverage_rate=1.0,
            schema_version="a3.0",
        )

    def _build_template_fallback(
        self,
        inp: SynthesizeInput,
        claims: List[ClaimSummary],
    ) -> SynthesizeOutput:
        """Fallback template déterministe quand LLM échoue mais claims présents.

        Format minimaliste : liste les claims sous forme structurée.
        """
        mode = _select_mode_from_verdict(inp.evaluate_output, n_claims=len(claims))
        if mode == "ABSTENTION":
            return self._build_abstention(inp)

        cited: List[CitedClaim] = []
        lines: List[str] = []
        for c in claims[:20]:  # max 20 claims dans fallback
            verbatim = c.value or c.value_normalized or f"(claim {c.claim_id})"
            cited.append(CitedClaim(
                claim_id=c.claim_id,
                claim_verbatim=str(verbatim),
                doc_title=None,
                section_id=None,
            ))
            subj = c.subject_canonical or "(unknown subject)"
            pred = c.predicate or "(unknown predicate)"
            lines.append(f"- {subj} — {pred}: {verbatim} [claim_id={c.claim_id}]")

        answer_text = (
            "Synthesized facts (LLM unavailable, template fallback):\n"
            + "\n".join(lines)
        )

        # Warnings transparence
        uncovered_warning = None
        if inp.evaluate_output.uncovered_sub_goals:
            uncov_idx = inp.evaluate_output.uncovered_sub_goals
            uncovered_warning = f"Sub-goals not covered: indices {uncov_idx}."
            answer_text += f"\n\n⚠ Sub-goals not covered: {uncov_idx}"

        cps = _aggregate_conflict_pending_summaries(inp.execute_output)
        cp_warning = None
        if cps:
            cp_ids = [cp["conflict_id"] for cp in cps]
            cp_warning = f"Unresolved :ConflictPending detected: {cp_ids}."
            answer_text += f"\n\n⚠ Conflicting sources: {cp_ids}"

        return SynthesizeOutput(
            answer_text=answer_text,
            cited_claims=cited,
            uncovered_sub_goals_warning=uncovered_warning,
            conflict_pending_warning=cp_warning,
            mode=mode,
            synthesize_warnings=["template_fallback_no_llm"],
            citation_coverage_rate=1.0,  # template garantit 1 citation par claim
            schema_version="a3.0",
        )


# ============================================================================
# Top-level API
# ============================================================================


def synthesize(
    parse_output: ParseOutput,
    execute_output: ExecuteOutput,
    evaluate_output: EvaluateOutput,
    response_mode: ResponseMode = "structured",
    synthesizer: Optional[Synthesizer] = None,
) -> SynthesizeOutput:
    """API top-level (cf ADR §2.5)."""
    inp = SynthesizeInput(
        parse_output=parse_output,
        execute_output=execute_output,
        evaluate_output=evaluate_output,
        response_mode=response_mode,
    )
    s = synthesizer or Synthesizer()
    return s.synthesize(inp)
