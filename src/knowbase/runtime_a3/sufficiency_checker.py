"""SufficiencyChecker — garde-fou anti-sur-confiance (Phase B, 25/05/2026).

Gap architectural identifié via Option ε + recall audit :
    - GroundingVerifier vérifie "la réponse est-elle supportée par les claims cités ?"
      (anti-hallucination de détail)
    - SufficiencyChecker vérifie "les claims répondent-ils à la QUESTION posée ?"
      (anti-sur-confiance : répondre à une question adjacente)

Cas typiques (bench Config C3) :
    - HUM_0028/0054/0033 : question demande transaction OM13/OM03, evidence n'a
      qu'OM17 (transaction différente) → pipeline répond OM17 (FAUX) au lieu d'abstenir
    - false_premise : question présuppose un fait absent → pipeline fabrique
    - lifecycle Q2_2 : question demande "quelle version" alors que c'est structurel

Architecture : LLM-only (Mécanisme 2 du design).
    Le Mécanisme 1 (regex identifiants) a été abandonné — trop fragile, faux
    positifs ("API v2" → "API" extrait comme requis), rate les concepts narratifs.

Le LLM léger (DeepSeek-V3.1, JSON strict OK) reçoit (question, claims_text) et
juge SUFFICIENT | INSUFFICIENT | FALSE_PREMISE. Conservateur par design :
ne marque INSUFFICIENT que si l'information critique est clairement absente.

Toggle env : `V6_SUFFICIENCY_CHECK_ENABLED` (default "0" — activer après bench A/B)
Domain-agnostic strict : aucun token corpus-spécifique, prompt universel.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, List, Literal, Optional

logger = logging.getLogger("knowbase.runtime_a3.sufficiency_checker")


SufficiencyVerdict = Literal["SUFFICIENT", "INSUFFICIENT", "FALSE_PREMISE"]


_SYSTEM_PROMPT = """You are a sufficiency checker for a knowledge-base Q&A system.

Given a USER QUESTION and a set of retrieved EVIDENCE claims, decide whether the
evidence is sufficient to answer the SPECIFIC question asked.

OUTPUT JSON ONLY (no markdown, no commentary):
{"verdict": "SUFFICIENT" | "INSUFFICIENT" | "FALSE_PREMISE", "reasoning": "<20-50 words>"}

VERDICTS:
- SUFFICIENT: the evidence directly contains the answer to the specific question.
  Mark SUFFICIENT even if the answer is not perfectly detailed, as long as the
  core information is present.
- INSUFFICIENT: the evidence is topically related but is MISSING the specific
  entity/identifier/value the question asks about. Example: the question asks
  about identifier X, but the evidence only describes a DIFFERENT identifier Y.
- FALSE_PREMISE: the question assumes a fact that the evidence contradicts or
  that does not hold. Example: the question asks "which version introduced X"
  but X is a structural requirement not tied to any version.

CRITICAL RULES:
- Be CONSERVATIVE. When in doubt, prefer SUFFICIENT. Only mark INSUFFICIENT
  when a clearly-required specific identifier/entity/value from the question is
  absent from ALL evidence.
- If the question asks about a SPECIFIC code/identifier/transaction/version and
  the evidence only contains a DIFFERENT one, that is INSUFFICIENT — answering
  with the adjacent identifier would be wrong.
- Do NOT penalize paraphrasing or partial detail. The downstream synthesizer
  handles wording.

