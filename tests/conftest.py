from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
import sys
from types import ModuleType
from typing import Dict

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


@dataclass
class RuntimeEnv:
    """Container providing access to reloaded config modules for tests."""

    data_dir: Path
    paths: ModuleType
    settings_module: ModuleType


@pytest.fixture
def runtime_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> RuntimeEnv:
    """Reload configuration modules against an isolated data directory."""

    data_dir = tmp_path / "data"
    monkeypatch.setenv("KNOWBASE_DATA_DIR", str(data_dir))

    paths_module = importlib.import_module("knowbase.config.paths")
    paths_module = importlib.reload(paths_module)

    settings_module = importlib.import_module("knowbase.config.settings")
    settings_module = importlib.reload(settings_module)
    settings_module.get_settings.cache_clear()

    yield RuntimeEnv(
        data_dir=data_dir,
        paths=paths_module,
        settings_module=settings_module,
    )

    settings_module.get_settings.cache_clear()


# ========================================
# Fixtures JWT pour tests avec authentification
# ========================================

@pytest.fixture
def jwt_admin_token() -> str:
    """Génère un token JWT valide pour un admin."""
    from knowbase.api.services.auth_service import get_auth_service

    auth_service = get_auth_service()
    token = auth_service.generate_access_token(
        user_id="admin-test-id",
        email="admin@test.com",
        role="admin",
        tenant_id="test-tenant"
    )
    return token


@pytest.fixture
def jwt_editor_token() -> str:
    """Génère un token JWT valide pour un editor."""
    from knowbase.api.services.auth_service import get_auth_service

    auth_service = get_auth_service()
    token = auth_service.generate_access_token(
        user_id="editor-test-id",
        email="editor@test.com",
        role="editor",
        tenant_id="test-tenant"
    )
    return token


@pytest.fixture
def jwt_viewer_token() -> str:
    """Génère un token JWT valide pour un viewer."""
    from knowbase.api.services.auth_service import get_auth_service

    auth_service = get_auth_service()
    token = auth_service.generate_access_token(
        user_id="viewer-test-id",
        email="viewer@test.com",
        role="viewer",
        tenant_id="test-tenant"
    )
    return token


@pytest.fixture
def admin_headers(jwt_admin_token: str) -> Dict[str, str]:
    """Headers HTTP avec JWT admin valide."""
    return {
        "Authorization": f"Bearer {jwt_admin_token}",
        "Content-Type": "application/json"
    }


@pytest.fixture
def editor_headers(jwt_editor_token: str) -> Dict[str, str]:
    """Headers HTTP avec JWT editor valide."""
    return {
        "Authorization": f"Bearer {jwt_editor_token}",
        "Content-Type": "application/json"
    }


@pytest.fixture
def viewer_headers(jwt_viewer_token: str) -> Dict[str, str]:
    """Headers HTTP avec JWT viewer valide."""
    return {
        "Authorization": f"Bearer {jwt_viewer_token}",
        "Content-Type": "application/json"
    }
