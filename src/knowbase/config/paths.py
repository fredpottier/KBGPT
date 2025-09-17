from __future__ import annotations

from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = PROJECT_ROOT / "src"
CONFIG_DIR = SRC_DIR / "knowbase" / "config"
COMMON_DIR = SRC_DIR / "knowbase" / "common"
PUBLIC_FILES_DIR = PROJECT_ROOT / "public_files"

DOCS_IN_DIR = PROJECT_ROOT / "docs_in"
DOCS_DONE_DIR = PROJECT_ROOT / "docs_done"
LOGS_DIR = PROJECT_ROOT / "logs"
MODELS_DIR = PROJECT_ROOT / "models"
STATUS_DIR = PROJECT_ROOT / "status"
PRESENTATIONS_DIR = PUBLIC_FILES_DIR / "presentations"
SLIDES_DIR = PUBLIC_FILES_DIR / "slides"
THUMBNAILS_DIR = PUBLIC_FILES_DIR / "thumbnails"


def ensure_directories(paths: Iterable[Path] | None = None) -> None:
    """Ensure the given directories exist."""
    targets = list(paths) if paths is not None else [
        DOCS_IN_DIR,
        DOCS_DONE_DIR,
        LOGS_DIR,
        MODELS_DIR,
        STATUS_DIR,
        PRESENTATIONS_DIR,
        SLIDES_DIR,
        THUMBNAILS_DIR,
    ]
    for directory in targets:
        directory.mkdir(parents=True, exist_ok=True)

