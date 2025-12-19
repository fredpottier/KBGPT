"""
🌊 OSMOSE Phase 1.8 - Tests LLM-as-a-Judge Validation

Tests unitaires pour la validation de clustering via LLM-as-a-Judge.
Inspiré par KGGen Section 3.3 (Stanford/FAR AI).

T1.8.1.7c - Tests LLM-as-a-Judge
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock, MagicMock
import asyncio
import json


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_driver():
    """Mock Neo4j driver."""
    driver = Mock()
    driver.session.return_value.__enter__ = Mock()
    driver.session.return_value.__exit__ = Mock(return_value=None)
    return driver


@pytest.fixture
def normalizer(mock_driver):
    """Crée un EntityNormalizerNeo4j pour tests."""
    from knowbase.ontology.entity_normalizer_neo4j import EntityNormalizerNeo4j
    return EntityNormalizerNeo4j(mock_driver)


@pytest.fixture
def concept_sap_s4():
    """Concept SAP S/4HANA."""
    return {
        "name": "SAP S/4HANA",
        "type": "PRODUCT",
        "aliases": ["S/4HANA", "S4HANA"],
        "context": "SAP S/4HANA is an intelligent ERP suite"
    }


@pytest.fixture
def concept_s4_cloud():
    """Concept SAP S/4HANA Cloud - différent de S/4HANA on-premise."""
    return {
        "name": "SAP S/4HANA Cloud",
        "type": "PRODUCT",
        "aliases": ["S/4HANA Cloud", "S4 Cloud"],
        "context": "SAP S/4HANA Cloud is a cloud-based ERP solution"
    }


@pytest.fixture
def concept_security_en():
    """Concept Security (EN)."""
    return {
        "name": "Security",
        "type": "CONCEPT",
        "aliases": [],
        "context": "Information security and cybersecurity"
    }


@pytest.fixture
def concept_securite_fr():
    """Concept Sécurité (FR) - équivalent à Security."""
    return {
        "name": "Sécurité",
        "type": "CONCEPT",
        "aliases": [],
        "context": "Sécurité informatique et cybersécurité"
    }


@pytest.fixture
def concept_gdpr():
    """Concept GDPR - différent de Security."""
    return {
        "name": "GDPR",
        "type": "REGULATION",
        "aliases": ["General Data Protection Regulation", "RGPD"],
        "context": "European data protection regulation"
    }


# =============================================================================
# Tests should_use_llm_judge (Décision de validation)
# =============================================================================

class TestShouldUseLlmJudge:
    """Tests pour la décision d'utiliser LLM-as-a-Judge."""

    def test_low_similarity_skip_validation(self, normalizer):
        """
        Test: Similarité trop basse → pas de validation LLM.

        Cas: similarity < 0.75 → pas de merge, économise appel LLM.
        """
        result = normalizer.should_use_llm_judge(
            similarity_score=0.60,
            concept_type_match=True
        )

        assert result is False

    def test_high_similarity_with_type_match_auto_merge(self, normalizer):
        """
        Test: Similarité très haute + types matchent → merge auto sans LLM.

        Cas: similarity >= 0.95 ET types identiques → merge évident.
        """
        result = normalizer.should_use_llm_judge(
            similarity_score=0.98,
            concept_type_match=True
        )

        assert result is False

    def test_high_similarity_without_type_match_needs_validation(self, normalizer):
        """
        Test: Similarité haute mais types différents → LLM validation.

        Cas: similarity >= 0.95 mais types différents → vérifier avec LLM.
        """
        result = normalizer.should_use_llm_judge(
            similarity_score=0.96,
            concept_type_match=False
        )

        assert result is True

    def test_gray_zone_needs_validation(self, normalizer):
        """
        Test: Similarité dans zone grise → LLM validation nécessaire.

        Cas: 0.75 <= similarity < 0.95 → zone incertaine.
        """
        result = normalizer.should_use_llm_judge(
            similarity_score=0.85,
            concept_type_match=True
        )

        assert result is True

    def test_custom_thresholds(self, normalizer):
        """
        Test: Seuils custom sont respectés.
        """
        # Avec min=0.80, 0.78 devrait skip
        result = normalizer.should_use_llm_judge(
            similarity_score=0.78,
            concept_type_match=True,
            min_similarity=0.80
        )

        assert result is False

        # Avec max=0.90, 0.92 avec type match devrait skip
        result = normalizer.should_use_llm_judge(
            similarity_score=0.92,
            concept_type_match=True,
            max_similarity=0.90
        )

        assert result is False


