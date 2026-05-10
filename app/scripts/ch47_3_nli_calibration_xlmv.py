"""
CH-47.3 — Calibration NLI avec mDeBERTa-v3-base vs XLM-V-base (upgrade test).

Compare la distribution entailment des 25 reasoning_steps réels (prototype v2)
sous deux modèles :
  - mDeBERTa-v3-base-xnli-multilingual-nli-2mil7 (0.28B params, baseline actuel)
  - xlm-v-base-mnli-xnli (0.8B params, candidat upgrade option B)

Output :
  - Distribution comparée par strength
  - Recommandation : garder v3-base + seuils empiriques OU upgrade XLM-V
  - data/audit/ch47_3_nli_calibration_compared.json
"""
from __future__ import annotations
import json
import sys
from collections import defaultdict
from pathlib import Path

PROTOTYPE = Path("/app/data/audit/ch47_prototype_10q_v2.json")
OUT = Path("/app/data/audit/ch47_3_nli_calibration_compared.json")

MODELS = {
    "mdeberta_v3_base": "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7",
    "xlm_v_base": "MoritzLaurer/xlm-v-base-mnli-xnli",
}


def build_premise(step: dict, facts_first: dict) -> str:
    parts = []
    atomic = {f["id"]: f for f in facts_first.get("atomic_facts", [])}
    relational = {r["id"]: r for r in facts_first.get("relational_facts", [])}
    for eid in step.get("evidence_ids", []) or []:
        f = atomic.get(eid)
        if f:
            q = ((f.get("source") or {}).get("quote") or "")[:500]
            if q:
                parts.append(q)
    rid = step.get("relation_id")
    if rid:
        r = relational.get(rid)
        if r:
            q = (r.get("evidence_quote") or "")[:500]
            if q and q not in parts:
                parts.append(q)
    return " ".join(parts)


def collect_pairs(data):
    pairs = []
    for q in data:
        if "error" in q:
            continue
        ff = q.get("facts_first_v2") or {}
        for step in (q.get("reasoning_output") or {}).get("reasoning_steps") or []:
            premise = build_premise(step, ff)
            hypothesis = step.get("inference") or ""
            if not premise or not hypothesis:
                continue
            pairs.append({
                "qid": q.get("id"),
                "step_no": step.get("step"),
                "strength": step.get("inference_strength") or "unknown",
                "premise": premise,
                "hypothesis": hypothesis,
            })
    return pairs


def run_model(model_name, pairs):
    from sentence_transformers import CrossEncoder
    import torch
    print(f"\nLoading {model_name}...")
    model = CrossEncoder(model_name, device="cuda" if torch.cuda.is_available() else "cpu")
    print(f"  → loaded on {model.device}")

    pairs_for_nli = [(p["premise"], p["hypothesis"]) for p in pairs]
    scores_raw = model.predict(pairs_for_nli, apply_softmax=True, show_progress_bar=False)
    # Both models output [ENTAILMENT, NEUTRAL, CONTRADICTION] (XNLI/MNLI standard)
    out = []
    for i, p in enumerate(pairs):
        entail, neutral, contra = scores_raw[i]
        out.append({
            **p,
            "entailment": float(entail),
            "neutral": float(neutral),
            "contradiction": float(contra),
        })
    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return out


def stats_per_strength(scored, label):
    print(f"\n=== {label} ===")
    by_s = defaultdict(list)
    for p in scored:
        by_s[p["strength"]].append(p)
    print(f"{'strength':<12} {'n':>3} {'min':>7} {'p20':>7} {'p50':>7} {'p80':>7} {'max':>7} {'mean':>7}")
    out = {}
    for s in ["direct", "probable", "speculative"]:
        items = by_s.get(s, [])
        if not items:
            continue
        scores = sorted([x["entailment"] for x in items])
        n = len(scores)
        def pct(p): return scores[max(0, min(n - 1, int(n * p)))]
        out[s] = {
            "n": n, "min": scores[0], "p20": pct(0.20), "p50": pct(0.5),
            "p80": pct(0.80), "max": scores[-1], "mean": sum(scores) / n,
        }
        print(f"{s:<12} {n:>3} {scores[0]:>7.3f} {pct(0.2):>7.3f} {pct(0.5):>7.3f} {pct(0.8):>7.3f} {scores[-1]:>7.3f} {sum(scores)/n:>7.3f}")
    return out


def main():
    data = json.loads(PROTOTYPE.read_text(encoding="utf-8"))
    pairs = collect_pairs(data)
    print(f"Collected {len(pairs)} reasoning_steps")

    results = {}
    for label, model_name in MODELS.items():
        scored = run_model(model_name, pairs)
        results[label] = scored

    # Stats par modèle
    summaries = {}
    for label, scored in results.items():
        summaries[label] = stats_per_strength(scored, label)

    # Comparaison directe sur les 4 cas critiques (direct < 0.1 sur v3-base)
    print(f"\n=== COMPARAISON DIRECT < 0.1 sur v3-base ===")
    v3_low = [p for p in results["mdeberta_v3_base"] if p["strength"] == "direct" and p["entailment"] < 0.1]
    print(f"{'qid':<6} {'step':<4} {'inference':<60} {'v3-base entail':>15} {'xlm-v entail':>15}")
    for p_v3 in v3_low:
        p_xlm = next((x for x in results["xlm_v_base"]
                     if x["qid"] == p_v3["qid"] and x["step_no"] == p_v3["step_no"]), None)
        infpr = p_v3["hypothesis"][:60]
        v3e = p_v3["entailment"]
        xlme = p_xlm["entailment"] if p_xlm else None
        print(f"{p_v3['qid']:<6} {p_v3['step_no']:<4} {infpr:<60} {v3e:>15.3f} {(xlme if xlme else 0):>15.3f}")

    # Recommandation
    print(f"\n=== RECOMMANDATION ===")
    v3_direct_p20 = summaries["mdeberta_v3_base"].get("direct", {}).get("p20", 0)
    xlm_direct_p20 = summaries["xlm_v_base"].get("direct", {}).get("p20", 0)
    print(f"v3-base direct p20: {v3_direct_p20:.3f}")
    print(f"xlm-v  direct p20: {xlm_direct_p20:.3f}")
    if xlm_direct_p20 > v3_direct_p20 + 0.1:
        print(f"→ XLM-V améliore p20 de {(xlm_direct_p20 - v3_direct_p20):.2f} → upgrade RECOMMANDÉ")
    else:
        print(f"→ Gain marginal, GARDER v3-base avec seuils empiriques (option A)")

    # Persist
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"models_tested": MODELS, "results": results, "summaries": summaries},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nPersisted → {OUT}")


if __name__ == "__main__":
    main()
