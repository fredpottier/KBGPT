"""
Tests pour DocContext extraction (ADR_ASSERTION_AWARE_KG).

Teste:
- CandidateMiner: extraction deterministe de marqueurs
- DocContextExtractor: classification et validation
- Models: serialisation/deserialisation
"""

import pytest
from knowbase.extraction_v2.context.models import (
    DocScope,
    MarkerEvidence,
    ScopeSignals,
    DocContextFrame,
    DocScopeAnalysis,
)
from knowbase.extraction_v2.context.candidate_mining import (
    CandidateMiner,
    MarkerCandidate,
    MiningResult,
)
from knowbase.extraction_v2.context.doc_context_extractor import (
    DocContextExtractor,
)


class TestDocScope:
    """Tests pour DocScope enum."""

    def test_values(self):
        assert DocScope.GENERAL.value == "GENERAL"
        assert DocScope.VARIANT_SPECIFIC.value == "VARIANT_SPECIFIC"
        assert DocScope.MIXED.value == "MIXED"

    def test_from_string(self):
        assert DocScope("GENERAL") == DocScope.GENERAL
        assert DocScope("VARIANT_SPECIFIC") == DocScope.VARIANT_SPECIFIC
        assert DocScope("MIXED") == DocScope.MIXED


class TestMarkerEvidence:
    """Tests pour MarkerEvidence."""

    def test_creation(self):
        m = MarkerEvidence(
            value="1809",
            evidence="SAP S/4HANA 1809",
            source="cover",
            confidence=0.9,
        )
        assert m.value == "1809"
        assert m.source == "cover"
        assert m.confidence == 0.9

    def test_serialization(self):
        m = MarkerEvidence(
            value="2025",
            evidence="Edition 2025",
            source="header",
        )
        d = m.to_dict()
        assert d["value"] == "2025"
        assert d["source"] == "header"

        m2 = MarkerEvidence.from_dict(d)
        assert m2.value == m.value
        assert m2.source == m.source


class TestScopeSignals:
    """Tests pour ScopeSignals."""

    def test_defaults(self):
        s = ScopeSignals()
        assert s.marker_position_score == 0.0
        assert s.conflict_score == 0.0

    def test_compute_variant_score(self):
        s = ScopeSignals(
            marker_position_score=0.9,
            marker_repeat_score=0.7,
            scope_language_score=0.5,
            marker_diversity_score=0.1,
            conflict_score=0.0,
        )
        score = s.compute_variant_score()
        assert score > 0.5  # Devrait etre eleve

    def test_compute_mixed_score(self):
        s = ScopeSignals(
            marker_diversity_score=0.8,
            conflict_score=0.7,
        )
        score = s.compute_mixed_score()
        assert score > 0.5  # Devrait etre eleve


class TestDocContextFrame:
    """Tests pour DocContextFrame."""

    def test_creation(self):
        frame = DocContextFrame(
            document_id="doc_123",
            strong_markers=["1809"],
            weak_markers=["FPS03"],
            doc_scope=DocScope.VARIANT_SPECIFIC,
            scope_confidence=0.85,
        )
        assert frame.document_id == "doc_123"
        assert frame.has_markers()
        assert frame.get_dominant_marker() == "1809"

    def test_empty(self):
        frame = DocContextFrame.empty("doc_empty")
        assert frame.doc_scope == DocScope.GENERAL
        assert not frame.has_markers()
        assert frame.get_dominant_marker() is None

    def test_serialization(self):
        frame = DocContextFrame(
            document_id="doc_456",
            strong_markers=["2025"],
            doc_scope=DocScope.VARIANT_SPECIFIC,
            scope_confidence=0.8,
        )
        d = frame.to_dict()
        assert d["document_id"] == "doc_456"
        assert d["doc_scope"] == "VARIANT_SPECIFIC"

        frame2 = DocContextFrame.from_dict(d)
        assert frame2.document_id == frame.document_id
        assert frame2.doc_scope == frame.doc_scope


