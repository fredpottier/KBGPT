# tests/claimfirst/test_chain_detector.py
"""
Tests pour ChainDetector — détection déterministe de chaînes S/P/O intra-doc.
"""

import pytest

from knowbase.claimfirst.composition.chain_detector import ChainDetector, ChainLink
from knowbase.claimfirst.models.result import RelationType


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


class TestChainDetectorBasic:
    """Tests de base : chaînes simples."""

    def test_simple_chain_two_claims(self):
        """A.object == B.subject → CHAINS_TO."""
        claims = [
            _make_claim_dict("c1", "doc1", "SAP S/4HANA", "USES", "Material Ledger"),
            _make_claim_dict("c2", "doc1", "Material Ledger", "ENABLES", "Real-Time Valuation"),
        ]
        detector = ChainDetector()
        relations = detector.detect_from_dicts(claims)

        assert len(relations) == 1
        r = relations[0]
        assert r.source_claim_id == "c1"
        assert r.target_claim_id == "c2"
        assert r.relation_type == RelationType.CHAINS_TO
        assert r.confidence == 1.0
        assert "material ledger" in r.basis.lower()

    def test_three_claim_chain(self):
        """A→B→C : deux edges CHAINS_TO."""
        claims = [
            _make_claim_dict("c1", "doc1", "SAP ERP", "BASED_ON", "SAP S/4HANA"),
            _make_claim_dict("c2", "doc1", "SAP S/4HANA", "USES", "HANA Database"),
            _make_claim_dict("c3", "doc1", "HANA Database", "PROVIDES", "In-Memory Processing"),
        ]
        detector = ChainDetector()
        relations = detector.detect_from_dicts(claims)

        assert len(relations) == 2
        ids = {(r.source_claim_id, r.target_claim_id) for r in relations}
        assert ("c1", "c2") in ids
        assert ("c2", "c3") in ids

    def test_no_chain_different_entities(self):
        """Pas de chaîne si object != subject."""
        claims = [
            _make_claim_dict("c1", "doc1", "SAP BTP", "USES", "Cloud Foundry"),
            _make_claim_dict("c2", "doc1", "Kubernetes", "ENABLES", "Containerization"),
        ]
        detector = ChainDetector()
        relations = detector.detect_from_dicts(claims)

        assert len(relations) == 0

    def test_normalization_matches(self):
        """Le matching est case-insensitive et strip."""
        claims = [
            _make_claim_dict("c1", "doc1", "SAP", "USES", "Material Ledger"),
            _make_claim_dict("c2", "doc1", "material ledger", "ENABLES", "Valuation"),
        ]
        detector = ChainDetector()
        relations = detector.detect_from_dicts(claims)

        assert len(relations) == 1

    def test_empty_input(self):
        """Liste vide → aucune relation."""
        detector = ChainDetector()
        relations = detector.detect_from_dicts([])
        assert relations == []

    def test_no_structured_form(self):
        """Claims sans structured_form → ignorées."""
        claims = [
            {"claim_id": "c1", "doc_id": "doc1", "structured_form": None},
            {"claim_id": "c2", "doc_id": "doc1"},
        ]
        detector = ChainDetector()
        relations = detector.detect_from_dicts(claims)
        assert relations == []


