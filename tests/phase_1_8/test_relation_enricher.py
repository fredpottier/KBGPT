"""
Tests Phase 1.8.3 - LLM Smart Relation Enrichment

Valide l'enrichissement des relations en zone grise via LLM.
Objectif: Precision 60% → 80%, Rappel 50% → 70%
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
import json
from datetime import datetime

from knowbase.relations.types import (
    TypedRelation,
    RelationType,
    RelationMetadata,
    ExtractionMethod,
    RelationStrength,
    RelationStatus
)
from knowbase.relations.relation_enricher import (
    RelationEnricher,
    enrich_relations_if_enabled,
    RELATION_ENRICHMENT_SYSTEM_PROMPT,
    RELATION_ENRICHMENT_USER_PROMPT
)


# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture
def sample_relations():
    """Create sample relations for testing."""
    relations = []

    # Relation 1: Gray zone (0.55 confidence)
    rel1 = TypedRelation(
        relation_id="rel-1",
        source_concept="concept-sap-s4hana",
        target_concept="concept-hana",
        relation_type=RelationType.REQUIRES,
        metadata=RelationMetadata(
            confidence=0.55,
            extraction_method=ExtractionMethod.PATTERN,
            source_doc_id="doc-1",
            source_chunk_ids=["chunk-1"],
            language="EN",
            created_at=datetime.utcnow(),
            strength=RelationStrength.MODERATE,
            status=RelationStatus.ACTIVE,
            require_validation=True
        ),
        evidence="S/4HANA requires HANA database"
    )
    relations.append(rel1)

    # Relation 2: Gray zone (0.45 confidence)
    rel2 = TypedRelation(
        relation_id="rel-2",
        source_concept="concept-btp",
        target_concept="concept-fiori",
        relation_type=RelationType.INTEGRATES_WITH,
        metadata=RelationMetadata(
            confidence=0.45,
            extraction_method=ExtractionMethod.PATTERN,
            source_doc_id="doc-1",
            source_chunk_ids=["chunk-2"],
            language="EN",
            created_at=datetime.utcnow(),
            strength=RelationStrength.WEAK,
            status=RelationStatus.ACTIVE,
            require_validation=True
        ),
        evidence="BTP integrates with Fiori"
    )
    relations.append(rel2)

    # Relation 3: High confidence (0.85 - not in gray zone)
    rel3 = TypedRelation(
        relation_id="rel-3",
        source_concept="concept-s4-cloud",
        target_concept="concept-s4",
        relation_type=RelationType.VERSION_OF,
        metadata=RelationMetadata(
            confidence=0.85,
            extraction_method=ExtractionMethod.LLM,
            source_doc_id="doc-1",
            source_chunk_ids=["chunk-3"],
            language="EN",
            created_at=datetime.utcnow(),
            strength=RelationStrength.STRONG,
            status=RelationStatus.ACTIVE,
            require_validation=False
        ),
        evidence="S/4HANA Cloud is a cloud version of S/4HANA"
    )
    relations.append(rel3)

    return relations


@pytest.fixture
def mock_llm_router():
    """Mock LLM router."""
    mock = Mock()
    return mock


@pytest.fixture
def enricher(mock_llm_router):
    """Create enricher with mocked LLM router."""
    with patch("knowbase.relations.relation_enricher.is_feature_enabled") as mock_flag:
        mock_flag.return_value = True
        return RelationEnricher(
            llm_router=mock_llm_router,
            batch_size=10,
            max_batches=5
        )


# =========================================================================
# Test: Gray Zone Detection
# =========================================================================

class TestGrayZoneDetection:
    """Tests for gray zone filtering."""

    def test_is_in_gray_zone_true(self, enricher, sample_relations):
        """Relation with confidence 0.55 is in gray zone."""
        assert enricher.is_in_gray_zone(sample_relations[0]) is True

    def test_is_in_gray_zone_true_boundary_low(self, enricher, sample_relations):
        """Relation with confidence 0.45 is in gray zone."""
        assert enricher.is_in_gray_zone(sample_relations[1]) is True

    def test_is_in_gray_zone_false_high_confidence(self, enricher, sample_relations):
        """Relation with confidence 0.85 is NOT in gray zone."""
        assert enricher.is_in_gray_zone(sample_relations[2]) is False

    def test_filter_gray_zone_relations(self, enricher, sample_relations):
        """Filter returns only gray zone relations."""
        gray_zone = enricher.filter_gray_zone_relations(sample_relations)

        assert len(gray_zone) == 2
        assert all(enricher.is_in_gray_zone(r) for r in gray_zone)

    def test_filter_gray_zone_empty_input(self, enricher):
        """Filter handles empty input."""
        result = enricher.filter_gray_zone_relations([])
        assert result == []


# =========================================================================
# Test: Batch Creation
# =========================================================================

class TestBatchCreation:
    """Tests for batch creation."""

    def test_creates_single_batch_small_input(self, enricher, sample_relations):
        """Small input creates single batch."""
        batches = enricher._create_batches(sample_relations)
        assert len(batches) == 1
        assert len(batches[0]) == 3

    def test_creates_multiple_batches(self, enricher):
        """Large input creates multiple batches."""
        # Create 25 relations
        relations = []
        for i in range(25):
            rel = TypedRelation(
                relation_id=f"rel-{i}",
                source_concept=f"src-{i}",
                target_concept=f"tgt-{i}",
                relation_type=RelationType.USES,
                metadata=RelationMetadata(
                    confidence=0.5,
                    extraction_method=ExtractionMethod.PATTERN,
                    source_doc_id="doc-1",
                    source_chunk_ids=[],
                    language="EN",
                    created_at=datetime.utcnow(),
                    strength=RelationStrength.MODERATE,
                    status=RelationStatus.ACTIVE,
                    require_validation=True
                ),
                evidence="test"
            )
            relations.append(rel)

        enricher.batch_size = 10
        batches = enricher._create_batches(relations)

        assert len(batches) == 3
        assert len(batches[0]) == 10
        assert len(batches[1]) == 10
        assert len(batches[2]) == 5


# =========================================================================
# Test: LLM Enrichment
# =========================================================================

class TestLLMEnrichment:
    """Tests for LLM-based enrichment."""

    def test_enrich_updates_confidence(self, enricher, mock_llm_router, sample_relations):
        """Enrichment updates relation confidence."""
        # Mock LLM response
        mock_llm_router.complete.return_value = json.dumps({
            "validations": [
                {
                    "relation_index": 0,
                    "verdict": "VALID",
                    "confidence": 0.92,
                    "reasoning": "Clear dependency relationship"
                },
                {
                    "relation_index": 1,
                    "verdict": "VALID",
                    "confidence": 0.78,
                    "reasoning": "Integration confirmed"
                }
            ]
        })

        # Get gray zone relations
        gray_zone = [r for r in sample_relations if enricher.is_in_gray_zone(r)]

        with patch("knowbase.relations.relation_enricher.is_feature_enabled") as mock_flag:
            mock_flag.return_value = True
            enriched = enricher.enrich_relations(gray_zone)

        assert enriched[0].metadata.confidence == 0.92
        assert enriched[1].metadata.confidence == 0.78

    def test_enrich_marks_invalid_relations(self, enricher, mock_llm_router, sample_relations):
        """Enrichment marks invalid relations as inactive."""
        mock_llm_router.complete.return_value = json.dumps({
            "validations": [
                {
                    "relation_index": 0,
                    "verdict": "INVALID",
                    "confidence": 0.1,
                    "reasoning": "No evidence supports this relation"
                }
            ]
        })

        gray_zone = [sample_relations[0]]

        with patch("knowbase.relations.relation_enricher.is_feature_enabled") as mock_flag:
            mock_flag.return_value = True
            enriched = enricher.enrich_relations(gray_zone)

        assert enriched[0].metadata.status == RelationStatus.INACTIVE

    def test_enrich_handles_uncertain_verdict(self, enricher, mock_llm_router, sample_relations):
        """Enrichment keeps require_validation for uncertain."""
        mock_llm_router.complete.return_value = json.dumps({
            "validations": [
                {
                    "relation_index": 0,
                    "verdict": "UNCERTAIN",
                    "confidence": 0.5,
                    "reasoning": "Ambiguous context"
                }
            ]
        })

        gray_zone = [sample_relations[0]]

        with patch("knowbase.relations.relation_enricher.is_feature_enabled") as mock_flag:
            mock_flag.return_value = True
            enriched = enricher.enrich_relations(gray_zone)

        assert enriched[0].metadata.require_validation is True

    def test_enrich_stores_reasoning(self, enricher, mock_llm_router, sample_relations):
        """Enrichment stores LLM reasoning in context."""
        mock_llm_router.complete.return_value = json.dumps({
            "validations": [
                {
                    "relation_index": 0,
                    "verdict": "VALID",
                    "confidence": 0.9,
                    "reasoning": "Test reasoning"
                }
            ]
        })

        gray_zone = [sample_relations[0]]

        with patch("knowbase.relations.relation_enricher.is_feature_enabled") as mock_flag:
            mock_flag.return_value = True
            enriched = enricher.enrich_relations(gray_zone)

        context = json.loads(enriched[0].context)
        assert "llm_validation" in context
        assert context["llm_validation"]["reasoning"] == "Test reasoning"


# =========================================================================
# Test: Feature Flag Integration
# =========================================================================

class TestFeatureFlagIntegration:
    """Tests for feature flag integration."""

    def test_enrichment_skipped_when_disabled(self, mock_llm_router, sample_relations):
        """Enrichment returns original relations when disabled."""
        with patch("knowbase.relations.relation_enricher.is_feature_enabled") as mock_flag:
            mock_flag.return_value = False
            enricher = RelationEnricher(llm_router=mock_llm_router)
            enriched = enricher.enrich_relations(sample_relations)

        # Should return original relations unchanged
        assert enriched == sample_relations
        mock_llm_router.complete.assert_not_called()

    def test_convenience_function_checks_flag(self, sample_relations):
        """enrich_relations_if_enabled checks feature flag."""
        with patch("knowbase.relations.relation_enricher.is_feature_enabled") as mock_flag:
            mock_flag.return_value = False
            result = enrich_relations_if_enabled(sample_relations)

        assert result == sample_relations


# =========================================================================
# Test: Batch Processing
# =========================================================================

class TestBatchProcessing:
    """Tests for batch processing limits."""

    def test_respects_max_batches_limit(self, enricher, mock_llm_router):
        """Processing stops at max_batches."""
        # Create many relations
        relations = []
        for i in range(100):
            rel = TypedRelation(
                relation_id=f"rel-{i}",
                source_concept=f"src-{i}",
                target_concept=f"tgt-{i}",
                relation_type=RelationType.USES,
                metadata=RelationMetadata(
                    confidence=0.5,
                    extraction_method=ExtractionMethod.PATTERN,
                    source_doc_id="doc-1",
                    source_chunk_ids=[],
                    language="EN",
                    created_at=datetime.utcnow(),
                    strength=RelationStrength.MODERATE,
                    status=RelationStatus.ACTIVE,
                    require_validation=True
                ),
                evidence="test"
            )
            relations.append(rel)

        enricher.batch_size = 10
        enricher.max_batches = 3  # Should only process 30 relations

        mock_llm_router.complete.return_value = json.dumps({"validations": []})

        with patch("knowbase.relations.relation_enricher.is_feature_enabled") as mock_flag:
            mock_flag.return_value = True
            enricher.enrich_relations(relations)

        # Should only call LLM 3 times (max_batches)
        assert mock_llm_router.complete.call_count == 3


# =========================================================================
# Test: Error Handling
# =========================================================================

class TestErrorHandling:
    """Tests for error handling."""

    def test_handles_json_parse_error(self, enricher, mock_llm_router, sample_relations):
        """Handles invalid JSON from LLM."""
        mock_llm_router.complete.return_value = "invalid json {"

        gray_zone = [sample_relations[0]]

        with patch("knowbase.relations.relation_enricher.is_feature_enabled") as mock_flag:
            mock_flag.return_value = True
            enriched = enricher.enrich_relations(gray_zone)

        # Should return original relations on error
        assert len(enriched) == 1
        assert enriched[0].relation_id == gray_zone[0].relation_id

    def test_handles_llm_error(self, enricher, mock_llm_router, sample_relations):
        """Handles LLM call errors."""
        mock_llm_router.complete.side_effect = Exception("API Error")

        gray_zone = [sample_relations[0]]

        with patch("knowbase.relations.relation_enricher.is_feature_enabled") as mock_flag:
            mock_flag.return_value = True
            enriched = enricher.enrich_relations(gray_zone)

        # Should return original relations on error
        assert len(enriched) == 1


# =========================================================================
# Test: Statistics
# =========================================================================

class TestStatistics:
    """Tests for enrichment statistics."""

    def test_get_enrichment_stats(self, enricher, sample_relations):
        """Statistics calculation works correctly."""
        # Create modified relations
        enriched = []
        for rel in sample_relations[:2]:
            new_rel = TypedRelation(
                relation_id=rel.relation_id,
                source_concept=rel.source_concept,
                target_concept=rel.target_concept,
                relation_type=rel.relation_type,
                metadata=RelationMetadata(
                    confidence=0.9,  # Improved
                    extraction_method=rel.metadata.extraction_method,
                    source_doc_id=rel.metadata.source_doc_id,
                    source_chunk_ids=rel.metadata.source_chunk_ids,
                    language=rel.metadata.language,
                    created_at=rel.metadata.created_at,
                    strength=rel.metadata.strength,
                    status=RelationStatus.ACTIVE,
                    require_validation=False
                ),
                evidence=rel.evidence
            )
            enriched.append(new_rel)

        stats = enricher.get_enrichment_stats(sample_relations[:2], enriched)

        assert stats["total_original"] == 2
        assert stats["total_enriched"] == 2
        assert stats["validated"] == 2
        assert stats["confidence_improved"] == 2

    def test_stats_handles_empty_input(self, enricher):
        """Statistics handles empty input."""
        stats = enricher.get_enrichment_stats([], [])

        assert stats["total_original"] == 0
        assert stats["total_enriched"] == 0


# =========================================================================
# Test: Prompt Formatting
# =========================================================================

class TestPromptFormatting:
    """Tests for prompt formatting."""

    def test_format_relations_for_prompt(self, enricher, sample_relations):
        """Relations are correctly formatted for prompt."""
        gray_zone = [sample_relations[0]]

        formatted = enricher._format_relations_for_prompt(gray_zone)

        assert "0." in formatted
        assert "REQUIRES" in formatted
        assert "concept-sap-s4hana" in formatted
        assert "concept-hana" in formatted

    def test_format_with_concepts_map(self, enricher, sample_relations):
        """Format uses concept names from map."""
        gray_zone = [sample_relations[0]]

        concepts_map = {
            "concept-sap-s4hana": {"canonical_name": "SAP S/4HANA"},
            "concept-hana": {"canonical_name": "SAP HANA"}
        }

        formatted = enricher._format_relations_for_prompt(gray_zone, concepts_map)

        assert "SAP S/4HANA" in formatted
        assert "SAP HANA" in formatted


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
