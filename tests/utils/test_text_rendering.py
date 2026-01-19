"""
Tests pour les utilitaires de rendu texte OSMOSE.

Vérifie que les fonctions de nettoyage des marqueurs Docling
fonctionnent correctement sans altérer le texte de référence.
"""

import pytest
from knowbase.utils.text_rendering import (
    strip_markers,
    render_quote,
    make_embedding_text,
    make_embedding_text_aggressive,
    extract_span_with_mapping,
)


class TestStripMarkers:
    """Tests pour strip_markers()."""

    def test_strip_paragraph_marker(self):
        """Supprime les marqueurs [PARAGRAPH]."""
        text = "[PARAGRAPH]\nThis is content."
        result = strip_markers(text)
        assert result == "This is content."

    def test_strip_page_marker(self):
        """Supprime les marqueurs [PAGE n]."""
        text = "[PAGE 1]\nContent here.\n[PAGE 2 | TYPE=DIAGRAM]\nMore content."
        result = strip_markers(text)
        assert "PAGE" not in result
        assert "Content here." in result
        assert "More content." in result

    def test_strip_table_markers(self):
        """Supprime les marqueurs de table mais garde le contenu."""
        text = "[TABLE_START id=tbl_1]\n| A | B |\n| 1 | 2 |\n[TABLE_END]"
        result = strip_markers(text)
        assert "TABLE_START" not in result
        assert "TABLE_END" not in result
        assert "| A | B |" in result

    def test_strip_title_marker(self):
        """Supprime les marqueurs [TITLE level=n]."""
        text = "[TITLE level=1] Important Section\nContent follows."
        result = strip_markers(text)
        assert "TITLE" not in result
        # Le titre lui-même devrait rester
        assert "Important Section" in result

    def test_strip_visual_enrichment_marker(self):
        """Supprime les marqueurs VISUAL_ENRICHMENT."""
        text = "[VISUAL_ENRICHMENT id=v1 confidence=0.85]\ndiagram_type: architecture\n[END_VISUAL_ENRICHMENT]"
        result = strip_markers(text, preserve_content=True)
        assert "VISUAL_ENRICHMENT" not in result
        assert "END_VISUAL_ENRICHMENT" not in result

    def test_strip_visual_block_complete(self):
        """Supprime les blocs VISUAL_ENRICHMENT complets avec preserve_content=False."""
        text = "Before.\n[VISUAL_ENRICHMENT id=v1]\ndiagram content\n[END_VISUAL_ENRICHMENT]\nAfter."
        result = strip_markers(text, preserve_content=False)
        assert "VISUAL_ENRICHMENT" not in result
        assert "diagram content" not in result
        assert "Before." in result
        assert "After." in result

    def test_empty_text(self):
        """Gère les textes vides."""
        assert strip_markers("") == ""
        assert strip_markers(None) == ""

    def test_no_markers(self):
        """Texte sans marqueurs reste inchangé."""
        text = "Just plain text without any markers."
        result = strip_markers(text)
        assert result == text

    def test_multiple_consecutive_markers(self):
        """Gère plusieurs marqueurs consécutifs."""
        text = "[PAGE 1]\n[PARAGRAPH]\nContent.\n[PARAGRAPH]\nMore content."
        result = strip_markers(text)
        assert "PAGE" not in result
        assert "PARAGRAPH" not in result
        assert "Content." in result
        assert "More content." in result

    def test_cleans_multiple_newlines(self):
        """Nettoie les lignes vides multiples."""
        text = "[PAGE 1]\n\n\n[PARAGRAPH]\nContent.\n\n\n\nMore."
        result = strip_markers(text)
        # Pas plus de 2 newlines consécutifs
        assert "\n\n\n" not in result


class TestRenderQuote:
    """Tests pour render_quote()."""

    def test_basic_quote_extraction(self):
        """Extrait une quote simple."""
        text = "[PARAGRAPH]\nSAP BTP enables integration.\n[TABLE_START]"
        # "SAP BTP enables integration." commence après "[PARAGRAPH]\n" = 12 chars
        result = render_quote(text, 12, 40)
        assert "SAP BTP enables integration." in result
        assert "PARAGRAPH" not in result

    def test_quote_with_marker_inside(self):
        """Gère une quote qui chevauche un marqueur."""
        text = "Start [PARAGRAPH]\nMiddle content here."
        result = render_quote(text, 0, 35)
        assert "PARAGRAPH" not in result
        assert "Start" in result

    def test_quote_with_context(self):
        """Ajoute du contexte avant/après."""
        text = "Before. Target text here. After."
        result = render_quote(text, 8, 24, context_chars=5)
        assert "..." in result  # Ellipse car contexte tronqué
        assert "Target text here" in result

    def test_empty_span(self):
        """Gère les spans vides ou invalides."""
        text = "Some text"
        assert render_quote(text, -1, 5) == ""
        assert render_quote(text, 5, 3) == ""  # end < start
        assert render_quote("", 0, 5) == ""

    def test_quote_preserves_table_content(self):
        """Préserve le contenu des tables."""
        text = "[TABLE_START id=1]\n| Col1 | Col2 |\n| A | B |\n[TABLE_END]"
        result = render_quote(text, 0, len(text))
        assert "| Col1 | Col2 |" in result
        assert "TABLE_START" not in result