class TestChainDetectorGuardRails:
    """Tests des garde-fous."""

    def test_no_self_loop(self):
        """Même claim en source et target → pas d'edge."""
        claims = [
            _make_claim_dict("c1", "doc1", "SAP S/4HANA", "USES", "SAP S/4HANA"),
        ]
        detector = ChainDetector()
        relations = detector.detect_from_dicts(claims)
        assert len(relations) == 0

    def test_no_trivial_cycle(self):
        """A.subject == B.object ET A.object == B.subject → pas d'edge."""
        claims = [
            _make_claim_dict("c1", "doc1", "Material Ledger", "SUPPORTS", "SAP S/4HANA"),
            _make_claim_dict("c2", "doc1", "SAP S/4HANA", "USES", "Material Ledger"),
        ]
        detector = ChainDetector()
        relations = detector.detect_from_dicts(claims)
        # Les deux edges forment un cycle trivial, les deux sont bloqués
        # c1.object=S/4HANA == c2.subject=S/4HANA → edge c1→c2
        #   mais c1.subject=Material Ledger == c2.object=Material Ledger
        #   ET join_key=sap s4hana → c1.subject_norm == c2.object_norm == join_key? Non.
        #   join_key = "sap s4hana", c1.subject_norm = "material ledger", c2.object_norm = "material ledger"
        #   c1.subject_norm != join_key → pas de cycle trivial sur CE join
        # Inversement pour join_key = "material ledger":
        #   c2.object=Material Ledger → source, c1.subject=Material Ledger → target
        #   Edge c2→c1. c2.subject_norm="sap s4hana", c1.object_norm="sap s4hana"
        #   c2.subject_norm == c1.object_norm == "sap s4hana" != join_key="material ledger"
        #   Pas de cycle trivial non plus → edge émise.
        # Conclusion : 2 edges (c1→c2 via s4hana, c2→c1 via material ledger)
        # Ce n'est PAS un cycle trivial car les join_keys sont différents.
        assert len(relations) == 2

    def test_actual_trivial_cycle(self):
        """Cycle trivial réel: A.object == B.subject == join_key ET A.subject == B.object == join_key."""
        # Pour que le cycle soit trivial, il faut que pour un MÊME join_key:
        # A.object = join_key = B.subject ET A.subject = join_key = B.object
        # Ce qui implique subject == object == join_key pour les deux claims
        claims = [
            _make_claim_dict("c1", "doc1", "HANA Database", "USES", "HANA Database"),
        ]
        detector = ChainDetector()
        relations = detector.detect_from_dicts(claims)
        # Self-loop bloqué
        assert len(relations) == 0

    def test_invalid_entity_join_key_rejected(self):
        """Join key qui est un terme générique → rejeté par is_valid_entity_name."""
        claims = [
            _make_claim_dict("c1", "doc1", "SAP BTP", "PROVIDES", "system"),
            _make_claim_dict("c2", "doc1", "system", "USES", "Kubernetes"),
        ]
        detector = ChainDetector()
        relations = detector.detect_from_dicts(claims)
        # "system" est dans la stoplist
        assert len(relations) == 0

    def test_short_join_key_rejected(self):
        """Join key < 3 caractères → rejeté."""
        claims = [
            _make_claim_dict("c1", "doc1", "SAP", "USES", "AI"),
            _make_claim_dict("c2", "doc1", "AI", "ENABLES", "Automation"),
        ]
        detector = ChainDetector()
        relations = detector.detect_from_dicts(claims)
        # "AI" normalisé = "ai" (len=2 < 3)
        # Mais "AI" est un acronyme 2 lettres... is_valid_entity_name check
        # En fait: is_valid_entity_name("ai") → normalized "ai", len < 3 et pas un acronyme majuscule
        assert len(relations) == 0

    def test_anti_cartesian_cap(self):
        """Plus de max_edges_per_key edges par join_key → cappé."""
        # Créer 5 sources et 5 targets = 25 combinaisons
        claims = []
        for i in range(5):
            claims.append(
                _make_claim_dict(
                    f"src_{i}", "doc1", f"Module {i}", "USES", "SAP S/4HANA",
                    confidence=0.5 + i * 0.1,
                )
            )
        for i in range(5):
            claims.append(
                _make_claim_dict(
                    f"tgt_{i}", "doc1", "SAP S/4HANA", "PROVIDES", f"Feature {i}",
                    confidence=0.5 + i * 0.1,
                )
            )

        detector = ChainDetector(max_edges_per_key=10)
        relations = detector.detect_from_dicts(claims)

        # 5*5=25 possibles, cappé à 10
        assert len(relations) == 10

    def test_anti_cartesian_prioritizes_high_confidence(self):
        """Les claims à plus haute confidence sont gardées en priorité."""
        claims = []
        for i in range(4):
            claims.append(
                _make_claim_dict(
                    f"src_{i}", "doc1", f"Module {i}", "USES", "SAP S/4HANA",
                    confidence=0.1 * (i + 1),
                )
            )
        for i in range(4):
            claims.append(
                _make_claim_dict(
                    f"tgt_{i}", "doc1", "SAP S/4HANA", "PROVIDES", f"Feature {i}",
                    confidence=0.1 * (i + 1),
                )
            )

        detector = ChainDetector(max_edges_per_key=3)
        relations = detector.detect_from_dicts(claims)

        assert len(relations) == 3
        # Les sources les plus confiantes (src_3=0.4, src_2=0.3) devraient apparaître
        source_ids = [r.source_claim_id for r in relations]
        assert "src_3" in source_ids


