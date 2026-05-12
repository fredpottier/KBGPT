"""Parse the EKX responses markdown and produce a report compatible with
gold_set_runner output (same schema as OSMOSIS report, so rejudge_only.py
can score it identically). Corpus-agnostic."""
import json
import re
from datetime import datetime
from pathlib import Path

EKX_MD = Path("/app/benchmark/questions/gold_set_sap_v1_ekx_responses.md")
GOLDSET = Path("/app/benchmark/questions/gold_set_sap_v1.json")
OSMOSIS_REPORT = Path("/app/benchmark/results/gold_set_sap_v1_v4_2_rejudged.json")
OUT = Path("/app/benchmark/results/gold_set_sap_v1_ekx_baseline.json")

PLACEHOLDER = "<COLLER ici la réponse EKX intégrale>"

# Load gold-set (for reference answers + question metadata)
gold = json.loads(GOLDSET.read_text(encoding="utf-8"))
gold_by_id = {q["id"]: q for q in gold}

# Parse EKX markdown
md = EKX_MD.read_text(encoding="utf-8")
# Each block : "## GOLD_SAP_QX_Y [cat]" then "**Q:** ..." then ```answer ... ```
pattern = re.compile(
    r"##\s+(GOLD_SAP_Q\d+_\d+)\s+\[([^\]]+)\].*?```answer\s*\n(.*?)\n```",
    re.DOTALL,
)
matches = pattern.findall(md)
print(f"Parsed {len(matches)} blocks from {EKX_MD}")

per_sample = []
skipped = []
for qid, cat, answer in matches:
    answer = answer.strip()
    if PLACEHOLDER in answer or len(answer) < 10:
        print(f"  ⚠️  {qid}: empty/placeholder, will score 0 (not_provided)")
        answer = "(NOT_PROVIDED — EKX response was not collected for this question)"
        skipped.append(qid)
    gold_item = gold_by_id.get(qid)
    if not gold_item:
        print(f"  ⚠️  {qid}: not in gold-set, skip")
        continue
    ref = gold_item.get("ground_truth", {}).get("answer", "")
    question = gold_item.get("question", "")

    per_sample.append({
        "id": qid,
        "question": question,
        "primary_type": gold_item.get("primary_type"),
        "reference_answer": ref,
        "osmosis_answer": answer,  # Keep key name for compat with rejudge_only.py
        "latency_ms": None,
        "judge": {"score": -1.0, "error": "not_judged_yet"},
        "structured_metrics": {
            "exact_match_identifiers": {"score": None, "n_matched": 0, "n_expected": 0},
            "citation_presence": {"score": None, "n_cited": 0, "n_expected": 0},
            "structured_avg": None,
        },
        "disagreement": None,
        "osmosis_meta": {"system": "EKX"},
    })

# Compute structured_metrics with same logic as gold_set_runner
import sys
sys.path.insert(0, "/app")
from benchmark.evaluators.gold_set_runner import exact_match_identifiers, citation_presence

for s in per_sample:
    g = gold_by_id[s["id"]]
    expected_ids = g.get("ground_truth", {}).get("exact_identifiers", [])
    expected_docs = g.get("ground_truth", {}).get("supporting_doc_ids", [])
    em = exact_match_identifiers(s["osmosis_answer"], expected_ids)
    cp = citation_presence(s["osmosis_answer"], expected_docs)
    s["structured_metrics"]["exact_match_identifiers"] = em
    s["structured_metrics"]["citation_presence"] = cp
    parts = [m["score"] for m in (em, cp) if m.get("score") is not None]
    s["structured_metrics"]["structured_avg"] = sum(parts) / len(parts) if parts else None

report = {
    "metadata": {
        "gold_set_path": str(GOLDSET),
        "system_under_test": "EKX (SAP internal RAG+KG)",
        "ran_at": datetime.utcnow().isoformat(),
        "skipped_questions": skipped,
    },
    "scores": {"global": {}, "by_category": {}},  # filled by rejudge
    "per_sample": per_sample,
}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"\n✓ Imported: {OUT} ({len(per_sample)} samples, {len(skipped)} skipped)")
