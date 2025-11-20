"""
Tests unitaires pour LLM-as-a-Judge Validation (Phase 1.8 T1.8.1.7c)

Tests de validation des clusters de concepts via LLM pour réduire
les faux positifs de clustering basé sur similarity.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import List, Dict, Any

from knowbase.semantic.indexing.semantic_indexer import SemanticIndexer
from knowbase.semantic.models import Concept, ConceptType
from knowbase.semantic.config import SemanticConfig


# ===================================
# FIXTURES
# ===================================

@pytest.fixture
def mock_embedder():
    """Mock embedder pour tests."""
    embedder = MagicMock()
    embedder.encode.return_value = [[0.1] * 1024]  # Fake embedding
    return embedder


@pytest.fixture
def mock_llm_router():
    """Mock LLM router pour tests."""
    router = AsyncMock()
    router.acomplete = AsyncMock()
    return router


@pytest.fixture
def semantic_config():
    """Configuration sémantique pour tests."""
    config = SemanticConfig()
    # Enable LLM-as-a-Judge validation
    config.indexing.llm_judge_validation = True
    config.indexing.llm_judge_min_cluster_size = 2
    config.indexing.similarity_threshold = 0.85
    return config


@pytest.fixture
def semantic_indexer(
    semantic_config,
    mock_embedder,
    mock_llm_router
):
    """SemanticIndexer avec mocks pour tests."""
    with patch('knowbase.semantic.indexing.semantic_indexer.get_embedder', return_value=mock_embedder):
        indexer = SemanticIndexer(
            llm_router=mock_llm_router,
            config=semantic_config
        )
    return indexer


@pytest.fixture
def sample_concepts() -> List[Concept]:
    """Concepts de test (synonymes cross-linguals)."""
    return [
        Concept(
            name="authentication",
            type=ConceptType.PRACTICE,
            context="User authentication via MFA",
            language="en",
            confidence=0.9,
            source_topic_id="topic-1",
            extraction_method="NER"
        ),
        Concept(
            name="authentification",
            type=ConceptType.PRACTICE,
            context="Authentification utilisateur via MFA",
            language="fr",
            confidence=0.9,
            source_topic_id="topic-2",
            extraction_method="NER"
        )
    ]


@pytest.fixture
def distinct_concepts() -> List[Concept]:
    """Concepts distincts (faux positifs potentiels)."""
    return [
        Concept(
            name="security",
            type=ConceptType.PRACTICE,
            context="Security controls and measures",
            language="en",
            confidence=0.9,
            source_topic_id="topic-1",
            extraction_method="NER"
        ),
        Concept(
            name="compliance",
            type=ConceptType.PRACTICE,
            context="Compliance with regulations",
            language="en",
            confidence=0.9,
            source_topic_id="topic-2",
            extraction_method="NER"
        )
    ]


# ===================================
# TESTS: _validate_cluster_via_llm()
# ===================================

class TestLLMJudgeValidation:
    """Tests validation LLM-as-a-Judge."""

    @pytest.mark.skip(reason="pytest-asyncio not installed")
    @pytest.mark.asyncio
    async def test_single_concept_skips_validation(self, semantic_indexer, sample_concepts):
        """Test: cluster avec 1 concept skip validation (toujours valide)."""
        single_concept = [sample_concepts[0]]

        result = await semantic_indexer._validate_cluster_via_llm(single_concept)

        assert result is True
        # LLM ne doit pas être appelé pour single concept
        semantic_indexer.llm_router.acomplete.assert_not_called()

    @pytest.mark.skip(reason="pytest-asyncio not installed")
    @pytest.mark.asyncio
    async def test_valid_cluster_approved(self, semantic_indexer, sample_concepts, mock_llm_router):
        """Test: cluster valide (synonymes) approuvé par LLM."""
        # Mock réponse LLM: cluster valide
        mock_llm_router.acomplete.return_value = '{"are_synonyms": true, "reasoning": "Translation FR/EN"}'

        result = await semantic_indexer._validate_cluster_via_llm(sample_concepts)

        assert result is True
        mock_llm_router.acomplete.assert_called_once()

        # Vérifier que le prompt contient les noms des concepts
        call_args = mock_llm_router.acomplete.call_args
        messages = call_args.kwargs["messages"]
        user_prompt = messages[1]["content"]
        assert "authentication" in user_prompt
        assert "authentification" in user_prompt

    @pytest.mark.skip(reason="pytest-asyncio not installed")
    @pytest.mark.asyncio
    async def test_invalid_cluster_rejected(self, semantic_indexer, distinct_concepts, mock_llm_router):
        """Test: cluster invalide (concepts distincts) rejeté par LLM."""
        # Mock réponse LLM: cluster invalide
        mock_llm_router.acomplete.return_value = '{"are_synonyms": false, "reasoning": "Different domains"}'

        result = await semantic_indexer._validate_cluster_via_llm(distinct_concepts)

        assert result is False
        mock_llm_router.acomplete.assert_called_once()

    @pytest.mark.skip(reason="pytest-asyncio not installed")
    @pytest.mark.asyncio
    async def test_llm_error_defaults_to_accept(self, semantic_indexer, sample_concepts, mock_llm_router):
        """Test: erreur LLM → fallback conservateur (accepter cluster)."""
        # Mock réponse LLM: erreur parsing
        mock_llm_router.acomplete.return_value = "Invalid JSON response"

        result = await semantic_indexer._validate_cluster_via_llm(sample_concepts)

        # Fallback conservateur: accepter si erreur
        assert result is True

    @pytest.mark.skip(reason="pytest-asyncio not installed")
    @pytest.mark.asyncio
    async def test_prompt_includes_threshold(self, semantic_indexer, sample_concepts, mock_llm_router):
        """Test: prompt inclut threshold de similarité."""
        mock_llm_router.acomplete.return_value = '{"are_synonyms": true, "reasoning": "OK"}'

        await semantic_indexer._validate_cluster_via_llm(sample_concepts, threshold=0.90)

        call_args = mock_llm_router.acomplete.call_args
        messages = call_args.kwargs["messages"]
        user_prompt = messages[1]["content"]

        # Vérifier que le threshold apparaît dans le prompt
        assert "0.9" in user_prompt

    @pytest.mark.skip(reason="pytest-asyncio not installed")
    @pytest.mark.asyncio
    async def test_llm_call_parameters(self, semantic_indexer, sample_concepts, mock_llm_router):
        """Test: paramètres appel LLM corrects."""
        mock_llm_router.acomplete.return_value = '{"are_synonyms": true, "reasoning": "OK"}'

        await semantic_indexer._validate_cluster_via_llm(sample_concepts)

        call_args = mock_llm_router.acomplete.call_args

        # Vérifier température = 0.0 (déterministe)
        assert call_args.kwargs["temperature"] == 0.0

        # Vérifier response_format JSON
        assert call_args.kwargs["response_format"] == {"type": "json_object"}

        # Vérifier max_tokens
        assert call_args.kwargs["max_tokens"] == 500


# ===================================
# TESTS: Integration dans canonicalize_concepts()
# ===================================

class TestLLMJudgeIntegration:
    """Tests intégration validation dans canonicalization."""

    @pytest.mark.skip(reason="pytest-asyncio not installed")
    @pytest.mark.asyncio
    async def test_validation_disabled_skips_llm(
        self,
        semantic_indexer,
        sample_concepts,
        mock_llm_router
    ):
        """Test: validation désactivée → pas d'appel LLM."""
        # Disable validation
        semantic_indexer.indexing_config.llm_judge_validation = False

        # Mock clustering to return 1 group
        with patch.object(
            semantic_indexer,
            '_cluster_similar_concepts',
            return_value=[sample_concepts]
        ):
            with patch.object(
                semantic_indexer,
                '_build_canonical_concept',
                new_callable=AsyncMock
            ):
                await semantic_indexer.canonicalize_concepts(sample_concepts)

        # LLM ne doit pas être appelé
        mock_llm_router.acomplete.assert_not_called()

    @pytest.mark.skip(reason="pytest-asyncio not installed")
    @pytest.mark.asyncio
    async def test_small_cluster_skips_validation(
        self,
        semantic_indexer,
        sample_concepts,
        mock_llm_router
    ):
        """Test: cluster < min_cluster_size skip validation."""
        # Set min_cluster_size = 3
        semantic_indexer.indexing_config.llm_judge_min_cluster_size = 3

        # Mock clustering: 1 cluster with 2 concepts (< 3)
        with patch.object(
            semantic_indexer,
            '_cluster_similar_concepts',
            return_value=[sample_concepts]
        ):
            with patch.object(
                semantic_indexer,
                '_build_canonical_concept',
                new_callable=AsyncMock
            ):
                await semantic_indexer.canonicalize_concepts(sample_concepts)

        # LLM ne doit pas être appelé (cluster trop petit)
        mock_llm_router.acomplete.assert_not_called()

    @pytest.mark.skip(reason="pytest-asyncio not installed")
    @pytest.mark.asyncio
    async def test_rejected_cluster_splits_into_individuals(
        self,
        semantic_indexer,
        distinct_concepts,
        mock_llm_router
    ):
        """Test: cluster rejeté → split en concepts individuels."""
        # Mock réponse LLM: rejection
        mock_llm_router.acomplete.return_value = '{"are_synonyms": false, "reasoning": "Distinct"}'

        # Mock clustering: 1 cluster with 2 distinct concepts
        with patch.object(
            semantic_indexer,
            '_cluster_similar_concepts',
            return_value=[distinct_concepts]
        ):
            mock_build = AsyncMock()
            with patch.object(
                semantic_indexer,
                '_build_canonical_concept',
                mock_build
            ):
                await semantic_indexer.canonicalize_concepts(distinct_concepts)

        # Cluster rejeté → split en 2 appels _build_canonical_concept
        assert mock_build.call_count == 2

        # Vérifier que chaque appel reçoit un seul concept
        calls = mock_build.call_args_list
        assert len(calls[0][0][0]) == 1  # Premier appel: 1 concept
        assert len(calls[1][0][0]) == 1  # Deuxième appel: 1 concept

    @pytest.mark.skip(reason="pytest-asyncio not installed")
    @pytest.mark.asyncio
    async def test_approved_cluster_builds_canonical(
        self,
        semantic_indexer,
        sample_concepts,
        mock_llm_router
    ):
        """Test: cluster approuvé → build canonical concept."""
        # Mock réponse LLM: approval
        mock_llm_router.acomplete.return_value = '{"are_synonyms": true, "reasoning": "Synonyms"}'

        # Mock clustering: 1 cluster with 2 concepts
        with patch.object(
            semantic_indexer,
            '_cluster_similar_concepts',
            return_value=[sample_concepts]
        ):
            mock_build = AsyncMock()
            with patch.object(
                semantic_indexer,
                '_build_canonical_concept',
                mock_build
            ):
                await semantic_indexer.canonicalize_concepts(sample_concepts)

        # Cluster approuvé → 1 seul appel _build_canonical_concept
        assert mock_build.call_count == 1

        # Vérifier que l'appel reçoit 2 concepts
        calls = mock_build.call_args_list
        assert len(calls[0][0][0]) == 2

    @pytest.mark.skip(reason="pytest-asyncio not installed")
    @pytest.mark.asyncio
    async def test_mixed_clusters_validation(
        self,
        semantic_indexer,
        sample_concepts,
        distinct_concepts,
        mock_llm_router
    ):
        """Test: mix de clusters approuvés/rejetés."""
        # Mock réponses LLM: 1 approuvé, 1 rejeté
        mock_llm_router.acomplete.side_effect = [
            '{"are_synonyms": true, "reasoning": "Synonyms"}',   # Cluster 1: approve
            '{"are_synonyms": false, "reasoning": "Distinct"}'   # Cluster 2: reject
        ]

        # Mock clustering: 2 clusters
        all_concepts = sample_concepts + distinct_concepts
        with patch.object(
            semantic_indexer,
            '_cluster_similar_concepts',
            return_value=[sample_concepts, distinct_concepts]
        ):
            mock_build = AsyncMock()
            with patch.object(
                semantic_indexer,
                '_build_canonical_concept',
                mock_build
            ):
                await semantic_indexer.canonicalize_concepts(all_concepts)

        # Cluster 1 approuvé (1 appel) + Cluster 2 rejeté (2 appels) = 3 appels
        assert mock_build.call_count == 3


