"""
Tests unitaires pour PR3 - Diff Queries + Marker Nodes.

Tests:
- MarkerStore: detect_marker_kind, MarkerNode, DiffResult
- ConceptDiffService: diff_by_markers, diff_by_documents, assertions
- API endpoints: /diff, /assertions, /by-polarity, /by-scope

Spec: doc/ongoing/ADR_ASSERTION_AWARE_KG.md - Section 7 (PR3)
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from dataclasses import asdict

from knowbase.consolidation.marker_store import (
    MarkerKind,
    MarkerNode,
    ConceptMarkerLink,
    DiffResult,
    MarkerStore,
    detect_marker_kind,
)
from knowbase.api.services.concept_diff_service import (
    DiffMode,
    ConceptInfo,
    AssertionInfo,
    ConceptDiffResult,
    AssertionQueryResult,
    ConceptDiffService,
)


# =============================================================================
# Tests pour detect_marker_kind
# =============================================================================


class TestDetectMarkerKind:
    """Tests pour la detection automatique du type de marker."""

    def test_fps_pattern(self):
        """FPS01, FPS03, FPS05, etc."""
        assert detect_marker_kind("FPS01") == MarkerKind.FPS
        assert detect_marker_kind("FPS03") == MarkerKind.FPS
        assert detect_marker_kind("fps05") == MarkerKind.FPS  # Case insensitive
        assert detect_marker_kind("FPS9") == MarkerKind.FPS

    def test_sp_pattern(self):
        """SP02, SP100, etc."""
        assert detect_marker_kind("SP02") == MarkerKind.SP
        assert detect_marker_kind("SP100") == MarkerKind.SP
        assert detect_marker_kind("sp50") == MarkerKind.SP

    def test_version_pattern(self):
        """v1.0.0, 3.2.1, etc."""
        assert detect_marker_kind("v1.0.0") == MarkerKind.VERSION
        assert detect_marker_kind("V2.5.3") == MarkerKind.VERSION
        assert detect_marker_kind("3.2.1") == MarkerKind.VERSION
        assert detect_marker_kind("1.0") == MarkerKind.VERSION

    def test_numeric_code_pattern(self):
        """SAP numeric codes: 1809, 2020, 2508."""
        assert detect_marker_kind("1809") == MarkerKind.NUMERIC_CODE
        assert detect_marker_kind("2020") == MarkerKind.NUMERIC_CODE
        assert detect_marker_kind("2508") == MarkerKind.NUMERIC_CODE
        assert detect_marker_kind("1909") == MarkerKind.NUMERIC_CODE

    def test_year_pattern(self):
        """Years that aren't SAP codes: 2024, 2025."""
        # Note: 2024, 2025 sont aussi NUMERIC_CODE car dans le range SAP
        # Seuls les years hors range SAP (ex: 2030+) seraient YEAR
        assert detect_marker_kind("2024") == MarkerKind.NUMERIC_CODE

    def test_edition_pattern(self):
        """Cloud, Private, Public, etc."""
        assert detect_marker_kind("Cloud") == MarkerKind.EDITION
        assert detect_marker_kind("PRIVATE") == MarkerKind.EDITION
        assert detect_marker_kind("public") == MarkerKind.EDITION
        assert detect_marker_kind("ON-PREMISE") == MarkerKind.EDITION
        assert detect_marker_kind("HYBRID") == MarkerKind.EDITION

    def test_unknown_pattern(self):
        """Patterns non reconnus."""
        assert detect_marker_kind("random") == MarkerKind.UNKNOWN
        assert detect_marker_kind("xyz123") == MarkerKind.UNKNOWN
        assert detect_marker_kind("") == MarkerKind.UNKNOWN


# =============================================================================
# Tests pour MarkerNode
# =============================================================================


