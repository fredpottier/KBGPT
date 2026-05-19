"""Injecte les T4 ground truths rédigées par Claude (citations corrigées) dans gold_set_sap_v2.json.

Lit t4_redactions_fixed.json, remplace les "PENDING_CLAUDE_REDACTION" par les vraies
answers, supprime le marker _needs_redaction.

Audit : signaler les T4 qui restent PENDING après patch.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

GOLDSET = Path("/app/benchmark/questions/gold_set_sap_v2.json")
REDACT = Path("/app/benchmark/questions/t4_redactions_fixed.json")
STRUCT_DIR = Path("/app/data/poc_a/structures")


def main():
    questions = json.loads(GOLDSET.read_text(encoding="utf-8"))
    redactions = json.loads(REDACT.read_text(encoding="utf-8"))
    redact_map = {r["id"]: r["claude_redacted_answer"] for r in redactions}

    # Final audit: doc citations in answers vs corpus
    existing = set(p.stem for p in STRUCT_DIR.glob("*.json"))

    patched = 0
    still_pending = 0
    final_citation_audit = {"valid": 0, "invalid": 0, "invalid_ids": set()}

    for q in questions:
        if q.get("ground_truth", {}).get("answer") == "PENDING_CLAUDE_REDACTION":
            qid = q["id"]
            if qid in redact_map:
                q["ground_truth"]["answer"] = redact_map[qid]
                if "_needs_redaction" in q:
                    del q["_needs_redaction"]
                patched += 1
            else:
                still_pending += 1
                print(f"  STILL PENDING: {qid}")

        # Audit citations
        ans = q.get("ground_truth", {}).get("answer", "")
        for cit in re.findall(r"\[doc=([^\]]+)\]", ans):
            if cit in existing:
                final_citation_audit["valid"] += 1
            else:
                final_citation_audit["invalid"] += 1
                final_citation_audit["invalid_ids"].add(cit)

    GOLDSET.write_text(json.dumps(questions, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Patched     : {patched}")
    print(f"Still pending: {still_pending}")
    print(f"")
    print(f"Citation audit:")
    print(f"  Valid    : {final_citation_audit['valid']}")
    print(f"  Invalid  : {final_citation_audit['invalid']}")
    if final_citation_audit["invalid_ids"]:
        print(f"  Invalid distinct IDs ({len(final_citation_audit['invalid_ids'])}):")
        for cid in sorted(final_citation_audit["invalid_ids"]):
            print(f"    - {cid}")


if __name__ == "__main__":
    main()
