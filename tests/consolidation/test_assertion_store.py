"""
Tests unitaires pour PR4 - Neo4j Storage + Persistence.

Tests:
- AssertionData et DocumentContextData dataclasses
- AssertionStore: persist_assertion, persist_document_context, queries
- Intégration avec osmose_agentique._persist_hybrid_anchor_to_neo4j

Spec: doc/ongoing/ADR_ASSERTION_AWARE_KG.md - Section 7 (PR4)
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from dataclasses import asdict

from knowbase.consolidation.assertion_store import (
    AssertionData,
    DocumentContextData,
    AssertionStore,
    get_assertion_store,
)


# =============================================================================
# Tests pour AssertionData
# =============================================================================


class TestAssertionData:
    """Tests pour la dataclass AssertionData."""

    def test_default_values(self):
        """Valeurs par défaut."""
        data = AssertionData()
        assert data.polarity == "unknown"
        assert data.scope == "unknown"
        assert data.markers == []
        assert data.confidence == 0.5
        assert data.qualifier_source == "unknown"
        assert data.is_override is False
        assert data.evidence_passage is None

    def test_custom_values(self):
        """Valeurs personnalisées."""
        data = AssertionData(
            polarity="positive",
            scope="constrained",
            markers=["1809", "Cloud"],
            confidence=0.9,
            qualifier_source="explicit",
            is_override=True,
            evidence_passage="Cette fonctionnalité est disponible dans 1809..."
        )
        assert data.polarity == "positive"
        assert data.scope == "constrained"
        assert len(data.markers) == 2
        assert data.confidence == 0.9
        assert data.is_override is True

    def test_to_dict(self):
        """Conversion to_dict exclut evidence_passage."""
        data = AssertionData(
            polarity="deprecated",
            scope="general",
            markers=["FPS03"],
            confidence=0.8,
            evidence_passage="Ce passage est très long..."
        )
        d = data.to_dict()

        assert d["polarity"] == "deprecated"
        assert d["scope"] == "general"
        assert d["markers"] == ["FPS03"]
        assert d["confidence"] == 0.8
        assert "evidence_passage" not in d  # Non inclus


# =============================================================================
# Tests pour DocumentContextData
# =============================================================================


class TestDocumentContextData:
    """Tests pour la dataclass DocumentContextData."""

    def test_default_values(self):
        """Valeurs par défaut."""
        data = DocumentContextData()
        assert data.detected_variant is None
        assert data.variant_confidence == 0.0
        assert data.doc_scope == "unknown"
        assert data.edition is None
        assert data.global_markers == []
        assert data.metadata_json is None

    def test_sap_variant(self):
        """Document SAP avec variante détectée."""
        data = DocumentContextData(
            detected_variant="1809",
            variant_confidence=0.95,
            doc_scope="variant_specific",
            edition="Cloud",
            global_markers=["1809", "Cloud", "FPS03"],
        )
        assert data.detected_variant == "1809"
        assert data.variant_confidence == 0.95
        assert data.doc_scope == "variant_specific"
        assert len(data.global_markers) == 3

    def test_to_dict(self):
        """Conversion to_dict exclut metadata_json."""
        data = DocumentContextData(
            detected_variant="2020",
            doc_scope="general",
            metadata_json='{"full": "context"}'
        )
        d = data.to_dict()

        assert d["detected_variant"] == "2020"
        assert d["doc_scope"] == "general"
        assert "metadata_json" not in d


# =============================================================================
# Tests pour AssertionStore (avec mocks Neo4j)
# =============================================================================


class TestAssertionStore:
    """Tests pour AssertionStore avec mocks Neo4j."""

    @pytest.fixture
    def mock_neo4j_client(self):
        """Mock du client Neo4j."""
        client = MagicMock()
        session = MagicMock()
        client.driver.session.return_value.__enter__ = MagicMock(return_value=session)
        client.driver.session.return_value.__exit__ = MagicMock(return_value=None)
        return client, session

    @pytest.fixture
    def store(self, mock_neo4j_client):
        """AssertionStore avec mock Neo4j."""
        client, _ = mock_neo4j_client
        store = AssertionStore(tenant_id="test")
        store._neo4j_client = client
        return store

    @pytest.mark.asyncio
    async def test_ensure_document_creates_node(self, store, mock_neo4j_client):
        """ensure_document crée un nœud Document."""
        _, session = mock_neo4j_client

        record = MagicMock()
        record.__getitem__ = lambda self, key: {"doc_id": "doc_001"}[key]

        result = MagicMock()
        result.single.return_value = record
        session.run.return_value = result

        context = DocumentContextData(
            detected_variant="1809",
            variant_confidence=0.9,
            doc_scope="variant_specific",
        )

        success = await store.ensure_document(
            document_id="doc_001",
            document_name="Test Document.pptx",
            context_data=context,
        )

        assert success is True
        session.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_persist_assertion_creates_relation(self, store, mock_neo4j_client):
        """persist_assertion crée une relation EXTRACTED_FROM."""
        _, session = mock_neo4j_client

        record = MagicMock()
        record.__getitem__ = lambda self, key: {"created": True}[key]

        result = MagicMock()
        result.single.return_value = record
        session.run.return_value = result

        assertion = AssertionData(
            polarity="positive",
            scope="constrained",
            markers=["1809"],
            confidence=0.85,
            qualifier_source="explicit",
        )

        success = await store.persist_assertion(
            proto_concept_id="pc_001",
            document_id="doc_001",
            assertion=assertion,
        )

        assert success is True
        session.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_persist_assertions_batch(self, store, mock_neo4j_client):
        """persist_assertions_batch crée plusieurs relations."""
        _, session = mock_neo4j_client

        record = MagicMock()
        record.__getitem__ = lambda self, key: {"created": 3}[key]

        result = MagicMock()
        result.single.return_value = record
        session.run.return_value = result

        assertions = [
            {"proto_id": "pc_001", "polarity": "positive", "scope": "general", "markers": ["1809"], "confidence": 0.8},
            {"proto_id": "pc_002", "polarity": "deprecated", "scope": "constrained", "markers": ["FPS03"], "confidence": 0.9},
            {"proto_id": "pc_003", "polarity": "future", "scope": "unknown", "markers": [], "confidence": 0.6},
        ]

        count = await store.persist_assertions_batch(
            assertions=assertions,
            document_id="doc_001",
        )

        assert count == 3
        session.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_document_context_returns_data(self, store, mock_neo4j_client):
        """get_document_context retourne les données du document."""
        _, session = mock_neo4j_client

        record = MagicMock()
        record.__getitem__ = lambda self, key: {
            "detected_variant": "2020",
            "variant_confidence": 0.85,
            "doc_scope": "variant_specific",
            "edition": "Cloud",
            "global_markers": ["2020", "Cloud"],
            "context_json": '{"extra": "data"}',
        }[key]

        result = MagicMock()
        result.single.return_value = record
        session.run.return_value = result

        context = await store.get_document_context("doc_001")

        assert context is not None
        assert context.detected_variant == "2020"
        assert context.variant_confidence == 0.85
        assert context.doc_scope == "variant_specific"
        assert len(context.global_markers) == 2

    @pytest.mark.asyncio
    async def test_get_document_context_not_found(self, store, mock_neo4j_client):
        """get_document_context retourne None si document non trouvé."""
        _, session = mock_neo4j_client

        result = MagicMock()
        result.single.return_value = None
        session.run.return_value = result

        context = await store.get_document_context("nonexistent")

        assert context is None

    @pytest.mark.asyncio
    async def test_get_assertions_for_document(self, store, mock_neo4j_client):
        """get_assertions_for_document retourne les assertions."""
        _, session = mock_neo4j_client

        records = [
            {
                "concept_id": "pc_001",
                "label": "SAP S/4HANA",
                "canonical_id": "cc_001",
                "polarity": "positive",
                "scope": "general",
                "markers": ["1809"],
                "confidence": 0.9,
                "qualifier_source": "explicit",
                "is_override": False,
            },
            {
                "concept_id": "pc_002",
                "label": "Legacy Feature",
                "canonical_id": "cc_002",
                "polarity": "deprecated",
                "scope": "constrained",
                "markers": ["FPS03"],
                "confidence": 0.8,
                "qualifier_source": "inherited",
                "is_override": False,
            },
        ]

        result = MagicMock()
        result.__iter__ = MagicMock(return_value=iter([
            MagicMock(**{"__getitem__": lambda self, k, r=rec: r[k]})
            for rec in records
        ]))
        session.run.return_value = result

        assertions = await store.get_assertions_for_document("doc_001")

        assert len(assertions) == 2


# =============================================================================
# Tests pour get_assertion_store singleton
# =============================================================================


class TestGetAssertionStore:
    """Tests pour la fonction singleton get_assertion_store."""

    def test_returns_same_instance(self):
        """Retourne la même instance pour le même tenant."""
        # Clear instances
        from knowbase.consolidation import assertion_store
        assertion_store._assertion_store_instances.clear()

        store1 = get_assertion_store("tenant_a")
        store2 = get_assertion_store("tenant_a")

        assert store1 is store2

    def test_different_tenants_different_instances(self):
        """Retourne des instances différentes pour différents tenants."""
        from knowbase.consolidation import assertion_store
        assertion_store._assertion_store_instances.clear()

        store_a = get_assertion_store("tenant_a")
        store_b = get_assertion_store("tenant_b")

        assert store_a is not store_b
        assert store_a.tenant_id == "tenant_a"
        assert store_b.tenant_id == "tenant_b"


# =============================================================================
# Tests d'intégration logique (sans Neo4j)
# =============================================================================


class TestIntegrationLogic:
    """Tests de la logique d'intégration sans Neo4j réel."""

    def test_assertion_data_normalization(self):
        """Les données d'assertion sont correctement normalisées."""
        # Simulation du flow de normalisation dans osmose_agentique.py

        # Données brutes d'un anchor context
        raw_context = {
            "polarity": "positive",
            "scope": "constrained",
            "local_markers": [{"value": "1809"}, {"value": "Cloud"}],
            "confidence": 0.85,
            "qualifier_source": "explicit",
            "is_override": False,
        }

        # Normalisation vers AssertionData
        markers = [m["value"] for m in raw_context.get("local_markers", [])]

        assertion = AssertionData(
            polarity=raw_context["polarity"],
            scope=raw_context["scope"],
            markers=markers,
            confidence=raw_context["confidence"],
            qualifier_source=raw_context["qualifier_source"],
            is_override=raw_context["is_override"],
        )

        assert assertion.markers == ["1809", "Cloud"]
        assert assertion.confidence == 0.85

    def test_document_context_from_frame(self):
        """DocumentContextData est correctement construit depuis DocContextFrame."""
        # Simulation du DocContextFrame avec les vrais attributs
        class MockDocContextFrame:
            strong_markers = ["1809", "Cloud"]
            weak_markers = ["FPS03"]
            scope_confidence = 0.9
            doc_scope = MagicMock(value="VARIANT_SPECIFIC")

            def get_dominant_marker(self):
                return self.strong_markers[0] if self.strong_markers else None

            def has_markers(self):
                return bool(self.strong_markers or self.weak_markers)

        frame = MockDocContextFrame()

        # Conversion vers DocumentContextData (comme dans osmose_agentique.py)
        detected_variant = frame.get_dominant_marker()
        global_markers = list(frame.strong_markers) + list(frame.weak_markers)
        edition = detected_variant if frame.doc_scope.value == "VARIANT_SPECIFIC" else None

        context = DocumentContextData(
            detected_variant=detected_variant,
            variant_confidence=frame.scope_confidence,
            doc_scope=frame.doc_scope.value,
            edition=edition,
            global_markers=global_markers,
        )

        assert context.detected_variant == "1809"
        assert context.variant_confidence == 0.9
        assert context.doc_scope == "VARIANT_SPECIFIC"
        assert len(context.global_markers) == 3
        assert context.edition == "1809"

    def test_assertion_confidence_priority(self):
        """La confiance la plus élevée est prioritaire."""
        # Simulation de la logique ON MATCH dans Neo4j

        existing = AssertionData(
            polarity="positive",
            confidence=0.7,
        )

        incoming = AssertionData(
            polarity="deprecated",
            confidence=0.9,
        )

        # Logique de merge: incoming.confidence > existing.confidence
        if incoming.confidence > existing.confidence:
            final_polarity = incoming.polarity
            final_confidence = incoming.confidence
        else:
            final_polarity = existing.polarity
            final_confidence = existing.confidence

        assert final_polarity == "deprecated"
        assert final_confidence == 0.9

    def test_markers_merge_logic(self):
        """Les markers sont fusionnés en prenant le plus grand ensemble."""
        existing_markers = ["1809"]
        incoming_markers = ["1809", "Cloud", "FPS03"]

        # Logique de merge: prendre le plus grand ensemble
        if len(incoming_markers) > len(existing_markers):
            final_markers = incoming_markers
        else:
            final_markers = existing_markers

        assert len(final_markers) == 3
        assert "Cloud" in final_markers

    def test_inherited_markers_fallback(self):
        """Les markers sont hérités du DocContextFrame si non présents."""
        local_markers = []
        global_markers = ["1809", "Cloud"]

        # Logique de fallback
        if not local_markers and global_markers:
            final_markers = global_markers
            qualifier_source = "inherited"
        else:
            final_markers = local_markers
            qualifier_source = "explicit"

        assert final_markers == ["1809", "Cloud"]
        assert qualifier_source == "inherited"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
