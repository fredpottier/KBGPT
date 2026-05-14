"""Tests ClaimSegmenter (CH-52.8.1 / S7.1)."""
from __future__ import annotations

import pytest

from knowbase.runtime_v5.verifier.claim_segmenter import (
    Claim,
    ClaimSegmenter,
    ClaimType,
    CitationRefExtracted,
    _classify_claim,
    _extract_citations,
)


@pytest.fixture
def segmenter():
    return ClaimSegmenter()


# ─── Basic segmentation ──────────────────────────────────────────────────────


class TestSegmentation:
    def test_single_claim(self, segmenter):
        claims = segmenter.segment("The procedure follows step A.")
        assert len(claims) == 1
        assert "step A" in claims[0].text

    def test_multiple_sentences(self, segmenter):
        text = (
            "The procedure follows step A. "
            "Then we apply step B. "
            "Finally validation happens in step C."
        )
        claims = segmenter.segment(text)
        assert len(claims) == 3

    def test_empty_input(self, segmenter):
        assert segmenter.segment("") == []
        assert segmenter.segment("   ") == []

    def test_short_sentence_filtered(self, segmenter):
        claims = segmenter.segment("OK. Yes. The procedure follows the standard.")
        # "OK" et "Yes" trop courts, seul le 3e claim retenu
        assert len(claims) == 1
        assert "standard" in claims[0].text

    def test_max_claims_cap(self):
        seg = ClaimSegmenter(max_claims=2)
        text = "Claim one is here. Claim two is also here. Claim three is too. Claim four too."
        claims = seg.segment(text)
        assert len(claims) == 2

    def test_question_mark_split(self, segmenter):
        text = "What is X? It is the answer. What about Y? It is also defined."
        claims = segmenter.segment(text)
        assert len(claims) >= 2


# ─── Citations extraction ────────────────────────────────────────────────────


class TestCitations:
    def test_doc_citation(self, segmenter):
        text = "The SLA is 99.9% [doc=003_SAP_Service_Description]."
        claims = segmenter.segment(text)
        assert claims[0].has_citation is True
        assert claims[0].citations[0].doc_id == "003_SAP_Service_Description"

    def test_doc_with_section(self, segmenter):
        text = "Step is found [doc=doc_x section=sec_1]."
        claims = segmenter.segment(text)
        assert claims[0].citations[0].doc_id == "doc_x"
        assert claims[0].citations[0].section_id == "sec_1"

    def test_source_index(self, segmenter):
        text = "Per the contract, the timeline is 4 weeks [Source 1]."
        claims = segmenter.segment(text)
        assert claims[0].citations[0].source_index == 1

    def test_no_citation(self, segmenter):
        text = "The procedure follows standard practice."
        claims = segmenter.segment(text)
        assert claims[0].has_citation is False
        assert claims[0].citations == []

    def test_multiple_citations_in_one_claim(self, segmenter):
        text = "The total includes A [doc=d1] and B [doc=d2]."
        claims = segmenter.segment(text)
        assert len(claims[0].citations) == 2


# ─── Classification ──────────────────────────────────────────────────────────


class TestClassification:
    def test_numeric(self):
        assert _classify_claim("The SLA is 99.9% uptime") == ClaimType.NUMERIC
        assert _classify_claim("Storage is 500 GB max") == ClaimType.NUMERIC
        assert _classify_claim("RTO is 4 hours") == ClaimType.NUMERIC

    def test_temporal(self):
        assert _classify_claim("Released in 2023") == ClaimType.TEMPORAL
        assert _classify_claim("Active since January") == ClaimType.TEMPORAL
        assert _classify_claim("Depuis 2022") == ClaimType.TEMPORAL

    def test_comparative(self):
        assert _classify_claim("X is faster than Y") == ClaimType.COMPARATIVE
        assert _classify_claim("Higher than baseline") == ClaimType.COMPARATIVE
        assert _classify_claim("X versus Y comparison") == ClaimType.COMPARATIVE

    def test_opinion(self):
        assert _classify_claim("You should consider option B") == ClaimType.OPINION
        assert _classify_claim("This may improve performance") == ClaimType.OPINION

    def test_factual_default(self):
        assert _classify_claim("The procedure follows standard practice") == ClaimType.FACTUAL


# ─── Meta / skip filter ──────────────────────────────────────────────────────


class TestMetaSkip:
    def test_meta_starter_skipped(self, segmenter):
        text = "Based on the document. The procedure follows the standard practice."
        claims = segmenter.segment(text)
        # "Based on the document" est short → skipped (meta + len)
        # Le 2nd claim retenu
        assert len(claims) == 1
        assert "procedure" in claims[0].text

    def test_meta_disabled(self):
        seg = ClaimSegmenter(skip_meta=False, min_claim_chars=3)
        text = "Based on doc. Standard practice."
        claims = seg.segment(text)
        # 2 claims maintenant (meta non skippé, min_claim_chars=3)
        assert len(claims) == 2


# ─── Span tracking ──────────────────────────────────────────────────────────


class TestSpans:
    def test_span_offsets(self, segmenter):
        text = "First claim is here. Second claim too."
        claims = segmenter.segment(text)
        # First claim début à 0
        assert claims[0].span_start == 0
        # Second claim après le premier
        assert claims[1].span_start > claims[0].span_end - 1


# ─── Stats ───────────────────────────────────────────────────────────────────


class TestStats:
    def test_stats_basic(self, segmenter):
        text = (
            "Cost is 500 EUR [doc=d1]. "
            "Released in 2023 [doc=d2]. "
            "Standard procedure applies."
        )
        claims = segmenter.segment(text)
        stats = segmenter.stats(claims)
        assert stats["n_claims"] == 3
        assert stats["by_type"]["numeric"] >= 1
        assert stats["by_type"]["temporal"] >= 1
        # 2/3 ont une citation → ~0.667
        assert 0.6 < stats["citation_rate"] < 0.7

    def test_stats_empty(self, segmenter):
        stats = segmenter.stats([])
        assert stats["n_claims"] == 0
        assert stats["citation_rate"] == 0.0


# ─── Multilingual basic ──────────────────────────────────────────────────────


class TestMultilingual:
    def test_french(self, segmenter):
        text = "La procédure suit l'étape A. Puis l'étape B s'applique."
        claims = segmenter.segment(text)
        assert len(claims) == 2

    def test_german(self, segmenter):
        text = "Das Verfahren folgt Schritt A. Dann gilt Schritt B."
        claims = segmenter.segment(text)
        assert len(claims) == 2

    def test_temporal_french(self):
        assert _classify_claim("Disponible depuis 2022") == ClaimType.TEMPORAL


# ─── Pydantic validation ─────────────────────────────────────────────────────


class TestPydanticValidation:
    def test_claim_extra_field_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            Claim(text="x", garbage="oops")

    def test_citation_ref_extra_rejected(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            CitationRefExtracted(raw="x", oops="garbage")
