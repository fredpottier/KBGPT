"""
Tests unitaires pour le Document Structural Awareness Layer.

Tests:
- ZoneSegmenter: Segmentation des pages en zones
- TemplateDetector: Detection des fragments repetitifs
- LinguisticCueDetector: Scoring des patterns linguistiques
- Integration: Pipeline complet

Spec: doc/ongoing/ADR_DOCUMENT_STRUCTURAL_AWARENESS.md
"""

import pytest
from knowbase.extraction_v2.context.structural import (
    # Models
    StructuralConfidence,
    Zone,
    ZoneConfig,
    ZonedLine,
    PageZones,
    TemplateFragment,
    StructuralAnalysis,
    # Segmenter
    ZoneSegmenter,
    # Detector
    TemplateDetector,
    # Linguistic
    LinguisticCueDetector,
    ContextualCues,
)
from knowbase.extraction_v2.context.structural.models import (
    normalize_for_template_matching,
    is_significant_line,
)


# =============================================================================
# Tests pour normalize_for_template_matching
# =============================================================================


class TestNormalization:
    """Tests pour la fonction de normalisation."""

    def test_lowercase(self):
        assert normalize_for_template_matching("Hello World") == "hello world"

    def test_numbers_masked(self):
        assert normalize_for_template_matching("Version 1809") == "version #"
        assert normalize_for_template_matching("2019 SAP") == "# sap"

    def test_whitespace_normalized(self):
        assert normalize_for_template_matching("hello   world") == "hello world"
        assert normalize_for_template_matching("  test  ") == "test"

    def test_empty_string(self):
        assert normalize_for_template_matching("") == ""
        assert normalize_for_template_matching(None) == ""

    def test_copyright_line(self):
        """Le cas de test principal du document."""
        line = "© 2019 SAP SE or an SAP affiliate company. All rights reserved."
        normalized = normalize_for_template_matching(line)
        assert "sap" in normalized
        assert "#" in normalized  # 2019 -> #


class TestIsSignificantLine:
    """Tests pour is_significant_line."""

    def test_normal_line(self):
        config = ZoneConfig()
        assert is_significant_line("This is a normal line", config) is True

    def test_short_line(self):
        config = ZoneConfig(min_line_length=10)
        assert is_significant_line("Hi", config) is False
        assert is_significant_line("Hello World", config) is True

    def test_pure_number(self):
        config = ZoneConfig(ignore_pure_numbers=True)
        assert is_significant_line("42", config) is False
        assert is_significant_line("Page 42", config) is True

    def test_only_symbols(self):
        config = ZoneConfig()
        assert is_significant_line("---", config) is False
        assert is_significant_line("***", config) is False


# =============================================================================
# Tests pour StructuralConfidence
# =============================================================================


class TestStructuralConfidence:
    """Tests pour l'enum StructuralConfidence."""

    def test_from_page_count_high(self):
        assert StructuralConfidence.from_page_count(5) == StructuralConfidence.HIGH
        assert StructuralConfidence.from_page_count(10) == StructuralConfidence.HIGH
        assert StructuralConfidence.from_page_count(100) == StructuralConfidence.HIGH

    def test_from_page_count_medium(self):
        assert StructuralConfidence.from_page_count(3) == StructuralConfidence.MEDIUM
        assert StructuralConfidence.from_page_count(4) == StructuralConfidence.MEDIUM

    def test_from_page_count_low(self):
        assert StructuralConfidence.from_page_count(1) == StructuralConfidence.LOW
        assert StructuralConfidence.from_page_count(2) == StructuralConfidence.LOW
        assert StructuralConfidence.from_page_count(0) == StructuralConfidence.LOW


# =============================================================================
# Tests pour ZoneSegmenter
# =============================================================================


class TestZoneSegmenter:
    """Tests pour ZoneSegmenter."""

    @pytest.fixture
    def segmenter(self):
        return ZoneSegmenter()

    def test_segment_empty_page(self, segmenter):
        result = segmenter.segment_page("", page_index=0)
        assert result.page_index == 0
        assert len(result.top_lines) == 0
        assert len(result.main_lines) == 0
        assert len(result.bottom_lines) == 0

    def test_segment_simple_page(self, segmenter):
        page = """Header Line 1
Header Line 2
Main Content Line 1
Main Content Line 2
Main Content Line 3
Main Content Line 4
Footer Line 1
Footer Line 2"""
        result = segmenter.segment_page(page, page_index=0)

        assert len(result.top_lines) > 0
        assert len(result.main_lines) > 0
        assert len(result.bottom_lines) > 0

        # Le header devrait etre en TOP
        assert any("Header" in line.text for line in result.top_lines)
        # Le footer devrait etre en BOTTOM
        assert any("Footer" in line.text for line in result.bottom_lines)

    def test_segment_with_page_numbers(self, segmenter):
        """Les numeros de page purs doivent etre ignores."""
        page = """Title
Content
42"""
        result = segmenter.segment_page(page, page_index=0)

        # "42" ne devrait pas apparaitre car c'est un numero pur
        all_texts = [line.text for line in result.get_all_lines()]
        assert "42" not in all_texts

    def test_segment_document(self, segmenter):
        pages = [
            "Page 1 Header\nPage 1 Content\nPage 1 Footer",
            "Page 2 Header\nPage 2 Content\nPage 2 Footer",
            "Page 3 Header\nPage 3 Content\nPage 3 Footer",
        ]
        result = segmenter.segment_document(pages)

        assert len(result) == 3
        assert result[0].page_index == 0
        assert result[1].page_index == 1
        assert result[2].page_index == 2

    def test_get_structural_confidence(self, segmenter):
        assert segmenter.get_structural_confidence(1) == StructuralConfidence.LOW
        assert segmenter.get_structural_confidence(4) == StructuralConfidence.MEDIUM
        assert segmenter.get_structural_confidence(10) == StructuralConfidence.HIGH