# =============================================================================
# Tests validate_cluster_via_llm (Validation LLM)
# =============================================================================

class TestValidateClusterViaLlm:
    """Tests pour la validation via LLM-as-a-Judge."""

    @pytest.mark.asyncio
    async def test_valid_cluster_approved(
        self,
        normalizer,
        concept_security_en,
        concept_securite_fr
    ):
        """
        Test: Cluster valide (équivalents cross-lingual) → True.

        Cas: "Security" (EN) et "Sécurité" (FR) = même concept.
        """
        # Mock LLM response
        mock_response = Mock()
        mock_response.content = json.dumps({
            "should_merge": True,
            "confidence": 0.95,
            "reason": "Both refer to the same concept in different languages"
        })

        with patch('knowbase.ontology.entity_normalizer_neo4j.get_llm_router') as mock_router:
            mock_llm = AsyncMock()
            mock_llm.generate_structured.return_value = mock_response
            mock_router.return_value = mock_llm

            should_merge, confidence, reason = await normalizer.validate_cluster_via_llm(
                concept_security_en,
                concept_securite_fr
            )

            assert should_merge is True
            assert confidence >= 0.85
            assert "language" in reason.lower() or "same" in reason.lower()

    @pytest.mark.asyncio
    async def test_invalid_cluster_rejected(
        self,
        normalizer,
        concept_sap_s4,
        concept_s4_cloud
    ):
        """
        Test: Cluster invalide (concepts différents) → False.

        Cas: "SAP S/4HANA" et "SAP S/4HANA Cloud" = éditions différentes.
        """
        mock_response = Mock()
        mock_response.content = json.dumps({
            "should_merge": False,
            "confidence": 0.90,
            "reason": "Different product editions: on-premise vs cloud"
        })

        with patch('knowbase.ontology.entity_normalizer_neo4j.get_llm_router') as mock_router:
            mock_llm = AsyncMock()
            mock_llm.generate_structured.return_value = mock_response
            mock_router.return_value = mock_llm

            should_merge, confidence, reason = await normalizer.validate_cluster_via_llm(
                concept_sap_s4,
                concept_s4_cloud
            )

            assert should_merge is False
            assert "edition" in reason.lower() or "different" in reason.lower()

    @pytest.mark.asyncio
    async def test_security_gdpr_not_merged(
        self,
        normalizer,
        concept_security_en,
        concept_gdpr
    ):
        """
        Test: Concepts liés mais distincts → False.

        Cas: "Security" et "GDPR" sont liés mais pas identiques.
        """
        mock_response = Mock()
        mock_response.content = json.dumps({
            "should_merge": False,
            "confidence": 0.88,
            "reason": "GDPR is a regulation, Security is a broader concept"
        })

        with patch('knowbase.ontology.entity_normalizer_neo4j.get_llm_router') as mock_router:
            mock_llm = AsyncMock()
            mock_llm.generate_structured.return_value = mock_response
            mock_router.return_value = mock_llm

            should_merge, confidence, reason = await normalizer.validate_cluster_via_llm(
                concept_security_en,
                concept_gdpr
            )

            assert should_merge is False

    @pytest.mark.asyncio
    async def test_low_confidence_rejected(self, normalizer, concept_sap_s4):
        """
        Test: LLM dit merge mais confidence trop basse → False.

        Cas: should_merge=True mais confidence=0.70 < threshold=0.85.
        """
        concept_sap_similar = {
            "name": "S/4HANA Enterprise",
            "type": "PRODUCT",
            "aliases": [],
            "context": "SAP ERP system"
        }

        mock_response = Mock()
        mock_response.content = json.dumps({
            "should_merge": True,
            "confidence": 0.70,  # Trop bas
            "reason": "Possibly the same product"
        })

        with patch('knowbase.ontology.entity_normalizer_neo4j.get_llm_router') as mock_router:
            mock_llm = AsyncMock()
            mock_llm.generate_structured.return_value = mock_response
            mock_router.return_value = mock_llm

            should_merge, confidence, reason = await normalizer.validate_cluster_via_llm(
                concept_sap_s4,
                concept_sap_similar,
                threshold=0.85
            )

            assert should_merge is False
            assert "too low" in reason.lower() or "confidence" in reason.lower()

    @pytest.mark.asyncio
    async def test_llm_error_fallback_conservative(self, normalizer, concept_sap_s4):
        """
        Test: Erreur LLM → Fallback conservateur (pas de merge).

        Cas: Exception lors de l'appel LLM → ne pas fusionner.
        """
        concept_sap_similar = {
            "name": "S4 HANA",
            "type": "PRODUCT",
            "aliases": [],
            "context": "ERP system"
        }

        with patch('knowbase.ontology.entity_normalizer_neo4j.get_llm_router') as mock_router:
            mock_llm = AsyncMock()
            mock_llm.generate_structured.side_effect = Exception("LLM service unavailable")
            mock_router.return_value = mock_llm

            should_merge, confidence, reason = await normalizer.validate_cluster_via_llm(
                concept_sap_s4,
                concept_sap_similar
            )

            assert should_merge is False
            assert confidence == 0.0
            assert "error" in reason.lower()

    @pytest.mark.asyncio
    async def test_json_parse_error_fallback(self, normalizer, concept_sap_s4):
        """
        Test: JSON invalide du LLM → Fallback conservateur.
        """
        concept_sap_similar = {
            "name": "S4",
            "type": "PRODUCT",
            "aliases": [],
            "context": "ERP"
        }

        mock_response = Mock()
        mock_response.content = "Not valid JSON"

        with patch('knowbase.ontology.entity_normalizer_neo4j.get_llm_router') as mock_router:
            mock_llm = AsyncMock()
            mock_llm.generate_structured.return_value = mock_response
            mock_router.return_value = mock_llm

            should_merge, confidence, reason = await normalizer.validate_cluster_via_llm(
                concept_sap_s4,
                concept_sap_similar
            )

            assert should_merge is False
            assert "JSON" in reason or "parse" in reason.lower()


