"""
S2.A.1.b — Extraction temporal + causal + list depuis Mintaka via filtres patterns.

Mintaka est multi-domaine et bilingue FR/EN, donc on peut filtrer ses 20K questions
pour extraire celles qui correspondent à nos types non-couverts (temporal/causal/list).

Filtres FR + EN :
  temporal : when, what year, which version, in which century, quel...année, quand, en quelle année
  causal   : why, what causes, what reason, pourquoi, pour quelle raison
  list     : list, which X are, name X, lister, énumérer, quels sont les
"""
from __future__ import annotations
import json
import random
import re
from collections import Counter
from pathlib import Path

DATA_DIR = Path("/app/data/router/external")
SEED = 42

# Filtre patterns
TEMPORAL_PATTERNS = [
    r"\bwhen\b", r"\bwhat year\b", r"\bin what year\b", r"\bwhich year\b",
    r"\bwhich version\b", r"\bwhich edition\b", r"\bwhich era\b",
    r"\bin what month\b", r"\bin what date\b", r"\bwhat date\b",
    r"\bquand\b", r"\ben quelle année\b", r"\ben quel mois\b",
    r"\bquelle année\b", r"\bquel mois\b", r"\bquelle date\b",
    r"\bquelle version\b", r"\bquelle édition\b",
]
CAUSAL_PATTERNS = [
    r"\bwhy\b", r"\bwhat caused\b", r"\bwhat causes\b", r"\bwhat reason\b",
    r"\bfor what reason\b", r"\bhow come\b",
    r"\bpourquoi\b", r"\bpour quelle raison\b", r"\bpour quel motif\b",
    r"\bquelle cause\b", r"\bquelles raisons\b",
]
# list_patterns kept restrictive — Mintaka rarely has true enumeration questions
LIST_PATTERNS = [
    r"\blist (the|all)\b",
    r"\bname all\b", r"\bname the\b", r"\bwhich .{1,30} are\b",
    r"\blister\b", r"\bénumérer\b", r"\bquels sont les\b", r"\bquelles sont les\b",
]

PATTERNS = {
    "temporal": [re.compile(p, re.IGNORECASE) for p in TEMPORAL_PATTERNS],
    "causal": [re.compile(p, re.IGNORECASE) for p in CAUSAL_PATTERNS],
    "list": [re.compile(p, re.IGNORECASE) for p in LIST_PATTERNS],
}


def detect_type(text: str) -> str | None:
    for t, regexes in PATTERNS.items():
        if any(rx.search(text) for rx in regexes):
            return t
    return None


def main():
    rng = random.Random(SEED)
    all_qs = []
    for split in ("train", "dev", "test"):
        with open(DATA_DIR / f"mintaka_{split}.json") as f:
            all_qs.extend(json.load(f))
    print(f"Loaded {len(all_qs)} Mintaka")

    by_type_lang: dict = {("temporal", "en"): [], ("temporal", "fr"): [],
                          ("causal", "en"): [], ("causal", "fr"): [],
                          ("list", "en"): [], ("list", "fr"): []}

    for q in all_qs:
        en_text = q.get("question", "") or ""
        fr_text = (q.get("translations", {}) or {}).get("fr", "") or ""
        for lang, text in (("en", en_text), ("fr", fr_text)):
            t = detect_type(text)
            if t:
                by_type_lang[(t, lang)].append((q, text))

    print("\nDetected by type & lang:")
    for k, v in by_type_lang.items():
        print(f"  {k} : {len(v)}")

    # Sample max 800 per type total (≈ 400 EN + 400 FR or balanced as available)
    out_records = []
    for typ in ("temporal", "causal", "list"):
        en_items = by_type_lang[(typ, "en")]
        fr_items = by_type_lang[(typ, "fr")]
        rng.shuffle(en_items); rng.shuffle(fr_items)
        n_each = min(400, len(en_items), len(fr_items)) if min(len(en_items), len(fr_items)) > 0 else 0
        if n_each == 0:
            n_each = max(len(en_items), len(fr_items)) // 2

        for q, text in en_items[:n_each]:
            out_records.append({
                "id": f"ROUTER_EXT_MINTAKA_FILT_EN_{typ.upper()}_{len(out_records):04d}",
                "question": text.strip(),
                "language": "en",
                "domain": "wikipedia",
                "primary_type": typ,
                "difficulty": "medium",
                "source": "mintaka_filtered",
                "source_id": q["id"],
                "complexity_type_orig": q.get("complexityType"),
                "qualifiers": {
                    "has_temporal_marker": typ == "temporal",
                    "has_negation": " not " in text.lower() or "n't" in text.lower(),
                    "has_conditional": False,
                    "is_meta_question": False,
                    "has_false_premise": False,
                },
            })
        for q, text in fr_items[:n_each]:
            out_records.append({
                "id": f"ROUTER_EXT_MINTAKA_FILT_FR_{typ.upper()}_{len(out_records):04d}",
                "question": text.strip(),
                "language": "fr",
                "domain": "wikipedia",
                "primary_type": typ,
                "difficulty": "medium",
                "source": "mintaka_filtered",
                "source_id": q["id"],
                "complexity_type_orig": q.get("complexityType"),
                "qualifiers": {
                    "has_temporal_marker": typ == "temporal",
                    "has_negation": " ne " in text.lower() or " n'" in text.lower(),
                    "has_conditional": False,
                    "is_meta_question": False,
                    "has_false_premise": False,
                },
            })

    print(f"\nGenerated {len(out_records)} records")
    print(f"By type : {Counter(r['primary_type'] for r in out_records)}")
    print(f"By lang : {Counter(r['language'] for r in out_records)}")

    out_path = DATA_DIR / "mintaka_filtered_extracted.jsonl"
    with out_path.open("w", encoding="utf-8") as f:
        for r in out_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Persisted → {out_path}")

    print("\nSamples per type:")
    seen = set()
    for r in out_records:
        key = (r["primary_type"], r["language"])
        if key not in seen:
            seen.add(key)
            print(f"  [{key}] {r['question'][:120]}")


if __name__ == "__main__":
    main()
