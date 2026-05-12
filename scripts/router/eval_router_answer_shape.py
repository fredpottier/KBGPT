"""
Re-eval du DeBERTa run 2 sur la nouvelle taxonomie answer_shape (5 classes).

But : voir si la performance grimpe vs ancien primary_type (7 classes).
Mapping :
  ancien primary_type → comparison_explicit, temporal, list, causal_explicit, scalar_factual
  unanswerable / false_premise → projetés sur l'answer_shape correspondant à la formulation

Le modèle DeBERTa est entraîné sur 7 classes (causal/comparison/factual/false_premise/list/temporal/unanswerable).
On mappe ses prédictions vers answer_shape :
  factual → scalar_factual
  comparison → comparison_explicit
  causal → causal_explicit
  list → list
  temporal → temporal
  false_premise → on garde sa prédiction pour epistemic_status, et on regarde si match shape
  unanswerable → idem
"""
from __future__ import annotations
import json
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

MODEL_DIR = Path("/app/data/router/model")
HOLDOUT = Path("/app/benchmark/questions/gold_set_v4_retagged.json")

LABEL_NAMES = ["causal", "comparison", "factual", "false_premise", "list", "temporal", "unanswerable"]
ID2LABEL = {i: n for i, n in enumerate(LABEL_NAMES)}
LABEL2ID = {n: i for i, n in enumerate(LABEL_NAMES)}

# Mapping prédiction modèle → answer_shape (5 classes pré-retrieval)
PRED_TO_SHAPE = {
    "factual": "scalar_factual",
    "comparison": "comparison_explicit",
    "causal": "causal_explicit",
    "list": "list",
    "temporal": "temporal",
    # false_premise / unanswerable : pas un answer_shape direct, on regarde la formulation
    # On les considère comme « meta-prédictions » → fallback sur top-2
    "false_premise": "FALLBACK",
    "unanswerable": "FALLBACK",
}

PRED_TO_EPISTEMIC = {
    "false_premise": "false_premise",
    "unanswerable": "unanswerable",
}


@torch.no_grad()
def main():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = AutoModelForSequenceClassification.from_pretrained(str(MODEL_DIR)).to(device)
    model.eval()
    tokenizer = AutoTokenizer.from_pretrained(str(MODEL_DIR))

    questions = json.loads(HOLDOUT.read_text(encoding="utf-8"))
    print(f"Loaded {len(questions)} retagged questions")

    correct_shape = 0
    correct_top2_shape = 0
    correct_epistemic = 0
    by_shape_correct = defaultdict(lambda: [0, 0])  # [correct, total]
    by_epistemic_correct = defaultdict(lambda: [0, 0])

    detail_failures = []

    BATCH = 32
    for start in range(0, len(questions), BATCH):
        batch = questions[start:start+BATCH]
        texts = [q["question"] for q in batch]
        enc = tokenizer(texts, truncation=True, max_length=128, padding=True, return_tensors="pt")
        enc = {k: v.to(device) for k, v in enc.items()}
        logits = model(**enc).logits.cpu().numpy()
        top1_idx = np.argmax(logits, axis=-1)
        top2_idx = np.argsort(logits, axis=-1)[:, -2:]  # last 2 = top-2

        for i, q in enumerate(batch):
            pred_top1_label = ID2LABEL[top1_idx[i]]
            pred_top2_labels = [ID2LABEL[ix] for ix in top2_idx[i]]

            # Map to shape
            pred_shape_top1 = PRED_TO_SHAPE.get(pred_top1_label, "FALLBACK")
            pred_shapes_top2 = [PRED_TO_SHAPE.get(l, "FALLBACK") for l in pred_top2_labels]

            gold_shape = q["gold_answer_shape"]
            gold_epistemic = q["gold_epistemic_status"]

            # Shape eval
            shape_match = pred_shape_top1 == gold_shape
            shape_top2_match = gold_shape in pred_shapes_top2 or shape_match
            if shape_match:
                correct_shape += 1
            if shape_top2_match:
                correct_top2_shape += 1

            by_shape_correct[gold_shape][1] += 1
            if shape_match:
                by_shape_correct[gold_shape][0] += 1

            # Epistemic eval (on regarde si la prédiction false_premise ou unanswerable
            # match le gold_epistemic_status)
            pred_epistemic = PRED_TO_EPISTEMIC.get(pred_top1_label, "answerable")
            epistemic_match = pred_epistemic == gold_epistemic
            if epistemic_match:
                correct_epistemic += 1
            by_epistemic_correct[gold_epistemic][1] += 1
            if epistemic_match:
                by_epistemic_correct[gold_epistemic][0] += 1

            if not shape_match:
                detail_failures.append({
                    "id": q["id"],
                    "language": q["language"],
                    "question": q["question"][:160],
                    "gold_shape": gold_shape,
                    "gold_epistemic": gold_epistemic,
                    "gold_corpus_signal": q["gold_corpus_signal_required"],
                    "pred_top1": pred_top1_label,
                    "pred_shape_top1": pred_shape_top1,
                    "pred_shape_top2": pred_shapes_top2,
                })

    n = len(questions)
    print(f"\n=== ANSWER_SHAPE ACCURACY (5 classes pré-retrieval) ===")
    print(f"Top-1 : {correct_shape}/{n} = {correct_shape/n*100:.1f}%")
    print(f"Top-2 : {correct_top2_shape}/{n} = {correct_top2_shape/n*100:.1f}%")
    print(f"\nPer-shape :")
    for shape, (c, t) in sorted(by_shape_correct.items()):
        print(f"  {shape:<22} : {c}/{t} = {c/t*100:.1f}%")

    print(f"\n=== EPISTEMIC_STATUS ACCURACY (3 classes) ===")
    print(f"Top-1 : {correct_epistemic}/{n} = {correct_epistemic/n*100:.1f}%")
    for epi, (c, t) in sorted(by_epistemic_correct.items()):
        print(f"  {epi:<22} : {c}/{t} = {c/t*100:.1f}%")

    # Persist failures pour analyse
    out = Path("/app/data/router/eval_answer_shape_failures.json")
    out.write_text(json.dumps(detail_failures, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{len(detail_failures)} failures persisted → {out}")


if __name__ == "__main__":
    main()
