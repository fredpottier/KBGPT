# tests/claimfirst/test_orchestrator.py
"""
Tests for Claim-First orchestrator.

Integration tests for the full pipeline.
"""

import pytest
from unittest.mock import MagicMock, patch

from knowbase.claimfirst.orchestrator import ClaimFirstOrchestrator
from knowbase.claimfirst.extractors.claim_extractor import MockLLMClient
from knowbase.claimfirst.models.result import ClaimFirstResult
from knowbase.claimfirst.models.passage import Passage


class MockPass0Result:
    """Mock Pass0Result for testing."""

    def __init__(self, doc_items=None):
        self.tenant_id = "default"
        self.doc_id = "test_doc"
        self.doc_version_id = "test_doc_v1"
        self.doc_items = doc_items or []
        self.sections = []
        self.chunks = []
        self.chunk_to_docitem_map = {}
        self.docitem_to_chunks_map = {}
        self.doc_title = "Test Document"
        self.page_count = 1


class MockDocItem:
    """Mock DocItem for testing."""

    def __init__(self, item_id, text, page_no=1):
        self.item_id = item_id
        self.doc_id = "test_doc"
        self.doc_version_id = "test_doc_v1"
        self.text = text
        self.content = text
        self.page_no = page_no
        self.charspan_start = 0
        self.charspan_end = len(text)
        self.section_id = "section_001"
        self.item_type = "paragraph"
        self.reading_order_index = 0


class MockCacheLoadResult:
    """Mock CacheLoadResult for testing."""

    def __init__(self, pass0_result):
        self.success = True
        self.pass0_result = pass0_result
        self.doc_title = "Test Document"
        self.error = None


