"""
Split train/val v3 — utilise gold_answer_shape (5 classes) comme label.

Stratification par (gold_answer_shape, language).
Output : data/router/v3/{train,val}.jsonl + label_mapping_v3.json
"""
from __future__ import annotations
import json
import random
from collections import defaultdict, Counter
from pathlib import Path

INPUT_PATH = Path("/app/benchmark/questions/router_training_set_v3.json")
OUTPUT_DIR = Path("/app/data/router/v3")
TRAIN_RATIO = 0.80
SEED = 42

LABEL_NAMES = ["causal_explicit", "comparison_explicit", "list", "scalar_factual", "temporal"]
LABEL2ID = {name: i for i, name in enumerate(LABEL_NAMES)}
ID2LABEL = {i: name for i, name in enumerate(LABEL_NAMES)}


def stratified_split(questions, train_ratio, seed):
    rng = random.Random(seed)
    by_strata = defaultdict(list)
    for q in questions:
        key = (q["gold_answer_shape"], q["language"])
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


def to_hf(q):
    return {
        "id": q["id"],
        "text": q["question"],
        "label": LABEL2ID[q["gold_answer_shape"]],
        "label_name": q["gold_answer_shape"],
        "language": q["language"],
        "epistemic": q["gold_epistemic_status"],
    }


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data = json.loads(INPUT_PATH.read_text(encoding="utf-8"))
    questions = data["questions"]
    print(f"Loaded {len(questions)} v3 questions")

    train, val = stratified_split(questions, TRAIN_RATIO, SEED)
    print(f"Split : {len(train)} train + {len(val)} val")

    with (OUTPUT_DIR / "train.jsonl").open("w", encoding="utf-8") as f:
        for q in train:
            f.write(json.dumps(to_hf(q), ensure_ascii=False) + "\n")
    with (OUTPUT_DIR / "val.jsonl").open("w", encoding="utf-8") as f:
        for q in val:
            f.write(json.dumps(to_hf(q), ensure_ascii=False) + "\n")
    (OUTPUT_DIR / "label_mapping.json").write_text(
        json.dumps({"label2id": LABEL2ID, "id2label": ID2LABEL, "labels": LABEL_NAMES},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n=== TRAIN ===")
    print(f"By label: {dict(Counter(to_hf(q)['label_name'] for q in train))}")
    print(f"By lang : {dict(Counter(q['language'] for q in train))}")
    print(f"\n=== VAL ===")
    print(f"By label: {dict(Counter(to_hf(q)['label_name'] for q in val))}")


if __name__ == "__main__":
    main()
