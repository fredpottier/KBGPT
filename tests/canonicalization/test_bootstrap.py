"""
Tests unitaires pour le service de bootstrap KG
Tests via l'API avec TestClient pour éviter dépendance pytest-asyncio
"""

import pytest
from datetime import datetime
from fastapi.testclient import TestClient
from knowbase.api.main import create_app


@pytest.fixture
def client():
    """Client de test FastAPI"""
    app = create_app()
    return TestClient(app)


class TestBootstrapSchemas:
    """Tests des schémas Pydantic"""

    def test_bootstrap_config_defaults(self):
        """Test valeurs par défaut BootstrapConfig"""
        from knowbase.canonicalization.schemas import BootstrapConfig

        config = BootstrapConfig()

        assert config.min_occurrences == 10
        assert config.min_confidence == 0.8
        assert config.group_id is None
        assert config.entity_types is None
        assert config.dry_run is False

    def test_bootstrap_config_validation(self):
        """Test validation BootstrapConfig"""
        from knowbase.canonicalization.schemas import BootstrapConfig
        from pydantic import ValidationError

        # min_occurrences < 1 invalide
        with pytest.raises(ValidationError):
            BootstrapConfig(min_occurrences=0)

        # min_confidence hors limites
        with pytest.raises(ValidationError):
            BootstrapConfig(min_confidence=1.5)

        with pytest.raises(ValidationError):
            BootstrapConfig(min_confidence=-0.1)

    def test_entity_candidate_status(self):
        """Test enum EntityCandidateStatus"""
        from knowbase.canonicalization.schemas import EntityCandidateStatus

        assert EntityCandidateStatus.CANDIDATE == "candidate"
        assert EntityCandidateStatus.SEED == "seed"
        assert EntityCandidateStatus.CANONICAL == "canonical"
        assert EntityCandidateStatus.REJECTED == "rejected"

    def test_entity_candidate_creation(self):
        """Test création EntityCandidate"""
        from knowbase.canonicalization.schemas import EntityCandidate, EntityCandidateStatus

        candidate = EntityCandidate(
            name="SAP S/4HANA",
            entity_type="solution",
            confidence=0.95,
            occurrences=25,
            group_id="corporate"
        )

        assert candidate.name == "SAP S/4HANA"
        assert candidate.entity_type == "solution"
        assert candidate.confidence == 0.95
        assert candidate.occurrences == 25
        assert candidate.status == EntityCandidateStatus.CANDIDATE
        assert candidate.source_chunks == []
        assert candidate.attributes == {}


class TestBootstrapAPI:
    """Tests de l'API bootstrap via endpoints"""

    def test_bootstrap_empty_candidates(self, client):
        """Test bootstrap sans candidates (Phase 3 non implémentée)"""
        response = client.post(
            "/api/canonicalization/bootstrap",
            json={"dry_run": True}
        )

        assert response.status_code == 200
        data = response.json()

        assert data["total_candidates"] == 0
        assert data["promoted_seeds"] == 0
        assert data["seed_ids"] == []
        assert data["dry_run"] is True
        assert isinstance(data["duration_seconds"], (int, float))
        assert isinstance(data["by_entity_type"], dict)

    def test_bootstrap_with_custom_thresholds(self, client):
        """Test bootstrap avec seuils personnalisés"""
        response = client.post(
            "/api/canonicalization/bootstrap",
            json={
                "min_occurrences": 20,
                "min_confidence": 0.9,
                "dry_run": True
            }
        )

        assert response.status_code == 200
        data = response.json()

        # Actuellement 0 car Phase 3 non implémentée
        assert data["promoted_seeds"] == 0
        assert data["total_candidates"] == 0

    def test_bootstrap_with_group_filter(self, client):
        """Test bootstrap avec filtre group_id"""
        response = client.post(
            "/api/canonicalization/bootstrap",
            json={
                "group_id": "corporate",
                "min_occurrences": 10,
                "min_confidence": 0.8,
                "dry_run": True
            }
        )

        assert response.status_code == 200

    def test_bootstrap_with_entity_type_filter(self, client):
        """Test bootstrap avec filtre entity_types"""
        response = client.post(
            "/api/canonicalization/bootstrap",
            json={
                "entity_types": ["solution", "product"],
                "min_occurrences": 10,
                "min_confidence": 0.8,
                "dry_run": True
            }
        )

        assert response.status_code == 200

    def test_bootstrap_invalid_config_min_occurrences(self, client):
        """Test validation min_occurrences invalide"""
        response = client.post(
            "/api/canonicalization/bootstrap",
            json={
                "min_occurrences": 0,  # Invalide
                "dry_run": True
            }
        )

        assert response.status_code == 422  # Validation error

    def test_bootstrap_invalid_confidence_too_high(self, client):
        """Test validation confidence > 1.0"""
        response = client.post(
            "/api/canonicalization/bootstrap",
            json={
                "min_confidence": 1.5,  # Invalide
                "dry_run": True
            }
        )

        assert response.status_code == 422

    def test_bootstrap_invalid_confidence_negative(self, client):
        """Test validation confidence < 0"""
        response = client.post(
            "/api/canonicalization/bootstrap",
            json={
                "min_confidence": -0.1,  # Invalide
                "dry_run": True
            }
        )

        assert response.status_code == 422

    def test_bootstrap_progress_endpoint(self, client):
        """Test endpoint progression bootstrap"""
        # Lancer bootstrap
        response = client.post(
            "/api/canonicalization/bootstrap",
            json={"dry_run": True}
        )
        assert response.status_code == 200

        # Récupérer progression (peut être None si terminé très vite)
        progress_response = client.get("/api/canonicalization/bootstrap/progress")
        assert progress_response.status_code == 200

        # La réponse peut être null
        data = progress_response.json()
        if data is not None:
            assert "status" in data
            assert "processed" in data
            assert "total" in data
            assert "promoted" in data

    def test_bootstrap_estimate_endpoint(self, client):
        """Test endpoint estimation bootstrap"""
        response = client.post(
            "/api/canonicalization/bootstrap/estimate",
            json={
                "min_occurrences": 10,
                "min_confidence": 0.8
            }
        )

        assert response.status_code == 200
        data = response.json()

        assert "qualified_candidates" in data
        assert "by_entity_type" in data
        assert "estimated_duration_seconds" in data

    def test_bootstrap_dry_run_no_side_effects(self, client):
        """Test que dry_run=True ne modifie rien"""
        # Bootstrap 1
        response1 = client.post(
            "/api/canonicalization/bootstrap",
            json={
                "min_occurrences": 5,
                "min_confidence": 0.5,
                "dry_run": True
            }
        )

        assert response1.status_code == 200
        result1 = response1.json()

        # Bootstrap 2 (identique)
        response2 = client.post(
            "/api/canonicalization/bootstrap",
            json={
                "min_occurrences": 5,
                "min_confidence": 0.5,
                "dry_run": True
            }
        )

        assert response2.status_code == 200
        result2 = response2.json()

        # Résultats identiques
        assert result1["total_candidates"] == result2["total_candidates"]
        assert result1["promoted_seeds"] == result2["promoted_seeds"]

    def test_bootstrap_response_time_acceptable(self, client):
        """Test temps de réponse bootstrap"""
        import time

        start = time.time()
        response = client.post(
            "/api/canonicalization/bootstrap",
            json={"dry_run": True}
        )
        duration = time.time() - start

        assert response.status_code == 200
        # Doit répondre rapidement même vide
        assert duration < 5.0

    def test_bootstrap_with_user_context(self, client):
        """Test bootstrap avec contexte utilisateur"""
        response = client.post(
            "/api/canonicalization/bootstrap",
            json={"dry_run": True},
            headers={"X-User-ID": "user_test_bootstrap"}
        )

        assert response.status_code == 200


