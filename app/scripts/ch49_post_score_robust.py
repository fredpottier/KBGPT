"""CH-49 — Re-score post-hoc du bench Robust avec gold v5 (100% couverture).

Pour chaque sample Robust, calcule structured_metrics contre la reference gold v5 :
  - exact_match : ratio exact_identifiers présents dans la réponse
  - citation : ratio supporting_doc_ids cités via [doc=...] OU via doc_id apparaissant en clair
  - item_recall : ratio list_items_expected (texte) présents dans la réponse (token overlap)
  - structured_avg : moyenne des metrics applicables

Output : data/audit/ch49_post_score_v5_robust.json
"""
from __future__ import annotations
import json
import re
from collections import defaultdict
from pathlib import Path

GOLD_V5 = json.loads(Path("/app/benchmark/questions/gold_set_v5.json").read_text(encoding="utf-8"))
gv5_by_sid = {q["source_id"]: q for q in GOLD_V5}

CH48_RB = json.loads(Path("/app/data/benchmark/results/robustness_run_20260509_161844_V4_CH48_LLAMA_TURBO_TOGETHER.json").read_text(encoding="utf-8"))
ch46_paths = [
    Path("/app/data/benchmark/results/robustness_run_20260508_060359_V4_CH46_POSTOPT.json"),
    Path("/data/benchmark/results/robustness_run_20260508_060359_V4_CH46_POSTOPT.json"),
]
CH46_RB = json.loads(next(p for p in ch46_paths if p.exists()).read_text(encoding="utf-8"))


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower().strip())


def fuzzy_in(needle: str, haystack: str) -> bool:
    """needle est-il dans haystack avec tolérance basique (token overlap > 60%)?"""
    n = normalize(needle)
    h = normalize(haystack)
    if not n:
        return False
    if n in h:
        return True
    n_tokens = set(re.findall(r"\w+", n))
    if len(n_tokens) <= 2:
        return False
    h_tokens = set(re.findall(r"\w+", h))
    return len(n_tokens & h_tokens) / len(n_tokens) >= 0.6


def score_sample(answer: str, gold: dict) -> dict:
    """Calcule les structured_metrics pour 1 sample contre 1 gold v5 entry."""
    gt = gold.get("ground_truth", {})
    ans = answer or ""

    out = {"applicable": True}

    # exact_match : présence des exact_identifiers
    exact_ids = gt.get("exact_identifiers") or []
    if exact_ids:
        n_match = sum(1 for x in exact_ids if normalize(x) in normalize(ans))
        out["exact_match"] = {
            "n_matched": n_match,
            "n_expected": len(exact_ids),
            "score": n_match / len(exact_ids) if exact_ids else 0,
            "missing_ids": [x for x in exact_ids if normalize(x) not in normalize(ans)],
            "applicable": True,
        }
    else:
        out["exact_match"] = {"applicable": False}

    # citation : citation des supporting_doc_ids
    docs = gt.get("supporting_doc_ids") or []
    cited_via_marker = re.findall(r"\[doc=([^\]]+)\]", ans)
    cited_via_text = [d for d in docs if d and d in ans]
    cited_set = set(cited_via_marker) | set(cited_via_text)
    if docs:
        # On considère qu'un doc est cité si trouvé dans cited_set OU si une partie significative est dans ans
        n_cited = sum(1 for d in docs if d in cited_set or (d and d[:20] in ans))
        out["citation"] = {
            "n_cited": n_cited,
            "n_expected": len(docs),
            "citation_rate": n_cited / len(docs),
            "applicable": True,
        }
    else:
        out["citation"] = {"applicable": False}

    # item_recall : présence des list_items_expected
    items = gt.get("list_items_expected") or []
    if items:
        n_recall = sum(1 for it in items if fuzzy_in(it, ans))
        out["item_recall"] = {
            "n_matched": n_recall,
            "n_expected": len(items),
            "recall": n_recall / len(items),
            "applicable": True,
        }
    else:
        out["item_recall"] = {"applicable": False}

    # Aggregated avg (only on applicable metrics)
    scores = []
    if out["exact_match"].get("applicable"):
        scores.append(out["exact_match"]["score"])
    if out["citation"].get("applicable"):
        scores.append(out["citation"]["citation_rate"])
    if out["item_recall"].get("applicable"):
        scores.append(out["item_recall"]["recall"])
    out["structured_avg"] = sum(scores) / len(scores) if scores else 0.0
    out["n_metrics"] = len(scores)

    # Special handling for unanswerable questions
    if gt.get("answerability") == "unanswerable":
        # Detect abstain markers
        abstain_markers = ["pas trouvé", "not found", "non disponible", "not available", "n'a pas été trouvée", "no specific answer"]
        is_abstain = any(m in normalize(ans) for m in abstain_markers)
        out["abstain_correct"] = is_abstain
        if is_abstain:
            out["structured_avg"] = 1.0

    return out


