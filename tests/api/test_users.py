from __future__ import annotations

import importlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_users(runtime_env, monkeypatch):
    """Crée une application FastAPI avec le router users pour les tests."""
    # Mock les dépendances pour éviter les initialisations lourdes
    dependencies = importlib.import_module("knowbase.api.dependencies")
    dependencies = importlib.reload(dependencies)

    mock_warm = Mock()
    monkeypatch.setattr(dependencies, "warm_clients", mock_warm)

    main = importlib.import_module("knowbase.api.main")
    main = importlib.reload(main)

    app = main.create_app()
    return app


@pytest.fixture
def client(app_with_users):
    """Client de test FastAPI."""
    return TestClient(app_with_users)


@pytest.fixture
def clean_users_file(runtime_env):
    """S'assure qu'on a un fichier users.json propre pour chaque test."""
    users_file = runtime_env.data_dir / "users.json"
    users_file.parent.mkdir(parents=True, exist_ok=True)

    # Créer un utilisateur par défaut
    default_users = [
        {
            "id": "default-user",
            "name": "Utilisateur par défaut",
            "email": None,
            "role": "user",
            "created_at": "2024-01-01T00:00:00",
            "last_active": "2024-01-01T00:00:00",
        }
    ]

    with open(users_file, "w", encoding="utf-8") as f:
        json.dump(default_users, f, ensure_ascii=False, indent=2)

    yield users_file

    # Cleanup après le test
    if users_file.exists():
        users_file.unlink()


