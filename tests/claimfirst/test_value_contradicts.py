# tests/claimfirst/test_value_contradicts.py
"""
Tests value-level CONTRADICTS detection.

Sans deps lourdes : uniquement value_contradicts + models Entity/Claim.
~33 tests couvrant ClaimKey, ValueFrame, FormalComparator, integration, stats.
"""

from __future__ import annotations

import pytest
from dataclasses import dataclass
from typing import Dict, List, Optional, Any

from knowbase.claimfirst.clustering.value_contradicts import (
    ValueType,
    ValueFrame,
    ContradictionVerdict,
    ContradictionResult,
    build_claim_key,
    have_comparable_claim_keys,
    parse_value_frame,
    compare_values,
    detect_value_contradictions,
)
from knowbase.claimfirst.models.entity import Entity


# =============================================================================
# Helpers — lightweight claim stub (pas d'import Claim pour éviter pydantic lent)
# =============================================================================


@dataclass
class FakeClaim:
    """Stub léger pour les tests (évite la validation Pydantic)."""

    claim_id: str
    doc_id: str = "doc1"
    structured_form: Optional[Dict[str, Any]] = None


def make_entity(entity_id: str, name: str, aliases: Optional[List[str]] = None) -> Entity:
    """Helper pour créer une Entity minimale."""
    return Entity(
        entity_id=entity_id,
        tenant_id="test",
        name=name,
        aliases=aliases or [],
    )


# =============================================================================
# Tests ClaimKey — Modif A + GF-1 + GF-2
# =============================================================================


class TestClaimKeyBuilding:

    def test_claim_key_with_entity_exact_match(self):
        """SF subject = "S/4HANA", entity normalized_name match → score 2 → entity_id."""
        entity = make_entity("ent-001", "S/4HANA")
        sf = {"subject": "S/4HANA", "predicate": "supports"}
        key = build_claim_key(
            sf,
            claim_id="c1",
            entities_by_claim={"c1": ["ent-001"]},
            entity_index={"ent-001": entity},
        )
        assert key == "ent-001|SUPPORTS"

    def test_claim_key_with_alias_match(self):
        """SF subject matche un alias → score 1 → entity_id."""
        entity = make_entity("ent-002", "Transport Layer Security", aliases=["TLS"])
        sf = {"subject": "TLS", "predicate": "version"}
        key = build_claim_key(
            sf,
            claim_id="c1",
            entities_by_claim={"c1": ["ent-002"]},
            entity_index={"ent-002": entity},
        )
        assert key == "ent-002|VERSION"

    def test_claim_key_best_score_wins(self):
        """2 entités, une exact(2) une alias(1) → exact gagne."""
        ent_alias = make_entity("ent-alias", "Something Else", aliases=["SAP BTP"])
        ent_exact = make_entity("ent-exact", "SAP BTP")
        sf = {"subject": "SAP BTP", "predicate": "requires"}
        key = build_claim_key(
            sf,
            claim_id="c1",
            entities_by_claim={"c1": ["ent-alias", "ent-exact"]},
            entity_index={"ent-alias": ent_alias, "ent-exact": ent_exact},
        )
        assert key == "ent-exact|REQUIRES"

    def test_claim_key_fallback_normalize(self):
        """Pas d'entity match → fallback Entity.normalize()."""
        entity = make_entity("ent-other", "Completely Different")
        sf = {"subject": "SAP BTP", "predicate": "supports"}
        key = build_claim_key(
            sf,
            claim_id="c1",
            entities_by_claim={"c1": ["ent-other"]},
            entity_index={"ent-other": entity},
        )
        expected = f"{Entity.normalize('SAP BTP')}|SUPPORTS"
        assert key == expected

    def test_claim_key_none_if_incomplete(self):
        """SF sans predicate → None."""
        assert build_claim_key({"subject": "SAP"}) is None
        assert build_claim_key({"predicate": "supports"}) is None
        assert build_claim_key({}) is None
        assert build_claim_key(None) is None

    def test_claim_key_without_entities(self):
        """entities_by_claim=None → fallback textuel."""
        sf = {"subject": "SAP BTP", "predicate": "supports"}
        key = build_claim_key(sf)
        assert key == f"{Entity.normalize('SAP BTP')}|SUPPORTS"