def main():
    runs = {
        "CH-48": CH48_RB["per_sample"],
        "CH-46": CH46_RB["per_sample"],
    }

    results = {}
    for run_name, samples in runs.items():
        per_sample = []
        for s in samples:
            oid = s.get("original_id")
            if not oid or oid not in gv5_by_sid:
                continue  # impossible avec 100% couverture mais sécurité
            gold = gv5_by_sid[oid]
            answer = s.get("answer", "")
            scored = score_sample(answer, gold)
            per_sample.append({
                "original_id": oid,
                "primary_type": gold["primary_type"],
                "secondary_types": gold["secondary_types"],
                "flags": gold["flags"],
                "judge_score": (s.get("evaluation") or {}).get("score"),
                "scored": scored,
            })
        results[run_name] = per_sample

    # Aggrégation par primary_type pour chaque run
    print(f"\n=== STRUCTURED_AVG par primary_type (100% Robust × gold_v5) ===\n")
    print(f"{'primary_type':15s} | {'n':>3s} | {'CH-46':>8s} | {'CH-48':>8s} | {'Δ':>9s} | {'idéal-CH48':>10s}")
    print("-" * 75)

    by_type_overall = {}
    for run_name in ("CH-46", "CH-48"):
        by_type = defaultdict(list)
        for r in results[run_name]:
            by_type[r["primary_type"]].append(r["scored"]["structured_avg"])
        by_type_overall[run_name] = by_type

    all_types = sorted(set(by_type_overall["CH-48"].keys()) | set(by_type_overall["CH-46"].keys()))
    for t in all_types:
        n = len(by_type_overall["CH-48"].get(t, []))
        v46 = sum(by_type_overall["CH-46"].get(t, [])) / max(len(by_type_overall["CH-46"].get(t, [])), 1)
        v48 = sum(by_type_overall["CH-48"].get(t, [])) / max(len(by_type_overall["CH-48"].get(t, [])), 1)
        delta = v48 - v46
        dev = 1.0 - v48
        arrow = "↑" if delta > 0.02 else ("↓" if delta < -0.02 else "·")
        print(f"{t:15s} | {n:>3d} | {v46:>8.3f} | {v48:>8.3f} | {arrow}{delta:>+8.3f} | {dev:>+8.3f}")

    # Distribution flags
    print(f"\n=== STRUCTURED_AVG par flag (top 10) ===\n")
    print(f"{'flag':25s} | {'n':>3s} | {'CH-46':>8s} | {'CH-48':>8s} | {'Δ':>9s}")
    print("-" * 70)
    flags_data = {"CH-46": defaultdict(list), "CH-48": defaultdict(list)}
    for run_name in ("CH-46", "CH-48"):
        for r in results[run_name]:
            for f in r["flags"]:
                flags_data[run_name][f].append(r["scored"]["structured_avg"])
    flag_counts = {f: len(flags_data["CH-48"][f]) for f in flags_data["CH-48"]}
    top_flags = sorted(flag_counts.items(), key=lambda x: -x[1])[:12]
    for f, n in top_flags:
        v46 = sum(flags_data["CH-46"].get(f, [])) / max(len(flags_data["CH-46"].get(f, [])), 1)
        v48 = sum(flags_data["CH-48"].get(f, [])) / max(len(flags_data["CH-48"].get(f, [])), 1)
        delta = v48 - v46
        arrow = "↑" if delta > 0.02 else ("↓" if delta < -0.02 else "·")
        print(f"{f:25s} | {n:>3d} | {v46:>8.3f} | {v48:>8.3f} | {arrow}{delta:>+8.3f}")

    # Persist
    out = Path("/app/data/audit/ch49_post_score_v5_robust.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✓ Persisted → {out}")


if __name__ == "__main__":
    main()
