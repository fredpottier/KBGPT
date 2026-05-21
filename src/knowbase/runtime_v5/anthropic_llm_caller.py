"""V5 AnthropicLLMCaller — Claude (Sonnet/Opus/Haiku) wrapper pour bench calibration.

⚠️ DEPRECATED (A3.6, 2026-05-21) — Réf ADR_PARSE_EVALUATE_RUNTIME §10.2.

Ce module sera supprimé une fois :
- Bench A3.8 validé (gates GA3-5/6/7 atteints)
- Phase B cross-domain validée
- V5.1 retiré comme endpoint de référence

Viole la charte open-source OSMOSIS (cf mémoire `feedback_no_proprietary_llm_in_production`
du 10/05/2026) : Claude/GPT-4o interdits en runtime production.

⚠️ USAGE STRICTEMENT LIMITÉ : bench de calibration ponctuel uniquement
(mesure plafond LLM). Ne JAMAIS activer en production.
⚠️ NE PAS étendre. Pour nouveaux développements, voir runtime_a3/ (open-source only).

---

Convertit l'API Anthropic native → format OpenAI attendu par ReasoningAgentV51 :
  - messages : extrait `system` séparé
  - tools : convert {name, description, parameters} → {name, description, input_schema}
  - response : content blocks (text + tool_use) → message {content, tool_calls}
  - usage : {input_tokens, output_tokens} → {prompt_tokens, completion_tokens}
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Optional

from knowbase.runtime_v5.reasoning_agent_v51 import LLMCaller

logger = logging.getLogger(__name__)

# Warning DEPRECATED (A3.6, 2026-05-21) — émis une fois par import
if not globals().get("_DEPRECATED_WARNED", False):
    logger.warning(
        "⚠️ DEPRECATED module loaded: runtime_v5.anthropic_llm_caller. "
        "Violates OSMOSIS open-source charter (no Claude/GPT in production runtime). "
        "Bench-calibration use only. Removal scheduled post-A3.8. "
        "See doc/ongoing/POST_A36_V51_SUPPRESSIONS_AUDIT_2026-05-21.md"
    )
    _DEPRECATED_WARNED = True


DEFAULT_MODEL = "claude-sonnet-4-6"  # latest Sonnet via API name


class AnthropicLLMCaller(LLMCaller):
    """Anthropic Claude wrapper avec conversion format → OpenAI compatible."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        timeout_s: int = 300,
        max_retries: int = 3,
    ):
        self.model = model
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self._client = None
        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            logger.warning(
                "[AnthropicLLMCaller] No ANTHROPIC_API_KEY in env. "
                "Calls will fail until configured."
            )

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(
                api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
                timeout=self.timeout_s,
            )
        return self._client

    @staticmethod
    def _split_system_messages(messages: list[dict]) -> tuple[str, list[dict]]:
        """Extrait le system prompt (Anthropic le veut en param séparé)."""
        system_parts = []
        user_msgs = []
        for m in messages:
            role = m.get("role", "user")
            if role == "system":
                system_parts.append(m.get("content", "") or "")
            else:
                user_msgs.append(m)
        return "\n\n".join(system_parts), user_msgs

    @staticmethod
    def _convert_messages_to_anthropic(messages: list[dict]) -> list[dict]:
        """Convertit messages OpenAI → Anthropic format.

        - user / assistant: content peut être string ou list de content blocks
        - tool messages OpenAI ({"role":"tool", "tool_call_id":..., "content":...})
          → user message avec content[0] = tool_result block
        - assistant messages avec tool_calls → content = [text + tool_use blocks]
        """
        out = []
        for m in messages:
            role = m.get("role")
            if role == "tool":
                # Tool result message → user message with tool_result block
                out.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": m.get("tool_call_id", ""),
                        "content": str(m.get("content", "") or ""),
                    }],
                })
            elif role == "assistant":
                content = m.get("content") or ""
                tool_calls = m.get("tool_calls") or []
                blocks = []
                if content:
                    blocks.append({"type": "text", "text": content})
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    try:
                        tool_input = json.loads(fn.get("arguments", "{}") or "{}")
                    except json.JSONDecodeError:
                        tool_input = {}
                    blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id", f"toolu_{uuid.uuid4().hex[:12]}"),
                        "name": fn.get("name", ""),
                        "input": tool_input,
                    })
                if not blocks:
                    blocks = [{"type": "text", "text": ""}]
                out.append({"role": "assistant", "content": blocks})
            else:
                # user / fallback
                content = m.get("content")
                if isinstance(content, list):
                    out.append({"role": "user", "content": content})
                else:
                    out.append({"role": "user", "content": str(content or "")})
        return out

    @staticmethod
    def _convert_tools_to_anthropic(tools: list[dict]) -> list[dict]:
        """Convertit tools OpenAI format → Anthropic format.

        OpenAI : {"type":"function", "function":{"name", "description", "parameters"}}
        Anthropic : {"name", "description", "input_schema"}
        """
        out = []
        for t in tools:
            fn = t.get("function", {}) if t.get("type") == "function" else t
            out.append({
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            })
        return out

    @staticmethod
    def _convert_response_to_openai(response) -> dict:
        """Convertit Anthropic response → format OpenAI {message, usage}."""
        content_text_parts = []
        tool_calls = []
        for block in response.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                content_text_parts.append(block.text or "")
            elif btype == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": json.dumps(block.input or {}),
                    },
                })
        msg = {
            "role": "assistant",
            "content": "\n".join(content_text_parts) if content_text_parts else None,
        }
        if tool_calls:
            msg["tool_calls"] = tool_calls

        usage_obj = response.usage
        usage = {
            "prompt_tokens": getattr(usage_obj, "input_tokens", 0),
            "completion_tokens": getattr(usage_obj, "output_tokens", 0),
        }
        return {"message": msg, "usage": usage, "_provider": "anthropic",
                "stop_reason": getattr(response, "stop_reason", None)}

    def call(
        self,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 2000,
    ) -> dict:
        """Sync LLM call (Anthropic API → OpenAI compatible response)."""
        import anthropic
        client = self._get_client()

        system_text, conv_messages = self._split_system_messages(messages)
        anthropic_messages = self._convert_messages_to_anthropic(conv_messages)
        anthropic_tools = self._convert_tools_to_anthropic(tools) if tools else []

        kwargs = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": 0.0,
            "messages": anthropic_messages,
        }
        if system_text:
            kwargs["system"] = system_text
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools

        last_err = None
        for attempt in range(self.max_retries):
            try:
                t0 = time.time()
                resp = client.messages.create(**kwargs)
                latency = time.time() - t0
                out = self._convert_response_to_openai(resp)
                out["_latency_s"] = latency
                return out
            except anthropic.APIStatusError as e:
                last_err = f"http_{e.status_code}: {e}"
                if e.status_code < 500 and e.status_code != 429:
                    return {"error": last_err, "_provider": "anthropic"}
            except anthropic.APIConnectionError as e:
                last_err = f"connection: {e}"
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"
            if attempt < self.max_retries - 1:
                backoff = min(2 ** (attempt + 1), 30)
                logger.info(
                    f"[AnthropicLLMCaller] Retry {attempt+1} after {backoff}s (err={last_err})"
                )
                time.sleep(backoff)
        return {"error": last_err or "unknown_error", "_provider": "anthropic"}
