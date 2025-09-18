from pathlib import Path

from knowbase.config.settings import get_settings


_settings = get_settings()


def get_docs_in() -> Path:
    return _settings.docs_in_dir


def get_docs_done() -> Path:
    return _settings.docs_done_dir


def get_slides_png() -> Path:
    return _settings.slides_dir


def get_status_dir() -> Path:
    return _settings.status_dir


def get_logs_dir() -> Path:
    return _settings.logs_dir


def get_cache_models() -> Path:
    return _settings.models_dir
