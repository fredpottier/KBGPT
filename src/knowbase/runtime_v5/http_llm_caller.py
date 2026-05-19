"""V5 HTTPLLMCaller — production LLM HTTP wrapper.

Branche `LLMCaller` interface (utilisée par ReasoningAgentV51) sur les
providers réels via HTTP :
- Priorité 1 : Together AI (rapide ×6, charte OSMOSIS)
- Fallback : DeepInfra (si TOGETHER_API_KEY absent ou erreur)

Charte respectée : pas de Claude Sonnet ni GPT-4o. Modèles open-source
serverless uniquement (DeepSeek-V3.1, Llama-3.3-70B-Turbo, Qwen2.5-72B...).

Réutilise la logique éprouvée du POC `reasoning_agent.py` (call_llm), wrappée
dans l'interface `LLMCaller`.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Optional

import requests

from knowbase.runtime_v5.reasoning_agent_v51 import LLMCaller

logger = logging.getLogger(__name__)


DEFAULT_MODEL = "deepseek-ai/DeepSeek-V3.1"
DEFAULT_TIMEOUT_S = 300
DEFAULT_MAX_RETRIES = 3


def _resolve_endpoint_key() -> tuple[str, str, str]:
    """Retourne (endpoint_url, api_key, provider_name) selon env.

    Together AI prioritaire (rapide), DeepInfra fallback.
    """
    together_key = os.getenv("TOGETHER_API_KEY", "").strip()
    if together_key:
        return (
            "https://api.together.xyz/v1/chat/completions",
            together_key,
            "together",
        )
    deepinfra_key = os.getenv("DEEPINFRA_API_KEY", "").strip()
    if deepinfra_key:
        return (
            "https://api.deepinfra.com/v1/openai/chat/completions",
            deepinfra_key,
            "deepinfra",
        )
    return ("", "", "none")


class HTTPLLMCaller(LLMCaller):
    """Implémentation production de LLMCaller.

    Args:
        model : modèle LLM (default DeepSeek-V3.1, charte open-source)
        timeout_s : timeout HTTP par call (default 300s)
        max_retries : retries avec exponential backoff (default 3)
        force_provider : override auto-detection ("together" | "deepinfra" | "vllm" | None)
        endpoint_url : override complet de l'URL (priorité sur force_provider).
                       Utile pour brancher vLLM self-hosted (EC2, on-prem).
    """

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        max_retries: int = DEFAULT_MAX_RETRIES,
        force_provider: Optional[str] = None,
        endpoint_url: Optional[str] = None,
    ):
        self.model = model
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.force_provider = force_provider
        self.endpoint_url = endpoint_url
        endpoint, key, provider = self._endpoint()
        if not key and provider != "vllm":
            logger.warning(
                "[HTTPLLMCaller] No API key found in env "
                "(TOGETHER_API_KEY or DEEPINFRA_API_KEY). "
                "Calls will fail until configured."
            )

    def _endpoint(self) -> tuple[str, str, str]:
        # endpoint_url explicite (ex: vLLM self-hosted EC2) prime sur tout
        if self.endpoint_url:
            # vLLM ne valide pas le Bearer par défaut, on passe une string dummy
            return (self.endpoint_url, "no-auth-vllm", "vllm")
        if self.force_provider == "together":
            key = os.getenv("TOGETHER_API_KEY", "").strip()
            return ("https://api.together.xyz/v1/chat/completions", key, "together")
        if self.force_provider == "deepinfra":
            key = os.getenv("DEEPINFRA_API_KEY", "").strip()
            return ("https://api.deepinfra.com/v1/openai/chat/completions", key, "deepinfra")
        if self.force_provider == "vllm":
            url = os.getenv("V5_VLLM_URL", "").strip()
            return (url, "no-auth-vllm", "vllm")
        return _resolve_endpoint_key()

    def call(
        self,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 2000,
    ) -> dict:
        """Synchronous LLM call. Retourne dict avec keys 'message', 'usage', '_provider'.

        En cas d'erreur HTTP/timeout : retourne {"error": "..."} (compat
        ReasoningAgentV51 qui sait gérer "error").
        """
        endpoint, key, provider = self._endpoint()
        if not key:
            return {"error": "no_api_key_configured"}

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.0,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        last_err = None
        for attempt in range(self.max_retries):
            try:
                t0 = time.time()
                r = requests.post(
                    endpoint,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self.timeout_s,
                )
                r.raise_for_status()
                data = r.json()
                latency = time.time() - t0
                # Normalize response shape : ReasoningAgentV51 expects
                # {"message": {...}, "usage": {...}}
                choices = data.get("choices") or []
                if not choices:
                    return {"error": "empty_choices", "_provider": provider}
                return {
                    "message": choices[0].get("message", {}),
                    "usage": data.get("usage", {}),
                    "_provider": provider,
                    "_latency_s": latency,
                }
            except requests.HTTPError as e:
                last_err = f"http_{e.response.status_code}: {e}"
                # 4xx → no retry (sauf 429)
                if e.response.status_code < 500 and e.response.status_code != 429:
                    return {"error": last_err, "_provider": provider}
            except requests.RequestException as e:
                last_err = f"{type(e).__name__}: {e}"
            except Exception as e:
                last_err = f"unexpected_{type(e).__name__}: {e}"

            if attempt < self.max_retries - 1:
                backoff_s = min(2 ** (attempt + 1), 30)
                logger.info(
                    f"[HTTPLLMCaller] Retry {attempt + 1}/{self.max_retries - 1} "
                    f"after {backoff_s}s (err={last_err})"
                )
                time.sleep(backoff_s)

        return {"error": last_err or "unknown_error", "_provider": provider}


# ─── Singleton helper ────────────────────────────────────────────────────────


_default_caller: Optional[HTTPLLMCaller] = None


def get_default_llm_caller(model: str = DEFAULT_MODEL) -> HTTPLLMCaller:
    global _default_caller
    if _default_caller is None or _default_caller.model != model:
        _default_caller = HTTPLLMCaller(model=model)
    return _default_caller


def reset_default_llm_caller() -> None:
    global _default_caller
    _default_caller = None
