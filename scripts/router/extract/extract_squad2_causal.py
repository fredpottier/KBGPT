"""S2.A.1.b — Extraction SQuAD 2.0 causal via filter pattern (Why...)."""
from __future__ import annotations
import json
import random
import re
from collections import Counter
from pathlib import Path

DATA_DIR = Path("/app/data/router/external")
OUTPUT_PATH = DATA_DIR / "squad2_causal.jsonl"
SEED = 42

CAUSAL_PATTERNS = [
    re.compile(r"^why\s", re.IGNORECASE),
    re.compile(r"^why,", re.IGNORECASE),
    re.compile(r"\bwhat caused\b", re.IGNORECASE),
    re.compile(r"\bwhat causes\b", re.IGNORECASE),
    re.compile(r"\bwhat was the cause\b", re.IGNORECASE),
    re.compile(r"\bwhat reason\b", re.IGNORECASE),
    re.compile(r"\bfor what reason\b", re.IGNORECASE),
    re.compile(r"\bwhat led to\b", re.IGNORECASE),
    re.compile(r"\bhow come\b", re.IGNORECASE),
    re.compile(r"\bwhat motivated\b", re.IGNORECASE),
]


def is_causal(text: str) -> bool:
    return any(rx.search(text) for rx in CAUSAL_PATTERNS)


def main():
    rng = random.Random(SEED)
    causal_qs = []

    for split in ("train", "dev"):
        with open(DATA_DIR / f"squad2_{split}.json") as f:
            data = json.load(f)
        for article in data["data"]:
            for para in article.get("paragraphs", []):
                for q in para.get("qas", []):
                    if q.get("is_impossible"):
                        continue  # only answerable
                    if is_causal(q["question"]):
                        causal_qs.append({"id": q["id"], "question": q["question"]})

    print(f"SQuAD2 answerable causal pattern matches: {len(causal_qs)}")

    rng.shuffle(causal_qs)
    records = []
    for q in causal_qs[:1300]:
        text = q["question"].strip()
        if len(text) < 20 or len(text) > 300:
            continue
        records.append({
            "id": f"ROUTER_EXT_SQUAD2_EN_CAUSAL_{len(records):04d}",
            "question": text,
            "language": "en",
            "domain": "wikipedia",
            "primary_type": "causal",
            "difficulty": "medium",
            "source": "squad2_filtered",
            "source_id": q["id"],
            "qualifiers": {
                "has_temporal_marker": False,
                "has_negation": " not " in text.lower() or "n't" in text.lower(),
                "has_conditional": False,
                "is_meta_question": False,
                "has_false_premise": False,
            },
        })

    print(f"Generated {len(records)} causal records")
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Persisted → {OUTPUT_PATH}")
    print("\nSamples:")
    for r in records[:5]:
        print(f"  {r['question'][:130]}")


if __name__ == "__main__":
    main()
