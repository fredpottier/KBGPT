"""
Phase 0 — Audit taxonomique des fails router.

Classer chaque fail (LLM zero-shot + DeBERTa run 2) en 3 catégories :
  - intrinsically_ambiguous : la question est légitimement multi-label
  - corpus_dependent : le label nécessite l'accès au KG/corpus
  - linguistic_pattern : la formulation devrait suffire (échec du modèle)

Génère un fichier audit_phase0_input.md où je classifie ensuite chaque cas.
Le critère de décision : si >30% corpus_dependent → gate 90% strict non atteignable.
"""
from __future__ import annotations
import json
from pathlib import Path

GOLD_PATH = Path("/app/benchmark/questions/gold_set_v4.json")
DEBERTA_PREDS_PATH = Path("/app/data/router/eval_predictions_gold.json")
LLM_BENCH_PATH = Path("/app/data/benchmark/calibration/bench_global_v4_qwen_baseline.json")
OUT_PATH = Path("/app/data/router/audit_phase0_input.md")


def main():
    gold = {q["id"]: q for q in json.loads(GOLD_PATH.read_text(encoding="utf-8"))}
    deberta_preds = json.loads(DEBERTA_PREDS_PATH.read_text(encoding="utf-8"))

    # LLM bench : récupérer les prédictions du Qwen-72B zero-shot sur gold_set_v4
    llm_bench_data = None
    if LLM_BENCH_PATH.exists():
        try:
            llm_bench_data = json.loads(LLM_BENCH_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    fails = []
    seen_ids = set()

    # 1. DeBERTa fails sur gold
    for p in deberta_preds:
        if not p.get("correct_top1"):
            qid = p["id"]
            if qid in seen_ids:
                continue
            seen_ids.add(qid)
            g = gold.get(qid, {})
            gt = g.get("ground_truth", {})
            fails.append({
                "id": qid,
                "question": p["text"],
                "language": p["language"],
                "gold_primary_type": p["label_name"],
                "gold_secondary_type": g.get("secondary_type"),
                "deberta_pred": p["pred_top1"],
                "deberta_top2": p["pred_top2"],
                "deberta_confidence": p["confidence_top1"],
                "ground_truth_summary": {
                    "answer": (gt.get("answer") or "")[:120],
                    "answerability": gt.get("answerability"),
                    "false_premise": gt.get("false_premise"),
                    "contradiction_vs_supersession": gt.get("contradiction_vs_supersession"),
                    "causal_chain": bool(gt.get("causal_chain")),
                    "list_items_expected": len(gt.get("list_items_expected") or []),
                },
                "category": g.get("category"),
                "stratum": g.get("stratum"),
                "source_fail": "deberta_run2",
            })

    # 2. LLM zero-shot fails (depuis bench global Qwen baseline post-leviers)
    if llm_bench_data and "per_sample" in llm_bench_data:
        for r in llm_bench_data["per_sample"]:
            qid = r.get("id", "")
            if not qid.startswith("GOLD_v4_"):
                continue
            expected = r.get("expected_type")
            predicted = r.get("primary_type_predicted")
            if not expected or expected in ("false_premise", "unanswerable"):
                continue
            if predicted == expected:
                continue
            if qid in seen_ids:
                # Déjà identifié comme fail DeBERTa, juste enrichir
                for f in fails:
                    if f["id"] == qid:
                        f["llm_pred"] = predicted
                        f["llm_confidence"] = r.get("primary_confidence")
                        f["source_fail"] = "both"
                        break
                continue
            seen_ids.add(qid)
            g = gold.get(qid, {})
            gt = g.get("ground_truth", {})
            fails.append({
                "id": qid,
                "question": r.get("question", g.get("question", "")),
                "language": r.get("language"),
                "gold_primary_type": expected,
                "gold_secondary_type": g.get("secondary_type"),
                "deberta_pred": None,
                "llm_pred": predicted,
                "llm_confidence": r.get("primary_confidence"),
                "ground_truth_summary": {
                    "answer": (gt.get("answer") or "")[:120],
                    "answerability": gt.get("answerability"),
                    "false_premise": gt.get("false_premise"),
                    "contradiction_vs_supersession": gt.get("contradiction_vs_supersession"),
                    "causal_chain": bool(gt.get("causal_chain")),
                    "list_items_expected": len(gt.get("list_items_expected") or []),
                },
                "category": g.get("category"),
                "stratum": g.get("stratum"),
                "source_fail": "llm_only",
            })

    print(f"Total unique fails to classify: {len(fails)}")
    print(f"  source=deberta_run2: {sum(1 for f in fails if f['source_fail'] == 'deberta_run2')}")
    print(f"  source=both:         {sum(1 for f in fails if f['source_fail'] == 'both')}")
    print(f"  source=llm_only:     {sum(1 for f in fails if f['source_fail'] == 'llm_only')}")

    # Output structuré
    lines = ["# Phase 0 — Audit taxonomique fails router\n",
             f"\n**Total fails à classifier** : {len(fails)}\n",
             "\nClassifie chaque fail dans :\n",
             "- `intrinsically_ambiguous` : multi-label légitime (la question peut être 2+ types selon interprétation)\n",
             "- `corpus_dependent` : le label nécessite voir le KG/corpus pour trancher\n",
             "- `linguistic_pattern` : la formulation seule devrait suffire (échec modèle)\n\n",
             "---\n\n"]

    for i, f in enumerate(fails, 1):
        gt = f["ground_truth_summary"]
        signals = []
        if gt.get("contradiction_vs_supersession"):
            signals.append(f"contradiction={gt['contradiction_vs_supersession']}")
        if gt.get("causal_chain"):
            signals.append("has_causal_chain")
        if gt.get("list_items_expected"):
            signals.append(f"n_list_items={gt['list_items_expected']}")
        if gt.get("answerability") and gt["answerability"] != "answerable":
            signals.append(f"answerability={gt['answerability']}")
        if gt.get("false_premise"):
            signals.append("false_premise=true")
        signals_str = " | ".join(signals) if signals else "none"

        preds = []
        if f.get("deberta_pred"):
            preds.append(f"DeBERTa→{f['deberta_pred']} ({f.get('deberta_confidence', 0):.2f})")
        if f.get("llm_pred"):
            preds.append(f"LLM-zs→{f['llm_pred']} ({f.get('llm_confidence', 0):.2f})")

        lines.append(f"## #{i} [{f['id']}] {f['language']} {f['source_fail']}\n")
        lines.append(f"**Q** : {f['question'][:240]}\n\n")
        lines.append(f"- **Gold primary** : `{f['gold_primary_type']}` (secondary: `{f.get('gold_secondary_type')}`)\n")
        lines.append(f"- **Predictions** : {' | '.join(preds) if preds else 'n/a'}\n")
        lines.append(f"- **Gold signals** : {signals_str}\n")
        lines.append(f"- **GT answer** : {gt.get('answer', '')}\n")
        lines.append(f"- **Category/Stratum** : {f.get('category')} / {f.get('stratum')}\n")
        lines.append(f"- **CLASSIFICATION** : `TODO` (intrinsically_ambiguous|corpus_dependent|linguistic_pattern)\n\n")

    OUT_PATH.write_text("".join(lines), encoding="utf-8")
    print(f"\nWrote audit input → {OUT_PATH}")
    print(f"  ({len(fails)} cases to classify, ~1h estimated)")

    # Aussi dump JSON pour traitement programmatique
    json_path = OUT_PATH.with_suffix(".json")
    json_path.write_text(json.dumps(fails, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  + JSON: {json_path}")


if __name__ == "__main__":
    main()
