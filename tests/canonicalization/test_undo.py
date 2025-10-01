"""
Tests undo transactionnel Phase 0 Critère 3
Valide annulation merge avec restauration état initial
"""

import pytest
from fastapi.testclient import TestClient
from knowbase.api.main import create_app


@pytest.fixture
def client():
    """Client de test FastAPI"""
    app = create_app()
    return TestClient(app)


class TestUndoMerge:
    """Tests undo merge transactionnel"""

    def test_undo_merge_within_7_days_succeeds(self, client):
        """
        Test undo merge dans délai 7j → succès

        Critère validation Phase 0.3:
        - Merge effectué puis undo immédiat
        - État initial restauré (candidates redeviennent disponibles)
        - Audit trail complet (merge + undo)
        """
        # Étape 1: Effectuer un merge
        merge_request = {
            "canonical_entity_id": "canonical_test_undo_001",
            "candidate_ids": ["cand_undo_1", "cand_undo_2", "cand_undo_3"],
            "user_id": "user_merge_123"
        }

        merge_response = client.post(
            "/api/canonicalization/merge",
            json=merge_request,
            headers={"Idempotency-Key": "test-undo-merge-001"}
        )

        assert merge_response.status_code == 200
        merge_data = merge_response.json()

        # Récupérer merge_id généré
        merge_id = merge_data.get("merge_id")
        assert merge_id is not None, "merge_id manquant dans réponse merge"

        # Étape 2: Effectuer undo immédiatement (dans délai 7j)
        undo_request = {
            "merge_id": merge_id,
            "reason": "Erreur de merge détectée - mauvaise entité canonique sélectionnée",
            "user_id": "admin_undo_456"
        }

        undo_response = client.post(
            "/api/canonicalization/undo-merge",
            json=undo_request
        )

        assert undo_response.status_code == 200, (
            f"Expected 200 OK mais reçu {undo_response.status_code}: {undo_response.text}"
        )

        undo_data = undo_response.json()

        # Vérifier résultat undo
        assert undo_data["merge_id"] == merge_id
        assert undo_data["operation"] == "undo_merge"
        assert set(undo_data["restored_candidates"]) == {"cand_undo_1", "cand_undo_2", "cand_undo_3"}
        assert undo_data["previous_canonical_id"] == "canonical_test_undo_001"
        assert undo_data["reason"] == "Erreur de merge détectée - mauvaise entité canonique sélectionnée"
        assert undo_data["executed_by"] == "admin_undo_456"
        assert undo_data["status"] == "undone"
        assert "audit_entry_id" in undo_data

        print(f"✅ Undo merge réussi: merge_id={merge_id[:12]}... → {len(undo_data['restored_candidates'])} candidates restaurées")

    def test_undo_merge_nonexistent_returns_404(self, client):
        """Test undo merge inexistant → 404 Not Found"""
        undo_request = {
            "merge_id": "merge_nonexistent_abc123xyz",
            "reason": "Test undo merge inexistant",
            "user_id": "admin_test"
        }

        response = client.post(
            "/api/canonicalization/undo-merge",
            json=undo_request
        )

        assert response.status_code == 404, (
            f"Expected 404 Not Found mais reçu {response.status_code}"
        )

        data = response.json()
        assert "introuvable" in data["detail"].lower()

        print(f"✅ 404 correctement retourné pour merge inexistant")

    def test_undo_merge_without_reason_returns_422(self, client):
        """Test undo sans raison → 422 Validation Error"""
        undo_request = {
            "merge_id": "merge_test_123",
            # Pas de "reason" (obligatoire)
            "user_id": "admin_test"
        }

        response = client.post(
            "/api/canonicalization/undo-merge",
            json=undo_request
        )

        # FastAPI validation error retourne 422
        assert response.status_code == 422, (
            f"Expected 422 Validation Error mais reçu {response.status_code}"
        )

        print(f"✅ 422 correctement retourné pour raison manquante")

    def test_undo_merge_reason_too_short_returns_422(self, client):
        """Test undo raison <10 caractères → 422 Validation Error"""
        undo_request = {
            "merge_id": "merge_test_456",
            "reason": "Erreur",  # < 10 caractères
            "user_id": "admin_test"
        }

        response = client.post(
            "/api/canonicalization/undo-merge",
            json=undo_request
        )

        # Pydantic validation min_length=10
        assert response.status_code == 422, (
            f"Expected 422 Validation Error mais reçu {response.status_code}"
        )

        print(f"✅ 422 correctement retourné pour raison trop courte")

    def test_undo_merge_audit_trail_complete(self, client):
        """
        Test audit trail complet: merge + undo tracés

        Vérifie:
        - Merge logged avec merge_id
        - Undo logged avec audit_entry_id
        - Lien entre merge et undo maintenu
        """
        # Effectuer merge
        merge_request = {
            "canonical_entity_id": "canonical_audit_test",
            "candidate_ids": ["cand_audit_1", "cand_audit_2"],
            "user_id": "user_audit_123"
        }

        merge_response = client.post(
            "/api/canonicalization/merge",
            json=merge_request,
            headers={"Idempotency-Key": "test-audit-trail-001"}
        )

        assert merge_response.status_code == 200
        merge_id = merge_response.json()["merge_id"]

        # Effectuer undo
        undo_request = {
            "merge_id": merge_id,
            "reason": "Test audit trail complet avec undo",
            "user_id": "admin_audit_456"
        }

        undo_response = client.post(
            "/api/canonicalization/undo-merge",
            json=undo_request
        )

        assert undo_response.status_code == 200
        undo_data = undo_response.json()

        # Vérifier audit trail
        assert undo_data["merge_id"] == merge_id, "merge_id doit correspondre"
        assert undo_data["audit_entry_id"] is not None, "audit_entry_id manquant"
        assert undo_data["audit_entry_id"].startswith("undo_"), "audit_entry_id doit commencer par undo_"

        print(f"✅ Audit trail complet validé: merge={merge_id[:12]}... → undo={undo_data['audit_entry_id'][:16]}...")


class TestUndoLimitations:
    """Tests limitations undo (délais, contraintes)"""

    def test_undo_description_in_response(self, client):
        """Test que la réponse undo contient tous les champs requis"""
        # Effectuer merge
        merge_request = {
            "canonical_entity_id": "canonical_full_response_test",
            "candidate_ids": ["cand_full_1"],
            "user_id": "user_test"
        }

        merge_response = client.post(
            "/api/canonicalization/merge",
            json=merge_request,
            headers={"Idempotency-Key": "test-full-response-001"}
        )

        merge_id = merge_response.json()["merge_id"]

        # Effectuer undo
        undo_request = {
            "merge_id": merge_id,
            "reason": "Test complet de la structure de réponse undo",
            "user_id": "admin_test_full"
        }

        response = client.post(
            "/api/canonicalization/undo-merge",
            json=undo_request
        )

        assert response.status_code == 200
        data = response.json()

        # Vérifier tous les champs requis
        required_fields = [
            "merge_id",
            "operation",
            "restored_candidates",
            "previous_canonical_id",
            "reason",
            "executed_by",
            "executed_at",
            "status",
            "audit_entry_id"
        ]

        for field in required_fields:
            assert field in data, f"Champ '{field}' manquant dans réponse undo"

        assert data["operation"] == "undo_merge"
        assert data["status"] == "undone"
        assert isinstance(data["restored_candidates"], list)
        assert len(data["restored_candidates"]) > 0

        print(f"✅ Structure réponse undo complète validée ({len(required_fields)} champs)")
