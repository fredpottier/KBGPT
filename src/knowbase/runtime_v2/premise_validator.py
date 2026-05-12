"""
Premise Validator — CH-32.A.

Pattern "Don't Let It Hallucinate" (arxiv 2504.06438, Apr 2025) :
détecte les présuppositions d'une question et vérifie qu'elles sont
supportées par l'evidence du KG. Si une présupposition est contredite,
flag "false premise" pour orienter le synthesizer vers une réponse de rejet.

Domain-agnostic : 2 LLM calls maximum (extraction + NLI), aucune
heuristique métier, aucun regex spécifique au corpus.

Performance attendue (paper) : F1 59→97% sur KG-FPQ, +0.6s latence sur tâches
simples (notre cas en ajoute ~5-15s à cause de Qwen3-235B vs modèle dédié).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


PRESUPPOSITION_EXTRACTION_PROMPT = """You are a presupposition extractor for a domain-agnostic question answering system.

A presupposition is an assertion that the question takes for granted as TRUE. If the presupposition is FALSE, the question is unanswerable as posed (it has a false premise).

Examples (domain-agnostic, multilingue):
- "Why does Regulation X prohibit ALL exports?" -> presupposes "Regulation X prohibits all exports"
- "What was Einstein's grade in fifth grade?" -> presupposes "Einstein had a fifth grade record"
- "Comment Apple a-t-il licencié son fondateur en 2010 ?" -> presupposes "Apple a licencié son fondateur en 2010"
- "Pourquoi le délai d'évaluation est-il de 60 jours dans le règlement 2021/821 ?" -> presupposes "Le délai d'évaluation est de 60 jours dans le règlement 2021/821"

What to extract:
- FALSIFIABLE FACTUAL claims that the question takes for granted
- Universal quantifiers ("all", "tous", "every", "any") that may be too strong
- Specific values, dates, identifiers asserted as true
- Causal/agency claims ("X does Y", "X requires Y")

What NOT to extract:
- Generic "what is X?" questions where X just defines a concept (no factual presupposition)
- Subjective or opinion claims
- Claims that simply rephrase the question

Rules:
1. Use the SAME LANGUAGE as the question.
2. Be PARSIMONIOUS — 0 to 3 presuppositions max, prefer 1-2.
3. Each presupposition must be SELF-CONTAINED and CHECKABLE against documents.
4. If the question has no checkable presupposition (e.g. open-ended "What is X?"), return empty list.

OUTPUT — STRICT JSON ONLY:
{
  "presuppositions": [
    {
      "text": "the presupposed assertion as a standalone statement",
      "must_contain": ["key", "tokens", "or", "identifiers"]
    }
  ]
}
"""


NLI_CHECK_PROMPT = """Determine whether the following EVIDENCE supports, contradicts, or is neutral toward an ASSERTION.

Definitions:
- SUPPORTS = the evidence explicitly states, strongly implies, OR is semantically equivalent
  to the assertion being TRUE. Cross-lingual paraphrase counts as support.
- CONTRADICTS = the evidence explicitly states or strongly implies the assertion is FALSE
  (e.g. evidence shows exceptions when assertion claims "all" or "always" ;
   evidence shows different value when assertion claims a specific value ;
   evidence shows the entity is missing or the action did not occur).
- NEUTRAL = the evidence neither supports nor contradicts (just adjacent topics
  or insufficient detail to judge).

⚠️ CROSS-LINGUAL SEMANTIC EQUIVALENCE rule (CH-36 B.2):
Evidence in English supports French assertions (and vice versa) when meaning matches.
Examples:
- Assertion FR: "Le règlement 2021/821 a remplacé le 428/2009"
  Evidence EN: "Regulation (EC) No 428/2009 is repealed [by 2021/821]" → SUPPORTS
- Assertion FR: "L'amendement 28 entre en vigueur le 15 décembre 2023"
  Evidence EN: "Amendment 28 enters into force on 15 December 2023" → SUPPORTS

⚠️ INFERENCE FROM CONTEXT rule:
Don't require verbatim term match. If multiple evidence pieces taken together logically
imply the assertion → SUPPORTS. Example: assertion "X has replaced Y" + evidence
"Y is repealed" + evidence "X establishes the new regime" → SUPPORTS.

Be DOMAIN-AGNOSTIC. Default to NEUTRAL only when evidence is genuinely silent or off-topic,
NOT when evidence uses different wording or different language.

