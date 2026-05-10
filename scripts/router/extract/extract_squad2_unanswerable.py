"""
S2.A.1.b — Extraction SQuAD 2.0 unanswerable → format router_training_set.

SQuAD 2.0 (Stanford, ~150K questions, CC-BY-SA-4.0) contient ~50K questions
explicitement marquées `is_impossible=True` = unanswerable.

EN seulement → on extrait EN, traduction FR via Qwen-72B en étape suivante.

Usage :
  docker exec knowbase-app python /app/scripts/router/extract/extract_squad2_unanswerable.py [--limit 1500]
"""
from __future__ import annotations
import argparse
import json
import random
from collections import Counter
from pathlib import Path

DATA_DIR = Path("/app/data/router/external")
OUTPUT_PATH = Path("/app/data/router/external/squad2_unanswerable.jsonl")
SEED = 42


def extract_unanswerable(squad_data: dict) -> list[dict]:
    """Iterate SQuAD format → flat list of unanswerable questions."""
    out = []
    for article in squad_data["data"]:
        title = article.get("title", "")
        for para in article.get("paragraphs", []):
            for q in para.get("qas", []):
                if q.get("is_impossible"):
                    out.append({
                        "id": q["id"],
                        "question": q["question"],
                        "title": title,
                    })
    return out


def to_router_record(q: dict, idx: int) -> dict | None:
    text = q["question"].strip()
    if len(text) < 20:
        return None
    return {
        "id": f"ROUTER_EXT_SQUAD2_EN_UNANSWERABLE_{idx:04d}",
        "question": text,
        "language": "en",
        "domain": "wikipedia",
        "primary_type": "unanswerable",
        "difficulty": "medium",
        "source": "squad2",
        "source_id": q["id"],
        "source_title": q.get("title"),
        "qualifiers": {
            "has_temporal_marker": False,
            "has_negation": "not " in text.lower() or "n't" in text.lower(),
            "has_conditional": False,
            "is_meta_question": False,
            "has_false_premise": False,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=1500)
    args = parser.parse_args()

    rng = random.Random(SEED)
    all_unans = []
    for split in ("train", "dev"):
        with open(DATA_DIR / f"squad2_{split}.json") as f:
            data = json.load(f)
        items = extract_unanswerable(data)
        print(f"[{split}] {len(items)} unanswerable")
        all_unans.extend(items)

    print(f"\nTotal unanswerable : {len(all_unans)}")
    rng.shuffle(all_unans)
    sample = all_unans[: args.limit * 2]  # over-sample to compensate filtered

    records = []
    for q in sample:
        r = to_router_record(q, len(records))
        if r is not None:
            records.append(r)
        if len(records) >= args.limit:
            break

    print(f"Generated {len(records)} router records")
    print(f"By difficulty : {Counter(r['difficulty'] for r in records)}")

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nPersisted → {OUTPUT_PATH}")
    print(f"\nSample (3 records):")
    for r in records[:3]:
        print(f"  {r['id']}: {r['question'][:100]}")


if __name__ == "__main__":
    main()
