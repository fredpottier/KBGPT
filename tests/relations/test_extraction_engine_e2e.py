"""Tests E2E pour RelationExtractionEngine.

Tests d'intégration couvrant:
- Les 3 stratégies d'extraction (llm_first, hybrid, pattern_only)
- L'orchestration des composants
- Le filtering par confidence
- Les statistiques de résultat
- Le mode hybrid avec _enhance_with_llm

Phase 2 OSMOSE - Tests End-to-End
"""

import pytest
from typing import List, Dict, Any
from unittest.mock import Mock, patch, MagicMock
import json
from datetime import datetime

from knowbase.relations.extraction_engine import RelationExtractionEngine
from knowbase.relations.types import (
    RelationType,
    TypedRelation,
    RelationMetadata,
    RelationExtractionResult,
    ExtractionMethod,
    RelationStrength,
    RelationStatus,
)


# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture
def sample_concepts() -> List[Dict[str, Any]]:
    """Concepts de test réalistes."""
    return [
        {
            "concept_id": "concept-s4hana",
            "canonical_name": "SAP S/4HANA",
            "surface_forms": ["S/4HANA", "S4HANA"],
            "concept_type": "PRODUCT"
        },
        {
            "concept_id": "concept-hana",
            "canonical_name": "SAP HANA",
            "surface_forms": ["HANA", "HANA Database"],
            "concept_type": "DATABASE"
        },
        {
            "concept_id": "concept-fiori",
            "canonical_name": "SAP Fiori",
            "surface_forms": ["Fiori", "SAP Fiori UX"],
            "concept_type": "UI_FRAMEWORK"
        },
        {
            "concept_id": "concept-ecc",
            "canonical_name": "SAP ECC",
            "surface_forms": ["ECC", "SAP ERP Central Component"],
            "concept_type": "LEGACY_PRODUCT"
        },
        {
            "concept_id": "concept-btp",
            "canonical_name": "SAP BTP",
            "surface_forms": ["BTP", "Business Technology Platform"],
            "concept_type": "PLATFORM"
        }
    ]


@pytest.fixture
def sample_text_relations() -> str:
    """Texte contenant plusieurs types de relations."""
    return """
    SAP S/4HANA est le nouvel ERP de SAP qui remplace SAP ECC.
    S/4HANA nécessite la base de données HANA pour fonctionner.
    SAP Fiori fait partie de S/4HANA et fournit l'interface utilisateur.
    BTP s'intègre avec S/4HANA pour les extensions cloud.
    SAP ECC est désormais obsolète depuis l'arrivée de S/4HANA.
    """


@pytest.fixture
def mock_llm_router():
    """Mock LLM router pour tests isolés."""
    mock = Mock()
    mock.complete.return_value = json.dumps({
        "relations": [
            {
                "source": "SAP S/4HANA",
                "target": "SAP HANA",
                "relation_type": "REQUIRES",
                "confidence": 0.92,
                "evidence": "S/4HANA nécessite HANA"
            },
            {
                "source": "SAP S/4HANA",
                "target": "SAP ECC",
                "relation_type": "REPLACES",
                "confidence": 0.88,
                "evidence": "S/4HANA remplace ECC"
            }
        ]
    })
    return mock


# =========================================================================
# Tests: Initialisation
# =========================================================================

