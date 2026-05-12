"""
Phase 4 (ADR §9.6) — Cascade calibrée DeBERTa + LLM fallback.

Étapes :
  1. Sortir logits DeBERTa v3 sur val set + gold_set_v4_retagged
  2. Calibrer température (temperature scaling) sur val set par minimisation NLL
  3. Pour chaque seuil de confidence calibrée, mesurer :
     - DeBERTa accuracy sur les cas confidents (utilisés)
     - % fallback (cas non-confidents)
     - Effective accuracy = utilisé*acc_DeBERTa + fallback*acc_LLM_zero_shot

LLM zero-shot baseline : 82% sur gold_set_v4 (référence Qwen-72B mesurée)

Output : table de tradeoffs seuil → effective accuracy
"""
from __future__ import annotations
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
from torch import nn
from transformers import AutoModelForSequenceClassification, AutoTokenizer

MODEL_DIR = Path("/app/data/router/v3/model")
VAL_PATH = Path("/app/data/router/v3/val.jsonl")
GOLD_PATH = Path("/app/benchmark/questions/gold_set_v4_retagged.json")
PANEL_PATH = Path("/app/benchmark/questions/panel_stress_test_100q.json")

LABEL_NAMES = ["causal_explicit", "comparison_explicit", "list", "scalar_factual", "temporal"]
LABEL2ID = {n: i for i, n in enumerate(LABEL_NAMES)}
ID2LABEL = {i: n for i, n in enumerate(LABEL_NAMES)}

LEGACY_TO_SHAPE = {
    "factual": "scalar_factual",
    "causal": "causal_explicit",
    "comparison": "comparison_explicit",
    "temporal": "temporal",
    "list": "list",
    "unanswerable": None,
    "false_premise": None,
}

# Hypothèse LLM zero-shot acc estimée (référence empirique sur gold_set_v4)
# Ancien LLM Qwen-72B zero-shot était à ~82% sur 7 classes ; mappé sur 5 shape, on estime ~85%
# (les cas corpus_dependent que LLM ratait sont moins pénalisants en answer_shape pur)
LLM_FALLBACK_ACC_ASSUMED = 0.85


@torch.no_grad()
def get_logits_and_labels(items, model, tokenizer, device, batch=32):
    """Retourne logits np.array (n, 5) + labels np.array (n,)."""
    all_logits = []
    all_labels = []
    for i in range(0, len(items), batch):
        b = items[i:i+batch]
        texts = [it["text"] for it in b]
        labels = [LABEL2ID[it["gold_shape"]] for it in b]
        enc = tokenizer(texts, truncation=True, max_length=128, padding=True, return_tensors="pt")
        enc = {k: v.to(device) for k, v in enc.items()}
        logits = model(**enc).logits.cpu().numpy()
        all_logits.append(logits)
        all_labels.extend(labels)
    return np.concatenate(all_logits, axis=0), np.array(all_labels)


def fit_temperature(logits, labels, max_iter=200):
    """Temperature scaling : minimise NLL en optimisant T tel que softmax(logits/T) calibre mieux."""
    logits_t = torch.tensor(logits, dtype=torch.float32)
    labels_t = torch.tensor(labels, dtype=torch.long)
    T = nn.Parameter(torch.ones(1, dtype=torch.float32))
    optim = torch.optim.LBFGS([T], lr=0.1, max_iter=max_iter)
    crit = nn.CrossEntropyLoss()

    def closure():
        optim.zero_grad()
        loss = crit(logits_t / T.clamp(min=1e-3), labels_t)
        loss.backward()
        return loss

    optim.step(closure)
    return float(T.detach().cpu().item())


def softmax_with_T(logits, T):
    z = logits / T
    z = z - z.max(axis=-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)