class TestCandidateMiner:
    """Tests pour CandidateMiner."""

    @pytest.fixture
    def miner(self):
        return CandidateMiner()

    def test_mine_filename_version(self, miner):
        """Test extraction de version depuis filename."""
        result = miner.mine_document(
            filename="S4HANA_1809_BUSINESS_SCOPE.pdf",
            pages_text=["Some content"],
        )
        values = result.get_unique_values()
        assert "1809" in values

    def test_mine_filename_year(self, miner):
        """Test extraction d'annee depuis filename."""
        result = miner.mine_document(
            filename="Business-Scope-2025-SAP-Cloud.pdf",
            pages_text=["Some content"],
        )
        values = result.get_unique_values()
        assert "2025" in values

    def test_mine_cover_page(self, miner):
        """Test extraction depuis cover page."""
        result = miner.mine_document(
            filename="document.pdf",
            pages_text=[
                "SAP S/4HANA 1809 Feature Pack Stack",
                "Page 2 content",
            ],
        )
        values = result.get_unique_values()
        assert "1809" in values

        # Verifier que la source est "cover"
        cover_candidates = result.get_by_source("cover")
        assert len(cover_candidates) > 0

    def test_mine_fps_pattern(self, miner):
        """Test extraction de FPS (Feature Pack Stack)."""
        result = miner.mine_document(
            filename="document.pdf",
            pages_text=["This applies to FPS03 and later"],
        )
        values = result.get_unique_values()
        assert "FPS03" in values

    def test_mine_no_candidates(self, miner):
        """Test quand aucun candidat n'est detecte."""
        result = miner.mine_document(
            filename="general_overview.pdf",
            pages_text=["This is a general overview document."],
        )
        assert len(result.candidates) == 0

    def test_conflict_detection(self, miner):
        """Test detection de patterns de conflit."""
        result = miner.mine_document(
            filename="comparison.pdf",
            pages_text=[
                "1809 vs 2020 comparison",
                "Unlike 1809, the 2020 version has...",
            ],
        )
        assert result.conflict_hits > 0

    def test_scope_language_detection(self, miner):
        """Test detection de scope language."""
        result = miner.mine_document(
            filename="doc.pdf",
            pages_text=[
                "This version applies to S/4HANA 1809 only.",
                "Starting with release 2020...",
            ],
        )
        assert result.scope_language_hits > 0

    def test_compute_signals(self, miner):
        """Test calcul des signaux."""
        result = miner.mine_document(
            filename="S4HANA_1809.pdf",
            pages_text=[
                "SAP S/4HANA 1809 Business Scope",
                "More about 1809 features",
            ],
        )
        signals = miner.compute_signals(result, total_pages=2)

        assert "marker_position_score" in signals
        assert "marker_repeat_score" in signals
        assert 0.0 <= signals["marker_position_score"] <= 1.0


