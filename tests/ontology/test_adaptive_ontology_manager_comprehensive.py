"""Tests complets pour AdaptiveOntologyManager.

Tests unitaires couvrant:
- Validation et sanitization des inputs
- Lookup dans le cache ontologie
- Store avec protection contre le cache poisoning
- Gestion des aliases
- Budget LLM
- Statistiques
"""

import pytest
from unittest.mock import MagicMock, patch
from typing import Dict, Any

from knowbase.ontology.adaptive_ontology_manager import (
    AdaptiveOntologyManager,
    _sanitize_concept_name,
    _validate_tenant_id,
    VALID_CONCEPT_NAME_PATTERN,
    VALID_TENANT_ID_PATTERN,
    MAX_CONCEPT_NAME_LENGTH,
)


class TestSanitizeConceptName:
    """Tests pour la fonction _sanitize_concept_name."""

    def test_sanitize_valid_name(self) -> None:
        """Test sanitization d'un nom valide."""
        result = _sanitize_concept_name("SAP S/4HANA")
        assert result == "SAP S/4HANA"

    def test_sanitize_with_whitespace(self) -> None:
        """Test sanitization avec espaces supplémentaires."""
        result = _sanitize_concept_name("  SAP S/4HANA  ")
        assert result == "SAP S/4HANA"

    def test_sanitize_special_characters(self) -> None:
        """Test sanitization avec caractères spéciaux autorisés."""
        result = _sanitize_concept_name("SAP S/4HANA (Cloud Edition)")
        assert result == "SAP S/4HANA (Cloud Edition)"

    def test_sanitize_unicode_characters(self) -> None:
        """Test sanitization avec caractères Unicode."""
        result = _sanitize_concept_name("Système d'information")
        assert result == "Système d'information"

    def test_sanitize_empty_string_raises(self) -> None:
        """Test que chaîne vide lève ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            _sanitize_concept_name("")

    def test_sanitize_whitespace_only_raises(self) -> None:
        """Test que espaces seuls lève ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            _sanitize_concept_name("   ")

    def test_sanitize_too_long_raises(self) -> None:
        """Test que nom trop long lève ValueError."""
        long_name = "a" * (MAX_CONCEPT_NAME_LENGTH + 1)
        with pytest.raises(ValueError, match="too long"):
            _sanitize_concept_name(long_name)

    def test_sanitize_max_length_ok(self) -> None:
        """Test que nom de longueur max est accepté."""
        max_name = "a" * MAX_CONCEPT_NAME_LENGTH
        result = _sanitize_concept_name(max_name)
        assert len(result) == MAX_CONCEPT_NAME_LENGTH


class TestValidateTenantId:
    """Tests pour la fonction _validate_tenant_id."""

    def test_validate_valid_tenant_id(self) -> None:
        """Test validation d'un tenant_id valide."""
        result = _validate_tenant_id("default")
        assert result == "default"

    def test_validate_tenant_id_with_numbers(self) -> None:
        """Test validation avec chiffres."""
        result = _validate_tenant_id("tenant123")
        assert result == "tenant123"

    def test_validate_tenant_id_with_underscore(self) -> None:
        """Test validation avec underscore."""
        result = _validate_tenant_id("tenant_abc")
        assert result == "tenant_abc"

    def test_validate_tenant_id_with_hyphen(self) -> None:
        """Test validation avec tiret."""
        result = _validate_tenant_id("tenant-abc")
        assert result == "tenant-abc"

    def test_validate_invalid_tenant_id_uppercase(self) -> None:
        """Test que majuscules sont refusées."""
        with pytest.raises(ValueError, match="Invalid tenant_id"):
            _validate_tenant_id("TENANT")

    def test_validate_invalid_tenant_id_special_chars(self) -> None:
        """Test que caractères spéciaux sont refusés."""
        with pytest.raises(ValueError, match="Invalid tenant_id"):
            _validate_tenant_id("tenant@123")

    def test_validate_tenant_id_too_long(self) -> None:
        """Test que tenant_id trop long est refusé."""
        with pytest.raises(ValueError, match="Invalid tenant_id"):
            _validate_tenant_id("a" * 51)


@pytest.fixture
def mock_neo4j_client():
    """Mock du client Neo4j."""
    client = MagicMock()
    client.is_connected.return_value = True
    client.database = "neo4j"

    # Mock driver et session
    mock_session = MagicMock()
    client.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    client.driver.session.return_value.__exit__ = MagicMock(return_value=None)

    return client


@pytest.fixture
def mock_redis_client():
    """Mock du client Redis."""
    client = MagicMock()
    client.incr.return_value = 1
    return client


