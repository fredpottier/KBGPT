"""Tests Workspace V1 schema (CH-52.5.5 / S4.7)."""
from __future__ import annotations

import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from knowbase.runtime_v5.agent.execution_plan import ExecutionPlan, PlanStep
from knowbase.runtime_v5.agent.workspace import (
    WORKSPACE_SCHEMA_VERSION,
    BudgetSnapshot,
    EpistemicStatus,
    EvidenceItem,
    LoopSignatureSnapshot,
    ToolCallRecord,
    Workspace,
)
from knowbase.runtime_v5.tools.registry import EvidenceType


# ─── Workspace creation + minimal ───────────────────────────────────────────


class TestCreation:
    def test_minimal(self):
        ws = Workspace(tenant_id="default", question="Quelle est la durée?")
        assert ws.schema_version == WORKSPACE_SCHEMA_VERSION
        assert ws.request_id.startswith("req_")
        assert ws.tool_calls == []
        assert ws.evidence_collected == []
        assert ws.finalized_at is None
        assert ws.epistemic_status is None

    def test_required_tenant_id(self):
        with pytest.raises(ValidationError):
            Workspace(tenant_id="", question="q")

    def test_required_question(self):
        with pytest.raises(ValidationError):
            Workspace(tenant_id="default", question="")

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            Workspace(tenant_id="default", question="q", garbage="oops")


# ─── Mutations runtime ──────────────────────────────────────────────────────


class TestMutations:
    def test_record_tool_call(self):
        ws = Workspace(tenant_id="default", question="q")
        rec = ws.record_tool_call(
            iter_idx=0, tool_name="outline",
            args={"doc_id": "x"}, result_summary="42 sections",
            result_chars=12000, latency_ms=250.0,
        )
        assert rec.tool_name == "outline"
        assert len(ws.tool_calls) == 1

    def test_record_tool_call_with_error(self):
        ws = Workspace(tenant_id="default", question="q")
        rec = ws.record_tool_call(
            iter_idx=0, tool_name="read", args={},
            error="section not found",
        )
        assert rec.error == "section not found"
        assert ws.tool_calls[0].error is not None

    def test_add_evidence(self):
        ws = Workspace(tenant_id="default", question="q")
        ev = ws.add_evidence(
            evidence_type=EvidenceType.FULL_SECTION_TEXT,
            doc_id="doc_x", section_id="sec_1",
            source_tool="read", iter_idx=1,
            text_excerpt="The procedure follows...", confidence=0.9,
        )
        assert ev.evidence_id.startswith("ev_")
        assert ev.confidence == 0.9
        assert len(ws.evidence_collected) == 1

    def test_record_loop_signature(self):
        ws = Workspace(tenant_id="default", question="q")
        sig = ws.record_loop_signature(
            iter_idx=0, tool="read", normalized_args='{"id":"A"}',
            evidence_gain=0.8, novelty_score=0.7,
        )
        assert sig.iter_idx == 0
        assert len(ws.loop_signatures) == 1

    def test_loop_signature_scores_clamped(self):
        ws = Workspace(tenant_id="default", question="q")
        sig = ws.record_loop_signature(
            iter_idx=0, tool="read", normalized_args="x",
            evidence_gain=1.5,  # > 1, should clamp
            novelty_score=-0.2,  # < 0, should clamp
        )
        assert sig.evidence_gain == 1.0
        assert sig.novelty_score == 0.0


# ─── Finalize ───────────────────────────────────────────────────────────────


class TestFinalize:
    def test_finalize_sets_fields(self):
        ws = Workspace(tenant_id="default", question="q")
        ws.finalize(
            final_answer="The answer is 42.",
            epistemic_status=EpistemicStatus.COMPLETE,
            stop_reason="concluded",
            latency_s=12.5,
        )
        assert ws.final_answer == "The answer is 42."
        assert ws.epistemic_status == EpistemicStatus.COMPLETE
        assert ws.stop_reason == "concluded"
        assert ws.latency_s == 12.5
        assert ws.finalized_at is not None

    def test_finalize_aborted(self):
        ws = Workspace(tenant_id="default", question="q")
        ws.finalize(
            final_answer="", epistemic_status=EpistemicStatus.ABORTED,
            stop_reason="user_cancelled", latency_s=3.2,
        )
        assert ws.epistemic_status == EpistemicStatus.ABORTED


# ─── Plan integration ───────────────────────────────────────────────────────


class TestPlanIntegration:
    def test_workspace_with_plan(self):
        plan = ExecutionPlan(
            steps=[PlanStep(
                intent="find relevant sections in doc",
                tool="find_in",
                args={"doc_id": "x", "query": "test"},
                expected_evidence_shape="section hits",
            )],
            max_iter_estimated=3,
        )
        ws = Workspace(tenant_id="default", question="q", plan=plan)
        assert ws.plan is not None
        assert len(ws.plan.steps) == 1


