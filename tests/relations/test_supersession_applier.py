"""Tests unitaires du SupersessionApplier — règle §9.4 CAS 1-4.

Cible : valider la logique déterministe de classification + écriture Cypher mockée.
Pas de dépendance Neo4j réelle (driver mocké).
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from knowbase.relations.supersession_applier import (
    SupersessionApplier,
    SupersessionDecision,
    _ClaimTemporalSnapshot,
)


# ============================================================================
# Helpers
# ============================================================================


def _make_snap(
    claim_id: str,
    valid_from: str | None = None,
    valid_from_marker: str = "explicit",
    ingested_at: str = "2026-05-20T10:00:00Z",
    invalidated_at: str | None = None,
) -> _ClaimTemporalSnapshot:
    return _ClaimTemporalSnapshot(
        claim_id=claim_id,
        valid_from=valid_from,
        valid_from_marker=valid_from_marker,
        ingested_at=ingested_at,
        invalidated_at=invalidated_at,
    )


def _make_applier_with_snaps(snap_a, snap_b):
    """Construit un applier avec un driver mocké qui retourne snap_a et snap_b."""
    driver = MagicMock()
    applier = SupersessionApplier(driver, tenant_id="default")
    # Mock _load_temporal_snapshot directement (plus simple que mocker driver/session/run)
    applier._load_temporal_snapshot = MagicMock(
        side_effect=lambda cid: snap_a if cid == snap_a.claim_id else snap_b
    )
    # Mock écritures Cypher : on simule un retour single() qui ne lève pas d'erreur
    session_mock = MagicMock()
    session_mock.run.return_value.single.return_value = {"inv_at": "2026-05-21T09:00:00Z", "rel_type": "SUPERSEDES"}
    driver.session.return_value.__enter__.return_value = session_mock
    return applier, driver


# ============================================================================
# CAS 1 — Les deux dates explicites
# ============================================================================


class TestCas1:
    def test_b_newer_than_a_creates_supersedes(self):
        snap_a = _make_snap("a1", valid_from="2023-03-15T00:00:00Z")
        snap_b = _make_snap("b1", valid_from="2026-10-12T00:00:00Z")
        applier, _ = _make_applier_with_snaps(snap_a, snap_b)

        decision = applier.apply(
            claim_a_id="a1",
            claim_b_id="b1",
            relation_type="CONTRADICTS",
            confidence=0.92,
            marker_type="inferred",
        )

        assert decision.action == "supersedes"
        assert decision.invalidated_claim_id == "a1"
        assert decision.winner_claim_id == "b1"
        assert decision.evolution_case == "CAS_1"

    def test_a_newer_than_b_creates_supersedes_reverse(self):
        snap_a = _make_snap("a1", valid_from="2026-10-12T00:00:00Z")
        snap_b = _make_snap("b1", valid_from="2023-03-15T00:00:00Z")
        applier, _ = _make_applier_with_snaps(snap_a, snap_b)

        decision = applier.apply(
            claim_a_id="a1",
            claim_b_id="b1",
            relation_type="CONTRADICTS",
            confidence=0.92,
        )

        assert decision.action == "supersedes"
        assert decision.invalidated_claim_id == "b1"  # B est le loser
        assert decision.winner_claim_id == "a1"
        assert decision.evolution_case == "CAS_1"

    def test_equal_dates_creates_conflict_pending(self):
        snap_a = _make_snap("a1", valid_from="2025-01-01T00:00:00Z")
        snap_b = _make_snap("b1", valid_from="2025-01-01T00:00:00Z")
        applier, _ = _make_applier_with_snaps(snap_a, snap_b)

        decision = applier.apply(
            claim_a_id="a1",
            claim_b_id="b1",
            relation_type="CONTRADICTS",
            confidence=0.90,
        )

        assert decision.action == "conflict_pending"
        assert decision.evolution_case == "CAS_1_EQUAL"
        assert decision.invalidated_claim_id is None  # Pas d'invalidation


# ============================================================================
# CAS 2 — A inconnue, B explicite (cas test RISE Bootcamp §9.7)
# ============================================================================


class TestCas2:
    def test_b_after_a_ingested_creates_supersedes(self):
        """CAS 2 satisfait : B.valid_from > A.ingested_at → B forcément postérieur."""
        snap_a = _make_snap(
            "a1",
            valid_from=None,
            valid_from_marker="ingestion_fallback",
            ingested_at="2026-05-19T21:23:27Z",
        )
        snap_b = _make_snap(
            "b1",
            valid_from="2026-10-12T00:00:00Z",
            valid_from_marker="explicit",
        )
        applier, _ = _make_applier_with_snaps(snap_a, snap_b)

        decision = applier.apply(
            claim_a_id="a1",
            claim_b_id="b1",
            relation_type="CONTRADICTS",
            confidence=0.92,
        )

        assert decision.action == "supersedes"
        assert decision.invalidated_claim_id == "a1"
        assert decision.winner_claim_id == "b1"
        assert decision.evolution_case == "CAS_2"

    def test_b_before_a_ingested_creates_conflict_pending(self):
        """CAS 2 ambigu : B.valid_from ≤ A.ingested_at → on ne peut pas trancher."""
        snap_a = _make_snap(
            "a1",
            valid_from=None,
            valid_from_marker="ingestion_fallback",
            ingested_at="2026-05-19T21:23:27Z",
        )
        snap_b = _make_snap(
            "b1",
            valid_from="2024-01-01T00:00:00Z",  # avant A.ingested_at
            valid_from_marker="explicit",
        )
        applier, _ = _make_applier_with_snaps(snap_a, snap_b)

        decision = applier.apply(
            claim_a_id="a1",
            claim_b_id="b1",
            relation_type="CONTRADICTS",
            confidence=0.92,
        )

        assert decision.action == "conflict_pending"
        assert decision.evolution_case == "CAS_2"


# ============================================================================
# CAS 3 — A explicite, B inconnue
# ============================================================================


class TestCas3:
    def test_creates_conflict_pending(self):
        snap_a = _make_snap("a1", valid_from="2025-03-15T00:00:00Z", valid_from_marker="explicit")
        snap_b = _make_snap("b1", valid_from=None, valid_from_marker="ingestion_fallback")
        applier, _ = _make_applier_with_snaps(snap_a, snap_b)

        decision = applier.apply(
            claim_a_id="a1",
            claim_b_id="b1",
            relation_type="CONTRADICTS",
            confidence=0.90,
        )

        assert decision.action == "conflict_pending"
        assert decision.evolution_case == "CAS_3"


# ============================================================================
# CAS 4 — Les deux inconnues
# ============================================================================


class TestCas4:
    def test_creates_conflict_pending(self):
        snap_a = _make_snap("a1", valid_from=None, valid_from_marker="ingestion_fallback")
        snap_b = _make_snap("b1", valid_from=None, valid_from_marker="ingestion_fallback")
        applier, _ = _make_applier_with_snaps(snap_a, snap_b)

        decision = applier.apply(
            claim_a_id="a1",
            claim_b_id="b1",
            relation_type="CONTRADICTS",
            confidence=0.88,
        )

        assert decision.action == "conflict_pending"
        assert decision.evolution_case == "CAS_4"


# ============================================================================
# Marker_type = 'prudence' → toujours conflict_pending (même si CAS 1/2 satisfait)
# ============================================================================


class TestPrudenceOverride:
    def test_prudence_forces_conflict_pending_even_on_cas_1(self):
        """Confidence basse → marker_type='prudence' → pas d'invalidation, juste conflict_pending."""
        snap_a = _make_snap("a1", valid_from="2023-03-15T00:00:00Z")
        snap_b = _make_snap("b1", valid_from="2026-10-12T00:00:00Z")
        applier, _ = _make_applier_with_snaps(snap_a, snap_b)

        decision = applier.apply(
            claim_a_id="a1",
            claim_b_id="b1",
            relation_type="CONTRADICTS",
            confidence=0.70,  # bas
            marker_type="prudence",
        )

        assert decision.action == "conflict_pending"
        # Le CAS reste CAS_1 (la classification §9.4 reste, c'est juste l'action qui change)
        assert decision.evolution_case == "CAS_1"