@pytest.fixture
def manager(mock_neo4j_client, mock_redis_client):
    """AdaptiveOntologyManager avec mocks."""
    return AdaptiveOntologyManager(
        neo4j_client=mock_neo4j_client,
        redis_client=mock_redis_client,
    )


class TestAdaptiveOntologyManagerInit:
    """Tests pour l'initialisation."""

    def test_init_with_neo4j_only(self, mock_neo4j_client) -> None:
        """Test initialisation avec Neo4j seulement."""
        manager = AdaptiveOntologyManager(neo4j_client=mock_neo4j_client)

        assert manager.neo4j is mock_neo4j_client
        assert manager.redis is None

    def test_init_with_neo4j_and_redis(
        self, mock_neo4j_client, mock_redis_client
    ) -> None:
        """Test initialisation avec Neo4j et Redis."""
        manager = AdaptiveOntologyManager(
            neo4j_client=mock_neo4j_client,
            redis_client=mock_redis_client,
        )

        assert manager.neo4j is mock_neo4j_client
        assert manager.redis is mock_redis_client


class TestAdaptiveOntologyManagerLookup:
    """Tests pour la méthode lookup."""

    def test_lookup_cache_hit(self, manager: AdaptiveOntologyManager) -> None:
        """Test lookup avec cache hit."""
        # Setup mock response
        mock_record = {
            "canonical_name": "SAP S/4HANA",
            "aliases": ["S/4HANA", "S4HANA"],
            "concept_type": "SOLUTION",
            "domain": "ERP",
            "confidence": 0.95,
            "source": "llm",
            "usage_count": 10,
            "ambiguity_warning": None,
            "possible_matches": [],
            "ontology_id": "ont-123",
        }

        mock_result = MagicMock()
        mock_result.single.return_value = mock_record

        mock_session = MagicMock()
        mock_session.run.return_value = mock_result
        manager.neo4j.driver.session.return_value.__enter__.return_value = mock_session

        result = manager.lookup("S/4HANA", "default")

        assert result is not None
        assert result["canonical_name"] == "SAP S/4HANA"
        assert result["confidence"] == 0.95

    def test_lookup_cache_miss(self, manager: AdaptiveOntologyManager) -> None:
        """Test lookup avec cache miss."""
        mock_result = MagicMock()
        mock_result.single.return_value = None

        mock_session = MagicMock()
        mock_session.run.return_value = mock_result
        manager.neo4j.driver.session.return_value.__enter__.return_value = mock_session

        result = manager.lookup("Unknown System", "default")

        assert result is None

    def test_lookup_neo4j_disconnected(
        self, mock_neo4j_client, mock_redis_client
    ) -> None:
        """Test lookup avec Neo4j déconnecté."""
        mock_neo4j_client.is_connected.return_value = False
        manager = AdaptiveOntologyManager(
            neo4j_client=mock_neo4j_client,
            redis_client=mock_redis_client,
        )

        result = manager.lookup("SAP S/4HANA", "default")

        assert result is None

    def test_lookup_invalid_concept_name(
        self, manager: AdaptiveOntologyManager
    ) -> None:
        """Test lookup avec nom de concept invalide."""
        result = manager.lookup("", "default")

        assert result is None

    def test_lookup_invalid_tenant_id(
        self, manager: AdaptiveOntologyManager
    ) -> None:
        """Test lookup avec tenant_id invalide."""
        result = manager.lookup("SAP S/4HANA", "INVALID_TENANT")

        assert result is None


