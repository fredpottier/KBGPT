"""
Agentic Synthesis — CH-39.2.

Single LLM call replacing :
- runtime_v2/synthesis.py (response generation)
- runtime_v2/premise_validator.py (false premise detection)
- runtime_v2/lifecycle_filter.py (DEPRECATED demote heuristic)
- Half of llm_filter.py (relevance filtering done by reading evidence)

The prompt asks the LLM to perform — IN ONE CALL — :
1. Detect the question's subject and presuppositions semantically
2. Read all evidence claims (with metadata: doc_id, lifecycle_status, publication_date)
3. Decide : extract answer / reject false premise / abstain
4. Output structured JSON for downstream validation

DOMAIN-AGNOSTIC by construction — no hardcoded patterns, lists, or examples
specific to a domain. The LLM uses semantic understanding for everything.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


AGENTIC_SYNTHESIS_PROMPT = """You are an evidence-locked synthesis agent for a domain-agnostic Q&A system.

Given a USER QUESTION and a list of EVIDENCE CLAIMS (each with metadata: doc_id, lifecycle_status, publication_date), produce a structured answer.

## Decision flow

For each question, decide ONE of three outcomes:

### A. ANSWER — Extract from evidence
The evidence supports a substantive response. Synthesize it citing the doc_ids verbatim.

### B. REJECT_FALSE_PREMISE — The question contains an unsupported assertion
The question asserts a specific fact (a value, identifier, scope, exclusivity, or causal claim) that the evidence contradicts. Examples of false premise patterns (cross-domain):
- regulatory: "Why does X require N days?" — but evidence shows different N
- software: "Why was feature F introduced in v1.0?" — but evidence shows v2.0
- medical: "Why does drug X require N mg?" — but evidence shows different N
- legal: "Why does clause A waive all liability?" — but evidence shows partial waiver
- product: "Why does only entity X have access?" — but evidence shows X and Y

Output explicitly states the evidence-supported correction.

### C. ABSTAIN — Evidence does not address the question
None of the evidence claims contain (verbatim, paraphrased, or implied) information answering the question. Honest abstention is preferable to invented answers.

## Critical rules

1. **Same language as the question** (English/French/etc — detect automatically).
2. **Cross-lingual semantic equivalence is FULL support**. Evidence in any language supports
   claims in any language when meaning matches. Examples (apply across all domains):
   - "is replaced" / "remplacé" / "ersetzt" / "sostituito" — replacement
   - "deprecated" / "obsolète" / "veraltet" / "obsoleto" — obsolescence
   - "in force" / "en vigueur" / "in Kraft" / "in vigore" — active state
3. **Inference from context is SUPPORT**. If claim "X has replaced Y" is supported by
   evidence A "Y is repealed" + evidence B "X is the new framework" → that's supported.
4. **Numerical/identifier mismatch = false premise**. If question claims value/ID N1 and
   evidence has N2, that's a false premise (output type B).
5. **Lifecycle awareness**. If the question asks about CURRENT state (no past date) AND
   the most relevant evidence comes from a doc with lifecycle_status=DEPRECATED, prefer
   evidence from ACTIVE docs OR explicitly note the historical nature.
6. **Citations are mandatory** in answer text : [doc=<doc_id>] inline.
7. **Be concise** : 2-4 sentences for normal questions, up to 6 for synthesis.
8. **🚨 REPRODUCE IDENTIFIERS EXACTLY**. Numbers, IDs, dates, codes must be copied
   character-by-character from the evidence. NEVER invert, abbreviate, or "guess close"
   on these. Examples of FATAL errors to avoid :
   - Inverting digits : evidence "2021/821" → answer "821/2021" (WRONG)
   - Abbreviating dates : evidence "20 May 2021" → answer "May 2021" (LOSES PRECISION)
   - Approximating numbers : evidence "21 J" → answer "20 J" (FALSE)
   When unsure, COPY the identifier verbatim from the evidence text.

9. **For "Pourquoi/Why X..." questions** (CH-39.7 fix causal_why) :
   a. FIRST verify the premise X is supported by evidence. If contradicted →
      REJECT_FALSE_PREMISE. If unverifiable → ABSTAIN.
   b. If premise X IS supported → produce a RICH causal explanation by drawing
      from MULTIPLE evidence claims when available. The answer should include :
      - The cause / mechanism / motivation (the actual "why")
      - Supporting evidence pieces (cite multiple [doc=X] when relevant)
      - Any qualifying conditions, scope, or exceptions visible in the evidence
   c. Aim for **3-5 sentences** for "why" questions (not 1-2). A good "why" answer
      synthesizes context across multiple chunks rather than picking the single most
      similar one.

## Output format — STRICT JSON ONLY

