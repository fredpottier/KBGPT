"""
Faithfulness NLI Judge — CH-32.B.

Vérifie post-synthèse que chaque assertion factuelle de la réponse est
ancrée (entailed) dans l'evidence (claims retenus). Si la réponse n'est
pas suffisamment supportée, renvoyer un signal pour régénérer ou abstenir.

Pattern : LLM-as-NLI-judge avec décomposition atomique légère
(Min et al. 2023 FActScore + VeriFastScore May 2025 + VeriCite Oct 2025).

Domain-agnostic. ~1-2 LLM calls par vérification (1 décomposition + 1 judge).

Notes :
- Pour optimiser à terme : remplacer par Vectara HHEM-2.1-Open
  (huggingface vectara/hallucination_evaluation_model, T5-based, multilingue
  FR/EN/DE, ~600MB, <1s CPU). Cette version utilise RuntimeLLMClient
  (Qwen2.5-72B/14B) pour rester sans nouvelle dépendance modèle.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


FAITHFULNESS_JUDGE_PROMPT = """You are a faithfulness judge for a domain-agnostic RAG system.

Given a generated ANSWER and the EVIDENCE that was retrieved, your job is to:
1. Decompose the answer into atomic factual claims (each a single, verifiable statement).
2. For each atomic claim, judge whether it is SUPPORTED by the evidence.

Definitions:
- SUPPORTED = the claim is explicitly stated, strongly implied, OR semantically equivalent
  to content in at least one evidence passage. Cross-lingual paraphrase counts as support.
- UNSUPPORTED = the claim is not present in the evidence (the LLM may have invented it,
  paraphrased something else incorrectly, or pulled from prior knowledge).
- NEUTRAL = the claim is a generic/non-factual statement (a definition, a connector,
  a meta-comment like "the evidence does not specify..."), not a factual assertion to verify.

