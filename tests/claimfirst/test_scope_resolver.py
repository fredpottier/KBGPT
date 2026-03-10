# tests/claimfirst/test_scope_resolver.py
"""Tests — Scope Resolver cascade (v1 5 niveaux + v2 6 niveaux avec claim_llm)."""

import pytest
import asyncio
import json
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional
from unittest.mock import patch, AsyncMock, MagicMock

from knowbase.claimfirst.extractors.scope_resolver import (
    resolve_scope,
    resolve_scope_v2,
    _parse_scope_llm_response,
)


class FakeEntityType(str, Enum):
    PRODUCT = "product"
    STANDARD = "standard"
    CONCEPT = "concept"
    ACTOR = "actor"
    OTHER = "other"


@dataclass
class FakeEntity:
    entity_id: str
    name: str
    entity_type: FakeEntityType = FakeEntityType.PRODUCT


@dataclass
class FakeCanonicalEntity:
    canonical_entity_id: str
    canonical_name: str
    entity_type: FakeEntityType = FakeEntityType.PRODUCT
    source_entity_ids: List[str] = None

    def __post_init__(self):
        if self.source_entity_ids is None:
            self.source_entity_ids = []


@dataclass
class FakePassage:
    section_title: Optional[str] = None


@dataclass
class FakeDocContext:
    primary_subject: Optional[str] = None


@dataclass
class FakeClaim:
    claim_id: str = "c1"
    text: str = "Some claim text"


# ── V1 Tests (régression) ────────────────────────────────────────────

class TestScopeResolverCascade:

    def test_priority_1_claim_explicit_with_ce_match(self):
        ce = FakeCanonicalEntity("ce_1", "MyProduct", FakeEntityType.PRODUCT, ["e1"])
        result = resolve_scope(
            claim=FakeClaim(),
            canonical_entities=[ce],
            scope_evidence="MyProduct",
        )
        assert result.scope_basis == "claim_explicit"
        assert result.scope_confidence == 0.95
        assert result.primary_anchor_id == "ce_1"
        assert result.comparable_for_dimension is True

    def test_priority_1_claim_explicit_no_ce_match(self):
        result = resolve_scope(
            claim=FakeClaim(),
            scope_evidence="UnknownProduct",
        )
        assert result.scope_basis == "claim_explicit"
        assert result.scope_confidence == 0.90
        assert result.primary_anchor_label == "UnknownProduct"
        assert result.comparable_for_dimension is True

    def test_priority_2_claim_entities_product(self):
        entity = FakeEntity("e1", "Widget", FakeEntityType.PRODUCT)
        ce = FakeCanonicalEntity("ce_1", "Widget", FakeEntityType.PRODUCT, ["e1"])
        result = resolve_scope(
            claim=FakeClaim(),
            entities=[entity],
            canonical_entities=[ce],
        )
        assert result.scope_basis == "claim_entities"
        assert result.scope_confidence == 0.85
        assert result.primary_anchor_type == "product"
        assert result.primary_anchor_id == "ce_1"

    def test_priority_2_claim_entities_standard(self):
        entity = FakeEntity("e1", "ISO 27001", FakeEntityType.STANDARD)
        result = resolve_scope(
            claim=FakeClaim(),
            entities=[entity],
        )
        assert result.scope_basis == "claim_entities"
        assert result.primary_anchor_type == "legal_frame"

    def test_priority_2_skip_concept(self):
        entity = FakeEntity("e1", "Encryption", FakeEntityType.CONCEPT)
        passage = FakePassage(section_title="Security Requirements")
        result = resolve_scope(
            claim=FakeClaim(),
            entities=[entity],
            passage=passage,
        )
        assert result.scope_basis == "section_context"

    def test_priority_3_section_context(self):
        passage = FakePassage(section_title="Data Retention Policy")
        result = resolve_scope(
            claim=FakeClaim(),
            passage=passage,
        )
        assert result.scope_basis == "section_context"
        assert result.scope_confidence == 0.70
        assert result.primary_anchor_label == "Data Retention Policy"
        assert result.scope_status == "inherited"

    def test_priority_4_document_context(self):
        doc_ctx = FakeDocContext(primary_subject="Enterprise Platform")
        result = resolve_scope(
            claim=FakeClaim(),
            doc_context=doc_ctx,
        )
        assert result.scope_basis == "document_context"
        assert result.scope_confidence == 0.60
        assert result.primary_anchor_label == "Enterprise Platform"

    def test_priority_5_ambiguous(self):
        result = resolve_scope(claim=FakeClaim())
        assert result.scope_status == "ambiguous"
        assert result.scope_confidence == 0.0
        assert result.comparable_for_dimension is False

    def test_cascade_priority_order(self):
        entity = FakeEntity("e1", "Widget", FakeEntityType.PRODUCT)
        passage = FakePassage(section_title="Some Section")
        doc_ctx = FakeDocContext(primary_subject="Some Subject")

        result = resolve_scope(
            claim=FakeClaim(),
            entities=[entity],
            passage=passage,
            doc_context=doc_ctx,
            scope_evidence="ExplicitScope",
        )
        assert result.scope_basis == "claim_explicit"


# ── V2 Tests (claim_llm) ────────────────────────────────────────────