class TestMakeEmbeddingText:
    """Tests pour make_embedding_text()."""

    def test_removes_markers_keeps_content(self):
        """Supprime marqueurs mais garde tout le contenu."""
        text = "[PAGE 1]\n[PARAGRAPH]\nImportant semantic content.\n[TABLE_START]\n| Data |"
        result = make_embedding_text(text)
        assert "PAGE" not in result
        assert "PARAGRAPH" not in result
        assert "TABLE_START" not in result
        assert "Important semantic content." in result
        assert "| Data |" in result

    def test_empty_text(self):
        """Gère texte vide."""
        assert make_embedding_text("") == ""

    def test_clean_text_unchanged(self):
        """Texte sans marqueurs reste similaire."""
        text = "Clean semantic text for embeddings."
        result = make_embedding_text(text)
        assert result.strip() == text


class TestMakeEmbeddingTextAggressive:
    """Tests pour make_embedding_text_aggressive()."""

    def test_removes_visual_blocks(self):
        """Supprime les blocs VISUAL_ENRICHMENT complets."""
        text = (
            "Semantic content.\n"
            "[VISUAL_ENRICHMENT id=v1]\n"
            "diagram_type: architecture\n"
            "visible_elements:\n"
            "- [E1|box] SAP\n"
            "[END_VISUAL_ENRICHMENT]\n"
            "More semantic content."
        )
        result = make_embedding_text_aggressive(text)
        assert "Semantic content." in result
        assert "More semantic content." in result
        assert "diagram_type" not in result
        assert "visible_elements" not in result
        assert "VISUAL_ENRICHMENT" not in result

    def test_preserves_tables(self):
        """Garde le contenu des tables (utile sémantiquement)."""
        text = "[TABLE_START]\n| Product | Price |\n| SAP | 100 |\n[TABLE_END]"
        result = make_embedding_text_aggressive(text)
        assert "| Product | Price |" in result


class TestExtractSpanWithMapping:
    """Tests pour extract_span_with_mapping()."""

    def test_basic_mapping(self):
        """Calcule les nouvelles positions après nettoyage."""
        text = "[PARAGRAPH]\nTarget text.\n[TABLE_START]"
        # "Target text." commence à position 12 dans le texte brut
        clean_text, new_start, new_end = extract_span_with_mapping(text, 12, 24)
        assert "Target text." in clean_text
        assert new_start >= 0
        assert new_end > new_start

    def test_empty_before(self):
        """Gère le cas où il n'y a rien avant le span."""
        text = "Target text here."
        clean_text, new_start, new_end = extract_span_with_mapping(text, 0, 11)
        assert new_start == 0
        assert clean_text == "Target text"

    def test_invalid_input(self):
        """Gère les entrées invalides."""
        assert extract_span_with_mapping("", 0, 5) == ("", 0, 0)
        assert extract_span_with_mapping("text", -1, 5) == ("", 0, 0)


class TestRealWorldScenarios:
    """Tests avec des exemples réalistes de documents OSMOSE."""

    def test_gdpr_document_chunk(self):
        """Teste avec un chunk typique de document GDPR."""
        text = """[PAGE 5 | TYPE=REGULATORY]
[TITLE level=1] Article 35 - Data Protection Impact Assessment

[PARAGRAPH]
Where a type of processing in particular using new technologies, and taking into account the nature, scope, context and purposes of the processing, is likely to result in a high risk to the rights and freedoms of natural persons, the controller shall, prior to the processing, carry out an assessment of the impact of the envisaged processing operations on the protection of personal data.

[TABLE_START id=dpia_criteria]
| Criteria | Description |
| High risk processing | Systematic monitoring, sensitive data |
| New technologies | AI, biometrics, profiling |
[TABLE_END]"""

        # Test render_quote pour une citation
        quote = render_quote(text, 100, 250)
        assert "PARAGRAPH" not in quote
        assert "processing" in quote.lower()

        # Test embedding text
        embed_text = make_embedding_text(text)
        assert "PAGE" not in embed_text
        assert "Article 35" in embed_text
        assert "| Criteria | Description |" in embed_text

    def test_architecture_diagram_page(self):
        """Teste avec une page de diagramme d'architecture."""
        text = """[PAGE 12 | TYPE=ARCHITECTURE_DIAGRAM]
[TITLE level=2] SAP BTP Integration Architecture

[VISUAL_ENRICHMENT id=vision_12_1 confidence=0.92]
diagram_type: architecture_diagram
visible_elements:
- [E1|box] "SAP Enterprise Cloud"
- [E2|box] "SAP BTP"
- [E3|arrow] "Integration Flow"
[END_VISUAL_ENRICHMENT]

[PARAGRAPH]
This architecture enables seamless data flow between on-premise and cloud systems."""

        # Embedding standard garde le contenu vision
        embed_std = make_embedding_text(text)
        assert "SAP BTP Integration Architecture" in embed_std

        # Embedding agressif supprime le bloc vision
        embed_agg = make_embedding_text_aggressive(text)
        assert "visible_elements" not in embed_agg
        assert "diagram_type" not in embed_agg
        assert "seamless data flow" in embed_agg
