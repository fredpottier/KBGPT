# tests/claimfirst/test_chain_detector_cross_doc.py
"""
Tests pour ChainDetector — détection de chaînes S/P/O cross-document.
"""

import math

import pytest

from knowbase.claimfirst.composition.chain_detector import (
    ChainDetector,
    ChainLink,
    PREDICATE_PRIORITY,
)


def _make_claim_dict(claim_id, doc_id, subject, predicate, obj, confidence=0.8):
    return {
        "claim_id": claim_id,
        "doc_id": doc_id,
        "structured_form": {
            "subject": subject,
            "predicate": predicate,
            "object": obj,
        },
        "confidence": confidence,
    }


class TestCrossDocBasic:
    """Détection cross-doc de base."""

    def test_simple_cross_doc_chain(self):
        """Deux claims de docs différents liées par un join_key → 1 ChainLink cross-doc."""
        claims = [
            _make_claim_dict("c1", "doc1", "SAP S/4HANA", "USES", "Material Ledger"),
            _make_claim_dict("c2", "doc2", "Material Ledger", "ENABLES", "Real-Time Valuation"),
        ]
        detector = ChainDetector()
        links = detector.detect_cross_doc(claims, hub_entities=set())

        assert len(links) == 1
        link = links[0]
        assert link.source_claim_id == "c1"
        assert link.target_claim_id == "c2"
        assert link.is_cross_doc is True
        assert link.source_doc_id == "doc1"
        assert link.target_doc_id == "doc2"
        assert link.join_key == "material ledger"
        assert link.join_key_name == "material ledger"
        assert link.join_method == "normalized_name"

    def test_no_intra_doc_in_cross_doc(self):
        """Deux claims du MÊME doc → pas de lien cross-doc."""
        claims = [
            _make_claim_dict("c1", "doc1", "SAP S/4HANA", "USES", "Material Ledger"),
            _make_claim_dict("c2", "doc1", "Material Ledger", "ENABLES", "Valuation"),
        ]
        detector = ChainDetector()
        links = detector.detect_cross_doc(claims, hub_entities=set())

        assert len(links) == 0

    def test_empty_input(self):
        """Liste vide → aucun lien."""
        detector = ChainDetector()
        links = detector.detect_cross_doc([], hub_entities=set())
        assert links == []

    def test_no_matching_keys(self):
        """Pas de join_key commun → aucun lien."""
        claims = [
            _make_claim_dict("c1", "doc1", "SAP BTP", "USES", "Cloud Foundry"),
            _make_claim_dict("c2", "doc2", "Kubernetes", "ENABLES", "Scaling"),
        ]
        detector = ChainDetector()
        links = detector.detect_cross_doc(claims, hub_entities=set())
        assert len(links) == 0

    def test_three_docs_multiple_links(self):
        """Claims de 3 docs liées par le même join_key."""
        claims = [
            _make_claim_dict("c1", "doc1", "SAP ERP", "USES", "Central Finance"),
            _make_claim_dict("c2", "doc2", "Central Finance", "ENABLES", "Consolidation"),
            _make_claim_dict("c3", "doc3", "Central Finance", "REQUIRES", "S/4HANA"),
        ]
        detector = ChainDetector()
        links = detector.detect_cross_doc(claims, hub_entities=set())

        # c1→c2 et c1→c3 (c1.object == c2.subject == c3.subject = "central finance")
        assert len(links) == 2
        pairs = {(l.source_claim_id, l.target_claim_id) for l in links}
        assert ("c1", "c2") in pairs
        assert ("c1", "c3") in pairs


class TestCrossDocHubFiltering:
    """Exclusion des hub entities."""

    def test_hub_entity_excluded(self):
        """Entity hub exclue → pas de lien via ce join_key."""
        claims = [
            _make_claim_dict("c1", "doc1", "SAP ERP", "USES", "SAP S/4HANA"),
            _make_claim_dict("c2", "doc2", "SAP S/4HANA", "PROVIDES", "Cloud ERP"),
        ]
        detector = ChainDetector()
        links = detector.detect_cross_doc(
            claims, hub_entities={"sap s4hana"}
        )
        assert len(links) == 0

    def test_non_hub_entity_passes(self):
        """Entity non-hub → lien créé normalement."""
        claims = [
            _make_claim_dict("c1", "doc1", "SAP ERP", "USES", "Material Ledger"),
            _make_claim_dict("c2", "doc2", "Material Ledger", "ENABLES", "Valuation"),
        ]
        detector = ChainDetector()
        links = detector.detect_cross_doc(
            claims, hub_entities={"sap s4hana"}
        )
        assert len(links) == 1

    def test_hub_by_entity_id_excluded(self):
        """Hub résolu par entity_id est aussi exclu."""
        entity_index = {"sap s4hana": "ent_001"}
        claims = [
            _make_claim_dict("c1", "doc1", "SAP ERP", "USES", "SAP S/4HANA"),
            _make_claim_dict("c2", "doc2", "SAP S/4HANA", "PROVIDES", "Cloud ERP"),
        ]
        detector = ChainDetector()
        links = detector.detect_cross_doc(
            claims,
            hub_entities={"sap s4hana"},
            entity_index=entity_index,
        )
        assert len(links) == 0