Be precise and brief."""


@dataclass
class SufficiencyResult:
    verdict: SufficiencyVerdict
    reasoning: str
    duration_s: float
    llm_failed: bool = False


class SufficiencyChecker:
    """Vérifie si l'evidence répond à la question (anti-sur-confiance).

    Dependency injection :
        - `llm_client` : objet exposant `.complete(system, user) -> str` (tests)
          En prod : llm_router via TaskType.RUNTIME_PARSE_EVALUATE (DeepSeek-V3.1).
    """

    def __init__(self, llm_client: Any = None, max_claims: int = 8):
        self._llm_client = llm_client
        self._max_claims = max_claims

    def _get_llm_client(self):
        if self._llm_client is None:
            from knowbase.common.llm_router import get_llm_router, TaskType

            class _RouterClient:
                def __init__(self):
                    self._router = get_llm_router()

                def complete(self, system: str, user: str) -> str:
                    return self._router.complete(
                        task_type=TaskType.RUNTIME_PARSE_EVALUATE,  # DeepSeek-V3.1
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        temperature=0.0,
                        max_tokens=200,
                    ).strip()
            self._llm_client = _RouterClient()
        return self._llm_client

    @staticmethod
    def _claim_text(claim: Any) -> str:
        """Texte le plus riche disponible pour un claim (verbatim > triplet)."""
        extras = claim.model_dump() if hasattr(claim, "model_dump") else {}
        for key in ("text", "claim_text_full", "verbatim_quote"):
            val = extras.get(key)
            if val and isinstance(val, str) and val.strip():
                return val.strip()[:400]
        parts: List[str] = []
        if getattr(claim, "subject_canonical", None):
            parts.append(str(claim.subject_canonical))
        if getattr(claim, "predicate", None):
            parts.append(str(claim.predicate).replace("_", " ").lower())
        val = getattr(claim, "value", None) or getattr(claim, "value_normalized", None)
        if val:
            parts.append(str(val))
        return " ".join(parts).strip()

    def _build_user_prompt(self, question: str, claims: List[Any]) -> str:
        claims_block = []
        for i, c in enumerate(claims[:self._max_claims], 1):
            claims_block.append(f"  [{i}] {self._claim_text(c)}")
        return (
            f"USER QUESTION: {question}\n\n"
            f"EVIDENCE CLAIMS:\n" + "\n".join(claims_block)
            + "\n\nRespond with JSON only."
        )

    def check(self, question: str, claims: List[Any]) -> SufficiencyResult:
        """Juge si l'evidence répond à la question.

        Returns SufficiencyResult. Fail-open : si LLM down ou parse échoue,
        retourne SUFFICIENT (ne bloque jamais le pipeline sur une erreur infra).
        """
        t0 = time.perf_counter()

        if not question or not question.strip() or not claims:
            # Pas d'evidence → laisser le pipeline gérer (court-circuit ABSTENTION amont)
            return SufficiencyResult("SUFFICIENT", "no_check_needed", time.perf_counter() - t0)

        try:
            raw = self._get_llm_client().complete(
                _SYSTEM_PROMPT, self._build_user_prompt(question, claims),
            )
        except Exception:
            logger.exception("sufficiency_check: LLM call failed, fail-open SUFFICIENT")
            return SufficiencyResult("SUFFICIENT", "llm_error_fail_open",
                                     time.perf_counter() - t0, llm_failed=True)

        verdict, reasoning = self._parse(raw)
        dt = time.perf_counter() - t0
        logger.info("[SUFFICIENCY] verdict=%s dur=%.2fs reasoning=%s",
                    verdict, dt, reasoning[:120])
        return SufficiencyResult(verdict, reasoning, dt)

    @staticmethod
    def _parse(raw: str) -> tuple[SufficiencyVerdict, str]:
        """Parse tolérant (JSON strict puis regex fallback). Fail-open SUFFICIENT."""
        if not raw or not raw.strip():
            return "SUFFICIENT", "empty_llm_response_fail_open"
        text = raw.strip()
        # Strip markdown fences
        m = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
        if m:
            text = m.group(1).strip()
        # JSON strict
        try:
            parsed = json.loads(text)
            v = parsed.get("verdict", "").upper()
            if v in ("SUFFICIENT", "INSUFFICIENT", "FALSE_PREMISE"):
                return v, parsed.get("reasoning", "")[:300]
        except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
            pass
        # Regex fallback sur le verdict
        m = re.search(r'"verdict"\s*:\s*"(SUFFICIENT|INSUFFICIENT|FALSE_PREMISE)"', text, re.IGNORECASE)
        if m:
            return m.group(1).upper(), "[regex_extract] " + text[:200]
        # Dernier recours : chercher le mot-clé brut
        up = text.upper()
        if "FALSE_PREMISE" in up:
            return "FALSE_PREMISE", "[keyword] " + text[:200]
        if "INSUFFICIENT" in up:
            return "INSUFFICIENT", "[keyword] " + text[:200]
        # Fail-open
        return "SUFFICIENT", "unparseable_fail_open"


def is_enabled() -> bool:
    """Toggle env. Défaut OFF — activer après bench A/B prouvant ROI positif."""
    return os.getenv("V6_SUFFICIENCY_CHECK_ENABLED", "0") == "1"