class TestScopeResolverV2:

    def test_v2_without_llm_same_as_v1(self):
        """Sans use_llm, v2 se comporte comme v1."""
        result = asyncio.get_event_loop().run_until_complete(
            resolve_scope_v2(
                claim=FakeClaim(),
                use_llm=False,
            )
        )
        assert result.scope_status == "ambiguous"

    def test_v2_claim_explicit_priority(self):
        """claim_explicit a toujours priorité sur claim_llm."""
        result = asyncio.get_event_loop().run_until_complete(
            resolve_scope_v2(
                claim=FakeClaim(text="Talent Management requires S_RFC"),
                scope_evidence="Talent Management",
                use_llm=True,
            )
        )
        assert result.scope_basis == "claim_explicit"

    @patch("knowbase.claimfirst.extractors.scope_resolver._extract_scope_via_llm")
    def test_v2_claim_llm_product(self, mock_llm):
        """LLM extrait scope_type=product → anchor_type=product."""
        mock_llm.return_value = {
            "primary_scope": "Talent Management",
            "secondary_scope": "",
            "scope_type": "product",
            "scope_found": True,
            "confidence": 0.92,
        }

        result = asyncio.get_event_loop().run_until_complete(
            resolve_scope_v2(
                claim=FakeClaim(text="Talent Management requires S_RFC authorization"),
                use_llm=True,
            )
        )
        assert result.scope_basis == "claim_llm"
        assert result.primary_anchor_label == "Talent Management"
        assert result.primary_anchor_type == "product"
        assert result.scope_confidence == 0.88  # Plafonnée

    @patch("knowbase.claimfirst.extractors.scope_resolver._extract_scope_via_llm")
    def test_v2_claim_llm_regulation(self, mock_llm):
        mock_llm.return_value = {
            "primary_scope": "GDPR",
            "scope_type": "regulation",
            "scope_found": True,
            "confidence": 0.95,
        }

        result = asyncio.get_event_loop().run_until_complete(
            resolve_scope_v2(
                claim=FakeClaim(text="GDPR requires data deletion within 30 days"),
                use_llm=True,
            )
        )
        assert result.scope_basis == "claim_llm"
        assert result.primary_anchor_type == "legal_frame"

    @patch("knowbase.claimfirst.extractors.scope_resolver._extract_scope_via_llm")
    def test_v2_claim_llm_not_found_falls_through(self, mock_llm):
        """scope_found=false → passe aux niveaux suivants."""
        mock_llm.return_value = {
            "scope_found": False,
            "confidence": 0.3,
        }

        passage = FakePassage(section_title="Security Section")
        result = asyncio.get_event_loop().run_until_complete(
            resolve_scope_v2(
                claim=FakeClaim(text="Some generic claim about security"),
                passage=passage,
                use_llm=True,
            )
        )
        assert result.scope_basis == "section_context"

    @patch("knowbase.claimfirst.extractors.scope_resolver._extract_scope_via_llm")
    def test_v2_claim_llm_error_falls_through(self, mock_llm):
        """Erreur LLM → passe aux niveaux suivants."""
        mock_llm.return_value = None

        doc_ctx = FakeDocContext(primary_subject="MyPlatform")
        result = asyncio.get_event_loop().run_until_complete(
            resolve_scope_v2(
                claim=FakeClaim(text="Some claim text here"),
                doc_context=doc_ctx,
                use_llm=True,
            )
        )
        assert result.scope_basis == "document_context"

    @patch("knowbase.claimfirst.extractors.scope_resolver._extract_scope_via_llm")
    def test_v2_claim_llm_before_entities(self, mock_llm):
        """claim_llm a priorité sur claim_entities (priorité 1.5 vs 2)."""
        mock_llm.return_value = {
            "primary_scope": "LLM Scope",
            "scope_type": "product",
            "scope_found": True,
            "confidence": 0.90,
        }

        entity = FakeEntity("e1", "Widget", FakeEntityType.PRODUCT)
        result = asyncio.get_event_loop().run_until_complete(
            resolve_scope_v2(
                claim=FakeClaim(text="Widget requires special config"),
                entities=[entity],
                use_llm=True,
            )
        )
        assert result.scope_basis == "claim_llm"
        assert result.primary_anchor_label == "LLM Scope"

    @patch("knowbase.claimfirst.extractors.scope_resolver._extract_scope_via_llm")
    def test_v2_confidence_capped(self, mock_llm):
        """Confiance LLM plafonnée à 0.88."""
        mock_llm.return_value = {
            "primary_scope": "Product",
            "scope_type": "product",
            "scope_found": True,
            "confidence": 0.99,
        }

        result = asyncio.get_event_loop().run_until_complete(
            resolve_scope_v2(
                claim=FakeClaim(text="Product does X"),
                use_llm=True,
            )
        )
        assert result.scope_confidence == 0.88


# ── Tests parser LLM ─────────────────────────────────────────────────

class TestParseScopeLLMResponse:

    def test_valid_response(self):
        resp = json.dumps({
            "primary_scope": "MyProduct",
            "scope_type": "product",
            "scope_found": True,
            "confidence": 0.9,
        })
        result = _parse_scope_llm_response(resp)
        assert result is not None
        assert result["primary_scope"] == "MyProduct"

    def test_invalid_json(self):
        result = _parse_scope_llm_response("not json")
        assert result is None

    def test_invalid_scope_type_normalized(self):
        resp = json.dumps({
            "primary_scope": "X",
            "scope_type": "invalid_type",
            "scope_found": True,
        })
        result = _parse_scope_llm_response(resp)
        assert result["scope_type"] == "other"

    def test_object_with_text_attr(self):
        """Objet avec .text contenant du JSON."""
        obj = MagicMock()
        obj.text = json.dumps({"scope_found": False})
        result = _parse_scope_llm_response(obj)
        assert result is not None
        assert result["scope_found"] is False
