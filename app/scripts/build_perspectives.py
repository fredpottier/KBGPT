"""
Script CLI pour construire les Perspectives.

Usage (dans Docker):
    python scripts/build_perspectives.py
    python scripts/build_perspectives.py --skip-llm
    python scripts/build_perspectives.py --dry-run
    python scripts/build_perspectives.py --facet-weight 0.3 --embedding-weight 0.7
"""

import sys
sys.path.insert(0, "/app/src")

from knowbase.perspectives.orchestrator import main

if __name__ == "__main__":
    main()
