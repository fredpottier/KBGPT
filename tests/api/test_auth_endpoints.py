"""
Tests E2E pour les endpoints d'authentification.

Phase 0 - Security Hardening
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from knowbase.api.main import create_app
from knowbase.db.base import Base
from knowbase.db import get_db
from knowbase.db.models import User
from knowbase.api.services.auth_service import get_auth_service


# Database de test en mémoire
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def test_db():
    """Fixture pour database de test."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(test_db):
    """Fixture TestClient FastAPI."""
    app = create_app()

    # Override get_db dependency
    def override_get_db():
        try:
            db = TestingSessionLocal()
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c


@pytest.fixture
def test_user(test_db):
    """Crée un utilisateur de test."""
    db = TestingSessionLocal()
    auth_service = get_auth_service()

    user = User(
        email="testuser@example.com",
        password_hash=auth_service.hash_password("TestPassword123!"),
        full_name="Test User",
        role="editor",
        tenant_id="tenant-test",
        is_active=True
    )

    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()

    return user


@pytest.fixture
def test_admin(test_db):
    """Crée un admin de test."""
    db = TestingSessionLocal()
    auth_service = get_auth_service()

    admin = User(
        email="admin@example.com",
        password_hash=auth_service.hash_password("AdminPass123!"),
        full_name="Admin User",
        role="admin",
        tenant_id="tenant-test",
        is_active=True
    )

    db.add(admin)
    db.commit()
    db.refresh(admin)
    db.close()

    return admin


def test_login_success(client, test_user):
    """Test login réussi."""
    response = client.post(
        "/api/auth/login",
        json={
            "email": "testuser@example.com",
            "password": "TestPassword123!"
        }
    )

    assert response.status_code == 200
    data = response.json()

    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 3600


def test_login_invalid_email(client):
    """Test login avec email inexistant."""
    response = client.post(
        "/api/auth/login",
        json={
            "email": "nonexistent@example.com",
            "password": "SomePassword123!"
        }
    )

    assert response.status_code == 401
    assert "invalide" in response.json()["detail"].lower()


def test_login_invalid_password(client, test_user):
    """Test login avec mauvais mot de passe."""
    response = client.post(
        "/api/auth/login",
        json={
            "email": "testuser@example.com",
            "password": "WrongPassword!"
        }
    )

    assert response.status_code == 401
    assert "invalide" in response.json()["detail"].lower()


def test_login_inactive_user(client, test_db):
    """Test login avec utilisateur désactivé."""
    db = TestingSessionLocal()
    auth_service = get_auth_service()

    inactive_user = User(
        email="inactive@example.com",
        password_hash=auth_service.hash_password("Password123!"),
        full_name="Inactive User",
        role="viewer",
        tenant_id="tenant-test",
        is_active=False  # Désactivé
    )

    db.add(inactive_user)
    db.commit()
    db.close()

    response = client.post(
        "/api/auth/login",
        json={
            "email": "inactive@example.com",
            "password": "Password123!"
        }
    )

    assert response.status_code == 401
    assert "désactivé" in response.json()["detail"].lower()


def test_refresh_token_success(client, test_user):
    """Test refresh token réussi."""
    # D'abord login
    login_response = client.post(
        "/api/auth/login",
        json={
            "email": "testuser@example.com",
            "password": "TestPassword123!"
        }
    )

    refresh_token = login_response.json()["refresh_token"]

    # Puis refresh
    response = client.post(
        "/api/auth/refresh",
        json={"refresh_token": refresh_token}
    )

    assert response.status_code == 200
    data = response.json()

    assert "access_token" in data
    assert "refresh_token" in data
    # Note: Si générés dans la même seconde, les tokens peuvent être identiques (claims identiques)


def test_refresh_token_invalid(client):
    """Test refresh avec token invalide."""
    response = client.post(
        "/api/auth/refresh",
        json={"refresh_token": "invalid.token.here"}
    )

    assert response.status_code == 401


