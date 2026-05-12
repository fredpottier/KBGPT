"""
Tests SelfCorrector transverse (Couche B).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from knowbase.facts_first.list_verifier import (
    SEVERITY_ERROR, SEVERITY_INFO, SEVERITY_WARNING,
    VerifierIssue, VerifierReport,
)
from knowbase.facts_first.self_corrector import (
    SelfCorrector,
    ACTIONABLE_ERROR_CODES,
    ACTIONABLE_WARNING_CODES,
)


def _report_with(*issues):
    r = VerifierReport(passed=all(i.severity != SEVERITY_ERROR for i in issues))
    for i in issues:
        r.add(i)
    return r


def test_no_issues_no_retry():
    rep = VerifierReport(passed=True)
    decision = SelfCorrector().decide(rep)
    assert not decision.should_retry


def test_actionable_error_triggers_retry():
    rep = _report_with(
        VerifierIssue("item.duplicate_id", SEVERITY_ERROR, "duplicate I1")
    )
    decision = SelfCorrector().decide(rep)
    assert decision.should_retry
    assert "item.duplicate_id" in decision.actionable_codes
    assert "Errors that MUST be fixed" in decision.feedback_message


def test_non_actionable_error_no_retry():
    rep = _report_with(
        VerifierIssue("schema.common.missing_field", SEVERITY_ERROR, "missing X")
    )
    decision = SelfCorrector().decide(rep)
    # schema errors not actionable by retry → no retry
    assert not decision.should_retry


def test_actionable_warning_triggers_retry_when_enabled():
    rep = _report_with(
        VerifierIssue("composer.items.uncited", SEVERITY_WARNING, "3 uncited")
    )
    decision = SelfCorrector(retry_on_actionable_warnings=True).decide(rep)
    assert decision.should_retry


def test_actionable_warning_no_retry_when_disabled():
    rep = _report_with(
        VerifierIssue("composer.items.uncited", SEVERITY_WARNING, "3 uncited")
    )
    decision = SelfCorrector(retry_on_actionable_warnings=False).decide(rep)
    assert not decision.should_retry


def test_select_better_retry_passes_initial_failed():
    r1 = _report_with(VerifierIssue("item.duplicate_id", SEVERITY_ERROR, "dup"))
    r2 = VerifierReport(passed=True)
    res1 = MagicMock(); res2 = MagicMock()
    sel, rep, reason = SelfCorrector.select_better(res1, res2, r1, r2)
    assert sel is res2
    assert reason == "retry_passed_initial_failed"


def test_select_better_initial_better_when_retry_introduces_errors():
    r1 = _report_with(
        VerifierIssue("composer.items.uncited", SEVERITY_WARNING, "1 uncited"),
    )
    # r1 passed (no errors) ; r2 introduces an error
    r2 = _report_with(
        VerifierIssue("item.duplicate_id", SEVERITY_ERROR, "dup"),
    )
    res1 = MagicMock(); res2 = MagicMock()
    sel, rep, reason = SelfCorrector.select_better(res1, res2, r1, r2)
    assert sel is res1
    assert reason == "initial_passed_retry_failed_rollback"


def test_select_better_more_items_breaks_tie():
    r1 = VerifierReport(passed=True)
    r2 = VerifierReport(passed=True)
    res1 = MagicMock()
    res1.facts_first_json = {"list_specific": {"items": [{"item_id": "I1"}]}}
    res2 = MagicMock()
    res2.facts_first_json = {"list_specific": {"items": [{"item_id": "I1"}, {"item_id": "I2"}]}}
    sel, rep, reason = SelfCorrector.select_better(res1, res2, r1, r2)
    assert sel is res2
    assert reason == "retry_more_items_same_errors"


def test_count_items_factual():
    res = MagicMock()
    res.facts_first_json = {"factual_specific": {"facts": [{"fact_id": "F1"}, {"fact_id": "F2"}]}}
    assert SelfCorrector._count_items(res) == 2


def test_count_items_empty():
    res = MagicMock()
    res.facts_first_json = {}
    assert SelfCorrector._count_items(res) == 0