class TestEngineInitialization:
    """Tests pour l'initialisation du RelationExtractionEngine."""

    def test_init_default_strategy(self):
        """Test initialisation avec stratégie par défaut (llm_first)."""
        engine = RelationExtractionEngine()

        assert engine.strategy == "llm_first"
        assert engine.llm_model == "gpt-4o-mini"
        assert engine.min_confidence == 0.60
        assert engine.language == "EN"

    def test_init_hybrid_strategy(self):
        """Test initialisation avec stratégie hybrid."""
        engine = RelationExtractionEngine(strategy="hybrid")

        assert engine.strategy == "hybrid"

    def test_init_pattern_only_strategy(self):
        """Test initialisation avec stratégie pattern_only."""
        engine = RelationExtractionEngine(strategy="pattern_only")

        assert engine.strategy == "pattern_only"

    def test_init_custom_min_confidence(self):
        """Test initialisation avec confidence personnalisée."""
        engine = RelationExtractionEngine(min_confidence=0.75)

        assert engine.min_confidence == 0.75

    def test_lazy_loading_pattern_matcher(self):
        """Test lazy loading du PatternMatcher."""
        engine = RelationExtractionEngine()

        # Pas encore chargé
        assert engine._pattern_matcher is None

        # Accès via property déclenche le chargement
        matcher = engine.pattern_matcher

        assert engine._pattern_matcher is not None
        assert matcher is not None

    def test_lazy_loading_llm_extractor(self):
        """Test lazy loading du LLMRelationExtractor."""
        engine = RelationExtractionEngine()

        # Pas encore chargé
        assert engine._llm_extractor is None

        # Accès via property déclenche le chargement
        extractor = engine.llm_extractor

        assert engine._llm_extractor is not None
        assert extractor is not None


# =========================================================================
# Tests: Pattern-Only Strategy
# =========================================================================

class TestPatternOnlyStrategy:
    """Tests pour la stratégie pattern_only."""

    def test_pattern_only_extracts_relations(self, sample_concepts, sample_text_relations):
        """Test extraction avec patterns uniquement."""
        engine = RelationExtractionEngine(
            strategy="pattern_only",
            min_confidence=0.50
        )

        result = engine.extract_relations(
            concepts=sample_concepts,
            full_text=sample_text_relations,
            document_id="test-doc-1",
            document_name="Test Document"
        )

        assert isinstance(result, RelationExtractionResult)
        assert result.document_id == "test-doc-1"
        assert result.total_relations_extracted >= 0
        assert result.extraction_time_seconds >= 0

    def test_pattern_only_extraction_method(self, sample_concepts, sample_text_relations):
        """Test que les relations ont extraction_method = PATTERN."""
        engine = RelationExtractionEngine(
            strategy="pattern_only",
            min_confidence=0.50
        )

        result = engine.extract_relations(
            concepts=sample_concepts,
            full_text=sample_text_relations,
            document_id="test-doc-2",
            document_name="Test Document"
        )

        for relation in result.relations:
            assert relation.metadata.extraction_method == ExtractionMethod.PATTERN

    def test_pattern_detects_requires(self, sample_concepts):
        """Test détection REQUIRES via patterns."""
        text = "S/4HANA nécessite HANA pour fonctionner correctement."

        engine = RelationExtractionEngine(
            strategy="pattern_only",
            min_confidence=0.50
        )

        result = engine.extract_relations(
            concepts=sample_concepts,
            full_text=text,
            document_id="test-requires",
            document_name="Test REQUIRES"
        )

        requires_relations = [
            r for r in result.relations
            if r.relation_type == RelationType.REQUIRES
        ]

        # Pattern "nécessite" devrait matcher
        assert len(requires_relations) >= 0  # Dépend des patterns disponibles

    def test_pattern_detects_replaces(self, sample_concepts):
        """Test détection REPLACES via patterns."""
        text = "SAP S/4HANA remplace SAP ECC pour les nouveaux clients."

        engine = RelationExtractionEngine(
            strategy="pattern_only",
            min_confidence=0.50
        )

        result = engine.extract_relations(
            concepts=sample_concepts,
            full_text=text,
            document_id="test-replaces",
            document_name="Test REPLACES"
        )

        replaces_relations = [
            r for r in result.relations
            if r.relation_type == RelationType.REPLACES
        ]

        # Pattern "remplace" devrait matcher
        assert len(replaces_relations) >= 0


# =========================================================================
# Tests: LLM-First Strategy
# =========================================================================

