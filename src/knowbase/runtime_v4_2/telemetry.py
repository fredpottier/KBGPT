"""Telemetry Runtime V4.2 — append-only JSONL traces (Cap5).

Persiste 1 ligne par question dans `data/runtime_v4_2/traces/<YYYY-MM-DD>.jsonl`.
Fichier rotated quotidiennement, jamais réécrit. Lecture offline pour :
  - distribution layer (cible 60-70 / 20-30 / 5-10)
  - false_abstain rate (Amendment 1)
  - latence p50/p95 par layer
  - coût par question
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from knowbase.runtime_v4_2.models import QuestionTrace

logger = logging.getLogger(__name__)


_DEFAULT_DIR = Path("/app/data/runtime_v4_2/traces")
_LOCK = threading.Lock()


def _trace_dir() -> Path:
    override = os.getenv("RUNTIME_V4_2_TRACE_DIR")
    base = Path(override) if override else _DEFAULT_DIR
    base.mkdir(parents=True, exist_ok=True)
    return base


def _today_path() -> Path:
    today = dt.datetime.utcnow().strftime("%Y-%m-%d")
    return _trace_dir() / f"{today}.jsonl"


def make_question_id(question: str) -> str:
    """ID stable basé sur question + timestamp (microseconds)."""
    ts = dt.datetime.utcnow().isoformat()
    h = hashlib.sha1(f"{question}|{ts}".encode("utf-8")).hexdigest()[:12]
    return f"q_{h}"


def now_iso() -> str:
    return dt.datetime.utcnow().isoformat() + "Z"


def _serialize(obj: Any) -> Any:
    """Convertit dataclasses + enums en types JSON-serializables."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _serialize(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(x) for x in obj]
    if hasattr(obj, "value") and hasattr(obj, "name"):  # Enum
        return obj.value
    return obj


def append_trace(trace: QuestionTrace) -> None:
    """Append un trace en JSONL. Thread-safe via lock global.

    Fail-soft : ne lève jamais — si écriture impossible, log warning.
    """
    try:
        path = _today_path()
        payload = _serialize(trace)
        line = json.dumps(payload, ensure_ascii=False, default=str)
        with _LOCK:
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Telemetry append failed (non-blocking): {exc}")


def daily_aggregate(date: str | None = None) -> dict[str, Any]:
    """Agrégation quotidienne pour dashboard (utilisé par /health endpoint).

    Compte distribution layer, abstain categories, p50/p95 latence.
    """
    target = date or dt.datetime.utcnow().strftime("%Y-%m-%d")
    path = _trace_dir() / f"{target}.jsonl"
    if not path.exists():
        return {"date": target, "n_traces": 0}

    n = 0
    layer_counts: dict[str, int] = {}
    abstain_counts: dict[str, int] = {}
    latencies: list[int] = []
    errors = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                t = json.loads(line)
            except Exception:
                continue
            n += 1
            layer = t.get("layer_used") or "unknown"
            layer_counts[layer] = layer_counts.get(layer, 0) + 1
            ab = t.get("abstain_category")
            if ab:
                abstain_counts[ab] = abstain_counts.get(ab, 0) + 1
            if t.get("error"):
                errors += 1
            tot = (t.get("latency_breakdown_ms") or {}).get("total_ms")
            if isinstance(tot, (int, float)):
                latencies.append(int(tot))

    p50 = _percentile(latencies, 0.5)
    p95 = _percentile(latencies, 0.95)
    return {
        "date": target,
        "n_traces": n,
        "layer_distribution": layer_counts,
        "abstain_distribution": abstain_counts,
        "errors": errors,
        "latency_ms_p50": p50,
        "latency_ms_p95": p95,
        "false_abstain_rate": _safe_div(
            abstain_counts.get("misaligned_but_answerable", 0), n
        ),
    }


def _percentile(values: list[int], q: float) -> int | None:
    if not values:
        return None
    s = sorted(values)
    idx = int(round(q * (len(s) - 1)))
    return s[max(0, min(idx, len(s) - 1))]


def _safe_div(a: int, b: int) -> float:
    return round(a / b, 4) if b else 0.0
