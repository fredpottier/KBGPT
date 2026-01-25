"""
Tests d'intégration Pass 0 avec document réel.

Ces tests nécessitent:
- Un document Docling réel (PDF traité par Docling)
- L'infrastructure Neo4j active

Usage:
    # Avec un document existant dans le cache
    pytest tests/stratified/test_pass0_integration.py -v --doc-path=/path/to/doc.knowcache.json

    # Avec un nouveau document PDF
    pytest tests/stratified/test_pass0_integration.py -v --pdf-path=/path/to/doc.pdf
"""

import json
import logging
import os
import pytest
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def pytest_addoption(parser):
    """Ajoute les options de ligne de commande."""
    parser.addoption(
        "--doc-path",
        action="store",
        default=None,
        help="Path to a .knowcache.json file with DoclingDocument",
    )
    parser.addoption(
        "--pdf-path",
        action="store",
        default=None,
        help="Path to a PDF file to process with Docling",
    )


@pytest.fixture
def doc_path(request) -> Optional[str]:
    return request.config.getoption("--doc-path")


@pytest.fixture
def pdf_path(request) -> Optional[str]:
    return request.config.getoption("--pdf-path")


def load_docling_from_cache(cache_path: str):
    """
    Charge un DoclingDocument depuis un fichier cache.

    Le cache contient la sortie serialized de DoclingDocument.
    """
    from docling.datamodel.document import DoclingDocument

    with open(cache_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Le cache peut avoir différentes structures
    if "docling_document" in data:
        doc_dict = data["docling_document"]
    elif "document" in data:
        doc_dict = data["document"]
    else:
        doc_dict = data

    # Reconstruire le DoclingDocument
    return DoclingDocument.model_validate(doc_dict)


def process_pdf_with_docling(pdf_path: str):
    """
    Traite un PDF avec Docling.

    Retourne un DoclingDocument.
    """
    from docling.document_converter import DocumentConverter

    converter = DocumentConverter()
    result = converter.convert(pdf_path)
    return result.document


@pytest.mark.integration
class TestPass0RealDocument:
    """Tests d'intégration avec documents réels."""

    def test_process_cached_document(self, doc_path):
        """Teste Pass 0 avec un document du cache."""
        if not doc_path:
            pytest.skip("No --doc-path provided")

        if not Path(doc_path).exists():
            pytest.skip(f"Document not found: {doc_path}")

        from knowbase.stratified.pass0 import Pass0Adapter

        # Load document
        docling_doc = load_docling_from_cache(doc_path)

        # Process with adapter
        adapter = Pass0Adapter()
        result = adapter.process_document(
            docling_document=docling_doc,
            tenant_id="test",
            doc_id="integration_test",
        )

        # Validate result
        assert result is not None
        assert result.item_count > 0, "Document should have DocItems"
        assert result.chunk_count > 0, "Document should have chunks"

        # Log stats
        logger.info(f"Pass 0 Integration Test Results:")
        logger.info(f"  - Items: {result.item_count}")
        logger.info(f"  - Sections: {result.section_count}")
        logger.info(f"  - Chunks: {result.chunk_count}")
        logger.info(f"  - Chunk mappings: {len(result.chunk_to_docitem_map)}")

        # Validate mappings
        for chunk_id, mapping in result.chunk_to_docitem_map.items():
            assert len(mapping.docitem_ids) > 0, f"Chunk {chunk_id} has no DocItem mapping"

    def test_process_pdf_document(self, pdf_path):
        """Teste Pass 0 avec un nouveau PDF."""
        if not pdf_path:
            pytest.skip("No --pdf-path provided")

        if not Path(pdf_path).exists():
            pytest.skip(f"PDF not found: {pdf_path}")

        from knowbase.stratified.pass0 import Pass0Adapter

        # Process PDF with Docling
        docling_doc = process_pdf_with_docling(pdf_path)

        # Process with adapter
        adapter = Pass0Adapter()
        result = adapter.process_document(
            docling_document=docling_doc,
            tenant_id="test",
            doc_id=Path(pdf_path).stem,
        )

        # Validate
        assert result is not None
        assert result.item_count > 0

        # Print summary
        print(f"\n{'='*50}")
        print(f"Pass 0 - PDF Processing Results")
        print(f"{'='*50}")
        print(f"Document: {pdf_path}")
        print(f"  - Pages: {result.page_count}")
        print(f"  - Items: {result.item_count}")
        print(f"  - Sections: {result.section_count}")
        print(f"  - Chunks: {result.chunk_count}")
        print(f"{'='*50}")


@pytest.mark.integration
class TestPass0WithNeo4j:
    """Tests d'intégration avec persistance Neo4j."""

    @pytest.mark.asyncio
    async def test_persist_to_neo4j_v2(self, doc_path):
        """Teste la persistance vers Neo4j avec schéma V2."""
        if not doc_path:
            pytest.skip("No --doc-path provided")

        if not Path(doc_path).exists():
            pytest.skip(f"Document not found: {doc_path}")

        # Check Neo4j connection
        neo4j_uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        neo4j_user = os.environ.get("NEO4J_USER", "neo4j")
        neo4j_password = os.environ.get("NEO4J_PASSWORD", "")

        if not neo4j_password:
            pytest.skip("NEO4J_PASSWORD not set")

        from neo4j import AsyncGraphDatabase
        from knowbase.stratified.pass0 import Pass0Adapter

        # Load document
        docling_doc = load_docling_from_cache(doc_path)

        # Create driver
        driver = AsyncGraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))

        try:
            # Process and persist
            adapter = Pass0Adapter()
            result = await adapter.process_and_persist_v2(
                docling_document=docling_doc,
                tenant_id="test",
                doc_id="integration_test_v2",
                neo4j_driver=driver,
            )

            # Verify in Neo4j
            async with driver.session(database="neo4j") as session:
                # Check Document node
                doc_result = await session.run("""
                    MATCH (d:Document {tenant_id: 'test', doc_id: 'integration_test_v2'})
                    RETURN d.item_count as item_count
                """)
                record = await doc_result.single()
                assert record is not None, "Document should be created in Neo4j"
                assert record["item_count"] == result.item_count

                # Check DocItems
                items_result = await session.run("""
                    MATCH (i:DocItem {tenant_id: 'test'})
                    WHERE i.docitem_id STARTS WITH 'test:integration_test_v2:'
                    RETURN count(i) as count
                """)
                record = await items_result.single()
                assert record["count"] == result.item_count

            logger.info(f"Neo4j V2 persistence test passed!")
            logger.info(f"  - Document node created")
            logger.info(f"  - {result.item_count} DocItem nodes created")

        finally:
            await driver.close()