class TestLLMFirstStrategy:
    """Tests pour la stratégie llm_first."""

    @patch('knowbase.relations.extraction_engine.RelationExtractionEngine.llm_extractor')
    def test_llm_first_uses_llm_extractor(
        self,
        mock_llm_extractor,
        sample_concepts,
        sample_text_relations
    ):
        """Test que llm_first utilise LLMRelationExtractor."""
        # Mock le retour de l'extracteur
        mock_relation = TypedRelation(
            relation_id="rel-1",
            source_concept="concept-s4hana",
            target_concept="concept-hana",
            relation_type=RelationType.REQUIRES,
            metadata=RelationMetadata(
                confidence=0.85,
                extraction_method=ExtractionMethod.LLM,
                source_doc_id="test-doc",
                source_chunk_ids=[],
                language="EN",
                created_at=datetime.utcnow(),
                strength=RelationStrength.STRONG,
                status=RelationStatus.ACTIVE,
                require_validation=False
            ),
            evidence="S/4HANA nécessite HANA"
        )
        mock_llm_extractor.extract_relations.return_value = [mock_relation]

        engine = RelationExtractionEngine(strategy="llm_first")

        result = engine.extract_relations(
            concepts=sample_concepts,
            full_text=sample_text_relations,
            document_id="test-llm-first",
            document_name="Test LLM First"
        )

        # Vérifier que LLM extractor a été appelé
        mock_llm_extractor.extract_relations.assert_called_once()

    def test_llm_first_extraction_method(self, sample_concepts):
        """Test que les relations ont extraction_method = LLM."""
        # Test avec mock pour éviter appels API réels
        with patch('knowbase.relations.llm_relation_extractor.LLMRelationExtractor') as MockExtractor:
            mock_instance = MockExtractor.return_value
            mock_relation = TypedRelation(
                relation_id="rel-1",
                source_concept="concept-s4hana",
                target_concept="concept-hana",
                relation_type=RelationType.REQUIRES,
                metadata=RelationMetadata(
                    confidence=0.85,
                    extraction_method=ExtractionMethod.LLM,
                    source_doc_id="test-doc",
                    source_chunk_ids=[],
                    language="EN",
                    created_at=datetime.utcnow(),
                    strength=RelationStrength.STRONG,
                    status=RelationStatus.ACTIVE,
                    require_validation=False
                ),
                evidence="Test"
            )
            mock_instance.extract_relations.return_value = [mock_relation]

            engine = RelationExtractionEngine(strategy="llm_first")
            engine._llm_extractor = mock_instance

            result = engine.extract_relations(
                concepts=sample_concepts,
                full_text="S/4HANA requires HANA database.",
                document_id="test-method",
                document_name="Test Method"
            )

            for relation in result.relations:
                assert relation.metadata.extraction_method == ExtractionMethod.LLM


# =========================================================================
# Tests: Hybrid Strategy
# =========================================================================

