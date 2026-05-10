"""
S2.A.1.b — Extraction HotpotQA pour causal + list.

HotpotQA (CMU/Stanford, ~113K questions multi-hop, CC-BY-SA-4.0). EN seulement.
On filtre par patterns linguistiques pour récupérer questions causal/list.

Output : EN questions, traduction FR à faire séparément si besoin.
"""
from __future__ import annotations
import json
import random
import re
from collections import Counter
from pathlib import Path

DATA_DIR = Path("/app/data/router/external")
SEED = 42

# Patterns plus larges qu'avec Mintaka pour capturer plus de causal
CAUSAL_PATTERNS = [
    r"^why ", r"^why,", r"^why\?",
    r"\bwhat caused\b", r"\bwhat causes\b", r"\bwhat was the cause\b",
    r"\bwhat reason\b", r"\bfor what reason\b", r"\bwhat led to\b",
    r"\bwhat made\b", r"\bwhat motivated\b", r"\bhow come\b",
    r"\bwhat drove\b", r"\bwhat triggered\b", r"\bwhat prompted\b",
]
LIST_PATTERNS = [
    r"^which of (the|these)\b",
    r"^name (the|all|three|four|five|two)\b",
    r"^list (the|all)\b",
    r"^name some\b",
    r"^which .{1,40}\bare\b",
    r"^what are the .{1,40}\b(of|in|that)\b",
]


def detect_type(text: str) -> str | None:
    text_lc = text.lower().strip()
    for rx in CAUSAL_PATTERNS:
        if re.search(rx, text_lc):
            return "causal"
    for rx in LIST_PATTERNS:
        if re.search(rx, text_lc):
            return "list"
    return None


def main():
    rng = random.Random(SEED)
    all_qs = []
    for fname in ("hotpot_train.json", "hotpot_dev.json"):
        path = DATA_DIR / fname
        if not path.exists():
            continue
        print(f"Loading {fname} ...")
        with open(path) as f:
            data = json.load(f)
        for q in data:
            all_qs.append({"id": q.get("_id", ""), "question": q.get("question", "")})
    print(f"Loaded {len(all_qs)} HotpotQA questions")

    by_type = {"causal": [], "list": []}
    for q in all_qs:
        t = detect_type(q["question"])
        if t:
            by_type[t].append(q)

    print(f"\nCausal matches : {len(by_type['causal'])}")
    print(f"List matches   : {len(by_type['list'])}")

    records = []
    for typ, items in by_type.items():
        rng.shuffle(items)
        # Take up to 1300 causal, 1200 list
        n_target = 1300 if typ == "causal" else 1200
        for q in items[:n_target]:
            text = q["question"].strip()
            if len(text) < 20 or len(text) > 300:
                continue
            records.append({
                "id": f"ROUTER_EXT_HOTPOT_EN_{typ.upper()}_{len(records):04d}",
                "question": text,
                "language": "en",
                "domain": "wikipedia",
                "primary_type": typ,
                "difficulty": "medium",
                "source": "hotpotqa",
                "source_id": q["id"],
                "qualifiers": {
                    "has_temporal_marker": False,
                    "has_negation": " not " in text.lower() or "n't" in text.lower(),
                    "has_conditional": False,
                    "is_meta_question": False,
                    "has_false_premise": False,
                },
            })

    print(f"\nGenerated {len(records)} records")
    print(f"By type : {Counter(r['primary_type'] for r in records)}")

    out_path = DATA_DIR / "hotpotqa_extracted.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Persisted → {out_path}")

    print("\n=== Samples ===")
    causal_samples = [r for r in records if r["primary_type"] == "causal"][:3]
    list_samples = [r for r in records if r["primary_type"] == "list"][:3]
    for r in causal_samples + list_samples:
        print(f"  [{r['primary_type']}] {r['question'][:140]}")


if __name__ == "__main__":
    main()
