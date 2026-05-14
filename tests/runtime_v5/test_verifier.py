"""Tests GroundingVerifier complet (CH-52.8.2-6)."""
from __future__ import annotations

import pytest

from knowbase.runtime_v5.verifier.answer_checks import (
    check_contradictory_citations,
    check_missing_qualifier,
    check_unsupported_numeric_transform,
    check_version_mismatch,
    run_answer_level_checks,
)
from knowbase.runtime_v5.verifier.backends import (
    MockNLIBackend,
    NLICheckResult,
    NLIDecision,
    NoOpVerifier,
    ScoreThresholdAdapter,
)
from knowbase.runtime_v5.verifier.claim_segmenter import ClaimSegmenter
from knowbase.runtime_v5.verifier.failure import (
    RETRYABLE_REASONS,
    FailureReason,
    VerifierFailure,
    is_retryable,
    make_failure,
)
from knowbase.runtime_v5.verifier.grounding_verifier import (
    GroundingVerifier,
    VerificationOutcome,
    VerificationReport,
)
from knowbase.runtime_v5.verifier.thresholds import (
    DEFAULT_THRESHOLDS_BY_SHAPE,
    ShapeThreshold,
    get_threshold,
    youden_j_calibrate,
)


# ════════════════════════════════════════════════════════════════════════════
# Backends (S7.2)
# ════════════════════════════════════════════════════════════════════════════


class TestNoOpVerifier:
    def test_always_supported(self):
        v = NoOpVerifier()
        r = v.check("claim text", "evidence text")
        assert r.decision == NLIDecision.SUPPORTED
        assert r.score == 1.0


class TestMockNLIBackend:
    def test_default(self):
        b = MockNLIBackend()
        r = b.check("any claim", "evidence")
        assert r.decision == NLIDecision.SUPPORTED

    def test_keyword_match(self):
        b = MockNLIBackend(
            default_decision=NLIDecision.SUPPORTED,
            keyword_decisions={"wrong": (NLIDecision.CONTRADICTED, 0.1)},
        )
        r = b.check("this is wrong info", "evidence")
        assert r.decision == NLIDecision.CONTRADICTED
        assert r.score == 0.1

    def test_calls_recorded(self):
        b = MockNLIBackend()
        b.check("c1", "e1")
        b.check("c2", "e2")
        assert b.calls_recorded == [("c1", "e1"), ("c2", "e2")]


class TestScoreThresholdAdapter:
    def test_thresholds_applied(self):
        backend = MockNLIBackend(default_score=0.8)
        adapter = ScoreThresholdAdapter(
            backend, support_threshold=0.7, contradict_threshold=0.3,
        )
        r = adapter.check("claim", "evidence")
        # score 0.8 >= 0.7 → SUPPORTED
        assert r.decision == NLIDecision.SUPPORTED

    def test_below_contradict(self):
        backend = MockNLIBackend(default_score=0.1)
        adapter = ScoreThresholdAdapter(
            backend, support_threshold=0.7, contradict_threshold=0.3,
        )
        r = adapter.check("claim", "evidence")
        assert r.decision == NLIDecision.CONTRADICTED

    def test_neutral_zone(self):
        backend = MockNLIBackend(default_score=0.5)
        adapter = ScoreThresholdAdapter(
            backend, support_threshold=0.7, contradict_threshold=0.3,
        )
        r = adapter.check("claim", "evidence")
        assert r.decision == NLIDecision.NEUTRAL

    def test_invalid_thresholds_rejected(self):
        backend = NoOpVerifier()
        with pytest.raises(ValueError):
            ScoreThresholdAdapter(backend, support_threshold=0.2, contradict_threshold=0.5)


# ════════════════════════════════════════════════════════════════════════════
# Failure types (S7.5)
# ════════════════════════════════════════════════════════════════════════════


class TestFailureTypes:
    def test_retryable_subset(self):
        assert FailureReason.MISSING_EVIDENCE in RETRYABLE_REASONS
        assert FailureReason.CITATION_MISMATCH in RETRYABLE_REASONS
        assert FailureReason.VERSION_CONFLICT not in RETRYABLE_REASONS
        assert FailureReason.CROSS_TENANT not in RETRYABLE_REASONS

    def test_make_failure_auto_retryable(self):
        f = make_failure(FailureReason.MISSING_EVIDENCE, "no evidence")
        assert f.retryable is True
        f2 = make_failure(FailureReason.VERSION_CONFLICT, "v1 vs v2")
        assert f2.retryable is False

    def test_is_retryable(self):
        assert is_retryable(FailureReason.MISSING_EVIDENCE) is True
        assert is_retryable(FailureReason.UNSUPPORTED_NUMERIC_TRANSFORM) is False


# ════════════════════════════════════════════════════════════════════════════
# Thresholds (S7.4)
# ════════════════════════════════════════════════════════════════════════════