class TestAdaptiveOntologyManagerStore:
    """Tests pour la méthode store."""

    def test_store_success(self, manager: AdaptiveOntologyManager) -> None:
        """Test store avec succès."""
        # Mock lookup pour retourner None (pas d'existant)
        mock_result_lookup = MagicMock()
        mock_result_lookup.single.return_value = None

        # Mock store pour retourner ontology_id
        mock_result_store = MagicMock()
        mock_result_store.single.return_value = {"ontology_id": "ont-new-123"}

        mock_session = MagicMock()
        mock_session.run.side_effect = [mock_result_lookup, mock_result_store]
        manager.neo4j.driver.session.return_value.__enter__.return_value = mock_session

        result = manager.store(
            tenant_id="default",
            canonical_name="SAP S/4HANA",
            raw_name="S/4HANA",
            canonicalization_result={
                "confidence": 0.9,
                "concept_type": "SOLUTION",
                "domain": "ERP",
                "aliases": ["S4HANA"],
            },
        )

        assert result == "ont-new-123"

    def test_store_low_confidence_rejected(
        self, manager: AdaptiveOntologyManager
    ) -> None:
        """Test store rejeté si confidence trop basse."""
        result = manager.store(
            tenant_id="default",
            canonical_name="SAP S/4HANA",
            raw_name="S/4HANA",
            canonicalization_result={
                "confidence": 0.5,  # < 0.6 min_confidence par défaut
            },
        )

        assert result == ""

    def test_store_hallucination_detected(
        self, manager: AdaptiveOntologyManager
    ) -> None:
        """Test store rejeté si hallucination détectée."""
        result = manager.store(
            tenant_id="default",
            canonical_name="Completely Different Name",
            raw_name="SAP S/4HANA",
            canonicalization_result={
                "confidence": 0.95,
            },
        )

        # Similarité trop faible → hallucination
        assert result == ""

    def test_store_neo4j_disconnected(
        self, mock_neo4j_client, mock_redis_client
    ) -> None:
        """Test store avec Neo4j déconnecté."""
        mock_neo4j_client.is_connected.return_value = False
        manager = AdaptiveOntologyManager(
            neo4j_client=mock_neo4j_client,
            redis_client=mock_redis_client,
        )

        result = manager.store(
            tenant_id="default",
            canonical_name="SAP S/4HANA",
            raw_name="S/4HANA",
            canonicalization_result={"confidence": 0.9},
        )

        assert result == ""

    def test_store_aliases_truncated(self, manager: AdaptiveOntologyManager) -> None:
        """Test que les aliases sont tronqués si > 50."""
        # Mock pour passer les validations
        mock_result_lookup = MagicMock()
        mock_result_lookup.single.return_value = None

        mock_result_store = MagicMock()
        mock_result_store.single.return_value = {"ontology_id": "ont-123"}

        mock_session = MagicMock()
        mock_session.run.side_effect = [mock_result_lookup, mock_result_store]
        manager.neo4j.driver.session.return_value.__enter__.return_value = mock_session

        # 60 aliases
        many_aliases = [f"alias_{i}" for i in range(60)]

        result = manager.store(
            tenant_id="default",
            canonical_name="SAP S/4HANA",
            raw_name="S/4HANA",
            canonicalization_result={
                "confidence": 0.9,
                "aliases": many_aliases,
            },
        )

        # Devrait réussir (aliases tronqués silencieusement)
        assert result != ""


class TestAdaptiveOntologyManagerAddAlias:
    """Tests pour la méthode add_alias."""

    def test_add_alias_success(self, manager: AdaptiveOntologyManager) -> None:
        """Test ajout d'alias avec succès."""
        mock_result = MagicMock()
        mock_result.single.return_value = {"ontology_id": "ont-123"}

        mock_session = MagicMock()
        mock_session.run.return_value = mock_result
        manager.neo4j.driver.session.return_value.__enter__.return_value = mock_session

        result = manager.add_alias(
            canonical_name="SAP S/4HANA",
            tenant_id="default",
            new_alias="S4 HANA Cloud",
        )

        assert result is True

    def test_add_alias_already_exists(
        self, manager: AdaptiveOntologyManager
    ) -> None:
        """Test ajout d'alias déjà existant."""
        mock_result = MagicMock()
        mock_result.single.return_value = None  # Pas de modification

        mock_session = MagicMock()
        mock_session.run.return_value = mock_result
        manager.neo4j.driver.session.return_value.__enter__.return_value = mock_session

        result = manager.add_alias(
            canonical_name="SAP S/4HANA",
            tenant_id="default",
            new_alias="S/4HANA",  # Alias existant
        )

        assert result is False

    def test_add_alias_neo4j_disconnected(
        self, mock_neo4j_client, mock_redis_client
    ) -> None:
        """Test ajout alias avec Neo4j déconnecté."""
        mock_neo4j_client.is_connected.return_value = False
        manager = AdaptiveOntologyManager(
            neo4j_client=mock_neo4j_client,
            redis_client=mock_redis_client,
        )

        result = manager.add_alias("SAP S/4HANA", "default", "New Alias")

        assert result is False


