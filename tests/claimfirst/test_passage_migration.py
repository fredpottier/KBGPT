# tests/claimfirst/test_passage_migration.py
"""
Tests unitaires pour la migration Passages → propriétés Claims.

Teste la logique pure (build_batches, analyze_sharing)
sans nécessiter Neo4j.

Note: On duplique les fonctions utilitaires ici pour éviter d'importer
le script complet qui dépend de neo4j (non disponible localement).
"""

from typing import Any, Dict, List


# --- Fonctions copiées depuis migrate_passages_to_properties.py ---
# (logique pure, pas de dépendance Neo4j)

def build_batches(pairs: List[Dict[str, Any]], batch_size: int) -> List[List[Dict[str, Any]]]:
    """Découpe les paires en lots de taille batch_size."""
    return [pairs[i:i + batch_size] for i in range(0, len(pairs), batch_size)]


def analyze_sharing(pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyse la distribution 1:1 vs 1:N des passages."""
    passage_to_claims: Dict[str, List[str]] = {}
    for pair in pairs:
        pid = pair["passage_id"]
        if pid not in passage_to_claims:
            passage_to_claims[pid] = []
        passage_to_claims[pid].append(pair["claim_id"])

    unique_passages = len(passage_to_claims)
    shared = {pid: cids for pid, cids in passage_to_claims.items() if len(cids) > 1}
    exclusive = unique_passages - len(shared)

    distribution = {}
    for pid, cids in passage_to_claims.items():
        count = len(cids)
        if count not in distribution:
            distribution[count] = 0
        distribution[count] += 1

    return {
        "unique_passages": unique_passages,
        "exclusive_1_to_1": exclusive,
        "shared_1_to_n": len(shared),
        "shared_percentage": round(100 * len(shared) / unique_passages, 1) if unique_passages else 0,
        "total_claim_assignments": len(pairs),
        "distribution": dict(sorted(distribution.items())),
    }


# --- Tests ---

class TestBuildBatches:
    """Tests pour la construction des lots."""

    def test_empty_pairs(self):
        """Aucune paire → aucun lot."""
        batches = build_batches([], 500)
        assert batches == []

    def test_single_batch(self):
        """Moins de paires que la taille du lot → un seul lot."""
        pairs = [{"claim_id": f"c{i}", "passage_text": f"text{i}"} for i in range(3)]
        batches = build_batches(pairs, 500)
        assert len(batches) == 1
        assert len(batches[0]) == 3

    def test_multiple_batches(self):
        """Plus de paires que la taille du lot → plusieurs lots."""
        pairs = [{"claim_id": f"c{i}"} for i in range(7)]
        batches = build_batches(pairs, 3)
        assert len(batches) == 3
        assert len(batches[0]) == 3
        assert len(batches[1]) == 3
        assert len(batches[2]) == 1

    def test_exact_batch_size(self):
        """Nombre de paires = multiple exact de la taille du lot."""
        pairs = [{"claim_id": f"c{i}"} for i in range(6)]
        batches = build_batches(pairs, 3)
        assert len(batches) == 2
        assert all(len(b) == 3 for b in batches)


class TestAnalyzeSharing:
    """Tests pour l'analyse du partage de passages."""

    def test_all_exclusive(self):
        """Tous les passages sont 1:1 (un passage par claim)."""
        pairs = [
            {"passage_id": "p1", "claim_id": "c1"},
            {"passage_id": "p2", "claim_id": "c2"},
            {"passage_id": "p3", "claim_id": "c3"},
        ]
        sharing = analyze_sharing(pairs)
        assert sharing["unique_passages"] == 3
        assert sharing["exclusive_1_to_1"] == 3
        assert sharing["shared_1_to_n"] == 0
        assert sharing["shared_percentage"] == 0.0
        assert sharing["total_claim_assignments"] == 3
        assert sharing["distribution"] == {1: 3}

    def test_shared_passage_duplication(self):
        """1 Passage avec 3 Claims → 3 claims enrichies, 1 passage partagé."""
        pairs = [
            {"passage_id": "p1", "claim_id": "c1"},
            {"passage_id": "p1", "claim_id": "c2"},
            {"passage_id": "p1", "claim_id": "c3"},
        ]
        sharing = analyze_sharing(pairs)
        assert sharing["unique_passages"] == 1
        assert sharing["exclusive_1_to_1"] == 0
        assert sharing["shared_1_to_n"] == 1
        assert sharing["shared_percentage"] == 100.0
        assert sharing["total_claim_assignments"] == 3
        assert sharing["distribution"] == {3: 1}

    def test_mixed_sharing(self):
        """Mix de passages exclusifs et partagés."""
        pairs = [
            # p1 partagé entre c1 et c2
            {"passage_id": "p1", "claim_id": "c1"},
            {"passage_id": "p1", "claim_id": "c2"},
            # p2 exclusif
            {"passage_id": "p2", "claim_id": "c3"},
            # p3 partagé entre c4, c5, c6
            {"passage_id": "p3", "claim_id": "c4"},
            {"passage_id": "p3", "claim_id": "c5"},
            {"passage_id": "p3", "claim_id": "c6"},
        ]
        sharing = analyze_sharing(pairs)
        assert sharing["unique_passages"] == 3
        assert sharing["exclusive_1_to_1"] == 1
        assert sharing["shared_1_to_n"] == 2
        assert sharing["total_claim_assignments"] == 6
        assert sharing["distribution"] == {1: 1, 2: 1, 3: 1}

    def test_empty_pairs(self):
        """Aucune paire → stats à zéro."""
        sharing = analyze_sharing([])
        assert sharing["unique_passages"] == 0
        assert sharing["exclusive_1_to_1"] == 0
        assert sharing["shared_1_to_n"] == 0
        assert sharing["shared_percentage"] == 0
        assert sharing["total_claim_assignments"] == 0

    def test_idempotent_analysis(self):
        """Analyser deux fois les mêmes données donne le même résultat."""
        pairs = [
            {"passage_id": "p1", "claim_id": "c1"},
            {"passage_id": "p1", "claim_id": "c2"},
            {"passage_id": "p2", "claim_id": "c3"},
        ]
        result1 = analyze_sharing(pairs)
        result2 = analyze_sharing(pairs)
        assert result1 == result2
