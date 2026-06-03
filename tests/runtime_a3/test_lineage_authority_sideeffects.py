"""Tests des agrégations Synthesize pour les side-effects #443 (lignée) et #440
(contradictions inter-autorités). Logique pure, sans Neo4j ni LLM.
"""

from knowbase.runtime_a3.schemas import (
    AuthorityConflictSummary,
    DocLineageSummary,
    ExecuteOutput,
    ToolResult,
)
from knowbase.runtime_a3.synthesize import (
    _aggregate_authority_conflicts,
    _aggregate_doc_lineages,
)


def _exec(*results: ToolResult) -> ExecuteOutput:
    return ExecuteOutput(results=list(results))


def _tool(idx=0, **kw) -> ToolResult:
    return ToolResult(sub_goal_idx=idx, tool="kg_claims", **kw)


def test_aggregate_doc_lineages_dedup_and_shape():
    dl = DocLineageSummary(
        doc_id="AC_21-25B_x",
        reg_key="AC 21-25B",
        in_force_reg_key="AC 21-25B",
        is_in_force=True,
        superseded=["AC 21-25A", "AC 21-25"],
        evidence=["This AC cancels AC 21-25A…"],
    )
    # même doc_id présent dans deux ToolResult -> dédupliqué
    out = _aggregate_doc_lineages(_exec(_tool(doc_lineages=[dl]), _tool(idx=1, doc_lineages=[dl])))
    assert len(out) == 1
    assert out[0]["document"] == "AC 21-25B"
    assert out[0]["in_force"] == "AC 21-25B"
    assert out[0]["supersedes"] == ["AC 21-25A", "AC 21-25"]


def test_aggregate_authority_conflicts_dedup_and_shape():
    ac = AuthorityConflictSummary(
        subject="floor deceleration",
        authority_a="FAA",
        doc_a="AC_25-17A_x",
        text_a="peak floor deceleration in not more than 0.09 sec",
        authority_b="EASA",
        doc_b="NPA_2013-20_x",
        text_b="peak floor deceleration in not more than 0.08 sec",
        confidence=0.9,
    )
    out = _aggregate_authority_conflicts(_exec(_tool(authority_conflicts=[ac, ac])))
    assert len(out) == 1
    row = out[0]
    assert row["authority_a"] == "FAA" and row["authority_b"] == "EASA"
    assert row["doc_a"] == "AC_25-17A_x"
    assert "0.09" in row["text_a"] and "0.08" in row["text_b"]


def test_aggregations_empty_when_absent():
    assert _aggregate_doc_lineages(_exec(_tool())) == []
    assert _aggregate_authority_conflicts(_exec(_tool())) == []
