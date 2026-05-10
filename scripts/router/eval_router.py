"""
S2.A.3 — Évaluation du DeBERTa router sur les 2 hold-outs.

Hold-outs :
  - gold_set_v4.json (132q régulatoire, label = `primary_type`)
  - panel_stress_test_100q.json (124q multi-domaines, label = `expected_primary_type`)

Mesures : top-1, top-2, F1 macro + breakdown par type, langue, domaine.
Gate ADR S2 : ≥90% top-1, ≥95% top-2 sur chaque hold-out.

Usage :
  docker exec knowbase-app python /app/scripts/router/eval_router.py
"""
from __future__ import annotations
import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

MODEL_DIR = Path("/app/data/router/model")
HOLDOUT_GOLD = Path("/app/benchmark/questions/gold_set_v4.json")
HOLDOUT_STRESS = Path("/app/benchmark/questions/panel_stress_test_100q.json")
OUTPUT_PATH = Path("/app/data/router/eval_holdouts.json")

LABEL_NAMES = ["causal", "comparison", "factual", "false_premise", "list", "temporal", "unanswerable"]
LABEL2ID = {name: i for i, name in enumerate(LABEL_NAMES)}
ID2LABEL = {i: name for name, i in LABEL2ID.items()}


def load_holdout_gold():
    qs = json.loads(HOLDOUT_GOLD.read_text(encoding="utf-8"))
    return [{"id": q["id"], "text": q["question"], "label_name": q.get("primary_type"),
             "language": q.get("language"), "domain": "regulatory"} for q in qs]


def load_holdout_stress():
    raw = json.loads(HOLDOUT_STRESS.read_text(encoding="utf-8"))
    qs = raw if isinstance(raw, list) else raw.get("questions", [])
    return [{"id": q["id"], "text": q["question"],
             "label_name": q.get("expected_primary_type"),
             "language": q.get("language"), "domain": q.get("domain")} for q in qs]


@torch.no_grad()
def predict_batch(model, tokenizer, texts, device):
    enc = tokenizer(texts, truncation=True, max_length=128, padding=True, return_tensors="pt")
    enc = {k: v.to(device) for k, v in enc.items()}
    logits = model(**enc).logits.cpu().numpy()
    top1 = np.argmax(logits, axis=-1)
    top2 = np.argsort(logits, axis=-1)[:, -2:]
    probs = torch.softmax(torch.tensor(logits), dim=-1).numpy()
    return top1, top2, probs


