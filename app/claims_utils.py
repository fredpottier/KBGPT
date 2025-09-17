from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
candidate_dirs = [ROOT / "src", ROOT.parent / "src"]
for candidate in candidate_dirs:
    if candidate.exists() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))
from knowbase.common.sap.claims import *  # noqa: F401,F403

