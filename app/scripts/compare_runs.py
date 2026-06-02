"""Comparateur de runs bench a38 — protocole de non-régression multi-corpus.

Distingue deux causes d'écart de score :
  - RÉGRESSION CODE : même corpus, git_sha différents → toute baisse est imputable au code.
  - EFFET CORPUS    : même git_sha, corpus différents → l'écart est dû au corpus (attendu).

Usage :
  # non-régression sur un corpus (2 derniers runs du corpus, ou 2 fichiers explicites)
  python scripts/compare_runs.py --corpus aero_seats
  python scripts/compare_runs.py runA.json runB.json

  # carte typologie : même code, plusieurs corpus
  python scripts/compare_runs.py --typology --git-sha <sha>

Exit code 1 si régression code détectée (baisse > seuil sur un déterministe).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

RUNS_DIR = Path(__file__).resolve().parent.parent / "data" / "benchmark" / "a38_runtime_v6"
# Métriques suivies (les 2 premières sont déterministes = décisionnelles)
METRICS = [
    ("exact_id_recall_mean", "Précision réf. (exact_id)", True),
    ("abstention_correct_rate", "Honnêteté (abstention)", True),
    ("C1_mean", "Qualité jugée (C1, bruité)", False),
]
# Seuil de régression sur une métrique DÉTERMINISTE (pp). Le juge (C1) est bruité → pas de gate.
REGRESSION_THRESHOLD = 0.05


def _load(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_runs() -> List[Dict[str, Any]]:
    runs = []
    for f in RUNS_DIR.glob("run_*.json"):
        try:
            d = _load(f)
            d["_file"] = f.name
            runs.append(d)
        except Exception:
            pass
    runs.sort(key=lambda d: d.get("timestamp", ""))
    return runs


def _fmt(v: Optional[float]) -> str:
    return "--" if v is None else f"{v:.3f}"


def _compare_pair(old: Dict[str, Any], new: Dict[str, Any]) -> int:
    a, b = old.get("agg_50q", {}) or {}, new.get("agg_50q", {}) or {}
    same_corpus = old.get("corpus") == new.get("corpus")
    same_code = old.get("git_sha") == new.get("git_sha")

    print("=" * 72)
    print(f"OLD  corpus={old.get('corpus')!r:18} sha={old.get('git_sha')} ts={old.get('timestamp')}")
    print(f"NEW  corpus={new.get('corpus')!r:18} sha={new.get('git_sha')} ts={new.get('timestamp')}")
    if same_corpus and not same_code:
        mode = "NON-RÉGRESSION (même corpus, code différent) → baisse = RÉGRESSION CODE"
    elif same_code and not same_corpus:
        mode = "TYPOLOGIE (même code, corpus différent) → écart = EFFET CORPUS (attendu)"
    elif same_corpus and same_code:
        mode = "REPRODUCTIBILITÉ (même corpus + même code) → écart = variance/bruit"
    else:
        mode = "MIXTE (corpus ET code diffèrent) → non attribuable, éviter"
    print(f"Mode : {mode}")
    print("-" * 72)
    print(f"{'Métrique':32} {'OLD':>8} {'NEW':>8} {'Δ':>8}")

    regression = False
    for key, label, deterministic in METRICS:
        ov, nv = a.get(key), b.get(key)
        if ov is None and nv is None:
            continue
        delta = (nv - ov) if (ov is not None and nv is not None) else None
        flag = ""
        if delta is not None and deterministic and same_corpus and not same_code:
            if delta < -REGRESSION_THRESHOLD:
                flag = "  ⚠️ RÉGRESSION CODE"; regression = True
            elif delta > REGRESSION_THRESHOLD:
                flag = "  ✅ gain"
        dtxt = "--" if delta is None else f"{delta:+.3f}"
        print(f"{label:32} {_fmt(ov):>8} {_fmt(nv):>8} {dtxt:>8}{flag}")

    # Par type (déterministe exact_id) — utile pour localiser
    pa = a.get("exact_id_recall_per_type", {}) or {}
    pb = b.get("exact_id_recall_per_type", {}) or {}
    types = sorted(set(pa) | set(pb))
    if types:
        print("-" * 72); print("exact_id_recall par type :")
        for t in types:
            ov = (pa.get(t) or {}).get("mean"); nv = (pb.get(t) or {}).get("mean")
            delta = (nv - ov) if (ov is not None and nv is not None) else None
            dtxt = "--" if delta is None else f"{delta:+.3f}"
            warn = "  ⚠️" if (delta is not None and same_corpus and not same_code and delta < -REGRESSION_THRESHOLD) else ""
            print(f"  {t:22} {_fmt(ov):>8} {_fmt(nv):>8} {dtxt:>8}{warn}")
            if warn:
                regression = True

    print("=" * 72)
    if same_corpus and not same_code:
        print("VERDICT :", "❌ RÉGRESSION CODE détectée" if regression else "✅ Pas de régression code")
    return 1 if regression else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", type=Path, help="2 fichiers run à comparer (old new)")
    ap.add_argument("--corpus", help="Compare les 2 derniers runs de ce corpus")
    ap.add_argument("--typology", action="store_true", help="Carte typologie : dernier run par corpus")
    ap.add_argument("--git-sha", help="Filtrer la typologie sur ce git_sha")
    args = ap.parse_args()

    if args.typology:
        runs = _iter_runs()
        if args.git_sha:
            runs = [r for r in runs if r.get("git_sha") == args.git_sha]
        latest_by_corpus: Dict[str, Dict[str, Any]] = {}
        for r in runs:
            latest_by_corpus[r.get("corpus", "?")] = r
        print("=" * 72); print("CARTE TYPOLOGIE (dernier run par corpus)")
        print(f"{'Corpus':20} {'sha':10} {'exact_id':>9} {'abst':>7} {'C1':>7}")
        for c, r in sorted(latest_by_corpus.items()):
            a = r.get("agg_50q", {}) or {}
            print(f"{c:20} {str(r.get('git_sha'))[:10]:10} {_fmt(a.get('exact_id_recall_mean')):>9} "
                  f"{_fmt(a.get('abstention_correct_rate')):>7} {_fmt(a.get('C1_mean')):>7}")
        return 0

    if len(args.files) == 2:
        return _compare_pair(_load(args.files[0]), _load(args.files[1]))

    if args.corpus:
        runs = [r for r in _iter_runs() if r.get("corpus") == args.corpus]
        if len(runs) < 2:
            print(f"Besoin de ≥2 runs pour le corpus {args.corpus!r} (trouvés: {len(runs)})")
            return 2
        return _compare_pair(runs[-2], runs[-1])

    print("Préciser soit 2 fichiers, soit --corpus <nom>, soit --typology.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
