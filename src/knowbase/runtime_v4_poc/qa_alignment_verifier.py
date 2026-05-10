"""Q↔A Alignment Verifier — DeepSeek-V3.1 (CH-49.POC Phase 1.A).

Vérifie sémantiquement qu'une réponse adresse bien la question posée. Utilise
DeepSeek-V3.1 (famille distincte du Composer Llama-Turbo) pour éviter le biais
auto-juge.

Cas d'usage couverts (Pattern transverse identifié dans ADR CH-49) :
- list Pattern A (items hors-cible) — 40% des fails list
- factual Pattern F (extraction brute non-raisonnée) — 20% des fails factual
- unanswerable Pattern O (off-topic au lieu d'abstain) — 40% des fails unanswerable

Domain-agnostic : sémantique LLM multi-langue, pas de keywords/regex.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


# Prompt domain-agnostic, multi-langue
SYSTEM_PROMPT = """You are a semantic alignment verifier. Your single job is to determine whether a given ANSWER conceptually addresses what a given QUESTION asks.

You DO NOT verify factual correctness — only semantic alignment.

Decision rules :
- ALIGNED : the answer addresses what the question is asking about (the topic, the facet, the angle requested)
- MISALIGNED : the answer talks about an adjacent or related topic but does not address what was specifically asked
- ABSTAIN_OK : the answer correctly states it cannot find the information (legitimate abstention)

Examples (abstract, language-agnostic):
- Q: "What is X's position on Y?" / A: "Y was adopted on date Z" → MISALIGNED (talks about Y, not X's position)
- Q: "List of category C items" / A: "Items of category D" → MISALIGNED (wrong category)
- Q: "Cost of X?" / A: "X is not specified in available documents" → ABSTAIN_OK
- Q: "Cost of X?" / A: "X requires authorization for export" → MISALIGNED (talks about X, not its cost)

Output STRICT JSON only :
{
  "decision": "ALIGNED" | "MISALIGNED" | "ABSTAIN_OK",
  "reason": "<one short sentence explaining the call>",
  "confidence": <float between 0 and 1>
}"""


@dataclass
class QAAlignmentResult:
    decision: str  # ALIGNED | MISALIGNED | ABSTAIN_OK
    reason: str
    confidence: float
    latency_ms: int
    raw: dict


class QAAlignmentVerifier:
    """Verifier sémantique Q↔A via DeepSeek-V3.1 (Together AI).

    Famille distincte du Composer (Llama-Turbo) → anti-biais auto-juge.
    """

    DEFAULT_MODEL = "deepseek-ai/DeepSeek-V3.1"
    DEFAULT_BASE_URL = "https://api.together.xyz/v1"

    def __init__(
        self,
        model: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        self.model = model or os.getenv("QA_VERIFIER_MODEL", self.DEFAULT_MODEL)
        self.base_url = base_url
        self.timeout = timeout
        self.api_key = os.getenv("TOGETHER_API_KEY", "")
        if not self.api_key:
            logger.warning("TOGETHER_API_KEY not set — QAAlignmentVerifier will fail")

    def verify(self, question: str, answer: str) -> QAAlignmentResult:
        """Vérifie l'alignement sémantique question ↔ réponse.

        Returns :
            QAAlignmentResult avec decision, reason, confidence, latency_ms.
        """
        t0 = time.time()
        user_msg = f"QUESTION:\n{question.strip()}\n\nANSWER:\n{(answer or '').strip()}"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.0,
            "max_tokens": 200,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            with httpx.Client(
                timeout=self.timeout,
                transport=httpx.HTTPTransport(retries=0),
            ) as client:
                resp = client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", "2"))
                    logger.warning(f"QAVerifier rate-limited, retrying in {retry_after}s")
                    time.sleep(retry_after)
                    resp = client.post(
                        f"{self.base_url}/chat/completions",
                        json=payload, headers=headers,
                    )
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                wall_ms = int((time.time() - t0) * 1000)
                return QAAlignmentResult(
                    decision=parsed.get("decision", "ALIGNED"),
                    reason=parsed.get("reason", ""),
                    confidence=float(parsed.get("confidence", 0.5)),
                    latency_ms=wall_ms,
                    raw=parsed,
                )
        except (httpx.HTTPError, json.JSONDecodeError, KeyError) as exc:
            wall_ms = int((time.time() - t0) * 1000)
            logger.error(f"QAVerifier failed: {exc}")
            # Fail open : si le verifier ne fonctionne pas, on laisse passer (pas de blocage prod)
            return QAAlignmentResult(
                decision="ALIGNED",
                reason=f"verifier_error: {exc}",
                confidence=0.0,
                latency_ms=wall_ms,
                raw={"error": str(exc)},
            )
