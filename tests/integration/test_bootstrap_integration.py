"""
Tests d'intégration pour le bootstrap KG
Valide le cycle de vie complet du bootstrap via l'API
"""

import pytest
from fastapi.testclient import TestClient
from knowbase.api.main import create_app


@pytest.fixture
def client():
    """Client de test FastAPI"""
    app = create_app()
    return TestClient(app)


class TestBootstrapAPI:
    """Tests d'intégration de l'API bootstrap"""

    def test_bootstrap_endpoint_exists(self, client):
        """Test que l'endpoint bootstrap existe"""
        response = client.post(
            "/api/canonicalization/bootstrap",
            json={
                "min_occurrences": 10,
                "min_confidence": 0.8,
                "dry_run": True
            }
        )

        # Doit retourner 200 (pas d'erreur 404)
        assert response.status_code == 200

    def test_bootstrap_with_default_config(self, client):
        """Test bootstrap avec configuration par défaut"""
        response = client.post(
            "/api/canonicalization/bootstrap",
            json={"dry_run": True}
        )

        assert response.status_code == 200
        data = response.json()

        # Vérifier structure de la réponse
        assert "total_candidates" in data
        assert "promoted_seeds" in data
        assert "seed_ids" in data
        assert "duration_seconds" in data
        assert "dry_run" in data
        assert "by_entity_type" in data

        assert data["dry_run"] is True

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

        # Avec des seuils plus élevés, moins d'entités devraient qualifier
        # (Actuellement 0 car Phase 3 pas implémentée)
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
        data = response.json()
        assert data["dry_run"] is True

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
        data = response.json()
        assert data["dry_run"] is True

    def test_bootstrap_invalid_config(self, client):
        """Test validation de configuration invalide"""
        # min_occurrences < 1
        response = client.post(
            "/api/canonicalization/bootstrap",
            json={
                "min_occurrences": 0,  # Invalide
                "dry_run": True
            }
        )

        assert response.status_code == 422  # Validation error

    def test_bootstrap_invalid_confidence(self, client):
        """Test validation confidence hors limites"""
        # confidence > 1.0
        response = client.post(
            "/api/canonicalization/bootstrap",
            json={
                "min_confidence": 1.5,  # Invalide
                "dry_run": True
            }
        )

        assert response.status_code == 422  # Validation error

    def test_bootstrap_progress_endpoint(self, client):
        """Test endpoint progression bootstrap"""
        # Démarrer un bootstrap en arrière-plan
        bootstrap_response = client.post(
            "/api/canonicalization/bootstrap",
            json={"dry_run": True}
        )
        assert bootstrap_response.status_code == 200

        # Récupérer la progression (peut être None si terminé très vite)
        progress_response = client.get("/api/canonicalization/bootstrap/progress")
        assert progress_response.status_code == 200

        # La réponse peut être null si aucun bootstrap en cours
        data = progress_response.json()
        if data is not None:
            assert "status" in data
            assert "processed" in data
            assert "total" in data
            assert "promoted" in data
            assert "started_at" in data

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

        # L'estimation doit être cohérente
        assert isinstance(data["qualified_candidates"], int)
        assert isinstance(data["by_entity_type"], dict)
        assert isinstance(data["estimated_duration_seconds"], (int, float))

    def test_bootstrap_openapi_documentation(self, client):
        """Test que les endpoints bootstrap sont accessibles"""
        # Le projet utilise openapi.json custom, on vérifie que les endpoints fonctionnent

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

    def test_bootstrap_response_time_acceptable(self, client):
        """Test que le bootstrap répond en temps raisonnable (même vide)"""
        import time

        start = time.time()
        response = client.post(
            "/api/canonicalization/bootstrap",
            json={"dry_run": True}
        )
        duration = time.time() - start

        assert response.status_code == 200
        # Même vide, doit répondre en < 1 seconde
        assert duration < 1.0

    def test_bootstrap_handles_concurrent_requests(self, client):
        """Test gestion de requêtes concurrentes"""
        import concurrent.futures

        def make_bootstrap_request():
            return client.post(
                "/api/canonicalization/bootstrap",
                json={"dry_run": True}
            )

        # Envoyer 3 requêtes en parallèle
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(make_bootstrap_request) for _ in range(3)]
            responses = [f.result() for f in futures]

        # Toutes doivent réussir
        assert all(r.status_code == 200 for r in responses)

    def test_bootstrap_with_authentication_context(self, client):
        """Test bootstrap avec contexte utilisateur multi-tenant"""
        # Simuler requête avec header X-User-ID
        response = client.post(
            "/api/canonicalization/bootstrap",
            json={
                "dry_run": True
            },
            headers={"X-User-ID": "user_test_bootstrap"}
        )

        assert response.status_code == 200

    def test_bootstrap_dry_run_no_side_effects(self, client):
        """Test que dry_run=True ne modifie rien"""
        # Bootstrap en dry_run
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

        # Refaire le même bootstrap - doit donner le même résultat
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

        # Les résultats doivent être identiques (aucune modification)
        assert result1["total_candidates"] == result2["total_candidates"]
        assert result1["promoted_seeds"] == result2["promoted_seeds"]


class TestBootstrapPhase3Integration:
    """
    Tests préparatoires pour Phase 3 (Extraction Auto)
    Ces tests documentent le comportement attendu une fois Phase 3 implémentée
    """

    def test_bootstrap_with_phase3_candidates_placeholder(self, client):
        """
        [PLACEHOLDER] Test bootstrap avec vraies candidates Phase 3

        Une fois Phase 3 implémentée, ce test devra:
        1. Insérer documents de test dans le système
        2. Attendre extraction automatique des candidates
        3. Vérifier que le bootstrap promeut les candidates fréquentes
        4. Valider les entités seeds créées dans le KG
        """
        # Pour l'instant, juste vérifier que l'endpoint fonctionne
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

        # TODO Phase 3: Remplacer par assertions sur vraies candidates

    def test_bootstrap_performance_placeholder(self, client):
        """
        [PLACEHOLDER] Test performance: Bootstrap 20+ entities <5min

        Critère Phase 0: Bootstrap de 20+ seed entities en <5min

        Une fois Phase 3 implémentée, ce test devra:
        1. Créer 100+ candidates de test avec occurrences/confidence variées
        2. Lancer bootstrap avec seuils permettant 20+ promotions
        3. Mesurer le temps d'exécution
        4. Valider durée < 5min (300s)
        """
        import time

        start = time.time()

        response = client.post(
            "/api/canonicalization/bootstrap",
            json={
                "min_occurrences": 10,
                "min_confidence": 0.8,
                "dry_run": True
            }
        )

        duration = time.time() - start

        assert response.status_code == 200
        data = response.json()

        # Actuellement très rapide car vide
        assert duration < 1.0

        # TODO Phase 3: Valider duration < 300s avec 20+ entités réelles
        # assert data["promoted_seeds"] >= 20
        # assert duration < 300.0
