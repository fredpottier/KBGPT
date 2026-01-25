"""
Tests pour Pass 0 Adapter V2.

Valide:
- Import et instanciation de l'adapter
- Génération des docitem_id composites
- Création des mappings chunk→DocItem
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime


class TestPass0AdapterImports:
    """Tests d'import de l'adapter."""

    def test_import_pass0_adapter(self):
        """Vérifie que Pass0Adapter peut être importé."""
        from knowbase.stratified.pass0 import Pass0Adapter
        assert Pass0Adapter is not None

    def test_import_pass0_result(self):
        """Vérifie que Pass0Result peut être importé."""
        from knowbase.stratified.pass0 import Pass0Result
        assert Pass0Result is not None

    def test_import_build_function(self):
        """Vérifie que build_structural_graph_v2 peut être importé."""
        from knowbase.stratified.pass0 import build_structural_graph_v2
        assert build_structural_graph_v2 is not None

    def test_import_from_main_module(self):
        """Vérifie l'import depuis le module principal stratified."""
        from knowbase.stratified import Pass0Adapter, Pass0Result, build_structural_graph_v2
        assert Pass0Adapter is not None
        assert Pass0Result is not None
        assert build_structural_graph_v2 is not None


class TestDocItemIdGeneration:
    """Tests pour la génération des docitem_id V2."""

    def test_get_docitem_id_v2(self):
        """Teste la génération d'un docitem_id composite."""
        from knowbase.stratified.pass0.adapter import get_docitem_id_v2

        result = get_docitem_id_v2("tenant1", "doc123", "item456")
        assert result == "tenant1:doc123:item456"

    def test_parse_docitem_id_v2(self):
        """Teste le parsing d'un docitem_id composite."""
        from knowbase.stratified.pass0.adapter import parse_docitem_id_v2

        tenant, doc_id, item_id = parse_docitem_id_v2("tenant1:doc123:item456")
        assert tenant == "tenant1"
        assert doc_id == "doc123"
        assert item_id == "item456"

    def test_parse_docitem_id_v2_invalid(self):
        """Teste le parsing d'un docitem_id invalide."""
        from knowbase.stratified.pass0.adapter import parse_docitem_id_v2

        with pytest.raises(ValueError, match="Invalid docitem_id format"):
            parse_docitem_id_v2("invalid_format")

    def test_parse_docitem_id_with_colons_in_item_id(self):
        """Teste le parsing avec des colons dans l'item_id."""
        from knowbase.stratified.pass0.adapter import parse_docitem_id_v2

        # L'item_id peut contenir des colons (ex: "#/texts/0:1")
        tenant, doc_id, item_id = parse_docitem_id_v2("tenant:doc:#/texts/0:1")
        assert tenant == "tenant"
        assert doc_id == "doc"
        assert item_id == "#/texts/0:1"


class TestChunkToDocItemMapping:
    """Tests pour les mappings chunk↔DocItem."""

    def test_chunk_to_docitem_mapping_creation(self):
        """Teste la création d'un ChunkToDocItemMapping."""
        from knowbase.stratified.pass0.adapter import ChunkToDocItemMapping

        mapping = ChunkToDocItemMapping(
            chunk_id="chunk_001",
            docitem_ids=["t:d:item1", "t:d:item2"],
            text="Some text content",
            char_start=0,
            char_end=17,
        )

        assert mapping.chunk_id == "chunk_001"
        assert len(mapping.docitem_ids) == 2
        assert mapping.get_primary_docitem() == "t:d:item1"

    def test_chunk_to_docitem_mapping_empty(self):
        """Teste un mapping sans DocItems (cas edge)."""
        from knowbase.stratified.pass0.adapter import ChunkToDocItemMapping

        mapping = ChunkToDocItemMapping(
            chunk_id="chunk_orphan",
            docitem_ids=[],
            text="Orphan chunk",
            char_start=0,
            char_end=12,
        )

        assert mapping.get_primary_docitem() is None


class TestPass0Result:
    """Tests pour Pass0Result."""

    def test_pass0_result_creation(self):
        """Teste la création d'un Pass0Result."""
        from knowbase.stratified.pass0.adapter import Pass0Result

        result = Pass0Result(
            tenant_id="default",
            doc_id="test_doc",
            doc_version_id="v1:abc123",
        )

        assert result.tenant_id == "default"
        assert result.doc_id == "test_doc"
        assert result.item_count == 0
        assert result.section_count == 0
        assert result.chunk_count == 0

    def test_pass0_result_summary(self):
        """Teste le résumé de Pass0Result."""
        from knowbase.stratified.pass0.adapter import Pass0Result

        result = Pass0Result(
            tenant_id="default",
            doc_id="test_doc",
            doc_version_id="v1:abc123",
        )

        summary = result.summary()
        assert "0 items" in summary
        assert "0 sections" in summary
        assert "0 chunks" in summary


class TestPass0Adapter:
    """Tests pour Pass0Adapter."""

    def test_adapter_instantiation(self):
        """Teste l'instanciation de l'adapter."""
        from knowbase.stratified.pass0 import Pass0Adapter

        adapter = Pass0Adapter()
        assert adapter is not None
        assert adapter.builder is not None

    def test_adapter_with_custom_params(self):
        """Teste l'adapter avec paramètres personnalisés."""
        from knowbase.stratified.pass0 import Pass0Adapter

        adapter = Pass0Adapter(
            max_chunk_size=2000,
            persist_artifacts=True,
        )

        assert adapter.builder.max_chunk_size == 2000
        assert adapter.builder.persist_artifacts is True


class TestIntegrationWithMock:
    """Tests d'intégration avec mocks."""

    @patch('knowbase.stratified.pass0.adapter.StructuralGraphBuilder')
    def test_process_document_calls_builder(self, mock_builder_class):
        """Vérifie que process_document utilise le StructuralGraphBuilder."""
        from knowbase.stratified.pass0 import Pass0Adapter
        from knowbase.structural.models import DocumentVersion

        # Setup mock
        mock_builder = MagicMock()
        mock_builder_class.return_value = mock_builder

        # Mock du résultat de build_from_docling
        mock_result = MagicMock()
        mock_result.doc_items = []
        mock_result.sections = []
        mock_result.chunks = []
        mock_result.doc_version = DocumentVersion(
            tenant_id="default",
            doc_id="test",
            doc_version_id="v1:hash",
            page_count=1,
        )
        mock_builder.build_from_docling.return_value = mock_result

        # Execute
        adapter = Pass0Adapter()
        mock_docling_doc = MagicMock()
        result = adapter.process_document(
            docling_document=mock_docling_doc,
            tenant_id="default",
            doc_id="test_doc",
        )

        # Verify
        mock_builder.build_from_docling.assert_called_once()
        assert result.tenant_id == "default"
        assert result.doc_id == "test_doc"


# Marker pour tests d'intégration réels
@pytest.mark.integration
class TestPass0AdapterIntegration:
    """Tests d'intégration nécessitant l'infrastructure."""

    @pytest.mark.skip(reason="Nécessite un document Docling réel")
    def test_process_real_document(self):
        """Test avec un vrai document Docling."""
        pass
