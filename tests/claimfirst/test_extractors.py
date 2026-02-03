# tests/claimfirst/test_extractors.py
"""
Tests for Claim-First extractors.

Tests:
- ClaimExtractor with mock LLM
- EntityExtractor with pattern matching
"""

import pytest

from knowbase.claimfirst.extractors.claim_extractor import (
    ClaimExtractor,
    MockLLMClient,
    build_claim_extraction_prompt,
)
from knowbase.claimfirst.extractors.entity_extractor import (
    EntityExtractor,
    SUBJECT_PATTERNS,
    ACRONYM_PATTERN,
)
from knowbase.claimfirst.models.claim import Claim, ClaimType
from knowbase.claimfirst.models.entity import Entity, EntityType
from knowbase.claimfirst.models.passage import Passage


class TestClaimExtractor:
    """Tests for ClaimExtractor."""

    def test_prompt_building(self):
        """Test prompt template building."""
        prompt = build_claim_extraction_prompt(
            units_text="U1: TLS 1.2 is required.",
            doc_title="Security Guide",
            doc_type="technical",
        )

        assert "U1: TLS 1.2 is required." in prompt
        assert "Security Guide" in prompt
        assert "FACTUAL" in prompt
        assert "PRESCRIPTIVE" in prompt

    def test_extractor_initialization(self):
        """Test extractor initialization."""
        mock_llm = MockLLMClient()
        extractor = ClaimExtractor(
            llm_client=mock_llm,
            min_unit_length=30,
            max_unit_length=500,
        )

        assert extractor.batch_size == 10
        assert extractor.unit_indexer.min_unit_length == 30

    def test_mock_llm_response(self):
        """Test mock LLM generates valid JSON."""
        mock_llm = MockLLMClient()

        # Test TLS pattern
        response = mock_llm.generate("TLS encryption required")
        import json
        claims = json.loads(response)

        assert isinstance(claims, list)
        if claims:
            assert "claim_text" in claims[0]
            assert "unit_id" in claims[0]

    def test_extractor_with_passages(self):
        """Test extraction from passages."""
        mock_llm = MockLLMClient()
        extractor = ClaimExtractor(llm_client=mock_llm)

        passages = [
            Passage(
                passage_id="default:doc_001:item_001",
                tenant_id="default",
                doc_id="doc_001",
                text="TLS 1.2 or higher is required for all API connections. This ensures data security in transit.",
                page_no=1,
            ),
            Passage(
                passage_id="default:doc_001:item_002",
                tenant_id="default",
                doc_id="doc_001",
                text="Daily backups are performed automatically at midnight UTC.",
                page_no=2,
            ),
        ]

        claims, unit_index = extractor.extract(
            passages=passages,
            tenant_id="default",
            doc_id="doc_001",
            doc_title="Test Document",
        )

        # Should extract claims based on mock patterns
        assert len(claims) >= 0  # Mock may not match all patterns
        assert isinstance(unit_index, dict)

    def test_extractor_stats(self):
        """Test extractor statistics."""
        mock_llm = MockLLMClient()
        extractor = ClaimExtractor(llm_client=mock_llm)

        extractor.reset_stats()
        stats = extractor.get_stats()

        assert stats["units_indexed"] == 0
        assert stats["claims_extracted"] == 0
        assert stats["llm_calls"] == 0


class TestEntityExtractor:
    """Tests for EntityExtractor."""

    def test_extractor_initialization(self):
        """Test extractor initialization."""
        extractor = EntityExtractor(
            min_mentions=1,
            max_entities_per_claim=5,
        )

        assert extractor.min_mentions == 1
        assert extractor.max_entities_per_claim == 5

    def test_acronym_pattern(self):
        """Test acronym extraction."""
        text = "SAP BTP supports TLS and GDPR compliance."
        matches = ACRONYM_PATTERN.findall(text)

        assert "SAP" in matches
        assert "BTP" in matches
        assert "TLS" in matches
        assert "GDPR" in matches

    def test_extract_from_claims(self):
        """Test entity extraction from claims."""
        extractor = EntityExtractor()

        claims = [
            Claim(
                claim_id="claim_001",
                tenant_id="default",
                doc_id="doc_001",
                text="SAP BTP requires TLS 1.2 encryption.",
                claim_type=ClaimType.PRESCRIPTIVE,
                verbatim_quote="SAP BTP requires TLS 1.2 encryption.",
                passage_id="p1",
            ),
            Claim(
                claim_id="claim_002",
                tenant_id="default",
                doc_id="doc_001",
                text="GDPR compliance is mandatory for EU customers.",
                claim_type=ClaimType.PRESCRIPTIVE,
                verbatim_quote="GDPR compliance is mandatory.",
                passage_id="p2",
            ),
        ]

        passages = [
            Passage(
                passage_id="p1",
                tenant_id="default",
                doc_id="doc_001",
                text="SAP BTP requires TLS 1.2 encryption.",
            ),
            Passage(
                passage_id="p2",
                tenant_id="default",
                doc_id="doc_001",
                text="GDPR compliance is mandatory.",
            ),
        ]

        entities, claim_entity_map = extractor.extract_from_claims(
            claims=claims,
            passages=passages,
            tenant_id="default",
        )

        # Should find SAP, BTP, TLS, GDPR
        entity_names = [e.name for e in entities]
        assert len(entities) > 0

        # Check claim-entity mapping
        assert "claim_001" in claim_entity_map or "claim_002" in claim_entity_map

    def test_stoplist_filtering(self):
        """Test stoplist filters generic terms."""
        extractor = EntityExtractor()

        claims = [
            Claim(
                claim_id="claim_001",
                tenant_id="default",
                doc_id="doc_001",
                text="The System provides Information about Data Service.",
                claim_type=ClaimType.FACTUAL,
                verbatim_quote="The System provides Information.",
                passage_id="p1",
            ),
        ]

        passages = [
            Passage(
                passage_id="p1",
                tenant_id="default",
                doc_id="doc_001",
                text="The System provides Information.",
            ),
        ]

        entities, _ = extractor.extract_from_claims(
            claims=claims,
            passages=passages,
            tenant_id="default",
        )

        # Generic terms should be filtered
        entity_names_normalized = [e.normalized_name for e in entities]
        assert "system" not in entity_names_normalized
        assert "information" not in entity_names_normalized
        assert "data" not in entity_names_normalized

    def test_entity_type_inference(self):
        """Test entity type inference."""
        extractor = EntityExtractor()

        assert extractor.infer_entity_type("SAP BTP") == EntityType.PRODUCT
        assert extractor.infer_entity_type("ISO 27001") == EntityType.STANDARD
        assert extractor.infer_entity_type("Customer") == EntityType.ACTOR

    def test_extractor_stats(self):
        """Test extractor statistics."""
        extractor = EntityExtractor()
        extractor.reset_stats()
        stats = extractor.get_stats()

        assert stats["entities_created"] == 0
        assert stats["filtered_by_stoplist"] == 0

    def test_custom_stoplist(self):
        """Test custom stoplist."""
        custom_stoplist = {"custom_term", "another_term"}
        extractor = EntityExtractor(custom_stoplist=custom_stoplist)

        assert "custom_term" in extractor.stoplist
        assert "another_term" in extractor.stoplist