def test_get_current_user_me(client, test_user):
    """Test GET /auth/me avec token valide."""
    # Login
    login_response = client.post(
        "/api/auth/login",
        json={
            "email": "testuser@example.com",
            "password": "TestPassword123!"
        }
    )

    access_token = login_response.json()["access_token"]

    # Get /me
    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {access_token}"}
    )

    assert response.status_code == 200
    data = response.json()

    assert data["email"] == "testuser@example.com"
    assert data["role"] == "editor"
    assert data["tenant_id"] == "tenant-test"


def test_get_current_user_me_without_token(client):
    """Test GET /auth/me sans token."""
    response = client.get("/api/auth/me")

    assert response.status_code == 403  # FastAPI HTTPBearer renvoie 403


def test_get_current_user_me_invalid_token(client):
    """Test GET /auth/me avec token invalide."""
    response = client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer invalid.token"}
    )

    assert response.status_code == 401


def test_register_success(client):
    """Test création utilisateur."""
    response = client.post(
        "/api/auth/register",
        json={
            "email": "newuser@example.com",
            "password": "NewPassword123!",
            "full_name": "New User",
            "role": "viewer",
            "tenant_id": "tenant-test"
        }
    )

    assert response.status_code == 201
    data = response.json()

    assert data["email"] == "newuser@example.com"
    assert data["role"] == "viewer"
    assert "password" not in data
    assert "password_hash" not in data


def test_register_duplicate_email(client, test_user):
    """Test création utilisateur avec email existant."""
    response = client.post(
        "/api/auth/register",
        json={
            "email": "testuser@example.com",  # Existe déjà
            "password": "Password123!",
            "full_name": "Duplicate User",
            "role": "viewer",
            "tenant_id": "tenant-test"
        }
    )

    assert response.status_code == 400
    assert "déjà utilisé" in response.json()["detail"].lower()


def test_register_weak_password(client):
    """Test création utilisateur avec mot de passe faible."""
    response = client.post(
        "/api/auth/register",
        json={
            "email": "weakpass@example.com",
            "password": "weak",  # Trop court
            "full_name": "Weak Pass User",
            "role": "viewer",
            "tenant_id": "tenant-test"
        }
    )

    assert response.status_code == 422  # Validation Pydantic


def test_login_updates_last_login(client, test_user):
    """Test que le login met à jour last_login_at."""
    db = TestingSessionLocal()

    # Vérifier last_login_at avant
    user_before = db.query(User).filter(User.email == "testuser@example.com").first()
    last_login_before = user_before.last_login_at

    # Login
    client.post(
        "/api/auth/login",
        json={
            "email": "testuser@example.com",
            "password": "TestPassword123!"
        }
    )

    # Vérifier last_login_at après
    db.expire_all()  # Force refresh depuis DB
    user_after = db.query(User).filter(User.email == "testuser@example.com").first()
    last_login_after = user_after.last_login_at

    assert last_login_after is not None
    if last_login_before:
        assert last_login_after > last_login_before

    db.close()


def test_full_auth_flow(client):
    """Test complet : register → login → me → refresh."""
    # 1. Register
    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "flowtest@example.com",
            "password": "FlowPassword123!",
            "full_name": "Flow Test User",
            "role": "editor",
            "tenant_id": "tenant-flow"
        }
    )
    assert register_response.status_code == 201

    # 2. Login
    login_response = client.post(
        "/api/auth/login",
        json={
            "email": "flowtest@example.com",
            "password": "FlowPassword123!"
        }
    )
    assert login_response.status_code == 200
    access_token = login_response.json()["access_token"]
    refresh_token = login_response.json()["refresh_token"]

    # 3. Get /me
    me_response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {access_token}"}
    )
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "flowtest@example.com"

    # 4. Refresh
    refresh_response = client.post(
        "/api/auth/refresh",
        json={"refresh_token": refresh_token}
    )
    assert refresh_response.status_code == 200
    new_access_token = refresh_response.json()["access_token"]

    # 5. Get /me avec nouveau token
    me_response2 = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {new_access_token}"}
    )
    assert me_response2.status_code == 200
