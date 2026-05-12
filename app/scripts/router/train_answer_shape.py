"""
Re-train XLM-RoBERTa-base sur answer_shape (5 classes pré-retrieval).

Données : /app/data/router/v3/{train,val}.jsonl
Output : /app/data/router/v3/model/

Hyperparams identiques au train run 2 qui marchait : 5 epochs, bf16, lr 2e-5, batch 16.
"""
from __future__ import annotations
import json
import logging
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

DATA_DIR = Path("/app/data/router/v3")
MODEL_OUT_DIR = DATA_DIR / "model"
MODEL_NAME = "FacebookAI/xlm-roberta-base"

NUM_LABELS = 5
LABEL_NAMES = ["causal_explicit", "comparison_explicit", "list", "scalar_factual", "temporal"]
ID2LABEL = {i: n for i, n in enumerate(LABEL_NAMES)}
LABEL2ID = {n: i for i, n in enumerate(LABEL_NAMES)}


def compute_metrics(eval_pred):
    logits, labels = eval_pred
    if isinstance(logits, tuple):
        logits = logits[0]
    preds = np.argmax(logits, axis=-1)
    top1 = float((preds == labels).mean())
    top2_indices = np.argsort(logits, axis=-1)[:, -2:]
    top2 = float(np.array([labels[i] in top2_indices[i] for i in range(len(labels))]).mean())

    f1_per_class = []
    for cls in range(NUM_LABELS):
        tp = int(((preds == cls) & (labels == cls)).sum())
        fp = int(((preds == cls) & (labels != cls)).sum())
        fn = int(((preds != cls) & (labels == cls)).sum())
        if tp + fp == 0 or tp + fn == 0:
            f1_per_class.append(0.0); continue
        p, r = tp / (tp + fp), tp / (tp + fn)
        f1_per_class.append(2 * p * r / (p + r) if (p + r) > 0 else 0.0)
    return {"accuracy": top1, "top2_accuracy": top2, "f1_macro": float(np.mean(f1_per_class))}


def main():
    MODEL_OUT_DIR.mkdir(parents=True, exist_ok=True)
    raw = load_dataset("json", data_files={
        "train": str(DATA_DIR / "train.jsonl"),
        "validation": str(DATA_DIR / "val.jsonl"),
    })
    logger.info(f"Train: {len(raw['train'])}, Val: {len(raw['validation'])}")

    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForSequenceClassification.from_pretrained(
        MODEL_NAME, num_labels=NUM_LABELS, id2label=ID2LABEL, label2id=LABEL2ID,
    )

    def tokenize(b): return tokenizer(b["text"], truncation=True, max_length=128)
    tokenized = raw.map(tokenize, batched=True)
    tokenized = tokenized.remove_columns([c for c in tokenized["train"].column_names
                                           if c not in ("input_ids", "attention_mask", "label")])

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
        logging_steps=20,
        save_total_limit=2,
        report_to="none",
        bf16=torch.cuda.is_available(),
        seed=42,
    )

    trainer = Trainer(
        model=model, args=args,
        train_dataset=tokenized["train"], eval_dataset=tokenized["validation"],
        processing_class=tokenizer,
        data_collator=DataCollatorWithPadding(tokenizer=tokenizer),
        compute_metrics=compute_metrics,
    )

    logger.info("=== Training ===")
    train_result = trainer.train()
    logger.info(f"Done : {train_result.metrics}")

    eval_result = trainer.evaluate()
    logger.info(f"Eval : {eval_result}")

    trainer.save_model(str(MODEL_OUT_DIR))
    tokenizer.save_pretrained(str(MODEL_OUT_DIR))
    (MODEL_OUT_DIR / "training_metrics.json").write_text(
        json.dumps({"train": train_result.metrics, "eval": eval_result},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Saved to {MODEL_OUT_DIR}")


if __name__ == "__main__":
    main()
