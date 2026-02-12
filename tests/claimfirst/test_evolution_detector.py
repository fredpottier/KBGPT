# tests/claimfirst/test_evolution_detector.py
"""
Tests pour VersionEvolutionDetector — détection d'évolution temporelle.

Tests unitaires purs (pas de Neo4j, pas de LLM).
compare_claims() est une fonction Python pure.
"""

import pytest

from knowbase.claimfirst.composition.evolution_detector import (
    ClaimEvolution,
    EvolutionLink,
    VersionEvolutionDetector,
    VersionPair,
    validate_evolution_edge_props,
    _spo_fingerprint,
    _sp_key,
)


def _make_pair() -> VersionPair:
    """Crée un VersionPair de test."""
    return VersionPair(
        subject_id="cs_abc123",
        subject_name="SAP S/4HANA",
        old_doc_id="doc_v1",
        new_doc_id="doc_v2",
        old_value="2021",
        new_value="2022",
        axis_key="release_id",
        axis_confidence="primary_axis",
    )


def _make_claim(claim_id, subject, predicate, obj):
    return {
        "claim_id": claim_id,
        "structured_form": {
            "subject": subject,
            "predicate": predicate,
            "object": obj,
        },
    }


class TestSpoFingerprint:
    """Tests pour le fingerprint S|P|O."""

    def test_basic(self):
        sf = {"subject": "SAP S/4HANA", "predicate": "USES", "object": "Material Ledger"}
        fp = _spo_fingerprint(sf)
        assert fp == "sap s4hana|USES|material ledger"

    def test_case_insensitive(self):
        sf1 = {"subject": "SAP S/4HANA", "predicate": "USES", "object": "Material Ledger"}
        sf2 = {"subject": "sap s/4hana", "predicate": "uses", "object": "material ledger"}
        # Les sujets/objets sont normalisés, les prédicats sont uppercased
        assert _spo_fingerprint(sf1) == _spo_fingerprint(sf2)

    def test_whitespace_normalized(self):
        sf1 = {"subject": " SAP  S/4HANA ", "predicate": "USES", "object": "Material Ledger"}
        sf2 = {"subject": "SAP S/4HANA", "predicate": "USES", "object": "Material Ledger"}
        assert _spo_fingerprint(sf1) == _spo_fingerprint(sf2)


class TestSpKey:
    """Tests pour la clé S+P."""

    def test_basic(self):
        sf = {"subject": "SAP S/4HANA", "predicate": "USES", "object": "Material Ledger"}
        assert _sp_key(sf) == "sap s4hana|USES"

    def test_same_sp_different_object(self):
        sf1 = {"subject": "SAP S/4HANA", "predicate": "USES", "object": "Material Ledger"}
        sf2 = {"subject": "SAP S/4HANA", "predicate": "USES", "object": "ABAP Platform"}
        assert _sp_key(sf1) == _sp_key(sf2)


class TestCompareClaimsUnchanged:
    """UNCHANGED : même fingerprint S|P|O."""

    def test_unchanged_exact_spo(self):
        """Même claim dans les deux versions → UNCHANGED, score=1.0."""
        pair = _make_pair()
        old = [_make_claim("c1", "SAP S/4HANA", "USES", "Material Ledger")]
        new = [_make_claim("c2", "SAP S/4HANA", "USES", "Material Ledger")]

        detector = VersionEvolutionDetector()
        links = detector.compare_claims(old, new, pair)

        unchanged = [l for l in links if l.evolution_type == ClaimEvolution.UNCHANGED]
        assert len(unchanged) == 1
        assert unchanged[0].source_claim_id == "c1"
        assert unchanged[0].target_claim_id == "c2"
        assert unchanged[0].similarity_score == 1.0
        assert unchanged[0].diff_summary == ""

    def test_unchanged_case_insensitive(self):
        """Même claim avec casse différente → UNCHANGED."""
        pair = _make_pair()
        old = [_make_claim("c1", "SAP S/4HANA", "USES", "Material Ledger")]
        new = [_make_claim("c2", "sap s/4hana", "uses", "material ledger")]

        detector = VersionEvolutionDetector()
        links = detector.compare_claims(old, new, pair)

        unchanged = [l for l in links if l.evolution_type == ClaimEvolution.UNCHANGED]
        assert len(unchanged) == 1

    def test_unchanged_not_double_counted(self):
        """Une claim matched en UNCHANGED ne doit PAS aussi apparaître en ADDED/REMOVED."""
        pair = _make_pair()
        old = [_make_claim("c1", "SAP", "USES", "HANA")]
        new = [_make_claim("c2", "SAP", "USES", "HANA")]

        detector = VersionEvolutionDetector()
        links = detector.compare_claims(old, new, pair)

        assert len(links) == 1
        assert links[0].evolution_type == ClaimEvolution.UNCHANGED