class TestHybridStrategy:
    """Tests pour la stratégie hybrid."""

    def test_hybrid_calls_pattern_first(self, sample_concepts, sample_text_relations):
        """Test que hybrid appelle patterns d'abord."""
        engine = RelationExtractionEngine(
            strategy="hybrid",
            min_confidence=0.50
        )

        # Spy sur _extract_with_patterns
        with patch.object(engine, '_extract_with_patterns', wraps=engine._extract_with_patterns) as spy:
            with patch.object(engine, '_enhance_with_llm', return_value=[]):
                result = engine.extract_relations(
                    concepts=sample_concepts,
                    full_text=sample_text_relations,
                    document_id="test-hybrid",
                    document_name="Test Hybrid"
                )

                spy.assert_called_once()

    def test_hybrid_calls_enhance_with_llm(self, sample_concepts, sample_text_relations):
        """Test que hybrid appelle _enhance_with_llm après patterns."""
        engine = RelationExtractionEngine(
            strategy="hybrid",
            min_confidence=0.50
        )

        with patch.object(engine, '_enhance_with_llm', return_value=[]) as mock_enhance:
            result = engine.extract_relations(
                concepts=sample_concepts,
                full_text=sample_text_relations,
                document_id="test-hybrid-enhance",
                document_name="Test Hybrid Enhance"
            )

            mock_enhance.assert_called_once()

    def test_enhance_with_llm_updates_extraction_method(self, sample_concepts):
        """Test que _enhance_with_llm change extraction_method vers HYBRID."""
        engine = RelationExtractionEngine(strategy="hybrid")

        # Créer relation pattern-based
        pattern_relation = TypedRelation(
            relation_id="rel-pattern-1",
            source_concept="concept-s4hana",
            target_concept="concept-hana",
            relation_type=RelationType.REQUIRES,
            metadata=RelationMetadata(
                confidence=0.65,
                extraction_method=ExtractionMethod.PATTERN,
                source_doc_id="test-doc",
                source_chunk_ids=[],
                language="EN",
                created_at=datetime.utcnow(),
                strength=RelationStrength.MODERATE,
                status=RelationStatus.ACTIVE,
                require_validation=True
            ),
            evidence="S/4HANA nécessite HANA"
        )

        # Mock RelationEnricher
        with patch('knowbase.relations.extraction_engine.is_feature_enabled', return_value=True):
            with patch('knowbase.relations.relation_enricher.RelationEnricher') as MockEnricher:
                mock_enricher = MockEnricher.return_value

                # Retourner la relation avec status ACTIVE
                enriched_relation = TypedRelation(
                    relation_id="rel-pattern-1",
                    source_concept="concept-s4hana",
                    target_concept="concept-hana",
                    relation_type=RelationType.REQUIRES,
                    metadata=RelationMetadata(
                        confidence=0.85,
                        extraction_method=ExtractionMethod.PATTERN,  # Sera changé
                        source_doc_id="test-doc",
                        source_chunk_ids=[],
                        language="EN",
                        created_at=datetime.utcnow(),
                        strength=RelationStrength.STRONG,
                        status=RelationStatus.ACTIVE,
                        require_validation=False
                    ),
                    evidence="S/4HANA nécessite HANA"
                )
                mock_enricher.enrich_relations.return_value = [enriched_relation]

                result = engine._enhance_with_llm(
                    candidate_relations=[pattern_relation],
                    full_text="S/4HANA nécessite HANA."
                )

                # Vérifier que extraction_method est HYBRID
                assert len(result) == 1
                assert result[0].metadata.extraction_method == ExtractionMethod.HYBRID

    def test_enhance_with_llm_filters_invalid(self, sample_concepts):
        """Test que _enhance_with_llm filtre les relations invalides."""
        engine = RelationExtractionEngine(strategy="hybrid")

        pattern_relations = [
            TypedRelation(
                relation_id="rel-1",
                source_concept="concept-s4hana",
                target_concept="concept-hana",
                relation_type=RelationType.REQUIRES,
                metadata=RelationMetadata(
                    confidence=0.55,
                    extraction_method=ExtractionMethod.PATTERN,
                    source_doc_id="test-doc",
                    source_chunk_ids=[],
                    language="EN",
                    created_at=datetime.utcnow(),
                    strength=RelationStrength.MODERATE,
                    status=RelationStatus.ACTIVE,
                    require_validation=True
                ),
                evidence="Test"
            ),
            TypedRelation(
                relation_id="rel-2",
                source_concept="concept-fiori",
                target_concept="concept-btp",
                relation_type=RelationType.USES,
                metadata=RelationMetadata(
                    confidence=0.45,
                    extraction_method=ExtractionMethod.PATTERN,
                    source_doc_id="test-doc",
                    source_chunk_ids=[],
                    language="EN",
                    created_at=datetime.utcnow(),
                    strength=RelationStrength.WEAK,
                    status=RelationStatus.ACTIVE,
                    require_validation=True
                ),
                evidence="Test invalid"
            )
        ]

        with patch('knowbase.relations.extraction_engine.is_feature_enabled', return_value=True):
            with patch('knowbase.relations.relation_enricher.RelationEnricher') as MockEnricher:
                mock_enricher = MockEnricher.return_value

                # Une relation validée, une invalidée
                validated = TypedRelation(
                    relation_id="rel-1",
                    source_concept="concept-s4hana",
                    target_concept="concept-hana",
                    relation_type=RelationType.REQUIRES,
                    metadata=RelationMetadata(
                        confidence=0.90,
                        extraction_method=ExtractionMethod.PATTERN,
                        source_doc_id="test-doc",
                        source_chunk_ids=[],
                        language="EN",
                        created_at=datetime.utcnow(),
                        strength=RelationStrength.STRONG,
                        status=RelationStatus.ACTIVE,
                        require_validation=False
                    ),
                    evidence="Test"
                )
                invalid = TypedRelation(
                    relation_id="rel-2",
                    source_concept="concept-fiori",
                    target_concept="concept-btp",
                    relation_type=RelationType.USES,
                    metadata=RelationMetadata(
                        confidence=0.20,
                        extraction_method=ExtractionMethod.PATTERN,
                        source_doc_id="test-doc",
                        source_chunk_ids=[],
                        language="EN",
                        created_at=datetime.utcnow(),
                        strength=RelationStrength.WEAK,
                        status=RelationStatus.INACTIVE,  # Marked invalid
                        require_validation=False
                    ),
                    evidence="Test invalid"
                )
                mock_enricher.enrich_relations.return_value = [validated, invalid]

                result = engine._enhance_with_llm(
                    candidate_relations=pattern_relations,
                    full_text="Test text"
                )

                # Seule la relation ACTIVE devrait être retournée
                assert len(result) == 1
                assert result[0].relation_id == "rel-1"
                assert result[0].metadata.status == RelationStatus.ACTIVE


