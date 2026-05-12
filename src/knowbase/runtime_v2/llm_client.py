"""
RuntimeLLMClient — Client LLM unifié pour le pipeline V2 query (runtime).

Politique :
- vLLM EC2 actif (Redis burst state + health check OK) → vLLM (gratuit en spot)
- Sinon → DeepInfra Qwen3-235B (paid mais stable, non-spot)
- Sinon → exception

L'idée : si l'utilisateur a déjà allumé vLLM EC2, on l'utilise (compute déjà payé).
Si vLLM est down ou pas configuré, on bascule sur DeepInfra automatiquement.

Ce client est destiné UNIQUEMENT aux modules runtime V2 (anchor, synthesis, subject_resolver,
atlas generator). L'ingestion volumineuse (claim_extractor, post_import) garde sa propre voie
via knowbase.common.llm_router (qui pousse explicitement vers vLLM EC2).

Endpoint OpenAI-compatible. Single API : chat_completion(messages, ...).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
# Note : pour le runtime V2 (synthèses 2-4 phrases, anchor extraction, subject resolver),
# on privilégie un modèle plus petit/rapide que Qwen3-235B (40-80s). Qwen2.5-14B-Instruct
# est cohérent avec le vLLM EC2 production et ~5-10x plus rapide en synthèse.
# Override possible via env DEEPINFRA_RUNTIME_MODEL.
DEEPINFRA_DEFAULT_MODEL = "Qwen/Qwen2.5-72B-Instruct"
VLLM_DEFAULT_MODEL = "Qwen/Qwen2.5-14B-Instruct-AWQ"


class LLMBackendUnavailable(Exception):
    """Raised when no LLM backend is available."""


class RuntimeLLMClient:
    """LLM client unifié pour le pipeline V2.

    Args:
        prefer_deepinfra: si True (default), DeepInfra est utilisé en priorité
        timeout: HTTP timeout par défaut
    """

    def __init__(
        self,
        timeout: float = 120.0,
        health_check_timeout: float = 2.5,
        endpoint_cache_seconds: int = 60,
    ) -> None:
        """
        Args:
            timeout: timeout HTTP par chat_completion (défaut)
            health_check_timeout: timeout du ping vLLM /health (rapide, 2.5s)
            endpoint_cache_seconds: durée de cache de la résolution d'endpoint
                avant re-vérification de la santé vLLM (défaut 60s)
        """
        self.timeout = timeout
        self.health_check_timeout = health_check_timeout
        self.endpoint_cache_seconds = endpoint_cache_seconds
        self._endpoint: Optional[dict] = None
        self._endpoint_resolved_at: float = 0.0

    def _vllm_healthy(self, url: str) -> bool:
        """Health check rapide vLLM /health (timeout court)."""
        try:
            with httpx.Client(timeout=self.health_check_timeout) as client:
                resp = client.get(f"{url.rstrip('/')}/health")
                return resp.status_code == 200
        except Exception:
            return False

    def _read_redis_burst_state(self) -> Optional[dict]:
        """Lit Redis burst state. Retourne {vllm_url, vllm_model} ou None."""
        try:
            import redis as _redis
            r = _redis.Redis(host=os.getenv("REDIS_HOST", "redis"), port=6379, decode_responses=True)
            raw = r.get("osmose:burst:state")
            if raw:
                state = json.loads(raw)
                if state.get("active") and state.get("vllm_url"):
                    return {
                        "vllm_url": state["vllm_url"].rstrip("/"),
                        "vllm_model": state.get("vllm_model") or VLLM_DEFAULT_MODEL,
                    }
        except Exception as exc:
            logger.warning(f"Could not read Redis burst state: {exc}")
        return None

    def _resolve_endpoint(self) -> dict:
        """Résout l'endpoint actif avec cache court (re-check toutes les `endpoint_cache_seconds`).

        Politique :
        1. Tente vLLM EC2 (Redis burst state) avec health check rapide → si OK, vLLM
        2. Tente env VLLM_URL avec health check → si OK, vLLM
        3. Sinon DeepInfra (DEEPINFRA_API_KEY)
        4. Sinon LLMBackendUnavailable
        """
        import time as _time

        # Cache court : si on a résolu il y a < endpoint_cache_seconds, réutilise
        now = _time.time()
        if (
            self._endpoint is not None
            and now - self._endpoint_resolved_at < self.endpoint_cache_seconds
        ):
            return self._endpoint

        # 1. Tenter vLLM EC2 via Redis burst state (priorité — déjà payé/actif)
        burst = self._read_redis_burst_state()
        if burst and self._vllm_healthy(burst["vllm_url"]):
            self._endpoint = {
                "url": burst["vllm_url"],
                "model": burst["vllm_model"],
                "headers": {},
                "provider": "vllm_ec2",
            }
            self._endpoint_resolved_at = now
            logger.info(f"RuntimeLLMClient → vLLM EC2 ({burst['vllm_url']})")
            return self._endpoint

        # 2. Tenter env VLLM_URL avec health check
        env_url = os.getenv("VLLM_URL")
        if env_url and self._vllm_healthy(env_url):
            self._endpoint = {
                "url": env_url.rstrip("/"),
                "model": os.getenv("VLLM_MODEL", VLLM_DEFAULT_MODEL),
                "headers": {},
                "provider": "vllm_env",
            }
            self._endpoint_resolved_at = now
            logger.info(f"RuntimeLLMClient → vLLM env ({env_url})")
            return self._endpoint

        # 3. Fallback DeepInfra
        di_key = os.getenv("DEEPINFRA_API_KEY")
        if di_key:
            self._endpoint = {
                "url": DEEPINFRA_BASE_URL,
                "model": os.getenv("DEEPINFRA_RUNTIME_MODEL", DEEPINFRA_DEFAULT_MODEL),
                "headers": {"Authorization": f"Bearer {di_key}"},
                "provider": "deepinfra",
            }
            self._endpoint_resolved_at = now
            logger.info(
                f"RuntimeLLMClient → DeepInfra fallback (vLLM unavailable, model={self._endpoint['model']})"
            )
            return self._endpoint

        # 4. Aucun backend
        self._endpoint = None
        self._endpoint_resolved_at = now
        raise LLMBackendUnavailable(
            "No LLM backend available: vLLM EC2 unhealthy + VLLM_URL unhealthy + DEEPINFRA_API_KEY missing"
        )

    def chat_completion(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 1000,
        json_mode: bool = False,
        timeout: Optional[float] = None,
        model_override: Optional[str] = None,
    ) -> str:
        """Envoie un chat completion. Returns le content (string).

        Args:
            messages: liste de {role, content}
            temperature: sampling temperature
            max_tokens: borne sortie
            json_mode: si True, demande response_format JSON
            timeout: override du timeout par défaut
        """
        result = self.chat_completion_with_meta(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
            timeout=timeout,
            model_override=model_override,
        )
        return result["content"]

    def chat_completion_with_meta(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 1000,
        json_mode: bool = False,
        logprobs: bool = False,
        top_logprobs: int = 5,
        timeout: Optional[float] = None,
        model_override: Optional[str] = None,
    ) -> dict:
        """Variante de `chat_completion` qui renvoie aussi les métadonnées
        (logprobs si demandé). CH-14 — HALT/EPR Logprob Entropy.

        Returns:
            {
                "content": str,
                "logprobs": list[dict] | None,  # si logprobs=True : list de {token, logprob, top_logprobs}
                "provider": str,
                "model": str,
            }
        """
        endpoint = self._resolve_endpoint()
        if endpoint is None:
            raise LLMBackendUnavailable("No backend resolved")

        # CH-33 — model_override (DeepInfra only). Pour vLLM EC2, on garde le
        # modèle local (override ignoré, le 14B AWQ est déjà rapide).
        eff_model = endpoint["model"]
        if model_override and endpoint.get("provider") == "deepinfra":
            eff_model = model_override
        payload: dict[str, Any] = {
            "model": eff_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if logprobs:
            payload["logprobs"] = True
            payload["top_logprobs"] = top_logprobs

        eff_timeout = timeout if timeout is not None else self.timeout
        try:
            with httpx.Client(timeout=eff_timeout) as client:
                resp = client.post(
                    f"{endpoint['url']}/chat/completions",
                    json=payload,
                    headers=endpoint["headers"],
                )
                resp.raise_for_status()
                data = resp.json()
                choice = data["choices"][0]
                out = {
                    "content": choice["message"]["content"],
                    "logprobs": None,
                    "provider": endpoint["provider"],
                    "model": eff_model,
                }
                if logprobs:
                    lp = choice.get("logprobs") or {}
                    # Format OpenAI : choice.logprobs.content = [{token, logprob, top_logprobs[]}]
                    out["logprobs"] = lp.get("content")
                return out
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            logger.error(
                f"LLM call failed via {endpoint['provider']}: {exc}"
            )
            raise

    @property
    def model(self) -> str:
        ep = self._resolve_endpoint()
        return ep["model"] if ep else "unknown"

    @property
    def provider(self) -> str:
        ep = self._resolve_endpoint()
        return ep["provider"] if ep else "unknown"


# ---------------------------------------------------------------------------
# Singleton helper
# ---------------------------------------------------------------------------

_default_client: Optional[RuntimeLLMClient] = None


def get_runtime_llm_client() -> RuntimeLLMClient:
    """Singleton du client LLM runtime V2."""
    global _default_client
    if _default_client is None:
        _default_client = RuntimeLLMClient()
    return _default_client


def reset_runtime_llm_client() -> None:
    """Force re-init (utile en test ou après changement de config)."""
    global _default_client
    _default_client = None
