"""SubjectIndexer — extraction subject_canonical indépendante de structured_form.

A4.2 (22/05/2026) — cf doc/ongoing/A41_AUDIT_PIPELINE_CLAIMFIRST.md

Contexte
--------
Le pipeline ClaimFirst V1.1 ne remplit `structured_form` (et donc
`subject_canonical` dénormalisé) que pour les claims HIGH VALUE = relations
S-P-O canoniques entre 2 entités nommées avec prédicat fermé.

61% des claims (7134/11622) sont donc sans `subject_canonical`, ce qui les
rend invisibles au runtime_v6 (qui indexe par sujet).

Ce module **peuple `subject_canonical` indépendamment de `structured_form`**
via une extraction LLM zero-shot strict (Qwen2.5-14B-AWQ via vLLM burst).

Priorité de remplissage (cohérence) :
    1. Si `claim.structured_form.subject` existe → utilisé tel quel (priorité SF)
    2. Sinon → extraction LLM via ce module
    3. Si LLM abstient (subject ambigu/descriptif) → `marginal=True`, `subject_canonical=None`

Charte stricte : domain-agnostic. Prompt zero-shot sans few-shot corpus-spécifique.

Toggle env : `V6_SUBJECT_INDEXER_ENABLED` (default "1").
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger("knowbase.claimfirst.subject_indexer")


# Constants
MIN_CONFIDENCE = 0.7  # seuil pour accepter un subject extrait
MAX_RETRIES = 2  # tentatives avant flag marginal


# Prompt zero-shot strict — domain-agnostic, validé sur 96 claims
# (cf data/benchmark/a42_extract_test/extract_test_20260522_110502.json)
EXTRACT_PROMPT = """You are extracting the primary subject of a claim.

A subject is the main entity, concept, or product the claim is asserting something about.
It must be a noun phrase that can be named in 1-5 words.

Rules:
- DO NOT include articles ("the", "a", "an", "le", "la") in the subject.
- Subject must be a concrete entity or technical term, NOT a generic action/verb.
- If the claim has multiple subjects, choose the most prominent one.
- If the claim has no clear subject (pure descriptive phrase, generic statement,
  or fragment), set "subject" to null and "marginal" to true.

OUTPUT JSON ONLY:
{
  "subject": "<name>"|null,
  "confidence": <float 0.0-1.0>,
  "marginal": <true if no clear subject, else false>,
  "reasoning": "<one short sentence>"
}

Claim text:"""


class SubjectIndexResult(BaseModel):
    """Résultat d'une indexation subject pour un claim."""

    model_config = ConfigDict(extra="forbid")

    claim_id: str
    subject: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    marginal: bool = False
    reasoning: str = ""
    duration_s: float = Field(default=0.0, ge=0.0)
    failure_reason: Optional[str] = None  # None / "LowConfidence" / "LLMError" / "EmptyText"


def _normalize_subject(subj: str) -> str:
    """Normalisation minimale post-extraction LLM.

    - Strip whitespace
    - Supprime article initial (the/a/an/le/la/les/un/une)
    - Cap à 200 chars (perf index Neo4j)
    """
    s = subj.strip()
    # Supprime l'article initial s'il est suivi d'un espace OU s'il est seul
    s = re.sub(r"^(the|a|an|le|la|les|un|une)(?:\s+|$)", "", s, flags=re.IGNORECASE)
    return s.strip()[:200]