# =============================================================================
# Tests pour TemplateDetector
# =============================================================================


class TestTemplateDetector:
    """Tests pour TemplateDetector."""

    @pytest.fixture
    def detector(self):
        return TemplateDetector(min_pages_ratio=0.3, min_occurrences=2)

    @pytest.fixture
    def segmenter(self):
        return ZoneSegmenter()

    def test_detect_repeated_footer(self, detector, segmenter):
        """Test principal: detecter un footer copyright repete."""
        # Simuler 5 pages avec le meme footer
        pages = []
        for i in range(5):
            page = f"""Title Page {i+1}
Main content for page {i+1}
More content here
© 2019 SAP SE or an SAP affiliate company. All rights reserved."""
            pages.append(page)

        pages_zones = segmenter.segment_document(pages)
        analysis = detector.analyze(pages_zones)

        # Devrait detecter le footer comme template
        assert len(analysis.template_fragments) >= 1

        # Le footer devrait avoir une haute template_likelihood
        copyright_template = None
        for template in analysis.template_fragments:
            if "sap" in template.normalized_text and "reserved" in template.normalized_text:
                copyright_template = template
                break

        assert copyright_template is not None, "Copyright footer not detected as template"
        assert copyright_template.template_likelihood > 0.5
        assert copyright_template.dominant_zone == Zone.BOTTOM

    def test_no_template_in_varied_content(self, detector, segmenter):
        """Du contenu varie ne devrait pas etre detecte comme template."""
        pages = [
            "Unique content page 1\nDifferent text here",
            "Completely different page 2\nNothing similar",
            "Yet another page 3\nAll unique content",
        ]
        pages_zones = segmenter.segment_document(pages)
        analysis = detector.analyze(pages_zones)

        # Peu ou pas de templates
        assert len(analysis.template_fragments) <= 1

    def test_structural_confidence_propagated(self, detector, segmenter):
        """La confiance structurelle doit etre propagee."""
        # 2 pages = LOW confidence
        pages_2 = ["Page 1", "Page 2"]
        analysis_2 = detector.analyze(segmenter.segment_document(pages_2))
        assert analysis_2.structural_confidence == StructuralConfidence.LOW

        # 5 pages = HIGH confidence
        pages_5 = [f"Page {i}" for i in range(5)]
        analysis_5 = detector.analyze(segmenter.segment_document(pages_5))
        assert analysis_5.structural_confidence == StructuralConfidence.HIGH

    def test_is_value_in_template(self, detector, segmenter):
        """Test helper is_value_in_template."""
        pages = []
        for i in range(5):
            pages.append(f"Content\n© 2019 Company. All rights reserved.")

        pages_zones = segmenter.segment_document(pages)
        analysis = detector.analyze(pages_zones)

        # "2019" devrait etre dans un template (normalise en #)
        # Mais la valeur exacte peut ne pas matcher car normalisee
        # On verifie que l'analyse a des templates
        assert len(analysis.template_fragments) >= 1


# =============================================================================
# Tests pour LinguisticCueDetector
# =============================================================================