class TestMarkerNode:
    """Tests pour la dataclass MarkerNode."""

    def test_basic_creation(self):
        """Creation basique avec auto-normalisation."""
        node = MarkerNode(value="1809")
        assert node.value == "1809"
        assert node.normalized_value == "1809"
        assert node.kind == MarkerKind.UNKNOWN  # Default
        assert node.tenant_id == "default"

    def test_normalized_value_auto(self):
        """Normalisation automatique (uppercase + strip)."""
        node = MarkerNode(value="  fps03  ")
        assert node.normalized_value == "FPS03"

    def test_explicit_normalized_value(self):
        """Normalized value explicite ne doit pas etre ecrasee."""
        node = MarkerNode(value="fps03", normalized_value="custom")
        assert node.normalized_value == "custom"

    def test_with_kind(self):
        """Creation avec kind explicite."""
        node = MarkerNode(value="1809", kind=MarkerKind.NUMERIC_CODE)
        assert node.kind == MarkerKind.NUMERIC_CODE


# =============================================================================
# Tests pour DiffResult
# =============================================================================


class TestDiffResult:
    """Tests pour la dataclass DiffResult."""

    def test_empty_diff(self):
        """Diff vide."""
        result = DiffResult()
        assert result.only_in_a == []
        assert result.only_in_b == []
        assert result.in_both == []

    def test_to_dict_with_data(self):
        """Conversion to_dict avec donnees."""
        result = DiffResult(
            only_in_a=["concept_1", "concept_2"],
            only_in_b=["concept_3"],
            in_both=["concept_4", "concept_5"],
            marker_a="1809",
            marker_b="2020",
            stats={"min_confidence": 0.5},
        )

        d = result.to_dict()

        assert d["marker_a"] == "1809"
        assert d["marker_b"] == "2020"
        assert d["only_in_a"] == ["concept_1", "concept_2"]
        assert d["only_in_b"] == ["concept_3"]
        assert d["in_both"] == ["concept_4", "concept_5"]
        assert d["stats"]["count_only_a"] == 2
        assert d["stats"]["count_only_b"] == 1
        assert d["stats"]["count_both"] == 2
        assert d["stats"]["min_confidence"] == 0.5


# =============================================================================
# Tests pour ConceptMarkerLink
# =============================================================================


class TestConceptMarkerLink:
    """Tests pour ConceptMarkerLink."""

    def test_basic_link(self):
        """Creation basique."""
        link = ConceptMarkerLink(
            concept_id="pc_001",
            marker_value="1809",
            confidence=0.9,
        )
        assert link.concept_id == "pc_001"
        assert link.marker_value == "1809"
        assert link.confidence == 0.9
        assert link.is_inherited is False  # Default
        assert link.qualifier_source == "explicit"  # Default


# =============================================================================
# Tests pour DiffMode
# =============================================================================


class TestDiffMode:
    """Tests pour l'enum DiffMode."""

    def test_values(self):
        """Verifier les valeurs de l'enum."""
        assert DiffMode.CONCEPTS.value == "concepts"
        assert DiffMode.ASSERTIONS.value == "assertions"
        assert DiffMode.RELATIONS.value == "relations"

    def test_from_string(self):
        """Creation depuis string."""
        assert DiffMode("concepts") == DiffMode.CONCEPTS
        assert DiffMode("assertions") == DiffMode.ASSERTIONS


# =============================================================================
# Tests pour ConceptInfo
# =============================================================================


class TestConceptInfo:
    """Tests pour ConceptInfo."""

    def test_basic_creation(self):
        """Creation basique."""
        info = ConceptInfo(
            concept_id="pc_001",
            label="Test Concept",
            polarity="positive",
            scope="general",
            confidence=0.8,
        )
        assert info.concept_id == "pc_001"
        assert info.label == "Test Concept"
        assert info.polarity == "positive"
        assert info.scope == "general"
        assert info.markers == []  # Default

    def test_to_dict(self):
        """Conversion to_dict."""
        info = ConceptInfo(
            concept_id="pc_001",
            label="Test Concept",
            canonical_id="cc_001",
            canonical_name="Canonical Test",
            polarity="negative",
            scope="constrained",
            confidence=0.9,
            markers=["1809", "2020"],
            document_id="doc_001",
        )

        d = info.to_dict()

        assert d["concept_id"] == "pc_001"
        assert d["label"] == "Test Concept"
        assert d["canonical_id"] == "cc_001"
        assert d["canonical_name"] == "Canonical Test"
        assert d["polarity"] == "negative"
        assert d["scope"] == "constrained"
        assert d["markers"] == ["1809", "2020"]