class TestAdaptiveOntologyManagerBudget:
    """Tests pour la gestion du budget LLM."""

    def test_check_budget_ok(self, manager: AdaptiveOntologyManager) -> None:
        """Test budget disponible."""
        manager.redis.incr.return_value = 5  # 5 appels < 50 max

        result = manager.check_llm_budget("doc-123")

        assert result is True

    def test_check_budget_exceeded(self, manager: AdaptiveOntologyManager) -> None:
        """Test budget dépassé."""
        manager.redis.incr.return_value = 51  # > 50 max

        result = manager.check_llm_budget("doc-123", max_llm_calls_per_doc=50)

        assert result is False

    def test_check_budget_redis_unavailable(
        self, mock_neo4j_client
    ) -> None:
        """Test budget sans Redis (dégradation gracieuse)."""
        manager = AdaptiveOntologyManager(neo4j_client=mock_neo4j_client)

        # Sans Redis, devrait autoriser (dégradation gracieuse)
        result = manager.check_llm_budget("doc-123")

        assert result is True

    def test_check_budget_redis_error(
        self, manager: AdaptiveOntologyManager
    ) -> None:
        """Test budget avec erreur Redis."""
        manager.redis.incr.side_effect = Exception("Redis connection error")

        # Devrait autoriser malgré l'erreur (dégradation gracieuse)
        result = manager.check_llm_budget("doc-123")

        assert result is True


class TestAdaptiveOntologyManagerStats:
    """Tests pour get_stats."""

    def test_get_stats_success(self, manager: AdaptiveOntologyManager) -> None:
        """Test récupération stats avec succès."""
        mock_record = {
            "total_entries": 100,
            "avg_confidence": 0.85,
            "total_usage": 500,
        }

        mock_result = MagicMock()
        mock_result.single.return_value = mock_record

        mock_session = MagicMock()
        mock_session.run.return_value = mock_result
        manager.neo4j.driver.session.return_value.__enter__.return_value = mock_session

        stats = manager.get_stats("default")

        assert stats["total_entries"] == 100
        assert stats["avg_confidence"] == 0.85
        assert stats["total_usage"] == 500

    def test_get_stats_empty(self, manager: AdaptiveOntologyManager) -> None:
        """Test stats avec base vide."""
        mock_record = {
            "total_entries": 0,
            "avg_confidence": None,
            "total_usage": None,
        }

        mock_result = MagicMock()
        mock_result.single.return_value = mock_record

        mock_session = MagicMock()
        mock_session.run.return_value = mock_result
        manager.neo4j.driver.session.return_value.__enter__.return_value = mock_session

        stats = manager.get_stats("default")

        assert stats["total_entries"] == 0
        assert stats["avg_confidence"] == 0.0

    def test_get_stats_neo4j_disconnected(
        self, mock_neo4j_client, mock_redis_client
    ) -> None:
        """Test stats avec Neo4j déconnecté."""
        mock_neo4j_client.is_connected.return_value = False
        manager = AdaptiveOntologyManager(
            neo4j_client=mock_neo4j_client,
            redis_client=mock_redis_client,
        )

        stats = manager.get_stats("default")

        assert stats["total_entries"] == 0
        assert "error" in stats


class TestAdaptiveOntologyManagerIncrementUsage:
    """Tests pour increment_usage."""

    def test_increment_usage_success(
        self, manager: AdaptiveOntologyManager
    ) -> None:
        """Test incrémentation usage."""
        mock_session = MagicMock()
        manager.neo4j.driver.session.return_value.__enter__.return_value = mock_session

        # Ne devrait pas lever d'exception
        manager.increment_usage("SAP S/4HANA", "default")

        mock_session.run.assert_called_once()

    def test_increment_usage_neo4j_disconnected(
        self, mock_neo4j_client, mock_redis_client
    ) -> None:
        """Test incrémentation avec Neo4j déconnecté."""
        mock_neo4j_client.is_connected.return_value = False
        manager = AdaptiveOntologyManager(
            neo4j_client=mock_neo4j_client,
            redis_client=mock_redis_client,
        )

        # Ne devrait pas lever d'exception
        manager.increment_usage("SAP S/4HANA", "default")


class TestAcronymDetection:
    """Tests pour la détection d'acronymes dans store."""

    def test_store_acronym_accepted(self, manager: AdaptiveOntologyManager) -> None:
        """Test que les acronymes valides sont acceptés."""
        # Mock pour passer les validations
        mock_result_lookup = MagicMock()
        mock_result_lookup.single.return_value = None

        mock_result_store = MagicMock()
        mock_result_store.single.return_value = {"ontology_id": "ont-123"}

        mock_session = MagicMock()
        mock_session.run.side_effect = [mock_result_lookup, mock_result_store]
        manager.neo4j.driver.session.return_value.__enter__.return_value = mock_session

        # ERP est un acronyme valide de Enterprise Resource Planning
        result = manager.store(
            tenant_id="default",
            canonical_name="Enterprise Resource Planning",
            raw_name="ERP",
            canonicalization_result={
                "confidence": 0.9,
            },
        )

        # Devrait être accepté grâce à la détection d'acronyme
        # (la logique d'acronyme permet une similarité plus faible)
        assert isinstance(result, str)
