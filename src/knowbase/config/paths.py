from __future__ import annotations

import os
import shutil
import warnings
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = PROJECT_ROOT / "src"
CONFIG_DIR = PROJECT_ROOT / "config"  # Config files are at project root, not in src/
COMMON_DIR = SRC_DIR / "knowbase" / "common"
DATA_DIR = Path(os.getenv("KNOWBASE_DATA_DIR", PROJECT_ROOT / "data")).expanduser()
PUBLIC_FILES_DIR = DATA_DIR / "public"

DOCS_IN_DIR = DATA_DIR / "docs_in"
DOCS_DONE_DIR = DATA_DIR / "docs_done"
LOGS_DIR = DATA_DIR / "logs"
MODELS_DIR = DATA_DIR / "models"
STATUS_DIR = DATA_DIR / "status"
PRESENTATIONS_DIR = DOCS_DONE_DIR
SLIDES_DIR = PUBLIC_FILES_DIR / "slides"
THUMBNAILS_DIR = PUBLIC_FILES_DIR / "thumbnails"

LEGACY_DIRECTORIES: dict[Path, Path] = {
    PROJECT_ROOT / "docs_in": DOCS_IN_DIR,
    PROJECT_ROOT / "docs_done": DOCS_DONE_DIR,
    PROJECT_ROOT / "logs": LOGS_DIR,
    PROJECT_ROOT / "models": MODELS_DIR,
    PROJECT_ROOT / "status": STATUS_DIR,
    PROJECT_ROOT / "public_files" / "presentations": DOCS_DONE_DIR,
    PROJECT_ROOT / "public_files" / "slides": SLIDES_DIR,
    PROJECT_ROOT / "public_files" / "thumbnails": THUMBNAILS_DIR,
    PROJECT_ROOT / "src" / "docs_in": DOCS_IN_DIR,
    PROJECT_ROOT / "src" / "docs_done": DOCS_DONE_DIR,
    PROJECT_ROOT / "src" / "logs": LOGS_DIR,
    PROJECT_ROOT / "src" / "models": MODELS_DIR,
    PROJECT_ROOT / "src" / "status": STATUS_DIR,
}


def _migrate_directory_contents(source: Path, destination: Path) -> None:
    """Move legacy directory content into the new runtime location if needed."""

    if not source.exists() or source.is_symlink():
        return

    if source.resolve() == destination.resolve():
        return

    try:
        for entry in source.iterdir():
            target = destination / entry.name
            if target.exists():
                warnings.warn(
                    (
                        "Legacy runtime directory %s contains %s but the target %s already exists. "
                        "Please consolidate the files manually."
                    )
                    % (source, entry.name, target),
                    stacklevel=2,
                )
                continue
            shutil.move(str(entry), str(target))
        try:
            source.rmdir()
        except OSError:
            warnings.warn(
                f"Legacy runtime directory {source} could not be cleaned up automatically.",
                stacklevel=2,
            )
        else:
            warnings.warn(
                f"Legacy runtime directory {source} was migrated to {destination}.",
                stacklevel=2,
            )
    except Exception as exc:  # pragma: no cover - defensive best effort
        warnings.warn(
            f"Failed to migrate legacy directory {source} to {destination}: {exc}",
            stacklevel=2,
        )


def _ensure_legacy_redirect(legacy: Path, new_target: Path) -> None:
    """Create a compatibility symlink or stub for a legacy runtime directory."""

    if legacy == new_target:
        return

    if legacy.is_symlink():
        try:
            if legacy.resolve() != new_target.resolve():
                warnings.warn(
                    f"Legacy path {legacy} points to {legacy.resolve()} instead of {new_target}.",
                    stacklevel=2,
                )
        except OSError:
            warnings.warn(
                f"Unable to resolve legacy symlink {legacy}; please recreate it to point to {new_target}.",
                stacklevel=2,
            )
        return

    if legacy.exists():
        _migrate_directory_contents(legacy, new_target)
        if legacy.exists():
            warnings.warn(
                f"Legacy runtime path {legacy} is deprecated; please switch to {new_target}.",
                stacklevel=2,
            )
            return

    if legacy.exists():
        return

    try:
        legacy.parent.mkdir(parents=True, exist_ok=True)
        try:
            # Use relative path for Docker compatibility
            if str(new_target).startswith(str(DATA_DIR)):
                # For paths under DATA_DIR, create relative symlinks from legacy location
                relative_target = os.path.relpath(new_target, legacy.parent)
                legacy.symlink_to(relative_target, target_is_directory=True)
            else:
                legacy.symlink_to(new_target, target_is_directory=True)
        except OSError as exc:
            if os.name == "nt":  # pragma: no cover - Windows fallback
                try:
                    legacy.mkdir(parents=True, exist_ok=True)
                    marker = legacy / "README.txt"
                    if not marker.exists():
                        marker.write_text(
                            (
                                "This directory is deprecated. Runtime data now lives in "
                                f"{new_target}. Update your configuration to point to the new path."
                            ),
                            encoding="utf-8",
                        )
                except OSError as nested_exc:
                    warnings.warn(
                        f"Could not create compatibility stub for {legacy}: {nested_exc}",
                        stacklevel=2,
                    )
                else:
                    warnings.warn(
                        f"Created deprecated stub at {legacy}; please migrate to {new_target}.",
                        stacklevel=2,
                    )
            else:
                warnings.warn(
                    f"Could not create symlink from {legacy} to {new_target}: {exc}",
                    stacklevel=2,
                )
        else:
            warnings.warn(
                f"Created compatibility redirect from legacy path {legacy} to {new_target}.",
                stacklevel=2,
            )
    except OSError as exc:
        warnings.warn(
            f"Could not prepare legacy redirect for {legacy}: {exc}",
            stacklevel=2,
        )


def ensure_directories(paths: Iterable[Path] | None = None) -> None:
    """Ensure runtime directories exist and provide compatibility with legacy paths."""

    default_targets = [
        DATA_DIR,
        DOCS_IN_DIR,
        DOCS_DONE_DIR,
        LOGS_DIR,
        MODELS_DIR,
        STATUS_DIR,
        PUBLIC_FILES_DIR,
        PRESENTATIONS_DIR,
        SLIDES_DIR,
        THUMBNAILS_DIR,
    ]
    targets = list(paths) if paths is not None else default_targets
    for directory in targets:
        directory.mkdir(parents=True, exist_ok=True)

    # Skip legacy migration in Docker environment
    if not os.getenv("KNOWBASE_DATA_DIR"):
        for legacy_path, new_path in LEGACY_DIRECTORIES.items():
            _ensure_legacy_redirect(legacy_path, new_path)

