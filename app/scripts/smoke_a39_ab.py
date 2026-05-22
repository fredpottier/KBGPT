"""Smoke A/B A3.9 — 3 questions x {resolver OFF, resolver ON}.

Mesure delta coverage / claim count / latence pour le subject_resolver
isolé (post-fix dénormalisation b9161db).

NB : le toggle V6_SUBJECT_RESOLVER_ENABLED est lu au runtime par
Executor._get_subject_resolver(), donc on peut le forcer via env var
juste avant l'instanciation.

Usage:
    docker exec knowbase-app python scripts/smoke_a39_ab.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("smoke_a39_ab")


def run_one(question: str, resolver_enabled: bool) -> Dict[str, Any]:
    os.environ["V6_SUBJECT_RESOLVER_ENABLED"] = "1" if resolver_enabled else "0"
    # Re-import pour que Executor relise l'env (sinon Executor déjà construit
    # garde son self.subject_resolver_enabled). On force une nouvelle instance.
    from knowbase.runtime_a3.execute import Executor
    from knowbase.runtime_a3.orchestrator import Orchestrator

    # Construit un orchestrator avec un executor fresh (relit l'env)
    orch = Orchestrator(executor=Executor())

    t0 = time.perf_counter()
    try:
        result = orch.run(
            question=question,
            tenant_id="default",
            as_of_date=datetime.now(timezone.utc),
            response_mode="structured",
        )
        dt = time.perf_counter() - t0

        # Compter les claims trouvés via results des iterations
        # Schéma : Iteration.execute_output: ExecuteOutput { results: List[ToolResult] }
        # ToolResult { coverage_signal, claims: List[ClaimSummary] }
        n_claims = 0
        coverage_states: List[str] = []
        for it in result.iterations:
            for tr in (it.execute_output.results or []):
                if tr.coverage_signal:
                    coverage_states.append(tr.coverage_signal)
                if tr.claims:
                    n_claims += len(tr.claims)

        return {
            "ok": True,
            "duration_s": dt,
            "n_iterations": len(result.iterations),
            "n_claims_total": n_claims,
            "coverage_states": coverage_states,
            "answer_text_preview": (result.synthesize_output.answer_text or "")[:150],
            "terminated_reason": result.terminated_reason,
        }
    except Exception as exc:
        dt = time.perf_counter() - t0
        logger.exception("run failed")
        return {
            "ok": False,
            "duration_s": dt,
            "error": str(exc)[:200],
        }


def main():
    # 3 questions stratifiées : factual + comparison + multi_hop
    questions = [
        "Quelle transaction est utilisee pour la Labeling Workbench dans Global Label Management ?",
        "Quel role SAP est fourni pour le team lead dans le Payroll Control Center ?",
        "Quelles options de connectivite Azure sont supportees pour RISE with SAP ?",
    ]

    print("\n" + "=" * 70)
    print("SMOKE A3.9 A/B — 3 questions × {resolver OFF, resolver ON}")
    print("=" * 70)

    runs: Dict[str, List[Dict]] = {"off": [], "on": []}

    for label, enabled in [("off", False), ("on", True)]:
        print(f"\n--- Resolver {label.upper()} ---")
        for i, q in enumerate(questions, 1):
            r = run_one(q, enabled)
            runs[label].append({"question": q, **r})
            if r["ok"]:
                print(f"  [{i}] {r['duration_s']:.2f}s "
                      f"iter={r['n_iterations']} "
                      f"claims={r['n_claims_total']} "
                      f"cov={r['coverage_states']} "
                      f"term={r['terminated_reason']}")
                print(f"      ans={r['answer_text_preview']!r}")
            else:
                print(f"  [{i}] FAILED: {r.get('error')}")

    # Delta analysis
    print("\n" + "=" * 70)
    print("DELTA")
    print("=" * 70)
    for i, q in enumerate(questions):
        off = runs["off"][i]
        on = runs["on"][i]
        if off.get("ok") and on.get("ok"):
            d_claims = on["n_claims_total"] - off["n_claims_total"]
            d_dur = on["duration_s"] - off["duration_s"]
            print(f"Q{i+1}: claims off={off['n_claims_total']} → on={on['n_claims_total']} "
                  f"(Δ{d_claims:+d}) | latence Δ{d_dur:+.2f}s")
            print(f"     cov off={off['coverage_states']}")
            print(f"     cov on ={on['coverage_states']}")
        else:
            print(f"Q{i+1}: comparaison impossible (un des deux runs a échoué)")

    # Persist
    out_dir = Path("/app/data/benchmark/a39_smoke_ab")
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"smoke_{ts}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({"timestamp": ts, "runs": runs}, f, indent=2, default=str, ensure_ascii=False)
    print(f"\nDetails: {out_file}")


if __name__ == "__main__":
    main()
