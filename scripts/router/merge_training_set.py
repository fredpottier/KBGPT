"""
S2.A.1.b — Merge tous les datasets extraits + 490 humaines en un seul training set étendu.

Sources :
  - benchmark/questions/router_training_set.json (490 humaines, 10 domaines, 7 types)
  - data/router/external/mintaka_extracted.jsonl
  - data/router/external/mintaka_filtered_extracted.jsonl
  - data/router/external/squad2_unanswerable.jsonl
  - data/router/external/squad2_causal.jsonl
  - data/router/external/hotpotqa_extracted.jsonl
  - data/router/external/falseqa_extracted.jsonl

Output : benchmark/questions/router_training_set_v2.json
"""
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path

ROOT = Path("/app")
HUMAN_PATH = ROOT / "benchmark/questions/router_training_set.json"
EXTERNAL_DIR = ROOT / "data/router/external"
OUT_PATH = ROOT / "benchmark/questions/router_training_set_v2.json"

EXTERNAL_FILES = [
    "mintaka_extracted.jsonl",
    "mintaka_filtered_extracted.jsonl",
    "squad2_unanswerable.jsonl",
    "squad2_causal.jsonl",
    "hotpotqa_extracted.jsonl",
    "falseqa_extracted.jsonl",
    "translated_fr.jsonl",  # Qwen-72B translations EN→FR (3900 sur causal/list/unans/falseprem)
]


def load_jsonl(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def main():
    # 1. Load humaines
    human_data = json.loads(HUMAN_PATH.read_text(encoding="utf-8"))
    human_qs = human_data["questions"]
    for q in human_qs:
        q["source"] = "manual_human"
    print(f"Loaded {len(human_qs)} human questions")

    # 2. Load externals
    all_external = []
    for fname in EXTERNAL_FILES:
        path = EXTERNAL_DIR / fname
        if not path.exists():
            print(f"  WARNING: missing {fname}")
            continue
        items = load_jsonl(path)
        print(f"  {fname}: {len(items)}")
        all_external.extend(items)

    # 3. Merge + dedup by question text (case-insensitive)
    seen_text = set()
    merged = []
    duplicates = 0
    for q in human_qs + all_external:
        key = q["question"].lower().strip()
        if key in seen_text:
            duplicates += 1
            continue
        seen_text.add(key)
        merged.append(q)
    print(f"\nMerged: {len(merged)} (deduplicated {duplicates})")

    # 4. Stats
    print("\n=== DISTRIBUTION ===")
    print(f"By source     : {dict(Counter(q.get('source', 'unknown') for q in merged))}")
    print(f"By primary_type: {dict(Counter(q['primary_type'] for q in merged))}")
    print(f"By language   : {dict(Counter(q['language'] for q in merged))}")
    by_type_lang = Counter((q['primary_type'], q['language']) for q in merged)
    print("\nBy (type, language):")
    for k, v in sorted(by_type_lang.items()):
        print(f"  {k}: {v}")

    # 5. Persist
    output = {
        "schema_version": "router_training_v2",
        "description": "Training set étendu : 490 humaines + datasets externes (Mintaka/SQuAD2/HotpotQA/FalseQA). Cible 10K, atteinte ~11K.",
        "sources": {
            "manual_human": "490 questions FR/EN, 10 domaines, 7 types",
            "mintaka": "AmazonScience Mintaka, 14K train (CC-BY-4.0), Wikipedia entities, factual+comparison + filtered temporal/list/causal",
            "squad2": "Stanford SQuAD 2.0 (CC-BY-SA-4.0), Wikipedia, unanswerable + causal filtered",
            "hotpotqa": "CMU/Stanford HotpotQA (CC-BY-SA-4.0), multi-hop, list+causal filtered",
            "falseqa": "thunlp FalseQA (MIT), false_premise label=1",
        },
        "questions": merged,
    }
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nPersisted → {OUT_PATH}")
    print(f"File size: {OUT_PATH.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
