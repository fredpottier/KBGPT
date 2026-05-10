"""
S2.A.2/A.3 — Fine-tune mDeBERTa-v3-base sur le router training set.

Modèle : microsoft/mdeberta-v3-base (~278M params, multilingue 100 langues)
Données : /app/data/router/train.jsonl (392q) + val.jsonl (98q)
Classes : 7 types (causal, comparison, factual, false_premise, list, temporal, unanswerable)

Hyperparams :
  - 5 epochs
  - batch_size 16
  - lr 2e-5
  - weight_decay 0.01
  - warmup_ratio 0.1

Output : /app/data/router/model/ (poids + tokenizer + config)

Usage :
  docker exec knowbase-app python /app/scripts/router/train_deberta.py
"""
from __future__ import annotations
import json
import logging
import sys
from pathlib import Path

import numpy as np
import torch
from datasets import load_dataset
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    DataCollatorWithPadding,
    Trainer,
    TrainingArguments,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path("/app/data/router")
MODEL_OUT_DIR = Path("/app/data/router/model")
# XLM-RoBERTa-base : 278M params, multilingue 100 langues, FR/EN/DE/ES robuste.
# Choisi vs mDeBERTa-v3-base à cause d'un mismatch nommage LayerNorm beta/gamma↔bias/weight
# qui faisait que le backbone n'était PAS chargé pré-entraîné dans transformers 5.5.
MODEL_NAME = "FacebookAI/xlm-roberta-base"

NUM_LABELS = 7
LABEL_NAMES = ["causal", "comparison", "factual", "false_premise", "list", "temporal", "unanswerable"]
ID2LABEL = {i: name for i, name in enumerate(LABEL_NAMES)}
LABEL2ID = {name: i for i, name in enumerate(LABEL_NAMES)}


def compute_metrics(eval_pred):
    """Compute accuracy top-1, top-2 + per-class F1."""
    logits, labels = eval_pred
    if isinstance(logits, tuple):
        logits = logits[0]
    preds = np.argmax(logits, axis=-1)
    top1_acc = float((preds == labels).mean())

    # Top-2 accuracy
    top2_indices = np.argsort(logits, axis=-1)[:, -2:]
    top2_correct = np.array([labels[i] in top2_indices[i] for i in range(len(labels))])
    top2_acc = float(top2_correct.mean())

    # Per-class F1 (macro)
    from collections import Counter
    f1_per_class = []
    for cls in range(NUM_LABELS):
        tp = int(((preds == cls) & (labels == cls)).sum())
        fp = int(((preds == cls) & (labels != cls)).sum())
        fn = int(((preds != cls) & (labels == cls)).sum())
        if tp + fp == 0 or tp + fn == 0:
            f1_per_class.append(0.0)
            continue
        precision = tp / (tp + fp)
        recall = tp / (tp + fn)
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        f1_per_class.append(f1)
    f1_macro = float(np.mean(f1_per_class))
    return {
        "accuracy": top1_acc,
        "top2_accuracy": top2_acc,
        "f1_macro": f1_macro,
    }


def main():
    logger.info("Loading datasets ...")
    raw = load_dataset("json", data_files={
        "train": str(DATA_DIR / "train.jsonl"),
        "validation": str(DATA_DIR / "val.jsonl"),
    })
    logger.info(f"Train: {len(raw['train'])}, Val: {len(raw['validation'])}")

    logger.info(f"Loading tokenizer + model {MODEL_NAME} ...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_NAME,
        num_labels=NUM_LABELS,
        id2label=ID2LABEL,
        label2id=LABEL2ID,
    )

    def tokenize_batch(batch):
        return tokenizer(batch["text"], truncation=True, max_length=128)

    logger.info("Tokenizing ...")
    tokenized = raw.map(tokenize_batch, batched=True)

    # Keep only fields needed by Trainer (cleaner logs, smaller batches)
    tokenized = tokenized.remove_columns(
        [c for c in tokenized["train"].column_names
         if c not in ("input_ids", "attention_mask", "label")]
    )

    data_collator = DataCollatorWithPadding(tokenizer=tokenizer)

    MODEL_OUT_DIR.mkdir(parents=True, exist_ok=True)
    args = TrainingArguments(
        output_dir=str(MODEL_OUT_DIR / "checkpoints"),
        num_train_epochs=5,
        per_device_train_batch_size=16,
        per_device_eval_batch_size=32,
        learning_rate=2e-5,
        weight_decay=0.01,
        warmup_ratio=0.1,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="accuracy",
        greater_is_better=True,
        logging_steps=10,
        save_total_limit=2,
        report_to="none",
        bf16=torch.cuda.is_available(),  # bf16 (DeBERTa-v3 incompatible avec fp16 grad scaler)
        seed=42,
    )

    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=tokenized["train"],
        eval_dataset=tokenized["validation"],
        processing_class=tokenizer,  # transformers 5.x renamed `tokenizer` → `processing_class`
        data_collator=data_collator,
        compute_metrics=compute_metrics,
    )

    logger.info("=== Starting training ===")
    train_result = trainer.train()
    logger.info(f"Training done : {train_result.metrics}")

    logger.info("=== Final evaluation on validation ===")
    eval_result = trainer.evaluate()
    logger.info(f"Eval : {eval_result}")

    logger.info(f"Saving model to {MODEL_OUT_DIR} ...")
    trainer.save_model(str(MODEL_OUT_DIR))
    tokenizer.save_pretrained(str(MODEL_OUT_DIR))

    # Persist final eval as JSON for downstream
    metrics_path = MODEL_OUT_DIR / "training_metrics.json"
    metrics_path.write_text(
        json.dumps({"train": train_result.metrics, "eval": eval_result},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"Persisted metrics → {metrics_path}")
    logger.info("Done.")


if __name__ == "__main__":
    sys.exit(main())
