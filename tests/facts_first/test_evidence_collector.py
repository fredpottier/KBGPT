"""
Tests CH-41.2 — EvidenceCollector (mocks ClaimRetriever + Neo4j driver).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from knowbase.facts_first.evidence_collector import (
    EvidenceBundle,
    EvidenceClaim,
    EvidenceCollector,
)


def _make_retriever_returning(hits: list):
    r = MagicMock()
    r.retrieve.return_value = hits
    return r


def _hit(claim_id, doc_id, text="some passage text long enough", score=0.9, pub_date=None):
    return SimpleNamespace(
        claim_id=claim_id, doc_id=doc_id, text=text,
        score=score, publication_date=pub_date,
    )


def _make_neo4j_driver(rows: list[dict]):
    """Mock du driver Neo4j qui retourne `rows` quand on appelle session.run().data()."""
    driver = MagicMock()
    session = MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    result = MagicMock()
    result.data.return_value = rows
    session.run.return_value = result
    driver.session.return_value = session
    return driver


def test_no_qdrant_hits_returns_unanswerable():
    retriever = _make_retriever_returning([])
    coll = EvidenceCollector(retriever=retriever, neo4j_driver=None)
    bundle = coll.collect("question whatever")
    assert bundle.answerability_hint == "unanswerable"
    assert len(bundle.claims) == 0
    assert bundle.diagnostic.get("reason") == "no_qdrant_hits"


def test_all_hits_below_min_score_unanswerable():
    retriever = _make_retriever_returning([
        _hit("c1", "doc1", score=0.05),
        _hit("c2", "doc2", score=0.10),
    ])
    coll = EvidenceCollector(retriever=retriever, min_score_keep=0.20)
    bundle = coll.collect("q")
    assert bundle.answerability_hint == "unanswerable"
    assert "all_hits_below_min_score" in bundle.diagnostic.get("reason", "")


def test_chunk_only_fallback_without_neo4j():
    retriever = _make_retriever_returning([
        _hit("c1", "doc1", text="chunk text long enough to keep", score=0.85),
        _hit("c2", "doc2", text="another chunk passage long enough", score=0.7),
    ])
    coll = EvidenceCollector(retriever=retriever, neo4j_driver=None)
    bundle = coll.collect("question")
    # 2 claims but answerability_hint=partial because count < 3
    assert bundle.answerability_hint == "partial"
    assert len(bundle.claims) == 2
    assert bundle.n_chunk_fallback == 2
    assert bundle.n_neo4j_enriched == 0
    for c in bundle.claims:
        assert c.enriched_from_neo4j is False
        assert c.is_valid()


def test_neo4j_enrichment_uses_verbatim_quote():
    retriever = _make_retriever_returning([
        _hit("claim_42", "doc1", text="raw passage text", score=0.85),
        _hit("claim_43", "doc1", text="raw passage 2 text", score=0.8),
        _hit("claim_44", "doc2", text="raw passage 3 text", score=0.75),
    ])
    rows = [
        {"claim_id": "claim_42", "verbatim_quote": "Verbatim quote forty-two long enough", "passage_text": None,
         "publication_date": "2021-05-20", "chunk_ids": ["ck_a"], "unit_ids": [], "language": "en",
         "passage_char_start": 0, "passage_char_end": 36},
        {"claim_id": "claim_43", "verbatim_quote": "Verbatim quote forty-three long enough", "passage_text": None,
         "publication_date": None, "chunk_ids": [], "unit_ids": [], "language": "en",
         "passage_char_start": 0, "passage_char_end": 38},
    ]
    driver = _make_neo4j_driver(rows)
    coll = EvidenceCollector(retriever=retriever, neo4j_driver=driver)
    bundle = coll.collect("q")

    assert len(bundle.claims) == 3
    assert bundle.n_neo4j_enriched == 2
    assert bundle.n_chunk_fallback == 1  # claim_44 not in Neo4j → chunk fallback
    enriched = [c for c in bundle.claims if c.enriched_from_neo4j]
    assert all(c.quote.startswith("Verbatim") for c in enriched)


def test_invalid_quote_rejected():
    """Quote trop courte → rejet."""
    retriever = _make_retriever_returning([
        _hit("c1", "doc1", text="short", score=0.85),  # 5 chars < MIN_QUOTE_CHARS(10)
        _hit("c2", "doc2", text="long enough passage to keep", score=0.8),
    ])
    coll = EvidenceCollector(retriever=retriever, neo4j_driver=None)
    bundle = coll.collect("q")
    assert bundle.n_rejected_invalid_quote == 1
    assert len(bundle.claims) == 1
    # 1 claim < 3 → partial
    assert bundle.answerability_hint == "partial"


def test_enough_evidence_gives_answerable():
    retriever = _make_retriever_returning([
        _hit(f"c{i}", "doc1", text=f"passage text long enough number {i}", score=0.8)
        for i in range(5)
    ])
    coll = EvidenceCollector(retriever=retriever, neo4j_driver=None)
    bundle = coll.collect("q")
    assert bundle.answerability_hint == "answerable"
    assert len(bundle.claims) == 5


def test_doc_ids_dedup():
    retriever = _make_retriever_returning([
        _hit("c1", "doc_A", score=0.9), _hit("c2", "doc_A", score=0.8),
        _hit("c3", "doc_B", score=0.7), _hit("c4", "doc_C", score=0.6),
    ])
    coll = EvidenceCollector(retriever=retriever, neo4j_driver=None)
    bundle = coll.collect("q")
    assert bundle.doc_ids() == ["doc_A", "doc_B", "doc_C"]


def test_retriever_exception_unanswerable():
    retriever = MagicMock()
    retriever.retrieve.side_effect = RuntimeError("qdrant down")
    coll = EvidenceCollector(retriever=retriever, neo4j_driver=None)
    bundle = coll.collect("q")
    assert bundle.answerability_hint == "unanswerable"
    assert "qdrant down" in bundle.diagnostic.get("retriever_error", "")


def test_neo4j_exception_silent_fallback_to_chunks():
    """Si Neo4j est down, on n'échoue pas — on retombe en chunk-only."""
    retriever = _make_retriever_returning([
        _hit("c1", "doc1", text="chunk passage long enough to keep", score=0.85),
        _hit("c2", "doc2", text="chunk passage 2 long enough to keep", score=0.8),
    ])
    driver = MagicMock()
    driver.session.side_effect = RuntimeError("neo4j down")
    coll = EvidenceCollector(retriever=retriever, neo4j_driver=driver)
    bundle = coll.collect("q")
    assert len(bundle.claims) == 2
    assert bundle.n_neo4j_enriched == 0
    assert bundle.n_chunk_fallback == 2
