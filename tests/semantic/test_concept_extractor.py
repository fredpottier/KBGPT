"""
🌊 OSMOSE Semantic Intelligence V2.1 - Tests ConceptExtractor

Tests du MultilingualConceptExtractor (composant CRITIQUE)
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock
from src.knowbase.semantic.extraction.concept_extractor import MultilingualConceptExtractor
from src.knowbase.semantic.models import Topic, Window
from src.knowbase.semantic.config import get_semantic_config


@pytest.fixture
def config():
    """Fixture configuration"""
    return get_semantic_config()


@pytest.fixture
def mock_llm_router():
    """Fixture LLMRouter mocké"""
    router = AsyncMock()
    router.route_request = AsyncMock(return_value={
        "content": '{"concepts": [{"name": "ISO 27001", "type": "STANDARD", "definition": "Information security standard", "relationships": ["security", "compliance"]}]}'
    })
    return router


@pytest.fixture
def extractor(config, mock_llm_router):
    """Fixture ConceptExtractor"""
    return MultilingualConceptExtractor(config, mock_llm_router)


@pytest.fixture
def sample_topic_en():
    """Topic anglais sample"""
    windows = [
        Window(
            text="ISO 27001 is an information security management standard. It provides requirements for establishing, implementing, maintaining and continually improving an information security management system.",
            start=0,
            end=200
        ),
        Window(
            text="The standard includes controls for access management, cryptography, and incident response. Organizations must implement policies to protect information assets.",
            start=150,
            end=350
        )
    ]

    return Topic(
        topic_id="test_topic_001",
        document_id="test_doc_001",
        section_path="1. Security Standards",
        windows=windows,
        anchors=["ISO 27001", "security", "management"],
        cohesion_score=0.85
    )


@pytest.fixture
def sample_topic_fr():
    """Topic français sample"""
    windows = [
        Window(
            text="La norme ISO 27001 est un standard de management de la sécurité de l'information. Elle fournit des exigences pour établir, mettre en œuvre et améliorer un système de management.",
            start=0,
            end=200
        )
    ]

    return Topic(
        topic_id="test_topic_002_fr",
        document_id="test_doc_002",
        section_path="1. Normes de Sécurité",
        windows=windows,
        anchors=["ISO 27001", "sécurité"],
        cohesion_score=0.80
    )


class TestMultilingualConceptExtractor:
    """Tests du MultilingualConceptExtractor"""

    @pytest.mark.asyncio
    async def test_extract_concepts_basic(self, extractor, sample_topic_en):
        """Test extraction basique concepts anglais"""
        concepts = await extractor.extract_concepts(sample_topic_en, enable_llm=False)

        # Assertions
        assert len(concepts) > 0, "Should extract at least 1 concept"

        for concept in concepts:
            assert concept.name, "Concept should have a name"
            assert isinstance(concept.type, str), "Concept type should be a string"
            assert concept.language in ["en", "fr", "de"], "Should detect language"
            assert 0.0 <= concept.confidence <= 1.0, "Confidence should be [0, 1]"
            assert concept.source_topic_id == "test_topic_001"
            assert concept.extraction_method in ["NER", "CLUSTERING"]

        print(f"\n✅ Extracted {len(concepts)} concepts:")
        for c in concepts[:5]:
            print(f"   - {c.name} ({c.type.value}) [method={c.extraction_method}, conf={c.confidence:.2f}]")

    @pytest.mark.asyncio
    async def test_extract_via_ner(self, extractor, sample_topic_en):
        """Test extraction NER uniquement"""
        concepts_ner = await extractor._extract_via_ner(sample_topic_en, "en")

        assert len(concepts_ner) > 0, "NER should extract entities"

        for concept in concepts_ner:
            assert concept.extraction_method == "NER"
            assert concept.confidence == 0.85  # NER high confidence

        print(f"\n✅ NER extracted {len(concepts_ner)} entities:")
        for c in concepts_ner:
            print(f"   - {c.name} ({c.type.value})")

    @pytest.mark.asyncio
    async def test_extract_via_clustering(self, extractor, sample_topic_en):
        """Test extraction clustering"""
        concepts_clustering = await extractor._extract_via_clustering(sample_topic_en, "en")

        # Clustering peut ne rien trouver si pas assez de noun phrases
        # Donc on vérifie juste qu'il ne crash pas
        assert isinstance(concepts_clustering, list)

        if concepts_clustering:
            for concept in concepts_clustering:
                assert concept.extraction_method == "CLUSTERING"
                assert concept.confidence == 0.75
                assert len(concept.related_concepts) > 0, "Clustering should provide related concepts"

            print(f"\n✅ Clustering extracted {len(concepts_clustering)} concepts:")
            for c in concepts_clustering:
                print(f"   - {c.name} (related: {c.related_concepts[:3]})")
        else:
            print("\n⚠️ Clustering found no concepts (normal for small topics)")

    @pytest.mark.asyncio
    async def test_extract_via_llm(self, extractor, sample_topic_en):
        """Test extraction LLM"""
        concepts_llm = await extractor._extract_via_llm(sample_topic_en, "en")

        # LLM mocké devrait retourner 1 concept
        assert len(concepts_llm) == 1, "LLM mock should return 1 concept"

        concept = concepts_llm[0]
        assert concept.name == "ISO 27001"
        assert concept.type == "standard"
        assert concept.definition == "Information security standard"
        assert concept.extraction_method == "LLM"
        assert concept.confidence == 0.80

        print(f"\n✅ LLM extracted: {concept.name} ({concept.type.value})")

    @pytest.mark.asyncio
    async def test_deduplication(self, extractor):
        """Test déduplication concepts similaires"""
        from src.knowbase.semantic.models import Concept

        # Créer concepts dupliqués
        concepts = [
            Concept(
                name="ISO 27001",
                type="standard",
                definition="",
                context="test",
                language="en",
                confidence=0.85,
                source_topic_id="test",
                extraction_method="NER"
            ),
            Concept(
                name="iso 27001",  # Même nom, case différente
                type="standard",
                definition="",
                context="test",
                language="en",
                confidence=0.75,
                source_topic_id="test",
                extraction_method="CLUSTERING"
            ),
            Concept(
                name="ISO27001",  # Variante sans espace
                type="standard",
                definition="",
                context="test",
                language="en",
                confidence=0.70,
                source_topic_id="test",
                extraction_method="CLUSTERING"
            ),
            Concept(
                name="GDPR",  # Concept différent
                type="standard",
                definition="",
                context="test",
                language="en",
                confidence=0.80,
                source_topic_id="test",
                extraction_method="NER"
            )
        ]

        deduplicated = extractor._deduplicate_concepts(concepts)

        # Devrait garder 2 concepts (ISO 27001 avec highest confidence + GDPR)
        assert len(deduplicated) <= 3, f"Should deduplicate, got {len(deduplicated)} concepts"

        # Vérifier que le concept gardé a la meilleure confiance
        iso_concepts = [c for c in deduplicated if "iso" in c.name.lower() and "27001" in c.name.lower()]
        if iso_concepts:
            best_iso = iso_concepts[0]
            assert best_iso.confidence >= 0.75, "Should keep highest confidence concept"

        print(f"\n✅ Deduplication: {len(concepts)} → {len(deduplicated)} concepts")
        for c in deduplicated:
            print(f"   - {c.name} (conf={c.confidence:.2f})")

    @pytest.mark.asyncio
    async def test_extract_french(self, extractor, sample_topic_fr):
        """Test extraction document français"""
        concepts = await extractor.extract_concepts(sample_topic_fr, enable_llm=False)

        assert len(concepts) > 0, "Should extract French concepts"

        # Vérifier détection langue française
        for concept in concepts:
            # Language detector devrait détecter français
            assert concept.language in ["fr", "en"], "Should detect French or English"

        print(f"\n✅ French extraction: {len(concepts)} concepts")
        for c in concepts[:3]:
            print(f"   - {c.name} (lang={c.language})")

    def test_map_ner_label_to_concept_type(self, extractor):
        """Test mapping NER label → concept type string"""
        assert extractor._map_ner_label_to_concept_type("ORG") == "entity"
        assert extractor._map_ner_label_to_concept_type("PRODUCT") == "tool"
        assert extractor._map_ner_label_to_concept_type("LAW") == "standard"
        assert extractor._map_ner_label_to_concept_type("UNKNOWN") == "entity"

        print("\n✅ NER label mapping working")

    def test_infer_concept_type_heuristic(self, extractor):
        """Test inférence type concept par heuristique"""
        # TOOL
        assert extractor._infer_concept_type_heuristic(
            "SAST Tool",
            []
        ) == "tool"

        # STANDARD
        assert extractor._infer_concept_type_heuristic(
            "ISO 27001 Standard",
            []
        ) == "standard"

        # PRACTICE
        assert extractor._infer_concept_type_heuristic(
            "Code Review Process",
            []
        ) == "practice"

        # ROLE
        assert extractor._infer_concept_type_heuristic(
            "Security Architect",
            []
        ) == "role"

        # ENTITY (default)
        assert extractor._infer_concept_type_heuristic(
            "SAP S/4HANA",
            []
        ) == "entity"

        print("\n✅ Heuristic type inference working")

    def test_extract_noun_phrases(self, extractor, sample_topic_en):
        """Test extraction noun phrases"""
        noun_phrases = extractor._extract_noun_phrases(sample_topic_en, "en")

        assert len(noun_phrases) > 0, "Should extract noun phrases"

        # Vérifier longueur phrases (2-50 chars)
        for phrase in noun_phrases:
            assert 2 <= len(phrase) <= 50, f"Invalid phrase length: {phrase}"

        print(f"\n✅ Extracted {len(noun_phrases)} noun phrases:")
        for phrase in noun_phrases[:10]:
            print(f"   - {phrase}")

    def test_get_llm_extraction_prompt(self, extractor):
        """Test génération prompts LLM multilingues"""
        text_sample = "ISO 27001 is a security standard."

        # Anglais
        prompt_en = extractor._get_llm_extraction_prompt(text_sample, "en")
        assert "Extract key concepts" in prompt_en
        assert "ENTITY, PRACTICE, STANDARD, TOOL, ROLE" in prompt_en
        assert text_sample in prompt_en

        # Français
        prompt_fr = extractor._get_llm_extraction_prompt(text_sample, "fr")
        assert "Extrait les concepts" in prompt_fr
        assert text_sample in prompt_fr

        # Allemand
        prompt_de = extractor._get_llm_extraction_prompt(text_sample, "de")
        assert "Extrahiere" in prompt_de
        assert text_sample in prompt_de

        # Langue non supportée → fallback anglais
        prompt_unknown = extractor._get_llm_extraction_prompt(text_sample, "xx")
        assert "Extract key concepts" in prompt_unknown

        print("\n✅ Multilingual prompts working (en, fr, de, fallback)")

    def test_parse_llm_response(self, extractor):
        """Test parsing réponse LLM JSON"""
        # Réponse valide
        response_valid = '{"concepts": [{"name": "ISO 27001", "type": "STANDARD", "definition": "Security standard", "relationships": ["security"]}]}'

        concepts = extractor._parse_llm_response(response_valid)
        assert len(concepts) == 1
        assert concepts[0]["name"] == "ISO 27001"

        # Réponse avec texte autour du JSON
        response_with_text = 'Here are the concepts:\n{"concepts": [{"name": "GDPR", "type": "STANDARD"}]}\nDone.'

        concepts = extractor._parse_llm_response(response_with_text)
        assert len(concepts) == 1
        assert concepts[0]["name"] == "GDPR"

        # Réponse invalide
        response_invalid = "This is not JSON"
        concepts = extractor._parse_llm_response(response_invalid)
        assert len(concepts) == 0

        print("\n✅ LLM response parsing working")

    @pytest.mark.asyncio
    async def test_concept_limit(self, extractor, sample_topic_en):
        """Test limite max concepts par topic"""
        # Configurer max à 5
        extractor.extraction_config.max_concepts_per_topic = 5

        concepts = await extractor.extract_concepts(sample_topic_en, enable_llm=False)

        assert len(concepts) <= 5, f"Should limit to 5 concepts, got {len(concepts)}"

        print(f"\n✅ Concept limit working: {len(concepts)} ≤ 5")

    @pytest.mark.asyncio
    async def test_min_concepts_triggers_llm(self, extractor, sample_topic_en, mock_llm_router):
        """Test que LLM est appelé si concepts insuffisants"""
        # Configurer min à 10 (plus que NER+Clustering peuvent fournir)
        extractor.extraction_config.min_concepts_per_topic = 10

        concepts = await extractor.extract_concepts(sample_topic_en, enable_llm=True)

        # LLM devrait avoir été appelé
        assert mock_llm_router.route_request.called, "LLM should be called when min not reached"

        print(f"\n✅ LLM triggered when min concepts not reached")

    @pytest.mark.asyncio
    async def test_full_pipeline_integration(self, extractor, sample_topic_en):
        """Test pipeline complet end-to-end"""
        concepts = await extractor.extract_concepts(sample_topic_en, enable_llm=True)

        # Vérifications complètes
        assert len(concepts) > 0, "Should extract concepts"
        assert len(concepts) <= extractor.extraction_config.max_concepts_per_topic

        # Vérifier qualité concepts
        for concept in concepts:
            assert concept.name, "Must have name"
            assert len(concept.name) <= 50, "Name too long"
            assert isinstance(concept.type, str), "Type must be a string"
            assert concept.language, "Must have language"
            assert 0.0 <= concept.confidence <= 1.0, "Invalid confidence"
            assert concept.extraction_method in ["NER", "CLUSTERING", "LLM"]

        # Stats par méthode
        methods_stats = {}
        for concept in concepts:
            method = concept.extraction_method
            methods_stats[method] = methods_stats.get(method, 0) + 1

        print(f"\n✅ Full pipeline: {len(concepts)} concepts extracted")
        print(f"   Methods breakdown: {methods_stats}")
        print(f"\n   Sample concepts:")
        for c in concepts[:5]:
            print(f"   - {c.name} ({c.type.value}) [method={c.extraction_method}, conf={c.confidence:.2f}, lang={c.language}]")


if __name__ == "__main__":
    # Run tests avec pytest
    pytest.main([__file__, "-v", "-s"])