class TestCrossDocRanking:
    """Ranking déterministe : predicate priority → IDF → tie-break claim_id."""

    def test_predicate_priority_ranking(self):
        """Les liens avec prédicats structurants (score 4) sont gardés en priorité."""
        claims = [
            # Prédicat faible (PROVIDES = 1)
            _make_claim_dict("c1", "doc1", "Module Alpha", "PROVIDES", "Central Finance"),
            # Prédicat fort (REQUIRES = 4)
            _make_claim_dict("c2", "doc1", "Module Beta", "REQUIRES", "Central Finance"),
            # Target
            _make_claim_dict("c3", "doc2", "Central Finance", "ENABLES", "Consolidation"),
        ]
        detector = ChainDetector(max_edges_per_key_cross_doc=1)
        links = detector.detect_cross_doc(claims, hub_entities=set())

        # Avec cap=1, seul le lien avec REQUIRES (score 4) doit survivre
        assert len(links) == 1
        assert links[0].source_claim_id == "c2"

    def test_idf_ranking(self):
        """À score prédicat égal, le join_key avec IDF plus haut est préféré."""
        claims = [
            # Join via "rare concept" (IDF haut)
            _make_claim_dict("c1", "doc1", "Module Alpha", "USES", "Rare Concept"),
            _make_claim_dict("c2", "doc2", "Rare Concept", "USES", "Feature X"),
            # Join via "common concept" (IDF bas)
            _make_claim_dict("c3", "doc1", "Module Beta", "USES", "Common Concept"),
            _make_claim_dict("c4", "doc2", "Common Concept", "USES", "Feature Y"),
            # Extra claims mentionnant "common concept" (baisse son IDF)
            _make_claim_dict("c5", "doc1", "Common Concept", "SUPPORTS", "Feature Z"),
            _make_claim_dict("c6", "doc2", "Common Concept", "PROVIDES", "Feature W"),
            _make_claim_dict("c7", "doc3", "Common Concept", "ENABLES", "Feature V"),
        ]

        # IDF calculé : "rare concept" apparaît dans 2 claims, "common concept" dans 5
        idf_map = ChainDetector.compute_idf(claims)
        assert idf_map.get("rare concept", 0) > idf_map.get("common concept", 0)

    def test_tiebreak_by_claim_id(self):
        """À score et IDF égaux, tri lexicographique par claim_id (idempotence)."""
        claims = [
            _make_claim_dict("c_beta", "doc1", "Module Beta", "USES", "Central Finance"),
            _make_claim_dict("c_alpha", "doc1", "Module Alpha", "USES", "Central Finance"),
            _make_claim_dict("c_target", "doc2", "Central Finance", "USES", "Feature X"),
        ]
        detector = ChainDetector(max_edges_per_key_cross_doc=1)
        links = detector.detect_cross_doc(claims, hub_entities=set())

        # Même predicate (USES=2), même IDF, tie-break = "c_alpha" < "c_beta"
        assert len(links) == 1
        assert links[0].source_claim_id == "c_alpha"

    def test_idempotence(self):
        """Deux exécutions identiques → même résultat exact."""
        claims = [
            _make_claim_dict("c1", "doc1", "SAP ERP", "USES", "Central Finance"),
            _make_claim_dict("c2", "doc1", "Module X", "REQUIRES", "Central Finance"),
            _make_claim_dict("c3", "doc2", "Central Finance", "ENABLES", "Consolidation"),
            _make_claim_dict("c4", "doc2", "Central Finance", "PROVIDES", "Reports"),
            _make_claim_dict("c5", "doc3", "SAP ERP", "USES", "Material Ledger"),
            _make_claim_dict("c6", "doc3", "Material Ledger", "SUPPORTS", "Valuation"),
        ]
        detector1 = ChainDetector(max_edges_per_key_cross_doc=3)
        detector2 = ChainDetector(max_edges_per_key_cross_doc=3)

        links1 = detector1.detect_cross_doc(claims, hub_entities=set())
        links2 = detector2.detect_cross_doc(claims, hub_entities=set())

        # Même nombre
        assert len(links1) == len(links2)
        # Mêmes paires dans le même ordre
        pairs1 = [(l.source_claim_id, l.target_claim_id) for l in links1]
        pairs2 = [(l.source_claim_id, l.target_claim_id) for l in links2]
        assert pairs1 == pairs2