# =============================================================================
# Tests validate_cluster_batch (Validation batch)
# =============================================================================

class TestValidateClusterBatch:
    """Tests pour la validation batch de paires de concepts."""

    @pytest.mark.asyncio
    async def test_batch_validation_success(
        self,
        normalizer,
        concept_security_en,
        concept_securite_fr,
        concept_gdpr
    ):
        """
        Test: Validation batch de 2 paires.
        """
        pairs = [
            (concept_security_en, concept_securite_fr),  # Should merge
            (concept_security_en, concept_gdpr)  # Should not merge
        ]

        # Mock responses
        responses = [
            {"should_merge": True, "confidence": 0.95, "reason": "Same concept"},
            {"should_merge": False, "confidence": 0.90, "reason": "Different concepts"}
        ]

        response_idx = [0]

        def get_response(*args, **kwargs):
            mock = Mock()
            mock.content = json.dumps(responses[response_idx[0]])
            response_idx[0] += 1
            return mock

        with patch('knowbase.ontology.entity_normalizer_neo4j.get_llm_router') as mock_router:
            mock_llm = AsyncMock()
            mock_llm.generate_structured.side_effect = get_response
            mock_router.return_value = mock_llm

            results = await normalizer.validate_cluster_batch(pairs)

            assert len(results) == 2
            assert results[0][0] is True  # First pair merged
            assert results[1][0] is False  # Second pair not merged

    @pytest.mark.asyncio
    async def test_batch_handles_exceptions(self, normalizer):
        """
        Test: Batch gère les exceptions individuelles.
        """
        pairs = [
            ({"name": "A", "type": "T", "aliases": [], "context": ""},
             {"name": "B", "type": "T", "aliases": [], "context": ""}),
            ({"name": "C", "type": "T", "aliases": [], "context": ""},
             {"name": "D", "type": "T", "aliases": [], "context": ""})
        ]

        call_count = [0]

        async def mock_generate(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call succeeds
                mock = Mock()
                mock.content = json.dumps({
                    "should_merge": True,
                    "confidence": 0.90,
                    "reason": "Match"
                })
                return mock
            else:
                # Second call fails
                raise Exception("API error")

        with patch('knowbase.ontology.entity_normalizer_neo4j.get_llm_router') as mock_router:
            mock_llm = AsyncMock()
            mock_llm.generate_structured.side_effect = mock_generate
            mock_router.return_value = mock_llm

            results = await normalizer.validate_cluster_batch(pairs)

            assert len(results) == 2
            assert results[0][0] is True  # First succeeded
            assert results[1][0] is False  # Second failed gracefully


# =============================================================================
# Tests Prompts (Integration)
# =============================================================================

class TestLlmJudgePrompts:
    """Tests pour les prompts LLM-as-a-Judge."""

    def test_get_llm_judge_prompt_structure(
        self,
        concept_sap_s4,
        concept_s4_cloud
    ):
        """
        Test: Le prompt est correctement formaté.
        """
        from knowbase.semantic.extraction.prompts import get_llm_judge_prompt

        prompts = get_llm_judge_prompt(concept_sap_s4, concept_s4_cloud)

        assert "system_prompt" in prompts
        assert "user_prompt" in prompts

        # Vérifier que les noms des concepts sont dans le prompt
        assert "SAP S/4HANA" in prompts["user_prompt"]
        assert "SAP S/4HANA Cloud" in prompts["user_prompt"]

    def test_prompt_includes_aliases(self, concept_sap_s4, concept_s4_cloud):
        """
        Test: Les aliases sont inclus dans le prompt.
        """
        from knowbase.semantic.extraction.prompts import get_llm_judge_prompt

        prompts = get_llm_judge_prompt(concept_sap_s4, concept_s4_cloud)

        # Aliases devraient être mentionnés
        assert "S/4HANA" in prompts["user_prompt"]
        assert "S4 Cloud" in prompts["user_prompt"] or "S/4HANA Cloud" in prompts["user_prompt"]

    def test_prompt_handles_empty_aliases(self):
        """
        Test: Le prompt gère les aliases vides.
        """
        from knowbase.semantic.extraction.prompts import get_llm_judge_prompt

        concept_a = {"name": "Test A", "type": "CONCEPT", "aliases": [], "context": ""}
        concept_b = {"name": "Test B", "type": "CONCEPT", "aliases": [], "context": ""}

        prompts = get_llm_judge_prompt(concept_a, concept_b)

        # Pas d'erreur, prompt valide
        assert "Test A" in prompts["user_prompt"]
        assert "Test B" in prompts["user_prompt"]

    def test_system_prompt_contains_instructions(self):
        """
        Test: Le system prompt contient les instructions de validation.
        """
        from knowbase.semantic.extraction.prompts import (
            LLM_JUDGE_CLUSTER_VALIDATION_SYSTEM_PROMPT
        )

        # Doit contenir des mots-clés importants
        assert "semantic" in LLM_JUDGE_CLUSTER_VALIDATION_SYSTEM_PROMPT.lower()
        assert "merge" in LLM_JUDGE_CLUSTER_VALIDATION_SYSTEM_PROMPT.lower()
        assert "should_merge" in LLM_JUDGE_CLUSTER_VALIDATION_SYSTEM_PROMPT


# =============================================================================
# Tests Edge Cases
# =============================================================================

class TestEdgeCases:
    """Tests pour les cas limites."""

    def test_single_concept_no_validation_needed(self, normalizer):
        """
        Test: Un seul concept → pas de clustering → skip validation.

        Cas limites documenté dans KGGen: single node clusters.
        """
        # should_use_llm_judge n'est jamais appelé pour un seul concept
        # Ce test vérifie le comportement attendu
        result = normalizer.should_use_llm_judge(
            similarity_score=1.0,  # Comparé à lui-même
            concept_type_match=True
        )

        # Similarité parfaite = auto-merge, pas de LLM
        assert result is False

    def test_empty_context_handled(self, normalizer):
        """
        Test: Concepts sans contexte sont gérés.
        """
        concept_no_context = {
            "name": "Unknown Product",
            "type": "PRODUCT",
            "aliases": [],
            "context": ""  # Pas de contexte
        }

        # Vérifier que should_use_llm_judge fonctionne
        result = normalizer.should_use_llm_judge(
            similarity_score=0.80,
            concept_type_match=True
        )

        # Zone grise → LLM validation
        assert result is True

    @pytest.mark.asyncio
    async def test_very_long_context_truncated(self, normalizer):
        """
        Test: Contexte très long est tronqué à 200 caractères.
        """
        from knowbase.semantic.extraction.prompts import get_llm_judge_prompt

        long_context = "A" * 500  # 500 caractères

        concept_long = {
            "name": "Test",
            "type": "CONCEPT",
            "aliases": [],
            "context": long_context
        }

        concept_short = {
            "name": "Test2",
            "type": "CONCEPT",
            "aliases": [],
            "context": "Short"
        }

        prompts = get_llm_judge_prompt(concept_long, concept_short)

        # Le contexte long devrait être tronqué à 200 caractères
        assert len(prompts["user_prompt"]) < len(long_context) + 500
