from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if SRC_DIR.exists() and str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
from knowbase.common.sap.solutions_dict import SAP_SOLUTIONS

__all__ = ["SAP_SOLUTIONS"]