class TestUsersAPI:
    """Tests pour les endpoints de gestion des utilisateurs."""

    def test_list_users_returns_default_user(self, client, clean_users_file):
        """Test GET /api/users/ - doit retourner l'utilisateur par défaut."""
        response = client.get("/api/users/")

        assert response.status_code == 200
        data = response.json()

        assert "users" in data
        assert "total" in data
        assert data["total"] == 1
        assert len(data["users"]) == 1

        default_user = data["users"][0]
        assert default_user["id"] == "default-user"
        assert default_user["name"] == "Utilisateur par défaut"
        assert default_user["role"] == "user"

    def test_get_user_by_id_existing(self, client, clean_users_file):
        """Test GET /api/users/{id} - utilisateur existant."""
        response = client.get("/api/users/default-user")

        assert response.status_code == 200
        data = response.json()

        assert data["id"] == "default-user"
        assert data["name"] == "Utilisateur par défaut"
        assert data["role"] == "user"

    def test_get_user_by_id_not_found(self, client, clean_users_file):
        """Test GET /api/users/{id} - utilisateur inexistant."""
        response = client.get("/api/users/inexistant")

        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert "inexistant" in data["detail"]

    def test_create_user_success(self, client, clean_users_file):
        """Test POST /api/users/ - création réussie."""
        user_data = {
            "name": "Test User",
            "email": "test@example.com",
            "role": "expert"
        }

        response = client.post("/api/users/", json=user_data)

        assert response.status_code == 201
        data = response.json()

        assert data["name"] == "Test User"
        assert data["email"] == "test@example.com"
        assert data["role"] == "expert"
        assert "id" in data
        assert "created_at" in data
        assert "last_active" in data

    def test_create_user_duplicate_name(self, client, clean_users_file):
        """Test POST /api/users/ - nom déjà existant."""
        user_data = {
            "name": "Utilisateur par défaut",  # Nom déjà pris
            "role": "admin"
        }

        response = client.post("/api/users/", json=user_data)

        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        assert "existe déjà" in data["detail"]

    def test_create_user_minimal_data(self, client, clean_users_file):
        """Test POST /api/users/ - données minimales (nom seulement)."""
        user_data = {"name": "Minimal User"}

        response = client.post("/api/users/", json=user_data)

        assert response.status_code == 201
        data = response.json()

        assert data["name"] == "Minimal User"
        assert data["email"] is None
        assert data["role"] == "user"  # Valeur par défaut

    def test_update_user_success(self, client, clean_users_file):
        """Test PUT /api/users/{id} - mise à jour réussie."""
        # D'abord créer un utilisateur
        create_response = client.post("/api/users/", json={"name": "Original Name"})
        user_id = create_response.json()["id"]

        # Puis le mettre à jour
        update_data = {
            "name": "Updated Name",
            "email": "updated@example.com",
            "role": "admin"
        }

        response = client.put(f"/api/users/{user_id}", json=update_data)

        assert response.status_code == 200
        data = response.json()

        assert data["name"] == "Updated Name"
        assert data["email"] == "updated@example.com"
        assert data["role"] == "admin"

    def test_update_user_not_found(self, client, clean_users_file):
        """Test PUT /api/users/{id} - utilisateur inexistant."""
        update_data = {"name": "New Name"}

        response = client.put("/api/users/inexistant", json=update_data)

        assert response.status_code == 404

    def test_update_user_partial(self, client, clean_users_file):
        """Test PUT /api/users/{id} - mise à jour partielle."""
        # Créer un utilisateur
        create_response = client.post("/api/users/", json={
            "name": "Original Name",
            "email": "original@example.com",
            "role": "expert"
        })
        user_id = create_response.json()["id"]

        # Mettre à jour seulement le nom
        update_data = {"name": "Only Name Updated"}

        response = client.put(f"/api/users/{user_id}", json=update_data)

        assert response.status_code == 200
        data = response.json()

        assert data["name"] == "Only Name Updated"
        assert data["email"] == "original@example.com"  # Inchangé
        assert data["role"] == "expert"  # Inchangé

    def test_delete_user_success(self, client, clean_users_file):
        """Test DELETE /api/users/{id} - suppression réussie."""
        # Créer un utilisateur
        create_response = client.post("/api/users/", json={"name": "To Delete"})
        user_id = create_response.json()["id"]

        # Le supprimer
        response = client.delete(f"/api/users/{user_id}")

        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert user_id in data["message"]

        # Vérifier qu'il n'existe plus
        get_response = client.get(f"/api/users/{user_id}")
        assert get_response.status_code == 404

    def test_delete_default_user_forbidden(self, client, clean_users_file):
        """Test DELETE /api/users/{id} - ne peut pas supprimer l'utilisateur par défaut."""
        response = client.delete("/api/users/default-user")

        assert response.status_code == 400
        data = response.json()
        assert "detail" in data
        assert "par défaut" in data["detail"]

    def test_delete_user_not_found(self, client, clean_users_file):
        """Test DELETE /api/users/{id} - utilisateur inexistant."""
        response = client.delete("/api/users/inexistant")

        assert response.status_code == 404

    def test_update_user_activity_success(self, client, clean_users_file):
        """Test POST /api/users/{id}/activity - mise à jour activité réussie."""
        response = client.post("/api/users/default-user/activity")

        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "Activité utilisateur mise à jour" in data["message"]

    def test_update_user_activity_not_found(self, client, clean_users_file):
        """Test POST /api/users/{id}/activity - utilisateur inexistant."""
        response = client.post("/api/users/inexistant/activity")

        assert response.status_code == 404

    def test_users_persistence_across_requests(self, client, clean_users_file):
        """Test que les utilisateurs sont persistés entre les requêtes."""
        # Créer un utilisateur
        create_data = {"name": "Persistent User", "role": "admin"}
        create_response = client.post("/api/users/", json=create_data)
        user_id = create_response.json()["id"]

        # Vérifier qu'il existe dans une nouvelle requête
        list_response = client.get("/api/users/")
        users = list_response.json()["users"]

        user_names = [u["name"] for u in users]
        assert "Persistent User" in user_names

        # Vérifier qu'on peut le récupérer par ID
        get_response = client.get(f"/api/users/{user_id}")
        assert get_response.status_code == 200
        assert get_response.json()["name"] == "Persistent User"

    def test_user_validation_empty_name(self, client, clean_users_file):
        """Test validation - nom vide refusé."""
        user_data = {"name": "", "role": "user"}

        response = client.post("/api/users/", json=user_data)

        assert response.status_code == 422  # Validation error

    def test_user_validation_invalid_role(self, client, clean_users_file):
        """Test validation - rôle invalide refusé."""
        user_data = {"name": "Test User", "role": "invalid_role"}

        response = client.post("/api/users/", json=user_data)

        assert response.status_code == 422  # Validation error