# ============================================================================
# Edge cases
# ============================================================================


class TestEdgeCases:
    def test_unknown_relation_type_returns_no_op(self):
        snap_a = _make_snap("a1", valid_from="2023-01-01T00:00:00Z")
        snap_b = _make_snap("b1", valid_from="2025-01-01T00:00:00Z")
        applier, _ = _make_applier_with_snaps(snap_a, snap_b)

        decision = applier.apply(
            claim_a_id="a1",
            claim_b_id="b1",
            relation_type="REFINES",  # pas dans _HANDLED_RELATIONS
        )

        assert decision.action == "no_op"

    def test_already_invalidated_claim_returns_no_op(self):
        snap_a = _make_snap(
            "a1",
            valid_from="2023-01-01T00:00:00Z",
            invalidated_at="2025-05-15T00:00:00Z",  # déjà invalidé
        )
        snap_b = _make_snap("b1", valid_from="2026-01-01T00:00:00Z")
        applier, _ = _make_applier_with_snaps(snap_a, snap_b)

        decision = applier.apply(
            claim_a_id="a1",
            claim_b_id="b1",
            relation_type="CONTRADICTS",
        )

        assert decision.action == "no_op"
        assert "déjà invalidé" in decision.reason

    def test_evolution_of_relation_supersedes_in_cas_1(self):
        """Type EVOLUTION_OF avec CAS 1 satisfait → :SUPERSEDES (cf §2.4 Phase C 4.2)."""
        snap_a = _make_snap("a1", valid_from="2023-01-01T00:00:00Z")
        snap_b = _make_snap("b1", valid_from="2026-01-01T00:00:00Z")
        applier, _ = _make_applier_with_snaps(snap_a, snap_b)

        decision = applier.apply(
            claim_a_id="a1",
            claim_b_id="b1",
            relation_type="EVOLUTION_OF",
            confidence=0.92,
            marker_type="inferred",
        )

        assert decision.action == "supersedes"
        assert decision.invalidated_claim_id == "a1"

    def test_missing_claim_returns_no_op(self):
        """Si load_temporal_snapshot retourne None pour un claim."""
        driver = MagicMock()
        applier = SupersessionApplier(driver, tenant_id="default")
        applier._load_temporal_snapshot = MagicMock(return_value=None)

        decision = applier.apply(
            claim_a_id="missing",
            claim_b_id="b1",
            relation_type="CONTRADICTS",
        )

        assert decision.action == "no_op"
        assert "introuvable" in decision.reason


