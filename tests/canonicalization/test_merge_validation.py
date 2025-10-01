"""
Tests validation stricte merge inputs - Phase 0.5 Durcissement P0.1
Valide rejection des cas limites critiques
"""
import pytest
from fastapi.testclient import TestClient
from knowbase.api.main import create_app


@pytest.fixture
def client():
    """Client test FastAPI"""
    app = create_app()
    return TestClient(app)


class TestMergeValidationP01:
    """Tests validation stricte inputs merge (P0.1)"""

    def test_merge_with_zero_candidates_rejected(self, client):
        """
        Test merge avec 0 candidates rejeté

        Critere P0.1: Bloquer merge avec liste vide
        Expected: 422 Unprocessable Entity (validation Pydantic min_length=1)
        """
        response = client.post(
            "/api/canonicalization/merge",
            json={
                "canonical_entity_id": "canon_test_001",
                "candidate_ids": []  # VIDE
            },
            headers={"Idempotency-Key": "test-zero-candidates"}
        )

        assert response.status_code == 422  # Pydantic validation
        print("OK: Merge 0 candidates rejeté (Pydantic validation)")

    def test_merge_with_self_reference_rejected(self, client):
        """
        Test merge avec self-reference rejeté

        Critere P0.1: Bloquer canonical_id dans candidate_ids
        Expected: 400 Bad Request avec message self-reference
        """
        canonical_id = "canon_self_ref_001"
        
        response = client.post(
            "/api/canonicalization/merge",
            json={
                "canonical_entity_id": canonical_id,
                "candidate_ids": ["cand_1", canonical_id, "cand_2"]  # SELF-REF
            },
            headers={"Idempotency-Key": "test-self-reference"}
        )

        assert response.status_code == 400
        assert "self-reference" in response.text.lower()
        print("OK: Self-reference rejeté")

    def test_merge_with_duplicates_rejected(self, client):
        """
        Test merge avec duplicates rejeté

        Critere P0.1: Bloquer duplicates dans candidate_ids
        Expected: 400 Bad Request avec message duplicates
        """
        response = client.post(
            "/api/canonicalization/merge",
            json={
                "canonical_entity_id": "canon_dup_001",
                "candidate_ids": ["cand_1", "cand_2", "cand_1", "cand_3"]  # DUPLICATE
            },
            headers={"Idempotency-Key": "test-duplicates"}
        )

        assert response.status_code == 400
        assert "duplicate" in response.text.lower()
        print("OK: Duplicates rejetés")

    def test_merge_with_empty_candidate_id_rejected(self, client):
        """
        Test merge avec candidate ID vide rejeté

        Critere P0.1: Bloquer IDs vides/invalides
        Expected: 400 Bad Request
        """
        response = client.post(
            "/api/canonicalization/merge",
            json={
                "canonical_entity_id": "canon_empty_001",
                "candidate_ids": ["cand_1", "", "cand_2"]  # VIDE
            },
            headers={"Idempotency-Key": "test-empty-id"}
        )

        assert response.status_code == 400
        assert "vide" in response.text.lower() or "invalide" in response.text.lower()
        print("OK: Candidate ID vide rejeté")

    def test_merge_with_valid_inputs_accepted(self, client):
        """
        Test merge avec inputs valides accepté

        Critere P0.1: Merge valide doit passer
        Expected: 200 OK
        """
        response = client.post(
            "/api/canonicalization/merge",
            json={
                "canonical_entity_id": "canon_valid_001",
                "candidate_ids": ["cand_1", "cand_2", "cand_3"]  # VALIDE
            },
            headers={"Idempotency-Key": "test-valid-merge"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["canonical_entity_id"] == "canon_valid_001"
        assert len(data["merged_candidates"]) == 3
        print("OK: Merge valide accepté")
