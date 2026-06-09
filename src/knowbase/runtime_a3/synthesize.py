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
import os
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


# i18n (01/06/2026) — le chat doit répondre dans la LANGUE DE LA QUESTION, pas
# celle des claims (corpus souvent EN). Domain-agnostic.
_LANG_NAMES = {"fr": "French", "en": "English", "de": "German", "es": "Spanish"}


def _lang_name(parse_output) -> str:
    code = getattr(parse_output, "language", None)
    code = getattr(code, "value", code)  # enum → str
    return _LANG_NAMES.get(str(code or "").lower(), "the same language as the question")


# Messages de repli (chemins SANS LLM) — localisés pour ne pas casser la langue.
_I18N_NO_CLAIM = {
    "fr": "Aucune information pertinente n'a été trouvée dans le corpus indexé pour répondre à cette question.",
    "en": "No relevant claim found in the indexed corpus to answer this question.",
    "de": "Im indexierten Korpus wurde keine relevante Information gefunden, um diese Frage zu beantworten.",
    "es": "No se ha encontrado información pertinente en el corpus indexado para responder a esta pregunta.",
}
_I18N_UNCOVERED = {
    "fr": "Aspects non couverts", "en": "Sub-goals not covered",
    "de": "Nicht abgedeckte Teilfragen", "es": "Aspectos no cubiertos",
}
_I18N_CONFLICT = {
    "fr": "Sources en tension", "en": "Conflicting sources",
    "de": "Widersprüchliche Quellen", "es": "Fuentes en conflicto",
}
_I18N_EQUIVALENT = {
    "fr": "énoncent la même valeur (unités différentes)",
    "en": "state the same value (different units)",
    "de": "nennen denselben Wert (unterschiedliche Einheiten)",
    "es": "expresan el mismo valor (unidades diferentes)",
}
_I18N_NEXT_STEPS = {
    "fr": "Pistes possibles :\n  - Reformuler avec des termes plus précis\n  - Vérifier que le corpus indexé couvre ce sujet",
    "en": "Possible next steps:\n  - Reformulate with more specific terms\n  - Verify that the indexed corpus covers this topic",
    "de": "Mögliche nächste Schritte:\n  - Mit präziseren Begriffen umformulieren\n  - Prüfen, ob das indexierte Korpus dieses Thema abdeckt",
    "es": "Posibles pasos siguientes:\n  - Reformular con términos más específicos\n  - Verificar que el corpus indexado cubre este tema",
}
_I18N_UNCOVERED_BLOCK = {
    "fr": "Aspects non couverts", "en": "Uncovered sub-goals",
    "de": "Nicht abgedeckte Teilfragen", "es": "Aspectos no cubiertos",
}


def _i18n(table: Dict[str, str], parse_output) -> str:
    code = getattr(parse_output, "language", None)
    code = getattr(code, "value", code)
    return table.get(str(code or "").lower(), table["en"])


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
- DOCUMENT TITLES, FILENAMES, SECTION NAMES and source metadata are NOT facts.
  NEVER extract or infer a value (version, date, number, code, identifier, name)
  from a `doc_title`, filename, or source label. A value appearing only in a
  filename (e.g. a year in "..._2025_Guide") does NOT mean it is the answer.
  Facts come ONLY from the verbatim claim TEXT. If the specific value the
  question asks for is not stated in any claim's text, abstain — do NOT guess it
  from a title or filename.
- LANGUAGE: write `answer_text` (and any warning message you put in it) in the
  SAME language as the user's question — given as `answer_language` in the input.
  Do this EVEN IF the cited claims are written in another language: translate the
  facts into the question's language. EXCEPTION: keep `cited_claims[].claim_verbatim`
  in its EXACT original source language (it is a verbatim quote, never translate it).
- Quote claims verbatim in `cited_claims[].claim_verbatim`. Do NOT paraphrase
  the source text. Paraphrasing for fluidity is OK in `answer_text`, but the
  verbatim field must be the exact source.
- COMPLETENESS: produce a THOROUGH answer that USES EVERY relevant cited claim,
  not only the single most direct one. When several claims bear on the question,
  synthesize them all — cover each distinct aspect, value, condition, qualifier,
  scope-limit, exception and cross-reference that the claims state. When ≥3 claims
  are provided, prefer a structured answer (a one-line lead, then grouped
  paragraphs or bullet points by aspect) rather than a single terse sentence.
  This rule adds COVERAGE of the provided claims only — it NEVER licenses invented
  content: every added detail must still trace to a cited claim (the grounding
  rules above remain absolute).