# ============================================================================
# Classification §9.4 isolée (sans IO Neo4j)
# ============================================================================


class TestClassifyCase:
    def test_cas_1(self):
        snap_a = _make_snap("a", valid_from="2023-01-01T00:00:00Z")
        snap_b = _make_snap("b", valid_from="2025-01-01T00:00:00Z")
        assert SupersessionApplier._classify_case(snap_a, snap_b) == "CAS_1"

    def test_cas_1_equal(self):
        snap_a = _make_snap("a", valid_from="2025-01-01T00:00:00Z")
        snap_b = _make_snap("b", valid_from="2025-01-01T00:00:00Z")
        assert SupersessionApplier._classify_case(snap_a, snap_b) == "CAS_1_EQUAL"

    def test_cas_2(self):
        snap_a = _make_snap("a", valid_from=None)
        snap_b = _make_snap("b", valid_from="2025-01-01T00:00:00Z")
        assert SupersessionApplier._classify_case(snap_a, snap_b) == "CAS_2"

    def test_cas_3(self):
        snap_a = _make_snap("a", valid_from="2023-01-01T00:00:00Z")
        snap_b = _make_snap("b", valid_from=None)
        assert SupersessionApplier._classify_case(snap_a, snap_b) == "CAS_3"

    def test_cas_4(self):
        snap_a = _make_snap("a", valid_from=None)
        snap_b = _make_snap("b", valid_from=None)
        assert SupersessionApplier._classify_case(snap_a, snap_b) == "CAS_4"
