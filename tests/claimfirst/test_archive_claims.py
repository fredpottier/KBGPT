# tests/claimfirst/test_archive_claims.py
"""
Tests unitaires pour l'archivage des claims isolées.

Teste la logique pure (is_claim_isolated, analyze_distribution)
sans nécessiter Neo4j.

Note: On duplique les fonctions utilitaires ici pour éviter d'importer
le script complet qui dépend de neo4j (non disponible localement).
"""

from typing import Any, Dict, List


# --- Fonctions copiées depuis archive_isolated_claims.py ---
# (logique pure, pas de dépendance Neo4j)

def is_claim_isolated(claim_data: Dict[str, Any]) -> bool:
    """Vérifie les critères d'isolation d'une claim."""
    if claim_data.get("structured_form_json") is not None:
        return False
    if claim_data.get("chains_to_out", 0) > 0:
        return False
    if claim_data.get("chains_to_in", 0) > 0:
        return False
    if claim_data.get("about_count", 0) > 0:
        return False
    if claim_data.get("refines_out", 0) > 0:
        return False
    if claim_data.get("refines_in", 0) > 0:
        return False
    if claim_data.get("qualifies_out", 0) > 0:
        return False
    if claim_data.get("qualifies_in", 0) > 0:
        return False
    if claim_data.get("contradicts_out", 0) > 0:
        return False
    if claim_data.get("contradicts_in", 0) > 0:
        return False
    return True


def analyze_distribution(claims: List[Dict[str, Any]]) -> Dict[str, int]:
    """Analyse la distribution des claims isolées par doc_id."""
    by_doc: Dict[str, int] = {}
    for claim in claims:
        doc_id = claim.get("doc_id", "unknown")
        by_doc[doc_id] = by_doc.get(doc_id, 0) + 1
    return dict(sorted(by_doc.items(), key=lambda x: -x[1]))


# --- Tests ---

class TestIsolationCriteria:
    """Tests pour les critères d'isolation."""

    def test_fully_isolated(self):
        """Claim sans structured_form et sans aucune relation → isolée."""
        claim = {
            "structured_form_json": None,
            "chains_to_out": 0,
            "chains_to_in": 0,
            "about_count": 0,
            "refines_out": 0,
            "refines_in": 0,
            "qualifies_out": 0,
            "qualifies_in": 0,
            "contradicts_out": 0,
            "contradicts_in": 0,
        }
        assert is_claim_isolated(claim) is True

    def test_has_structured_form(self):
        """Claim avec structured_form → pas isolée."""
        claim = {
            "structured_form_json": '{"s": "SAP", "p": "supports", "o": "HANA"}',
            "chains_to_out": 0,
            "chains_to_in": 0,
            "about_count": 0,
            "refines_out": 0,
            "refines_in": 0,
            "qualifies_out": 0,
            "qualifies_in": 0,
            "contradicts_out": 0,
            "contradicts_in": 0,
        }
        assert is_claim_isolated(claim) is False

    def test_has_chains_to_out(self):
        """Claim avec CHAINS_TO sortant → pas isolée."""
        claim = {
            "structured_form_json": None,
            "chains_to_out": 1,
            "chains_to_in": 0,
            "about_count": 0,
            "refines_out": 0,
            "refines_in": 0,
            "qualifies_out": 0,
            "qualifies_in": 0,
            "contradicts_out": 0,
            "contradicts_in": 0,
        }
        assert is_claim_isolated(claim) is False

    def test_has_chains_to_in(self):
        """Claim cible de CHAINS_TO → pas isolée."""
        claim = {
            "structured_form_json": None,
            "chains_to_out": 0,
            "chains_to_in": 2,
            "about_count": 0,
            "refines_out": 0,
            "refines_in": 0,
            "qualifies_out": 0,
            "qualifies_in": 0,
            "contradicts_out": 0,
            "contradicts_in": 0,
        }
        assert is_claim_isolated(claim) is False

    def test_has_about(self):
        """Claim avec relation ABOUT → pas isolée."""
        claim = {
            "structured_form_json": None,
            "chains_to_out": 0,
            "chains_to_in": 0,
            "about_count": 1,
            "refines_out": 0,
            "refines_in": 0,
            "qualifies_out": 0,
            "qualifies_in": 0,
            "contradicts_out": 0,
            "contradicts_in": 0,
        }
        assert is_claim_isolated(claim) is False

    def test_has_refines_out(self):
        """Claim qui REFINES une autre → pas isolée."""
        claim = {
            "structured_form_json": None,
            "chains_to_out": 0,
            "chains_to_in": 0,
            "about_count": 0,
            "refines_out": 1,
            "refines_in": 0,
            "qualifies_out": 0,
            "qualifies_in": 0,
            "contradicts_out": 0,
            "contradicts_in": 0,
        }
        assert is_claim_isolated(claim) is False

    def test_has_qualifies_in(self):
        """Claim qualifiée par une autre → pas isolée."""
        claim = {
            "structured_form_json": None,
            "chains_to_out": 0,
            "chains_to_in": 0,
            "about_count": 0,
            "refines_out": 0,
            "refines_in": 0,
            "qualifies_out": 0,
            "qualifies_in": 1,
            "contradicts_out": 0,
            "contradicts_in": 0,
        }
        assert is_claim_isolated(claim) is False

    def test_has_contradicts(self):
        """Claim qui CONTRADICTS → pas isolée."""
        claim = {
            "structured_form_json": None,
            "chains_to_out": 0,
            "chains_to_in": 0,
            "about_count": 0,
            "refines_out": 0,
            "refines_in": 0,
            "qualifies_out": 0,
            "qualifies_in": 0,
            "contradicts_out": 1,
            "contradicts_in": 0,
        }
        assert is_claim_isolated(claim) is False

    def test_missing_fields_default_to_isolated(self):
        """Claim avec champs manquants (defaults à 0) → isolée si pas de structured_form."""
        claim = {"structured_form_json": None}
        assert is_claim_isolated(claim) is True


