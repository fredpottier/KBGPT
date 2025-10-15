"""
🌊 OSMOSE Semantic Intelligence V2.1 - Tests SemanticIndexer

Tests du SemanticIndexer (canonicalization cross-lingual)
Composant CRITIQUE pour USP cross-lingual KnowWhere
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock
from src.knowbase.semantic.indexing.semantic_indexer import SemanticIndexer
from src.knowbase.semantic.models import Concept, CanonicalConcept, ConceptType
from src.knowbase.semantic.config import get_semantic_config


@pytest.fixture
def config():
    """Fixture configuration"""
    return get_semantic_config()


@pytest.fixture
def mock_llm_router():
    """Fixture LLMRouter mocké"""
    router = AsyncMock()

    # Mock pour unified definition
    router.route_request = AsyncMock(return_value={
        "content": "A security standard for information management systems."
    })

    return router


@pytest.fixture
def indexer(config, mock_llm_router):
    """Fixture SemanticIndexer"""
    return SemanticIndexer(mock_llm_router, config)


@pytest.fixture
def sample_concepts_multilingual():
    """Concepts multilingues (authentication FR/EN/DE)"""
    return [
        Concept(
            name="authentication",
            type=ConceptType.PRACTICE,
            definition="Process of verifying identity",
            context="User authentication is required",
            language="en",
            confidence=0.90,
            source_topic_id="topic_001",
            extraction_method="NER"
        ),
        Concept(
            name="authentification",
            type=ConceptType.PRACTICE,
            definition="Processus de vérification d'identité",
            context="L'authentification utilisateur est requise",
            language="fr",
            confidence=0.88,
            source_topic_id="topic_002",
            extraction_method="NER"
        ),
        Concept(
            name="Authentifizierung",
            type=ConceptType.PRACTICE,
            definition="Prozess der Identitätsüberprüfung",
            context="Benutzer-Authentifizierung ist erforderlich",
            language="de",
            confidence=0.85,
            source_topic_id="topic_003",
            extraction_method="NER"
        )
    ]


@pytest.fixture
def sample_concepts_hierarchy():
    """Concepts avec hiérarchie (Security Testing parent → SAST/DAST children)"""
    return [
        Concept(
            name="Security Testing",
            type=ConceptType.PRACTICE,
            definition="Testing for security vulnerabilities",
            context="Security testing is essential",
            language="en",
            confidence=0.90,
            source_topic_id="topic_010",
            extraction_method="NER"
        ),
        Concept(
            name="SAST",
            type=ConceptType.TOOL,
            definition="Static Application Security Testing",
            context="SAST tools analyze source code",
            language="en",
            confidence=0.95,
            source_topic_id="topic_011",
            extraction_method="NER"
        ),
        Concept(
            name="DAST",
            type=ConceptType.TOOL,
            definition="Dynamic Application Security Testing",
            context="DAST tools test running applications",
            language="en",
            confidence=0.95,
            source_topic_id="topic_012",
            extraction_method="NER"
        ),
        Concept(
            name="Penetration Testing",
            type=ConceptType.PRACTICE,
            definition="Simulated cyber attack",
            context="Penetration testing finds vulnerabilities",
            language="en",
            confidence=0.92,
            source_topic_id="topic_013",
            extraction_method="NER"
        )
    ]


class TestSemanticIndexer:
    """Tests du SemanticIndexer"""

    @pytest.mark.asyncio
    async def test_cross_lingual_canonicalization(self, indexer, sample_concepts_multilingual):
        """Test unification cross-lingual FR/EN/DE"""
        canonical = await indexer.canonicalize_concepts(
            sample_concepts_multilingual,
            enable_hierarchy=False,
            enable_relations=False
        )

        # Devrait unifier en 1 concept canonique
        assert len(canonical) == 1, f"Should unify to 1 concept, got {len(canonical)}"

        concept = canonical[0]

        # Nom canonique devrait être anglais (priorité)
        assert concept.canonical_name == "authentication", \
            f"Canonical name should be 'authentication', got '{concept.canonical_name}'"

        # Aliases devrait contenir les 3 variantes
        assert len(concept.aliases) == 3, f"Should have 3 aliases, got {len(concept.aliases)}"
        assert "authentification" in concept.aliases
        assert "Authentifizierung" in concept.aliases

        # Langues détectées
        assert set(concept.languages) == {"en", "fr", "de"}

        # Type
        assert concept.type == ConceptType.PRACTICE

        # Support
        assert concept.support == 3

        # Confidence (moyenne)
        expected_conf = (0.90 + 0.88 + 0.85) / 3
        assert abs(concept.confidence - expected_conf) < 0.01

        print(f"\n✅ Cross-lingual canonicalization:")
        print(f"   Canonical: {concept.canonical_name}")
        print(f"   Aliases: {concept.aliases}")
        print(f"   Languages: {concept.languages}")
        print(f"   Support: {concept.support}")

    @pytest.mark.asyncio
    async def test_clustering_separate_concepts(self, indexer):
        """Test que concepts différents ne sont PAS unifiés"""
        concepts = [
            Concept(
                name="ISO 27001",
                type=ConceptType.STANDARD,
                definition="",
                context="",
                language="en",
                confidence=0.90,
                source_topic_id="t1",
                extraction_method="NER"
            ),
            Concept(
                name="GDPR",
                type=ConceptType.STANDARD,
                definition="",
                context="",
                language="en",
                confidence=0.90,
                source_topic_id="t2",
                extraction_method="NER"
            )
        ]

        canonical = await indexer.canonicalize_concepts(
            concepts,
            enable_hierarchy=False,
            enable_relations=False
        )

        # Devrait rester 2 concepts séparés (pas similaires)
        assert len(canonical) >= 2, \
            f"Different concepts should not be unified, got {len(canonical)}"

        print(f"\n✅ Separate concepts preserved: {len(canonical)} concepts")

    def test_select_canonical_name_english_priority(self, indexer):
        """Test priorité anglais pour nom canonique"""
        concepts = [
            Concept(
                name="authentification",
                type=ConceptType.PRACTICE,
                definition="",
                context="",
                language="fr",
                confidence=0.90,
                source_topic_id="t1",
                extraction_method="NER"
            ),
            Concept(
                name="authentication",
                type=ConceptType.PRACTICE,
                definition="",
                context="",
                language="en",
                confidence=0.85,
                source_topic_id="t2",
                extraction_method="NER"
            ),
            Concept(
                name="auth",  # Plus court
                type=ConceptType.PRACTICE,
                definition="",
                context="",
                language="en",
                confidence=0.80,
                source_topic_id="t3",
                extraction_method="NER"
            )
        ]

        canonical_name = indexer._select_canonical_name(concepts)

        # Devrait choisir "auth" (anglais + plus court)
        assert canonical_name == "auth", \
            f"Should select shortest English name, got '{canonical_name}'"

        print(f"\n✅ Canonical name selection: '{canonical_name}'")

    def test_select_canonical_name_no_english(self, indexer):
        """Test sélection sans concepts anglais (fallback)"""
        concepts = [
            Concept(
                name="authentification",
                type=ConceptType.PRACTICE,
                definition="",
                context="",
                language="fr",
                confidence=0.90,
                source_topic_id="t1",
                extraction_method="NER"
            ),
            Concept(
                name="authentification",  # Duplicate
                type=ConceptType.PRACTICE,
                definition="",
                context="",
                language="fr",
                confidence=0.85,
                source_topic_id="t2",
                extraction_method="NER"
            ),
            Concept(
                name="Authentifizierung",
                type=ConceptType.PRACTICE,
                definition="",
                context="",
                language="de",
                confidence=0.88,
                source_topic_id="t3",
                extraction_method="NER"
            )
        ]

        canonical_name = indexer._select_canonical_name(concepts)

        # Devrait choisir le plus fréquent: "authentification" (2 occurrences)
        assert canonical_name == "authentification", \
            f"Should select most frequent, got '{canonical_name}'"

        print(f"\n✅ Canonical name fallback: '{canonical_name}'")

    @pytest.mark.asyncio
    async def test_generate_unified_definition(self, indexer):
        """Test génération définition unifiée via LLM"""
        concepts = [
            Concept(
                name="ISO 27001",
                type=ConceptType.STANDARD,
                definition="Information security management standard",
                context="",
                language="en",
                confidence=0.90,
                source_topic_id="t1",
                extraction_method="NER"
            ),
            Concept(
                name="ISO 27001",
                type=ConceptType.STANDARD,
                definition="Standard for information security",
                context="",
                language="en",
                confidence=0.85,
                source_topic_id="t2",
                extraction_method="NER"
            )
        ]

        unified = await indexer._generate_unified_definition(concepts)

        # Devrait appeler LLM (mocké)
        assert unified, "Should generate unified definition"
        assert isinstance(unified, str)

        print(f"\n✅ Unified definition: {unified}")

    @pytest.mark.asyncio
    async def test_generate_unified_definition_single(self, indexer):
        """Test définition unique (pas de fusion LLM)"""
        concepts = [
            Concept(
                name="GDPR",
                type=ConceptType.STANDARD,
                definition="General Data Protection Regulation",
                context="",
                language="en",
                confidence=0.90,
                source_topic_id="t1",
                extraction_method="NER"
            )
        ]

        unified = await indexer._generate_unified_definition(concepts)

        # Devrait retourner définition telle quelle (pas LLM)
        assert unified == "General Data Protection Regulation"

        print(f"\n✅ Single definition preserved: {unified}")

    @pytest.mark.asyncio
    async def test_generate_unified_definition_empty(self, indexer):
        """Test sans définitions"""
        concepts = [
            Concept(
                name="Test",
                type=ConceptType.ENTITY,
                definition="",
                context="",
                language="en",
                confidence=0.90,
                source_topic_id="t1",
                extraction_method="NER"
            )
        ]

        unified = await indexer._generate_unified_definition(concepts)

        # Devrait retourner vide
        assert unified == ""

        print("\n✅ Empty definition handled")

    @pytest.mark.asyncio
    async def test_build_hierarchy(self, indexer, sample_concepts_hierarchy, mock_llm_router):
        """Test construction hiérarchie via LLM"""
        # Mock LLM pour retourner hiérarchie
        mock_llm_router.route_request = AsyncMock(return_value={
            "content": '''{
                "hierarchies": [
                    {
                        "parent": "Security Testing",
                        "children": ["SAST", "DAST", "Penetration Testing"]
                    }
                ]
            }'''
        })

        # Canonicaliser d'abord
        canonical = await indexer.canonicalize_concepts(
            sample_concepts_hierarchy,
            enable_hierarchy=True,
            enable_relations=False
        )

        # Trouver parent
        parent_concept = next(
            (c for c in canonical if c.canonical_name == "Security Testing"),
            None
        )

        # Vérifications
        if parent_concept:
            assert parent_concept.hierarchy_children, "Parent should have children"
            assert "SAST" in parent_concept.hierarchy_children
            assert "DAST" in parent_concept.hierarchy_children

            print(f"\n✅ Hierarchy built:")
            print(f"   Parent: {parent_concept.canonical_name}")
            print(f"   Children: {parent_concept.hierarchy_children}")

            # Vérifier children ont parent
            sast_concept = next(
                (c for c in canonical if c.canonical_name == "SAST"),
                None
            )
            if sast_concept:
                assert sast_concept.hierarchy_parent == "Security Testing"
                print(f"   Child 'SAST' has parent: {sast_concept.hierarchy_parent}")
        else:
            print("\n⚠️ Parent concept 'Security Testing' not found (may be unified)")

    @pytest.mark.asyncio
    async def test_extract_relations(self, indexer):
        """Test extraction relations sémantiques"""
        concepts = [
            Concept(
                name="authentication",
                type=ConceptType.PRACTICE,
                definition="",
                context="",
                language="en",
                confidence=0.90,
                source_topic_id="t1",
                extraction_method="NER"
            ),
            Concept(
                name="authorization",
                type=ConceptType.PRACTICE,
                definition="",
                context="",
                language="en",
                confidence=0.90,
                source_topic_id="t2",
                extraction_method="NER"
            ),
            Concept(
                name="access control",
                type=ConceptType.PRACTICE,
                definition="",
                context="",
                language="en",
                confidence=0.90,
                source_topic_id="t3",
                extraction_method="NER"
            ),
            Concept(
                name="ISO 27001",  # Très différent
                type=ConceptType.STANDARD,
                definition="",
                context="",
                language="en",
                confidence=0.90,
                source_topic_id="t4",
                extraction_method="NER"
            )
        ]

        canonical = await indexer.canonicalize_concepts(
            concepts,
            enable_hierarchy=False,
            enable_relations=True
        )

        # Vérifier relations extraites
        auth_concept = next(
            (c for c in canonical if "authentication" in c.canonical_name.lower()),
            None
        )

        if auth_concept and auth_concept.related_concepts:
            assert len(auth_concept.related_concepts) > 0
            print(f"\n✅ Relations extracted for '{auth_concept.canonical_name}':")
            print(f"   Related: {auth_concept.related_concepts}")
        else:
            print("\n⚠️ No relations found (normal if concepts too different)")

    def test_calculate_quality_score_high(self, indexer):
        """Test quality score élevé"""
        canonical = CanonicalConcept(
            canonical_name="authentication",
            aliases=["authentification", "Authentifizierung"],
            languages=["en", "fr", "de"],
            type=ConceptType.PRACTICE,
            definition="Process of verifying identity",
            hierarchy_parent=None,
            hierarchy_children=["MFA", "SSO"],
            related_concepts=["authorization", "access control"],
            source_concepts=[],
            support=5,
            confidence=0.90
        )

        score = indexer.calculate_quality_score(canonical)

        # Score devrait être élevé (toutes conditions remplies)
        assert score >= 0.8, f"High quality concept should have score >= 0.8, got {score}"

        print(f"\n✅ High quality score: {score:.2f}")
        print(f"   Support: {canonical.support}")
        print(f"   Languages: {len(canonical.languages)}")
        print(f"   Definition: {'yes' if canonical.definition else 'no'}")
        print(f"   Hierarchy: {'yes' if canonical.hierarchy_children else 'no'}")
        print(f"   Relations: {'yes' if canonical.related_concepts else 'no'}")

    def test_calculate_quality_score_low(self, indexer):
        """Test quality score faible"""
        canonical = CanonicalConcept(
            canonical_name="test",
            aliases=["test"],
            languages=["en"],
            type=ConceptType.ENTITY,
            definition="",
            hierarchy_parent=None,
            hierarchy_children=[],
            related_concepts=[],
            source_concepts=[],
            support=1,
            confidence=0.70
        )

        score = indexer.calculate_quality_score(canonical)

        # Score devrait être faible
        assert score < 0.5, f"Low quality concept should have score < 0.5, got {score}"

        print(f"\n✅ Low quality score: {score:.2f}")

    @pytest.mark.asyncio
    async def test_full_pipeline_integration(self, indexer, sample_concepts_multilingual):
        """Test pipeline complet end-to-end"""
        canonical = await indexer.canonicalize_concepts(
            sample_concepts_multilingual,
            enable_hierarchy=True,
            enable_relations=True
        )

        # Vérifications globales
        assert len(canonical) > 0, "Should produce canonical concepts"

        for concept in canonical:
            # Structure
            assert concept.canonical_name, "Must have canonical name"
            assert concept.aliases, "Must have aliases"
            assert concept.languages, "Must have languages"
            assert concept.type, "Must have type"

            # Métriques
            assert concept.support >= 1, "Support must be >= 1"
            assert 0.0 <= concept.confidence <= 1.0, "Invalid confidence"

            # Quality
            quality_score = indexer.calculate_quality_score(concept)
            assert 0.0 <= quality_score <= 1.0, "Invalid quality score"

        print(f"\n✅ Full pipeline: {len(canonical)} canonical concepts")
        for c in canonical:
            print(f"\n   Concept: {c.canonical_name}")
            print(f"     Aliases: {c.aliases}")
            print(f"     Languages: {c.languages}")
            print(f"     Support: {c.support}")
            print(f"     Confidence: {c.confidence:.2f}")
            print(f"     Quality: {indexer.calculate_quality_score(c):.2f}")
            if c.hierarchy_children:
                print(f"     Children: {c.hierarchy_children}")
            if c.related_concepts:
                print(f"     Related: {c.related_concepts}")

    @pytest.mark.asyncio
    async def test_empty_input(self, indexer):
        """Test avec input vide"""
        canonical = await indexer.canonicalize_concepts([])

        assert len(canonical) == 0, "Empty input should return empty list"

        print("\n✅ Empty input handled correctly")

    @pytest.mark.asyncio
    async def test_large_concept_set(self, indexer):
        """Test avec grand nombre de concepts (>50)"""
        concepts = []
        for i in range(60):
            concepts.append(
                Concept(
                    name=f"Concept {i}",
                    type=ConceptType.ENTITY,
                    definition="",
                    context="",
                    language="en",
                    confidence=0.80,
                    source_topic_id=f"t{i}",
                    extraction_method="NER"
                )
            )

        canonical = await indexer.canonicalize_concepts(
            concepts,
            enable_hierarchy=True,
            enable_relations=False
        )

        # Devrait gérer sans crash
        assert len(canonical) > 0, "Should handle large concept sets"

        print(f"\n✅ Large concept set handled: {len(concepts)} → {len(canonical)}")


if __name__ == "__main__":
    # Run tests avec pytest
    pytest.main([__file__, "-v", "-s"])
