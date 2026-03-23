"""API endpoint pour les resultats de benchmark."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/benchmarks", tags=["benchmarks"])

RESULTS_DIR = Path("data/benchmark/results")
# Fallback paths
RESULTS_DIR_ALT = Path("/data/benchmark/results")
RESULTS_DIR_LOCAL = Path("benchmark/results")


def _get_results_dir() -> Path:
    for d in [RESULTS_DIR, RESULTS_DIR_ALT, RESULTS_DIR_LOCAL]:
        if d.exists():
            return d
    return RESULTS_DIR


@router.get("")
async def get_benchmark_runs() -> dict[str, Any]:
    """Liste les runs de benchmark disponibles avec leurs scores."""
    results_dir = _get_results_dir()

    if not results_dir.exists():
        return {"runs": []}

    runs = []
    # Chercher les sous-dossiers (YYYYMMDD_HHMMSS ou YYYYMMDD_label)
    run_dirs = sorted(
        [d for d in results_dir.iterdir() if d.is_dir() and d.name[:8].isdigit()],
        reverse=True,
    )

    for run_dir in run_dirs[:5]:
        judge_files = sorted(run_dir.glob("judge_*.json"))
        if not judge_files:
            continue

        tasks = []
        for jf in judge_files:
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
                # Parse filename: judge_osmosis_T1_kg.json
                parts = jf.stem.replace("judge_", "").split("_")
                task_match = next((p for p in parts if p.startswith("T") and len(p) == 2), None)
                source = parts[-1] if parts[-1] in ("kg", "human") else "kg"
                system = "_".join(parts[:parts.index(task_match)]) if task_match and task_match in parts else "unknown"

                tasks.append({
                    "task": task_match or data.get("metadata", {}).get("task", "?"),
                    "source": source,
                    "system": system,
                    "scores": data.get("scores", {}),
                    "metadata": data.get("metadata", {}),
                    "judgments_count": len(data.get("judgments", [])),
                })
            except Exception as e:
                logger.warning(f"Error reading {jf}: {e}")

        if tasks:
            runs.append({"timestamp": run_dir.name, "tasks": tasks})

    return {"runs": runs}