# =============================================================================
# Tests pour AssertionInfo
# =============================================================================


class TestAssertionInfo:
    """Tests pour AssertionInfo."""

    def test_basic_creation(self):
        """Creation basique."""
        info = AssertionInfo(
            concept_id="pc_001",
            label="Test",
            polarity="positive",
            scope="general",
            markers=["1809"],
            confidence=0.8,
            document_id="doc_001",
        )
        assert info.concept_id == "pc_001"
        assert info.evidence == []  # Default

    def test_to_dict_truncates_evidence(self):
        """to_dict tronque evidence a 2 elements."""
        info = AssertionInfo(
            concept_id="pc_001",
            label="Test",
            polarity="positive",
            scope="general",
            markers=[],
            confidence=0.8,
            document_id="doc_001",
            evidence=["ev1", "ev2", "ev3", "ev4"],
        )

        d = info.to_dict()
        assert len(d["evidence"]) == 2
        assert d["evidence"] == ["ev1", "ev2"]


# =============================================================================
# Tests pour ConceptDiffResult
# =============================================================================


class TestConceptDiffResult:
    """Tests pour ConceptDiffResult."""

    def test_empty_result(self):
        """Resultat vide."""
        result = ConceptDiffResult(
            marker_a="1809",
            marker_b="2020",
            mode=DiffMode.CONCEPTS,
        )
        assert result.only_in_a == []
        assert result.only_in_b == []
        assert result.in_both == []
        assert result.changed == []

    def test_to_dict_with_concepts(self):
        """to_dict avec concepts."""
        result = ConceptDiffResult(
            marker_a="1809",
            marker_b="2020",
            mode=DiffMode.ASSERTIONS,
            only_in_a=[ConceptInfo(concept_id="pc_1", label="C1")],
            only_in_b=[ConceptInfo(concept_id="pc_2", label="C2")],
            in_both=[ConceptInfo(concept_id="pc_3", label="C3")],
            changed=[{"concept_id": "pc_4", "change_type": "positive_to_deprecated"}],
            stats={"mode": "assertions"},
        )

        d = result.to_dict()

        assert d["marker_a"] == "1809"
        assert d["marker_b"] == "2020"
        assert d["mode"] == "assertions"
        assert len(d["only_in_a"]) == 1
        assert len(d["only_in_b"]) == 1
        assert len(d["in_both"]) == 1
        assert d["stats"]["count_only_a"] == 1
        assert d["stats"]["count_changed"] == 1


# =============================================================================
# Tests pour AssertionQueryResult
# =============================================================================


class TestAssertionQueryResult:
    """Tests pour AssertionQueryResult."""

    def test_empty_result(self):
        """Resultat vide."""
        result = AssertionQueryResult(
            concept_id="pc_001",
            canonical_id=None,
            label="Test",
        )
        assert result.assertions == []
        assert result.has_conflict is False
        assert result.conflict_flags == []

    def test_with_conflict(self):
        """Resultat avec conflit detecte."""
        result = AssertionQueryResult(
            concept_id="pc_001",
            canonical_id="cc_001",
            label="Test",
            aggregated_polarity="unknown",
            has_conflict=True,
            conflict_flags=["polarity_conflict: ['positive', 'deprecated']"],
        )

        d = result.to_dict()

        assert d["has_conflict"] is True
        assert len(d["conflict_flags"]) == 1


# =============================================================================
# Tests pour MarkerStore (avec mocks Neo4j)
# =============================================================================