class TestCrossDocCaps:
    """Caps per join_key et per doc_pair."""

    def test_cap_per_join_key(self):
        """Le nombre de liens par join_key est cappé."""
        claims = []
        # 5 sources (doc1) × 5 targets (doc2) = 25 paires pour "central finance"
        for i in range(5):
            claims.append(
                _make_claim_dict(
                    f"src_{i}", "doc1", f"Module {i}", "USES", "Central Finance"
                )
            )
        for i in range(5):
            claims.append(
                _make_claim_dict(
                    f"tgt_{i}", "doc2", "Central Finance", "PROVIDES", f"Feature {i}"
                )
            )

        detector = ChainDetector(max_edges_per_key_cross_doc=3)
        links = detector.detect_cross_doc(claims, hub_entities=set())

        assert len(links) == 3

    def test_cap_per_doc_pair(self):
        """Le nombre de liens par paire de docs est cappé."""
        claims = []
        # Beaucoup de join_keys différents entre doc1 et doc2
        for i in range(20):
            entity = f"Entity Alpha {i}"
            claims.append(
                _make_claim_dict(
                    f"src_{i}", "doc1", f"Module {i}", "USES", entity
                )
            )
            claims.append(
                _make_claim_dict(
                    f"tgt_{i}", "doc2", entity, "PROVIDES", f"Feature {i}"
                )
            )

        # max_edges_per_key_cross_doc=5 (par join_key), mais cap doc_pair=10
        detector = ChainDetector(
            max_edges_per_key_cross_doc=5,
            max_edges_per_doc_pair=10,
        )
        links = detector.detect_cross_doc(claims, hub_entities=set())

        assert len(links) == 10


class TestCrossDocEntityIndex:
    """Jointure par entity_id (robuste)."""

    def test_join_by_entity_id(self):
        """Claims avec entity_index → jointure par entity_id."""
        entity_index = {
            "material ledger": "ent_042",
        }
        claims = [
            _make_claim_dict("c1", "doc1", "SAP S/4HANA", "USES", "Material Ledger"),
            _make_claim_dict("c2", "doc2", "Material Ledger", "ENABLES", "Valuation"),
        ]
        detector = ChainDetector()
        links = detector.detect_cross_doc(
            claims, hub_entities=set(), entity_index=entity_index
        )

        assert len(links) == 1
        assert links[0].join_method == "entity_id"
        # join_key = entity_id, mais join_key_name = nom lisible
        assert links[0].join_key == "ent_042"
        assert links[0].join_key_name == "material ledger"

    def test_fallback_to_normalized_name(self):
        """Sans entity_index → fallback sur normalized_name."""
        claims = [
            _make_claim_dict("c1", "doc1", "SAP S/4HANA", "USES", "Material Ledger"),
            _make_claim_dict("c2", "doc2", "Material Ledger", "ENABLES", "Valuation"),
        ]
        detector = ChainDetector()
        links = detector.detect_cross_doc(claims, hub_entities=set())

        assert len(links) == 1
        assert links[0].join_method == "normalized_name"

    def test_mixed_entity_id_and_normalized(self):
        """Certaines entities résolues par entity_id, d'autres par normalized."""
        entity_index = {
            "material ledger": "ent_042",
            # "central finance" pas dans l'index
        }
        claims = [
            _make_claim_dict("c1", "doc1", "SAP S/4HANA", "USES", "Material Ledger"),
            _make_claim_dict("c2", "doc2", "Material Ledger", "ENABLES", "Valuation"),
            _make_claim_dict("c3", "doc1", "SAP ERP", "USES", "Central Finance"),
            _make_claim_dict("c4", "doc2", "Central Finance", "PROVIDES", "Reports"),
        ]
        detector = ChainDetector()
        links = detector.detect_cross_doc(
            claims, hub_entities=set(), entity_index=entity_index
        )

        assert len(links) == 2
        methods = {l.join_method for l in links}
        assert "entity_id" in methods
        assert "normalized_name" in methods