@pytest.mark.integration
class TestPass0Invariants:
    """Tests des invariants V2 sur document réel."""

    def test_v2_001_all_items_have_docitem_id(self, doc_path):
        """V2-001: Tous les DocItems ont un docitem_id V2."""
        if not doc_path:
            pytest.skip("No --doc-path provided")

        if not Path(doc_path).exists():
            pytest.skip(f"Document not found: {doc_path}")

        from knowbase.stratified.pass0 import Pass0Adapter
        from knowbase.stratified.pass0.adapter import get_docitem_id_v2

        docling_doc = load_docling_from_cache(doc_path)
        adapter = Pass0Adapter()
        result = adapter.process_document(
            docling_document=docling_doc,
            tenant_id="test",
            doc_id="invariant_test",
        )

        # Verify all items can generate valid docitem_id
        for item in result.doc_items:
            docitem_id = get_docitem_id_v2(
                result.tenant_id,
                result.doc_id,
                item.item_id,
            )
            assert docitem_id is not None
            assert docitem_id.startswith("test:invariant_test:")

    def test_v2_009_docitems_have_section(self, doc_path):
        """V2-009: Quasi-tous les DocItems ont une Section."""
        if not doc_path:
            pytest.skip("No --doc-path provided")

        if not Path(doc_path).exists():
            pytest.skip(f"Document not found: {doc_path}")

        from knowbase.stratified.pass0 import Pass0Adapter

        docling_doc = load_docling_from_cache(doc_path)
        adapter = Pass0Adapter()
        result = adapter.process_document(
            docling_document=docling_doc,
            tenant_id="test",
            doc_id="invariant_test",
        )

        # Count items with section
        items_with_section = sum(1 for item in result.doc_items if item.section_id)
        ratio = items_with_section / max(len(result.doc_items), 1)

        # At least 80% should have a section (some items may be pre-content)
        assert ratio >= 0.8, f"Only {ratio*100:.1f}% of items have a section (expected >= 80%)"

        logger.info(f"V2-009: {ratio*100:.1f}% of items have a section")
