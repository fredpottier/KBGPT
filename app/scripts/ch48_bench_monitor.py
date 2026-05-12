"""CH-48 — Monitoring qualité bench live.

Affiche périodiquement (toutes 30s) :
  - Progression du job (Redis state)
  - Taux ANSWER / ABSTAIN / réponses vides en cours
  - Distribution latences par tranche
  - Headers rate-limit Together AI restants
  - Erreurs récentes dans les logs

Émet UNE LIGNE par tick → compatible Monitor.
"""
from __future__ import annotations
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import redis as _redis
import requests


REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
TOGETHER_KEY = os.getenv("TOGETHER_API_KEY", "")
RESULTS_DIR = Path("/app/data/benchmark/results")


def get_bench_state(rds, kind: str = "robustness") -> dict:
    """Lit l'état d'un bench depuis Redis (clé osmose:benchmark:{kind}:state)."""
    raw = rds.get(f"osmose:benchmark:{kind}:state")
    if raw:
        try:
            return json.loads(raw)
        except Exception:
            pass
    return {}


def find_latest_partial_result(tag: str) -> Path | None:
    """Trouve le fichier .json de résultat partiel le plus récent pour le tag."""
    if not RESULTS_DIR.exists():
        return None
    candidates = sorted(
        [p for p in RESULTS_DIR.glob("*.json") if tag in p.name],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def quick_analyze(path: Path) -> dict:
    """Lit un fichier de résultat partiel et compte ANSWER/ABSTAIN/empty."""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    samples = d.get("per_sample") or d.get("results") or []
    n = len(samples)
    if n == 0:
        return {"n": 0}
    answer = sum(1 for s in samples if s.get("decision") == "ANSWER")
    abstain = sum(1 for s in samples if s.get("decision") == "ABSTAIN")
    empty = sum(1 for s in samples if not (s.get("answer") or "").strip())
    walls = [s.get("wall_ms", 0) for s in samples if s.get("wall_ms")]
    mean_wall = sum(walls) // len(walls) if walls else 0
    return {
        "n": n, "answer": answer, "abstain": abstain, "empty": empty,
        "mean_wall_ms": mean_wall,
    }


def check_rate_limit() -> dict:
    """Probe Together AI pour récupérer les headers rate-limit actuels."""
    if not TOGETHER_KEY:
        return {}
    try:
        r = requests.post(
            "https://api.together.xyz/v1/chat/completions",
            headers={"Authorization": f"Bearer {TOGETHER_KEY}"},
            json={
                "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
                "messages": [{"role": "user", "content": "ok"}],
                "max_tokens": 1,
            },
            timeout=10,
        )
        return {
            "rpm_remaining": r.headers.get("x-ratelimit-remaining", "?"),
            "tpm_remaining": r.headers.get("x-ratelimit-remaining-tokens", "?"),
            "status": r.status_code,
        }
    except Exception as exc:
        return {"error": str(exc)[:60]}


def main():
    kind = sys.argv[1] if len(sys.argv) > 1 else "robustness"
    tag = sys.argv[2] if len(sys.argv) > 2 else "V4_CH48_LLAMA_TURBO_TOGETHER"
    interval = int(sys.argv[3]) if len(sys.argv) > 3 else 30

    rds = _redis.Redis.from_url(REDIS_URL, decode_responses=True)
    print(f"MON kind={kind} tag={tag} interval={interval}s start={datetime.now().strftime('%H:%M:%S')}", flush=True)

    last_n = 0
    while True:
        ts = datetime.now().strftime("%H:%M:%S")
        state = get_bench_state(rds, kind)
        status = state.get("status", "?")
        cur = state.get("progress", 0)
        total = state.get("total", 0)
        phase = state.get("phase", "?")

        latest = find_latest_partial_result(tag)
        ana = quick_analyze(latest) if latest else {}
        n = ana.get("n", 0)
        rl = check_rate_limit()
        rpm = rl.get("rpm_remaining", "?")
        tpm = rl.get("tpm_remaining", "?")

        delta_n = n - last_n
        last_n = n
        line = (
            f"{ts} status={status} phase={phase} prog={cur}/{total} "
            f"file_n={n} ans={ana.get('answer','?')} "
            f"abs={ana.get('abstain','?')} empty={ana.get('empty','?')} "
            f"mean_wall={ana.get('mean_wall_ms',0)}ms "
            f"rpm={rpm} tpm={tpm}"
        )
        if ana.get("empty", 0) > 5:
            line += " ⚠️ EMPTY_SPIKE"
        if ana.get("abstain", 0) > 0 and n > 0 and ana.get("abstain") / n > 0.30:
            line += " ⚠️ ABSTAIN_HIGH"
        print(line, flush=True)

        if status in {"completed", "failed", "error"}:
            print(f"FINAL status={status}", flush=True)
            break

        time.sleep(interval)


if __name__ == "__main__":
    main()
