"""V6-P1.3 — POC extraction structurée sur 1 section unique.

Test le pipeline V6 :
1. Charge 1 section de doc 014 Operations Guide
2. Appelle DeepSeek-V3.1 via Together AI avec prompt universel
3. Parse l'output JSON via Pydantic SectionExtraction
4. Audit qualité manuel : print + audit guide

Usage :
    docker exec knowbase-app python scripts/v6_poc_extract_one_section.py
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

from knowbase.runtime_v5.structure_loader import load_structure
from knowbase.runtime_v6.schemas import SectionExtraction
from knowbase.runtime_v6.extraction.prompt import build_extraction_messages


# ─── LLM config (charte open-source) ──────────────────────────────────────────

TOGETHER_KEY = os.getenv("TOGETHER_API_KEY", "").strip()
DEEPINFRA_KEY = os.getenv("DEEPINFRA_API_KEY", "").strip()
MODEL = os.getenv("V6_EXTRACT_MODEL", "deepseek-ai/DeepSeek-V3.1")


def _endpoint_key() -> tuple[str, str, str]:
    if TOGETHER_KEY:
        return ("https://api.together.xyz/v1/chat/completions", TOGETHER_KEY, "together")
    return ("https://api.deepinfra.com/v1/openai/chat/completions", DEEPINFRA_KEY, "deepinfra")


def call_llm(messages: list[dict], max_tokens: int = 4000) -> dict:
    """Appel LLM JSON-only. Returns dict avec 'content' ou 'error'."""
    endpoint, key, provider = _endpoint_key()
    if not key:
        return {"error": "no_api_key"}

    payload = {
        "model": MODEL,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},  # force JSON mode if supported
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
        content = data["choices"][0]["message"]["content"]
        return {
            "content": content,
            "usage": data.get("usage", {}),
            "latency_s": time.time() - t0,
            "provider": provider,
        }
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def parse_extraction(content: str, doc_id: str, section_id: str) -> SectionExtraction | dict:
    """Parse output JSON LLM via Pydantic. Returns SectionExtraction ou {'error':...}."""
    # Strip markdown fences if present
    clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError as exc:
        return {"error": f"json_decode: {exc}", "raw": content[:500]}

    # Inject doc_id / section_id (le LLM n'est pas censé les produire)
    parsed["doc_id"] = doc_id
    parsed["section_id"] = section_id

    # Inject evidence_section_id dans tous les sous-items (required field)
    # Le LLM est explicitement instruit de ne pas le produire — on le pose ici.
    for key in ("entities", "facts", "procedures", "constraints", "references"):
        for item in parsed.get(key, []) or []:
            if "evidence_section_id" not in item or not item.get("evidence_section_id"):
                item["evidence_section_id"] = section_id

    try:
        extr = SectionExtraction(**parsed)
        return extr
    except Exception as exc:
        return {"error": f"pydantic: {exc}", "raw_dict": parsed}


def print_audit_report(extr: SectionExtraction, llm_resp: dict):
    """Affiche un audit lisible du résultat d'extraction."""
    print("=" * 70)
    print(f"EXTRACTION AUDIT — doc {extr.doc_id} | section {extr.section_id}")
    print(f"Model: {MODEL} ({llm_resp.get('provider', '?')}) — {llm_resp.get('latency_s', 0):.1f}s")
    usage = llm_resp.get("usage", {})
    print(f"Tokens : in={usage.get('prompt_tokens', '?')} out={usage.get('completion_tokens', '?')}")
    print("=" * 70)

    print(f"\n[ENTITIES] ({len(extr.entities)})")
    for e in extr.entities:
        aliases = f" [aliases: {', '.join(e.aliases)}]" if e.aliases else ""
        dtype = f" {{type={e.domain_type}}}" if e.domain_type else ""
        desc = f"\n      → {e.description}" if e.description else ""
        print(f"  • {e.canonical_name} ({e.entity_kind}){dtype}{aliases}{desc}")

    print(f"\n[FACTS] ({len(extr.facts)})")
    for f in extr.facts:
        mod = f" [{f.modality}]" if f.modality != "asserted" else ""
        print(f"  • {f.subject} --{f.predicate}--> {f.object}{mod}")
        print(f'      evidence: "{f.evidence_text[:120]}..."')

    print(f"\n[PROCEDURES] ({len(extr.procedures)})")
    for p in extr.procedures:
        print(f"  • {p.name}")
        print(f"      goal: {p.goal}")
        if p.prerequisites:
            print(f"      prereq: {', '.join(p.prerequisites)}")
        for s in p.steps:
            note = f"  ({s.notes})" if s.notes else ""
            print(f"      {s.step_number}. {s.action[:100]}{note}")

    print(f"\n[CONSTRAINTS] ({len(extr.constraints)})")
    for c in extr.constraints:
        applies = f" → applies to {', '.join(c.applies_to)}" if c.applies_to else ""
        print(f"  • [{c.constraint_type}] {c.statement[:150]}{applies}")

    print(f"\n[REFERENCES] ({len(extr.references)})")
    for r in extr.references:
        print(f"  • '{r.reference_text}' ({r.target_kind})")

    print("\n" + "=" * 70)
    print("AUDIT GUIDE (manuel) :")
    print("  ☐ Les entités sont-elles toutes pertinentes ? Aucun bruit ?")
    print("  ☐ Les facts capturent-ils l'essentiel ? Evidence verbatim correcte ?")
    print("  ☐ Les procedures (s'il y en a) sont-elles bien séquencées ?")
    print("  ☐ Les constraints sont-elles vraiment des règles ?")
    print("  ☐ Les references pointent-elles vers des docs réels ?")
    print("=" * 70)


