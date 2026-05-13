"""Tests intégration tracer + metrics dans ReasoningAgentV51 (CH-52.7.5)."""
from __future__ import annotations

import json
from typing import Optional

import pytest

from knowbase.runtime_v5.agent.workspace import EpistemicStatus
from knowbase.runtime_v5.observability.metrics import MetricsRegistry
from knowbase.runtime_v5.observability.pii import PIIRedactor
from knowbase.runtime_v5.observability.tracer import (
    InMemoryTracer,
    SpanStatus,
)
from knowbase.runtime_v5.reasoning_agent_v51 import ReasoningAgentV51
from knowbase.runtime_v5.tools.poc_tools_registration import register_poc_tools
from knowbase.runtime_v5.tools.registry import (
    EvidenceType,
    ToolCategory,
    ToolRegistry,
    ToolSpec,
)
from tests.runtime_v5.test_reasoning_agent_v51 import (  # type: ignore
    MockLLMCaller,
    _resp_final,
    _resp_tool_calls,
    _tc,
    _fake_outline,
    _fake_read,
)


@pytest.fixture
def registry_with_fakes():
    reg = ToolRegistry()
    reg.register(ToolSpec(
        name="outline",
        category=ToolCategory.NAVIGATION,
        description="Fake outline tool for tests.",
        preferred_when="overview requested",
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
        description="Fake read tool for tests.",
        preferred_when="section content needed",
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
    return reg


# ─── Tracer captures hierarchy ──────────────────────────────────────────────


class TestTracerHierarchy:
    def test_root_span_with_attributes(self, registry_with_fakes):
        tracer = InMemoryTracer()
        llm = MockLLMCaller([
            _resp_tool_calls([_tc("c1", "outline", {"doc_id": "doc_x"})]),
            _resp_final("Final."),
        ])
        agent = ReasoningAgentV51(
            llm_caller=llm,
            registry=registry_with_fakes,
            tracer=tracer,
        )
        result = agent.run(question="Q?", tenant_id="tenant_a", answer_shape="factual")

        # 1 root span gen_ai.agent.answer
        roots = tracer.get_root_spans()
        assert len(roots) == 1
        root = roots[0]
        assert root.name == "gen_ai.agent.answer"
        assert root.attributes["tenant_id"] == "tenant_a"
        assert root.attributes["answer_shape"] == "factual"
        assert root.attributes["request_id"].startswith("req_")

    def test_root_span_has_final_attributes(self, registry_with_fakes):
        tracer = InMemoryTracer()
        llm = MockLLMCaller([
            _resp_tool_calls([_tc("c1", "outline", {"doc_id": "doc_x"})]),
            _resp_final("Done."),
        ])
        agent = ReasoningAgentV51(
            llm_caller=llm, registry=registry_with_fakes, tracer=tracer,
        )
        result = agent.run(question="Q?", tenant_id="tenant_a")

        root = tracer.get_root_spans()[0]
        assert root.attributes["epistemic_status"] == "complete"
        assert root.attributes["n_iterations"] == 2  # 1 tool + 1 final
        assert root.attributes["n_tool_calls"] == 1
        assert root.status == SpanStatus.OK

    def test_llm_inference_sub_span(self, registry_with_fakes):
        tracer = InMemoryTracer()
        llm = MockLLMCaller([
            _resp_tool_calls([_tc("c1", "outline", {"doc_id": "doc_x"})]),
            _resp_final("X"),
        ])
        agent = ReasoningAgentV51(
            llm_caller=llm, registry=registry_with_fakes, tracer=tracer,
        )
        agent.run(question="Q", tenant_id="tenant_a")

        inference_spans = tracer.get_spans_by_name("gen_ai.inference")
        # 2 iters → 2 inference spans
        assert len(inference_spans) == 2
        # Each has parent_id pointing to root
        root = tracer.get_root_spans()[0]
        for s in inference_spans:
            assert s.parent_id == root.span_id
            assert "completion_tokens" in s.attributes

    def test_tool_execute_sub_spans(self, registry_with_fakes):
        tracer = InMemoryTracer()
        llm = MockLLMCaller([
            _resp_tool_calls([_tc("c1", "outline", {"doc_id": "doc_x"})]),
            _resp_tool_calls([_tc("c2", "read", {
                "doc_id": "doc_x", "section_path_or_numbering": "2",
            })]),
            _resp_final("X"),
        ])
        agent = ReasoningAgentV51(
            llm_caller=llm, registry=registry_with_fakes, tracer=tracer,
        )
        agent.run(question="Q", tenant_id="tenant_a")

        tool_spans = tracer.get_spans_by_name("gen_ai.execute_tool")
        assert len(tool_spans) == 2
        names = [s.attributes["tool_name"] for s in tool_spans]
        assert names == ["outline", "read"]
        # Latencies recorded
        for s in tool_spans:
            assert s.attributes["latency_ms"] >= 0


# ─── PII redaction dans tracer ─────────────────────────────────────────────


class TestPIIRedactionInTracer:
    def test_question_not_in_attributes_by_default(self, registry_with_fakes):
        """ADR §3g : question pas dans les attributs (tier3 only)."""
        tracer = InMemoryTracer(redactor=PIIRedactor())
        llm = MockLLMCaller([_resp_final("X")])
        agent = ReasoningAgentV51(
            llm_caller=llm, registry=registry_with_fakes, tracer=tracer,
        )
        agent.run(question="Contact me at fred@example.com", tenant_id="t_a")
        root = tracer.get_root_spans()[0]
        # Question pas exposée comme attribut root
        assert "question" not in root.attributes
        # Email PII pas dans aucun attribut
        all_attrs = json.dumps({**root.attributes,
                                **{s.name: s.attributes for s in tracer.spans}})
        assert "fred@example.com" not in all_attrs


# ─── Metrics enregistrement ─────────────────────────────────────────────────


class TestMetricsRecorded:
    def test_agent_duration_recorded(self, registry_with_fakes):
        metrics = MetricsRegistry()
        llm = MockLLMCaller([_resp_final("X")])
        agent = ReasoningAgentV51(
            llm_caller=llm, registry=registry_with_fakes, metrics=metrics,
        )
        agent.run(question="Q", tenant_id="t_a", answer_shape="factual")

        snap = metrics.snapshot()
        # Histogram doit avoir une obs sous (shape=factual, epistemic_status=complete)
        hist = snap["histograms"].get("v5_agent_answer_duration_s", {})
        # 1 obs au minimum
        assert any(d["count"] >= 1 for d in hist.values())

    def test_iterations_recorded(self, registry_with_fakes):
        metrics = MetricsRegistry()
        llm = MockLLMCaller([
            _resp_tool_calls([_tc("c1", "outline", {"doc_id": "x"})]),
            _resp_final("X"),
        ])
        agent = ReasoningAgentV51(
            llm_caller=llm, registry=registry_with_fakes, metrics=metrics,
        )
        agent.run(question="Q", tenant_id="t_a", answer_shape="factual")

        hist = metrics.snapshot()["histograms"].get("v5_agent_iterations", {})
        # 1 obs avec count=1
        assert any(d["count"] >= 1 for d in hist.values())

    def test_tool_calls_counter(self, registry_with_fakes):
        metrics = MetricsRegistry()
        llm = MockLLMCaller([
            _resp_tool_calls([_tc("c1", "outline", {"doc_id": "x"})]),
            _resp_tool_calls([_tc("c2", "read", {
                "doc_id": "x", "section_path_or_numbering": "1",
            })]),
            _resp_final("X"),
        ])
        agent = ReasoningAgentV51(
            llm_caller=llm, registry=registry_with_fakes, metrics=metrics,
        )
        agent.run(question="Q", tenant_id="t_a")

        c = metrics.snapshot()["counters"].get("v5_tool_calls_total", {})
        # 2 tool calls : outline + read, outcome=ok
        total = sum(c.values())
        assert total == 2

    def test_stop_reason_counter(self, registry_with_fakes):
        metrics = MetricsRegistry()
        llm = MockLLMCaller([_resp_final("Done.")])
        agent = ReasoningAgentV51(
            llm_caller=llm, registry=registry_with_fakes, metrics=metrics,
        )
        agent.run(question="Q", tenant_id="t_a")

        sr = metrics.snapshot()["counters"].get("v5_agent_stop_reason_total", {})
        total = sum(sr.values())
        assert total == 1


# ─── No PII default = transparent ───────────────────────────────────────────


class TestNoTracerByDefault:
    def test_works_without_tracer_provided(self, registry_with_fakes):
        """Default = NoOpTracer / default metrics. Pas de crash."""
        llm = MockLLMCaller([_resp_final("X")])
        agent = ReasoningAgentV51(llm_caller=llm, registry=registry_with_fakes)
        result = agent.run(question="Q", tenant_id="t_a")
        assert result.epistemic_status == EpistemicStatus.COMPLETE


# ─── Tool call avec repair counter ──────────────────────────────────────────


class TestRepairCounter:
    def test_repaired_tool_call_increments(self, registry_with_fakes):
        metrics = MetricsRegistry()
        llm = MockLLMCaller([
            _resp_tool_calls([_tc("c1", "outline",
                                   {"doc_id": "x", "garbage_key": "ignored"})]),
            _resp_final("X"),
        ])
        agent = ReasoningAgentV51(
            llm_caller=llm, registry=registry_with_fakes, metrics=metrics,
        )
        agent.run(question="Q", tenant_id="t_a")

        # repair counter incremented
        repair = metrics.snapshot()["counters"].get("v5_tool_call_repair_total", {})
        assert sum(repair.values()) >= 1
        # tool_calls_total avec outcome=repaired
        tc = metrics.snapshot()["counters"].get("v5_tool_calls_total", {})
        # Au moins une entrée avec outcome=repaired
        any_repaired = any("repaired" in str(k) for k in tc.keys())
        assert any_repaired


# ─── Exception path ─────────────────────────────────────────────────────────


class TestExceptionSpanCapture:
    def test_llm_error_marks_span_error(self, registry_with_fakes):
        tracer = InMemoryTracer()

        class FailingLLM(MockLLMCaller):
            def call(self, messages, tools, max_tokens=2000):
                self.n_calls += 1
                return {"error": "provider unreachable"}

        llm = FailingLLM([])
        agent = ReasoningAgentV51(
            llm_caller=llm, registry=registry_with_fakes, tracer=tracer,
        )
        result = agent.run(question="Q", tenant_id="t_a")
        assert result.epistemic_status == EpistemicStatus.ABORTED

        # Inference span should have ERROR status
        inference_spans = tracer.get_spans_by_name("gen_ai.inference")
        assert any(s.status == SpanStatus.ERROR for s in inference_spans)
