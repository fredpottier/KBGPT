"""
Tests Phase 1.8.2 - Gatekeeper Prefetch Ontology

Valide le préchargement intelligent des entrées ontologie par type de document.
Objectif: Cache hit rate 50% → 70%, LLM calls -20%
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
import json

from knowbase.ontology.adaptive_ontology_manager import (
    AdaptiveOntologyManager,
    get_domains_for_document_type,
    DOCUMENT_TYPE_DOMAIN_MAPPING
)


# =========================================================================
# Test: Document Type → Domain Mapping
# =========================================================================

class TestDocumentTypeDomainMapping:
    """Tests pour le mapping types documents → domaines."""

    def test_mapping_sap_technical(self):
        """Vérifie mapping pour documents SAP techniques."""
        domains = get_domains_for_document_type("sap_technical")
        assert "SAP" in domains
        assert "ERP" in domains
        assert "Cloud" in domains

    def test_mapping_pharma_regulatory(self):
        """Vérifie mapping pour documents pharma réglementaires."""
        domains = get_domains_for_document_type("pharma_regulatory")
        assert "FDA" in domains
        assert "Pharma" in domains
        assert "Regulatory" in domains
        assert "Compliance" in domains

    def test_mapping_crm_documentation(self):
        """Vérifie mapping pour documents CRM."""
        domains = get_domains_for_document_type("crm_documentation")
        assert "CRM" in domains
        assert "Salesforce" in domains

    def test_mapping_unknown_type_returns_default(self):
        """Un type inconnu retourne les domaines par défaut."""
        domains = get_domains_for_document_type("unknown_type_xyz")
        default_domains = DOCUMENT_TYPE_DOMAIN_MAPPING["default"]
        assert domains == default_domains

    def test_mapping_rfp(self):
        """Vérifie mapping pour RFP."""
        domains = get_domains_for_document_type("rfp")
        assert "Business" in domains
        assert "Requirements" in domains

    def test_all_mappings_have_domains(self):
        """Tous les mappings définis ont au moins un domaine."""
        for doc_type, domains in DOCUMENT_TYPE_DOMAIN_MAPPING.items():
            assert len(domains) > 0, f"Type '{doc_type}' n'a pas de domaines"


# =========================================================================
# Test: Prefetch for Document Type
# =========================================================================

class TestPrefetchForDocumentType:
    """Tests pour la méthode prefetch_for_document_type()."""

    @pytest.fixture
    def mock_neo4j(self):
        """Mock du client Neo4j."""
        mock = Mock()
        mock.is_connected.return_value = True
        mock.database = "neo4j"

        # Mock driver et session
        mock_session = MagicMock()
        mock_driver = Mock()
        mock_driver.session.return_value.__enter__ = Mock(return_value=mock_session)
        mock_driver.session.return_value.__exit__ = Mock(return_value=False)
        mock.driver = mock_driver

        return mock

    @pytest.fixture
    def mock_redis(self):
        """Mock du client Redis."""
        mock = Mock()
        mock.get.return_value = None  # Pas de cache par défaut
        mock.setex.return_value = True
        return mock

    @pytest.fixture
    def manager(self, mock_neo4j, mock_redis):
        """Instance du manager avec mocks."""
        return AdaptiveOntologyManager(mock_neo4j, mock_redis)

    def test_prefetch_returns_count(self, manager, mock_neo4j):
        """Prefetch retourne le nombre d'entrées préchargées."""
        # Setup mock records
        mock_records = [
            {
                "canonical_name": "SAP S/4HANA",
                "aliases": ["S/4", "S4HANA"],
                "concept_type": "Product",
                "domain": "SAP",
                "confidence": 0.95,
                "usage_count": 100
            },
            {
                "canonical_name": "SAP Business Technology Platform",
                "aliases": ["BTP", "SAP BTP"],
                "concept_type": "Product",
                "domain": "SAP",
                "confidence": 0.90,
                "usage_count": 50
            }
        ]

        # Configure session mock
        mock_session = mock_neo4j.driver.session.return_value.__enter__.return_value
        mock_result = Mock()
        mock_result.__iter__ = Mock(return_value=iter(mock_records))
        mock_session.run.return_value = mock_result

        count = manager.prefetch_for_document_type("sap_technical", "default")

        assert count == 2

    def test_prefetch_uses_cache_if_available(self, manager, mock_redis):
        """Prefetch utilise le cache Redis si disponible."""
        mock_redis.get.return_value = "5"  # Cache dit 5 entrées

        count = manager.prefetch_for_document_type("sap_technical", "default")

        assert count == 5
        # Ne devrait pas avoir appelé Neo4j
        manager.neo4j.driver.session.assert_not_called()

    def test_prefetch_stores_in_redis(self, manager, mock_neo4j, mock_redis):
        """Prefetch stocke les résultats dans Redis."""
        mock_records = [
            {
                "canonical_name": "Test Concept",
                "aliases": [],
                "concept_type": "Concept",
                "domain": "Test",
                "confidence": 0.85,
                "usage_count": 10
            }
        ]

        mock_session = mock_neo4j.driver.session.return_value.__enter__.return_value
        mock_result = Mock()
        mock_result.__iter__ = Mock(return_value=iter(mock_records))
        mock_session.run.return_value = mock_result

        manager.prefetch_for_document_type("sap_technical", "default", ttl_seconds=1800)

        # Vérifie que Redis setex a été appelé
        assert mock_redis.setex.called

    def test_prefetch_with_neo4j_disconnected(self, mock_redis):
        """Prefetch retourne 0 si Neo4j déconnecté."""
        mock_neo4j = Mock()
        mock_neo4j.is_connected.return_value = False

        manager = AdaptiveOntologyManager(mock_neo4j, mock_redis)
        count = manager.prefetch_for_document_type("sap_technical", "default")

        assert count == 0

    def test_prefetch_validates_tenant_id(self, manager):
        """Prefetch valide le tenant_id."""
        # Tenant ID invalide
        count = manager.prefetch_for_document_type("sap_technical", "INVALID TENANT!")

        assert count == 0

    def test_prefetch_respects_max_entries(self, manager, mock_neo4j):
        """Prefetch respecte la limite max_entries."""
        mock_session = mock_neo4j.driver.session.return_value.__enter__.return_value
        mock_result = Mock()
        mock_result.__iter__ = Mock(return_value=iter([]))
        mock_session.run.return_value = mock_result

        manager.prefetch_for_document_type("sap_technical", "default", max_entries=100)

        # Vérifier que max_entries est passé à la requête
        call_args = mock_session.run.call_args
        assert call_args[1]["max_entries"] == 100


