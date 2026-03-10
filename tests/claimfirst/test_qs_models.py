# tests/claimfirst/test_qs_models.py
"""Tests Phase 1 — Modèles QS Cross-Doc v1."""

import pytest
from datetime import datetime

from knowbase.claimfirst.models.question_dimension import (
    QuestionDimension,
    VALID_VALUE_TYPES,
    VALID_OPERATORS,
)
from knowbase.claimfirst.models.resolved_scope import (
    ScopeAxis,
    ResolvedScope,
)
from knowbase.claimfirst.models.comparability_verdict import (
    ComparabilityLevel,
    ComparabilityVerdict,
    are_comparable,
)
from knowbase.claimfirst.models.qs_candidate import QSCandidate
from knowbase.claimfirst.models.question_signature import (
    QuestionSignature,
    QSValueType,
    QSExtractionMethod,
)


# ── QuestionDimension ──────────────────────────────────────────────────

class TestQuestionDimension:

    def test_make_id_deterministic(self):
        id1 = QuestionDimension.make_id("default", "min_version")
        id2 = QuestionDimension.make_id("default", "min_version")
        assert id1 == id2
        assert id1.startswith("qd_")

    def test_make_id_case_insensitive(self):
        id1 = QuestionDimension.make_id("default", "Min_Version")
        id2 = QuestionDimension.make_id("default", "min_version")
        assert id1 == id2

    def test_neo4j_roundtrip(self):
        qd = QuestionDimension(
            dimension_id="qd_test123",
            dimension_key="data_retention_period",
            canonical_question="What is the data retention period?",
            value_type="number",
            allowed_operators=[">=", "<="],
            value_comparable="strict",
            status="candidate",
            info_count=5,
            doc_count=3,
            tenant_id="default",
        )
        props = qd.to_neo4j_properties()
        restored = QuestionDimension.from_neo4j_record(props)
        assert restored.dimension_id == qd.dimension_id
        assert restored.dimension_key == qd.dimension_key
        assert restored.value_type == "number"
        assert restored.allowed_operators == [">=", "<="]
        assert restored.value_comparable == "strict"
        assert restored.info_count == 5
        assert restored.doc_count == 3

    def test_valid_value_types(self):
        for vt in ("number", "version", "boolean", "percent", "enum", "string"):
            assert vt in VALID_VALUE_TYPES

    def test_valid_operators(self):
        for op in ("=", ">=", "<=", ">", "<", "approx", "in"):
            assert op in VALID_OPERATORS


# ── ResolvedScope ──────────────────────────────────────────────────────

class TestResolvedScope:

    def test_scope_axis_roundtrip(self):
        axis = ScopeAxis(axis_key="product", value="MyProduct", value_id="ce_abc", source="claim")
        d = axis.to_dict()
        restored = ScopeAxis.from_dict(d)
        assert restored.axis_key == "product"
        assert restored.value == "MyProduct"
        assert restored.value_id == "ce_abc"

    def test_resolved_scope_roundtrip(self):
        scope = ResolvedScope(
            primary_anchor_type="product",
            primary_anchor_id="ce_123",
            primary_anchor_label="MyProduct",
            axes=[ScopeAxis(axis_key="region", value="EU")],
            scope_basis="claim_explicit",
            scope_status="resolved",
            scope_confidence=0.95,
            comparable_for_dimension=True,
        )
        d = scope.to_dict()
        restored = ResolvedScope.from_dict(d)
        assert restored.primary_anchor_type == "product"
        assert restored.scope_confidence == 0.95
        assert len(restored.axes) == 1
        assert restored.axes[0].value == "EU"
        assert restored.comparable_for_dimension is True


# ── ComparabilityVerdict ───────────────────────────────────────────────

class TestComparabilityVerdict:

    def test_not_comparable_requires_reason(self):
        with pytest.raises(ValueError):
            ComparabilityVerdict(level=ComparabilityLevel.NOT_COMPARABLE)

    def test_comparable_strict_no_reason_needed(self):
        v = ComparabilityVerdict(level=ComparabilityLevel.COMPARABLE_STRICT)
        assert v.reason is None


# ── are_comparable ─────────────────────────────────────────────────────

class _FakeQS:
    """Fake QS pour tester are_comparable."""
    def __init__(self, dimension_id, value_type="number", operator="=", scope=None):
        self.dimension_id = dimension_id
        self.value_type = value_type
        self.operator = operator
        self.scope = scope


class _FakeScope:
    def __init__(self, status="resolved", anchor_id=None, anchor_type=None, basis="claim_explicit"):
        self.scope_status = status
        self.primary_anchor_id = anchor_id
        self.primary_anchor_type = anchor_type
        self.scope_basis = basis


