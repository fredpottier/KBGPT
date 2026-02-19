# tests/claimfirst/test_quality_kg_v14.py
"""
Tests unitaires pour V1.4 : LLM Merge Arbiter + Quality Gates PASS + Champion/Redundant.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from knowbase.claimfirst.models.claim import Claim, ClaimType, ClaimScope


# ============================================================================
# Helpers
# ============================================================================

def _make_claim(
    claim_id: str = "c1",
    text: str = "SAP S/4HANA supports TLS 1.2 encryption",
    confidence: float = 0.9,
    quality_status: Optional[str] = None,
    quality_scores: Optional[Dict[str, float]] = None,
    is_champion: Optional[bool] = None,
    redundant: Optional[bool] = None,
    champion_claim_id: Optional[str] = None,
    doc_id: str = "doc_001",
    cluster_id: Optional[str] = None,
) -> Claim:
    return Claim(
        claim_id=claim_id,
        tenant_id="default",
        doc_id=doc_id,
        text=text,
        claim_type=ClaimType.FACTUAL,
        verbatim_quote=text,
        passage_id="p1",
        confidence=confidence,
        quality_status=quality_status,
        quality_scores=quality_scores,
        is_champion=is_champion,
        redundant=redundant,
        champion_claim_id=champion_claim_id,
        cluster_id=cluster_id,
    )


# ============================================================================
# C.1 — Claim model : champion/redundant fields
# ============================================================================

class TestClaimChampionFields:
    """Teste les champs V1.4 is_champion, redundant, champion_claim_id."""

    def test_default_values_are_none(self):
        claim = _make_claim()
        assert claim.is_champion is None
        assert claim.redundant is None
        assert claim.champion_claim_id is None

    def test_set_champion(self):
        claim = _make_claim(is_champion=True)
        assert claim.is_champion is True
        assert claim.redundant is None

    def test_set_redundant(self):
        claim = _make_claim(redundant=True, champion_claim_id="c_champ")
        assert claim.redundant is True
        assert claim.champion_claim_id == "c_champ"
        assert claim.is_champion is None

    def test_to_neo4j_properties_includes_champion_fields(self):
        claim = _make_claim(is_champion=True)
        props = claim.to_neo4j_properties()
        assert props["is_champion"] is True
        assert "redundant" not in props  # None → pas inclus
        assert "champion_claim_id" not in props

    def test_to_neo4j_properties_includes_redundant_fields(self):
        claim = _make_claim(redundant=True, champion_claim_id="c_champ")
        props = claim.to_neo4j_properties()
        assert props["redundant"] is True
        assert props["champion_claim_id"] == "c_champ"
        assert "is_champion" not in props  # None → pas inclus

    def test_to_neo4j_properties_excludes_none_fields(self):
        claim = _make_claim()
        props = claim.to_neo4j_properties()
        assert "is_champion" not in props
        assert "redundant" not in props
        assert "champion_claim_id" not in props

    def test_from_neo4j_record_reads_champion_fields(self):
        record = {
            "claim_id": "c1",
            "tenant_id": "default",
            "doc_id": "doc_001",
            "text": "SAP S/4HANA supports TLS 1.2 encryption",
            "claim_type": "FACTUAL",
            "verbatim_quote": "SAP S/4HANA supports TLS 1.2 encryption",
            "passage_id": "p1",
            "confidence": 0.9,
            "is_champion": True,
            "redundant": None,
            "champion_claim_id": None,
        }
        claim = Claim.from_neo4j_record(record)
        assert claim.is_champion is True
        assert claim.redundant is None
        assert claim.champion_claim_id is None

    def test_from_neo4j_record_reads_redundant_fields(self):
        record = {
            "claim_id": "c2",
            "tenant_id": "default",
            "doc_id": "doc_001",
            "text": "SAP S/4HANA supports TLS 1.2 encryption",
            "claim_type": "FACTUAL",
            "verbatim_quote": "SAP S/4HANA supports TLS 1.2 encryption",
            "passage_id": "p1",
            "confidence": 0.7,
            "is_champion": None,
            "redundant": True,
            "champion_claim_id": "c1",
        }
        claim = Claim.from_neo4j_record(record)
        assert claim.redundant is True
        assert claim.champion_claim_id == "c1"


# ============================================================================
# B.1 — mark_pass_on_remaining
# ============================================================================

class TestMarkPassOnRemaining:
    """Teste QualityGateRunner.mark_pass_on_remaining()."""

    def test_marks_claims_without_quality_status(self):
        from knowbase.claimfirst.quality.quality_gate_runner import QualityGateRunner

        claims = [
            _make_claim(claim_id="c1", quality_status=None),
            _make_claim(claim_id="c2", quality_status=None),
        ]
        verif_scores = {"c1": 0.92, "c2": 0.88}

        count = QualityGateRunner.mark_pass_on_remaining(claims, verif_scores)

        assert count == 2
        assert claims[0].quality_status == "PASS"
        assert claims[1].quality_status == "PASS"
        assert claims[0].quality_scores["verif_score"] == 0.92
        assert claims[1].quality_scores["verif_score"] == 0.88

    def test_skips_claims_with_existing_status(self):
        from knowbase.claimfirst.quality.quality_gate_runner import QualityGateRunner

        claims = [
            _make_claim(claim_id="c1", quality_status="REJECT_FABRICATION"),
            _make_claim(claim_id="c2", quality_status=None),
        ]
        verif_scores = {"c1": 0.75, "c2": 0.90}

        count = QualityGateRunner.mark_pass_on_remaining(claims, verif_scores)

        assert count == 1
        assert claims[0].quality_status == "REJECT_FABRICATION"
        assert claims[1].quality_status == "PASS"

    def test_handles_missing_verif_score(self):
        from knowbase.claimfirst.quality.quality_gate_runner import QualityGateRunner

        claims = [_make_claim(claim_id="c1", quality_status=None)]
        verif_scores = {}  # pas de score pour c1

        count = QualityGateRunner.mark_pass_on_remaining(claims, verif_scores)

        assert count == 1
        assert claims[0].quality_status == "PASS"
        assert claims[0].quality_scores is None  # pas de score → pas de dict

    def test_empty_claims_list(self):
        from knowbase.claimfirst.quality.quality_gate_runner import QualityGateRunner

        count = QualityGateRunner.mark_pass_on_remaining([], {})
        assert count == 0

    def test_preserves_existing_quality_scores(self):
        from knowbase.claimfirst.quality.quality_gate_runner import QualityGateRunner

        claims = [
            _make_claim(
                claim_id="c1",
                quality_status=None,
                quality_scores={"triviality": 0.3},
            ),
        ]
        verif_scores = {"c1": 0.91}

        QualityGateRunner.mark_pass_on_remaining(claims, verif_scores)

        assert claims[0].quality_scores == {"triviality": 0.3, "verif_score": 0.91}


# ============================================================================
# C.2 — Champion marking dans ClaimClusterer
# ============================================================================

class TestChampionMarkingInClusterer:
    """Teste que ClaimClusterer marque is_champion/redundant."""

    def test_champion_and_redundant_marking(self):
        from knowbase.claimfirst.clustering.claim_clusterer import ClaimClusterer

        claims = [
            _make_claim(claim_id="c1", confidence=0.95, text="SAP S/4HANA supports TLS 1.2 encryption"),
            _make_claim(claim_id="c2", confidence=0.85, text="SAP S/4HANA supports TLS 1.2 for security"),
            _make_claim(claim_id="c3", confidence=0.75, text="S/4HANA has TLS 1.2 support built in"),
        ]

        # Créer des embeddings synthétiques très similaires
        import numpy as np
        base = np.random.randn(10)
        embeddings = {
            "c1": base + np.random.randn(10) * 0.01,
            "c2": base + np.random.randn(10) * 0.01,
            "c3": base + np.random.randn(10) * 0.01,
        }

        # Entités communes
        entities_by_claim = {
            "c1": ["e_s4hana", "e_tls"],
            "c2": ["e_s4hana", "e_tls"],
            "c3": ["e_s4hana", "e_tls"],
        }

        clusterer = ClaimClusterer(
            embedding_threshold=0.90,
            lexical_overlap_min=0.2,
        )
        clusters = clusterer.cluster(
            claims=claims,
            embeddings=embeddings,
            entities_by_claim=entities_by_claim,
        )

        # Au moins un cluster créé
        assert len(clusters) >= 1

        # Vérifier champion marking
        champion_claims = [c for c in claims if c.is_champion is True]
        redundant_claims = [c for c in claims if c.redundant is True]

        # Le champion doit être c1 (plus haute confiance)
        if champion_claims:
            assert champion_claims[0].claim_id == "c1"
            assert champion_claims[0].is_champion is True

        # Les redundants pointent vers le champion
        for rc in redundant_claims:
            assert rc.champion_claim_id == "c1"


# ============================================================================
# A.1 — MergeArbiter : gates déterministes
# ============================================================================

class TestMergeArbiterDeterministic:
    """Teste les gates déterministes du MergeArbiter."""

    def test_prefix_dedup(self):
        from knowbase.claimfirst.extractors.merge_arbiter import MergeArbiter, MergeResult

        entities = [
            {"entity_id": "e1", "name": "SAP SAP S/4HANA", "normalized_name": "sap sap s4hana", "claim_count": 10},
            {"entity_id": "e2", "name": "SAP S/4HANA", "normalized_name": "sap s4hana", "claim_count": 50},
        ]

        arbiter = MergeArbiter()
        result = MergeResult()
        remaining = arbiter.deterministic_pass(entities, result)

        assert result.stats["prefix_dedup"] == 1
        assert len(result.deterministic_merges) >= 1
        merge = result.deterministic_merges[0]
        assert merge.target_id == "e2"
        assert "e1" in merge.source_ids
        assert merge.rule == "prefix_duplication"

    def test_case_only_merge(self):
        from knowbase.claimfirst.extractors.merge_arbiter import MergeArbiter, MergeResult

        entities = [
            {"entity_id": "e1", "name": "SAP BTP", "normalized_name": "sap btp", "claim_count": 5},
            {"entity_id": "e2", "name": "sap btp", "normalized_name": "sap btp", "claim_count": 20},
        ]

        arbiter = MergeArbiter()
        result = MergeResult()
        remaining = arbiter.deterministic_pass(entities, result)

        assert result.stats["case_only"] == 1
        merge = result.deterministic_merges[0]
        assert merge.target_id == "e2"  # plus de claims
        assert merge.rule == "case_only"

    def test_version_stripping(self):
        from knowbase.claimfirst.extractors.merge_arbiter import MergeArbiter, MergeResult

        entities = [
            {"entity_id": "e1", "name": "React", "normalized_name": "react", "claim_count": 30},
            {"entity_id": "e2", "name": "React 18", "normalized_name": "react 18", "claim_count": 10},
        ]

        arbiter = MergeArbiter()
        result = MergeResult()
        remaining = arbiter.deterministic_pass(entities, result)

        assert result.stats["version_strip"] == 1
        merge = [m for m in result.deterministic_merges if m.rule == "version_qualifier"]
        assert len(merge) == 1
        assert merge[0].target_id == "e1"  # sans version → canonical

    def test_no_merge_when_different(self):
        from knowbase.claimfirst.extractors.merge_arbiter import MergeArbiter, MergeResult

        entities = [
            {"entity_id": "e1", "name": "React", "normalized_name": "react", "claim_count": 30},
            {"entity_id": "e2", "name": "Angular", "normalized_name": "angular", "claim_count": 10},
        ]

        arbiter = MergeArbiter()
        result = MergeResult()
        remaining = arbiter.deterministic_pass(entities, result)

        assert len(result.deterministic_merges) == 0
        assert len(remaining) == 2

    def test_dedup_prefix_helper(self):
        from knowbase.claimfirst.extractors.merge_arbiter import MergeArbiter

        assert MergeArbiter._dedup_prefix("SAP SAP S/4HANA") == "SAP S/4HANA"
        assert MergeArbiter._dedup_prefix("SAP S/4HANA") == "SAP S/4HANA"
        assert MergeArbiter._dedup_prefix("The The Product") == "The Product"
        assert MergeArbiter._dedup_prefix("Single") == "Single"

    def test_pregroup_candidates_token_overlap(self):
        from knowbase.claimfirst.extractors.merge_arbiter import MergeArbiter

        entities = [
            {"entity_id": "e1", "name": "SAP S/4HANA", "normalized_name": "sap s4hana", "claim_count": 50},
            {"entity_id": "e2", "name": "SAP S/4HANA Cloud", "normalized_name": "sap s4hana cloud", "claim_count": 20},
            {"entity_id": "e3", "name": "Angular", "normalized_name": "angular", "claim_count": 10},
        ]

        arbiter = MergeArbiter()
        groups = arbiter._pregroup_candidates(entities)

        # e1 et e2 devraient être groupés (high overlap)
        # e3 devrait être seul
        grouped_ids = set()
        for group in groups:
            for e in group:
                grouped_ids.add(e["entity_id"])

        assert "e1" in grouped_ids
        assert "e2" in grouped_ids


# ============================================================================
# Integration : MergeResult dataclass
# ============================================================================

class TestMergeResultDataclass:
    def test_default_stats(self):
        from knowbase.claimfirst.extractors.merge_arbiter import MergeResult

        result = MergeResult()
        assert result.stats["entities_input"] == 0
        assert result.stats["llm_merge"] == 0
        assert result.deterministic_merges == []
        assert result.llm_merges == []
        assert result.similar_pairs == []
