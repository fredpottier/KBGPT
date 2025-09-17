from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC_DIR = ROOT / "src"
PARENT_SRC_DIR = ROOT.parent / "src"
for candidate in (SRC_DIR, PARENT_SRC_DIR):
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))
from knowbase.common.logging import setup_logging

__all__ = ["setup_logging"]