class TestCompareClaimsModified:
    """MODIFIED : même S+P, objet différent."""

    def test_modified_different_object(self):
        """Même S+P, objet changé → MODIFIED avec diff_summary et raw objects."""
        pair = _make_pair()
        old = [_make_claim("c1", "SAP S/4HANA", "REQUIRES", "TLS 1.2")]
        new = [_make_claim("c2", "SAP S/4HANA", "REQUIRES", "TLS 1.3")]

        detector = VersionEvolutionDetector()
        links = detector.compare_claims(old, new, pair)

        modified = [l for l in links if l.evolution_type == ClaimEvolution.MODIFIED]
        assert len(modified) == 1
        m = modified[0]
        assert m.source_claim_id == "c1"
        assert m.target_claim_id == "c2"
        assert m.diff_summary == "object: TLS 1.2 -> TLS 1.3"
        assert m.old_object_raw == "TLS 1.2"
        assert m.new_object_raw == "TLS 1.3"
        assert m.similarity_score == 0.7

    def test_modified_not_double_counted(self):
        """Une claim matched en MODIFIED ne doit PAS aussi apparaître en ADDED/REMOVED."""
        pair = _make_pair()
        old = [_make_claim("c1", "SAP", "REQUIRES", "Version 1")]
        new = [_make_claim("c2", "SAP", "REQUIRES", "Version 2")]

        detector = VersionEvolutionDetector()
        links = detector.compare_claims(old, new, pair)

        # 1 MODIFIED, 0 ADDED, 0 REMOVED
        types = [l.evolution_type for l in links]
        assert types.count(ClaimEvolution.MODIFIED) == 1
        assert types.count(ClaimEvolution.ADDED) == 0
        assert types.count(ClaimEvolution.REMOVED) == 0


class TestCompareClaimsAdded:
    """ADDED : claim uniquement dans new."""

    def test_added_new_claim(self):
        """Claim dans new sans match dans old → ADDED."""
        pair = _make_pair()
        old = []
        new = [_make_claim("c2", "SAP S/4HANA", "PROVIDES", "New Feature")]

        detector = VersionEvolutionDetector()
        links = detector.compare_claims(old, new, pair)

        assert len(links) == 1
        assert links[0].evolution_type == ClaimEvolution.ADDED
        assert links[0].source_claim_id == ""
        assert links[0].target_claim_id == "c2"
        assert links[0].new_object_raw == "New Feature"


class TestCompareClaimsRemoved:
    """REMOVED : claim uniquement dans old."""

    def test_removed_old_claim(self):
        """Claim dans old sans match dans new → REMOVED."""
        pair = _make_pair()
        old = [_make_claim("c1", "SAP S/4HANA", "SUPPORTS", "Legacy Feature")]
        new = []

        detector = VersionEvolutionDetector()
        links = detector.compare_claims(old, new, pair)

        assert len(links) == 1
        assert links[0].evolution_type == ClaimEvolution.REMOVED
        assert links[0].source_claim_id == "c1"
        assert links[0].target_claim_id == ""
        assert links[0].old_object_raw == "Legacy Feature"


class TestGuardRails:
    """Garde-fous contre les faux positifs."""

    def test_guard_rail_multi_sp_skip(self):
        """S+P apparaît 2x dans old → skip MODIFIED (ambiguïté)."""
        pair = _make_pair()
        old = [
            _make_claim("c1", "SAP", "USES", "Feature A"),
            _make_claim("c2", "SAP", "USES", "Feature B"),
        ]
        new = [_make_claim("c3", "SAP", "USES", "Feature C")]

        detector = VersionEvolutionDetector()
        links = detector.compare_claims(old, new, pair)

        # Pas de MODIFIED (ambiguïté), les claims restent ADDED/REMOVED
        modified = [l for l in links if l.evolution_type == ClaimEvolution.MODIFIED]
        assert len(modified) == 0

        stats = detector.get_stats()
        assert stats.get("modified_skipped_ambiguous", 0) >= 1

    def test_guard_rail_multi_sp_new_side(self):
        """S+P apparaît 2x dans new → skip MODIFIED aussi."""
        pair = _make_pair()
        old = [_make_claim("c1", "SAP", "USES", "Feature A")]
        new = [
            _make_claim("c2", "SAP", "USES", "Feature B"),
            _make_claim("c3", "SAP", "USES", "Feature C"),
        ]

        detector = VersionEvolutionDetector()
        links = detector.compare_claims(old, new, pair)

        modified = [l for l in links if l.evolution_type == ClaimEvolution.MODIFIED]
        assert len(modified) == 0

    def test_no_modified_if_same_object_normalized(self):
        """Même S+P et même objet (après normalisation) → pas de MODIFIED."""
        pair = _make_pair()
        old = [_make_claim("c1", "SAP", "USES", "Material Ledger")]
        new = [_make_claim("c2", "SAP", "USES", "material ledger")]

        detector = VersionEvolutionDetector()
        links = detector.compare_claims(old, new, pair)

        # C'est un UNCHANGED via fingerprint, pas un MODIFIED
        unchanged = [l for l in links if l.evolution_type == ClaimEvolution.UNCHANGED]
        modified = [l for l in links if l.evolution_type == ClaimEvolution.MODIFIED]
        assert len(unchanged) == 1
        assert len(modified) == 0