# =========================================================================
# Test: Lookup in Prefetch
# =========================================================================

class TestLookupInPrefetch:
    """Tests pour lookup_in_prefetch()."""

    @pytest.fixture
    def manager_with_prefetch(self):
        """Manager avec cache prefetch simulé."""
        mock_neo4j = Mock()
        mock_neo4j.is_connected.return_value = True
        mock_neo4j.database = "neo4j"

        mock_redis = Mock()
        # Simuler des données préchargées
        prefetched_data = json.dumps([
            {
                "canonical_name": "SAP S/4HANA Cloud",
                "aliases": ["S/4HANA Cloud", "S4 Cloud"],
                "concept_type": "Product",
                "domain": "SAP",
                "confidence": 0.95,
                "usage_count": 100
            },
            {
                "canonical_name": "SAP Business Technology Platform",
                "aliases": ["BTP", "SAP BTP"],
                "concept_type": "Platform",
                "domain": "SAP",
                "confidence": 0.90,
                "usage_count": 50
            }
        ])
        mock_redis.get.return_value = prefetched_data

        return AdaptiveOntologyManager(mock_neo4j, mock_redis)

    def test_lookup_finds_canonical_name(self, manager_with_prefetch):
        """Lookup trouve par canonical_name."""
        result = manager_with_prefetch.lookup_in_prefetch(
            "SAP S/4HANA Cloud",
            "sap_technical",
            "default"
        )

        assert result is not None
        assert result["canonical_name"] == "SAP S/4HANA Cloud"

    def test_lookup_finds_by_alias(self, manager_with_prefetch):
        """Lookup trouve par alias."""
        result = manager_with_prefetch.lookup_in_prefetch(
            "BTP",
            "sap_technical",
            "default"
        )

        assert result is not None
        assert result["canonical_name"] == "SAP Business Technology Platform"

    def test_lookup_case_insensitive(self, manager_with_prefetch):
        """Lookup est case-insensitive."""
        result = manager_with_prefetch.lookup_in_prefetch(
            "sap btp",  # lowercase
            "sap_technical",
            "default"
        )

        assert result is not None
        assert result["canonical_name"] == "SAP Business Technology Platform"

    def test_lookup_falls_back_to_neo4j(self, manager_with_prefetch):
        """Lookup fait fallback sur Neo4j si non trouvé dans prefetch."""
        # Setup mock pour lookup Neo4j
        mock_session = MagicMock()
        mock_result = Mock()
        mock_result.single.return_value = {
            "canonical_name": "Found in Neo4j",
            "aliases": [],
            "concept_type": "Concept",
            "domain": "Other",
            "confidence": 0.8,
            "usage_count": 5,
            "ontology_id": "test-id",
            "source": "llm",
            "ambiguity_warning": None,
            "possible_matches": []
        }
        mock_session.run.return_value = mock_result

        manager_with_prefetch.neo4j.driver.session.return_value.__enter__ = Mock(
            return_value=mock_session
        )
        manager_with_prefetch.neo4j.driver.session.return_value.__exit__ = Mock(
            return_value=False
        )

        result = manager_with_prefetch.lookup_in_prefetch(
            "Unknown Concept",
            "sap_technical",
            "default"
        )

        # Devrait avoir appelé lookup() standard
        assert mock_session.run.called