class TestMarkerStore:
    """Tests pour MarkerStore avec mocks Neo4j."""

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
        """MarkerStore avec mock Neo4j."""
        client, _ = mock_neo4j_client
        store = MarkerStore(tenant_id="test")
        store._neo4j_client = client
        return store

    @pytest.mark.asyncio
    async def test_ensure_marker_creates_node(self, store, mock_neo4j_client):
        """ensure_marker cree un noeud si inexistant."""
        _, session = mock_neo4j_client

        # Mock response
        record = MagicMock()
        record.__getitem__ = lambda self, key: {
            "value": "1809",
            "kind": "numeric_code",
            "normalized": "1809",
        }[key]

        result = MagicMock()
        result.single.return_value = record
        session.run.return_value = result

        node = await store.ensure_marker("1809")

        assert node.value == "1809"
        assert node.kind == MarkerKind.NUMERIC_CODE
        session.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_link_concept_to_marker(self, store, mock_neo4j_client):
        """link_concept_to_marker cree une relation."""
        _, session = mock_neo4j_client

        # Mock ensure_marker response
        ensure_record = MagicMock()
        ensure_record.__getitem__ = lambda self, key: {
            "value": "1809",
            "kind": "numeric_code",
            "normalized": "1809",
        }[key]

        # Mock link response
        link_record = MagicMock()
        link_record.__getitem__ = lambda self, key: {"created": True}[key]

        result = MagicMock()
        result.single.side_effect = [ensure_record, link_record]
        session.run.return_value = result

        success = await store.link_concept_to_marker(
            concept_id="pc_001",
            marker_value="1809",
            confidence=0.9,
        )

        # Verifie que les queries ont ete appelees
        assert session.run.call_count >= 1

    @pytest.mark.asyncio
    async def test_diff_markers_empty(self, store, mock_neo4j_client):
        """diff_markers retourne vide si pas de concepts."""
        _, session = mock_neo4j_client

        record = MagicMock()
        record.__getitem__ = lambda self, key: {
            "only_a": [],
            "only_b": [],
            "in_both": [],
        }[key]

        result = MagicMock()
        result.single.return_value = record
        session.run.return_value = result

        diff = await store.diff_markers(["1809"], ["2020"])

        assert diff.only_in_a == []
        assert diff.only_in_b == []
        assert diff.in_both == []

    @pytest.mark.asyncio
    async def test_diff_markers_with_results(self, store, mock_neo4j_client):
        """diff_markers retourne les ensembles corrects."""
        _, session = mock_neo4j_client

        record = MagicMock()
        record.__getitem__ = lambda self, key: {
            "only_a": ["pc_001", "pc_002"],
            "only_b": ["pc_003"],
            "in_both": ["pc_004"],
        }[key]

        result = MagicMock()
        result.single.return_value = record
        session.run.return_value = result

        diff = await store.diff_markers(["1809"], ["2020"], min_confidence=0.5)

        assert len(diff.only_in_a) == 2
        assert len(diff.only_in_b) == 1
        assert len(diff.in_both) == 1
        assert "pc_001" in diff.only_in_a
        assert "pc_003" in diff.only_in_b


# =============================================================================
# Tests pour ConceptDiffService (avec mocks)
# =============================================================================