# ─── Serialization ──────────────────────────────────────────────────────────


class TestSerialization:
    def test_roundtrip_json(self):
        ws = Workspace(
            tenant_id="default", question="What's the value?",
            answer_shape="quantitative",
        )
        ws.record_tool_call(
            iter_idx=0, tool_name="outline",
            args={"doc_id": "x"}, result_summary="OK",
            result_chars=500, latency_ms=100.0,
        )
        ws.add_evidence(
            evidence_type=EvidenceType.STRUCTURE_INDEX,
            doc_id="doc_x", source_tool="outline", iter_idx=0,
        )
        ws.finalize(
            final_answer="42",
            epistemic_status=EpistemicStatus.COMPLETE,
            stop_reason="concluded",
            latency_s=5.0,
        )

        # Round-trip JSON
        s = ws.to_json()
        ws2 = Workspace.from_json(s)
        assert ws2.tenant_id == ws.tenant_id
        assert ws2.question == ws.question
        assert ws2.answer_shape == "quantitative"
        assert len(ws2.tool_calls) == 1
        assert ws2.tool_calls[0].tool_name == "outline"
        assert ws2.evidence_collected[0].evidence_type == EvidenceType.STRUCTURE_INDEX
        assert ws2.epistemic_status == EpistemicStatus.COMPLETE
        assert ws2.finalized_at is not None

    def test_json_indent(self):
        ws = Workspace(tenant_id="default", question="q")
        s = ws.to_json(indent=2)
        assert "\n" in s  # indented

    def test_from_dict(self):
        ws = Workspace(tenant_id="default", question="q")
        d = json.loads(ws.to_json())
        ws2 = Workspace.from_dict(d)
        assert ws2.tenant_id == "default"


# ─── doc_version_snapshot (audit reproducibility) ───────────────────────────


class TestDocVersionSnapshot:
    def test_snapshot_pinned_at_creation(self):
        ws = Workspace(
            tenant_id="default", question="q",
            doc_version_snapshot={"doc_a": 2, "doc_b": 5},
        )
        assert ws.doc_version_snapshot == {"doc_a": 2, "doc_b": 5}

    def test_snapshot_roundtrip(self):
        ws = Workspace(
            tenant_id="default", question="q",
            doc_version_snapshot={"doc_x": 3},
        )
        ws2 = Workspace.from_json(ws.to_json())
        assert ws2.doc_version_snapshot == {"doc_x": 3}


# ─── Summary ─────────────────────────────────────────────────────────────────


class TestSummary:
    def test_summary_minimal(self):
        ws = Workspace(tenant_id="default", question="q")
        s = ws.summary()
        assert s["request_id"].startswith("req_")
        assert s["n_tool_calls"] == 0
        assert s["finalized"] is False

    def test_summary_after_activity(self):
        ws = Workspace(tenant_id="default", question="q")
        ws.record_tool_call(iter_idx=0, tool_name="outline", args={})
        ws.record_tool_call(iter_idx=1, tool_name="read", args={}, error="not found")
        ws.add_evidence(
            evidence_type=EvidenceType.SECTION_HITS, doc_id="x",
            source_tool="find_in", iter_idx=2,
        )
        ws.finalize(
            final_answer="X", epistemic_status=EpistemicStatus.PARTIAL,
            stop_reason="partial", latency_s=8.0,
        )
        s = ws.summary()
        assert s["n_tool_calls"] == 2
        assert s["n_tool_errors"] == 1
        assert s["n_evidence_items"] == 1
        assert s["epistemic_status"] == "partial"
        assert s["finalized"] is True


# ─── Schema version ─────────────────────────────────────────────────────────


class TestSchemaVersion:
    def test_default_version(self):
        ws = Workspace(tenant_id="default", question="q")
        assert ws.schema_version == "v1"

    def test_version_persisted(self):
        ws = Workspace(tenant_id="default", question="q")
        ws2 = Workspace.from_json(ws.to_json())
        assert ws2.schema_version == "v1"


# ─── Charter compliance ──────────────────────────────────────────────────────


class TestCharterCompliance:
    def test_no_corpus_specific_fields(self):
        """Charte : pas de champs SAP-spécifiques ou domain-spécifiques."""
        ws = Workspace(tenant_id="default", question="q")
        fields = set(ws.model_dump().keys())
        forbidden = {"sap_solution", "rfp_id", "regulation_ref", "patient_id"}
        assert not (fields & forbidden)