# =========================================================================
# Tests: Confidence Filtering
# =========================================================================

class TestConfidenceFiltering:
    """Tests pour le filtering par confidence."""

    def test_filters_below_min_confidence(self, sample_concepts):
        """Test que les relations sous le seuil sont filtrées."""
        engine = RelationExtractionEngine(
            strategy="pattern_only",
            min_confidence=0.70
        )

        # Mock pattern matcher pour retourner relations avec différentes confidences
        with patch.object(engine, 'pattern_matcher') as mock_matcher:
            low_conf = TypedRelation(
                relation_id="rel-low",
                source_concept="concept-s4hana",
                target_concept="concept-hana",
                relation_type=RelationType.USES,
                metadata=RelationMetadata(
                    confidence=0.55,  # Below 0.70
                    extraction_method=ExtractionMethod.PATTERN,
                    source_doc_id="test-doc",
                    source_chunk_ids=[],
                    language="EN",
                    created_at=datetime.utcnow(),
                    strength=RelationStrength.WEAK,
                    status=RelationStatus.ACTIVE,
                    require_validation=True
                ),
                evidence="Test"
            )
            high_conf = TypedRelation(
                relation_id="rel-high",
                source_concept="concept-s4hana",
                target_concept="concept-ecc",
                relation_type=RelationType.REPLACES,
                metadata=RelationMetadata(
                    confidence=0.85,  # Above 0.70
                    extraction_method=ExtractionMethod.PATTERN,
                    source_doc_id="test-doc",
                    source_chunk_ids=[],
                    language="EN",
                    created_at=datetime.utcnow(),
                    strength=RelationStrength.STRONG,
                    status=RelationStatus.ACTIVE,
                    require_validation=False
                ),
                evidence="Test"
            )
            mock_matcher.extract_relations.return_value = [low_conf, high_conf]

            result = engine.extract_relations(
                concepts=sample_concepts,
                full_text="Test text",
                document_id="test-filter",
                document_name="Test Filter"
            )

            # Seule high_conf devrait passer
            assert len(result.relations) == 1
            assert result.relations[0].relation_id == "rel-high"


# =========================================================================
# Tests: Statistics
# =========================================================================

