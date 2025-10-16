"""
🌊 OSMOSE Semantic Intelligence - Tests Intégration Profiler

Tests d'intégration avec documents réels
"""

import pytest
import asyncio
from pathlib import Path
from knowbase.semantic.profiler import SemanticDocumentProfiler


FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestProfilerIntegration:
    """Tests d'intégration avec documents réels"""

    @pytest.mark.asyncio
    async def test_profile_simple_document(self):
        """Test profiling document simple"""
        profiler = SemanticDocumentProfiler()

        doc_path = FIXTURES_DIR / "simple_doc.txt"
        text = doc_path.read_text()

        profile = await profiler.profile_document(
            document_id="simple_001",
            document_path=str(doc_path),
            tenant_id="test_tenant",
            text_content=text
        )

        # Document simple → complexité basse
        assert profile.overall_complexity < 0.5, f"Expected low complexity, got {profile.overall_complexity}"
        assert profile.domain in ["finance", "pharma", "consulting", "general"]

        print(f"\n[SIMPLE DOC]")
        print(f"  Complexity: {profile.overall_complexity:.2f}")
        print(f"  Domain: {profile.domain} ({profile.domain_confidence:.2f})")
        print(f"  Zones: {len(profile.complexity_zones)}")
        print(f"  Narratives: {len(profile.narrative_threads)}")

    @pytest.mark.asyncio
    async def test_profile_finance_document(self):
        """Test profiling document finance (complexité moyenne)"""
        profiler = SemanticDocumentProfiler()

        doc_path = FIXTURES_DIR / "finance_medium.txt"
        text = doc_path.read_text()

        profile = await profiler.profile_document(
            document_id="finance_001",
            document_path=str(doc_path),
            tenant_id="test_tenant",
            text_content=text
        )

        # Document financier → complexité moyenne
        assert 0.3 <= profile.overall_complexity <= 0.8
        # Peut être classé finance ou general
        assert profile.domain in ["finance", "general"]

        # Au moins une zone de complexité détectée
        assert len(profile.complexity_zones) > 0

        print(f"\n[FINANCE DOC]")
        print(f"  Complexity: {profile.overall_complexity:.2f}")
        print(f"  Domain: {profile.domain} ({profile.domain_confidence:.2f})")
        print(f"  Zones: {len(profile.complexity_zones)}")
        if profile.complexity_zones:
            print(f"  First zone: {profile.complexity_zones[0].complexity_level}")
            print(f"  Key concepts: {profile.complexity_zones[0].key_concepts[:3]}")

    @pytest.mark.asyncio
    async def test_profile_crr_evolution(self):
        """Test profiling CRR Evolution (narratives + temporal markers)"""
        profiler = SemanticDocumentProfiler()

        doc_path = FIXTURES_DIR / "crr_evolution.txt"
        text = doc_path.read_text()

        profile = await profiler.profile_document(
            document_id="crr_001",
            document_path=str(doc_path),
            tenant_id="test_tenant",
            text_content=text
        )

        # Document avec narratives → devrait détecter des threads
        assert len(profile.narrative_threads) > 0, "Should detect narrative threads in CRR evolution"

        # Vérifier présence de markers temporels
        has_temporal = any(len(t.temporal_markers) > 0 for t in profile.narrative_threads)
        assert has_temporal, "Should detect temporal markers (revised, updated, superseded)"

        # Vérifier présence de causal links
        has_causal = any(len(t.causal_links) > 0 for t in profile.narrative_threads)
        assert has_causal, "Should detect causal links (because, therefore)"

        print(f"\n[CRR EVOLUTION DOC]")
        print(f"  Complexity: {profile.overall_complexity:.2f}")
        print(f"  Domain: {profile.domain} ({profile.domain_confidence:.2f})")
        print(f"  Zones: {len(profile.complexity_zones)}")
        print(f"  Narratives: {len(profile.narrative_threads)}")

        for i, thread in enumerate(profile.narrative_threads):
            print(f"  Thread {i+1}: {thread.description}")
            print(f"    - Confidence: {thread.confidence:.2f}")
            print(f"    - Causal links: {thread.causal_links}")
            print(f"    - Temporal markers: {thread.temporal_markers}")


class TestProfilerPerformance:
    """Tests de performance"""

    @pytest.mark.asyncio
    async def test_profile_multiple_documents(self):
        """Test profiling de plusieurs documents"""
        profiler = SemanticDocumentProfiler()

        fixtures = [
            "simple_doc.txt",
            "finance_medium.txt",
            "crr_evolution.txt"
        ]

        profiles = []
        for fixture in fixtures:
            doc_path = FIXTURES_DIR / fixture
            if not doc_path.exists():
                continue

            text = doc_path.read_text()
            profile = await profiler.profile_document(
                document_id=f"test_{fixture}",
                document_path=str(doc_path),
                tenant_id="test_tenant",
                text_content=text
            )
            profiles.append(profile)

        # Vérifier qu'on a traité tous les documents
        assert len(profiles) == len(fixtures)

        # Vérifier variation de complexité
        complexities = [p.overall_complexity for p in profiles]
        assert min(complexities) < max(complexities), "Should have complexity variation"

        print(f"\n[BATCH PROFILING]")
        print(f"  Documents processed: {len(profiles)}")
        print(f"  Complexity range: {min(complexities):.2f} - {max(complexities):.2f}")


# ===================================
# RUN TESTS
# ===================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
