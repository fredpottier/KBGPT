"""
S2.A.1.b — Extraction Mintaka → format router_training_set.

Mintaka (AmazonScience, 20K questions, CC-BY-4.0) couvre `factual` et `comparison`.
Les traductions FR sont incluses dans le dataset (clé `translations.fr`).

Mapping complexityType → notre type :
  count, ordinal, intersection, generic, superlative, multihop, yesno → factual
  comparative, difference                                              → comparison

Domaines Mintaka (Wikipedia) → on tagge `wikipedia` (onzième domaine, complément aux 10 originaux).

Usage :
  docker exec knowbase-app python /app/scripts/router/extract/extract_mintaka.py [--limit 4000]
"""
from __future__ import annotations
import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

DATA_DIR = Path("/app/data/router/external")
OUTPUT_PATH = Path("/app/data/router/external/mintaka_extracted.jsonl")
SEED = 42

# Mapping complexityType → primary_type
TYPE_MAPPING_FACTUAL = {"count", "ordinal", "intersection", "generic", "superlative", "multihop", "yesno"}
TYPE_MAPPING_COMPARISON = {"comparative", "difference"}


def load_all_mintaka():
    """Concat train + dev + test (20K total)."""
    all_qs = []
    for split in ("train", "dev", "test"):
        with open(DATA_DIR / f"mintaka_{split}.json") as f:
            for q in json.load(f):
                q["source_split"] = split
                all_qs.append(q)
    return all_qs


def to_router_record(q: dict, language: str, primary_type: str, idx: int) -> dict | None:
    """Format compatible avec router_training_set.json (mêmes champs que mes 490q)."""
    if language == "en":
        text = q.get("question", "")
    else:
        text = q.get("translations", {}).get(language, "")
    text = (text or "").strip()
    if len(text) < 20:  # questions trop courtes = bruit
        return None
    if "{" in text or "[" in text:  # placeholder cassé
        return None

    # Difficulty heuristic basé sur complexityType
    ct = q["complexityType"]
    if ct in {"generic", "yesno"}:
        difficulty = "easy"
    elif ct in {"ordinal", "comparative", "count"}:
        difficulty = "medium"
    else:  # intersection, superlative, multihop, difference
        difficulty = "hard"

    return {
        "id": f"ROUTER_EXT_MINTAKA_{language.upper()}_{primary_type.upper()}_{idx:04d}",
        "question": text,
        "language": language,
        "domain": "wikipedia",
        "primary_type": primary_type,
        "difficulty": difficulty,
        "source": "mintaka",
        "source_id": q["id"],
        "complexity_type_orig": ct,
        "category_orig": q.get("category"),
        "qualifiers": {
            "has_temporal_marker": False,  # Mintaka peu de marqueurs temporels explicites
            "has_negation": "not" in text.lower() or " ne " in text.lower() or " n'" in text.lower(),
            "has_conditional": False,
            "is_meta_question": False,
            "has_false_premise": False,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit-factual", type=int, default=2500,
                        help="Total factual questions to extract (split FR/EN 50/50)")
    parser.add_argument("--limit-comparison", type=int, default=1500,
                        help="Total comparison questions to extract (split FR/EN 50/50)")
    args = parser.parse_args()

    rng = random.Random(SEED)
    all_qs = load_all_mintaka()
    print(f"Loaded {len(all_qs)} Mintaka questions")

    # Group by primary_type then by complexityType for balanced sampling
    factual_by_ct = defaultdict(list)
    comparison_by_ct = defaultdict(list)
    for q in all_qs:
        ct = q["complexityType"]
        if ct in TYPE_MAPPING_FACTUAL:
            factual_by_ct[ct].append(q)
        elif ct in TYPE_MAPPING_COMPARISON:
            comparison_by_ct[ct].append(q)

    print(f"\nfactual sub-types: {dict((k, len(v)) for k, v in factual_by_ct.items())}")
    print(f"comparison sub-types: {dict((k, len(v)) for k, v in comparison_by_ct.items())}")

    def sample_balanced(by_ct: dict, n_total: int) -> list:
        """Sample n_total questions balanced across complexityType buckets."""
        if not by_ct:
            return []
        n_per_bucket = n_total // len(by_ct)
        out = []
        for ct, items in by_ct.items():
            rng.shuffle(items)
            out.extend(items[:n_per_bucket])
        return out

    # Sample (FR + EN 50/50, donc on échantillonne moitié de chaque limit pour 1 langue)
    n_fact_per_lang = args.limit_factual // 2
    n_comp_per_lang = args.limit_comparison // 2

    factual_questions = sample_balanced(factual_by_ct, n_fact_per_lang)
    comparison_questions = sample_balanced(comparison_by_ct, n_comp_per_lang)

    records = []
    idx = 0
    for q in factual_questions:
        for lang in ("en", "fr"):
            r = to_router_record(q, lang, "factual", idx)
            if r is not None:
                records.append(r); idx += 1
    for q in comparison_questions:
        for lang in ("en", "fr"):
            r = to_router_record(q, lang, "comparison", idx)
            if r is not None:
                records.append(r); idx += 1

    rng.shuffle(records)
    print(f"\nGenerated {len(records)} router records")
    print(f"By primary_type: {Counter(r['primary_type'] for r in records)}")
    print(f"By language    : {Counter(r['language'] for r in records)}")
    print(f"By difficulty  : {Counter(r['difficulty'] for r in records)}")

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nPersisted → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