class TestComparableClaimKeys:

    def test_comparable_keys_exact_match(self):
        """Même ClaimKey → True."""
        c1 = FakeClaim("c1", structured_form={"subject": "TLS", "predicate": "version", "object": "1.2"})
        c2 = FakeClaim("c2", structured_form={"subject": "TLS", "predicate": "version", "object": "1.3"})
        assert have_comparable_claim_keys(c1, c2) is True

    def test_comparable_keys_entity_overlap_fallback(self):
        """ClaimKey diff mais entity overlap + même pred → True (GF-2)."""
        # "TLS" vs "Transport Layer Security" → different text keys
        c1 = FakeClaim("c1", structured_form={"subject": "TLS", "predicate": "version", "object": "1.2"})
        c2 = FakeClaim("c2", structured_form={"subject": "Transport Layer Security", "predicate": "version", "object": "1.3"})
        # Mais les deux claims sont liées à la même entity
        entities_by_claim = {"c1": ["ent-tls"], "c2": ["ent-tls", "ent-other"]}
        assert have_comparable_claim_keys(c1, c2, entities_by_claim=entities_by_claim) is True

    def test_comparable_keys_no_match(self):
        """Sujets et entités différents → False."""
        c1 = FakeClaim("c1", structured_form={"subject": "TLS", "predicate": "version", "object": "1.2"})
        c2 = FakeClaim("c2", structured_form={"subject": "HTTP", "predicate": "version", "object": "2.0"})
        entities_by_claim = {"c1": ["ent-tls"], "c2": ["ent-http"]}
        assert have_comparable_claim_keys(c1, c2, entities_by_claim=entities_by_claim) is False


# =============================================================================
# Tests ValueFrame Parser — Modif B
# =============================================================================


class TestParseValueFrame:

    def test_parse_version_strict(self):
        """'1.2.3' → VERSION((1,2,3))."""
        vf = parse_value_frame("1.2.3")
        assert vf.value_type == ValueType.VERSION
        assert vf.parsed_value == (1, 2, 3)

    def test_parse_version_two_parts(self):
        """'1.2' → VERSION((1,2))."""
        vf = parse_value_frame("1.2")
        assert vf.value_type == ValueType.VERSION
        assert vf.parsed_value == (1, 2)

    def test_parse_version_with_v(self):
        """'v3.0' → VERSION((3,0))."""
        vf = parse_value_frame("v3.0")
        assert vf.value_type == ValueType.VERSION
        assert vf.parsed_value == (3, 0)

    def test_parse_number_with_unit(self):
        """'4 GB' → NUMBER(4.0, 'GB')."""
        vf = parse_value_frame("4 GB")
        assert vf.value_type == ValueType.NUMBER
        assert vf.parsed_value == 4.0
        assert vf.unit == "GB"

    def test_parse_number_no_unit(self):
        """'99.5' → NUMBER(99.5, None) — pas de version (un seul '.')."""
        # "99.5" matche VERSION d'abord? Non : VERSION_STRICT = \d+(\.\d+)+ (2+ parts)
        # "99.5" a 2 parts (99, 5), donc matche VERSION.
        # Correction: on attend VERSION pour "99.5" car ça matche le pattern version.
        # Pour tester NUMBER pur, utiliser un entier seul.
        vf = parse_value_frame("100")
        assert vf.value_type == ValueType.NUMBER
        assert vf.parsed_value == 100.0
        assert vf.unit is None

    def test_parse_number_decimal_no_unit(self):
        """Un nombre décimal seul — matche VERSION car 2 parties."""
        # "99.5" has pattern \d+\.\d+ → VERSION captures it
        # This is by design: "99.5" could be a version number
        vf = parse_value_frame("99.5")
        assert vf.value_type == ValueType.VERSION
        assert vf.parsed_value == (99, 5)

    def test_parse_percent(self):
        """'99.9 %' → NUMBER(99.9, '%') — unit captures '%'."""
        # "99.9 %" — VERSION_STRICT won't match (has space and %)
        # NUMBER_WITH_UNIT: "99.9" then "%" → match
        vf = parse_value_frame("99.9 %")
        assert vf.value_type == ValueType.NUMBER
        assert vf.parsed_value == pytest.approx(99.9)
        assert vf.unit == "%"

    def test_parse_text_untyped(self):
        """'supported' → UNTYPED (PAS de BOOLEAN — Modif B)."""
        vf = parse_value_frame("supported")
        assert vf.value_type == ValueType.UNTYPED
        assert vf.parsed_value is None

    def test_parse_empty(self):
        """'' → UNTYPED."""
        vf = parse_value_frame("")
        assert vf.value_type == ValueType.UNTYPED

    def test_parse_number_with_comma(self):
        """'1000' → NUMBER. '1,5 GB' → NUMBER (virgule = décimale)."""
        vf = parse_value_frame("1000")
        assert vf.value_type == ValueType.NUMBER
        assert vf.parsed_value == 1000.0

        vf2 = parse_value_frame("1,5 GB")
        assert vf2.value_type == ValueType.NUMBER
        assert vf2.parsed_value == 1.5
        assert vf2.unit == "GB"