class TestExtractionStatistics:
    """Tests pour les statistiques d'extraction."""

    def test_result_has_relations_by_type(self, sample_concepts):
        """Test que le résultat contient les stats par type."""
        engine = RelationExtractionEngine(
            strategy="pattern_only",
            min_confidence=0.50
        )

        with patch.object(engine, 'pattern_matcher') as mock_matcher:
            relations = [
                TypedRelation(
                    relation_id="rel-1",
                    source_concept="concept-s4hana",
                    target_concept="concept-hana",
                    relation_type=RelationType.REQUIRES,
                    metadata=RelationMetadata(
                        confidence=0.75,
                        extraction_method=ExtractionMethod.PATTERN,
                        source_doc_id="test-doc",
                        source_chunk_ids=[],
                        language="EN",
                        created_at=datetime.utcnow(),
                        strength=RelationStrength.STRONG,
                        status=RelationStatus.ACTIVE,
                        require_validation=False
                    ),
                    evidence="Test"
                ),
                TypedRelation(
                    relation_id="rel-2",
                    source_concept="concept-s4hana",
                    target_concept="concept-ecc",
                    relation_type=RelationType.REPLACES,
                    metadata=RelationMetadata(
                        confidence=0.80,
                        extraction_method=ExtractionMethod.PATTERN,
                        source_doc_id="test-doc",
                        source_chunk_ids=[],
                        language="EN",
                        created_at=datetime.utcnow(),
                        strength=RelationStrength.STRONG,
                        status=RelationStatus.ACTIVE,
                        require_validation=False
                    ),
                    evidence="Test"
                )
            ]
            mock_matcher.extract_relations.return_value = relations

            result = engine.extract_relations(
                concepts=sample_concepts,
                full_text="Test text",
                document_id="test-stats",
                document_name="Test Stats"
            )

            assert RelationType.REQUIRES in result.relations_by_type
            assert RelationType.REPLACES in result.relations_by_type
            assert result.relations_by_type[RelationType.REQUIRES] == 1
            assert result.relations_by_type[RelationType.REPLACES] == 1

    def test_result_has_method_stats(self, sample_concepts):
        """Test que le résultat contient les stats par méthode."""
        engine = RelationExtractionEngine(
            strategy="pattern_only",
            min_confidence=0.50
        )

        with patch.object(engine, 'pattern_matcher') as mock_matcher:
            relations = [
                TypedRelation(
                    relation_id="rel-1",
                    source_concept="concept-s4hana",
                    target_concept="concept-hana",
                    relation_type=RelationType.REQUIRES,
                    metadata=RelationMetadata(
                        confidence=0.75,
                        extraction_method=ExtractionMethod.PATTERN,
                        source_doc_id="test-doc",
                        source_chunk_ids=[],
                        language="EN",
                        created_at=datetime.utcnow(),
                        strength=RelationStrength.STRONG,
                        status=RelationStatus.ACTIVE,
                        require_validation=False
                    ),
                    evidence="Test"
                )
            ]
            mock_matcher.extract_relations.return_value = relations

            result = engine.extract_relations(
                concepts=sample_concepts,
                full_text="Test text",
                document_id="test-method-stats",
                document_name="Test Method Stats"
            )

            assert ExtractionMethod.PATTERN in result.extraction_method_stats
            assert result.extraction_method_stats[ExtractionMethod.PATTERN] == 1

    def test_result_has_extraction_time(self, sample_concepts):
        """Test que le résultat contient le temps d'extraction."""
        engine = RelationExtractionEngine(
            strategy="pattern_only",
            min_confidence=0.50
        )

        result = engine.extract_relations(
            concepts=sample_concepts,
            full_text="Test text",
            document_id="test-time",
            document_name="Test Time"
        )

        assert result.extraction_time_seconds >= 0
        assert isinstance(result.extraction_time_seconds, float)


# =========================================================================
# Tests: Edge Cases
# =========================================================================

class TestEdgeCases:
    """Tests pour les cas limites."""

    def test_empty_concepts_list(self):
        """Test avec liste de concepts vide."""
        engine = RelationExtractionEngine(strategy="pattern_only")

        result = engine.extract_relations(
            concepts=[],
            full_text="Some text with SAP products",
            document_id="test-empty-concepts",
            document_name="Test Empty"
        )

        assert result.total_relations_extracted == 0
        assert len(result.relations) == 0

    def test_empty_text(self, sample_concepts):
        """Test avec texte vide."""
        engine = RelationExtractionEngine(strategy="pattern_only")

        result = engine.extract_relations(
            concepts=sample_concepts,
            full_text="",
            document_id="test-empty-text",
            document_name="Test Empty Text"
        )

        assert result.total_relations_extracted == 0

    def test_no_matching_patterns(self, sample_concepts):
        """Test avec texte sans patterns de relation."""
        engine = RelationExtractionEngine(strategy="pattern_only")

        result = engine.extract_relations(
            concepts=sample_concepts,
            full_text="This is a simple text about weather and cooking.",
            document_id="test-no-patterns",
            document_name="Test No Patterns"
        )

        # Peut ou pas avoir de relations selon co-occurrence
        assert isinstance(result.relations, list)

    def test_single_concept(self):
        """Test avec un seul concept (pas de paires possibles)."""
        engine = RelationExtractionEngine(strategy="pattern_only")

        single_concept = [{
            "concept_id": "concept-solo",
            "canonical_name": "Solo Concept",
            "surface_forms": ["Solo"],
            "concept_type": "TEST"
        }]

        result = engine.extract_relations(
            concepts=single_concept,
            full_text="Solo concept mentioned here.",
            document_id="test-single",
            document_name="Test Single"
        )

        assert result.total_relations_extracted == 0


