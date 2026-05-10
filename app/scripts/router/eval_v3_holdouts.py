"""
Eval modèle v3 (5 classes answer_shape) sur hold-outs.

gold_set_v4_retagged : utilise gold_answer_shape directement.
panel_stress_test : on n'a pas re-taggué, mais les types de base mappent vers shape.
"""
from __future__ import annotations
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

MODEL_DIR = Path("/app/data/router/v3/model")
GOLD_PATH = Path("/app/benchmark/questions/gold_set_v4_retagged.json")
PANEL_PATH = Path("/app/benchmark/questions/panel_stress_test_100q.json")

LABEL_NAMES = ["causal_explicit", "comparison_explicit", "list", "scalar_factual", "temporal"]
ID2LABEL = {i: n for i, n in enumerate(LABEL_NAMES)}
LABEL2ID = {n: i for i, n in enumerate(LABEL_NAMES)}

# Mapping types panel_stress (anciens 7 types) → 5 shape
LEGACY_TO_SHAPE = {
    "factual": "scalar_factual",
    "causal": "causal_explicit",
    "comparison": "comparison_explicit",  # heuristique : panel n'a pas de comparison émergent
    "temporal": "temporal",
    "list": "list",
    "unanswerable": None,  # pas d'answer_shape direct
    "false_premise": None,
}


@torch.no_grad()
def eval_holdout(name, items, model, tokenizer, device, batch=32):
    items = [it for it in items if it["gold_shape"] in LABEL2ID]
    if not items:
        return None
    print(f"\n[{name}] {len(items)} items")

    correct1 = 0
    correct2 = 0
    by_shape = defaultdict(lambda: [0, 0])
    confusion = defaultdict(lambda: defaultdict(int))

    for i in range(0, len(items), batch):
        b = items[i:i+batch]
        texts = [it["text"] for it in b]
        enc = tokenizer(texts, truncation=True, max_length=128, padding=True, return_tensors="pt")
        enc = {k: v.to(device) for k, v in enc.items()}
        logits = model(**enc).logits.cpu().numpy()
        top1 = np.argmax(logits, axis=-1)
        top2_idx = np.argsort(logits, axis=-1)[:, -2:]

        for it, t1, t2 in zip(b, top1, top2_idx):
            pred = ID2LABEL[t1]
            preds_top2 = [ID2LABEL[ix] for ix in t2]
            gold = it["gold_shape"]
            ok1 = pred == gold
            ok2 = gold in preds_top2 or ok1
            if ok1: correct1 += 1
            if ok2: correct2 += 1
            by_shape[gold][1] += 1
            if ok1: by_shape[gold][0] += 1
            confusion[gold][pred] += 1

    n = len(items)
    print(f"  Top-1 : {correct1}/{n} = {correct1/n*100:.1f}%")
    print(f"  Top-2 : {correct2}/{n} = {correct2/n*100:.1f}%")
    for shape in LABEL_NAMES:
        c, t = by_shape[shape]
        if t > 0:
            print(f"    {shape:<22} : {c}/{t} = {c/t*100:.1f}%")
    print(f"  Confusion (rows=gold, cols=pred):")
    for gold in LABEL_NAMES:
        row = confusion[gold]
        cells = "  ".join(f"{l[:6]}={row.get(l, 0):>3}" for l in LABEL_NAMES)
        print(f"    {gold:<22} | {cells}")
    return {"name": name, "n": n, "top1": correct1/n, "top2": correct2/n}


def main():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = AutoModelForSequenceClassification.from_pretrained(str(MODEL_DIR)).to(device).eval()
    tokenizer = AutoTokenizer.from_pretrained(str(MODEL_DIR))

    # Gold_set_v4 retagged
    gold_qs = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    gold_items = [{"id": q["id"], "text": q["question"], "gold_shape": q["gold_answer_shape"],
                   "language": q["language"]} for q in gold_qs]

    # Panel stress (mapping legacy)
    panel_raw = json.loads(PANEL_PATH.read_text(encoding="utf-8"))
    panel_qs = panel_raw if isinstance(panel_raw, list) else panel_raw.get("questions", [])
    panel_items = []
    for q in panel_qs:
        legacy = q.get("expected_primary_type")
        shape = LEGACY_TO_SHAPE.get(legacy)
        if shape is None:
            continue  # skip unanswerable/false_premise (pas dans answer_shape)
        panel_items.append({"id": q["id"], "text": q["question"], "gold_shape": shape,
                           "language": q["language"]})

    print(f"Loaded gold:{len(gold_items)} panel:{len(panel_items)}")

    res_gold = eval_holdout("gold_set_v4 retagged", gold_items, model, tokenizer, device)
    res_panel = eval_holdout("panel_stress (legacy mapped)", panel_items, model, tokenizer, device)

    print("\n=== SUMMARY ===")
    print(f"gold_set_v4    : top1={res_gold['top1']*100:.1f}% top2={res_gold['top2']*100:.1f}%")
    print(f"panel_stress   : top1={res_panel['top1']*100:.1f}% top2={res_panel['top2']*100:.1f}%")
    print(f"\nGate ADR §9.4 (≥90% top-1) : "
          f"gold={'✅' if res_gold['top1'] >= 0.9 else '❌'} | "
          f"panel={'✅' if res_panel['top1'] >= 0.9 else '❌'}")


if __name__ == "__main__":
    main()