# =============================================================================
# Tests FormalComparator — GF-3
# =============================================================================


class TestFormalComparator:

    def test_number_diff_needs_llm(self):
        """4 GB vs 8 GB → NEED_LLM (GF-3 : PAS CONTRADICTS)."""
        vf1 = ValueFrame(ValueType.NUMBER, "4 GB", 4.0, "GB")
        vf2 = ValueFrame(ValueType.NUMBER, "8 GB", 8.0, "GB")
        result = compare_values(vf1, vf2)
        assert result.verdict == ContradictionVerdict.NEED_LLM

    def test_number_compatible(self):
        """4 GB vs 4 GB → COMPATIBLE(0.95)."""
        vf1 = ValueFrame(ValueType.NUMBER, "4 GB", 4.0, "GB")
        vf2 = ValueFrame(ValueType.NUMBER, "4 GB", 4.0, "GB")
        result = compare_values(vf1, vf2)
        assert result.verdict == ContradictionVerdict.COMPATIBLE
        assert result.confidence == 0.95

    def test_number_unit_mismatch(self):
        """4 GB vs 4 MB → INCOMPARABLE."""
        vf1 = ValueFrame(ValueType.NUMBER, "4 GB", 4.0, "GB")
        vf2 = ValueFrame(ValueType.NUMBER, "4 MB", 4.0, "MB")
        result = compare_values(vf1, vf2)
        assert result.verdict == ContradictionVerdict.INCOMPARABLE

    def test_version_compatible(self):
        """(1,2) vs (1,2) → COMPATIBLE."""
        vf1 = ValueFrame(ValueType.VERSION, "1.2", (1, 2), None)
        vf2 = ValueFrame(ValueType.VERSION, "1.2", (1, 2), None)
        result = compare_values(vf1, vf2)
        assert result.verdict == ContradictionVerdict.COMPATIBLE

    def test_version_diff_needs_llm(self):
        """(1,2) vs (2,0) → NEED_LLM."""
        vf1 = ValueFrame(ValueType.VERSION, "1.2", (1, 2), None)
        vf2 = ValueFrame(ValueType.VERSION, "2.0", (2, 0), None)
        result = compare_values(vf1, vf2)
        assert result.verdict == ContradictionVerdict.NEED_LLM

    def test_untyped_needs_llm(self):
        """'supported' vs 'disabled' → NEED_LLM."""
        vf1 = ValueFrame(ValueType.UNTYPED, "supported", None, None)
        vf2 = ValueFrame(ValueType.UNTYPED, "disabled", None, None)
        result = compare_values(vf1, vf2)
        assert result.verdict == ContradictionVerdict.NEED_LLM

    def test_type_mismatch(self):
        """NUMBER vs VERSION → INCOMPARABLE."""
        vf1 = ValueFrame(ValueType.NUMBER, "4", 4.0, None)
        vf2 = ValueFrame(ValueType.VERSION, "1.2", (1, 2), None)
        result = compare_values(vf1, vf2)
        assert result.verdict == ContradictionVerdict.INCOMPARABLE

    def test_number_same_no_unit(self):
        """100 vs 100 → COMPATIBLE."""
        vf1 = ValueFrame(ValueType.NUMBER, "100", 100.0, None)
        vf2 = ValueFrame(ValueType.NUMBER, "100", 100.0, None)
        result = compare_values(vf1, vf2)
        assert result.verdict == ContradictionVerdict.COMPATIBLE


# =============================================================================
# Tests Integration — detect_value_contradictions()
# =============================================================================