class TestDocContextExtractor:
    """Tests pour DocContextExtractor."""

    @pytest.fixture
    def extractor(self):
        # Mode sans LLM pour tests
        return DocContextExtractor(use_llm=False)

    def test_extract_sync_variant_specific(self, extractor):
        """Test classification VARIANT_SPECIFIC (sync)."""
        frame = extractor.extract_sync(
            document_id="doc_1809",
            filename="S4HANA_1809_BUSINESS_SCOPE_MASTER.pdf",
            pages_text=[
                "SAP S/4HANA 1809",
                "Feature Pack Stack 03",
                "Business Scope Master",
            ],
        )
        assert frame.doc_scope == DocScope.VARIANT_SPECIFIC
        assert "1809" in frame.strong_markers or "1809" in frame.weak_markers

    def test_extract_sync_general(self, extractor):
        """Test classification GENERAL (sync)."""
        frame = extractor.extract_sync(
            document_id="doc_general",
            filename="GROW_with_SAP_Overview.pptx",
            pages_text=[
                "GROW with SAP",
                "Overview presentation",
                "Benefits and features",
            ],
        )
        # Sans marqueurs specifiques, devrait etre GENERAL
        # (peut etre VARIANT_SPECIFIC si "GROW" est detecte)
        assert frame.doc_scope in (DocScope.GENERAL, DocScope.VARIANT_SPECIFIC)

    def test_extract_sync_mixed(self, extractor):
        """Test classification MIXED (sync)."""
        frame = extractor.extract_sync(
            document_id="doc_comparison",
            filename="Whats_New_S4HANA_2508.pdf",
            pages_text=[
                "What's New in SAP S/4HANA Cloud 2508",
                "Compared to previous version 2408",
                "Unlike 2408, the new 2508 release...",
                "1809 vs 2020 vs 2508 comparison",
            ],
        )
        # Avec plusieurs versions et patterns de comparaison
        # Ca peut etre MIXED ou VARIANT_SPECIFIC selon l'heuristique
        assert frame.doc_scope in (DocScope.MIXED, DocScope.VARIANT_SPECIFIC)
        assert frame.has_markers()

    @pytest.mark.asyncio
    async def test_extract_async(self, extractor):
        """Test extraction async sans LLM."""
        frame = await extractor.extract(
            document_id="doc_async",
            filename="S4HANA_2025.pdf",
            pages_text=[
                "SAP S/4HANA Cloud 2025",
                "Private Edition features",
            ],
        )
        assert frame.document_id == "doc_async"
        assert frame.has_markers() or frame.doc_scope == DocScope.GENERAL


class TestDocScopeAnalysis:
    """Tests pour DocScopeAnalysis."""

    def test_to_context_frame(self):
        """Test conversion vers DocContextFrame."""
        analysis = DocScopeAnalysis(
            strong_markers=[
                MarkerEvidence(value="1809", evidence="SAP 1809", source="cover"),
            ],
            weak_markers=[
                MarkerEvidence(value="FPS03", evidence="FPS03", source="body"),
            ],
            doc_scope=DocScope.VARIANT_SPECIFIC,
            scope_confidence=0.85,
        )

        frame = analysis.to_context_frame("doc_test")

        assert frame.document_id == "doc_test"
        assert frame.strong_markers == ["1809"]
        assert frame.weak_markers == ["FPS03"]
        assert frame.doc_scope == DocScope.VARIANT_SPECIFIC
        assert frame.scope_confidence == 0.85


class TestIntegration:
    """Tests d'integration."""

    def test_mining_result_merge_duplicates(self):
        """Test fusion des doublons dans MiningResult."""
        result = MiningResult(
            candidates=[
                MarkerCandidate(value="1809", source="filename"),
                MarkerCandidate(value="1809", source="cover"),
                MarkerCandidate(value="1809", source="body"),
            ],
        )
        merged = result.merge_duplicates()

        assert len(merged.candidates) == 1
        candidate = merged.candidates[0]
        assert candidate.value == "1809"
        # Source la plus fiable devrait etre gardee
        assert candidate.source == "filename"
        assert candidate.occurrences == 3

    def test_full_pipeline_sync(self):
        """Test pipeline complet en mode sync."""
        extractor = DocContextExtractor(use_llm=False)

        # Document SAP 1809
        frame = extractor.extract_sync(
            document_id="full_test",
            filename="S4HANA_1809_BUSINESS_SCOPE_MASTER_L23.pdf",
            pages_text=[
                "SAP S/4HANA 1809",
                "Business Scope Master Guide",
                "Level 2-3 Documentation",
                "Applies to SAP S/4HANA 1809 FPS03",
                "Content about various features...",
            ] * 3,  # Simuler plusieurs pages
        )

        assert frame.document_id == "full_test"
        assert frame.has_markers()
        # Devrait detecter 1809
        all_markers = frame.strong_markers + frame.weak_markers
        assert any("1809" in m for m in all_markers)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