class TestBootstrapResult:
    """Tests du modèle BootstrapResult"""

    def test_bootstrap_result_structure(self, client):
        """Test structure complète de BootstrapResult"""
        response = client.post(
            "/api/canonicalization/bootstrap",
            json={
                "min_occurrences": 10,
                "min_confidence": 0.8,
                "dry_run": True
            }
        )

        assert response.status_code == 200
        data = response.json()

        # Vérifier tous les champs requis
        required_fields = [
            "total_candidates",
            "promoted_seeds",
            "seed_ids",
            "duration_seconds",
            "dry_run",
            "by_entity_type"
        ]

        for field in required_fields:
            assert field in data, f"Champ manquant: {field}"

        # Vérifier types
        assert isinstance(data["total_candidates"], int)
        assert isinstance(data["promoted_seeds"], int)
        assert isinstance(data["seed_ids"], list)
        assert isinstance(data["duration_seconds"], (int, float))
        assert isinstance(data["dry_run"], bool)
        assert isinstance(data["by_entity_type"], dict)


class TestBootstrapPhase3Readiness:
    """
    Tests de préparation pour Phase 3
    Ces tests documentent le comportement attendu avec vraies candidates
    """

    def test_bootstrap_placeholder_phase3(self, client):
        """
        [PLACEHOLDER] Test bootstrap avec vraies candidates

        Une fois Phase 3 implémentée:
        - Insérer documents de test
        - Attendre extraction candidates
        - Vérifier bootstrap promeut candidates fréquentes
        """
        response = client.post(
            "/api/canonicalization/bootstrap",
            json={
                "min_occurrences": 10,
                "min_confidence": 0.8,
                "dry_run": True
            }
        )

        assert response.status_code == 200
        data = response.json()

        # Actuellement 0 car Phase 3 non implémentée
        assert data["total_candidates"] == 0
        assert data["promoted_seeds"] == 0

        # TODO Phase 3: Ajouter assertions sur vraies candidates

    def test_bootstrap_openapi_documentation(self, client):
        """Test que les endpoints sont accessibles (OpenAPI spec custom)"""
        # Le projet utilise openapi.json custom, on vérifie juste que les endpoints répondent

        # Bootstrap endpoint
        response = client.post(
            "/api/canonicalization/bootstrap",
            json={"dry_run": True}
        )
        assert response.status_code == 200

        # Progress endpoint
        response = client.get("/api/canonicalization/bootstrap/progress")
        assert response.status_code == 200

        # Estimate endpoint
        response = client.post(
            "/api/canonicalization/bootstrap/estimate",
            json={"min_occurrences": 10, "min_confidence": 0.8}
        )
        assert response.status_code == 200