class TestThresholds:
    def test_factual_threshold(self):
        t = get_threshold("factual")
        assert t.support == 0.65
        assert t.inverted is False

    def test_unanswerable_inverted(self):
        t = get_threshold("unanswerable")
        assert t.inverted is True

    def test_unknown_shape_fallback(self):
        t = get_threshold("invented_shape")
        assert t.support == 0.55  # fallback multi_hop

    def test_none_shape_fallback(self):
        t = get_threshold(None)
        assert t.support == 0.55

    def test_validate_invalid(self):
        with pytest.raises(ValueError):
            ShapeThreshold(support=0.3, contradict=0.5).validate()

    def test_all_default_shapes_valid(self):
        for shape, _ in DEFAULT_THRESHOLDS_BY_SHAPE.items():
            t = get_threshold(shape)
            t.validate()


class TestYoudenJ:
    def test_perfect_separation(self):
        pos = [0.8, 0.9, 0.95]
        neg = [0.1, 0.2, 0.3]
        t, j = youden_j_calibrate(pos, neg)
        assert j > 0.9
        assert 0.3 < t <= 0.8

    def test_overlap(self):
        pos = [0.5, 0.6, 0.7]
        neg = [0.4, 0.5, 0.6]
        t, j = youden_j_calibrate(pos, neg)
        assert j > 0
        assert t > 0

    def test_empty_inputs_raises(self):
        with pytest.raises(ValueError):
            youden_j_calibrate([], [0.1])
        with pytest.raises(ValueError):
            youden_j_calibrate([0.5], [])


# ════════════════════════════════════════════════════════════════════════════
# Answer-level checks (S7.3)
# ════════════════════════════════════════════════════════════════════════════


def _make_claim(text, citations_raw=None, claim_type=None):
    from knowbase.runtime_v5.verifier.claim_segmenter import (
        Claim, CitationRefExtracted, ClaimType,
    )
    citations = [
        CitationRefExtracted(raw=r["raw"], doc_id=r.get("doc_id"),
                             section_id=r.get("section_id"))
        for r in (citations_raw or [])
    ]
    return Claim(
        text=text,
        claim_type=claim_type or ClaimType.FACTUAL,
        citations=citations,
        span_start=0,
        span_end=len(text),
        has_citation=bool(citations),
    )


class TestContradictoryCitations:
    def test_diverging_numerics_diff_sources(self):
        from knowbase.runtime_v5.verifier.claim_segmenter import ClaimType
        claims = [
            _make_claim(
                "The recovery time is 4 hours under standard contract",
                citations_raw=[{"raw": "[doc=d1]", "doc_id": "d1"}],
                claim_type=ClaimType.NUMERIC,
            ),
            _make_claim(
                "The recovery time is 12 hours under standard contract",
                citations_raw=[{"raw": "[doc=d2]", "doc_id": "d2"}],
                claim_type=ClaimType.NUMERIC,
            ),
        ]
        failures = check_contradictory_citations(claims)
        assert len(failures) >= 1
        assert failures[0].reason == FailureReason.CONTRADICTORY_CITATIONS

    def test_same_source_no_failure(self):
        from knowbase.runtime_v5.verifier.claim_segmenter import ClaimType
        claims = [
            _make_claim(
                "Cost is 100 EUR",
                citations_raw=[{"raw": "[doc=d1]", "doc_id": "d1"}],
                claim_type=ClaimType.NUMERIC,
            ),
            _make_claim(
                "Cost is 200 EUR",
                citations_raw=[{"raw": "[doc=d1]", "doc_id": "d1"}],
                claim_type=ClaimType.NUMERIC,
            ),
        ]
        # Same source → pas failure (le verifier ne juge pas la contradiction interne d'1 source)
        failures = check_contradictory_citations(claims)
        assert failures == []


class TestVersionMismatch:
    def test_multiple_versions_same_doc(self):
        claims = [
            _make_claim(
                "In version 2023, the procedure follows X",
                citations_raw=[{"raw": "[doc=d1]", "doc_id": "d1"}],
            ),
            _make_claim(
                "In 2022, the same procedure followed Y",
                citations_raw=[{"raw": "[doc=d1]", "doc_id": "d1"}],
            ),
        ]
        failures = check_version_mismatch(claims)
        assert len(failures) >= 1
        assert failures[0].reason == FailureReason.VERSION_CONFLICT

    def test_no_version_mention(self):
        claims = [
            _make_claim("Procedure follows step A",
                        citations_raw=[{"raw": "[doc=d1]", "doc_id": "d1"}])
        ]
        failures = check_version_mismatch(claims)
        assert failures == []


class TestUnsupportedNumericTransform:
    def test_transform_without_compute_tool(self):
        from knowbase.runtime_v5.verifier.claim_segmenter import ClaimType
        claims = [
            _make_claim(
                "Performance improved 30 percent compared to v1",
                citations_raw=[{"raw": "[doc=d1]", "doc_id": "d1"}],
                claim_type=ClaimType.NUMERIC,
            ),
        ]
        failures = check_unsupported_numeric_transform(claims, cited_tool_names=set())
        assert len(failures) >= 1
        assert failures[0].reason == FailureReason.UNSUPPORTED_NUMERIC_TRANSFORM

    def test_transform_with_compute_tool_no_failure(self):
        from knowbase.runtime_v5.verifier.claim_segmenter import ClaimType
        claims = [
            _make_claim(
                "Performance improved 30 percent compared to v1",
                citations_raw=[{"raw": "[doc=d1]", "doc_id": "d1"}],
                claim_type=ClaimType.NUMERIC,
            ),
        ]
        # Tool compute_derived_metric cité
        failures = check_unsupported_numeric_transform(
            claims, cited_tool_names={"compute_derived_metric"},
        )
        assert failures == []


