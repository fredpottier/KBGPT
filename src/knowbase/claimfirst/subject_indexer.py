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

import asyncio
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
DEFAULT_CONCURRENCY_NON_BURST = 8  # concurrence prudente hors burst


def _default_concurrency() -> int:
    """Concurrence LLM des appels SubjectIndexer : config burst si actif (≈32),
    sinon défaut prudent. Même plomberie que ClaimExtractor (gather + semaphore)."""
    try:
        from knowbase.ingestion.burst.provider_switch import (
            get_burst_concurrency_config, is_burst_mode_active,
        )
        if is_burst_mode_active():
            n = (get_burst_concurrency_config() or {}).get("max_concurrent_llm")
            if n and int(n) > 0:
                return int(n)
    except Exception:
        pass
    return DEFAULT_CONCURRENCY_NON_BURST


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
        max_concurrent: Optional[int] = None,
        llm_acomplete: Optional[Callable[[str], Any]] = None,
    ):
        self._llm_complete = llm_complete
        self._llm_acomplete = llm_acomplete
        self._min_confidence = min_confidence
        self._max_retries = max_retries
        self._max_concurrent = (
            max_concurrent if (max_concurrent and max_concurrent > 0) else _default_concurrency()
        )

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

    def _get_llm_acomplete(self) -> Callable[[str], Any]:
        """Lazy init du caller LLM ASYNC (Qwen2.5-14B-AWQ via LLMRouter singleton burst-aware)."""
        if self._llm_acomplete is None:
            from knowbase.common.llm_router import get_llm_router, TaskType
            router = get_llm_router()

            async def _acomplete(claim_text: str) -> str:
                return await router.acomplete(
                    task_type=TaskType.FAST_CLASSIFICATION,
                    messages=[
                        {"role": "system", "content": EXTRACT_PROMPT},
                        {"role": "user", "content": claim_text[:1500]},
                    ],
                    temperature=0.0,
                    max_tokens=200,
                )
            self._llm_acomplete = _acomplete
        return self._llm_acomplete

    async def _acall(self, text: str) -> str:
        """Appel LLM unifié pour le chemin async. Priorité : acomplete injecté >
        complete sync injecté (tests → hors event loop) > défaut async router."""
        if self._llm_acomplete is not None:
            return await self._llm_acomplete(text)
        if self._llm_complete is not None:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self._llm_complete, text)
        return await self._get_llm_acomplete()(text)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def _empty_result(claim_id: str, t0: float) -> SubjectIndexResult:
        return SubjectIndexResult(
            claim_id=claim_id, subject=None, confidence=0.0, marginal=True,
            reasoning="empty claim text", duration_s=time.perf_counter() - t0,
            failure_reason="EmptyText",
        )

    def _interpret(
        self, claim_id: str, raw: str, t0: float
    ) -> "tuple[Optional[SubjectIndexResult], Optional[str]]":
        """Parse la réponse LLM + applique la décision. Retourne (résultat, None) si
        terminal (kept/marginal), ou (None, erreur) pour signaler un retry. Peut lever
        (parse error) — géré par la boucle appelante."""
        parsed = self._parse_llm_response(raw)
        subj = parsed.get("subject")
        if subj:
            subj = _normalize_subject(str(subj)) or None
        confidence = float(parsed.get("confidence", 0.0))
        marginal = bool(parsed.get("marginal", False))
        reasoning = str(parsed.get("reasoning", ""))[:200]
        if subj and confidence >= self._min_confidence and not marginal:
            return SubjectIndexResult(
                claim_id=claim_id, subject=subj, confidence=confidence, marginal=False,
                reasoning=reasoning, duration_s=time.perf_counter() - t0,
            ), None
        if marginal:
            return SubjectIndexResult(
                claim_id=claim_id, subject=None, confidence=confidence, marginal=True,
                reasoning=reasoning, duration_s=time.perf_counter() - t0,
            ), None
        return None, f"LowConfidence (conf={confidence:.2f})"

    def _all_failed(self, claim_id: str, last_error: Optional[str], t0: float) -> SubjectIndexResult:
        return SubjectIndexResult(
            claim_id=claim_id, subject=None, confidence=0.0, marginal=True,
            reasoning=f"all retries failed: {last_error}",
            duration_s=time.perf_counter() - t0, failure_reason=last_error,
        )

    def index_one(self, claim_id: str, text: str) -> SubjectIndexResult:
        """Extrait le subject_canonical d'un claim (SYNC). Retourne SubjectIndexResult."""
        t0 = time.perf_counter()
        if not text or not text.strip():
            return self._empty_result(claim_id, t0)
        last_error: Optional[str] = None
        complete = self._get_llm_complete()
        for attempt in range(self._max_retries):
            try:
                res, err = self._interpret(claim_id, complete(text), t0)
                if res is not None:
                    return res
                last_error = err
            except Exception as exc:
                last_error = f"LLMError: {str(exc)[:100]}"
                logger.warning("SubjectIndexer attempt %d/%d failed for claim %s: %s",
                               attempt + 1, self._max_retries, claim_id, last_error)
        return self._all_failed(claim_id, last_error, t0)

    async def _aindex_one(self, claim_id: str, text: str) -> SubjectIndexResult:
        """Variante ASYNC de index_one (même logique retry/décision, LLM awaité)."""
        t0 = time.perf_counter()
        if not text or not text.strip():
            return self._empty_result(claim_id, t0)
        last_error: Optional[str] = None
        for attempt in range(self._max_retries):
            try:
                res, err = self._interpret(claim_id, await self._acall(text), t0)
                if res is not None:
                    return res
                last_error = err
            except Exception as exc:
                last_error = f"LLMError: {str(exc)[:100]}"
                logger.warning("SubjectIndexer(async) attempt %d/%d failed for claim %s: %s",
                               attempt + 1, self._max_retries, claim_id, last_error)
        return self._all_failed(claim_id, last_error, t0)

    async def _aindex_all(
        self, to_index: List[Any]
    ) -> "List[tuple[Any, SubjectIndexResult]]":
        """Indexe en PARALLÈLE (gather + semaphore) la liste des claims à traiter."""
        sem = asyncio.Semaphore(self._max_concurrent)

        async def _one(c):
            async with sem:
                claim_id = getattr(c, "claim_id", None) or "unknown"
                text = getattr(c, "text", None) or getattr(c, "verbatim_quote", "") or ""
                return c, await self._aindex_one(claim_id, text)

        return await asyncio.gather(*[_one(c) for c in to_index])

    @staticmethod
    def _run_async(coro):
        """Exécute une coro depuis un contexte SYNC. Si une boucle tourne déjà
        (appelé depuis de l'async), bascule dans un thread dédié."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()

    def index_claims(self, claims: List[Any]) -> List[SubjectIndexResult]:
        """Indexe une liste de claims (objets Claim ou compatibles), EN PARALLÈLE.

        Les claims ayant déjà un SF.subject sont sautés (priorité SF, cohérence forcée).
        Les autres sont indexés via LLM en parallèle (semaphore = config burst ≈32).

        Returns:
            List[SubjectIndexResult] — un résultat par claim traité (skip ceux avec SF.subject)
        """
        # Phase 1 (sync, rapide) : séparer skip (SF.subject) des claims à indexer
        results: List[SubjectIndexResult] = []
        to_index: List[Any] = []
        for c in claims:
            sf = getattr(c, "structured_form", None)
            if sf and isinstance(sf, dict) and sf.get("subject"):
                if hasattr(c, "subject_canonical"):
                    c.subject_canonical = sf["subject"]  # cohérence priorité SF
                continue
            to_index.append(c)
        if not to_index:
            return results

        # Phase 2 (parallèle) : extraction LLM des sujets
        pairs = self._run_async(self._aindex_all(to_index))

        # Phase 3 (sync) : appliquer les résultats aux claims (mutations sérialisées = sûr)
        for c, result in pairs:
            results.append(result)
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