class TestEmptyInputs:
    """Cas limites."""

    def test_empty_claims(self):
        """Listes vides → pas de liens."""
        pair = _make_pair()
        detector = VersionEvolutionDetector()
        links = detector.compare_claims([], [], pair)
        assert links == []

    def test_no_structured_form(self):
        """Claims sans structured_form → ignorées."""
        pair = _make_pair()
        old = [{"claim_id": "c1"}]  # pas de structured_form
        new = [{"claim_id": "c2"}]

        detector = VersionEvolutionDetector()
        links = detector.compare_claims(old, new, pair)
        assert links == []


class TestMixedEvolution:
    """Scénario réaliste avec tous les types."""

    def test_full_scenario(self):
        """Mix de UNCHANGED + MODIFIED + ADDED + REMOVED."""
        pair = _make_pair()
        old = [
            _make_claim("c1", "SAP", "USES", "HANA"),           # → UNCHANGED
            _make_claim("c2", "SAP", "REQUIRES", "TLS 1.2"),    # → MODIFIED
            _make_claim("c3", "SAP", "SUPPORTS", "ECC"),        # → REMOVED
        ]
        new = [
            _make_claim("c4", "SAP", "USES", "HANA"),           # ← UNCHANGED
            _make_claim("c5", "SAP", "REQUIRES", "TLS 1.3"),    # ← MODIFIED
            _make_claim("c6", "SAP", "PROVIDES", "Analytics"),  # ← ADDED
        ]

        detector = VersionEvolutionDetector()
        links = detector.compare_claims(old, new, pair)

        by_type = {}
        for l in links:
            by_type.setdefault(l.evolution_type, []).append(l)

        assert len(by_type.get(ClaimEvolution.UNCHANGED, [])) == 1
        assert len(by_type.get(ClaimEvolution.MODIFIED, [])) == 1
        assert len(by_type.get(ClaimEvolution.REMOVED, [])) == 1
        assert len(by_type.get(ClaimEvolution.ADDED, [])) == 1

        # Vérifier le MODIFIED
        mod = by_type[ClaimEvolution.MODIFIED][0]
        assert mod.old_object_raw == "TLS 1.2"
        assert mod.new_object_raw == "TLS 1.3"

        # Total = 4 (pas de double comptage)
        assert len(links) == 4

        # Stats
        stats = detector.get_stats()
        assert stats["unchanged"] == 1
        assert stats["modified"] == 1
        assert stats["added"] == 1
        assert stats["removed"] == 1


class TestValidateEdgeProps:
    """Tests pour validate_evolution_edge_props."""

    def test_valid_props(self):
        """Propriétés complètes → pas d'erreur."""
        props = {
            "method": "version_evolution",
            "chain_type": "evolution_modified",
            "cross_doc": True,
            "comparable_subject_id": "cs_abc",
            "axis_key": "release_id",
            "old_axis_value": "2021",
            "new_axis_value": "2022",
            "evolution_type": "modified",
            "similarity_score": 0.7,
        }
        validate_evolution_edge_props(props)  # pas d'exception

    def test_missing_props_raises(self):
        """Propriétés manquantes → ValueError."""
        props = {
            "method": "version_evolution",
            "chain_type": "evolution_modified",
            # manque: cross_doc, comparable_subject_id, axis_key, etc.
        }
        with pytest.raises(ValueError, match="Propriétés obligatoires manquantes"):
            validate_evolution_edge_props(props)


class TestVersionPair:
    """Tests pour VersionPair."""

    def test_axis_confidence_default(self):
        pair = _make_pair()
        assert pair.axis_confidence == "primary_axis"

    def test_heuristic_confidence(self):
        pair = VersionPair(
            subject_id="cs_x",
            subject_name="Test",
            old_doc_id="d1",
            new_doc_id="d2",
            old_value="2021",
            new_value="2022",
            axis_key="year_heuristic",
            axis_confidence="heuristic",
        )
        assert pair.axis_confidence == "heuristic"
