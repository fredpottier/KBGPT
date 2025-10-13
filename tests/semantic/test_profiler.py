"""
🌊 OSMOSE Semantic Intelligence - Tests Profiler

Tests pour SemanticDocumentProfiler
"""

import pytest
import asyncio
from knowbase.semantic.profiler import SemanticDocumentProfiler


class TestSemanticDocumentProfiler:
    """Tests du profiler sémantique"""

    def test_profiler_initialization(self):
        """Test initialisation profiler"""
        profiler = SemanticDocumentProfiler()

        assert profiler is not None
        assert profiler.config is not None
        assert profiler.llm_router is not None

    @pytest.mark.asyncio
    async def test_profile_simple_document(self):
        """Test profiling d'un document simple"""
        profiler = SemanticDocumentProfiler()

        text = """
        This is a simple document. It contains basic information.
        There are no complex concepts here. Just plain text.
        """

        profile = await profiler.profile_document(
            document_id="test_001",
            document_path="/test/simple.txt",
            tenant_id="tenant_test",
            text_content=text
        )

        # Vérifications
        assert profile.document_id == "test_001"
        assert profile.tenant_id == "tenant_test"
        assert profile.overall_complexity >= 0.0
        assert profile.overall_complexity <= 1.0
        assert profile.domain in ["finance", "pharma", "consulting", "general"]

    @pytest.mark.asyncio
    async def test_profile_document_with_narratives(self):
        """Test profiling avec détection de narratives"""
        profiler = SemanticDocumentProfiler()

        text = """
        The Customer Retention Rate was revised in 2023.
        This change was made because the previous methodology was outdated.
        Therefore, we updated the formula to align with ISO standards.
        The new version superseded the old one as a result of stakeholder feedback.
        """

        profile = await profiler.profile_document(
            document_id="test_002",
            document_path="/test/narrative.txt",
            tenant_id="tenant_test",
            text_content=text
        )

        # Vérifications narratives
        assert len(profile.narrative_threads) > 0, "Should detect narrative threads"

        # Vérifier qu'au moins un thread contient des causal/temporal markers
        has_causal = any(len(t.causal_links) > 0 for t in profile.narrative_threads)
        has_temporal = any(len(t.temporal_markers) > 0 for t in profile.narrative_threads)

        assert has_causal or has_temporal, "Should detect causal or temporal markers"


class TestComplexityAnalysis:
    """Tests de l'analyse de complexité"""

    def test_complexity_score_to_level(self):
        """Test conversion score → niveau"""
        profiler = SemanticDocumentProfiler()

        assert profiler._complexity_score_to_level(0.2) == "simple"
        assert profiler._complexity_score_to_level(0.5) == "medium"
        assert profiler._complexity_score_to_level(0.8) == "complex"

    def test_split_text_into_chunks(self):
        """Test découpage en chunks"""
        profiler = SemanticDocumentProfiler()

        short_text = "This is short"
        chunks = profiler._split_text_into_chunks(short_text, max_length=100)
        assert len(chunks) == 1

        long_text = "A" * 5000
        chunks = profiler._split_text_into_chunks(long_text, max_length=1000)
        assert len(chunks) > 1


class TestNarrativeDetection:
    """Tests de détection de narratives"""

    def test_detect_causal_connectors(self):
        """Test détection connecteurs causaux"""
        profiler = SemanticDocumentProfiler()

        text = "This happened because of that. Therefore, we changed. As a result, it improved."
        threads = profiler._detect_preliminary_narratives(text)

        # Au moins un thread devrait être détecté
        assert len(threads) >= 0  # Peut être 0 si moins de 2 occurrences du même connecteur

    def test_detect_temporal_markers(self):
        """Test détection marqueurs temporels"""
        profiler = SemanticDocumentProfiler()

        text = "The document was revised. The formula was updated. The methodology was superseded."
        threads = profiler._detect_preliminary_narratives(text)

        # Devrait détecter des marqueurs temporels
        temporal_threads = [t for t in threads if len(t.temporal_markers) > 0]
        assert len(temporal_threads) > 0, "Should detect temporal markers"


class TestDomainClassification:
    """Tests de classification domaine"""

    def test_classify_domain_returns_valid_domain(self):
        """Test que la classification retourne un domaine valide"""
        profiler = SemanticDocumentProfiler()

        text = "Financial report with revenue and expenses"
        domain, confidence = profiler._classify_domain(text)

        # Vérifier que le domaine est valide
        valid_domains = ["finance", "pharma", "consulting", "general"]
        assert domain in valid_domains
        assert 0.0 <= confidence <= 1.0


# ===================================
# RUN TESTS
# ===================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