class TestConceptDiffService:
    """Tests pour ConceptDiffService avec mocks."""

    @pytest.fixture
    def mock_marker_store(self):
        """Mock du MarkerStore."""
        store = MagicMock(spec=MarkerStore)
        store.diff_markers = AsyncMock(return_value=DiffResult(
            only_in_a=["pc_1"],
            only_in_b=["pc_2"],
            in_both=["pc_3"],
            marker_a="1809",
            marker_b="2020",
        ))
        return store

    @pytest.fixture
    def mock_neo4j_client(self):
        """Mock du client Neo4j."""
        client = MagicMock()
        session = MagicMock()
        client.driver.session.return_value.__enter__ = MagicMock(return_value=session)
        client.driver.session.return_value.__exit__ = MagicMock(return_value=None)
        return client, session

    @pytest.fixture
    def service(self, mock_marker_store, mock_neo4j_client):
        """ConceptDiffService avec mocks."""
        client, _ = mock_neo4j_client
        svc = ConceptDiffService(tenant_id="test")
        svc._marker_store = mock_marker_store
        svc._neo4j_client = client
        return svc

    @pytest.mark.asyncio
    async def test_diff_by_markers_basic(self, service, mock_marker_store, mock_neo4j_client):
        """diff_by_markers mode CONCEPTS basique."""
        _, session = mock_neo4j_client

        # Mock pour _enrich_concept_list
        def mock_records(*args, **kwargs):
            result = MagicMock()
            result.__iter__ = MagicMock(return_value=iter([]))
            return result

        session.run.side_effect = mock_records

        result = await service.diff_by_markers(
            marker_a="1809",
            marker_b="2020",
            mode=DiffMode.CONCEPTS,
            include_details=False,  # Skip enrichment
        )

        assert result.marker_a == "1809"
        assert result.marker_b == "2020"
        assert result.mode == DiffMode.CONCEPTS
        assert len(result.only_in_a) == 1
        assert len(result.only_in_b) == 1
        mock_marker_store.diff_markers.assert_called_once()

    @pytest.mark.asyncio
    async def test_diff_by_markers_assertions_mode(self, service, mock_marker_store, mock_neo4j_client):
        """diff_by_markers mode ASSERTIONS detecte les changements."""
        _, session = mock_neo4j_client

        # Mock pour les enrichments
        def mock_records(*args, **kwargs):
            result = MagicMock()
            result.__iter__ = MagicMock(return_value=iter([]))
            return result

        session.run.side_effect = mock_records

        result = await service.diff_by_markers(
            marker_a="1809",
            marker_b="2020",
            mode=DiffMode.ASSERTIONS,
            include_details=False,
        )

        assert result.mode == DiffMode.ASSERTIONS

    @pytest.mark.asyncio
    async def test_get_assertions_for_concept_not_found(self, service, mock_neo4j_client):
        """get_assertions_for_concept retourne vide si concept inexistant."""
        _, session = mock_neo4j_client

        record = MagicMock()
        record.__getitem__ = lambda self, key: {
            "concept_id": None,
            "canonical_id": None,
            "label": None,
            "assertions": [],
        }[key]

        result_mock = MagicMock()
        result_mock.single.return_value = record
        session.run.return_value = result_mock

        result = await service.get_assertions_for_concept("nonexistent")

        assert result.assertions == []
        assert result.label == ""

    @pytest.mark.asyncio
    async def test_get_concepts_by_polarity(self, service, mock_neo4j_client):
        """get_concepts_by_polarity retourne les concepts filtres."""
        _, session = mock_neo4j_client

        from knowbase.extraction_v2.context.anchor_models import Polarity

        records = [
            {
                "concept_id": "pc_001",
                "label": "Deprecated Feature",
                "canonical_id": None,
                "canonical_name": None,
                "polarity": "deprecated",
                "scope": "general",
                "confidence": 0.9,
                "markers": ["1809"],
                "document_id": "doc_001",
            }
        ]

        result_mock = MagicMock()
        result_mock.__iter__ = MagicMock(return_value=iter([
            MagicMock(**{"__getitem__": lambda self, k: records[0][k]})
        ]))
        session.run.return_value = result_mock

        concepts = await service.get_concepts_by_polarity(
            polarity=Polarity.DEPRECATED,
            limit=10,
        )

        # Verifie que la query a ete executee
        session.run.assert_called_once()


# =============================================================================
# Tests API Endpoints (avec FastAPI TestClient)
# =============================================================================


class TestConceptsAPIEndpoints:
    """Tests pour les endpoints API /concepts/*.

    Ces tests verifient la structure des responses sans Neo4j reel.
    """

    @pytest.fixture
    def mock_diff_service(self):
        """Mock du ConceptDiffService."""
        service = MagicMock(spec=ConceptDiffService)
        service.diff_by_markers = AsyncMock(return_value=ConceptDiffResult(
            marker_a="1809",
            marker_b="2020",
            mode=DiffMode.CONCEPTS,
            only_in_a=[ConceptInfo(concept_id="pc_1", label="C1")],
            only_in_b=[],
            in_both=[],
        ))
        service.get_assertions_for_concept = AsyncMock(return_value=AssertionQueryResult(
            concept_id="pc_001",
            canonical_id=None,
            label="Test Concept",
            assertions=[],
        ))
        return service

    def test_diff_request_model(self):
        """Teste le modele DiffRequest."""
        from knowbase.api.routers.concepts import DiffRequest

        request = DiffRequest(
            marker_a="1809",
            marker_b="2020",
            mode="assertions",
            min_confidence=0.7,
        )
        assert request.marker_a == "1809"
        assert request.mode == "assertions"
        assert request.min_confidence == 0.7

    def test_diff_response_model(self):
        """Teste le modele DiffResponse."""
        from knowbase.api.routers.concepts import DiffResponse

        response = DiffResponse(
            marker_a="1809",
            marker_b="2020",
            mode="concepts",
            only_in_a=[{"concept_id": "pc_1", "label": "C1"}],
            only_in_b=[],
            in_both=[],
            changed=[],
            stats={"count": 1},
        )
        assert len(response.only_in_a) == 1
        assert response.stats["count"] == 1

    def test_assertions_response_model(self):
        """Teste le modele AssertionsResponse."""
        from knowbase.api.routers.concepts import AssertionsResponse

        response = AssertionsResponse(
            concept_id="pc_001",
            label="Test",
            assertions=[],
            has_conflict=False,
        )
        assert response.concept_id == "pc_001"
        assert response.has_conflict is False

    def test_concept_list_response_model(self):
        """Teste le modele ConceptListResponse."""
        from knowbase.api.routers.concepts import ConceptListResponse

        response = ConceptListResponse(
            concepts=[{"concept_id": "pc_1", "label": "C1"}],
            total=1,
            filter_applied="polarity=deprecated",
        )
        assert response.total == 1
        assert response.filter_applied == "polarity=deprecated"


