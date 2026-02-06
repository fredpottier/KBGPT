# tests/claimfirst/applicability/test_evidence_unit_segmenter.py
"""Tests pour EvidenceUnitSegmenter (Layer A)."""

import pytest

from knowbase.claimfirst.applicability.evidence_unit_segmenter import (
    EvidenceUnitSegmenter,
)
from knowbase.claimfirst.models.passage import Passage


def _make_passage(text: str, idx: int = 0, page_no: int = None, section_title: str = None) -> Passage:
    """Helper pour créer un Passage de test."""
    return Passage(
        passage_id=f"test:{idx}",
        tenant_id="test",
        doc_id="test_doc",
        text=text,
        page_no=page_no,
        reading_order_index=idx,
        section_title=section_title,
    )


class TestEvidenceUnitSegmenter:
    """Tests pour le segmenteur d'unités d'evidence."""

    def setup_method(self):
        self.segmenter = EvidenceUnitSegmenter()

    def test_basic_sentence_split(self):
        """Découpe basique en phrases."""
        passage = _make_passage(
            "First sentence here. Second sentence here. Third one."
        )
        units = self.segmenter.segment([passage])
        assert len(units) == 3
        assert units[0].text == "First sentence here."
        assert units[1].text == "Second sentence here."
        assert units[2].text == "Third one."

    def test_stable_ids(self):
        """Les IDs sont stables et déterministes."""
        passage = _make_passage("Sentence one. Sentence two.", idx=5)
        units = self.segmenter.segment([passage])
        assert units[0].unit_id == "EU:0:0"
        assert units[1].unit_id == "EU:0:1"

        # Re-segmenter donne les mêmes IDs
        units2 = self.segmenter.segment([passage])
        assert units[0].unit_id == units2[0].unit_id
        assert units[1].unit_id == units2[1].unit_id

    def test_multiple_passages(self):
        """Les IDs reflètent l'index du passage."""
        passages = [
            _make_passage("First passage sentence.", idx=0),
            _make_passage("Second passage sentence.", idx=1),
        ]
        units = self.segmenter.segment(passages)
        assert len(units) == 2
        assert units[0].unit_id == "EU:0:0"
        assert units[1].unit_id == "EU:1:0"

    def test_abbreviations_protected(self):
        """Les abréviations ne causent pas de split."""
        passage = _make_passage(
            "See Fig. 1 for details. The result is clear."
        )
        units = self.segmenter.segment([passage])
        # "Fig." ne doit pas splitter
        assert len(units) == 2

    def test_version_numbers_protected(self):
        """Les numéros de version ne causent pas de split."""
        passage = _make_passage(
            "This applies to version 2.1.3 of the software. Next sentence."
        )
        units = self.segmenter.segment([passage])
        assert len(units) == 2
        assert "2.1.3" in units[0].text

    def test_short_lines_preserved(self):
        """Les lignes courtes type 'Version 2023' sont conservées."""
        passage = _make_passage("Version 2023")
        units = self.segmenter.segment([passage])
        assert len(units) == 1
        assert units[0].text == "Version 2023"

    def test_very_short_lines_filtered(self):
        """Les lignes trop courtes (<5 chars) sont filtrées."""
        passage = _make_passage("Hi")
        units = self.segmenter.segment([passage])
        assert len(units) == 0

    def test_empty_passage_skipped(self):
        """Les passages vides sont ignorés."""
        passages = [
            _make_passage("", idx=0),
            _make_passage("Real content here.", idx=1),
        ]
        units = self.segmenter.segment(passages)
        assert len(units) == 1
        assert units[0].passage_idx == 1

    def test_long_sentence_split(self):
        """Les phrases > 500 chars sont découpées."""
        long_text = "; ".join([f"clause number {i}" for i in range(50)])
        passage = _make_passage(long_text)
        units = self.segmenter.segment([passage])
        # Doit avoir été découpé
        assert len(units) >= 2
        for unit in units:
            assert len(unit.text) <= 600  # Tolérance

    def test_page_no_propagated(self):
        """page_no est propagé depuis le passage parent."""
        passage = _make_passage("Some text here.", page_no=42)
        units = self.segmenter.segment([passage])
        assert units[0].page_no == 42

    def test_section_title_propagated(self):
        """section_title est propagé depuis le passage parent."""
        passage = _make_passage("Some text here.", section_title="Architecture")
        units = self.segmenter.segment([passage])
        assert units[0].section_title == "Architecture"

    def test_exclamation_and_question_marks(self):
        """! et ? sont toujours des fins de phrase."""
        passage = _make_passage("Is this correct? Yes it is! Very good.")
        units = self.segmenter.segment([passage])
        assert len(units) == 3
