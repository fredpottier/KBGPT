from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
import sys
from types import ModuleType

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