```
{
  "decision": "ANSWER" | "REJECT_FALSE_PREMISE" | "ABSTAIN",
  "answer": "<prose answer with [doc=...] citations>",
  "false_premise_detected": false | true,
  "false_premise_correction": "<if false premise: state the evidence-supported correction>" | null,
  "abstention_reason": "<if abstain: why the evidence is insufficient>" | null,
  "doc_ids_cited": ["<doc_id_1>", "<doc_id_2>"],
  "confidence": 0.0..1.0,
  "subject": "<the entity/concept the question is about>",
  "presupposition_check": "<the implicit assumption of the question, and whether it holds>"
}
```

NO markdown, NO commentary outside JSON, NO partial JSON. Always return valid JSON.
"""


@dataclass
class SynthesisOutput:
    """Output structuré de la synthèse agentic."""
    decision: str = "ABSTAIN"  # ANSWER | REJECT_FALSE_PREMISE | ABSTAIN
    answer: str = ""
    false_premise_detected: bool = False
    false_premise_correction: Optional[str] = None
    abstention_reason: Optional[str] = None
    doc_ids_cited: list[str] = field(default_factory=list)
    confidence: float = 0.0
    subject: str = ""
    presupposition_check: str = ""
    # Meta
    raw_response: str = ""
    parse_error: Optional[str] = None
    latency_s: float = 0.0


def _build_evidence_block(claims: list[Any], max_claims: int = 10, max_chars_per_claim: int = 500) -> str:
    """Construit le bloc evidence pour le prompt avec metadata enrichie."""
    lines = []
    used = claims[:max_claims]
    for i, c in enumerate(used, 1):
        text = getattr(c, "text", None) if not isinstance(c, dict) else c.get("text", "")
        text = re.sub(r"\s+", " ", (text or "")[:max_chars_per_claim]).strip()
        doc_id = getattr(c, "doc_id", None) if not isinstance(c, dict) else c.get("doc_id", "unknown")
        lifecycle = getattr(c, "lifecycle_status", None) if not isinstance(c, dict) else c.get("lifecycle_status")
        pub_date = getattr(c, "publication_date", None) if not isinstance(c, dict) else c.get("publication_date")
        meta_bits = [f"doc_id={doc_id}"]
        if lifecycle:
            meta_bits.append(f"lifecycle_status={lifecycle}")
        if pub_date:
            meta_bits.append(f"publication_date={pub_date}")
        meta = " | ".join(meta_bits)
        lines.append(f"[E{i}] {meta}\n    text: {text}")
    return "\n".join(lines) if lines else "(no evidence claims)"


def _parse_json_response(raw: str) -> dict:
    """Parse robuste de la réponse JSON LLM."""
    # Strip markdown code fences si présents
    raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    raw = re.sub(r"\s*```\s*$", "", raw)
    # Trouve le premier JSON object
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        raise ValueError("no JSON object found in response")
    return json.loads(m.group())


def synthesize(
    question: str,
    claims: list[Any],
    timeout: float = 120.0,
    temperature: float = 0.2,
    max_tokens: int = 800,
) -> SynthesisOutput:
    """Single-call agentic synthesis.

    Args:
        question: question utilisateur
        claims: evidence claims with .text, .doc_id, optional .lifecycle_status, .publication_date
        timeout: HTTP timeout LLM
        temperature: sampling
        max_tokens: max output tokens

    Returns:
        SynthesisOutput with structured JSON fields parsed.
    """
    import time
    out = SynthesisOutput()
    t0 = time.time()

    if not claims:
        out.decision = "ABSTAIN"
        out.abstention_reason = "no_evidence_retrieved"
        out.answer = "Je ne peux pas répondre : aucune evidence n'a été retrouvée pour cette question."
        out.latency_s = time.time() - t0
        return out

    evidence_block = _build_evidence_block(claims)
    user_prompt = (
        f"QUESTION: {question}\n\n"
        f"EVIDENCE CLAIMS:\n{evidence_block}\n\n"
        f"Now produce the JSON output following the schema. Return JSON only."
    )

    try:
        from knowbase.runtime_v3.llm_client import get_runtime_llm_client
        client = get_runtime_llm_client()
        raw = client.chat_completion(
            messages=[
                {"role": "system", "content": AGENTIC_SYNTHESIS_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=True,
            timeout=timeout,
        )
        out.raw_response = raw or ""
    except Exception as exc:  # noqa: BLE001
        logger.error("[AGENTIC_SYNTH] LLM call failed: %s", exc)
        out.parse_error = f"llm_call_failed:{type(exc).__name__}"
        out.decision = "ABSTAIN"
        out.abstention_reason = f"synthesis_unavailable:{type(exc).__name__}"
        out.answer = "Erreur synthèse LLM — abstention par défaut."
        out.latency_s = time.time() - t0
        return out

    try:
        data = _parse_json_response(raw)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[AGENTIC_SYNTH] JSON parse failed: %s — raw=%r", exc, raw[:300])
        out.parse_error = f"parse_error:{type(exc).__name__}"
        # Fallback : utiliser le raw text comme answer brute
        out.decision = "ANSWER"
        out.answer = raw.strip()
        out.confidence = 0.3  # low confidence sur fallback
        out.latency_s = time.time() - t0
        return out

    # Map JSON fields → SynthesisOutput
    decision = (data.get("decision") or "ABSTAIN").strip().upper()
    if decision not in {"ANSWER", "REJECT_FALSE_PREMISE", "ABSTAIN"}:
        decision = "ABSTAIN"
    out.decision = decision
    raw_answer = data.get("answer")
    if raw_answer is None:
        out.answer = ""
    else:
        out.answer = str(raw_answer)[:3000]
    out.false_premise_detected = bool(data.get("false_premise_detected", False))
    out.false_premise_correction = data.get("false_premise_correction")
    out.abstention_reason = data.get("abstention_reason")
    out.doc_ids_cited = [str(d) for d in (data.get("doc_ids_cited") or []) if d]
    try:
        out.confidence = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
    except Exception:
        out.confidence = 0.5
    out.subject = str(data.get("subject", ""))[:200]
    out.presupposition_check = str(data.get("presupposition_check", ""))[:300]
    out.latency_s = time.time() - t0

    logger.info(
        "[AGENTIC_SYNTH] decision=%s false_premise=%s confidence=%.2f cited=%d latency=%.1fs",
        out.decision, out.false_premise_detected, out.confidence,
        len(out.doc_ids_cited), out.latency_s,
    )
    return out


def regenerate_with_feedback(
    question: str,
    claims: list[Any],
    previous_output: SynthesisOutput,
    faithfulness_feedback: str,
    timeout: float = 120.0,
) -> SynthesisOutput:
    """Régénération conditionnelle avec feedback faithfulness.

    Used quand le NLI judge dit UNFAITHFUL : on demande au LLM de réviser
    en se concentrant sur les claims problématiques.
    """
    feedback_prompt = (
        f"PREVIOUS ANSWER (judged unfaithful) :\n{previous_output.answer}\n\n"
        f"FAITHFULNESS FEEDBACK :\n{faithfulness_feedback}\n\n"
        f"INSTRUCTIONS for revision :\n"
        f"1. Identify which specific tokens (identifiers, numbers, dates) in the previous "
        f"answer caused the unsupported verdict.\n"
        f"2. If those tokens have a CORRECT counterpart in the evidence (e.g. answer wrote "
        f"'821/2021' but evidence has '2021/821') → FIX the answer with the verbatim correct value.\n"
        f"3. If the underlying CLAIM is supported by the evidence (just wrong wording or token), "
        f"PRODUCE a corrected answer (decision=ANSWER) with verbatim-copied tokens.\n"
        f"4. ONLY abstain (decision=ABSTAIN) if the corrected claim is NOT supported by any "
        f"evidence chunk.\n"
        f"5. ONLY reject premise (decision=REJECT_FALSE_PREMISE) if the evidence shows the "
        f"question's assertion is genuinely contradicted.\n\n"
        f"Return JSON only."
    )

    evidence_block = _build_evidence_block(claims)
    user_prompt = (
        f"QUESTION: {question}\n\n"
        f"EVIDENCE CLAIMS:\n{evidence_block}\n\n"
        f"{feedback_prompt}"
    )

    out = SynthesisOutput()
    import time
    t0 = time.time()
    try:
        from knowbase.runtime_v3.llm_client import get_runtime_llm_client
        client = get_runtime_llm_client()
        raw = client.chat_completion(
            messages=[
                {"role": "system", "content": AGENTIC_SYNTHESIS_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,  # plus déterministe sur regen
            max_tokens=800,
            json_mode=True,
            timeout=timeout,
        )
        out.raw_response = raw or ""
        data = _parse_json_response(raw)
        out.decision = (data.get("decision") or "ABSTAIN").strip().upper()
        out.answer = str(data.get("answer", ""))[:3000]
        out.false_premise_detected = bool(data.get("false_premise_detected", False))
        out.false_premise_correction = data.get("false_premise_correction")
        out.abstention_reason = data.get("abstention_reason")
        out.doc_ids_cited = [str(d) for d in (data.get("doc_ids_cited") or []) if d]
        try:
            out.confidence = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
        except Exception:
            out.confidence = 0.5
    except Exception as exc:  # noqa: BLE001
        logger.warning("[AGENTIC_SYNTH] Regen failed: %s — keeping previous", exc)
        out = previous_output  # fallback : keep previous
    out.latency_s = time.time() - t0
    return out
