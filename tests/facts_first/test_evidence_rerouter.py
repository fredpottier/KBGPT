"""
Tests CH-42.3 — EvidenceRerouter (déterministe, mocks Neo4j).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from knowbase.facts_first.evidence_collector import EvidenceBundle, EvidenceClaim
from knowbase.facts_first.evidence_rerouter import EvidenceRerouter, RerouterDecision
from knowbase.facts_first.question_analyzer import AnalyzerResult, RoutingDecision


def _analyzer(ptype: str, conf: float) -> AnalyzerResult:
    return AnalyzerResult(
        primary_type=ptype, primary_confidence=conf,
        secondary_type=None, secondary_confidence=None,
        language="en", rationale="test",
        routing=RoutingDecision.SINGLE if conf >= 0.7 else RoutingDecision.COMBINED,
    )


def _bundle(claims_data):
    """claims_data = list of (claim_id, doc_id, publication_date)."""
    claims = [
        EvidenceClaim(
            claim_id=cid, doc_id=doc, chunk_id=None, page_no=None,
            quote=f"quote for {cid} long enough", score=0.85,
            publication_date=date,
        )
        for cid, doc, date in claims_data
    ]
    return EvidenceBundle(question="q", claims=claims)


def _mock_driver(lifecycle_rows=None, logical_rows=None):
    """Mock Neo4j driver returning custom rows for the 2 queries."""
    driver = MagicMock()
    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    call_count = {"n": 0}

    def run_side_effect(query, **kwargs):
        result = MagicMock()
        call_count["n"] += 1
        # 1st call = LIFECYCLE, 2nd = LOGICAL
        if "LIFECYCLE_RELATION" in query:
            result.data.return_value = lifecycle_rows or []
        else:
            result.data.return_value = logical_rows or []
        return result

    session.run.side_effect = run_side_effect
    driver.session.return_value = session
    return driver


def test_high_confidence_no_override():
    """Analyzer ≥ 0.7 sur type structuré → pas de promotion."""
    rerouter = EvidenceRerouter(neo4j_driver=None)
    bundle = _bundle([("c1", "doc1", "2021-05-20")])
    decision = rerouter.reroute(_analyzer("list", 0.85), bundle)
    assert decision.was_promoted is False
    assert decision.final_type == "list"
    assert "high_confidence" in decision.rationale


def test_no_evidence_no_promotion():
    rerouter = EvidenceRerouter(neo4j_driver=None)
    bundle = EvidenceBundle(question="q", claims=[])
    decision = rerouter.reroute(_analyzer("factual", 0.5), bundle)
    assert decision.was_promoted is False
    assert "no_evidence" in decision.rationale


def test_lifecycle_signal_promotes_factual_to_temporal():
    """LIFECYCLE_RELATION sur seed claims → promotion factual → temporal."""
    driver = _mock_driver(
        lifecycle_rows=[{"rel_type": "SUPERSEDES", "n": 3}],
        logical_rows=[],
    )
    rerouter = EvidenceRerouter(neo4j_driver=driver)
    bundle = _bundle([("c1", "doc1", "2021-05-20"), ("c2", "doc2", "2009-05-05")])
    decision = rerouter.reroute(_analyzer("factual", 0.6), bundle)
    assert decision.was_promoted is True
    assert decision.promoted_type == "temporal"
    assert "LIFECYCLE_RELATION" in decision.rationale


def test_logical_contradicts_promotes_factual_to_comparison():
    """LOGICAL_RELATION CONTRADICTS sur seed claims → promotion factual → comparison."""
    driver = _mock_driver(
        lifecycle_rows=[],
        logical_rows=[{"rel_type": "CONTRADICTS", "n": 2}, {"rel_type": "REAFFIRMS", "n": 1}],
    )
    rerouter = EvidenceRerouter(neo4j_driver=driver)
    bundle = _bundle([("c1", "doc1", "2021-05-20")])
    decision = rerouter.reroute(_analyzer("factual", 0.6), bundle)
    assert decision.was_promoted is True
    assert decision.promoted_type == "comparison"


def test_multi_date_multi_doc_promotes_to_temporal():
    """≥2 dates distinctes × ≥2 docs → signal temporal sans Neo4j."""
    rerouter = EvidenceRerouter(neo4j_driver=None)
    bundle = _bundle([
        ("c1", "doc1", "2009-05-05"),
        ("c2", "doc2", "2021-05-20"),
        ("c3", "doc3", "2024-09-30"),
    ])
    decision = rerouter.reroute(_analyzer("factual", 0.6), bundle)
    assert decision.was_promoted is True
    assert decision.promoted_type == "temporal"


def test_list_never_demoted():
    """list classé par analyzer (même conf 0.5) ne doit jamais être demoted."""
    driver = _mock_driver(
        lifecycle_rows=[{"rel_type": "SUPERSEDES", "n": 3}],
        logical_rows=[],
    )
    rerouter = EvidenceRerouter(neo4j_driver=driver)
    bundle = _bundle([("c1", "doc1", "2021-05-20")])
    decision = rerouter.reroute(_analyzer("list", 0.55), bundle)
    assert decision.was_promoted is False  # list reste list
    assert "list_kept_no_demotion" in decision.rationale


def test_no_signals_no_promotion():
    """Aucun signal KG → analyzer reste."""
    driver = _mock_driver(lifecycle_rows=[], logical_rows=[])
    rerouter = EvidenceRerouter(neo4j_driver=driver)
    bundle = _bundle([("c1", "doc1", "2021-05-20")])
    decision = rerouter.reroute(_analyzer("factual", 0.6), bundle)
    assert decision.was_promoted is False
    assert "no_kg_signals" in decision.rationale


def test_neo4j_error_no_promotion():
    """Si Neo4j down, on ne promeut pas (conservateur)."""
    driver = MagicMock()
    driver.session.side_effect = RuntimeError("neo4j down")
    rerouter = EvidenceRerouter(neo4j_driver=driver)
    bundle = _bundle([("c1", "doc1", "2021-05-20")])
    decision = rerouter.reroute(_analyzer("factual", 0.6), bundle)
    # Peut promouvoir si signal multi-date détecté côté evidence (sans Neo4j),
    # mais pas via lifecycle/logical → ici 1 doc 1 date = pas de promotion
    assert decision.was_promoted is False


def test_signal_match_analyzer_no_promotion():
    """Si analyzer dit déjà 'temporal' avec confiance moyenne, signal lifecycle ne promeut pas vers lui-même."""
    driver = _mock_driver(
        lifecycle_rows=[{"rel_type": "SUPERSEDES", "n": 3}],
        logical_rows=[],
    )
    rerouter = EvidenceRerouter(neo4j_driver=driver)
    bundle = _bundle([("c1", "doc1", "2021-05-20")])
    decision = rerouter.reroute(_analyzer("temporal", 0.6), bundle)
    assert decision.was_promoted is False
    assert "signals_match_analyzer" in decision.rationale


def test_to_dict_serialization():
    rerouter = EvidenceRerouter(neo4j_driver=None)
    bundle = _bundle([("c1", "doc1", "2021-05-20")])
    decision = rerouter.reroute(_analyzer("list", 0.85), bundle)
    d = decision.to_dict()
    assert d["original_type"] == "list"
    assert d["was_promoted"] is False
    assert d["final_type"] == "list"
