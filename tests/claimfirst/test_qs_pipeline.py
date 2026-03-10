# tests/claimfirst/test_qs_pipeline.py
"""Tests Phase 5 — Pipeline end-to-end avec mocks LLM."""

import pytest
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

from knowbase.claimfirst.extractors.comparability_gate import candidate_gate
from knowbase.claimfirst.extractors.scope_resolver import resolve_scope
from knowbase.claimfirst.extractors.dimension_mapper import map_to_dimension
from knowbase.claimfirst.extractors.qs_llm_extractor import (
    _parse_gate_response,
    _parse_extraction_response,
)
from knowbase.claimfirst.models.question_dimension import QuestionDimension
from knowbase.claimfirst.models.question_signature import (
    QuestionSignature,
    QSValueType,
    QSExtractionMethod,
)


class FakeEntityType(str, Enum):
    PRODUCT = "product"


@dataclass
class FakeClaim:
    claim_id: str
    doc_id: str
    text: str
    structured_form: Optional[Dict] = None
    claim_type: Optional[str] = None


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
class FakeDocContext:
    primary_subject: Optional[str] = None


class TestEndToEndPipeline:
    """Pipeline complet avec 3 claims synthétiques couvrant les 4 étapes."""

    CLAIMS = [
        FakeClaim(
            claim_id="c1", doc_id="d1",
            text="The system requires a minimum of 256 GB of storage for production deployment",
            structured_form={"subject": "system", "entities": [{"name": "ProductA"}]},
        ),
        FakeClaim(
            claim_id="c2", doc_id="d1",
            text="Data retention period must not exceed 36 months for compliance purposes",
            structured_form={"subject": "data", "entities": [{"name": "ProductA"}]},
        ),
        FakeClaim(
            claim_id="c3", doc_id="d2",
            text="The platform requires at least 128 GB of storage for standard operations",
            structured_form={"subject": "platform", "entities": [{"name": "ProductB"}]},
        ),
    ]

    def test_step0_gating(self):
        """Étape 0 — Les 3 claims ont des signaux forts."""
        for claim in self.CLAIMS:
            result = candidate_gate(claim)
            assert result.retained, f"Claim {claim.claim_id} should be retained: {result.rejection_reason}"
            assert len(result.signals) > 0

    def test_step1_llm_gate_mock(self):
        """Étape 1 — Mock LLM gate parsing."""
        responses = [
            '{"label": "COMPARABLE_FACT"}',
            '{"label": "COMPARABLE_FACT"}',
            '{"label": "COMPARABLE_FACT"}',
        ]
        for resp in responses:
            assert _parse_gate_response(resp) == "COMPARABLE_FACT"

    def test_step2_llm_extraction_mock(self):
        """Étape 2 — Mock LLM extraction parsing."""
        response = '''{
            "candidate_question": "What is the minimum storage requirement?",
            "candidate_dimension_key": "min_storage",
            "value_type": "number",
            "value_raw": "256 GB",
            "value_normalized": "256",
            "operator": ">=",
            "scope_evidence": "ProductA",
            "scope_basis": "claim_explicit",
            "confidence": 0.92
        }'''
        result = _parse_extraction_response(
            response, "c1", "d1",
            {"c1": ("COMPARABLE_FACT", ["strong:numeric_with_unit", "strong:constraint_min_max"])},
        )
        assert result is not None
        assert result.is_valid()
        assert result.value_type == "number"
        assert result.gate_label == "COMPARABLE_FACT"

    def test_step3a_dimension_mapper(self):
        """Étape 3a — Mapper crée une nouvelle dimension puis matche."""
        registry: List[QuestionDimension] = []

        # Premier candidat → nouvelle dimension
        dim_id, score = map_to_dimension(
            "min_storage", "What is the min storage?",
            "number", ">=", registry,
        )
        assert dim_id is None  # Pas encore dans le registre

        # Créer la dimension
        new_dim = QuestionDimension(
            dimension_id=QuestionDimension.make_id("default", "min_storage"),
            dimension_key="min_storage",
            canonical_question="What is the minimum storage requirement?",
            value_type="number",
            allowed_operators=[">="],
            value_comparable="strict",
            tenant_id="default",
        )
        registry.append(new_dim)

        # Deuxième candidat avec même clé → match exact
        dim_id2, score2 = map_to_dimension(
            "min_storage", "What is the minimum storage?",
            "number", ">=", registry,
        )
        assert dim_id2 == new_dim.dimension_id
        assert score2 == 1.0

    def test_step3b_scope_resolver(self):
        """Étape 3b — Scope résolu via entities."""
        entity = FakeEntity("e1", "ProductA", FakeEntityType.PRODUCT)
        ce = FakeCanonicalEntity("ce_1", "ProductA", FakeEntityType.PRODUCT, ["e1"])

        scope = resolve_scope(
            claim=self.CLAIMS[0],
            entities=[entity],
            canonical_entities=[ce],
            scope_evidence="ProductA",
        )
        assert scope.scope_status == "resolved"
        assert scope.primary_anchor_id == "ce_1"

    def test_full_pipeline_produces_qs(self):
        """Pipeline complet : gating → mock LLM → scope → QS finale."""
        # Étape 0 : gating
        retained = [c for c in self.CLAIMS if candidate_gate(c).retained]
        assert len(retained) == 3

        # Étape 1+2 : mock LLM (simulé via parse)
        extraction_resp = '''{
            "candidate_question": "What is the minimum storage requirement?",
            "candidate_dimension_key": "min_storage",
            "value_type": "number",
            "value_raw": "256 GB",
            "value_normalized": "256",
            "operator": ">=",
            "scope_evidence": "ProductA",
            "scope_basis": "claim_explicit",
            "confidence": 0.92
        }'''
        candidate = _parse_extraction_response(extraction_resp, "c1", "d1", {})
        assert candidate is not None

        # Étape 3b : scope
        scope = resolve_scope(
            claim=retained[0],
            scope_evidence=candidate.scope_evidence,
        )

        # Construire QS finale
        qs = QuestionSignature(
            qs_id=f"qs_{candidate.claim_id}_min_storage",
            claim_id=candidate.claim_id,
            doc_id=candidate.doc_id,
            question=candidate.candidate_question,
            dimension_key=candidate.candidate_dimension_key,
            value_type=QSValueType(candidate.value_type),
            extracted_value=candidate.value_raw,
            value_normalized=candidate.value_normalized,
            operator=candidate.operator,
            extraction_method=QSExtractionMethod.LLM_LEVEL_B,
            confidence=candidate.confidence,
        )
        qs.set_resolved_scope(scope)

        assert qs.dimension_key == "min_storage"
        assert qs.extraction_method == QSExtractionMethod.LLM_LEVEL_B
        rs = qs.get_resolved_scope()
        assert rs is not None
        assert rs.scope_basis == "claim_explicit"