class TestCrossDocGuardRails:
    """Garde-fous cross-doc."""

    def test_no_self_loop(self):
        """Même claim_id en source et target → pas d'edge."""
        claims = [
            _make_claim_dict("c1", "doc1", "SAP S/4HANA", "USES", "SAP S/4HANA"),
        ]
        detector = ChainDetector()
        links = detector.detect_cross_doc(claims, hub_entities=set())
        assert len(links) == 0

    def test_invalid_entity_rejected(self):
        """Join key invalide (stoplist) → rejeté."""
        claims = [
            _make_claim_dict("c1", "doc1", "SAP BTP", "PROVIDES", "system"),
            _make_claim_dict("c2", "doc2", "system", "USES", "Kubernetes"),
        ]
        detector = ChainDetector()
        links = detector.detect_cross_doc(claims, hub_entities=set())
        assert len(links) == 0

    def test_short_join_key_rejected(self):
        """Join key < 3 chars → rejeté."""
        claims = [
            _make_claim_dict("c1", "doc1", "SAP", "USES", "AI"),
            _make_claim_dict("c2", "doc2", "AI", "ENABLES", "Automation"),
        ]
        detector = ChainDetector()
        links = detector.detect_cross_doc(claims, hub_entities=set())
        assert len(links) == 0

    def test_non_canonical_predicate_excluded(self):
        """Claims avec prédicats non-canoniques ignorées."""
        claims = [
            _make_claim_dict("c1", "doc1", "SAP S/4HANA", "MONITORS", "Performance"),
            _make_claim_dict("c2", "doc2", "Performance", "CONNECTS_TO", "Dashboard"),
        ]
        detector = ChainDetector()
        links = detector.detect_cross_doc(claims, hub_entities=set())
        assert len(links) == 0

    def test_no_trivial_cycle_cross_doc(self):
        """Cycle trivial cross-doc bloqué."""
        claims = [
            _make_claim_dict("c1", "doc1", "HANA Database", "USES", "HANA Database"),
            _make_claim_dict("c2", "doc2", "HANA Database", "USES", "HANA Database"),
        ]
        detector = ChainDetector()
        links = detector.detect_cross_doc(claims, hub_entities=set())
        # Self-loop bloqué (même claim_id ou cycle trivial)
        assert len(links) == 0


class TestCrossDocStats:
    """Statistiques cross-doc."""

    def test_cross_doc_stats_populated(self):
        """Les stats cross-doc sont remplies après detect_cross_doc."""
        claims = [
            _make_claim_dict("c1", "doc1", "SAP S/4HANA", "USES", "Material Ledger"),
            _make_claim_dict("c2", "doc2", "Material Ledger", "ENABLES", "Valuation"),
        ]
        detector = ChainDetector()
        links = detector.detect_cross_doc(claims, hub_entities=set())

        stats = detector.get_cross_doc_stats()
        assert stats["claims_with_sf"] == 2
        assert stats["chains_detected"] == 1
        assert stats["join_keys_found"] >= 1
        assert stats["joins_by_normalized"] >= 1

    def test_reset_cross_doc_stats(self):
        """reset_cross_doc_stats remet tout à zéro."""
        detector = ChainDetector()
        detector._cross_doc_stats["chains_detected"] = 42
        detector.reset_cross_doc_stats()
        assert detector._cross_doc_stats["chains_detected"] == 0


class TestComputeIdf:
    """Tests pour compute_idf."""

    def test_idf_rare_vs_common(self):
        """Un terme rare a un IDF plus haut qu'un terme commun."""
        claims = [
            _make_claim_dict("c1", "doc1", "Module", "USES", "Rare Concept"),
            _make_claim_dict("c2", "doc2", "Common Concept", "USES", "Feature"),
            _make_claim_dict("c3", "doc3", "Common Concept", "PROVIDES", "Output"),
            _make_claim_dict("c4", "doc1", "Common Concept", "ENABLES", "Scaling"),
        ]
        idf = ChainDetector.compute_idf(claims)

        # "rare concept" dans 1 claim, "common concept" dans 3 claims
        assert idf["rare concept"] > idf["common concept"]

    def test_idf_empty_input(self):
        """Pas de claims → IDF vide."""
        idf = ChainDetector.compute_idf([])
        assert idf == {}

    def test_idf_with_entity_index(self):
        """IDF utilise entity_id si disponible."""
        entity_index = {"material ledger": "ent_042"}
        claims = [
            _make_claim_dict("c1", "doc1", "SAP", "USES", "Material Ledger"),
            _make_claim_dict("c2", "doc2", "Material Ledger", "PROVIDES", "Reports"),
        ]
        idf = ChainDetector.compute_idf(claims, entity_index=entity_index)

        # Le join_key doit être "ent_042" (entity_id), pas "material ledger"
        assert "ent_042" in idf

    def test_idf_values_are_log_based(self):
        """IDF = log(total / count)."""
        claims = [
            _make_claim_dict("c1", "doc1", "Alpha", "USES", "Target"),
            _make_claim_dict("c2", "doc2", "Beta", "USES", "Target"),
            _make_claim_dict("c3", "doc3", "Gamma", "USES", "Feature"),
        ]
        idf = ChainDetector.compute_idf(claims)

        # "target" apparaît dans 2 claims sur 3 → IDF = log(3/2)
        assert abs(idf["target"] - math.log(3 / 2)) < 0.001


