"""V6-P2.1 — POC cross-domain extraction.

Test critique de la charte universal/domain-agnostic : applique le MÊME
prompt + MÊME schema Pydantic V6 sur deux sections issues de domaines
totalement différents de SAP :
1. Légal — Article 32 RGPD (texte officiel public)
2. Médical — Protocole asthme aigu (synthétique, BTS/SIGN-style)

Si l'extraction fonctionne sur ces deux domaines sans modification du
prompt, alors la charte est respectée et on peut industrialiser.

Usage :
    docker exec knowbase-app python scripts/v6_poc_extract_cross_domain.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

from knowbase.runtime_v6.schemas import SectionExtraction
from knowbase.runtime_v6.extraction.prompt import build_extraction_messages


TOGETHER_KEY = os.getenv("TOGETHER_API_KEY", "").strip()
DEEPINFRA_KEY = os.getenv("DEEPINFRA_API_KEY", "").strip()
MODEL = os.getenv("V6_EXTRACT_MODEL", "deepseek-ai/DeepSeek-V3.1")


# ─── Sections cross-domain (sources publiques) ───────────────────────────────

LEGAL_SECTION = {
    "doc_id": "GDPR_Regulation_EU_2016_679",
    "section_id": "sec_art_32",
    "section_title": "Article 32 - Security of processing",
    "section_text": (
        "Article 32 - Security of processing\n"
        "1. Taking into account the state of the art, the costs of implementation and the nature, "
        "scope, context and purposes of processing as well as the risk of varying likelihood and "
        "severity for the rights and freedoms of natural persons, the controller and the processor "
        "shall implement appropriate technical and organisational measures to ensure a level of "
        "security appropriate to the risk, including inter alia as appropriate:\n"
        "(a) the pseudonymisation and encryption of personal data;\n"
        "(b) the ability to ensure the ongoing confidentiality, integrity, availability and "
        "resilience of processing systems and services;\n"
        "(c) the ability to restore the availability and access to personal data in a timely manner "
        "in the event of a physical or technical incident;\n"
        "(d) a process for regularly testing, assessing and evaluating the effectiveness of "
        "technical and organisational measures for ensuring the security of the processing.\n"
        "2. In assessing the appropriate level of security account shall be taken in particular of "
        "the risks that are presented by processing, in particular from accidental or unlawful "
        "destruction, loss, alteration, unauthorised disclosure of, or access to personal data "
        "transmitted, stored or otherwise processed.\n"
        "3. Adherence to an approved code of conduct as referred to in Article 40 or an approved "
        "certification mechanism as referred to in Article 42 may be used as an element by which to "
        "demonstrate compliance with the requirements set out in paragraph 1 of this Article."
    ),
}


MEDICAL_SECTION = {
    "doc_id": "Acute_Asthma_Protocol_Generic_v1",
    "section_id": "sec_acute_mgmt_adult",
    "section_title": "Initial Management of Acute Asthma Exacerbation in Adults",
    "section_text": (
        "Initial Management of Acute Asthma Exacerbation in Adults\n\n"
        "For patients aged 12 years and over presenting with acute asthma exacerbation, "
        "administer salbutamol 5 mg via nebulizer with high-flow oxygen (6-8 L/min). "
        "Reassess oxygen saturation (SpO2) every 5 minutes during nebulization. "
        "Target SpO2 is 94-98%.\n\n"
        "If no clinical improvement is observed within 20 minutes, escalate treatment by "
        "adding ipratropium bromide 0.5 mg to the next salbutamol nebulization. "
        "Administer prednisolone 40-50 mg orally, or methylprednisolone 125 mg "
        "intravenously if the oral route is not tolerated.\n\n"
        "Salbutamol is contraindicated in patients with known hypersensitivity to beta-2 "
        "agonists. Caution is required in patients with cardiac arrhythmia or hyperthyroidism.\n\n"
        "For severity stratification criteria (mild, moderate, severe, life-threatening), "
        "refer to British Thoracic Society (BTS) guideline SIGN 158, section 4.2.\n\n"
        "If the patient has a life-threatening exacerbation (silent chest, cyanosis, SpO2 < 92%, "
        "PEF < 33% predicted), immediate ICU consultation is required."
    ),
}


# ─── LLM call (réutilise pattern POC) ────────────────────────────────────────


def _endpoint_key():
    if TOGETHER_KEY:
        return ("https://api.together.xyz/v1/chat/completions", TOGETHER_KEY, "together")
    return ("https://api.deepinfra.com/v1/openai/chat/completions", DEEPINFRA_KEY, "deepinfra")


def call_llm(messages, max_tokens=4000):
    endpoint, key, provider = _endpoint_key()
    if not key:
        return {"error": "no_api_key"}
    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    try:
        t0 = time.time()
        r = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
            timeout=180,
        )
        r.raise_for_status()
        data = r.json()
        return {
            "content": data["choices"][0]["message"]["content"],
            "usage": data.get("usage", {}),
            "latency_s": time.time() - t0,
            "provider": provider,
        }
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def parse_extraction(content, doc_id, section_id):
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError as exc:
        return {"error": f"json_decode: {exc}", "raw": content[:500]}
    parsed["doc_id"] = doc_id
    parsed["section_id"] = section_id
    for key in ("entities", "facts", "procedures", "constraints", "references"):
        for item in parsed.get(key, []) or []:
            if "evidence_section_id" not in item or not item.get("evidence_section_id"):
                item["evidence_section_id"] = section_id
    try:
        return SectionExtraction(**parsed)
    except Exception as exc:
        return {"error": f"pydantic: {exc}", "raw_dict": parsed}


def print_audit(label, extr, llm_resp):
    print("\n" + "=" * 72)
    print(f"  {label}")
    print("=" * 72)
    print(f"Doc: {extr.doc_id} | Section: {extr.section_id}")
    print(f"Model: {MODEL} ({llm_resp.get('provider')}) — {llm_resp.get('latency_s', 0):.1f}s")
    usage = llm_resp.get("usage", {})
    print(f"Tokens : in={usage.get('prompt_tokens', '?')} out={usage.get('completion_tokens', '?')}")
    print("-" * 72)

    print(f"\n[ENTITIES] ({len(extr.entities)})")
    for e in extr.entities:
        al = f" [aliases: {', '.join(e.aliases)}]" if e.aliases else ""
        print(f"  • {e.canonical_name} ({e.entity_kind}){al}")
        if e.description:
            print(f"      → {e.description[:140]}")

    print(f"\n[FACTS] ({len(extr.facts)})")
    for f in extr.facts:
        mod = f" [{f.modality}]" if f.modality != "asserted" else ""
        print(f"  • {f.subject} --{f.predicate}--> {f.object[:80]}{mod}")

    print(f"\n[PROCEDURES] ({len(extr.procedures)})")
    for p in extr.procedures:
        print(f"  • {p.name} — goal: {p.goal[:80]}")
        for s in p.steps:
            print(f"      {s.step_number}. {s.action[:100]}")

    print(f"\n[CONSTRAINTS] ({len(extr.constraints)})")
    for c in extr.constraints:
        applies = f" → applies to {', '.join(c.applies_to)}" if c.applies_to else ""
        print(f"  • [{c.constraint_type}] {c.statement[:140]}{applies}")

    print(f"\n[REFERENCES] ({len(extr.references)})")
    for r in extr.references:
        print(f"  • '{r.reference_text}' ({r.target_kind})")


def run_one(section):
    print(f"\n>>> Extracting: {section['section_title']}")
    print(f"    ({len(section['section_text'])} chars)")
    msgs = build_extraction_messages(
        section["doc_id"],
        section["section_id"],
        section["section_title"],
        section["section_text"],
    )
    resp = call_llm(msgs)
    if "error" in resp:
        print(f"LLM ERROR: {resp['error']}")
        return None
    result = parse_extraction(resp["content"], section["doc_id"], section["section_id"])
    if isinstance(result, dict) and "error" in result:
        print(f"PARSE ERROR: {result['error']}")
        if "raw" in result:
            print(f"Raw: {result['raw'][:500]}")
        return None
    return result, resp


def main():
    print("=== V6-P2.1 Cross-domain extraction ===")
    print(f"Model: {MODEL}\n")

    # Legal
    legal_pair = run_one(LEGAL_SECTION)
    if legal_pair:
        legal_extr, legal_resp = legal_pair
        print_audit("LEGAL — GDPR Article 32", legal_extr, legal_resp)
    else:
        legal_extr, legal_resp = None, None

    # Medical
    med_pair = run_one(MEDICAL_SECTION)
    if med_pair:
        med_extr, med_resp = med_pair
        print_audit("MEDICAL — Acute Asthma Protocol", med_extr, med_resp)
    else:
        med_extr, med_resp = None, None

    # Save bundled artifact
    root = Path("/app") if Path("/app").exists() else Path(__file__).resolve().parents[2]
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    output_path = root / f"benchmark/runs/v6_poc_crossdomain_{ts}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    bundle = {
        "_meta": {
            "ts": ts,
            "model": MODEL,
            "purpose": "Cross-domain charter validation (legal + medical) — same prompt, same schema as SAP POC.",
        },
        "legal": {
            "section": LEGAL_SECTION,
            "extraction": legal_extr.model_dump(mode="json") if legal_extr else None,
            "llm_meta": {
                "provider": legal_resp.get("provider") if legal_resp else None,
                "latency_s": legal_resp.get("latency_s") if legal_resp else None,
                "usage": legal_resp.get("usage") if legal_resp else None,
            },
        },
        "medical": {
            "section": MEDICAL_SECTION,
            "extraction": med_extr.model_dump(mode="json") if med_extr else None,
            "llm_meta": {
                "provider": med_resp.get("provider") if med_resp else None,
                "latency_s": med_resp.get("latency_s") if med_resp else None,
                "usage": med_resp.get("usage") if med_resp else None,
            },
        },
    }
    output_path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n\nSaved bundle: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
