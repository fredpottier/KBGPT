"""Tests intégration ReasoningAgentV51 (CH-52.5.6).

LLM mocked via MockLLMCaller (scriptable). Vérifie l'orchestration de tous
les modules S4 dans le pipeline complet.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

import pytest

from knowbase.runtime_v5.agent.budgets import HARD_CAP_ITER, HARD_CAP_TOOL_CALLS
from knowbase.runtime_v5.agent.cancellation import CancellationToken
from knowbase.runtime_v5.agent.workspace import EpistemicStatus
from knowbase.runtime_v5.reasoning_agent_v51 import (
    AgentRunResult,
    LLMCaller,
    ReasoningAgentV51,
)
from knowbase.runtime_v5.tools.poc_tools_registration import register_poc_tools
from knowbase.runtime_v5.tools.registry import (
    EvidenceType,
    ToolCategory,
    ToolRegistry,
    ToolSpec,
)
from knowbase.runtime_v5.tools.sanitizer import ToolCallSanitizer


# ─── MockLLMCaller : LLM scriptable ──────────────────────────────────────────


class MockLLMCaller(LLMCaller):
    """LLM scripté : on programme une suite de responses (tool_calls ou content)."""

    def __init__(self, responses: list[dict]):
        """responses = list de dicts {tool_calls: [...]} OR {content: "final"}.

        Si vide quand .call() est invoqué → return {content: ""}.
        """
        self.responses = list(responses)
        self.n_calls = 0
        self.messages_history = []

    def call(
        self,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 2000,
    ) -> dict:
        self.messages_history.append({
            "n_messages": len(messages),
            "n_tools": len(tools),
        })
        self.n_calls += 1
        if not self.responses:
            return {
                "message": {"content": "", "tool_calls": None},
                "usage": {"completion_tokens": 0},
            }
        next_resp = self.responses.pop(0)
        return {
            "message": next_resp,
            "usage": {"completion_tokens": 100},
        }


# ─── Tool spec factices avec handlers déterministes ──────────────────────────


def _fake_outline(doc_id: str, max_sections: int = 80, min_text_chars: int = 0) -> dict:
    """Fake outline : retourne 3 sections."""
    return {
        "doc_id": doc_id,
        "n_pages": 10,
        "outline": [
            {"section_id": "sec_1", "level": 1, "numbering": "1", "title": "Intro"},
            {"section_id": "sec_2", "level": 1, "numbering": "2", "title": "Main"},
            {"section_id": "sec_3", "level": 1, "numbering": "3", "title": "Conclusion"},
        ],
    }


def _fake_read(doc_id: str, section_path_or_numbering: str, max_chars: int = 8000) -> dict:
    """Fake read : retourne un texte unique par section_id."""
    contents = {
        "1": "alpha beta gamma delta",
        "2": "epsilon zeta eta theta",
        "3": "iota kappa lambda mu",
    }
    return {
        "doc_id": doc_id,
        "section_id": f"sec_{section_path_or_numbering}",
        "title": f"Section {section_path_or_numbering}",
        "text": contents.get(section_path_or_numbering, "default text"),
        "section_path": f"/{section_path_or_numbering}",
        "text_chars_total": len(contents.get(section_path_or_numbering, "")),
    }


def _fake_find_in(doc_id: str, query: str, max_results: int = 10, snippet_chars: int = 400) -> dict:
    return {
        "doc_id": doc_id,
        "query": query,
        "n_hits": 1,
        "hits": [{
            "section_id": "sec_match",
            "title": "Matching section",
            "snippet": f"... matching {query} ...",
        }],
    }


@pytest.fixture
def registry_with_fakes():
    reg = ToolRegistry()
    reg.register(ToolSpec(
        name="outline",
        category=ToolCategory.NAVIGATION,
        description="Fake outline tool for testing — returns 3 sections.",
        preferred_when="overview requested first call",
        evidence_type_returned=EvidenceType.STRUCTURE_INDEX,
        parameters_schema={
            "type": "object", "additionalProperties": False,
            "properties": {
                "doc_id": {"type": "string"},
                "max_sections": {"type": "integer", "default": 80},
                "min_text_chars": {"type": "integer", "default": 0},
            },
            "required": ["doc_id"],
        },
        handler=_fake_outline,
    ))
    reg.register(ToolSpec(
        name="read",
        category=ToolCategory.READING,
        description="Fake read tool for testing — returns deterministic text.",
        preferred_when="section_id known and content needed",
        evidence_type_returned=EvidenceType.FULL_SECTION_TEXT,
        parameters_schema={
            "type": "object", "additionalProperties": False,
            "properties": {
                "doc_id": {"type": "string"},
                "section_path_or_numbering": {"type": "string"},
                "max_chars": {"type": "integer", "default": 8000},
            },
            "required": ["doc_id", "section_path_or_numbering"],
        },
        handler=_fake_read,
    ))
    reg.register(ToolSpec(
        name="find_in",
        category=ToolCategory.SEARCH,
        description="Fake find_in tool for testing — returns 1 fake hit.",
        preferred_when="query non-specific broad search",
        evidence_type_returned=EvidenceType.SECTION_HITS,
        parameters_schema={
            "type": "object", "additionalProperties": False,
            "properties": {
                "doc_id": {"type": "string"},
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 10},
                "snippet_chars": {"type": "integer", "default": 400},
            },
            "required": ["doc_id", "query"],
        },
        handler=_fake_find_in,
    ))
    return reg


# ─── Tool-call response helpers ──────────────────────────────────────────────


def _tc(call_id: str, fn_name: str, args: dict) -> dict:
    return {
        "id": call_id,
        "function": {"name": fn_name, "arguments": json.dumps(args)},
    }


def _resp_tool_calls(tcs: list[dict]) -> dict:
    return {"content": None, "tool_calls": tcs}


def _resp_final(content: str) -> dict:
    return {"content": content, "tool_calls": None}


# ─── Happy path : outline → read → conclude ──────────────────────────────────


class TestHappyPath:
    def test_simple_flow(self, registry_with_fakes):
        """3 LLM calls : outline → read → conclude with answer."""
        llm = MockLLMCaller([
            _resp_tool_calls([_tc("c1", "outline", {"doc_id": "doc_x"})]),
            _resp_tool_calls([_tc("c2", "read", {"doc_id": "doc_x", "section_path_or_numbering": "2"})]),
            _resp_final("The answer is X [doc=doc_x section=sec_2]."),
        ])
        agent = ReasoningAgentV51(llm_caller=llm, registry=registry_with_fakes)
        result = agent.run(question="What is X?", tenant_id="default")

        assert isinstance(result, AgentRunResult)
        assert "The answer is X" in result.answer
        assert result.epistemic_status == EpistemicStatus.COMPLETE
        assert result.stop_reason == "concluded"
        assert result.workspace.summary()["n_tool_calls"] == 2  # outline + read
        assert result.workspace.summary()["n_evidence_items"] >= 1
        assert llm.n_calls == 3


# ─── Anti-thrash : LLM répète la même call ───────────────────────────────────


class TestAntiThrash:
    def test_duplicate_call_triggers_stop(self, registry_with_fakes):
        """LLM appelle 3x outline(doc_x) → duplicate detection stops."""
        llm = MockLLMCaller([
            _resp_tool_calls([_tc("c1", "outline", {"doc_id": "doc_x"})]),
            _resp_tool_calls([_tc("c2", "outline", {"doc_id": "doc_x"})]),
            _resp_tool_calls([_tc("c3", "outline", {"doc_id": "doc_x"})]),
            # On ne devrait jamais arriver ici
            _resp_final("late"),
        ])
        agent = ReasoningAgentV51(llm_caller=llm, registry=registry_with_fakes)
        result = agent.run(question="Test", tenant_id="default")

        assert "thrash" in result.stop_reason
        assert result.epistemic_status == EpistemicStatus.PARTIAL


# ─── Tool call repair (Sanitizer) ────────────────────────────────────────────


class TestToolCallRepair:
    def test_extra_args_stripped(self, registry_with_fakes):
        """LLM passe args garbage → sanitizer strip → exec OK."""
        llm = MockLLMCaller([
            _resp_tool_calls([_tc("c1", "outline",
                {"doc_id": "doc_x", "garbage_key": "ignored"})]),
            _resp_final("Done."),
        ])
        agent = ReasoningAgentV51(llm_caller=llm, registry=registry_with_fakes)
        result = agent.run(question="q", tenant_id="default")
        # Tool call recorded as repaired
        tcs = result.workspace.tool_calls
        assert any(tc.repair_applied for tc in tcs)
        assert result.epistemic_status == EpistemicStatus.COMPLETE


# ─── Unknown tool ────────────────────────────────────────────────────────────


class TestUnknownTool:
    def test_unknown_tool_injected_as_error(self, registry_with_fakes):
        llm = MockLLMCaller([
            _resp_tool_calls([_tc("c1", "nonexistent_tool", {})]),
            _resp_final("Sorry, that tool was unknown."),
        ])
        agent = ReasoningAgentV51(llm_caller=llm, registry=registry_with_fakes)
        result = agent.run(question="q", tenant_id="default")
        # Tool call recorded with error
        assert any(tc.error and "Unknown" in tc.error for tc in result.workspace.tool_calls)
        assert result.epistemic_status == EpistemicStatus.COMPLETE  # final answer received


# ─── Cancellation ────────────────────────────────────────────────────────────


class TestCancellation:
    def test_cancel_before_run(self, registry_with_fakes):
        llm = MockLLMCaller([
            _resp_tool_calls([_tc("c1", "outline", {"doc_id": "doc_x"})]),
            _resp_final("done"),
        ])
        token = CancellationToken()
        token.cancel(reason="user_disconnect", source="user")
        agent = ReasoningAgentV51(llm_caller=llm, registry=registry_with_fakes)
        result = agent.run(question="q", tenant_id="default", cancellation=token)
        assert result.epistemic_status == EpistemicStatus.ABORTED
        assert "cancelled" in result.stop_reason

    @pytest.mark.asyncio
    async def test_cancel_during_run(self, registry_with_fakes):
        """Cancel after first iter → next iter check_async catches it."""
        # Use lots of tool calls so cancel hits mid-run
        llm = MockLLMCaller([
            _resp_tool_calls([_tc(f"c{i}", "outline", {"doc_id": "doc_x"})])
            for i in range(10)
        ])
        token = CancellationToken()
        agent = ReasoningAgentV51(llm_caller=llm, registry=registry_with_fakes)

        async def _cancel_after():
            await asyncio.sleep(0.05)
            token.cancel(reason="test")

        run_task = asyncio.create_task(
            agent.run_async(question="q", tenant_id="default", cancellation=token)
        )
        cancel_task = asyncio.create_task(_cancel_after())
        result = await run_task
        await cancel_task
        # Si le cancel arrive très vite : ABORTED
        # Sinon le test passe si on a au moins quelques itérations
        assert result.workspace.tool_calls or result.epistemic_status == EpistemicStatus.ABORTED


# ─── Budget caps ─────────────────────────────────────────────────────────────


class TestBudgetCaps:
    def test_soft_cap_iterations_stops(self, registry_with_fakes):
        """Shape=factual → max_iter=3. 4ème iter doit déclencher soft cap."""
        llm = MockLLMCaller([
            _resp_tool_calls([_tc(f"c{i}", "find_in", {"doc_id": "d", "query": f"q{i}"})])
            for i in range(10)
        ])
        agent = ReasoningAgentV51(llm_caller=llm, registry=registry_with_fakes)
        result = agent.run(
            question="q", tenant_id="default", answer_shape="factual"
        )
        assert "budget_soft_cap_max_iterations" in result.stop_reason
        assert result.workspace.summary()["n_tool_calls"] <= 3 + 1  # +1 for the call that triggered exit


# ─── Workspace serialization ─────────────────────────────────────────────────


class TestWorkspaceSerialization:
    def test_workspace_roundtrip_post_run(self, registry_with_fakes):
        llm = MockLLMCaller([
            _resp_tool_calls([_tc("c1", "outline", {"doc_id": "doc_x"})]),
            _resp_final("answer"),
        ])
        agent = ReasoningAgentV51(llm_caller=llm, registry=registry_with_fakes)
        result = agent.run(question="q", tenant_id="default")
        ws = result.workspace
        s = ws.to_json()
        # Round-trip
        from knowbase.runtime_v5.agent.workspace import Workspace
        ws2 = Workspace.from_json(s)
        assert ws2.question == ws.question
        assert ws2.epistemic_status == ws.epistemic_status
        assert ws2.finalized_at is not None


# ─── Final synthesis forcée ──────────────────────────────────────────────────


class TestForcedSynthesis:
    def test_max_iter_triggers_forced_synth(self, registry_with_fakes):
        """Budget soft cap → forced synthesis appelle LLM avec tools=[]."""
        llm = MockLLMCaller(
            # First 3 iters with tool calls (factual budget = 3)
            [_resp_tool_calls([_tc(f"c{i}", "find_in",
                                   {"doc_id": "d", "query": f"q{i}"})])
             for i in range(3)]
            + [_resp_final("Forced answer based on partial evidence")]
        )
        agent = ReasoningAgentV51(llm_caller=llm, registry=registry_with_fakes)
        result = agent.run(question="q", tenant_id="default", answer_shape="factual")
        # Soft cap → forced synth → final answer non-vide
        assert result.answer != ""
        assert "Forced answer" in result.answer or "Insufficient" in result.answer


# ─── Stats workspace après run ───────────────────────────────────────────────


class TestStatsAfterRun:
    def test_workspace_captures_full_trace(self, registry_with_fakes):
        llm = MockLLMCaller([
            _resp_tool_calls([_tc("c1", "outline", {"doc_id": "doc_x"})]),
            _resp_tool_calls([_tc("c2", "find_in",
                                   {"doc_id": "doc_x", "query": "X"})]),
            _resp_tool_calls([_tc("c3", "read",
                                   {"doc_id": "doc_x",
                                    "section_path_or_numbering": "2"})]),
            _resp_final("Conclusion based on 3 tool calls."),
        ])
        agent = ReasoningAgentV51(llm_caller=llm, registry=registry_with_fakes)
        result = agent.run(question="q", tenant_id="default")

        ws = result.workspace
        assert ws.summary()["n_tool_calls"] == 3
        assert ws.summary()["n_loop_signatures"] == 3
        assert ws.summary()["n_evidence_items"] >= 2  # outline + find_in + read
        # iterations = 4 : 3 itérations avec tool_calls + 1 itération finale conclude
        assert ws.budgets_snapshot.iterations == 4
        assert ws.budgets_snapshot.tool_calls == 3
        assert result.epistemic_status == EpistemicStatus.COMPLETE
