"""Tests HTTPLLMCaller (B1 — branchement HTTP réel)."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
import requests

from knowbase.runtime_v5.http_llm_caller import (
    DEFAULT_MODEL,
    HTTPLLMCaller,
    _resolve_endpoint_key,
    get_default_llm_caller,
    reset_default_llm_caller,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_default_llm_caller()
    yield
    reset_default_llm_caller()


# ─── Endpoint resolution ─────────────────────────────────────────────────────


class TestEndpointResolution:
    def test_together_priority(self, monkeypatch):
        monkeypatch.setenv("TOGETHER_API_KEY", "tk_test")
        monkeypatch.setenv("DEEPINFRA_API_KEY", "di_test")
        endpoint, key, provider = _resolve_endpoint_key()
        assert provider == "together"
        assert "together.xyz" in endpoint
        assert key == "tk_test"

    def test_deepinfra_fallback(self, monkeypatch):
        monkeypatch.delenv("TOGETHER_API_KEY", raising=False)
        monkeypatch.setenv("DEEPINFRA_API_KEY", "di_test")
        endpoint, key, provider = _resolve_endpoint_key()
        assert provider == "deepinfra"
        assert key == "di_test"

    def test_no_keys(self, monkeypatch):
        monkeypatch.delenv("TOGETHER_API_KEY", raising=False)
        monkeypatch.delenv("DEEPINFRA_API_KEY", raising=False)
        endpoint, key, provider = _resolve_endpoint_key()
        assert provider == "none"
        assert key == ""


# ─── HTTPLLMCaller init ──────────────────────────────────────────────────────


class TestInit:
    def test_default_model(self):
        c = HTTPLLMCaller()
        assert c.model == DEFAULT_MODEL

    def test_force_provider(self, monkeypatch):
        monkeypatch.setenv("DEEPINFRA_API_KEY", "x")
        monkeypatch.setenv("TOGETHER_API_KEY", "y")
        c = HTTPLLMCaller(force_provider="deepinfra")
        endpoint, key, provider = c._endpoint()
        assert provider == "deepinfra"


# ─── Mock HTTP success ───────────────────────────────────────────────────────


class TestHTTPSuccess:
    def test_simple_response(self, monkeypatch):
        monkeypatch.setenv("TOGETHER_API_KEY", "tk_test")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello", "tool_calls": None}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        with patch("requests.post", return_value=mock_response):
            c = HTTPLLMCaller()
            out = c.call(
                messages=[{"role": "user", "content": "Hi"}],
                tools=[],
                max_tokens=100,
            )
        assert "message" in out
        assert out["message"]["content"] == "Hello"
        assert out["usage"]["completion_tokens"] == 5
        assert out["_provider"] == "together"
        assert "_latency_s" in out

    def test_with_tools(self, monkeypatch):
        monkeypatch.setenv("TOGETHER_API_KEY", "tk_test")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": None,
                    "tool_calls": [{
                        "id": "c1",
                        "function": {"name": "outline", "arguments": "{\"doc_id\":\"x\"}"},
                    }],
                }
            }],
            "usage": {},
        }
        with patch("requests.post", return_value=mock_response) as mock_post:
            c = HTTPLLMCaller()
            tools = [{"type": "function", "function": {"name": "outline"}}]
            out = c.call(messages=[], tools=tools)
        # Verify payload included tool_choice='auto'
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["tool_choice"] == "auto"
        assert call_kwargs["json"]["tools"] == tools
        assert out["message"]["tool_calls"][0]["function"]["name"] == "outline"


# ─── Mock HTTP errors ────────────────────────────────────────────────────────


class TestHTTPErrors:
    def test_no_api_key(self, monkeypatch):
        monkeypatch.delenv("TOGETHER_API_KEY", raising=False)
        monkeypatch.delenv("DEEPINFRA_API_KEY", raising=False)
        c = HTTPLLMCaller()
        out = c.call(messages=[], tools=[])
        assert "error" in out
        assert "no_api_key" in out["error"]

    def test_4xx_no_retry(self, monkeypatch):
        monkeypatch.setenv("TOGETHER_API_KEY", "tk_test")

        mock_response = MagicMock()
        http_err = requests.HTTPError(response=MagicMock(status_code=400))
        http_err.response = MagicMock(status_code=400)
        mock_response.raise_for_status.side_effect = http_err

        with patch("requests.post", return_value=mock_response) as mock_post:
            c = HTTPLLMCaller(max_retries=3)
            out = c.call(messages=[], tools=[])
        # 1 call only (pas de retry pour 400)
        assert mock_post.call_count == 1
        assert "error" in out
        assert "http_400" in out["error"]

    def test_429_retries(self, monkeypatch):
        monkeypatch.setenv("TOGETHER_API_KEY", "tk_test")

        mock_response = MagicMock()
        http_err = requests.HTTPError()
        http_err.response = MagicMock(status_code=429)
        mock_response.raise_for_status.side_effect = http_err

        with patch("requests.post", return_value=mock_response) as mock_post, \
                patch("time.sleep") as mock_sleep:
            c = HTTPLLMCaller(max_retries=2)
            out = c.call(messages=[], tools=[])
        assert mock_post.call_count == 2  # retries happened
        assert "error" in out

    def test_empty_choices(self, monkeypatch):
        monkeypatch.setenv("TOGETHER_API_KEY", "tk_test")
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"choices": [], "usage": {}}
        with patch("requests.post", return_value=mock_response):
            c = HTTPLLMCaller()
            out = c.call(messages=[], tools=[])
        assert "error" in out
        assert "empty_choices" in out["error"]


# ─── Singleton ───────────────────────────────────────────────────────────────


class TestSingleton:
    def test_singleton_same_model(self, monkeypatch):
        monkeypatch.setenv("TOGETHER_API_KEY", "tk")
        c1 = get_default_llm_caller()
        c2 = get_default_llm_caller()
        assert c1 is c2

    def test_singleton_resets_on_model_change(self, monkeypatch):
        monkeypatch.setenv("TOGETHER_API_KEY", "tk")
        c1 = get_default_llm_caller(model="model_a")
        c2 = get_default_llm_caller(model="model_b")
        assert c1 is not c2