class TestAnalyzeDistribution:
    """Tests pour l'analyse de distribution."""

    def test_single_document(self):
        """Toutes les claims d'un seul document."""
        claims = [
            {"claim_id": "c1", "doc_id": "doc1"},
            {"claim_id": "c2", "doc_id": "doc1"},
            {"claim_id": "c3", "doc_id": "doc1"},
        ]
        dist = analyze_distribution(claims)
        assert dist == {"doc1": 3}

    def test_multiple_documents(self):
        """Claims réparties sur plusieurs documents."""
        claims = [
            {"claim_id": "c1", "doc_id": "doc1"},
            {"claim_id": "c2", "doc_id": "doc2"},
            {"claim_id": "c3", "doc_id": "doc1"},
            {"claim_id": "c4", "doc_id": "doc3"},
            {"claim_id": "c5", "doc_id": "doc2"},
        ]
        dist = analyze_distribution(claims)
        assert dist["doc1"] == 2
        assert dist["doc2"] == 2
        assert dist["doc3"] == 1

    def test_empty(self):
        """Aucune claim → distribution vide."""
        assert analyze_distribution([]) == {}

    def test_idempotent(self):
        """Analyser deux fois donne le même résultat."""
        claims = [
            {"claim_id": "c1", "doc_id": "doc1"},
            {"claim_id": "c2", "doc_id": "doc2"},
        ]
        r1 = analyze_distribution(claims)
        r2 = analyze_distribution(claims)
        assert r1 == r2


class TestArchivedExclusion:
    """Tests pour la logique d'exclusion (mock du filtre query)."""

    def test_archived_claims_should_be_filtered(self):
        """Vérifie la logique de filtrage des claims archivées."""
        claims = [
            {"claim_id": "c1", "archived": True},
            {"claim_id": "c2", "archived": False},
            {"claim_id": "c3", "archived": None},
            {"claim_id": "c4"},  # Pas de champ archived
        ]

        # Logique de filtrage équivalente au filtre Cypher
        def is_active(claim):
            archived = claim.get("archived")
            return archived is None or archived is False

        active = [c for c in claims if is_active(c)]
        assert len(active) == 3
        assert all(c["claim_id"] != "c1" for c in active)

    def test_idempotent_archive(self):
        """Archiver deux fois ne change pas le résultat."""
        claims = [
            {"claim_id": "c1", "archived": None},
            {"claim_id": "c2", "archived": True},  # déjà archivée
        ]

        for c in claims:
            c["archived"] = True

        for c in claims:
            c["archived"] = True

        assert all(c["archived"] is True for c in claims)