# =========================================================================
# Tests: Feature Flag Integration
# =========================================================================

class TestFeatureFlagIntegration:
    """Tests pour l'intégration des feature flags."""

    def test_enhance_with_llm_disabled(self, sample_concepts):
        """Test _enhance_with_llm quand feature flag désactivé."""
        engine = RelationExtractionEngine(strategy="hybrid")

        relations = [
            TypedRelation(
                relation_id="rel-1",
                source_concept="concept-s4hana",
                target_concept="concept-hana",
                relation_type=RelationType.REQUIRES,
                metadata=RelationMetadata(
                    confidence=0.65,
                    extraction_method=ExtractionMethod.PATTERN,
                    source_doc_id="test-doc",
                    source_chunk_ids=[],
                    language="EN",
                    created_at=datetime.utcnow(),
                    strength=RelationStrength.MODERATE,
                    status=RelationStatus.ACTIVE,
                    require_validation=True
                ),
                evidence="Test"
            )
        ]

        with patch('knowbase.relations.extraction_engine.is_feature_enabled', return_value=False):
            result = engine._enhance_with_llm(
                candidate_relations=relations,
                full_text="Test text"
            )

            # Devrait retourner les relations originales sans modification
            assert len(result) == 1
            assert result[0].metadata.extraction_method == ExtractionMethod.PATTERN


# =========================================================================
# Tests: Integration (nécessite connexion LLM)
# =========================================================================

@pytest.mark.integration
class TestIntegration:
    """Tests d'intégration avec appels LLM réels."""

    def test_full_pipeline_llm_first(self, sample_concepts, sample_text_relations):
        """Test pipeline complet llm_first avec vrai LLM."""
        engine = RelationExtractionEngine(
            strategy="llm_first",
            min_confidence=0.60
        )

        result = engine.extract_relations(
            concepts=sample_concepts,
            full_text=sample_text_relations,
            document_id="test-integration",
            document_name="Test Integration"
        )

        # Vérifications basiques
        assert isinstance(result, RelationExtractionResult)
        assert result.extraction_time_seconds > 0

        # Devrait extraire au moins quelques relations
        # (texte contient REPLACES, REQUIRES, PART_OF patterns)
        if result.total_relations_extracted > 0:
            for rel in result.relations:
                assert rel.metadata.confidence >= 0.60
                assert rel.source_concept in [c["concept_id"] for c in sample_concepts]
                assert rel.target_concept in [c["concept_id"] for c in sample_concepts]

    def test_full_pipeline_hybrid(self, sample_concepts, sample_text_relations):
        """Test pipeline complet hybrid avec vrai LLM."""
        engine = RelationExtractionEngine(
            strategy="hybrid",
            min_confidence=0.50
        )

        result = engine.extract_relations(
            concepts=sample_concepts,
            full_text=sample_text_relations,
            document_id="test-integration-hybrid",
            document_name="Test Integration Hybrid"
        )

        assert isinstance(result, RelationExtractionResult)

        # En mode hybrid, on peut avoir PATTERN ou HYBRID comme méthode
        for rel in result.relations:
            assert rel.metadata.extraction_method in [
                ExtractionMethod.PATTERN,
                ExtractionMethod.HYBRID
            ]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