class TestMissingQualifier:
    def test_always_without_qualifier(self):
        claims = [
            _make_claim(
                "The procedure always succeeds",
                citations_raw=[{"raw": "[doc=d1]", "doc_id": "d1"}],
            ),
        ]
        failures = check_missing_qualifier(claims)
        assert len(failures) >= 1
        assert failures[0].reason == FailureReason.MISSING_QUALIFIER

    def test_always_with_qualifier_ok(self):
        claims = [
            _make_claim(
                "The procedure always succeeds under the standard contract",
                citations_raw=[{"raw": "[doc=d1]", "doc_id": "d1"}],
            ),
        ]
        failures = check_missing_qualifier(claims)
        assert failures == []


# ════════════════════════════════════════════════════════════════════════════
# GroundingVerifier integration (S7.6)
# ════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def evidence_map():
    return {
        "d1": "The recovery time is 4 hours in production.",
        "d2": "The standard procedure applies to all production systems.",
        "sec_1": "Step A is executed first.",
    }


class TestGroundingVerifier:
    def test_noop_verifier_accepts_all(self, evidence_map):
        gv = GroundingVerifier()  # default NoOpVerifier
        report = gv.verify(
            answer_text="Recovery time is 4 hours [doc=d1]. Standard applies [doc=d2].",
            evidence_by_citation=evidence_map,
        )
        assert report.outcome == VerificationOutcome.ACCEPTED
        assert report.n_claims() == 2

    def test_missing_evidence_triggers_retry(self, evidence_map):
        gv = GroundingVerifier()
        # Claim cite [doc=d_inexistent] qui n'est pas dans evidence_map
        report = gv.verify(
            answer_text="Recovery time is 4 hours [doc=d_unknown].",
            evidence_by_citation=evidence_map,
        )
        assert report.outcome == VerificationOutcome.RETRY_REQUESTED
        assert any(f.reason == FailureReason.MISSING_EVIDENCE for f in report.failures)
        assert report.has_retryable_failures()

    def test_contradicted_claim_marks_failure(self, evidence_map):
        backend = MockNLIBackend(
            default_score=0.05,  # bas → CONTRADICTED via threshold
        )
        gv = GroundingVerifier(backend=ScoreThresholdAdapter(
            backend, support_threshold=0.7, contradict_threshold=0.3,
        ))
        report = gv.verify(
            answer_text="Recovery time is 999 hours [doc=d1].",
            evidence_by_citation=evidence_map,
            answer_shape="factual",
        )
        assert report.outcome == VerificationOutcome.RETRY_REQUESTED  # citation_mismatch = retryable

    def test_no_claims_accepted(self, evidence_map):
        gv = GroundingVerifier()
        report = gv.verify(
            answer_text="OK.",
            evidence_by_citation=evidence_map,
        )
        # Trop court → 0 claims → ACCEPTED (no claims = no failure)
        assert report.outcome == VerificationOutcome.ACCEPTED

    def test_critical_failure_rejects(self, evidence_map):
        gv = GroundingVerifier()
        # Force unsupported_numeric_transform sans compute cited
        report = gv.verify(
            answer_text=(
                "Performance improved 30 percent compared to v1 baseline [doc=d1]."
            ),
            evidence_by_citation=evidence_map,
            answer_shape="quantitative",
            cited_tool_names=set(),  # pas de compute_derived_metric
        )
        assert report.outcome == VerificationOutcome.REJECTED
        assert any(f.reason == FailureReason.UNSUPPORTED_NUMERIC_TRANSFORM
                   for f in report.failures)

    def test_summary_compact(self, evidence_map):
        gv = GroundingVerifier()
        report = gv.verify(
            answer_text="Step A is first [doc=sec_1]. Procedure follows [doc=d2].",
            evidence_by_citation=evidence_map,
            answer_shape="factual",
        )
        s = report.summary()
        assert "outcome" in s
        assert "n_claims" in s
        assert "support_rate" in s
        assert "n_failures" in s


class TestThresholdInversionForUnanswerable:
    def test_unanswerable_high_score_flagged(self, evidence_map):
        """shape=unanswerable + score haut = bad (réponse alors que devrait abstain)."""
        backend = MockNLIBackend(default_score=0.95)  # haut
        gv = GroundingVerifier(backend=backend)
        report = gv.verify(
            answer_text="The answer is X [doc=d1].",
            evidence_by_citation=evidence_map,
            answer_shape="unanswerable",
        )
        # Score haut + inverted=True → claim treated as CONTRADICTED
        # → failure = citation_mismatch retryable
        assert any(
            r.decision == NLIDecision.CONTRADICTED
            for r in report.nli_results
        )