class TestIntegration:

    def test_end_to_end_number_same_filtered(self):
        """Même valeur → 0 dans need_llm (COMPATIBLE)."""
        c1 = FakeClaim("c1", structured_form={"subject": "RAM", "predicate": "requires", "object": "4 GB"})
        c2 = FakeClaim("c2", structured_form={"subject": "RAM", "predicate": "requires", "object": "4 GB"})
        formal, need_llm, stats = detect_value_contradictions([(c1, c2)])
        assert len(need_llm) == 0
        assert stats["formal_compatible"] == 1

    def test_end_to_end_number_diff_to_llm(self):
        """Valeurs diff → dans need_llm_pairs."""
        c1 = FakeClaim("c1", structured_form={"subject": "RAM", "predicate": "requires", "object": "4 GB"})
        c2 = FakeClaim("c2", structured_form={"subject": "RAM", "predicate": "requires", "object": "8 GB"})
        formal, need_llm, stats = detect_value_contradictions([(c1, c2)])
        assert len(need_llm) == 1
        assert stats["need_llm"] == 1

    def test_end_to_end_skips_no_sf(self):
        """Claims sans SF → 0 résultats."""
        c1 = FakeClaim("c1", structured_form=None)
        c2 = FakeClaim("c2", structured_form={"subject": "X", "predicate": "Y", "object": "Z"})
        formal, need_llm, stats = detect_value_contradictions([(c1, c2)])
        assert len(formal) == 0
        assert len(need_llm) == 0
        assert stats["no_sf"] == 1

    def test_end_to_end_skips_key_mismatch(self):
        """Sujets différents → 0 résultats."""
        c1 = FakeClaim("c1", structured_form={"subject": "TLS", "predicate": "version", "object": "1.2"})
        c2 = FakeClaim("c2", structured_form={"subject": "HTTP", "predicate": "version", "object": "2.0"})
        formal, need_llm, stats = detect_value_contradictions([(c1, c2)])
        assert len(formal) == 0
        assert len(need_llm) == 0
        assert stats["key_mismatch"] == 1

    def test_end_to_end_entity_overlap_fallback(self):
        """ClaimKey diff mais entity overlap → passe (GF-2)."""
        c1 = FakeClaim("c1", structured_form={"subject": "TLS", "predicate": "version", "object": "1.2"})
        c2 = FakeClaim("c2", structured_form={"subject": "Transport Layer Security", "predicate": "version", "object": "1.3"})
        entities_by_claim = {"c1": ["ent-tls"], "c2": ["ent-tls"]}
        formal, need_llm, stats = detect_value_contradictions(
            [(c1, c2)],
            entities_by_claim=entities_by_claim,
        )
        # "1.2" and "1.3" are both VERSION → diff → NEED_LLM
        assert len(need_llm) == 1
        assert stats["need_llm"] == 1

    def test_context_gate_filters(self):
        """Gate retourne False → paire filtrée."""
        c1 = FakeClaim("c1", structured_form={"subject": "TLS", "predicate": "version", "object": "1.2"})
        c2 = FakeClaim("c2", structured_form={"subject": "TLS", "predicate": "version", "object": "1.3"})
        gate = lambda c1, c2: False
        formal, need_llm, stats = detect_value_contradictions(
            [(c1, c2)],
            context_gate=gate,
        )
        assert len(formal) == 0
        assert len(need_llm) == 0
        assert stats["gate_filtered"] == 1


# =============================================================================
# Tests Stats
# =============================================================================


class TestStats:

    def test_stats_counters(self):
        """Vérifier que tous les compteurs sont présents."""
        formal, need_llm, stats = detect_value_contradictions([])
        assert stats["pairs_in"] == 0
        assert stats["no_sf"] == 0
        assert stats["key_mismatch"] == 0
        assert stats["gate_filtered"] == 0
        assert stats["formal_compatible"] == 0
        assert stats["incomparable"] == 0
        assert stats["need_llm"] == 0

    def test_stats_with_mixed_batch(self):
        """Mélange de cas → stats cohérentes."""
        c_no_sf = FakeClaim("c0", structured_form=None)
        c_tls_12 = FakeClaim("c1", structured_form={"subject": "TLS", "predicate": "version", "object": "1.2"})
        c_tls_12b = FakeClaim("c1b", structured_form={"subject": "TLS", "predicate": "version", "object": "1.2"})
        c_tls_13 = FakeClaim("c2", structured_form={"subject": "TLS", "predicate": "version", "object": "1.3"})
        c_http = FakeClaim("c3", structured_form={"subject": "HTTP", "predicate": "supports", "object": "yes"})

        pairs = [
            (c_no_sf, c_tls_12),       # no_sf
            (c_tls_12, c_tls_12b),      # COMPATIBLE
            (c_tls_12, c_tls_13),       # NEED_LLM (version diff)
            (c_tls_12, c_http),         # key_mismatch (different subject)
        ]

        formal, need_llm, stats = detect_value_contradictions(pairs)
        assert stats["pairs_in"] == 4
        assert stats["no_sf"] == 1
        assert stats["key_mismatch"] == 1
        assert stats["formal_compatible"] == 1
        assert stats["need_llm"] == 1
        assert len(need_llm) == 1
        assert len(formal) == 1  # 1 COMPATIBLE
