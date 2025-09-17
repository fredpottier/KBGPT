from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if SRC_DIR.exists() and str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
from knowbase.common.clients import (
    ensure_qdrant_collection,
    get_openai_client,
    get_qdrant_client,
    get_sentence_transformer,
)

__all__ = [
    "ensure_qdrant_collection",
    "get_openai_client",
    "get_qdrant_client",
    "get_sentence_transformer",
]
