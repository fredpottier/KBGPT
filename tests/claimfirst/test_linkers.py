# tests/claimfirst/test_linkers.py
"""
Tests for Claim-First linkers.

Tests:
- PassageLinker (Claim → Passage via unit spans)
- EntityLinker (Claim → Entity, no role V1)
- FacetMatcher (Claim → Facet via patterns)
"""

import pytest

from knowbase.claimfirst.linkers.passage_linker import PassageLinker
from knowbase.claimfirst.linkers.entity_linker import EntityLinker
from knowbase.claimfirst.linkers.facet_matcher import FacetMatcher
from knowbase.claimfirst.models.claim import Claim, ClaimType
from knowbase.claimfirst.models.entity import Entity, EntityType
from knowbase.claimfirst.models.passage import Passage
from knowbase.stratified.pass1.assertion_unit_indexer import (
    AssertionUnitIndexer,
    UnitIndexResult,
    AssertionUnit,
)


class TestPassageLinker:
    """Tests for PassageLinker."""

    def test_linker_initialization(self):
        """Test linker initialization."""
        linker = PassageLinker()
        assert linker.stats["claims_processed"] == 0

    def test_link_via_passage_id(self):
        """Test linking via direct passage_id."""
        linker = PassageLinker()

        claims = [
            Claim(
                claim_id="claim_001",
                tenant_id="default",
                doc_id="doc_001",
                text="Test claim.",
                claim_type=ClaimType.FACTUAL,
                verbatim_quote="Test claim.",
                passage_id="p1",
            ),
        ]

        passages = [
            Passage(
                passage_id="p1",
                tenant_id="default",
                doc_id="doc_001",
                text="Test passage.",
            ),
        ]

        links = linker.link(claims, passages, unit_index={})

        assert len(links) == 1
        assert links[0] == ("claim_001", "p1")

    def test_link_via_unit_spans(self):
        """Test linking via unit spans."""
        linker = PassageLinker()

        passage_id = "default:doc_001:item_001"
        claims = [
            Claim(
                claim_id="claim_001",
                tenant_id="default",
                doc_id="doc_001",
                text="Test claim.",
                claim_type=ClaimType.FACTUAL,
                verbatim_quote="Test claim.",
                passage_id="",  # No direct passage_id
                unit_ids=[f"{passage_id}#U1"],
            ),
        ]

        passages = [
            Passage(
                passage_id=passage_id,
                tenant_id="default",
                doc_id="doc_001",
                text="Test passage text here.",
                char_start=0,
                char_end=100,
            ),
        ]

        # Create unit index
        unit = AssertionUnit(
            unit_local_id="U1",
            docitem_id=passage_id,
            text="Test claim.",
            char_start=0,
            char_end=11,
            unit_type="sentence",
        )
        unit_result = UnitIndexResult(docitem_id=passage_id, units=[unit])
        unit_index = {passage_id: unit_result}

        links = linker.link(claims, passages, unit_index)

        assert len(links) == 1
        assert links[0][1] == passage_id

    def test_orphan_claims(self):
        """Test handling of orphan claims."""
        linker = PassageLinker()

        claims = [
            Claim(
                claim_id="claim_001",
                tenant_id="default",
                doc_id="doc_001",
                text="Test claim.",
                claim_type=ClaimType.FACTUAL,
                verbatim_quote="Test claim.",
                passage_id="non_existent_passage",
            ),
        ]

        passages = []  # No passages

        links = linker.link(claims, passages, unit_index={})

        assert len(links) == 0
        assert linker.stats["orphan_claims"] == 1

    def test_linker_stats(self):
        """Test linker statistics."""
        linker = PassageLinker()
        linker.reset_stats()
        stats = linker.get_stats()

        assert stats["claims_processed"] == 0
        assert stats["links_created"] == 0