OUTPUT — STRICT JSON ONLY:
{
  "verdict": "SUPPORTS" | "CONTRADICTS" | "NEUTRAL",
  "confidence": 0.0..1.0,
  "reasoning": "one short sentence explaining the verdict",
  "key_evidence_ids": [<integer ids from the evidence list>]
}
"""


FAST_MODEL = "mistralai/Mistral-Small-3.1-24B-Instruct-2503"


@dataclass
class PresuppositionCheck:
    """Résultat de la vérification d'une présupposition."""
    presupposition: str
    must_contain: list[str] = field(default_factory=list)
    verdict: str = "NEUTRAL"  # SUPPORTS | CONTRADICTS | NEUTRAL
    confidence: float = 0.0
    reasoning: str = ""
    contradicting_evidence: list[dict] = field(default_factory=list)
    supporting_evidence: list[dict] = field(default_factory=list)


@dataclass
class PremiseValidationResult:
    """Résultat global de la validation de prémisse."""
    has_false_premise: bool = False
    n_presuppositions: int = 0
    presuppositions: list[PresuppositionCheck] = field(default_factory=list)
    diagnostic: dict = field(default_factory=dict)


def _extract_presuppositions(question: str, timeout: float = 30.0) -> list[dict]:
    """LLM extract presuppositions from the question."""
    from knowbase.runtime_v2.llm_client import get_runtime_llm_client

    client = get_runtime_llm_client()
    raw = client.chat_completion(
        messages=[
            {"role": "system", "content": PRESUPPOSITION_EXTRACTION_PROMPT},
            {"role": "user", "content": f"Question: {question}\n\nExtract presuppositions:"},
        ],
        temperature=0.0,
        max_tokens=300,
        json_mode=True,
        timeout=timeout,
        model_override=FAST_MODEL,
    )
    m = re.search(r"\{[\s\S]*\}", raw or "")
    if not m:
        return []
    try:
        data = json.loads(m.group())
        out = data.get("presuppositions") or []
        # Sanitize
        clean = []
        for p in out:
            txt = (p.get("text") or "").strip()
            if not txt:
                continue
            mc = p.get("must_contain") or []
            if not isinstance(mc, list):
                mc = []
            mc = [str(t).strip() for t in mc if t and str(t).strip()][:6]
            clean.append({"text": txt, "must_contain": mc})
        return clean[:3]  # max 3 presuppositions
    except Exception as e:
        logger.warning(f"[PREMISE_EXTRACT] JSON parse failed: {e}")
        return []


def _nli_check(presupposition: str, claims: list[Any], timeout: float = 30.0) -> dict:
    """LLM NLI check : evidence (claims) vs assertion (presupposition)."""
    from knowbase.runtime_v2.llm_client import get_runtime_llm_client

    if not claims:
        return {"verdict": "NEUTRAL", "confidence": 0.0, "reasoning": "no_evidence", "key_evidence_ids": []}

    evidence_lines = []
    for i, c in enumerate(claims[:5], 1):
        text = (getattr(c, "text", None) or "")[:400]
        text = re.sub(r"\s+", " ", text).strip()
        evidence_lines.append(f"[{i}] {text}")
    evidence_block = "\n".join(evidence_lines)

    user = (
        f"EVIDENCE:\n{evidence_block}\n\n"
        f"ASSERTION: {presupposition}\n\n"
        f"Return JSON only."
    )

    client = get_runtime_llm_client()
    raw = client.chat_completion(
        messages=[
            {"role": "system", "content": NLI_CHECK_PROMPT},
            {"role": "user", "content": user},
        ],
        temperature=0.0,
        max_tokens=200,
        json_mode=True,
        timeout=timeout,
        model_override=FAST_MODEL,
    )
    m = re.search(r"\{[\s\S]*\}", raw or "")
    if not m:
        return {"verdict": "NEUTRAL", "confidence": 0.0, "reasoning": "parse_fail", "key_evidence_ids": []}
    try:
        data = json.loads(m.group())
        verdict = (data.get("verdict") or "NEUTRAL").strip().upper()
        if verdict not in {"SUPPORTS", "CONTRADICTS", "NEUTRAL"}:
            verdict = "NEUTRAL"
        try:
            conf = float(data.get("confidence", 0.5))
        except Exception:
            conf = 0.5
        return {
            "verdict": verdict,
            "confidence": max(0.0, min(1.0, conf)),
            "reasoning": str(data.get("reasoning", ""))[:200],
            "key_evidence_ids": data.get("key_evidence_ids") or [],
        }
    except Exception as e:
        logger.warning(f"[PREMISE_NLI] parse failed: {e}")
        return {"verdict": "NEUTRAL", "confidence": 0.0, "reasoning": "parse_fail", "key_evidence_ids": []}


