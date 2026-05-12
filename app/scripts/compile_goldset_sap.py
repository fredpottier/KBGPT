"""Parse le markdown rempli par le user et compile en gold_set_sap_v1.json.
Audit qualité : champs vides, placeholders restés, JSON malformés."""
import json
import re
from pathlib import Path

src = Path("/app/benchmark/questions/gold_set_sap_v1_sources.md")
out_json = Path("/app/benchmark/questions/gold_set_sap_v1.json")
out_audit = Path("/app/benchmark/questions/gold_set_sap_v1_audit.md")

content = src.read_text(encoding="utf-8")

# Extract all JSON blocks
json_blocks = re.findall(r"```json\s*\n(.*?)\n```", content, re.DOTALL)
print(f"JSON blocks found: {len(json_blocks)}")

audit = ["# Audit gold-set SAP v1\n"]
audit.append(f"Total blocks: {len(json_blocks)}\n\n")

compiled = []
issues = []

PLACEHOLDER_PATTERNS = [
    "<TO FILL",
    "<liste mots-clés",
    "<liste doc_ids",
    "<liste",
]

for i, block in enumerate(json_blocks, 1):
    try:
        # Strip leading whitespace each line and parse
        data = json.loads(block)
    except json.JSONDecodeError as e:
        issues.append(f"Q{i}: JSON malformé — {e}")
        continue

    qid = data.get("id", f"BLOCK_{i}")
    q = data.get("question", "")
    gt = data.get("ground_truth", {})
    answer = gt.get("answer", "")
    identifiers = gt.get("exact_identifiers", [])
    docs = gt.get("supporting_doc_ids", [])

    problems = []
    if not answer or any(p in answer for p in PLACEHOLDER_PATTERNS):
        problems.append("answer placeholder/vide")
    if not identifiers or any(isinstance(x, str) and any(p in x for p in PLACEHOLDER_PATTERNS) for x in identifiers):
        problems.append("exact_identifiers placeholder/vide")
    if not docs or any(isinstance(x, str) and any(p in x for p in PLACEHOLDER_PATTERNS) for x in docs):
        problems.append("supporting_doc_ids placeholder/vide")

    if problems:
        issues.append(f"{qid} | {q[:80]}... | issues: {', '.join(problems)}")

    compiled.append(data)

# Write compiled
out_json.write_text(json.dumps(compiled, indent=2, ensure_ascii=False), encoding="utf-8")

# Write audit
audit.append(f"## Compilation: {len(compiled)} questions extraites\n\n")
audit.append(f"## Issues détectées: {len(issues)}\n\n")
for line in issues:
    audit.append(f"- {line}\n")
out_audit.write_text("".join(audit), encoding="utf-8")

# Console summary
print(f"\n=== Compilé: {len(compiled)} questions → {out_json} ===")
print(f"\n=== Issues: {len(issues)} ===")
for line in issues[:20]:
    print(f"  - {line}")
if len(issues) > 20:
    print(f"  ... +{len(issues)-20}")

# Per-category stats
from collections import Counter
cats = Counter(d.get("primary_type", "?") for d in compiled)
print(f"\n=== Par catégorie ===")
for cat, n in cats.most_common():
    print(f"  {cat}: {n}")

# Count answers by length (proxy for completeness)
ans_lens = [len(d.get("ground_truth", {}).get("answer", "")) for d in compiled]
print(f"\n=== Longueur réponses (chars) ===")
print(f"  min: {min(ans_lens) if ans_lens else 0}")
print(f"  median: {sorted(ans_lens)[len(ans_lens)//2] if ans_lens else 0}")
print(f"  max: {max(ans_lens) if ans_lens else 0}")
