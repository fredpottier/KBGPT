"""
Tests P1.4b-4 / Q17 — Claim.get_source_citation() + round-trip Neo4j des champs citation.
"""

from knowbase.claimfirst.models.claim import Claim, ClaimType


def _claim(**kw):
    base = dict(
        claim_id="claim_x", tenant_id="default", doc_id="doc1",
        text="SAP HANA supports in-memory processing.",
        claim_type=ClaimType.FACTUAL,
        verbatim_quote="SAP HANA supports in-memory processing.",
        passage_id="doc1:p1",
    )
    base.update(kw)
    return Claim(**base)


def test_get_source_citation_full():
    c = _claim(page_no=9, passage_char_start=0, passage_char_end=132)
    cit = c.get_source_citation()
    assert cit["doc_id"] == "doc1"
    assert cit["page"] == 9
    assert cit["passage_char_range"] == [0, 132]
    assert cit["verbatim"] == "SAP HANA supports in-memory processing."
    assert cit["passage_id"] == "doc1:p1"


def test_get_source_citation_without_page():
    c = _claim()
    cit = c.get_source_citation()
    assert cit["page"] is None
    assert cit["passage_char_range"] is None
    assert cit["doc_id"] == "doc1" and cit["verbatim"]


def test_citation_fields_roundtrip_neo4j():
    c = _claim(page_no=5, passage_char_start=10, passage_char_end=200)
    props = c.to_neo4j_properties()
    assert props["page_no"] == 5
    assert props["passage_char_start"] == 10
    assert props["passage_char_end"] == 200
    # round-trip : from_neo4j_record doit restaurer les champs
    props.setdefault("created_at", c.created_at.isoformat())
    restored = Claim.from_neo4j_record(props)
    assert restored.page_no == 5
    assert restored.get_source_citation()["passage_char_range"] == [10, 200]


def test_citation_fields_absent_not_serialized():
    c = _claim()  # pas de page_no
    props = c.to_neo4j_properties()
    assert "page_no" not in props
    assert "passage_char_start" not in props