def validate_premise(
    question: str,
    retriever,
    doc_ids: Optional[list[str]] = None,
    skip_for_short: bool = True,
    min_question_length: int = 30,
    top_k_per_presup: int = 5,
    contradiction_threshold: float = 0.6,
) -> PremiseValidationResult:
    """Top-level entry point.

    Args:
        question: question utilisateur
        retriever: ClaimRetriever (déjà instancié dans pipeline)
        doc_ids: scope du retrieve (None = tous docs)
        skip_for_short: skip pour questions courtes (économie cost)
        min_question_length: seuil sous lequel skip (default 30 chars)
        top_k_per_presup: nb claims retrieve par présupposition
        contradiction_threshold: confidence minimale pour flag CONTRADICTS

    Returns:
        PremiseValidationResult avec has_false_premise et détails par présup.
    """
    result = PremiseValidationResult()

    if skip_for_short and len(question.strip()) < min_question_length:
        result.diagnostic["skip_reason"] = "question_too_short"
        return result

    try:
        presuppositions = _extract_presuppositions(question)
    except Exception as e:
        logger.warning(f"[PREMISE_VALIDATE] extract failed: {e}")
        result.diagnostic["extract_error"] = f"{type(e).__name__}: {e}"
        return result

    result.n_presuppositions = len(presuppositions)
    result.diagnostic["n_presuppositions"] = len(presuppositions)

    if not presuppositions:
        return result

    for p in presuppositions:
        # Retrieve evidence ciblée pour cette présupposition (texte + tokens must)
        retrieve_text = p["text"]
        if p.get("must_contain"):
            retrieve_text = f"{p['text']} {' '.join(p['must_contain'])}"
        try:
            claims = retriever.retrieve(retrieve_text, doc_ids=doc_ids, top_k=top_k_per_presup)
        except Exception as e:
            logger.warning(f"[PREMISE_VALIDATE] retrieve failed: {e}")
            claims = []

        try:
            nli = _nli_check(p["text"], claims)
        except Exception as e:
            logger.warning(f"[PREMISE_VALIDATE] NLI failed: {e}")
            nli = {"verdict": "NEUTRAL", "confidence": 0.0, "reasoning": f"nli_error:{type(e).__name__}", "key_evidence_ids": []}

        check = PresuppositionCheck(
            presupposition=p["text"],
            must_contain=p.get("must_contain") or [],
            verdict=nli["verdict"],
            confidence=nli["confidence"],
            reasoning=nli["reasoning"],
        )

        ev_ids = [i for i in (nli.get("key_evidence_ids") or []) if isinstance(i, int)]
        evidence_pack = []
        for i in ev_ids:
            if 1 <= i <= len(claims):
                c = claims[i - 1]
                evidence_pack.append({
                    "claim_id": getattr(c, "claim_id", None),
                    "doc_id": getattr(c, "doc_id", None),
                    "text": (getattr(c, "text", None) or "")[:300],
                })

        if check.verdict == "CONTRADICTS" and check.confidence >= contradiction_threshold:
            check.contradicting_evidence = evidence_pack
            result.has_false_premise = True
        elif check.verdict == "SUPPORTS" and check.confidence >= 0.5:
            check.supporting_evidence = evidence_pack

        result.presuppositions.append(check)

    logger.info(
        f"[PREMISE_VALIDATE] q_len={len(question)} n_presup={result.n_presuppositions} "
        f"false_premise={result.has_false_premise} verdicts="
        f"{[(p.verdict, round(p.confidence, 2)) for p in result.presuppositions]}"
    )
    return result


def build_false_premise_response(
    question: str,
    result: PremiseValidationResult,
) -> str:
    """Construit une réponse formattée quand une fausse prémisse a été détectée.

    Domain-agnostic, multilingue : la première phrase explique le problème,
    la suite cite l'évidence contradictoire.
    """
    if not result.has_false_premise:
        return ""

    # Détection langue heuristique : si question contient majoritairement français → FR
    q_lower = question.lower()
    is_french = any(t in q_lower for t in [" le ", " la ", " les ", " est ", " sont ", " pour ", " avec "])

    contradicted = [p for p in result.presuppositions if p.verdict == "CONTRADICTS"]
    if not contradicted:
        return ""

    # Préfixe + raisonnement + citations
    parts = []
    if is_french:
        parts.append("**Attention — la question contient une prémisse qui n'est pas confirmée par les sources.**")
    else:
        parts.append("**Note — the question contains a premise that is not supported by the sources.**")

    for p in contradicted:
        if is_french:
            parts.append(f"\nLa prémisse \"{p.presupposition}\" est contredite par l'évidence : {p.reasoning}.")
        else:
            parts.append(f"\nThe premise \"{p.presupposition}\" is contradicted by the evidence: {p.reasoning}.")

        # citations
        for ev in p.contradicting_evidence[:2]:
            doc = ev.get("doc_id") or "unknown"
            txt = (ev.get("text") or "")[:200]
            parts.append(f"  [doc={doc}] {txt}")

    return "\n".join(parts)