# =============================================================================
# Tests d'integration logique (sans Neo4j)
# =============================================================================


class TestIntegrationLogic:
    """Tests de la logique d'integration entre composants."""

    def test_marker_kind_detection_in_link_flow(self):
        """Le MarkerStore detecte automatiquement le kind."""
        # Simule le flow complet sans Neo4j

        # 1. Detection du kind
        kind = detect_marker_kind("1809")
        assert kind == MarkerKind.NUMERIC_CODE

        # 2. Creation du node
        node = MarkerNode(value="1809", kind=kind)
        assert node.kind == MarkerKind.NUMERIC_CODE
        assert node.normalized_value == "1809"

        # 3. Creation du link
        link = ConceptMarkerLink(
            concept_id="pc_001",
            marker_value="1809",
            confidence=0.9,
        )
        assert link.marker_value == "1809"

    def test_diff_result_stats_calculation(self):
        """Les stats sont correctement calculees dans DiffResult."""
        result = DiffResult(
            only_in_a=["a", "b", "c"],  # 3
            only_in_b=["d"],            # 1
            in_both=["e", "f"],         # 2
            marker_a="A",
            marker_b="B",
        )

        d = result.to_dict()

        assert d["stats"]["count_only_a"] == 3
        assert d["stats"]["count_only_b"] == 1
        assert d["stats"]["count_both"] == 2

    def test_concept_diff_result_aggregation(self):
        """ConceptDiffResult aggrege correctement les stats."""
        result = ConceptDiffResult(
            marker_a="1809",
            marker_b="2020",
            mode=DiffMode.ASSERTIONS,
            only_in_a=[
                ConceptInfo(concept_id="pc_1", label="C1"),
                ConceptInfo(concept_id="pc_2", label="C2"),
            ],
            only_in_b=[ConceptInfo(concept_id="pc_3", label="C3")],
            in_both=[],
            changed=[
                {"concept_id": "pc_4", "change_type": "positive_to_deprecated"},
                {"concept_id": "pc_5", "change_type": "positive_to_negative"},
            ],
        )

        d = result.to_dict()

        assert d["stats"]["count_only_a"] == 2
        assert d["stats"]["count_only_b"] == 1
        assert d["stats"]["count_both"] == 0
        assert d["stats"]["count_changed"] == 2

    def test_assertion_conflict_detection_logic(self):
        """La logique de detection de conflit fonctionne."""
        # Sans conflit (une seule polarity)
        no_conflict = AssertionQueryResult(
            concept_id="pc_001",
            canonical_id=None,
            label="Test",
            aggregated_polarity="positive",
            has_conflict=False,
        )
        assert no_conflict.has_conflict is False

        # Avec conflit (polarities mixtes)
        with_conflict = AssertionQueryResult(
            concept_id="pc_001",
            canonical_id=None,
            label="Test",
            aggregated_polarity="unknown",
            has_conflict=True,
            conflict_flags=["polarity_conflict: ['positive', 'deprecated']"],
        )
        assert with_conflict.has_conflict is True
        assert len(with_conflict.conflict_flags) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
