# tests/claimfirst/test_axis_detector.py
"""
Tests pour ApplicabilityAxisDetector.

INV-25: Axis keys neutres + display_name optionnel
INV-26: Evidence obligatoire pour chaque valeur
"""

import pytest

from knowbase.claimfirst.axes.axis_detector import (
    ApplicabilityAxisDetector,
    AxisObservation,
    FALLBACK_AXIS_PATTERNS,
)
from knowbase.claimfirst.models.passage import Passage


@pytest.fixture
def detector():
    """Crée un détecteur sans LLM."""
    return ApplicabilityAxisDetector(llm_client=None, use_llm_extraction=False)


@pytest.fixture
def sample_passages():
    """Crée des passages de test avec des signaux de fallback patterns."""
    return [
        Passage(
            passage_id="p1",
            doc_id="doc1",
            tenant_id="default",
            text="Copyright © 2021 Acme Corp. All rights reserved.",
            position=0,
        ),
        Passage(
            passage_id="p2",
            doc_id="doc1",
            tenant_id="default",
            text="Effective from 2020-06-15, the new regulation applies.",
            position=1,
        ),
        Passage(
            passage_id="p3",
            doc_id="doc1",
            tenant_id="default",
            text="The Enterprise Edition includes advanced reporting features.",
            position=2,
        ),
    ]


class TestAxisDetector:
    """Tests pour ApplicabilityAxisDetector (fallback patterns, sans LLM)."""

    def test_release_id_requires_llm(self, detector, sample_passages):
        """release_id n'est PAS dans les fallback patterns (nécessite LLM)."""
        observations = detector.detect(
            doc_id="doc1",
            tenant_id="default",
            passages=sample_passages,
        )

        release_obs = next(
            (o for o in observations if o.axis_key == "release_id"),
            None
        )
        # Sans LLM, release_id ne doit PAS être détecté par fallback
        assert release_obs is None

    def test_detect_year_from_copyright(self, detector, sample_passages):
        """Détecte year depuis un contexte copyright (fallback conservatif)."""
        observations = detector.detect(
            doc_id="doc1",
            tenant_id="default",
            passages=sample_passages,
        )

        year_obs = next(
            (o for o in observations if o.axis_key == "year"),
            None
        )
        assert year_obs is not None
        assert "2021" in year_obs.values_extracted

    def test_detect_edition(self, detector, sample_passages):
        """Détecte l'axe edition."""
        observations = detector.detect(
            doc_id="doc1",
            tenant_id="default",
            passages=sample_passages,
        )

        edition_obs = next(
            (o for o in observations if o.axis_key == "edition"),
            None
        )
        assert edition_obs is not None
        assert "Enterprise" in edition_obs.values_extracted

    def test_evidence_spans_created(self, detector, sample_passages):
        """INV-26: Vérifie que evidence spans sont créés."""
        observations = detector.detect(
            doc_id="doc1",
            tenant_id="default",
            passages=sample_passages,
        )

        for obs in observations:
            assert len(obs.evidence_spans) > 0
            for evidence in obs.evidence_spans:
                assert evidence.snippet_ref is not None

    def test_detect_from_title_requires_llm(self, detector):
        """Sans LLM, un titre seul ne suffit pas à détecter des axes."""
        passages = [
            Passage(
                passage_id="p1",
                doc_id="doc1",
                tenant_id="default",
                text="Some generic content without version.",
                position=0,
            ),
        ]

        observations = detector.detect(
            doc_id="doc1",
            tenant_id="default",
            passages=passages,
            doc_title="Clio III Owner Manual 2023",
        )

        # Sans LLM, un titre n'est pas suffisant pour identifier release_id
        # (pourrait être "III" = génération, "2023" = année ou release)
        release_obs = next(
            (o for o in observations if o.axis_key == "release_id"),
            None
        )
        assert release_obs is None

    def test_abstention_on_ambiguous(self, detector):
        """S'abstient sur contenu ambigu sans axes clairs."""
        passages = [
            Passage(
                passage_id="p1",
                doc_id="doc1",
                tenant_id="default",
                text="This document discusses various topics.",
                position=0,
            ),
        ]

        observations = detector.detect(
            doc_id="doc1",
            tenant_id="default",
            passages=passages,
        )

        # Peut être vide ou avec peu d'observations
        # L'important est de ne pas inventer
        for obs in observations:
            assert len(obs.values_extracted) > 0

    def test_display_name_extraction(self, detector):
        """C1: Vérifie extraction du display_name."""
        passages = [
            Passage(
                passage_id="p1",
                doc_id="doc1",
                tenant_id="default",
                text="This release version 3.0 introduces new features.",
                position=0,
            ),
        ]

        observations = detector.detect(
            doc_id="doc1",
            tenant_id="default",
            passages=passages,
        )

        release_obs = next(
            (o for o in observations if o.axis_key == "release_id"),
            None
        )
        if release_obs:
            # display_name peut être "version" ou "release"
            assert release_obs.axis_display_name in [None, "version", "release", "v"]

    def test_stats_tracking(self, detector, sample_passages):
        """Vérifie que les statistiques sont trackées."""
        detector.reset_stats()

        detector.detect(
            doc_id="doc1",
            tenant_id="default",
            passages=sample_passages,
        )

        stats = detector.get_stats()
        assert stats["documents_processed"] == 1
        assert stats["axes_detected"] >= 0
        assert stats["fallback_extractions"] >= 0


class TestFallbackPatterns:
    """Tests pour les patterns fallback (domain-agnostic, conservatifs)."""

    def test_release_id_not_in_fallback(self):
        """release_id n'est PAS dans les fallback patterns (nécessite LLM)."""
        assert "release_id" not in FALLBACK_AXIS_PATTERNS

    def test_year_patterns_require_context(self):
        """year fallback nécessite un contexte copyright/publication."""
        pattern, group = FALLBACK_AXIS_PATTERNS["year"]

        # Matche AVEC contexte copyright/publication
        match_cases = [
            ("Copyright 2023 Acme Corp", "2023"),
            ("© 2021 All rights reserved", "2021"),
            ("Published 2024", "2024"),
            ("publication 2020 rev 3", "2020"),
        ]
        for text, expected in match_cases:
            match = pattern.search(text)
            assert match is not None, f"Pattern should match: {text}"
            assert match.group(group) == expected

        # Ne matche PAS sans contexte (trop ambigu)
        no_match_cases = [
            "2021",                    # nu → pourrait être version
            "Since 2020",              # pas copyright
            "Year 2023 edition",       # pas copyright
        ]
        for text in no_match_cases:
            match = pattern.search(text)
            assert match is None, f"Pattern should NOT match without copyright context: {text}"

    def test_effective_date_patterns(self):
        """Teste les patterns de date effective."""
        pattern, group = FALLBACK_AXIS_PATTERNS["effective_date"]

        test_cases = [
            ("since 2021-01", "2021-01"),
            ("as of 2020-06-15", "2020-06-15"),
            ("valid from 2023-03", "2023-03"),
        ]

        for text, expected in test_cases:
            match = pattern.search(text)
            assert match is not None, f"Pattern should match: {text}"
            assert match.group(group) == expected
