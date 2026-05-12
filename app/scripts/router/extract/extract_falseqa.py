"""S2.A.1.b — FalseQA (thunlp) → false_premise. EN seulement, label=1 = false_premise."""
from __future__ import annotations
import csv
import json
import random
from pathlib import Path
from collections import Counter

DATA_DIR = Path("/app/data/router/external")
OUTPUT_PATH = DATA_DIR / "falseqa_extracted.jsonl"
SEED = 42


def main():
    rng = random.Random(SEED)
    items = []
    for fname in ("falseqa_train.csv", "falseqa_test.csv"):
        path = DATA_DIR / fname
        with path.open() as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("label") == "1":  # false_premise
                    items.append(row["question"].strip())
    print(f"Loaded {len(items)} FalseQA false_premise questions")

    rng.shuffle(items)
    records = []
    for q in items:
        if len(q) < 20 or len(q) > 300:
            continue
        records.append({
            "id": f"ROUTER_EXT_FALSEQA_EN_FALSE_PREMISE_{len(records):04d}",
            "question": q,
            "language": "en",
            "domain": "wikipedia",
            "primary_type": "false_premise",
            "difficulty": "medium",
            "source": "falseqa",
            "qualifiers": {
                "has_temporal_marker": False,
                "has_negation": " not " in q.lower() or "n't" in q.lower(),
                "has_conditional": False,
                "is_meta_question": False,
                "has_false_premise": True,
            },
        })

    print(f"Generated {len(records)} records")
    print(f"By difficulty: {Counter(r['difficulty'] for r in records)}")
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Persisted → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