def evaluate_holdout(name: str, items: list[dict], model, tokenizer, device, batch_size: int = 32):
    items = [it for it in items if it["label_name"] in LABEL2ID]
    if not items:
        return {"name": name, "error": "no_valid_items"}
    logger.info(f"[{name}] Evaluating {len(items)} items")

    all_top1, all_top2 = [], []
    all_probs = []
    for i in range(0, len(items), batch_size):
        batch = items[i:i+batch_size]
        texts = [b["text"] for b in batch]
        top1, top2, probs = predict_batch(model, tokenizer, texts, device)
        all_top1.extend(top1.tolist())
        all_top2.extend(top2.tolist())
        all_probs.extend(probs.tolist())

    # Annotate each item with prediction
    for it, t1, t2, p in zip(items, all_top1, all_top2, all_probs):
        it["pred_top1"] = ID2LABEL[t1]
        it["pred_top2"] = [ID2LABEL[i] for i in t2]
        it["confidence_top1"] = float(p[t1])
        it["correct_top1"] = it["pred_top1"] == it["label_name"]
        it["correct_top2"] = it["label_name"] in it["pred_top2"]

    # Aggregate metrics
    n = len(items)
    top1_acc = sum(1 for it in items if it["correct_top1"]) / n
    top2_acc = sum(1 for it in items if it["correct_top2"]) / n

    # Per-type
    by_type = defaultdict(list)
    for it in items:
        by_type[it["label_name"]].append(it)
    per_type = {}
    for t, group in by_type.items():
        ng = len(group)
        per_type[t] = {
            "n": ng,
            "top1_acc": sum(1 for it in group if it["correct_top1"]) / ng,
            "top2_acc": sum(1 for it in group if it["correct_top2"]) / ng,
        }

    # Per-language
    by_lang = defaultdict(list)
    for it in items:
        by_lang[it.get("language", "unk")].append(it)
    per_lang = {
        l: {"n": len(g),
            "top1_acc": sum(1 for it in g if it["correct_top1"]) / len(g),
            "top2_acc": sum(1 for it in g if it["correct_top2"]) / len(g)}
        for l, g in by_lang.items()
    }

    # Confusion matrix top-1
    confusion = defaultdict(lambda: defaultdict(int))
    for it in items:
        confusion[it["label_name"]][it["pred_top1"]] += 1
    confusion = {k: dict(v) for k, v in confusion.items()}

    # F1 macro
    f1_per_class = []
    for cls in LABEL_NAMES:
        tp = sum(1 for it in items if it["pred_top1"] == cls and it["label_name"] == cls)
        fp = sum(1 for it in items if it["pred_top1"] == cls and it["label_name"] != cls)
        fn = sum(1 for it in items if it["pred_top1"] != cls and it["label_name"] == cls)
        if tp + fp == 0 or tp + fn == 0:
            f1_per_class.append(0.0)
            continue
        p = tp / (tp + fp); r = tp / (tp + fn)
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
        f1_per_class.append(f1)
    f1_macro = float(np.mean(f1_per_class))

    return {
        "name": name,
        "n": n,
        "top1_accuracy": top1_acc,
        "top2_accuracy": top2_acc,
        "f1_macro": f1_macro,
        "per_type": per_type,
        "per_language": per_lang,
        "confusion_top1": confusion,
        "gate_top1_passed": top1_acc >= 0.90,
        "gate_top2_passed": top2_acc >= 0.95,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", default=str(MODEL_DIR))
    parser.add_argument("--save-per-sample", action="store_true",
                        help="Persist per-sample predictions to /app/data/router/eval_predictions_<holdout>.json")
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"Device : {device}")
    logger.info(f"Loading model from {args.model_dir}")
    model = AutoModelForSequenceClassification.from_pretrained(args.model_dir).to(device)
    model.eval()
    tokenizer = AutoTokenizer.from_pretrained(args.model_dir)

    gold_items = load_holdout_gold()
    stress_items = load_holdout_stress()
    logger.info(f"gold_set_v4 : {len(gold_items)} items, panel_stress : {len(stress_items)} items")

    res_gold = evaluate_holdout("gold_set_v4 (regulatory)", gold_items, model, tokenizer, device)
    res_stress = evaluate_holdout("panel_stress_test (multi-domain)", stress_items, model, tokenizer, device)

    output = {"gold_set_v4": res_gold, "panel_stress_test": res_stress}
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Persisted aggregate → {OUTPUT_PATH}")

    if args.save_per_sample:
        (Path("/app/data/router") / "eval_predictions_gold.json").write_text(
            json.dumps(gold_items, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (Path("/app/data/router") / "eval_predictions_stress.json").write_text(
            json.dumps(stress_items, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # Pretty print summary
    print()
    print("=" * 90)
    for tag, r in (("gold_set_v4", res_gold), ("panel_stress_test", res_stress)):
        print(f"\n[{tag}] n={r['n']}  top1={r['top1_accuracy']:.3f}  top2={r['top2_accuracy']:.3f}  "
              f"f1_macro={r['f1_macro']:.3f}  gate_top1={r['gate_top1_passed']}  gate_top2={r['gate_top2_passed']}")
        print(f"  per_type: " + "  ".join(
            f"{t}={m['top1_acc']:.2f}({m['n']})" for t, m in r['per_type'].items()))
        print(f"  per_lang: " + "  ".join(
            f"{l}={m['top1_acc']:.2f}({m['n']})" for l, m in r['per_language'].items()))


if __name__ == "__main__":
    sys.exit(main())