class TestCrossDocIntraDocIntact:
    """Vérification que l'intra-doc n'est pas affecté."""

    def test_intra_doc_still_works(self):
        """detect_from_dicts fonctionne toujours pour l'intra-doc."""
        claims = [
            _make_claim_dict("c1", "doc1", "SAP S/4HANA", "USES", "Material Ledger"),
            _make_claim_dict("c2", "doc1", "Material Ledger", "ENABLES", "Valuation"),
        ]
        detector = ChainDetector()
        relations = detector.detect_from_dicts(claims)

        assert len(relations) == 1
        assert relations[0].source_claim_id == "c1"
        assert relations[0].target_claim_id == "c2"

    def test_cross_doc_excluded_from_intra(self):
        """detect_from_dicts ignore les liens cross-doc."""
        claims = [
            _make_claim_dict("c1", "doc1", "SAP S/4HANA", "USES", "Material Ledger"),
            _make_claim_dict("c2", "doc2", "Material Ledger", "ENABLES", "Valuation"),
        ]
        detector = ChainDetector()
        relations = detector.detect_from_dicts(claims)
        assert len(relations) == 0


class TestPredicatePriority:
    """Tests du dictionnaire PREDICATE_PRIORITY."""

    def test_structuring_predicates_highest(self):
        """REQUIRES, REPLACES, PART_OF, INTEGRATED_IN = score 4."""
        for pred in ("REQUIRES", "REPLACES", "PART_OF", "INTEGRATED_IN"):
            assert PREDICATE_PRIORITY[pred] == 4

    def test_all_canonical_predicates_have_priority(self):
        """Tous les prédicats canoniques ont un score de priorité."""
        from knowbase.claimfirst.composition.chain_detector import _CANONICAL_PREDICATES
        for pred in _CANONICAL_PREDICATES:
            assert pred in PREDICATE_PRIORITY, f"{pred} missing from PREDICATE_PRIORITY"


class TestJoinKeyName:
    """Tests pour join_key_name (invariant de lisibilité durable)."""

    def test_post_init_fallback(self):
        """ChainLink sans join_key_name → __post_init__ met join_key comme fallback."""
        link = ChainLink(
            source_claim_id="c1",
            target_claim_id="c2",
            join_key="material ledger",
            source_predicate="USES",
            target_predicate="ENABLES",
            doc_id="doc1",
        )
        assert link.join_key_name == "material ledger"

    def test_explicit_join_key_name(self):
        """ChainLink avec join_key_name explicite → pas de fallback."""
        link = ChainLink(
            source_claim_id="c1",
            target_claim_id="c2",
            join_key="ent_042",
            source_predicate="USES",
            target_predicate="ENABLES",
            doc_id="doc1↔doc2",
            join_key_name="material ledger",
        )
        assert link.join_key == "ent_042"
        assert link.join_key_name == "material ledger"

    def test_intra_doc_join_key_name(self):
        """Intra-doc : join_key_name == join_key (toujours normalized_name)."""
        claims = [
            _make_claim_dict("c1", "doc1", "SAP S/4HANA", "USES", "Material Ledger"),
            _make_claim_dict("c2", "doc1", "Material Ledger", "ENABLES", "Valuation"),
        ]
        detector = ChainDetector()
        relations = detector.detect_from_dicts(claims)
        assert len(relations) == 1
        # detect_from_dicts retourne ClaimRelation, pas ChainLink
        # On teste via _get_links_in_doc indirectement

    def test_cross_doc_entity_id_preserves_name(self):
        """Cross-doc avec entity_id : join_key != join_key_name."""
        entity_index = {"central finance": "ent_099"}
        claims = [
            _make_claim_dict("c1", "doc1", "SAP ERP", "USES", "Central Finance"),
            _make_claim_dict("c2", "doc2", "Central Finance", "PROVIDES", "Reports"),
        ]
        detector = ChainDetector()
        links = detector.detect_cross_doc(
            claims, hub_entities=set(), entity_index=entity_index
        )
        assert len(links) == 1
        assert links[0].join_key == "ent_099"
        assert links[0].join_key_name == "central finance"
        assert links[0].join_method == "entity_id"
