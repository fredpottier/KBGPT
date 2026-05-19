"""Corrige les citations [doc=...] dans t4_redactions.json en mappant les noms
abrégés (ex: '003_Upgrade_Guide_2023') vers les doc_ids exacts du corpus
(ex: '003_SAP_S4HANA_2023_Upgrade_Guide_299d71e9').

Approche : match par prefix numérique (003_, 005_, etc.) car tous les docs ont
ce préfixe unique dans le corpus.

Audit final : 0 citation orpheline tolérée.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

STRUCT_DIR = Path("/app/data/poc_a/structures")
REDACT_IN = Path("/app/benchmark/questions/t4_redactions.json")
REDACT_OUT = Path("/app/benchmark/questions/t4_redactions_fixed.json")
REPORT = Path("/app/benchmark/questions/t4_redactions_audit.md")


def build_prefix_map() -> dict:
    """Build {numeric_prefix: full_doc_id} for the 76 corpus docs."""
    m = {}
    for p in STRUCT_DIR.glob("*.json"):
        name = p.stem
        # Extract leading numeric prefix (e.g. "003")
        prefix_match = re.match(r"^(\d{3})_", name)
        if prefix_match:
            num_prefix = prefix_match.group(1)
            m[num_prefix] = name
    return m


def main():
    prefix_map = build_prefix_map()
    print(f"Corpus prefix map: {len(prefix_map)} numeric prefixes mapped")

    existing_doc_ids = set(prefix_map.values())
    # Also non-numeric prefixed docs (Service_Level_Agreement_..., RISE_with_SAP_...)
    for p in STRUCT_DIR.glob("*.json"):
        existing_doc_ids.add(p.stem)

    redactions = json.loads(REDACT_IN.read_text(encoding="utf-8"))

    fixes_applied = []
    still_invalid = []
    final_redactions = []

    for r in redactions:
        qid = r["id"]
        ans = r.get("claude_redacted_answer", "")

        # Find all [doc=...] citations
        def replace_citation(match):
            cited = match.group(1)
            # Check if already valid
            if cited in existing_doc_ids:
                return f"[doc={cited}]"
            # Try numeric prefix match
            prefix_match = re.match(r"^(\d{3})_", cited)
            if prefix_match:
                num = prefix_match.group(1)
                if num in prefix_map:
                    full_id = prefix_map[num]
                    fixes_applied.append((qid, cited, full_id))
                    return f"[doc={full_id}]"
            # Try fuzzy contained-in
            for ex in existing_doc_ids:
                if cited in ex:
                    fixes_applied.append((qid, cited, ex))
                    return f"[doc={ex}]"
            # Try fuzzy reverse (corpus_id in cited)
            for ex in existing_doc_ids:
                if ex in cited and len(ex) > 10:
                    fixes_applied.append((qid, cited, ex))
                    return f"[doc={ex}]"
            # No match - log
            still_invalid.append((qid, cited))
            return f"[doc={cited}]"  # leave as-is, will be flagged

        fixed_ans = re.sub(r"\[doc=([^\]]+)\]", replace_citation, ans)
        final_redactions.append({
            "id": qid,
            "claude_redacted_answer": fixed_ans,
        })

    # Write fixed redactions
    REDACT_OUT.write_text(json.dumps(final_redactions, indent=2, ensure_ascii=False), encoding="utf-8")

    # Generate audit report
    lines = [
        "# T4 Redactions Citation Audit",
        "",
        f"Total redactions: {len(redactions)}",
        f"Fixes applied   : {len(fixes_applied)}",
        f"Still invalid   : {len(still_invalid)}",
        "",
        "## Fixes Applied",
        "",
        "| Question | Cited (abbreviated) | Mapped to (corpus doc_id) |",
        "|---|---|---|",
    ]
    for qid, abbrev, full in fixes_applied[:50]:
        lines.append(f"| {qid} | `{abbrev}` | `{full}` |")
    if len(fixes_applied) > 50:
        lines.append(f"| ... | ... | ... ({len(fixes_applied)-50} more) |")

    if still_invalid:
        lines.extend([
            "",
            "## Citations STILL INVALID (need manual fix)",
            "",
        ])
        for qid, cit in still_invalid:
            lines.append(f"- {qid}: `[doc={cit}]`")

    REPORT.write_text("\n".join(lines), encoding="utf-8")

    # Print summary
    print(f"Fixes applied: {len(fixes_applied)}")
    print(f"Still invalid: {len(still_invalid)}")
    print(f"Written     : {REDACT_OUT}")
    print(f"Audit report: {REPORT}")
    if still_invalid:
        print("\nStill invalid citations:")
        for qid, cit in still_invalid:
            print(f"  {qid}: {cit}")


if __name__ == "__main__":
    main()