Rules:
1. Be DOMAIN-AGNOSTIC : do not assume vocabulary or domain.
2. Be STRICT but FAIR : a claim that paraphrases evidence in different wording is SUPPORTED
   if the meaning is preserved (don't penalize for synonyms or restructuring).
3. ⚠️ CROSS-LINGUAL SEMANTIC EQUIVALENCE : evidence in any language supports claims in any
   language when the meaning matches. Examples of equivalent expressions across languages:
   - "is replaced" / "remplacé" / "ersetzt" / "sustituido" / "sostituito" — replacement
   - "is deprecated" / "obsolète" / "veraltet" / "obsoleto" — obsolescence
   - "is mandatory" / "obligatoire" / "obligatorisch" / "obbligatorio" — obligation
   - "supersedes" / "abrogé" / "superato" — superseding
   - "enters into force" / "entre en vigueur" / "tritt in Kraft" / "entra in vigore" — activation
   - "complies with" / "respecte" / "entspricht" / "cumple con" — compliance
4. ⚠️ INFERENCE FROM CONTEXT : if the answer states "X has replaced Y" and one evidence
   passage mentions "Y is repealed/deprecated" while another mentions "X" as the new
   version/regime → SUPPORTED (the connection is inferable). This applies across domains:
   - regulatory: "Regulation A replaced Regulation B"
   - software: "v2.0 deprecated v1.x APIs"
   - medical: "drug A superseded drug B for indication Z"
   - legal: "contract clause A revised by amendment B"
5. Numerical values, dates, identifiers (article numbers, regulation IDs, version codes,
   medical doses, error codes, currency amounts) must match the evidence EXACTLY to be
   SUPPORTED. A different value = UNSUPPORTED.
6. Citation tokens like [doc=xxx] in the answer are NOT factual claims to verify.
7. Sentences expressing abstention ("the evidence does not contain...", "is not specified")
   are NEUTRAL, not UNSUPPORTED.

Examples of CORRECT verdicts (cross-domain illustrations):
- Claim: "X has replaced Y" / Evidence: "Y is repealed" + "X establishes the new framework"
  → SUPPORTED (replacement implied by repeal + new regime)

- Claim: "Amendement 28 entered into force on 15 December 2023"
  Evidence: "L'Amendement 28 entre en vigueur le 15 décembre 2023"
  → SUPPORTED (cross-lingual identity)

- Claim: "The maximum dose is 200 mg/day"
  Evidence: "maximum daily dose 100 mg/day"
  → UNSUPPORTED (numerical mismatch 200 vs 100)

- Claim: "Version 3.0 introduced async/await"
  Evidence: "Async/await was introduced in v3.0 changelog"
  → SUPPORTED (synonymous, version match)

OUTPUT — STRICT JSON ONLY:
{
  "atomic_claims": [
    {
      "claim": "<atomic factual statement extracted from the answer>",
      "verdict": "SUPPORTED" | "UNSUPPORTED" | "NEUTRAL",
      "confidence": 0.0..1.0,
      "evidence_ids": [<ids of evidence passages that support, if any>],
      "reasoning": "<one short sentence>"
    }
  ],
  "overall_faithfulness": 0.0..1.0,
  "overall_verdict": "FAITHFUL" | "PARTIAL" | "UNFAITHFUL"
}

Compute overall_faithfulness as : (n_SUPPORTED + 0.5 * n_NEUTRAL) / max(1, n_factual)
where n_factual = n_SUPPORTED + n_UNSUPPORTED (NEUTRAL excluded from denominator).
Compute overall_verdict :
- FAITHFUL    if overall_faithfulness >= 0.8
- PARTIAL     if overall_faithfulness >= 0.5
- UNFAITHFUL  if overall_faithfulness < 0.5
"""


@dataclass
class AtomicClaimVerdict:
    claim: str
    verdict: str  # SUPPORTED | UNSUPPORTED | NEUTRAL
    confidence: float = 0.0
    evidence_ids: list[int] = field(default_factory=list)
    reasoning: str = ""


@dataclass
class FaithfulnessReport:
    overall_faithfulness: float = 1.0
    overall_verdict: str = "FAITHFUL"  # FAITHFUL | PARTIAL | UNFAITHFUL
    atomic_claims: list[AtomicClaimVerdict] = field(default_factory=list)
    n_factual: int = 0
    n_supported: int = 0
    n_unsupported: int = 0
    n_neutral: int = 0
    diagnostic: dict = field(default_factory=dict)
    judge_called: bool = False
    fallback_reason: Optional[str] = None


FAST_MODEL = "mistralai/Mistral-Small-3.1-24B-Instruct-2503"


def judge_faithfulness(
    answer: str,
    claims: list[Any],
    timeout: float = 60.0,
    skip_min_chars: int = 30,
    max_evidence_chars_per_claim: int = 400,
    max_evidence_claims: int = 8,
    model_override: Optional[str] = FAST_MODEL,
) -> FaithfulnessReport:
    """Évalue la fidélité de `answer` par rapport aux `claims`.

    Args:
        answer: réponse synthétisée par le LLM
        claims: liste d'EvidenceClaim-like (.claim_id, .text, .doc_id, .score)
        timeout: HTTP timeout LLM
        skip_min_chars: skip si réponse trop courte (rien à juger)
        max_evidence_chars_per_claim: borne par claim
        max_evidence_claims: borne nombre de claims envoyés au juge

    Returns:
        FaithfulnessReport.
    """
    report = FaithfulnessReport()

    if not answer or len(answer.strip()) < skip_min_chars:
        report.fallback_reason = "answer_too_short"
        report.diagnostic["skip_reason"] = "answer_too_short"
        return report

    if not claims:
        report.fallback_reason = "no_evidence"
        report.overall_verdict = "UNFAITHFUL"
        report.overall_faithfulness = 0.0
        report.diagnostic["skip_reason"] = "no_evidence"
        return report

    # Build evidence block (id-référencé pour traçabilité)
    used = list(claims[:max_evidence_claims])
    ev_lines = []
    for i, c in enumerate(used, 1):
        text = (getattr(c, "text", None) or "")[:max_evidence_chars_per_claim]
        text = re.sub(r"\s+", " ", text).strip()
        ev_lines.append(f"[{i}] doc={getattr(c, 'doc_id', '?')} {text}")
    evidence_block = "\n".join(ev_lines)

    user = (
        f"EVIDENCE (id-referenced):\n{evidence_block}\n\n"
        f"ANSWER:\n{answer}\n\n"
        f"Decompose the answer into atomic claims and judge each. Return JSON only."
    )

    try:
        from knowbase.runtime_v2.llm_client import get_runtime_llm_client
        client = get_runtime_llm_client()
        report.judge_called = True
        raw = client.chat_completion(
            messages=[
                {"role": "system", "content": FAITHFULNESS_JUDGE_PROMPT},
                {"role": "user", "content": user},
            ],
            temperature=0.0,
            max_tokens=600,
            json_mode=True,
            timeout=timeout,
            model_override=model_override,
        )
    except Exception as e:
        logger.warning(f"[FAITH_JUDGE] LLM call failed: {e}")
        report.fallback_reason = f"llm_error:{type(e).__name__}"
        # Best-effort : on retourne un score neutre 0.5
        report.overall_faithfulness = 0.5
        report.overall_verdict = "PARTIAL"
        return report

    m = re.search(r"\{[\s\S]*\}", raw or "")
    if not m:
        report.fallback_reason = "parse_no_json"
        report.overall_faithfulness = 0.5
        report.overall_verdict = "PARTIAL"
        return report
    try:
        data = json.loads(m.group())
    except Exception as e:
        logger.warning(f"[FAITH_JUDGE] JSON parse failed: {e}")
        report.fallback_reason = f"parse_error:{type(e).__name__}"
        report.overall_faithfulness = 0.5
        report.overall_verdict = "PARTIAL"
        return report

    valid_verdicts = {"SUPPORTED", "UNSUPPORTED", "NEUTRAL"}
    for ac in (data.get("atomic_claims") or []):
        verdict = (ac.get("verdict") or "NEUTRAL").strip().upper()
        if verdict not in valid_verdicts:
            verdict = "NEUTRAL"
        try:
            conf = float(ac.get("confidence", 0.5))
        except Exception:
            conf = 0.5
        ev_ids = [i for i in (ac.get("evidence_ids") or []) if isinstance(i, int)]
        report.atomic_claims.append(AtomicClaimVerdict(
            claim=str(ac.get("claim", ""))[:300],
            verdict=verdict,
            confidence=max(0.0, min(1.0, conf)),
            evidence_ids=ev_ids,
            reasoning=str(ac.get("reasoning", ""))[:200],
        ))

    # Counts + recompute faithfulness pour cohérence (le LLM peut se tromper sur le math)
    report.n_supported = sum(1 for c in report.atomic_claims if c.verdict == "SUPPORTED")
    report.n_unsupported = sum(1 for c in report.atomic_claims if c.verdict == "UNSUPPORTED")
    report.n_neutral = sum(1 for c in report.atomic_claims if c.verdict == "NEUTRAL")
    report.n_factual = report.n_supported + report.n_unsupported

    if report.n_factual == 0:
        # Réponse purement abstentive : pas de claim factuel à juger → FAITHFUL par défaut
        report.overall_faithfulness = 1.0
        report.overall_verdict = "FAITHFUL"
        report.diagnostic["all_neutral"] = True
    else:
        report.overall_faithfulness = report.n_supported / report.n_factual
        if report.overall_faithfulness >= 0.8:
            report.overall_verdict = "FAITHFUL"
        elif report.overall_faithfulness >= 0.5:
            report.overall_verdict = "PARTIAL"
        else:
            report.overall_verdict = "UNFAITHFUL"

    # Optionnel : aligner avec la valeur LLM-reportée si proche (sinon trust local)
    try:
        llm_overall = float(data.get("overall_faithfulness", report.overall_faithfulness))
        report.diagnostic["llm_reported_faithfulness"] = round(llm_overall, 3)
    except Exception:
        pass

    logger.info(
        f"[FAITH_JUDGE] verdict={report.overall_verdict} "
        f"score={report.overall_faithfulness:.2f} "
        f"supported={report.n_supported} unsupported={report.n_unsupported} "
        f"neutral={report.n_neutral}"
    )
    return report


def should_regenerate(
    report: FaithfulnessReport,
    score_threshold: float = 0.7,
    minor_response_n_factual: int = 4,
    high_ratio_trigger: float = 0.3,
) -> bool:
    """Politique de régénération CH-33 — équilibrée latence/qualité.

    Régénère si :
    - UNFAITHFUL (overall_faithfulness < 0.5) — toujours
    - PARTIAL avec score < score_threshold (default 0.7)
    - n_unsupported >= 1 ET n_factual <= minor_response_n_factual (4) :
      sur réponse courte, 1 claim non supporté est probablement central.
    - n_unsupported >= 1 ET ratio >= high_ratio_trigger (30%) :
      sur réponse longue, 30%+ d'unsupported = problème significatif.

    Ne régénère PAS si :
    - FAITHFUL (≥ 0.8)
    - 1 claim non supporté noyé dans 8+ claims supportés (probablement détail mineur)

    Tradeoff : ~+10s par regen, mais évite l'hallucination sur le claim principal.
    """
    if report.overall_verdict == "UNFAITHFUL":
        return True
    if report.overall_verdict == "PARTIAL" and report.overall_faithfulness < score_threshold:
        return True
    if report.n_unsupported >= 1 and report.n_factual > 0:
        # Sur réponse courte : tout claim unsupported est important
        if report.n_factual <= minor_response_n_factual:
            return True
        # Sur réponse longue : seulement si ratio significatif
        if (report.n_unsupported / report.n_factual) >= high_ratio_trigger:
            return True
    return False


def build_unsupported_warning(report: FaithfulnessReport) -> Optional[str]:
    """Construit un avertissement si la réponse contient des claims non supportés.

    Utilisable comme insight_hint downstream.
    """
    unsupported = [c for c in report.atomic_claims if c.verdict == "UNSUPPORTED"]
    if not unsupported:
        return None
    bullets = "\n".join(f"  - {c.claim[:200]}" for c in unsupported[:3])
    return (
        f"**Attention** : {len(unsupported)} affirmation(s) de la réponse "
        f"ne sont pas directement supportées par les sources :\n{bullets}"
    )