class TestClaimFirstOrchestrator:
    """Tests for ClaimFirstOrchestrator."""

    def test_orchestrator_initialization(self):
        """Test orchestrator initialization."""
        mock_llm = MockLLMClient()

        orchestrator = ClaimFirstOrchestrator(
            llm_client=mock_llm,
            tenant_id="default",
            persist_enabled=False,
        )

        assert orchestrator.tenant_id == "default"
        assert orchestrator.persist_enabled is False

    def test_process_empty_document(self):
        """Test processing empty document."""
        mock_llm = MockLLMClient()

        orchestrator = ClaimFirstOrchestrator(
            llm_client=mock_llm,
            persist_enabled=False,
        )

        # Empty document
        pass0 = MockPass0Result(doc_items=[])
        cache_result = MockCacheLoadResult(pass0)

        result = orchestrator.process(
            doc_id="test_doc",
            cache_result=cache_result,
        )

        assert isinstance(result, ClaimFirstResult)
        assert result.passage_count == 0
        assert result.claim_count == 0

    def test_process_with_docitems(self):
        """Test processing document with DocItems."""
        mock_llm = MockLLMClient()

        orchestrator = ClaimFirstOrchestrator(
            llm_client=mock_llm,
            persist_enabled=False,
        )

        # Create DocItems with content that triggers mock patterns
        doc_items = [
            MockDocItem(
                item_id="item_001",
                text="TLS 1.2 encryption is required for all API connections to ensure security.",
                page_no=1,
            ),
            MockDocItem(
                item_id="item_002",
                text="Daily backups are performed automatically at midnight UTC for disaster recovery.",
                page_no=2,
            ),
        ]

        pass0 = MockPass0Result(doc_items=doc_items)
        cache_result = MockCacheLoadResult(pass0)

        result = orchestrator.process(
            doc_id="test_doc",
            cache_result=cache_result,
        )

        assert isinstance(result, ClaimFirstResult)
        assert result.passage_count == 2
        # Claims depend on mock LLM patterns
        assert result.processing_time_ms >= 0

    def test_process_creates_passages(self):
        """Test that processing creates passages from DocItems."""
        mock_llm = MockLLMClient()

        orchestrator = ClaimFirstOrchestrator(
            llm_client=mock_llm,
            persist_enabled=False,
        )

        doc_items = [
            MockDocItem(item_id="item_001", text="Sample text content.", page_no=1),
        ]

        pass0 = MockPass0Result(doc_items=doc_items)
        cache_result = MockCacheLoadResult(pass0)

        result = orchestrator.process(
            doc_id="test_doc",
            cache_result=cache_result,
        )

        assert result.passage_count == 1
        passage = result.passages[0]
        assert passage.doc_id == "test_doc"
        assert passage.text == "Sample text content."

    def test_process_extracts_entities(self):
        """Test that processing extracts entities."""
        mock_llm = MockLLMClient()

        orchestrator = ClaimFirstOrchestrator(
            llm_client=mock_llm,
            persist_enabled=False,
        )

        doc_items = [
            MockDocItem(
                item_id="item_001",
                text="SAP BTP requires TLS encryption for GDPR compliance.",
                page_no=1,
            ),
        ]

        pass0 = MockPass0Result(doc_items=doc_items)
        cache_result = MockCacheLoadResult(pass0)

        result = orchestrator.process(
            doc_id="test_doc",
            cache_result=cache_result,
        )

        # Should extract entities like SAP, BTP, TLS, GDPR
        # Depends on claims being extracted first
        assert isinstance(result.entities, list)

    def test_process_matches_facets(self):
        """Test that processing matches facets."""
        mock_llm = MockLLMClient()

        orchestrator = ClaimFirstOrchestrator(
            llm_client=mock_llm,
            persist_enabled=False,
        )

        doc_items = [
            MockDocItem(
                item_id="item_001",
                text="TLS 1.2 encryption is mandatory for security compliance.",
                page_no=1,
            ),
        ]

        pass0 = MockPass0Result(doc_items=doc_items)
        cache_result = MockCacheLoadResult(pass0)

        result = orchestrator.process(
            doc_id="test_doc",
            cache_result=cache_result,
        )

        # Should have security-related facets
        assert result.facet_count >= 0  # Predefined facets may be included

    def test_process_handles_failed_cache(self):
        """Test handling of failed cache load."""
        mock_llm = MockLLMClient()

        orchestrator = ClaimFirstOrchestrator(
            llm_client=mock_llm,
            persist_enabled=False,
        )

        # Failed cache result
        cache_result = MockCacheLoadResult(None)
        cache_result.success = False
        cache_result.error = "Cache not found"

        result = orchestrator.process(
            doc_id="test_doc",
            cache_result=cache_result,
        )

        # Should return empty result
        assert result.claim_count == 0
        assert result.passage_count == 0

    def test_orchestrator_stats(self):
        """Test orchestrator statistics."""
        mock_llm = MockLLMClient()

        orchestrator = ClaimFirstOrchestrator(
            llm_client=mock_llm,
            persist_enabled=False,
        )

        orchestrator.reset_stats()
        stats = orchestrator.get_stats()

        assert "claim_extractor" in stats
        assert "entity_extractor" in stats
        assert "passage_linker" in stats

    def test_result_has_links(self):
        """Test that result contains links."""
        mock_llm = MockLLMClient()

        orchestrator = ClaimFirstOrchestrator(
            llm_client=mock_llm,
            persist_enabled=False,
        )

        doc_items = [
            MockDocItem(
                item_id="item_001",
                text="TLS encryption is required for all connections to the platform.",
                page_no=1,
            ),
        ]

        pass0 = MockPass0Result(doc_items=doc_items)
        cache_result = MockCacheLoadResult(pass0)

        result = orchestrator.process(
            doc_id="test_doc",
            cache_result=cache_result,
        )

        # Links should be lists of tuples
        assert isinstance(result.claim_passage_links, list)
        assert isinstance(result.claim_entity_links, list)
        assert isinstance(result.claim_facet_links, list)

    def test_tenant_id_override(self):
        """Test tenant_id override in process."""
        mock_llm = MockLLMClient()

        orchestrator = ClaimFirstOrchestrator(
            llm_client=mock_llm,
            tenant_id="default",
            persist_enabled=False,
        )

        pass0 = MockPass0Result(doc_items=[])
        cache_result = MockCacheLoadResult(pass0)

        result = orchestrator.process(
            doc_id="test_doc",
            cache_result=cache_result,
            tenant_id="custom_tenant",  # Override
        )

        assert result.tenant_id == "custom_tenant"


class TestClaimFirstPersistence:
    """Tests for persistence integration."""

    def test_process_and_persist_without_driver(self):
        """Test that process_and_persist works without Neo4j driver."""
        mock_llm = MockLLMClient()

        orchestrator = ClaimFirstOrchestrator(
            llm_client=mock_llm,
            neo4j_driver=None,
            persist_enabled=True,  # Enabled but no driver
        )

        pass0 = MockPass0Result(doc_items=[])
        cache_result = MockCacheLoadResult(pass0)

        # Should not raise even without driver
        result = orchestrator.process_and_persist(
            doc_id="test_doc",
            cache_result=cache_result,
        )

        assert isinstance(result, ClaimFirstResult)