class TestEntityLinker:
    """Tests for EntityLinker."""

    def test_linker_initialization(self):
        """Test linker initialization."""
        linker = EntityLinker()
        assert linker.min_entity_length == 2

    def test_basic_linking(self):
        """Test basic entity linking."""
        linker = EntityLinker()

        claims = [
            Claim(
                claim_id="claim_001",
                tenant_id="default",
                doc_id="doc_001",
                text="SAP BTP requires TLS encryption.",
                claim_type=ClaimType.PRESCRIPTIVE,
                verbatim_quote="SAP BTP requires TLS encryption.",
                passage_id="p1",
            ),
        ]

        entities = [
            Entity(
                entity_id="e1",
                tenant_id="default",
                name="SAP BTP",
                entity_type=EntityType.PRODUCT,
            ),
            Entity(
                entity_id="e2",
                tenant_id="default",
                name="TLS",
                entity_type=EntityType.CONCEPT,
            ),
        ]

        links = linker.link(claims, entities)

        # Should link both entities
        linked_entity_ids = [eid for _, eid in links]
        assert "e1" in linked_entity_ids
        assert "e2" in linked_entity_ids

    def test_no_partial_matches(self):
        """Test that partial matches are avoided."""
        linker = EntityLinker()

        claims = [
            Claim(
                claim_id="claim_001",
                tenant_id="default",
                doc_id="doc_001",
                text="The CAPITAL investment is significant.",
                claim_type=ClaimType.FACTUAL,
                verbatim_quote="The CAPITAL investment is significant.",
                passage_id="p1",
            ),
        ]

        entities = [
            Entity(
                entity_id="e1",
                tenant_id="default",
                name="API",  # Should NOT match "cAPItal"
                entity_type=EntityType.CONCEPT,
            ),
        ]

        links = linker.link(claims, entities)

        # API should not match in CAPITAL
        assert len(links) == 0

    def test_alias_matching(self):
        """Test matching via aliases."""
        linker = EntityLinker()

        claims = [
            Claim(
                claim_id="claim_001",
                tenant_id="default",
                doc_id="doc_001",
                text="The Business Technology Platform is great.",
                claim_type=ClaimType.FACTUAL,
                verbatim_quote="The Business Technology Platform is great.",
                passage_id="p1",
            ),
        ]

        entities = [
            Entity(
                entity_id="e1",
                tenant_id="default",
                name="SAP BTP",
                entity_type=EntityType.PRODUCT,
                aliases=["Business Technology Platform"],
            ),
        ]

        links = linker.link(claims, entities)

        # Should match via alias
        assert len(links) == 1
        assert links[0] == ("claim_001", "e1")

    def test_link_with_confidence(self):
        """Test linking with confidence scores."""
        linker = EntityLinker()

        claims = [
            Claim(
                claim_id="claim_001",
                tenant_id="default",
                doc_id="doc_001",
                text="SAP BTP is a platform.",
                claim_type=ClaimType.FACTUAL,
                verbatim_quote="SAP BTP is a platform.",
                passage_id="p1",
            ),
        ]

        entities = [
            Entity(
                entity_id="e1",
                tenant_id="default",
                name="SAP BTP",
                entity_type=EntityType.PRODUCT,
            ),
        ]

        links = linker.link_with_confidence(claims, entities)

        assert len(links) == 1
        claim_id, entity_id, confidence = links[0]
        assert confidence >= 0.9  # High confidence for exact match

    def test_linker_stats(self):
        """Test linker statistics."""
        linker = EntityLinker()
        linker.reset_stats()
        stats = linker.get_stats()

        assert stats["claims_processed"] == 0
        assert stats["links_created"] == 0


class TestFacetMatcher:
    """Tests for FacetMatcher."""

    def test_matcher_initialization(self):
        """Test matcher initialization."""
        matcher = FacetMatcher(include_predefined=True)
        assert matcher.min_confidence == 0.5

    def test_pattern_matching(self):
        """Test pattern-based facet matching."""
        matcher = FacetMatcher()

        claims = [
            Claim(
                claim_id="claim_001",
                tenant_id="default",
                doc_id="doc_001",
                text="TLS 1.2 encryption is required for all connections.",
                claim_type=ClaimType.PRESCRIPTIVE,
                verbatim_quote="TLS 1.2 encryption is required.",
                passage_id="p1",
            ),
            Claim(
                claim_id="claim_002",
                tenant_id="default",
                doc_id="doc_001",
                text="Daily backups are performed at midnight.",
                claim_type=ClaimType.FACTUAL,
                verbatim_quote="Daily backups are performed.",
                passage_id="p2",
            ),
        ]

        facets, links = matcher.match(claims, tenant_id="default")

        # Should create facets from patterns
        assert len(facets) > 0
        assert len(links) > 0

        # Check facet domains
        domains = [f.domain for f in facets]
        # Should have security-related facets due to "TLS" and "encryption"
        assert any("security" in d for d in domains)

    def test_predefined_facets_included(self):
        """Test predefined facets are included."""
        matcher = FacetMatcher(include_predefined=True)

        claims = [
            Claim(
                claim_id="claim_001",
                tenant_id="default",
                doc_id="doc_001",
                text="Security measures are in place.",
                claim_type=ClaimType.FACTUAL,
                verbatim_quote="Security measures are in place.",
                passage_id="p1",
            ),
        ]

        facets, links = matcher.match(claims, tenant_id="default")

        # Should have predefined facets
        domains = [f.domain for f in facets]
        assert "security" in domains

    def test_keyword_matching(self):
        """Test keyword-based facet matching."""
        matcher = FacetMatcher()

        claims = [
            Claim(
                claim_id="claim_001",
                tenant_id="default",
                doc_id="doc_001",
                text="GDPR compliance ensures data protection.",
                claim_type=ClaimType.FACTUAL,
                verbatim_quote="GDPR compliance ensures data protection.",
                passage_id="p1",
            ),
        ]

        facets, links = matcher.match(claims, tenant_id="default")

        # Should match GDPR-related facets
        linked_claim_ids = [cid for cid, _ in links]
        assert "claim_001" in linked_claim_ids

    def test_matcher_stats(self):
        """Test matcher statistics."""
        matcher = FacetMatcher()
        matcher.reset_stats()
        stats = matcher.get_stats()

        assert stats["claims_processed"] == 0
        assert stats["patterns_matched"] == 0