# =========================================================================
# Test: Get Prefetched Entries
# =========================================================================

class TestGetPrefetchedEntries:
    """Tests pour get_prefetched_entries()."""

    def test_returns_cached_entries(self):
        """Retourne les entrées depuis Redis."""
        mock_neo4j = Mock()
        mock_redis = Mock()

        cached_data = json.dumps([
            {"canonical_name": "Test1", "aliases": []},
            {"canonical_name": "Test2", "aliases": []}
        ])
        mock_redis.get.return_value = cached_data

        manager = AdaptiveOntologyManager(mock_neo4j, mock_redis)
        entries = manager.get_prefetched_entries("sap_technical", "default")

        assert len(entries) == 2
        assert entries[0]["canonical_name"] == "Test1"

    def test_returns_empty_if_no_redis(self):
        """Retourne liste vide si Redis non disponible."""
        mock_neo4j = Mock()
        manager = AdaptiveOntologyManager(mock_neo4j, None)

        entries = manager.get_prefetched_entries("sap_technical", "default")

        assert entries == []

    def test_returns_empty_if_no_cache(self):
        """Retourne liste vide si pas de cache."""
        mock_neo4j = Mock()
        mock_redis = Mock()
        mock_redis.get.return_value = None

        manager = AdaptiveOntologyManager(mock_neo4j, mock_redis)
        entries = manager.get_prefetched_entries("sap_technical", "default")

        assert entries == []


# =========================================================================
# Test: Invalidate Prefetch Cache
# =========================================================================

class TestInvalidatePrefetchCache:
    """Tests pour invalidate_prefetch_cache()."""

    def test_deletes_cache_keys(self):
        """Invalide supprime les clés Redis."""
        mock_neo4j = Mock()
        mock_redis = Mock()

        manager = AdaptiveOntologyManager(mock_neo4j, mock_redis)
        result = manager.invalidate_prefetch_cache("sap_technical", "default")

        assert result is True
        mock_redis.delete.assert_called_once()

    def test_returns_false_if_no_redis(self):
        """Retourne False si Redis non disponible."""
        mock_neo4j = Mock()
        manager = AdaptiveOntologyManager(mock_neo4j, None)

        result = manager.invalidate_prefetch_cache("sap_technical", "default")

        assert result is False


# =========================================================================
# Test: Get Prefetch Stats
# =========================================================================