def main():
    # Hardcoded POC config (1 section choisie)
    doc_id = "014_SAP_S4HANA_2021_Operations_Guide_819d2c07"
    section_id = "sec_84170103ffeadf"  # 10.7.4.1.1.1 Component-Specific Monitoring (WWI/Expert)

    print(f"=== V6-P1.3 POC extraction — 1 section ===")
    print(f"Doc: {doc_id}")
    print(f"Section: {section_id}\n")

    struct = load_structure(doc_id)
    if struct is None:
        print(f"ERROR: doc {doc_id} not found")
        return 1

    target = struct.by_id.get(section_id)
    if target is None:
        print(f"ERROR: section {section_id} not found in doc")
        return 1

    section_text = target.get("text", "") or ""
    section_title = target.get("title", "") or ""

    print(f"Section title: {section_title}")
    print(f"Section length: {len(section_text)} chars")
    print(f"Preview: {section_text[:200]}...\n")

    # Build prompt
    messages = build_extraction_messages(doc_id, section_id, section_title, section_text)

    # Call LLM
    print("Calling LLM...")
    llm_resp = call_llm(messages)
    if "error" in llm_resp:
        print(f"LLM ERROR: {llm_resp['error']}")
        return 1

    # Parse output
    print(f"Got response in {llm_resp['latency_s']:.1f}s\n")
    result = parse_extraction(llm_resp["content"], doc_id, section_id)
    if isinstance(result, dict) and "error" in result:
        print(f"PARSE ERROR: {result['error']}")
        print(f"\nRaw LLM output:")
        print(llm_resp["content"][:2000])
        if "raw_dict" in result:
            print(f"\nParsed dict (Pydantic failed):")
            print(json.dumps(result["raw_dict"], indent=2)[:2000])
        return 1

    # Audit print
    print_audit_report(result, llm_resp)

    # Save result for offline inspection
    root = Path("/app") if Path("/app").exists() else Path(__file__).resolve().parents[2]
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    output_path = root / f"benchmark/runs/v6_poc_extraction_{ts}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps({
            "_meta": {
                "ts": ts,
                "model": MODEL,
                "provider": llm_resp.get("provider"),
                "latency_s": llm_resp.get("latency_s"),
                "usage": llm_resp.get("usage"),
                "doc_id": doc_id,
                "section_id": section_id,
                "section_title": section_title,
                "section_chars": len(section_text),
            },
            "section_text": section_text,
            "extraction": result.model_dump(mode="json"),
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nSaved: {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