# ===================================
# TESTS: Prompt Building
# ===================================

class TestLLMJudgePromptBuilding:
    """Tests construction prompts LLM-as-a-Judge."""

    def test_build_prompt_includes_concepts(self, semantic_indexer):
        """Test: prompt contient noms des concepts."""
        concept_names = ["authentication", "authentification"]

        prompt = semantic_indexer._build_llm_judge_prompt(concept_names, similarity_threshold=0.85)

        assert "authentication" in prompt
        assert "authentification" in prompt
        assert "0.85" in prompt

    def test_build_prompt_includes_guidelines(self, semantic_indexer):
        """Test: prompt contient guidelines validation."""
        concept_names = ["security", "compliance"]

        prompt = semantic_indexer._build_llm_judge_prompt(concept_names, similarity_threshold=0.85)

        # Vérifier présence guidelines
        assert "MERGE" in prompt or "merge" in prompt.lower()
        assert "KEEP SEPARATE" in prompt or "separate" in prompt.lower()
        assert "synonyms" in prompt.lower()

    def test_build_prompt_requires_json_format(self, semantic_indexer):
        """Test: prompt demande format JSON."""
        concept_names = ["concept1", "concept2"]

        prompt = semantic_indexer._build_llm_judge_prompt(concept_names, similarity_threshold=0.85)

        # Vérifier demande JSON
        assert "JSON" in prompt or "json" in prompt
        assert "are_synonyms" in prompt
        assert "reasoning" in prompt


