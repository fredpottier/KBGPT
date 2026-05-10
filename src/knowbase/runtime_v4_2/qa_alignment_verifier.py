"""Q↔A Alignment Verifier production-grade (CH-49 Phase 1, Cap1).

Vérifie sémantiquement qu'une réponse adresse la question. Anti-biais auto-juge
(famille distincte du Composer Llama-Turbo).

Évolutions vs POC `runtime_v4_poc/qa_alignment_verifier.py` :
  - Retry exponential backoff (max 3, 1s/2s/4s) sur 429/5xx/timeout
  - Honor Retry-After header
  - Fallback provider DeepInfra (DeepSeek-V3.1) si Together hard-fail
  - Telemetry (provider used, fallback flag, latency)
  - Fail-open avec marqueur explicite (verifier_error vs ALIGNED)
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional

import httpx

from knowbase.runtime_v4_2.models import QAVerifierTrace

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are a semantic alignment verifier. Your single job is to determine whether a given ANSWER conceptually addresses what a given QUESTION asks.

You DO NOT verify factual correctness — only semantic alignment.

Decision rules :
- ALIGNED : the answer addresses what the question is asking about (the topic, the facet, the angle requested)
- MISALIGNED : the answer talks about an adjacent or related topic but does not address what was specifically asked
- ABSTAIN_OK : the answer correctly states it cannot find the information (legitimate abstention)

Examples (abstract, language-agnostic):
- Q: "What is X's position on Y?" / A: "Y was adopted on date Z" -> MISALIGNED (talks about Y, not X's position)
- Q: "List of category C items" / A: "Items of category D" -> MISALIGNED (wrong category)
- Q: "Cost of X?" / A: "X is not specified in available documents" -> ABSTAIN_OK
- Q: "Cost of X?" / A: "X requires authorization for export" -> MISALIGNED (talks about X, not its cost)

Output STRICT JSON only :
{
  "decision": "ALIGNED" | "MISALIGNED" | "ABSTAIN_OK",
  "reason": "<one short sentence explaining the call>",
  "confidence": <float between 0 and 1>
}"""


class QAAlignmentVerifier:
    """Verifier sémantique Q↔A production avec retry + fallback provider.

    Provider primaire : Together AI / DeepSeek-V3.1 (cohérence avec POC validé).
    Fallback : DeepInfra / DeepSeek-V3 si Together hard-fail (rate-limit ou 5xx persistants).
    """

    DEFAULT_MODEL_TOGETHER = "deepseek-ai/DeepSeek-V3.1"
    DEFAULT_MODEL_DEEPINFRA = "deepseek-ai/DeepSeek-V3"
    TOGETHER_BASE = "https://api.together.xyz/v1"
    DEEPINFRA_BASE = "https://api.deepinfra.com/v1/openai"

    def __init__(
        self,
        model: Optional[str] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        self.model_together = model or os.getenv(
            "QA_VERIFIER_MODEL", self.DEFAULT_MODEL_TOGETHER
        )
        self.model_deepinfra = os.getenv(
            "QA_VERIFIER_FALLBACK_MODEL", self.DEFAULT_MODEL_DEEPINFRA
        )
        self.timeout = timeout
        self.max_retries = max_retries
        self.together_key = os.getenv("TOGETHER_API_KEY", "")
        self.deepinfra_key = os.getenv("DEEPINFRA_API_KEY", "")
        if not self.together_key and not self.deepinfra_key:
            logger.warning(
                "QAAlignmentVerifier: aucune clé API définie (TOGETHER ni DEEPINFRA)"
            )

    @property
    def model(self) -> str:
        return self.model_together

    @property
    def api_key(self) -> str:
        return self.together_key

    def verify(self, question: str, answer: str) -> QAVerifierTrace:
        """Vérifie alignement Q↔A. Tente Together (retry x3) puis DeepInfra fallback."""
        t0 = time.time()

        # Together AI primary
        if self.together_key:
            result = self._call_provider(
                question=question,
                answer=answer,
                base_url=self.TOGETHER_BASE,
                model=self.model_together,
                api_key=self.together_key,
                provider_label="together",
                t_start=t0,
            )
            if result is not None:
                return result

        # Fallback DeepInfra
        if self.deepinfra_key:
            logger.warning("QAVerifier: Together exhausted, falling back to DeepInfra")
            result = self._call_provider(
                question=question,
                answer=answer,
                base_url=self.DEEPINFRA_BASE,
                model=self.model_deepinfra,
                api_key=self.deepinfra_key,
                provider_label="deepinfra",
                t_start=t0,
                fallback_used=True,
            )
            if result is not None:
                return result

        # Hard fail-open : on laisse passer mais on marque
        wall_ms = int((time.time() - t0) * 1000)
        logger.error("QAVerifier: tous les providers ont échoué — fail-open ALIGNED")
        return QAVerifierTrace(
            decision="ALIGNED",
            reason="verifier_unavailable_fail_open",
            confidence=0.0,
            latency_ms=wall_ms,
            provider="error",
            fallback_used=True,
        )

    def _call_provider(
        self,
        question: str,
        answer: str,
        base_url: str,
        model: str,
        api_key: str,
        provider_label: str,
        t_start: float,
        fallback_used: bool = False,
    ) -> Optional[QAVerifierTrace]:
        user_msg = f"QUESTION:\n{question.strip()}\n\nANSWER:\n{(answer or '').strip()}"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.0,
            "max_tokens": 200,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        delay = 1.0
        for attempt in range(self.max_retries):
            try:
                with httpx.Client(
                    timeout=self.timeout,
                    transport=httpx.HTTPTransport(retries=0),
                ) as client:
                    resp = client.post(
                        f"{base_url}/chat/completions", json=payload, headers=headers,
                    )
                    if resp.status_code == 429:
                        retry_after = float(resp.headers.get("Retry-After", str(delay)))
                        logger.warning(
                            f"QAVerifier[{provider_label}] 429, retry_after={retry_after}s "
                            f"(attempt {attempt + 1}/{self.max_retries})"
                        )
                        time.sleep(min(retry_after, 30.0))
                        delay = min(delay * 2, 30.0)
                        continue
                    if resp.status_code >= 500:
                        logger.warning(
                            f"QAVerifier[{provider_label}] {resp.status_code}, "
                            f"backoff {delay}s (attempt {attempt + 1}/{self.max_retries})"
                        )
                        time.sleep(delay)
                        delay = min(delay * 2, 30.0)
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    parsed = json.loads(content)
                    wall_ms = int((time.time() - t_start) * 1000)
                    return QAVerifierTrace(
                        decision=parsed.get("decision", "ALIGNED"),
                        reason=parsed.get("reason", ""),
                        confidence=float(parsed.get("confidence", 0.5)),
                        latency_ms=wall_ms,
                        provider=provider_label,
                        fallback_used=fallback_used,
                    )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                logger.warning(
                    f"QAVerifier[{provider_label}] network error {exc.__class__.__name__}, "
                    f"backoff {delay}s (attempt {attempt + 1}/{self.max_retries})"
                )
                time.sleep(delay)
                delay = min(delay * 2, 30.0)
                continue
            except (httpx.HTTPError, json.JSONDecodeError, KeyError) as exc:
                logger.error(f"QAVerifier[{provider_label}] non-retryable: {exc}")
                return None  # Bascule vers fallback ou fail-open

        logger.error(f"QAVerifier[{provider_label}] retries exhausted")
        return None
