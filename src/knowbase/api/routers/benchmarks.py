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
        # Primary judge files (not .claude.json)
        judge_files = sorted(
            f for f in run_dir.glob("judge_*.json")
            if ".claude." not in f.name
        )
        if not judge_files:
            continue

        # Secondary judge files (.claude.json) for cross-validation
        claude_files = {f.name.replace(".claude.json", ".json"): f
                        for f in run_dir.glob("judge_*.claude.json")}

        tasks = []
        for jf in judge_files:
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
                parts = jf.stem.replace("judge_", "").split("_")
                task_match = next((p for p in parts if p.startswith("T") and len(p) == 2), None)
                source = parts[-1] if parts[-1] in ("kg", "human") else "kg"
                system = "_".join(parts[:parts.index(task_match)]) if task_match and task_match in parts else "unknown"

                scores = data.get("scores", {})

                # Cross-validation : comparer avec le juge Claude si disponible
                divergences: dict[str, Any] = {}
                claude_file = claude_files.get(jf.name)
                if claude_file and claude_file.exists():
                    try:
                        claude_data = json.loads(claude_file.read_text(encoding="utf-8"))
                        claude_scores = claude_data.get("scores", {})
                        for metric, value in scores.items():
                            if metric == "total_evaluated" or not isinstance(value, (int, float)):
                                continue
                            claude_val = claude_scores.get(metric)
                            if isinstance(claude_val, (int, float)):
                                delta = abs(value - claude_val)
                                if delta > 0.15:  # Seuil de divergence significative
                                    divergences[metric] = {
                                        "primary": round(value, 3),
                                        "secondary": round(claude_val, 3),
                                        "delta": round(delta, 3),
                                        "secondary_judge": claude_data.get("metadata", {}).get("judge_model", "claude"),
                                    }
                    except Exception:
                        pass

                task_entry: dict[str, Any] = {
                    "task": task_match or data.get("metadata", {}).get("task", "?"),
                    "source": source,
                    "system": system,
                    "scores": scores,
                    "metadata": data.get("metadata", {}),
                    "judgments_count": len(data.get("judgments", [])),
                }
                if divergences:
                    task_entry["divergences"] = divergences

                tasks.append(task_entry)
            except Exception as e:
                logger.warning(f"Error reading {jf}: {e}")

        if tasks:
            runs.append({"timestamp": run_dir.name, "tasks": tasks})

    return {"runs": runs}