# ===================================
# TESTS: Response Parsing
# ===================================

class TestLLMJudgeResponseParsing:
    """Tests parsing réponses LLM-as-a-Judge."""

    def test_parse_valid_response_true(self, semantic_indexer):
        """Test: parse réponse valide (synonyms=true)."""
        response = '{"are_synonyms": true, "reasoning": "Translation FR/EN"}'

        result = semantic_indexer._parse_llm_judge_response(response)

        assert result is not None
        assert result["are_synonyms"] is True
        assert result["reasoning"] == "Translation FR/EN"

    def test_parse_valid_response_false(self, semantic_indexer):
        """Test: parse réponse valide (synonyms=false)."""
        response = '{"are_synonyms": false, "reasoning": "Different domains"}'

        result = semantic_indexer._parse_llm_judge_response(response)

        assert result is not None
        assert result["are_synonyms"] is False
        assert result["reasoning"] == "Different domains"

    def test_parse_response_with_extra_text(self, semantic_indexer):
        """Test: parse réponse avec texte supplémentaire."""
        response = 'Here is the validation:\n{"are_synonyms": true, "reasoning": "OK"}\nDone.'

        result = semantic_indexer._parse_llm_judge_response(response)

        assert result is not None
        assert result["are_synonyms"] is True

    def test_parse_invalid_json_returns_none(self, semantic_indexer):
        """Test: JSON invalide → None."""
        response = "This is not JSON"

        result = semantic_indexer._parse_llm_judge_response(response)

        assert result is None

    def test_parse_missing_are_synonyms_field_returns_none(self, semantic_indexer):
        """Test: champ are_synonyms manquant → None."""
        response = '{"reasoning": "OK"}'  # Missing are_synonyms

        result = semantic_indexer._parse_llm_judge_response(response)

        assert result is None

    def test_parse_missing_reasoning_uses_default(self, semantic_indexer):
        """Test: reasoning manquant → fallback 'N/A'."""
        response = '{"are_synonyms": true}'  # Missing reasoning

        result = semantic_indexer._parse_llm_judge_response(response)

        assert result is not None
        assert result["are_synonyms"] is True
        assert result["reasoning"] == "N/A"