- Inline citation format: `[claim_id=<id>]` after each factual statement.
  Group multiple citations: `[claim_id=c_001][claim_id=c_002]`.
- If sub_goals are uncovered (per input warning), surface them in
  `uncovered_sub_goals_warning` AND in answer_text under "⚠ Sub-goals not
  covered".
- If :ConflictPending exist on the topic, expose both/all versions in
  `conflict_pending_warning` AND in answer_text under "⚠ Conflicting sources".
- If `procedure_chains` are present (a step-by-step sequence with a goal and
  ordered steps), and the question asks HOW to do something, the next/previous
  step, or prerequisites, use the ordered_steps + prerequisites to structure the
  answer. The cited claims remain the evidence; the chain provides ordering and
  completeness. Still cite the underlying claims; do not invent steps absent
  from the chain.
- If `doc_lineages` are present (document version chains): when the question asks
  which version/edition is current or in force, or what a document replaced or
  superseded, answer from the chain — name the in-force document (`in_force`) and,
  in order, the documents it superseded (`supersedes`). Use the `evidence` verbatim
  as the proof of supersession. Do NOT assert a version that is not in the chain;
  if `is_in_force` is false, say which document supersedes it.
- If `authority_conflicts` are present (two regulatory authorities/sources state
  requirements on the same point), check the `equivalent` flag FIRST:
  * `equivalent: true` — the two sides state the SAME value in different units
    (e.g. 1,500 lb vs 680 kg). This is NOT a divergence: present it as a
    cross-authority CONFIRMATION ("both <authority_a> and <authority_b> state
    the same limit, expressed as <text_a fragment> and <text_b fragment>").
    NEVER label an equivalent pair "divergence" or use the ⚠ marker for it.
  * `equivalent: false` — a REAL difference: expose BOTH explicitly with
    attribution — e.g. "<authority_a> (<doc_a>) states <text_a>, whereas
    <authority_b> (<doc_b>) states <text_b>" — then state the actual difference.
    Never present one authority's rule as if it were universal. Surface this in
    answer_text under "⚠ Divergence between authorities".
- CLAIM `status` (lifecycle):
  * `in_force` — current knowledge; answer normally.
  * `superseded` — a HISTORICAL fact, replaced by a successor document. NEVER
    present it as the current rule. For evolution/lifecycle/point-in-time
    questions it IS the answer material: present it temporally ("under the
    <valid_from> edition, X was …; the current edition states …"). For
    current-state questions, prefer in_force claims and mention the superseded
    value only as history if relevant.
  * `withdrawn` — the SOURCE DOCUMENT was cancelled but no successor restates
    this specific point. EPISTEMIC caveat required, with this exact nuance:
    say "according to <doc> (document cancelled); the successor does not
    restate this point" — NEVER say or imply "this is no longer valid" (the
    corpus does not state that; do not invent the replacement).
- If two claims about the same point CONTRADICT and both carry dates but no
  resolution: present BOTH temporally with their dates and sources ("the
  <newer date> document states X; the <older date> document stated Y") and let
  the reader decide — do NOT silently prefer the more recent one.
- COMPARISON questions (the question contrasts two or more items, versions,
  editions, options, or documents): structure the answer to present EACH side
  EXPLICITLY and put them side by side (e.g. "Side A: <facts> ; Side B: <facts>"),
  then state the actual difference. Cite the claims of each side. If the evidence
  covers one side but NOT the other, say so explicitly ("the corpus documents X
  for A but does not document the corresponding fact for B") instead of describing
  only the covered side. Never present a one-sided answer as if it were the
  comparison.
- BE SPECIFIC, NOT GENERIC. Especially for broad/multi-aspect questions ("what do
  the documents say about X, including A, B, C"): answer EACH named aspect with its
  CONCRETE facts from the claims — the actual identifiers, names, values, options,
  steps, or conditions — NOT a high-level paraphrase. Prefer naming the actual
  items (e.g. "the supported options are Alpha, Beta and Gamma") over a vague
  summary ("there are several options"). If a claim carries a specific fact
  relevant to a requested aspect, surface that fact; do not summarize it away. A
  correct-but-vague answer that omits the specifics available in the claims is a FAILURE.
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


def _aggregate_procedure_chains(execute_output: ExecuteOutput) -> List[Dict[str, Any]]:
    """Agrège les chaînes procédurales dédupliquées (par procedure_id, Phase B P1.5)."""
    seen: Set[str] = set()
    out: List[Dict[str, Any]] = []
    for r in execute_output.results:
        for pc in getattr(r, "procedure_chains", []) or []:
            if pc.procedure_id in seen:
                continue
            seen.add(pc.procedure_id)
            out.append({
                "procedure_id": pc.procedure_id,
                "name": pc.name,
                "goal": pc.goal,
                "ordered_steps": pc.ordered_steps,
                "prerequisites": pc.prerequisites,
            })
    return out


def _aggregate_doc_lineages(execute_output: ExecuteOutput) -> List[Dict[str, Any]]:
    """Agrège les lignées de document dédupliquées (par doc_id, #443)."""
    seen: Set[str] = set()
    out: List[Dict[str, Any]] = []
    for r in execute_output.results:
        for dl in getattr(r, "doc_lineages", []) or []:
            if dl.doc_id in seen:
                continue
            seen.add(dl.doc_id)
            out.append({
                "document": dl.reg_key or dl.doc_id,
                "in_force": dl.in_force_reg_key,
                "is_in_force": dl.is_in_force,
                "supersedes": dl.superseded,
                "evidence": dl.evidence,
                "evidence_claim_ids": getattr(dl, "evidence_claim_ids", []) or [],
            })
    return out


def _aggregate_authority_conflicts(execute_output: ExecuteOutput) -> List[Dict[str, Any]]:
    """Agrège les contradictions inter-autorités dédupliquées (#440).

    Marqueur `equivalent` (05/06/2026, retour Fred) : une paire dont les deux
    côtés énoncent les MÊMES valeurs dans des unités différentes (1,500 lb vs
    680 kg) est une CONCORDANCE, pas une divergence — le prompt la présente en
    confirmation inter-autorités, jamais sous « ⚠ Divergence ». Détection
    déterministe (conversion d'unités), cf relations/value_equivalence.py.
    """
    from knowbase.relations.value_equivalence import quantities_equivalent

    seen: Set[tuple] = set()
    out: List[Dict[str, Any]] = []
    for r in execute_output.results:
        for ac in getattr(r, "authority_conflicts", []) or []:
            key = (ac.doc_a, ac.doc_b, ac.text_a[:40])
            if key in seen:
                continue
            seen.add(key)
            try:
                equivalent = quantities_equivalent(ac.text_a, ac.text_b)
            except Exception:
                equivalent = False
            out.append({
                "subject": ac.subject,
                "authority_a": ac.authority_a,
                "doc_a": ac.doc_a,
                "text_a": ac.text_a,
                "authority_b": ac.authority_b,
                "doc_b": ac.doc_b,
                "text_b": ac.text_b,
                "equivalent": equivalent,
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
        # Statut lifecycle (ADR_RESOLUTION_CONTRADICTIONS §5.2/§7.D/§7.F) :
        # - superseded : invalidé par lignée documentaire → fait HISTORIQUE
        # - withdrawn  : doc porteur annulé, successeur muet → caveat épistémique
        # - in_force   : courant
        if c.invalidated_at is not None:
            status = "superseded"
        elif extras.get("lifecycle_status") == "withdrawn":
            status = "withdrawn"
        else:
            status = "in_force"
        claims_payload.append({
            "claim_id": c.claim_id,
            "subject": c.subject_canonical,
            "predicate": c.predicate,
            "value": c.value or c.value_normalized,
            "text": (claim_text[:600] if isinstance(claim_text, str) else None),
            "source_doc_id": c.source_doc_id,
            "marker_type": c.marker_type,
            "status": status,
            "valid_from": (str(c.valid_from)[:10] if c.valid_from else None),
            "valid_until": (str(c.valid_until)[:10] if c.valid_until else None),
        })

    cps = _aggregate_conflict_pending_summaries(inp.execute_output)
    procedure_chains = _aggregate_procedure_chains(inp.execute_output)
    doc_lineages = _aggregate_doc_lineages(inp.execute_output)
    authority_conflicts = _aggregate_authority_conflicts(inp.execute_output)

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

    answer_language = _lang_name(inp.parse_output)
    payload = {
        "question": inp.parse_output.raw_question,
        "answer_language": answer_language,
        "response_mode": inp.response_mode,
        "evaluate_verdict": inp.evaluate_output.verdict,
        "evaluate_reasoning": inp.evaluate_output.reasoning,
        "sub_goals": sub_goals_payload,
        "uncovered_sub_goals": inp.evaluate_output.uncovered_sub_goals,
        "claims": claims_payload,
        "conflict_pendings": cps,
        "procedure_chains": procedure_chains,
        "doc_lineages": doc_lineages,
        "authority_conflicts": authority_conflicts,
    }
    return (
        "USER INPUT (JSON):\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + f"\n\nWrite answer_text in {answer_language}. Respond with JSON only."
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
        top_k_override: Optional[int] = None,
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

        # P3.2 (29/05/2026) — top_k élargi pour les questions-liste : une réponse
        # multi-items (codes, objets, outils) était tronquée à 5 → on garde plus de
        # candidats pour couvrir tous les items. N'affecte PAS le factual atomique.
        # Levier A complétude (09/06/2026) — le top_k non-liste à 5 rendait les
        # réponses laconiques vs RAG (12 chunks). V6_SYNTH_TOP_K (défaut 10) élargit
        # la matière VALIDÉE envoyée à la synthèse → couverture sans perte d'ancrage.
        # Mettre "5" pour revenir au comportement historique.
        import os as _os
        is_list = any(
            sg.kind == "list_enumeration" for sg in inp.parse_output.sub_goals
        )
        eff_top_k = (
            int(_os.getenv("V6_LIST_TOP_K", "12")) if is_list
            else int(_os.getenv("V6_SYNTH_TOP_K", "10"))
        )
        if top_k_override is not None:
            eff_top_k = top_k_override

        # P2.2 — Cross-encoder reranker prioritaire si activé
        if _os.getenv("V6_CROSS_ENCODER_RERANK", "0") == "1":
            try:
                from knowbase.runtime_a3.reranker import ClaimReranker
                reranker = ClaimReranker(top_k=eff_top_k)
                question = inp.parse_output.raw_question
                # Comparaison / multi-aspect (≥2 sous-buts distincts) → rerank
                # ÉQUILIBRÉ par côté pour que les 2 côtés soient représentés (sinon
                # le côté dominant écrase l'autre → synthèse un seul côté).
                # Cf project_comparison_synthesis_audit.
                n_groups = len(set(groups)) if groups else 1
                if n_groups >= 2:
                    kept_claims, kept_scores = reranker.rerank_balanced(
                        question, claims, groups, top_k=max(eff_top_k, 2 * n_groups),
                    )
                else:
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
                question, claims, groups=groups, top_k=eff_top_k,
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
                        # DÉTERMINISME (01/06/2026) — temperature=0 + seed fixe pour que
                        # la MÊME question donne la MÊME réponse (assert/abstention
                        # stable). Reproductibilité = condition de confiance.
                        temperature=0.0,
                        seed=1234,
                        max_tokens=1500,
                    )
            self._llm_client = _RouterClient()
        return self._llm_client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def synthesize(self, inp: SynthesizeInput) -> SynthesizeOutput:
        """Rédige et valide la sortie (LLM ou fallback template)."""
        # PremiseVerifier (faux présupposés, 30/05/2026) — AVANT tout : empêche la
        # confabulation quand des claims existent mais que le présupposé est faux.
        # Cf ADR_PREMISE_VERIFIER.md. Toggle V6_PREMISE_VERIFIER_ENABLED. Fail-open.
        premise = self._maybe_premise_correction(inp)
        if premise is not None:
            return premise

        claims = _aggregate_claims(inp.execute_output)

        # Court-circuit ABSTENTION (pas d'evidence → pas besoin LLM)
        if inp.evaluate_output.verdict == "INSUFFICIENT_EVIDENCE" or not claims:
            return self._build_abstention(inp)

        # A3.11 : filtre sémantique claims↔question avant LLM (top-K pertinents).
        # Stratifié par sub_goal_idx pour préserver la diversité (comparison etc.).
        # Fait UNE FOIS ici pour éviter de re-encoder dans les retries.
        filtered_claims = self._apply_claim_filter(inp)

        # SufficiencyChecker (Phase B, 25/05/2026) — garde-fou anti-sur-confiance.
        # Vérifie que les claims top-K répondent à la QUESTION posée (pas juste
        # sémantiquement proches). Si INSUFFICIENT/FALSE_PREMISE → abstention motivée.
        # Toggle V6_SUFFICIENCY_CHECK_ENABLED (défaut OFF). Fail-open (SUFFICIENT).
        suff = self._maybe_sufficiency_abstention(inp, filtered_claims)
        if suff is not None:
            return suff

        # Tentative LLM
        try:
            out = self._call_llm_with_retry(inp, override_claims=filtered_claims)
            if out is not None:
                out = self._maybe_textonly_rescue(out, inp, filtered_claims)
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
            except Exception as exc:  # noqa: BLE001
                # Erreur TRANSITOIRE (timeout réseau, 5xx provider, connexion) — la
                # plus fréquente sur les gros prompts comparison/2-côtés. Avant ce fix,
                # elle n'était PAS rattrapée par la boucle → repli template immédiat
                # (≈25% des questions comparison du bench). On retente avec backoff.
                last_error = exc
                logger.warning(
                    "synthesize: LLM attempt %d/%d transient error: %s",
                    attempt + 1, self._max_retries, exc,
                )
                if attempt < self._max_retries - 1:
                    import time as _time
                    _time.sleep(2.0 * (attempt + 1))  # 2s, 4s
        logger.warning(
            "synthesize: all %d LLM attempts failed (last=%s)",
            self._max_retries, last_error,
        )
        return None

    # ------------------------------------------------------------------
    # Finalize: post-validation + citation coverage check
    # ------------------------------------------------------------------

    def _maybe_textonly_rescue(
        self,
        out: SynthesizeOutput,
        inp: SynthesizeInput,
        filtered_claims: List[ClaimSummary],
    ) -> SynthesizeOutput:
        """Garde STABILITÉ (chantier 05/06) — rescue des flips TEXT_ONLY.

        Pattern observé (bench + chat) : Evaluate dit CORRECT, des claims sont
        fournis, mais le LLM Synthesize déclare TEXT_ONLY (« the evidence does
        not document… ») parce que le top-5 filtré a raté LE claim clé — flip
        run-to-run causé par la non-déterminisme provider (DeepSeek MoE, même à
        temperature=0+seed) en amont (Parse → retrieval → top-5 différents).

        Rescue ÉTROIT (anti-A3.10 : jamais une cascade systématique) :
        uniquement si verdict==CORRECT ET claims≥1 ET mode==TEXT_ONLY, on
        re-filtre avec top_k élargi (12) et on retente UNE synthèse. Si le LLM
        maintient TEXT_ONLY → on respecte (abstention/constat honnête conservé).
        Toggle V6_TEXTONLY_RESCUE (défaut "1"). Coût : 1 appel LLM, rare.
        """
        if os.getenv("V6_TEXTONLY_RESCUE", "1") != "1":
            return out
        if out.mode != "TEXT_ONLY":
            return out
        if inp.evaluate_output.verdict != "CORRECT" or not filtered_claims:
            return out
        try:
            widened = self._apply_claim_filter(inp, top_k_override=12)
        except Exception:
            return out
        if len(widened) <= len(filtered_claims):
            return out  # rien de plus à montrer → inutile de retenter
        logger.info(
            "synthesize: TEXT_ONLY rescue — verdict CORRECT avec %d claims, "
            "retry avec top-K élargi (%d claims)",
            len(filtered_claims), len(widened),
        )
        try:
            retried = self._call_llm_with_retry(inp, override_claims=widened)
        except Exception:
            return out
        if retried is not None and retried.mode != "TEXT_ONLY":
            retried.synthesize_warnings = list(retried.synthesize_warnings) + [
                "textonly_rescue_applied"
            ]
            return retried
        out.synthesize_warnings = list(out.synthesize_warnings) + [
            "textonly_rescue_unchanged"
        ]
        return out

    def _finalize(
        self,
        out: SynthesizeOutput,
        inp: SynthesizeInput,
    ) -> SynthesizeOutput:
        """Calcule citation_coverage_rate + ajoute warning si <95%.
        A4.5 : applique GroundingVerifier (NLI mDeBERTa) si activé.
        """
        # Signal structuré de divergence d'autorités (05/06/2026, retour Fred) :
        # posé DÉTERMINISTIQUEMENT (jamais par le LLM) quand au moins une paire
        # inter-autorités NON-équivalente a été attachée au retrieval — l'UI peut
        # matérialiser un picto/bandeau sans regex sur answer_text. Les paires
        # `equivalent` (mêmes valeurs, unités différentes) ne déclenchent PAS.
        try:
            acs = _aggregate_authority_conflicts(inp.execute_output)
            real = [ac for ac in acs if not ac.get("equivalent")]
            if real:
                pairs = ", ".join(
                    f"{ac.get('authority_a') or ac.get('doc_a')}↔"
                    f"{ac.get('authority_b') or ac.get('doc_b')}"
                    for ac in real[:3]
                )
                out.authority_divergence_warning = (
                    f"Divergence entre autorités réglementaires détectée ({pairs})."
                )
        except Exception:
            pass
        # PREUVE DE LIGNÉE citable (fix filage démo 06/06) : quand des lignées
        # documentaires ont été utilisées, la déclaration de supersession
        # (« This AC cancels AC 21-25A… ») doit apparaître comme une VRAIE
        # citation — claim_id réel → la hydration API résout le bon doc + la
        # bonne page. Avant ce fix, le LLM rattachait la phrase de lignée à un
        # claim de retrieval sans rapport (constaté : preuve d'annulation
        # AC 21-25A « sourcée » sur une page flammabilité d'ETSO-C127c).
        try:
            lineages = _aggregate_doc_lineages(inp.execute_output)
            already = {cc.claim_id for cc in out.cited_claims}
            answer_lower = (out.answer_text or "").lower()
            for dl in lineages:
                # Ne citer que les lignées dont la réponse PARLE réellement
                # (sinon les lignées des autres docs touchés par le retrieval
                # polluent la liste de citations — ex AC 20-146 sur une
                # question AC 21-25A).
                mentioned_keys = [
                    k for k in (
                        [dl.get("document"), dl.get("in_force")]
                        + list(dl.get("supersedes") or [])
                    ) if k
                ]
                if not any(str(k).lower() in answer_lower for k in mentioned_keys):
                    continue
                for cid, ev in zip(dl.get("evidence_claim_ids") or [],
                                   dl.get("evidence") or []):
                    if cid and cid not in already:
                        out.cited_claims.append(CitedClaim(
                            claim_id=cid,
                            claim_verbatim=(ev or "")[:300],
                        ))
                        already.add(cid)
        except Exception:
            logger.exception("synthesize: lineage evidence citation failed (non-fatal)")

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
    # PremiseVerifier (faux présupposés)
    # ------------------------------------------------------------------

    def _maybe_premise_correction(
        self, inp: SynthesizeInput
    ) -> Optional[SynthesizeOutput]:
        """Si le PremiseVerifier détecte un faux présupposé → réponse corrective.

        Retourne None si désactivé, statut OK, ou erreur (fail-open : on laisse le
        pipeline normal répondre). Cf ADR_PREMISE_VERIFIER.md.
        """
        from knowbase.runtime_a3.premise_verifier import (
            PremiseVerifier, is_enabled as pv_enabled,
        )
        if not pv_enabled():
            return None
        try:
            if not hasattr(self, "_premise_verifier"):
                self._premise_verifier = PremiseVerifier()
            # Passer les claims que le pipeline a réellement trouvés (preuve riche →
            # évite les faux positifs UNSUPPORTED sur entités existantes mal-retrouvées).
            pipeline_texts: List[str] = []
            for c in _aggregate_claims(inp.execute_output)[:30]:
                extras = c.model_dump() if hasattr(c, "model_dump") else {}
                txt = extras.get("text") or c.value or c.value_normalized
                if not txt:
                    subj = c.subject_canonical or ""
                    pred = (c.predicate or "").replace("_", " ")
                    txt = f"{subj} {pred} {c.value or ''}".strip()
                if txt:
                    pipeline_texts.append(str(txt))
            result = self._premise_verifier.verify(
                inp.parse_output.raw_question, pipeline_evidence=pipeline_texts,
            )
        except Exception:
            logger.exception("[PREMISE] verify raised, fail-open (continue synthesize)")
            return None

        if not result.is_false_premise:
            return None

        # GARDE STABILITÉ (chantier 05/06) — FALSE_UNSUPPORTED ignoré sous
        # verdict Evaluate==CORRECT. ÉTAYÉ PAR LES DONNÉES (bench @70460ba,
        # 15 questions false_premise réelles) :
        #   - les détections RÉUSSIES viennent de FALSE_CONTRADICTED (3) ou de
        #     l'abstention normale — JAMAIS de FALSE_UNSUPPORTED ;
        #   - l'unique tir FALSE_UNSUPPORTED sur un vrai faux-présupposé
        #     (AERO_FP_0002) a été jugé 0.0 (la correction était mauvaise) ;
        #   - en face, FALSE_UNSUPPORTED tire à ~70% sur des questions
        #     ANSWERABLE (LIST_0003 : 3 flips/4 runs) → flips TEXT_ONLY.
        # FALSE_UNSUPPORTED = signal d'ABSENCE, structurellement contradictoire
        # avec un évaluateur qui vient de juger la question couverte par les
        # claims. FALSE_CONTRADICTED (le corpus CONTREDIT le présupposé) reste
        # souverain. Hors verdict CORRECT, FALSE_UNSUPPORTED s'applique normalement.
        if (
            os.getenv("V6_PREMISE_UNSUPPORTED_SKIP_ON_CORRECT", "1") == "1"
            and result.status == "FALSE_UNSUPPORTED"
            and inp.evaluate_output.verdict == "CORRECT"
        ):
            logger.info(
                "[PREMISE] FALSE_UNSUPPORTED ignoré (verdict=CORRECT — signal "
                "d'absence contredit par la couverture jugée complète)"
            )
            return None

        if result.correction:
            answer = result.correction
        elif result.status == "FALSE_CONTRADICTED":
            answer = ("Les documents indexés contredisent un présupposé de la question. "
                      "La réponse demandée ne peut donc pas être fournie telle quelle.")
        else:  # FALSE_UNSUPPORTED
            answer = ("Les documents indexés ne documentent pas l'élément spécifique évoqué "
                      "par la question ; il pourrait ne pas exister ou être hors périmètre.")

        return SynthesizeOutput(
            answer_text=answer,
            cited_claims=[],
            uncovered_sub_goals_warning=None,
            conflict_pending_warning=None,
            mode="TEXT_ONLY",  # réponse corrective ancrée corpus (pas un claim KG)
            synthesize_warnings=[f"premise_{result.status.lower()}"],
            citation_coverage_rate=1.0,
            schema_version="a3.0",
        )

    # ------------------------------------------------------------------
    # SufficiencyChecker (anti-sur-confiance)
    # ------------------------------------------------------------------

    def _maybe_sufficiency_abstention(
        self,
        inp: SynthesizeInput,
        filtered_claims: List[ClaimSummary],
    ) -> Optional[SynthesizeOutput]:
        """Si SufficiencyChecker activé et juge INSUFFICIENT/FALSE_PREMISE → abstention.

        Retourne None si check désactivé, SUFFICIENT, ou erreur (fail-open).
        """
        from knowbase.runtime_a3.sufficiency_checker import SufficiencyChecker, is_enabled

        if not is_enabled() or not filtered_claims:
            return None

        try:
            if not hasattr(self, "_sufficiency_checker"):
                self._sufficiency_checker = SufficiencyChecker()
            question = inp.parse_output.raw_question
            result = self._sufficiency_checker.check(question, filtered_claims)
        except Exception:
            logger.exception("[SUFFICIENCY] check raised, fail-open (continue synthesize)")
            return None

        if result.verdict == "SUFFICIENT":
            return None

        # INSUFFICIENT ou FALSE_PREMISE → abstention motivée
        if result.verdict == "FALSE_PREMISE":
            answer = (
                "La question semble reposer sur une prémisse que les documents "
                "indexés ne confirment pas. "
                f"({result.reasoning})\n\n"
                "Aucune réponse fiable ne peut être fournie sans risque d'erreur."
            )
            warning = "sufficiency_check: false_premise detected"
        else:  # INSUFFICIENT
            answer = (
                "Les documents indexés contiennent des informations proches mais "
                "ne couvrent pas précisément l'élément demandé dans la question. "
                f"({result.reasoning})\n\n"
                "Répondre avec les éléments disponibles risquerait d'être inexact."
            )
            warning = "sufficiency_check: insufficient evidence for the specific question"

        return SynthesizeOutput(
            answer_text=answer,
            cited_claims=[],
            uncovered_sub_goals_warning=warning,
            conflict_pending_warning=None,
            mode="ABSTENTION",
            synthesize_warnings=[f"sufficiency_{result.verdict.lower()}"],
            citation_coverage_rate=1.0,
            schema_version="a3.0",
        )

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
            uncovered_block = (
                "\n\n" + _i18n(_I18N_UNCOVERED_BLOCK, inp.parse_output) + ":\n"
                + "\n".join(uncovered_descs)
            )

        answer = (
            _i18n(_I18N_NO_CLAIM, inp.parse_output)
            + uncovered_block
            + "\n\n" + _i18n(_I18N_NEXT_STEPS, inp.parse_output)
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

    def _build_authority_conflict_fallback(
        self,
        inp: SynthesizeInput,
        claims: List[ClaimSummary],
        authority_conflicts: List[Dict[str, Any]],
    ) -> SynthesizeOutput:
        """Repli déterministe 2-côtés pour les questions comparison inter-autorités.

        Rend « <autorité A> (<doc A>) : <texte A> / <autorité B> (<doc B>) : <texte B> »
        et cite les claims des deux documents (matchés par source_doc_id). Garantit
        une réponse comparative attribuée même quand le LLM de synthèse échoue.
        """
        _wlbl = _i18n(_I18N_CONFLICT, inp.parse_output)
        # Équivalences d'unités (mêmes valeurs) ≠ divergences : présentées en
        # concordance, jamais sous le marqueur ⚠ (retour Fred 05/06).
        real = [ac for ac in authority_conflicts if not ac.get("equivalent")]
        equiv = [ac for ac in authority_conflicts if ac.get("equivalent")]
        lines: List[str] = []
        docs_cited: set = set()
        if real:
            lines.append(f"⚠ {_wlbl} :")
            for ac in real[:4]:
                a_lab = ac.get("authority_a") or ac.get("doc_a") or "?"
                b_lab = ac.get("authority_b") or ac.get("doc_b") or "?"
                lines.append(f"- {a_lab} ({ac.get('doc_a')}) : {ac.get('text_a')}")
                lines.append(f"- {b_lab} ({ac.get('doc_b')}) : {ac.get('text_b')}")
                docs_cited.add(ac.get("doc_a"))
                docs_cited.add(ac.get("doc_b"))
        _eq_lbl = _i18n(_I18N_EQUIVALENT, inp.parse_output)
        for ac in equiv[:4]:
            a_lab = ac.get("authority_a") or ac.get("doc_a") or "?"
            b_lab = ac.get("authority_b") or ac.get("doc_b") or "?"
            lines.append(
                f"✓ {a_lab} & {b_lab} — {_eq_lbl} : "
                f"{a_lab} « {ac.get('text_a')} » / {b_lab} « {ac.get('text_b')} »"
            )
            docs_cited.add(ac.get("doc_a"))
            docs_cited.add(ac.get("doc_b"))

        # Citations : les claims des documents impliqués (preuve verbatim)
        cited: List[CitedClaim] = []
        for c in claims:
            if getattr(c, "source_doc_id", None) in docs_cited:
                verbatim = c.value or c.value_normalized or f"(claim {c.claim_id})"
                cited.append(CitedClaim(
                    claim_id=c.claim_id,
                    claim_verbatim=str(verbatim),
                    doc_title=None,
                    section_id=None,
                ))
                if len(cited) >= 12:
                    break

        adw = None
        if real:
            pairs = ", ".join(
                f"{ac.get('authority_a') or ac.get('doc_a')}↔"
                f"{ac.get('authority_b') or ac.get('doc_b')}"
                for ac in real[:3]
            )
            adw = f"Divergence entre autorités réglementaires détectée ({pairs})."
        return SynthesizeOutput(
            answer_text="\n".join(lines),
            cited_claims=cited,
            conflict_pending_warning=None,
            authority_divergence_warning=adw,
            mode="REASONED",
            synthesize_warnings=["template_fallback_authority_conflict"],
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

        # Repli COMPARISON-aware : si des contradictions inter-autorités existent
        # (FAA vs EASA…), produire une réponse 2-côtés ATTRIBUÉE plutôt qu'une liste
        # de claims bruts. Couvre exactement les questions comparison qui échouaient
        # le plus (timeout synthèse sur gros prompt 2-côtés).
        authority_conflicts = _aggregate_authority_conflicts(inp.execute_output)
        if authority_conflicts:
            return self._build_authority_conflict_fallback(inp, claims, authority_conflicts)

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
            _ulbl = _i18n(_I18N_UNCOVERED, inp.parse_output)
            uncovered_warning = f"{_ulbl}: {uncov_idx}."
            answer_text += f"\n\n⚠ {_ulbl}: {uncov_idx}"

        cps = _aggregate_conflict_pending_summaries(inp.execute_output)
        cp_warning = None
        if cps:
            cp_ids = [cp["conflict_id"] for cp in cps]
            _clbl = _i18n(_I18N_CONFLICT, inp.parse_output)
            cp_warning = f"{_clbl}: {cp_ids}."
            answer_text += f"\n\n⚠ {_clbl}: {cp_ids}"

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
