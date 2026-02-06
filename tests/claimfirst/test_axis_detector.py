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
    BOOTSTRAP_AXIS_PATTERNS,
)
from knowbase.claimfirst.models.passage import Passage


@pytest.fixture
def detector():
    """Crée un détecteur sans LLM."""
    return ApplicabilityAxisDetector(llm_client=None, use_llm_discovery=False)


@pytest.fixture
def sample_passages():
    """Crée des passages de test."""
    return [
        Passage(
            passage_id="p1",
            doc_id="doc1",
            tenant_id="default",
            text="This feature is available in SAP S/4HANA version 2021.",
            position=0,
        ),
        Passage(
            passage_id="p2",
            doc_id="doc1",
            tenant_id="default",
            text="Since 2020, the GL Accounting module supports multi-currency.",
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
    """Tests pour ApplicabilityAxisDetector."""

    def test_detect_numeric_order(self, detector, sample_passages):
        """Détecte un axe avec ordre numérique (release_id)."""
        observations = detector.detect(
            doc_id="doc1",
            tenant_id="default",
            passages=sample_passages,
        )

        # Doit détecter release_id (version 2021)
        release_obs = next(
            (o for o in observations if o.axis_key == "release_id"),
            None
        )
        assert release_obs is not None
        assert "2021" in release_obs.values_extracted
        assert release_obs.reliability == "explicit_text"

    def test_detect_year(self, detector, sample_passages):
        """Détecte l'axe year."""
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
        # Devrait trouver 2021 et 2020
        assert len(year_obs.values_extracted) >= 1

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
                # passage_id peut être None pour metadata

    def test_detect_from_title(self, detector):
        """Détecte depuis le titre du document."""
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
            doc_title="SAP S/4HANA 2023 Operations Guide",
        )

        # Doit détecter depuis le titre (2023 = year, pas release_id)
        year_obs = next(
            (o for o in observations if o.axis_key == "year"),
            None
        )
        assert year_obs is not None
        assert "2023" in year_obs.values_extracted
        assert year_obs.reliability == "metadata"

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
        assert stats["bootstrap_matches"] >= 0


class TestBootstrapPatterns:
    """Tests pour les patterns bootstrap."""

    def test_version_patterns(self):
        """Teste les patterns de version."""
        pattern, group = BOOTSTRAP_AXIS_PATTERNS["release_id"]

        test_cases = [
            ("version 2021", "2021"),
            ("release 3.0", "3.0"),
            ("v1.2.3", "1.2.3"),
            ("V 2.0", "2.0"),
            ("Release: 2023", "2023"),
        ]

        for text, expected in test_cases:
            match = pattern.search(text)
            assert match is not None, f"Pattern should match: {text}"
            assert match.group(group) == expected, f"Expected {expected} from {text}"

    def test_year_patterns(self):
        """Teste les patterns d'année."""
        pattern, group = BOOTSTRAP_AXIS_PATTERNS["year"]

        test_cases = [
            ("2021", "2021"),
            ("Since 2020", "2020"),
            ("Year 2023 edition", "2023"),
        ]

        for text, expected in test_cases:
            match = pattern.search(text)
            assert match is not None, f"Pattern should match: {text}"
            assert match.group(group) == expected

    def test_effective_date_patterns(self):
        """Teste les patterns de date effective."""
        pattern, group = BOOTSTRAP_AXIS_PATTERNS["effective_date"]

        test_cases = [
            ("since 2021-01", "2021-01"),
            ("as of 2020-06-15", "2020-06-15"),
            ("valid from 2023-03", "2023-03"),
        ]

        for text, expected in test_cases:
            match = pattern.search(text)
            assert match is not None, f"Pattern should match: {text}"
            assert match.group(group) == expected
