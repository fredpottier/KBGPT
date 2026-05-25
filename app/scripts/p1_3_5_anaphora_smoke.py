"""P1.3.5 — smoke A/B résolution d'anaphores (test du fix "contexte passage").

Cas conçus pour que l'ANTÉCÉDENT soit dans la prose du passage mais PAS dans
les unités du batch (simule un batch qui a perdu le contexte, ex. batch_size 5).
On compare l'extraction SANS vs AVEC passage_context → le fix doit résoudre
"il/ce/le système" → l'entité nommée.

Usage :
    V5_VLLM_URL=http://<ip>:8000 V5_VLLM_MODEL=Qwen/Qwen2.5-72B-Instruct-AWQ \
      python app/scripts/p1_3_5_anaphora_smoke.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.p1_2_validate_qualifiers import _make_client, _call_llm, _parse_claims_json  # noqa: E402
from knowbase.claimfirst.extractors.claim_extractor import build_claim_extraction_prompt  # noqa: E402

# Antécédent dans la 1re phrase (prose), unités = phrases anaphoriques suivantes.
CASES = [
    {
        "doc_title": "SAP EHS — Operations Guide",
        "doc_subject": "SAP EHS Expert cache",
        "passage": "The Expert cache stores component monitoring data for SAP EHS. "
                   "It must be initialized before its first use. "
                   "To initialize it, open transaction CG5Z and click the Initialize button.",
        # Le batch ne contient QUE les phrases anaphoriques (pas la 1re)
        "units": ["U1: It must be initialized before its first use.",
                  "U2: To initialize it, open transaction CG5Z and click the Initialize button."],
        "antecedent": "Expert cache",
    },
    {
        "doc_title": "Dual-Use Export Regulation",
        "doc_subject": "Regulation 2021/821",
        "passage": "Regulation (EU) 2021/821 governs the export of dual-use items. "
                   "It entered into force on 9 September 2021. "
                   "Under it, exporters must obtain an authorization before shipping to non-EU countries.",
        "units": ["U1: It entered into force on 9 September 2021.",
                  "U2: Under it, exporters must obtain an authorization before shipping to non-EU countries."],
        "antecedent": "2021/821",
    },
]

_LEAD_ANAPHORA = re.compile(r"^\s*(it|this|that|they|these|those|the system|under it|the latter|he|she)\b", re.I)


def _run(client, model, units_text, passage_context):
    prompt = build_claim_extraction_prompt(
        units_text=units_text, doc_title="Doc", doc_type="technical",
        passage_context=passage_context,
    )
    raw = _call_llm(client, model, prompt)
    return _parse_claims_json(raw)


def main():
    client, forced, label = _make_client("vllm")
    import os
    model = forced or os.getenv("V5_VLLM_MODEL", "Qwen/Qwen2.5-72B-Instruct-AWQ")
    print(f"=== P1.3.5 anaphora A/B — {label} {model} ===\n")

    for c in CASES:
        units_text = "\n".join(c["units"])
        print(f"### {c['doc_title']} (antécédent attendu : '{c['antecedent']}')")
        for tag, ctx in [("SANS contexte passage", ""), ("AVEC contexte passage", c["passage"])]:
            claims = _run(client, model, units_text, ctx)
            print(f"  -- {tag} : {len(claims)} claims --")
            resolved = 0
            for cl in claims:
                t = str(cl.get("claim_text", ""))
                has_antecedent = c["antecedent"].lower() in t.lower()
                lead = bool(_LEAD_ANAPHORA.match(t))
                ok = has_antecedent and not lead
                resolved += int(ok)
                flag = "✓ auto-porteur" if ok else ("✗ anaphore tête" if lead else "✗ antécédent absent")
                print(f"       [{flag}] {t}")
            rate = resolved / len(claims) if claims else 0
            print(f"     → auto-porteurs : {resolved}/{len(claims)} ({rate:.0%})")
        print()


if __name__ == "__main__":
    main()
