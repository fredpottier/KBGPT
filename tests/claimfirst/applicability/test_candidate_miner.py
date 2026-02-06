# tests/claimfirst/applicability/test_candidate_miner.py
"""Tests pour CandidateMiner (Layer B)."""

import pytest

from knowbase.claimfirst.applicability.candidate_miner import CandidateMiner
from knowbase.claimfirst.applicability.models import (
    EvidenceUnit,
    MarkerCategory,
)


def _make_unit(text: str, p_idx: int = 0, s_idx: int = 0, page_no: int = None) -> EvidenceUnit:
    """Helper pour créer une EvidenceUnit de test."""
    return EvidenceUnit(
        unit_id=f"EU:{p_idx}:{s_idx}",
        text=text,
        passage_idx=p_idx,
        sentence_idx=s_idx,
        page_no=page_no,
    )


class TestCandidateMiner:
    """Tests pour le miner de candidats."""

    def setup_method(self):
        self.miner = CandidateMiner()

    def test_extract_year(self):
        """Extrait les années."""
        units = [_make_unit("This document covers features for 2023.")]
        profile = self.miner.mine(units, "doc1")
        years = profile.get_candidates_by_type("year")
        assert len(years) == 1
        assert years[0].raw_value == "2023"

    def test_filter_copyright_year(self):
        """Filtre les années dans un contexte copyright."""
        units = [_make_unit("Copyright © 2019 SAP SE. All rights reserved.")]
        profile = self.miner.mine(units, "doc1")
        years = profile.get_candidates_by_type("year")
        assert len(years) == 0

    def test_extract_version(self):
        """Extrait les versions numériques."""
        units = [_make_unit("Compatible with 3.2.1 of the platform.")]
        profile = self.miner.mine(units, "doc1")
        versions = profile.get_candidates_by_type("version")
        assert any(v.raw_value == "3.2.1" for v in versions)

    def test_extract_named_version(self):
        """Extrait les named versions."""
        units = [_make_unit("This applies to Release 2023 FPS01.")]
        profile = self.miner.mine(units, "doc1")
        named = profile.get_candidates_by_type("named_version")
        assert len(named) >= 1
        assert any("Release 2023" in nv.raw_value for nv in named)

    def test_frequency_counting(self):
        """Compte correctement les fréquences."""
        units = [
            _make_unit("The 2023 update introduces new features.", p_idx=0, s_idx=0),
            _make_unit("The 2023 release includes improvements.", p_idx=1, s_idx=0),
            _make_unit("See the 2023 documentation for details.", p_idx=2, s_idx=0),
        ]
        profile = self.miner.mine(units, "doc1")
        years = profile.get_candidates_by_type("year")
        year_2023 = next((y for y in years if y.raw_value == "2023"), None)
        assert year_2023 is not None
        assert year_2023.frequency == 3

    def test_in_title_detection(self):
        """Détecte les valeurs présentes dans le titre."""
        units = [_make_unit("This document covers 2023 features.")]
        profile = self.miner.mine(units, "doc1", title="Product Guide 2023")
        years = profile.get_candidates_by_type("year")
        year_2023 = next((y for y in years if y.raw_value == "2023"), None)
        assert year_2023 is not None
        assert year_2023.in_title is True

    def test_in_header_zone(self):
        """Détecte les valeurs dans la zone header (10% premiers passages)."""
        units = [
            _make_unit("Published in 2023.", p_idx=0, s_idx=0),
            _make_unit("Some content.", p_idx=50, s_idx=0),
        ]
        profile = self.miner.mine(units, "doc1")
        years = profile.get_candidates_by_type("year")
        year_2023 = next((y for y in years if y.raw_value == "2023"), None)
        assert year_2023 is not None
        assert year_2023.in_header_zone is True

    def test_cooccurrence_with_subject(self):
        """Détecte la co-occurrence avec le primary_subject."""
        units = [_make_unit("S/4HANA 2023 includes new features.")]
        profile = self.miner.mine(units, "doc1", primary_subject="S/4HANA")
        years = profile.get_candidates_by_type("year")
        year_2023 = next((y for y in years if y.raw_value == "2023"), None)
        assert year_2023 is not None
        assert year_2023.cooccurs_with_subject is True

    def test_marker_detection_conditionality(self):
        """Détecte les markers CONDITIONALITY."""
        units = [_make_unit("If the system is configured for HA, then this applies.")]
        profile = self.miner.mine(units, "doc1")
        assert MarkerCategory.CONDITIONALITY.value in profile.markers_by_category

    def test_marker_detection_scope(self):
        """Détecte les markers SCOPE."""
        units = [_make_unit("This section applies to on-premise deployments.")]
        profile = self.miner.mine(units, "doc1")
        assert MarkerCategory.SCOPE.value in profile.markers_by_category

    def test_marker_detection_reference(self):
        """Détecte les markers REFERENCE."""
        units = [_make_unit("Based on version 3.0 of the specification.")]
        profile = self.miner.mine(units, "doc1")
        assert MarkerCategory.REFERENCE.value in profile.markers_by_category

    def test_context_snippets(self):
        """Extrait les snippets de contexte."""
        units = [_make_unit("The document covers 2023 features and updates.")]
        profile = self.miner.mine(units, "doc1")
        years = profile.get_candidates_by_type("year")
        year_2023 = next((y for y in years if y.raw_value == "2023"), None)
        assert year_2023 is not None
        assert len(year_2023.context_snippets) >= 1

    def test_date_iso_extraction(self):
        """Extrait les dates ISO."""
        units = [_make_unit("Effective from 2024-01-15 onwards.")]
        profile = self.miner.mine(units, "doc1")
        dates = profile.get_candidates_by_type("date")
        assert any(d.raw_value == "2024-01-15" for d in dates)

    def test_named_version_rejects_false_positives(self):
        """Rejette les faux positifs comme 'version of', 'release notes'."""
        units = [
            _make_unit("This is a version of the product documentation.", p_idx=0, s_idx=0),
            _make_unit("See the release notes for details.", p_idx=1, s_idx=0),
            _make_unit("The version for SAP customers.", p_idx=2, s_idx=0),
        ]
        profile = self.miner.mine(units, "doc1")
        named = profile.get_candidates_by_type("named_version")
        # Aucun faux positif — les tokens "of", "notes", "for" n'ont pas de chiffre
        assert len(named) == 0

    def test_named_version_accepts_valid_versions(self):
        """Accepte les versions nommées valides (avec chiffres)."""
        units = [
            _make_unit("This applies to Release 1809.", p_idx=0, s_idx=0),
            _make_unit("Compatible with Version 2023.", p_idx=1, s_idx=0),
            _make_unit("Requires FPS 01 or later.", p_idx=2, s_idx=0),
            _make_unit("Available since SP 12.", p_idx=3, s_idx=0),
        ]
        profile = self.miner.mine(units, "doc1")
        named = profile.get_candidates_by_type("named_version")
        values = {nv.raw_value for nv in named}
        assert "Release 1809" in values
        assert "Version 2023" in values
        assert "FPS 01" in values
        assert "SP 12" in values

    def test_empty_units(self):
        """Gère une liste vide d'unités."""
        profile = self.miner.mine([], "doc1")
        assert profile.total_units == 0
        assert len(profile.value_candidates) == 0
        assert len(profile.markers) == 0