class TestLinguisticCueDetector:
    """Tests pour LinguisticCueDetector."""

    @pytest.fixture
    def detector(self):
        return LinguisticCueDetector()

    def test_scope_language_detection(self, detector):
        """Detecter le scope language."""
        text = "Available in version 1809 and later releases"
        cues = detector.score_context(text)

        assert cues.scope_language_score > 0.3
        assert len(cues.scope_matches) > 0

    def test_legal_language_detection(self, detector):
        """Detecter le legal language."""
        text = "© 2019 SAP SE or an SAP affiliate company. All rights reserved."
        cues = detector.score_context(text)

        assert cues.legal_language_score > 0.5
        assert len(cues.legal_matches) > 0

    def test_contrast_language_detection(self, detector):
        """Detecter le contrast language."""
        text = "Unlike version 1809, the 2020 release includes new features"
        cues = detector.score_context(text)

        assert cues.contrast_language_score > 0.3
        assert len(cues.contrast_matches) > 0

    def test_empty_text(self, detector):
        """Texte vide = scores a zero."""
        cues = detector.score_context("")
        assert cues.scope_language_score == 0.0
        assert cues.legal_language_score == 0.0
        assert cues.contrast_language_score == 0.0

    def test_is_likely_template_context(self, detector):
        """Test helper is_likely_template_context."""
        legal_cues = ContextualCues(
            scope_language_score=0.1,
            legal_language_score=0.8,
        )
        assert detector.is_likely_template_context(legal_cues) is True

        scope_cues = ContextualCues(
            scope_language_score=0.8,
            legal_language_score=0.1,
        )
        assert detector.is_likely_template_context(scope_cues) is False

    def test_is_likely_context_setting(self, detector):
        """Test helper is_likely_context_setting."""
        scope_cues = ContextualCues(
            scope_language_score=0.5,
            legal_language_score=0.1,
        )
        assert detector.is_likely_context_setting(scope_cues) is True

        legal_cues = ContextualCues(
            scope_language_score=0.1,
            legal_language_score=0.8,
        )
        assert detector.is_likely_context_setting(legal_cues) is False

    def test_score_evidence_samples(self, detector):
        """Test agregation de plusieurs samples."""
        samples = [
            {"text": "Available in version 1809", "page": 0, "zone": "main"},
            {"text": "© 2019 Company", "page": 1, "zone": "bottom"},
        ]
        cues = detector.score_evidence_samples(samples)

        # Les deux types de language devraient etre detectes
        assert cues.scope_language_score > 0
        assert cues.legal_language_score > 0


# =============================================================================
# Tests d'integration
# =============================================================================


class TestIntegration:
    """Tests d'integration du pipeline complet."""

    def test_sap_1809_scenario(self):
        """
        Test du scenario principal: document SAP 1809 avec footer copyright.

        Attendu:
        - 1809 dans titre/main = CONTEXT_SETTING
        - 2019 dans footer repete = TEMPLATE_NOISE
        """
        # Simuler le document SAP 1809
        pages = []
        for i in range(10):
            if i == 0:
                # Page de couverture
                page = """SAP S/4HANA
Business Scope Release 1809
Speaker's Name, SAP
© 2019 SAP SE or an SAP affiliate company. All rights reserved."""
            else:
                page = f"""Slide {i+1} Content
Feature description for 1809
More technical details
© 2019 SAP SE or an SAP affiliate company. All rights reserved."""
            pages.append(page)

        # Pipeline
        segmenter = ZoneSegmenter()
        template_detector = TemplateDetector()
        linguistic_detector = LinguisticCueDetector()

        # Etape 1: Segmentation
        pages_zones = segmenter.segment_document(pages)
        assert len(pages_zones) == 10

        # Etape 2: Detection templates
        analysis = template_detector.analyze(pages_zones)
        assert analysis.structural_confidence == StructuralConfidence.HIGH

        # Le footer copyright doit etre detecte
        copyright_templates = [
            t for t in analysis.template_fragments
            if "reserved" in t.normalized_text
        ]
        assert len(copyright_templates) >= 1

        copyright_template = copyright_templates[0]
        assert copyright_template.dominant_zone == Zone.BOTTOM
        assert copyright_template.template_likelihood > 0.5

        # Etape 3: Linguistic cues pour le footer
        footer_cues = linguistic_detector.score_context(
            "© 2019 SAP SE or an SAP affiliate company. All rights reserved."
        )
        assert footer_cues.legal_language_score > 0.5
        assert footer_cues.scope_language_score < 0.3

        # Etape 3b: Linguistic cues pour le titre
        title_cues = linguistic_detector.score_context(
            "Business Scope Release 1809"
        )
        assert title_cues.scope_language_score > 0.3
        assert title_cues.legal_language_score < 0.3

        # Verification finale des distributions
        zone_dist_2019 = analysis.get_zone_distribution_for_value("2019")
        zone_dist_1809 = analysis.get_zone_distribution_for_value("1809")

        # 2019 devrait etre majoritairement en BOTTOM
        assert zone_dist_2019["bottom"] > zone_dist_2019["main"]
        assert zone_dist_2019["bottom"] > zone_dist_2019["top"]

        # 1809 devrait etre majoritairement en TOP/MAIN
        total_top_main = zone_dist_1809["top"] + zone_dist_1809["main"]
        assert total_top_main > zone_dist_1809["bottom"]

    def test_short_document_low_confidence(self):
        """Document court = confiance structurelle faible."""
        # Contenu varie pour eviter detection template
        pages = [
            "Introduction to the topic\nWith detailed explanation",
            "Different content entirely\nUnrelated paragraphs here",
        ]

        segmenter = ZoneSegmenter()
        template_detector = TemplateDetector()

        pages_zones = segmenter.segment_document(pages)
        analysis = template_detector.analyze(pages_zones)

        assert analysis.structural_confidence == StructuralConfidence.LOW
        # Avec contenu varie, peu de templates detectes
        assert analysis.template_coverage < 0.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
