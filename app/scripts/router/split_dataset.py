"""
S2.A.2 — Split train/val stratifié pour router_training_set.

Stratification par (primary_type, language) pour préserver l'équilibre.
Output : train.jsonl + val.jsonl dans data/router/.

Ratio par défaut : 80/20 → 392 train + 98 val sur 490q.

Usage :
  docker exec knowbase-app python /app/scripts/router/split_dataset.py
"""
from __future__ import annotations
import json
import random
from collections import defaultdict
from pathlib import Path

import os
INPUT_PATH = Path(os.getenv("ROUTER_TRAIN_INPUT", "/app/benchmark/questions/router_training_set_v2.json"))
OUTPUT_DIR = Path("/app/data/router")
TRAIN_RATIO = 0.80
SEED = 42

# Label encoding (ordre alphabétique pour cohérence)
LABEL_NAMES = ["causal", "comparison", "factual", "false_premise", "list", "temporal", "unanswerable"]
LABEL2ID = {name: i for i, name in enumerate(LABEL_NAMES)}
ID2LABEL = {i: name for name, i in LABEL2ID.items()}


def stratified_split(questions: list[dict], train_ratio: float, seed: int) -> tuple[list, list]:
    """Split stratifié par (primary_type, language)."""
    rng = random.Random(seed)
    by_strata: dict[tuple, list] = defaultdict(list)
    for q in questions:
        key = (q["primary_type"], q["language"])
        by_strata[key].append(q)

    train, val = [], []
    for key, items in by_strata.items():
        rng.shuffle(items)
        n_train = int(round(len(items) * train_ratio))
        train.extend(items[:n_train])
        val.extend(items[n_train:])

    rng.shuffle(train)
    rng.shuffle(val)
    return train, val


def to_hf_record(q: dict) -> dict:
    """Format compatible HF Trainer : text + label int."""
    return {
        "id": q["id"],
        "text": q["question"],
        "label": LABEL2ID[q["primary_type"]],
        "label_name": q["primary_type"],
        "language": q["language"],
        "domain": q.get("domain"),
        "difficulty": q.get("difficulty"),
    }


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    data = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    qs = data["questions"]
    print(f"Loaded {len(qs)} questions from {INPUT_PATH}")

    train, val = stratified_split(qs, TRAIN_RATIO, SEED)
    print(f"Split : {len(train)} train + {len(val)} val (ratio {TRAIN_RATIO})")

    # Persist as JSONL (1 record/line) — standard format HF datasets
    train_path = OUTPUT_DIR / "train.jsonl"
    val_path = OUTPUT_DIR / "val.jsonl"
    label_meta_path = OUTPUT_DIR / "label_mapping.json"

    with train_path.open("w", encoding="utf-8") as f:
        for q in train:
            f.write(json.dumps(to_hf_record(q), ensure_ascii=False) + "\n")
    with val_path.open("w", encoding="utf-8") as f:
        for q in val:
            f.write(json.dumps(to_hf_record(q), ensure_ascii=False) + "\n")
    label_meta_path.write_text(
        json.dumps({"label2id": LABEL2ID, "id2label": ID2LABEL, "labels": LABEL_NAMES},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {train_path}, {val_path}, {label_meta_path}")

    # Verify distribution
    from collections import Counter
    print("\n=== TRAIN distribution ===")
    print(f"By label: {dict(Counter(r['label_name'] for r in [to_hf_record(q) for q in train]))}")
    print(f"By lang : {dict(Counter(r['language'] for r in [to_hf_record(q) for q in train]))}")
    print("\n=== VAL distribution ===")
    print(f"By label: {dict(Counter(r['label_name'] for r in [to_hf_record(q) for q in val]))}")
    print(f"By lang : {dict(Counter(r['language'] for r in [to_hf_record(q) for q in val]))}")


if __name__ == "__main__":
    main()