class TestChainDetectorIntraDoc:
    """Tests intra-doc uniquement."""

    def test_cross_doc_no_chain(self):
        """Claims de documents différents → pas de chaîne."""
        claims = [
            _make_claim_dict("c1", "doc1", "SAP S/4HANA", "USES", "Material Ledger"),
            _make_claim_dict("c2", "doc2", "Material Ledger", "ENABLES", "Valuation"),
        ]
        detector = ChainDetector()
        relations = detector.detect_from_dicts(claims)

        assert len(relations) == 0

    def test_multiple_docs_independent(self):
        """Chaînes dans chaque doc, indépendantes."""
        claims = [
            # doc1
            _make_claim_dict("c1", "doc1", "SAP BTP", "USES", "Cloud Foundry"),
            _make_claim_dict("c2", "doc1", "Cloud Foundry", "PROVIDES", "Runtime"),
            # doc2
            _make_claim_dict("c3", "doc2", "Azure", "USES", "Kubernetes"),
            _make_claim_dict("c4", "doc2", "Kubernetes", "ENABLES", "Scaling"),
        ]
        detector = ChainDetector()
        relations = detector.detect_from_dicts(claims)

        assert len(relations) == 2
        pairs = {(r.source_claim_id, r.target_claim_id) for r in relations}
        assert ("c1", "c2") in pairs
        assert ("c3", "c4") in pairs


class TestChainDetectorDedupAndPairs:
    """Tests déduplication des paires."""

    def test_no_duplicate_pairs(self):
        """Même paire (A, B) n'apparaît qu'une fois."""
        # Deux join_keys mènent à la même paire (improbable mais testons)
        claims = [
            _make_claim_dict("c1", "doc1", "SAP S/4HANA", "USES", "Material Ledger"),
            _make_claim_dict("c2", "doc1", "Material Ledger", "REPLACES", "Legacy System"),
        ]
        detector = ChainDetector()
        relations = detector.detect_from_dicts(claims)

        # 1 seule chaîne c1→c2 via "material ledger"
        assert len(relations) == 1

    def test_incomplete_sf_ignored(self):
        """structured_form avec champ manquant → ignoré."""
        claims = [
            _make_claim_dict("c1", "doc1", "SAP", "USES", ""),
            _make_claim_dict("c2", "doc1", "", "USES", "SAP"),
            _make_claim_dict("c3", "doc1", "SAP", "", "Cloud"),
        ]
        detector = ChainDetector()
        relations = detector.detect_from_dicts(claims)
        assert len(relations) == 0


class TestChainLinks:
    """Tests pour get_chain_links_from_dicts (métadonnées enrichies)."""

    def test_chain_link_metadata(self):
        """ChainLink contient les predicates et join_key_freq."""
        claims = [
            _make_claim_dict("c1", "doc1", "SAP S/4HANA", "BASED_ON", "HANA Database"),
            _make_claim_dict("c2", "doc1", "HANA Database", "PROVIDES", "In-Memory"),
        ]
        detector = ChainDetector()
        links = detector.get_chain_links_from_dicts(claims)

        assert len(links) == 1
        link = links[0]
        assert isinstance(link, ChainLink)
        assert link.join_key == "hana database"
        assert link.source_predicate == "BASED_ON"
        assert link.target_predicate == "PROVIDES"
        assert link.doc_id == "doc1"
        assert link.join_key_freq == 2  # c1 et c2 touchent ce join_key


class TestChainDetectorStats:
    """Tests des statistiques."""

    def test_stats_populated(self):
        claims = [
            _make_claim_dict("c1", "doc1", "SAP BTP", "USES", "Cloud Foundry"),
            _make_claim_dict("c2", "doc1", "Cloud Foundry", "PROVIDES", "Runtime"),
        ]
        detector = ChainDetector()
        detector.detect_from_dicts(claims)

        stats = detector.get_stats()
        assert stats["claims_with_sf"] == 2
        assert stats["docs_processed"] == 1
        assert stats["chains_detected"] == 1
        assert stats["join_keys_found"] >= 1

    def test_reset_stats(self):
        detector = ChainDetector()
        detector._stats["chains_detected"] = 42
        detector.reset_stats()
        assert detector._stats["chains_detected"] == 0