class SubjectIndexer:
    """Extracteur de subject_canonical via LLM zero-shot.

    Injection de dépendance pour testabilité :
        - `llm_complete` : callable `(claim_text: str) -> str` (raw JSON LLM response)
    """

    def __init__(
        self,
        llm_complete: Optional[Callable[[str], str]] = None,
        min_confidence: float = MIN_CONFIDENCE,
        max_retries: int = MAX_RETRIES,
    ):
        self._llm_complete = llm_complete
        self._min_confidence = min_confidence
        self._max_retries = max_retries

    def _get_llm_complete(self) -> Callable[[str], str]:
        """Lazy init du LLM caller (Qwen2.5-14B-AWQ via LLMRouter)."""
        if self._llm_complete is None:
            from knowbase.common.llm_router import LLMRouter, TaskType
            router = LLMRouter()
            def _complete(claim_text: str) -> str:
                return router.complete(
                    task_type=TaskType.FAST_CLASSIFICATION,
                    messages=[
                        {"role": "system", "content": EXTRACT_PROMPT},
                        {"role": "user", "content": claim_text[:1500]},
                    ],
                    temperature=0.0,
                    max_tokens=200,
                )
            self._llm_complete = _complete
        return self._llm_complete

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def index_one(self, claim_id: str, text: str) -> SubjectIndexResult:
        """Extrait le subject_canonical d'un claim. Retourne SubjectIndexResult."""
        t0 = time.perf_counter()

        if not text or not text.strip():
            return SubjectIndexResult(
                claim_id=claim_id,
                subject=None,
                confidence=0.0,
                marginal=True,
                reasoning="empty claim text",
                duration_s=time.perf_counter() - t0,
                failure_reason="EmptyText",
            )

        last_error: Optional[str] = None
        for attempt in range(self._max_retries):
            try:
                raw = self._get_llm_complete()(text)
                parsed = self._parse_llm_response(raw)
                # Normaliser subject si présent
                subj = parsed.get("subject")
                if subj:
                    subj = _normalize_subject(str(subj))
                    if not subj:  # devient vide après normalisation
                        subj = None
                confidence = float(parsed.get("confidence", 0.0))
                marginal = bool(parsed.get("marginal", False))
                reasoning = str(parsed.get("reasoning", ""))[:200]

                # Décision : si subject extrait avec confidence ≥ seuil → kept
                # Sinon si marginal=true → flag marginal
                # Sinon (low confidence sans flag marginal) → LowConfidence
                if subj and confidence >= self._min_confidence and not marginal:
                    return SubjectIndexResult(
                        claim_id=claim_id,
                        subject=subj,
                        confidence=confidence,
                        marginal=False,
                        reasoning=reasoning,
                        duration_s=time.perf_counter() - t0,
                    )
                if marginal:
                    return SubjectIndexResult(
                        claim_id=claim_id,
                        subject=None,
                        confidence=confidence,
                        marginal=True,
                        reasoning=reasoning,
                        duration_s=time.perf_counter() - t0,
                    )
                # Low confidence sans marginal — retry si possible
                last_error = f"LowConfidence (conf={confidence:.2f})"
            except Exception as exc:
                last_error = f"LLMError: {str(exc)[:100]}"
                logger.warning(
                    "SubjectIndexer attempt %d/%d failed for claim %s: %s",
                    attempt + 1, self._max_retries, claim_id, last_error,
                )

        # Toutes tentatives échouées → flag marginal
        return SubjectIndexResult(
            claim_id=claim_id,
            subject=None,
            confidence=0.0,
            marginal=True,
            reasoning=f"all retries failed: {last_error}",
            duration_s=time.perf_counter() - t0,
            failure_reason=last_error,
        )

    def index_claims(self, claims: List[Any]) -> List[SubjectIndexResult]:
        """Indexe une liste de claims (objets Claim ou compatibles).

        Itère sur les claims qui n'ont PAS déjà de subject_canonical issu de
        structured_form. Si le claim a déjà SF.subject, on saute (priorité SF).

        Returns:
            List[SubjectIndexResult] — un résultat par claim traité (skip ceux avec SF.subject)
        """
        results: List[SubjectIndexResult] = []
        for c in claims:
            # Skip si SF.subject existe (priorité SF)
            sf = getattr(c, "structured_form", None)
            if sf and isinstance(sf, dict) and sf.get("subject"):
                # Garantit que claim.subject_canonical reflète SF.subject (cohérence)
                if hasattr(c, "subject_canonical"):
                    c.subject_canonical = sf["subject"]
                continue
            # Sinon, extraire via LLM
            claim_id = getattr(c, "claim_id", None) or "unknown"
            text = getattr(c, "text", None) or getattr(c, "verbatim_quote", "") or ""
            result = self.index_one(claim_id, text)
            results.append(result)
            # Apply au claim
            if hasattr(c, "subject_canonical"):
                c.subject_canonical = result.subject
            if hasattr(c, "marginal"):
                c.marginal = result.marginal
            if hasattr(c, "subject_extraction_confidence"):
                c.subject_extraction_confidence = result.confidence
        return results

    @staticmethod
    def _parse_llm_response(raw: str) -> Dict[str, Any]:
        """Parse JSON de la réponse LLM, tolérant aux markdown fences."""
        if not raw or not raw.strip():
            raise ValueError("empty LLM response")
        stripped = raw.strip()
        if stripped.startswith("```"):
            m = re.search(r"```(?:json)?\s*(.+?)\s*```", stripped, re.DOTALL)
            if m:
                stripped = m.group(1).strip()
        return json.loads(stripped)


# ============================================================================
# Toggle env
# ============================================================================


def is_enabled() -> bool:
    """Retourne True si le SubjectIndexer doit être appliqué côté pipeline."""
    return os.getenv("V6_SUBJECT_INDEXER_ENABLED", "1") == "1"


# ============================================================================
# Top-level API
# ============================================================================


def index_claims(claims: List[Any], indexer: Optional[SubjectIndexer] = None) -> List[SubjectIndexResult]:
    """API top-level."""
    if not is_enabled():
        return []
    idx = indexer or SubjectIndexer()
    return idx.index_claims(claims)