# ===================================
# TESTS: Edge Cases
# ===================================

class TestLLMJudgeEdgeCases:
    """Tests edge cases LLM-as-a-Judge."""

    @pytest.mark.skip(reason="pytest-asyncio not installed")
    @pytest.mark.asyncio
    async def test_empty_cluster_returns_true(self, semantic_indexer):
        """Test: cluster vide → True (pas de concepts à valider)."""
        result = await semantic_indexer._validate_cluster_via_llm([])

        assert result is True

    @pytest.mark.skip(reason="pytest-asyncio not installed")
    @pytest.mark.asyncio
    async def test_three_concepts_cluster(self, semantic_indexer, mock_llm_router):
        """Test: cluster avec 3 concepts (edge case)."""
        concepts = [
            Concept(name="auth", type=ConceptType.PRACTICE, context="Auth", language="en", confidence=0.9, source_topic_id="1", extraction_method="NER"),
            Concept(name="authentication", type=ConceptType.PRACTICE, context="Authentication", language="en", confidence=0.9, source_topic_id="2", extraction_method="NER"),
            Concept(name="authentification", type=ConceptType.PRACTICE, context="Authentification", language="fr", confidence=0.9, source_topic_id="3", extraction_method="NER")
        ]

        mock_llm_router.acomplete.return_value = '{"are_synonyms": true, "reasoning": "All synonyms"}'

        result = await semantic_indexer._validate_cluster_via_llm(concepts)

        assert result is True

        # Vérifier que le prompt contient les 3 concepts
        call_args = mock_llm_router.acomplete.call_args
        messages = call_args.kwargs["messages"]
        user_prompt = messages[1]["content"]
        assert "auth" in user_prompt
        assert "authentication" in user_prompt
        assert "authentification" in user_prompt