class TestAreComparable:

    def test_strict_same_dimension_same_scope(self):
        scope = _FakeScope(status="resolved", anchor_id="ce_1", anchor_type="product", basis="claim_explicit")
        a = _FakeQS("dim1", scope=scope)
        b = _FakeQS("dim1", scope=scope)
        v = are_comparable(a, b)
        assert v.level == ComparabilityLevel.COMPARABLE_STRICT

    def test_loose_different_anchor_same_type(self):
        sa = _FakeScope(status="resolved", anchor_id="ce_1", anchor_type="product")
        sb = _FakeScope(status="resolved", anchor_id="ce_2", anchor_type="product")
        a = _FakeQS("dim1", scope=sa)
        b = _FakeQS("dim1", scope=sb)
        v = are_comparable(a, b)
        assert v.level == ComparabilityLevel.COMPARABLE_LOOSE

    def test_dimension_mismatch(self):
        a = _FakeQS("dim1")
        b = _FakeQS("dim2")
        v = are_comparable(a, b)
        assert v.level == ComparabilityLevel.NOT_COMPARABLE
        assert v.reason == "dimension_mismatch"

    def test_operator_inversion(self):
        a = _FakeQS("dim1", operator=">=")
        b = _FakeQS("dim1", operator="<=")
        v = are_comparable(a, b)
        assert v.level == ComparabilityLevel.NOT_COMPARABLE
        assert v.reason == "incompatible_operator"

    def test_anchor_type_mismatch(self):
        sa = _FakeScope(status="resolved", anchor_id="ce_1", anchor_type="product")
        sb = _FakeScope(status="resolved", anchor_id="ce_2", anchor_type="legal_frame")
        a = _FakeQS("dim1", scope=sa)
        b = _FakeQS("dim1", scope=sb)
        v = are_comparable(a, b)
        assert v.level == ComparabilityLevel.NOT_COMPARABLE
        assert v.reason == "anchor_mismatch"

    def test_ambiguous_scope(self):
        sa = _FakeScope(status="ambiguous")
        sb = _FakeScope(status="resolved", anchor_id="ce_1")
        a = _FakeQS("dim1", scope=sa)
        b = _FakeQS("dim1", scope=sb)
        v = are_comparable(a, b)
        assert v.level == ComparabilityLevel.NEED_REVIEW


# ── QSCandidate ────────────────────────────────────────────────────────

class TestQSCandidate:

    def test_valid_candidate(self):
        c = QSCandidate(
            claim_id="c1", doc_id="d1",
            candidate_question="What is the min version?",
            candidate_dimension_key="min_version",
            value_type="version", value_raw="1.2", operator=">=",
        )
        assert c.is_valid()

    def test_invalid_value_type(self):
        c = QSCandidate(
            claim_id="c1", doc_id="d1",
            candidate_question="Q?",
            candidate_dimension_key="k",
            value_type="INVALID", value_raw="x",
        )
        assert not c.is_valid()

    def test_invalid_operator(self):
        c = QSCandidate(
            claim_id="c1", doc_id="d1",
            candidate_question="Q?",
            candidate_dimension_key="k",
            value_type="number", value_raw="5", operator="~",
        )
        assert not c.is_valid()

    def test_abstain_not_valid(self):
        c = QSCandidate(
            claim_id="c1", doc_id="d1",
            candidate_question="Q?",
            candidate_dimension_key="k",
            value_type="number", value_raw="5",
            abstain_reason="too vague",
        )
        assert not c.is_valid()


# ── QuestionSignature v2 ──────────────────────────────────────────────

class TestQuestionSignatureV2:

    def test_neo4j_roundtrip_v2(self):
        scope = ResolvedScope(
            primary_anchor_type="product",
            primary_anchor_id="ce_abc",
            primary_anchor_label="MyProduct",
            scope_basis="claim_explicit",
            scope_status="resolved",
            scope_confidence=0.95,
            comparable_for_dimension=True,
        )
        qs = QuestionSignature(
            qs_id="qs_test",
            claim_id="c1",
            doc_id="d1",
            question="What is the min version?",
            dimension_key="min_version",
            dimension_id="qd_abc",
            canonical_question="What is the minimum version required?",
            value_type=QSValueType.VERSION,
            extracted_value="1.2",
            value_normalized="1.2",
            operator=">=",
            extraction_method=QSExtractionMethod.LLM_LEVEL_B,
            confidence=0.9,
            gate_label="COMPARABLE_FACT",
            gating_signals=["strong:version_explicit"],
        )
        qs.set_resolved_scope(scope)

        props = qs.to_neo4j_properties()
        assert props["dimension_id"] == "qd_abc"
        assert props["extraction_method"] == "llm_level_b"
        assert props["scope_anchor_type"] == "product"

        restored = QuestionSignature.from_neo4j_record(props)
        assert restored.dimension_id == "qd_abc"
        assert restored.extraction_method == QSExtractionMethod.LLM_LEVEL_B
        assert restored.operator == ">="
        rs = restored.get_resolved_scope()
        assert rs is not None
        assert rs.primary_anchor_type == "product"

    def test_legacy_compat(self):
        """V1 records sans extraction_method doivent être désérialisables."""
        record = {
            "qs_id": "qs_old",
            "claim_id": "c1",
            "doc_id": "d1",
            "question": "Q?",
            "dimension_key": "k",
            "value_type": "number",
            "extracted_value": "5",
            "extraction_level": "level_b",
            "confidence": 0.85,
            "created_at": "2026-01-01T00:00:00",
        }
        qs = QuestionSignature.from_neo4j_record(record)
        assert qs.extraction_method == QSExtractionMethod.LLM_LEVEL_B
        assert qs.extraction_level.value == "level_b"