def evaluate_cascade(logits, labels, T, thresholds, llm_acc=LLM_FALLBACK_ACC_ASSUMED):
    """Pour chaque seuil, compute effective accuracy assumant fallback LLM."""
    probs = softmax_with_T(logits, T)
    max_proba = probs.max(axis=-1)
    pred_top1 = probs.argmax(axis=-1)
    correct = (pred_top1 == labels)
    n = len(labels)
    print(f"  Calibrated T={T:.3f} | DeBERTa raw top-1 = {correct.mean()*100:.1f}%")

    print(f"\n  {'thr':>5} | {'%DeB':>6} | {'%LLM':>6} | {'DeB_acc':>8} | {'eff_acc':>8} | {'eff_(real_LLM)':>15}")
    print(f"  ------+--------+--------+----------+----------+----------------")
    rows = []
    for thr in thresholds:
        use_deberta = max_proba >= thr
        n_deb = int(use_deberta.sum())
        n_llm = n - n_deb
        deb_acc = correct[use_deberta].mean() if n_deb > 0 else 0.0
        # effective = (n_deb * deb_acc + n_llm * llm_acc) / n
        eff_acc = (n_deb * deb_acc + n_llm * llm_acc) / n
        rows.append({
            "threshold": thr, "n_deberta": n_deb, "n_llm": n_llm,
            "deberta_acc": float(deb_acc), "effective_acc": float(eff_acc),
            "deberta_pct": n_deb / n * 100, "llm_pct": n_llm / n * 100,
        })
        print(f"  {thr:>5.2f} | {n_deb/n*100:>5.1f}% | {n_llm/n*100:>5.1f}% | "
              f"{deb_acc*100:>7.1f}% | {eff_acc*100:>7.1f}% | (using llm_acc={llm_acc:.2f})")
    return rows


def main():
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device : {device}")
    print(f"Loading model from {MODEL_DIR}")
    model = AutoModelForSequenceClassification.from_pretrained(str(MODEL_DIR)).to(device).eval()
    tokenizer = AutoTokenizer.from_pretrained(str(MODEL_DIR))

    # Val items
    val_items = []
    with VAL_PATH.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            val_items.append({"id": r["id"], "text": r["text"], "gold_shape": r["label_name"]})
    print(f"Val: {len(val_items)} items")

    # Gold items
    gold_qs = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
    gold_items = [{"id": q["id"], "text": q["question"], "gold_shape": q["gold_answer_shape"]}
                  for q in gold_qs if q["gold_answer_shape"] in LABEL2ID]
    print(f"Gold: {len(gold_items)} items")

    # Panel items
    panel_raw = json.loads(PANEL_PATH.read_text(encoding="utf-8"))
    panel_qs = panel_raw if isinstance(panel_raw, list) else panel_raw.get("questions", [])
    panel_items = []
    for q in panel_qs:
        legacy = q.get("expected_primary_type")
        shape = LEGACY_TO_SHAPE.get(legacy)
        if shape is None: continue
        panel_items.append({"id": q["id"], "text": q["question"], "gold_shape": shape})
    print(f"Panel: {len(panel_items)} items")

    # Get logits
    print("\n=== Computing logits ===")
    val_logits, val_labels = get_logits_and_labels(val_items, model, tokenizer, device)
    gold_logits, gold_labels = get_logits_and_labels(gold_items, model, tokenizer, device)
    panel_logits, panel_labels = get_logits_and_labels(panel_items, model, tokenizer, device)

    # Fit temperature on val
    print("\n=== Fitting temperature on val ===")
    T_val = fit_temperature(val_logits, val_labels)
    print(f"Val temperature : T={T_val:.3f}")

    # Eval cascade
    thresholds = [0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]

    print(f"\n=== CASCADE ON GOLD_SET_V4 (n={len(gold_items)}) ===")
    rows_gold = evaluate_cascade(gold_logits, gold_labels, T_val, thresholds, llm_acc=0.85)

    print(f"\n=== CASCADE ON PANEL_STRESS (n={len(panel_items)}) ===")
    rows_panel = evaluate_cascade(panel_logits, panel_labels, T_val, thresholds, llm_acc=0.85)

    # Find best threshold
    print("\n=== BEST THRESHOLDS ===")
    best_gold = max(rows_gold, key=lambda r: r["effective_acc"])
    best_panel = max(rows_panel, key=lambda r: r["effective_acc"])
    print(f"Gold  best: thr={best_gold['threshold']} eff_acc={best_gold['effective_acc']*100:.1f}% "
          f"(DeBERTa pour {best_gold['deberta_pct']:.1f}%, LLM fallback {best_gold['llm_pct']:.1f}%)")
    print(f"Panel best: thr={best_panel['threshold']} eff_acc={best_panel['effective_acc']*100:.1f}% "
          f"(DeBERTa pour {best_panel['deberta_pct']:.1f}%, LLM fallback {best_panel['llm_pct']:.1f}%)")

    # Persist
    out_path = Path("/app/data/router/v3/cascade_calibration.json")
    out_path.write_text(json.dumps({
        "temperature": T_val,
        "llm_fallback_acc_assumed": LLM_FALLBACK_ACC_ASSUMED,
        "gold_set_v4": rows_gold,
        "panel_stress_test": rows_panel,
        "best_thresholds": {"gold": best_gold, "panel": best_panel},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nPersisted → {out_path}")


if __name__ == "__main__":
    sys.exit(main())