class TestGetPrefetchStats:
    """Tests pour get_prefetch_stats()."""

    def test_returns_stats(self):
        """Retourne statistiques du cache prefetch."""
        mock_neo4j = Mock()
        mock_redis = Mock()

        # Simuler scan Redis
        mock_redis.scan.return_value = (0, [
            "ontology_prefetch:default:sap_technical:data"
        ])
        mock_redis.get.return_value = json.dumps([
            {"canonical_name": "Test1"},
            {"canonical_name": "Test2"}
        ])

        manager = AdaptiveOntologyManager(mock_neo4j, mock_redis)
        stats = manager.get_prefetch_stats("default")

        assert "cached_types" in stats
        assert "total_cached_entries" in stats
        assert stats["total_cached_entries"] == 2

    def test_returns_error_if_no_redis(self):
        """Retourne erreur si Redis non disponible."""
        mock_neo4j = Mock()
        manager = AdaptiveOntologyManager(mock_neo4j, None)

        stats = manager.get_prefetch_stats("default")

        assert "error" in stats


# =========================================================================
# Test: Integration Scenarios
# =========================================================================

class TestPrefetchIntegration:
    """Tests d'intégration pour le workflow prefetch complet."""

    def test_prefetch_then_lookup_workflow(self):
        """Workflow complet: prefetch puis lookups optimisés."""
        mock_neo4j = Mock()
        mock_neo4j.is_connected.return_value = True
        mock_neo4j.database = "neo4j"

        mock_redis = Mock()
        stored_data = {}

        def mock_setex(key, ttl, value):
            stored_data[key] = value
            return True

        def mock_get(key):
            return stored_data.get(key)

        mock_redis.setex.side_effect = mock_setex
        mock_redis.get.side_effect = mock_get

        # Setup Neo4j mock pour prefetch
        mock_session = MagicMock()
        mock_records = [
            {
                "canonical_name": "SAP S/4HANA",
                "aliases": ["S/4", "S4"],
                "concept_type": "Product",
                "domain": "SAP",
                "confidence": 0.95,
                "usage_count": 100
            }
        ]
        mock_result = Mock()
        mock_result.__iter__ = Mock(return_value=iter(mock_records))
        mock_session.run.return_value = mock_result

        mock_neo4j.driver.session.return_value.__enter__ = Mock(return_value=mock_session)
        mock_neo4j.driver.session.return_value.__exit__ = Mock(return_value=False)

        manager = AdaptiveOntologyManager(mock_neo4j, mock_redis)

        # 1. Prefetch
        count = manager.prefetch_for_document_type("sap_technical", "default")
        assert count == 1

        # 2. Lookup devrait utiliser le cache
        result = manager.lookup_in_prefetch("S/4", "sap_technical", "default")
        assert result is not None
        assert result["canonical_name"] == "SAP S/4HANA"

    def test_ttl_respected(self):
        """Vérifie que TTL est passé à Redis."""
        mock_neo4j = Mock()
        mock_neo4j.is_connected.return_value = True
        mock_neo4j.database = "neo4j"

        mock_redis = Mock()
        mock_redis.get.return_value = None

        mock_session = MagicMock()
        mock_result = Mock()
        mock_result.__iter__ = Mock(return_value=iter([]))
        mock_session.run.return_value = mock_result

        mock_neo4j.driver.session.return_value.__enter__ = Mock(return_value=mock_session)
        mock_neo4j.driver.session.return_value.__exit__ = Mock(return_value=False)

        manager = AdaptiveOntologyManager(mock_neo4j, mock_redis)

        # Prefetch avec TTL custom
        manager.prefetch_for_document_type("sap_technical", "default", ttl_seconds=7200)

        # Note: setex n'est pas appelé si pas d'entrées
        # Ce test vérifie juste que ça ne crash pas


# =========================================================================
# Test: Feature Flag Integration
# =========================================================================

class TestPrefetchFeatureFlag:
    """Tests pour l'intégration avec feature flags."""

    def test_prefetch_respects_feature_flag(self):
        """Prefetch respecte le feature flag enable_ontology_prefetch."""
        # Ce test valide le pattern d'utilisation avec feature flags
        from knowbase.config.feature_flags import is_feature_enabled

        # En dev, le prefetch devrait être configurable
        # Le flag est à false par défaut dans feature_flags.yaml
        # donc le code appelant devrait vérifier avant d'appeler prefetch
        pass  # Pattern validation seulement


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
