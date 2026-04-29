#!/usr/bin/env python3
"""
Phase B / Test 3b — FrameBuilder V2 evidence-locked + validator post-LLM.

Renforce Test 3 avec :
1. Prompt strict : pour CHAQUE valeur non-null, le LLM doit fournir `evidence_quote`
   (citation verbatim depuis le full_text, max 80 chars).
2. Validator post-LLM : pour chaque evidence_quote, on vérifie qu'elle existe dans
   le full_text (substring match insensible aux espaces multiples). Si non → REJECT
   le field, log warning.
3. Output : frame V2 *epuré* (uniquement les fields validés) + liste des rejets.

Cible V3.3 : 0 hallucination tolérée sur les fields persistés.

Usage : docker exec knowbase-app python /tmp/audit_phase_b_test3b.py
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

import httpx
from neo4j import GraphDatabase

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
TENANT_ID = os.getenv("TENANT_ID", "default")

VLLM_URL = os.getenv("VLLM_URL", "http://18.199.218.46:8000")
VLLM_MODEL = "Qwen/Qwen2.5-14B-Instruct-AWQ"

CACHE_DIR = Path("/data/extraction_cache") if Path("/data").exists() else Path("data/extraction_cache")
OUTPUT_DIR = Path("/data/forensics") if Path("/data").exists() else Path("data/forensics")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TS = datetime.now().strftime("%Y%m%d_%H%M%S")
MD_PATH = OUTPUT_DIR / f"audit_phase_b_test3b_{TS}.md"

TARGET_DOCS = [
    "cs25_amdt_28_32f1a9ac",
    "dualuse_reg_428_2009_original_372b7ac3",
    "cs25_change_amdt_26_28f2c375",
]

PROMPT_SYSTEM_V2_LOCKED = """You are a regulatory analyst extracting an evidence-locked ApplicabilityFrame V2.

The frame has 3 ORTHOGONAL axes (V3.3 schema):

1. **Scope** (invariant): product_version, region, edition, conditions[], subject_class
2. **Temporality**: publication_date, validity_start, validity_end
3. **Lifecycle**: status (ACTIVE|DEPRECATED|SUPERSEDED|REPEALED|DRAFT|UNKNOWN), supersedes[], superseded_by, evolves_from

CRITICAL RULES (V3.3 evidence-locked):
- For EACH non-null value you extract, you MUST provide an `evidence_quote`: a verbatim citation from the source text (max 80 chars).
- The `evidence_quote` MUST appear LITERALLY in the source (we will verify by substring match).
- If you cannot find a literal quote, set the value to null.
- DO NOT use prior knowledge about the document. ONLY use what is explicitly written in the inputs.
- DO NOT reformulate dates that are NOT in the source. If the source says "15 December 2023", you can convert to "2023-12-15", but the evidence_quote must be "15 December 2023" verbatim.
- For categorical values (region=EU, status=ACTIVE), the evidence_quote must contain a phrase that justifies it (e.g., "Council of the European Union", "Official Journal of the European Union" for region=EU).

Output JSON schema (each field has paired `_quote` field):
{
  "scope": {
    "product_version": "..." | null,
    "product_version_quote": "..." | null,
    "region": "..." | null,
    "region_quote": "..." | null,
    "edition": "..." | null,
    "edition_quote": "..." | null,
    "conditions": [{"value": "...", "quote": "..."}, ...],
    "subject_class": "..." | null,
    "subject_class_quote": "..." | null
  },
  "temporality": {
    "publication_date": "YYYY-MM-DD" | "YYYY" | null,
    "publication_date_quote": "..." | null,
    "validity_start": "..." | null,
    "validity_start_quote": "..." | null,
    "validity_end": "..." | null,
    "validity_end_quote": "..." | null
  },
  "lifecycle": {
    "status": "...",
    "status_quote": "...",
    "supersedes": [{"value": "...", "quote": "..."}, ...],
    "superseded_by": "..." | null,
    "superseded_by_quote": "..." | null,
    "evolves_from": "..." | null,
    "evolves_from_quote": "..." | null
  }
}

If a quote is null, the corresponding value MUST be null. No exceptions."""


def normalize_for_match(s: str) -> str:
    """Normalise pour match: collapse whitespace, lowercase."""
    return re.sub(r"\s+", " ", s.lower()).strip()


def validate_quote(quote: str, full_text_normalized: str) -> bool:
    """Check if quote substring is in full_text (case-insensitive, whitespace-collapsed)."""
    if not quote:
        return False
    return normalize_for_match(quote) in full_text_normalized


def validate_frame(frame: dict, full_text: str) -> tuple[dict, list[dict]]:
    """
    Validate evidence_quote for each non-null field.
    Returns (cleaned_frame, list_of_rejects).
    """
    rejects: list[dict] = []
    cleaned = {"scope": {}, "temporality": {}, "lifecycle": {}}
    ft_norm = normalize_for_match(full_text)

    # Scope
    scope = frame.get("scope", {}) or {}
    for field in ["product_version", "region", "edition", "subject_class"]:
        val = scope.get(field)
        quote = scope.get(f"{field}_quote")
        if val is None:
            cleaned["scope"][field] = None
        elif quote and validate_quote(quote, ft_norm):
            cleaned["scope"][field] = val
            cleaned["scope"][f"{field}_quote"] = quote
        else:
            rejects.append({"axis": "scope", "field": field, "value": val, "quote": quote, "reason": "quote not found in full_text"})
            cleaned["scope"][field] = None
    # conditions[]
    conditions_clean = []
    for c in scope.get("conditions", []) or []:
        if isinstance(c, dict) and validate_quote(c.get("quote", ""), ft_norm):
            conditions_clean.append(c["value"])
        else:
            rejects.append({"axis": "scope", "field": "conditions", "value": c.get("value") if isinstance(c, dict) else c, "quote": c.get("quote") if isinstance(c, dict) else None, "reason": "quote not found"})
    cleaned["scope"]["conditions"] = conditions_clean

    # Temporality
    temp = frame.get("temporality", {}) or {}
    for field in ["publication_date", "validity_start", "validity_end"]:
        val = temp.get(field)
        quote = temp.get(f"{field}_quote")
        if val is None:
            cleaned["temporality"][field] = None
        elif quote and validate_quote(quote, ft_norm):
            cleaned["temporality"][field] = val
            cleaned["temporality"][f"{field}_quote"] = quote
        else:
            rejects.append({"axis": "temporality", "field": field, "value": val, "quote": quote, "reason": "quote not found in full_text"})
            cleaned["temporality"][field] = None

    # Lifecycle
    lc = frame.get("lifecycle", {}) or {}
    status = lc.get("status")
    status_quote = lc.get("status_quote")
    if status and status_quote and validate_quote(status_quote, ft_norm):
        cleaned["lifecycle"]["status"] = status
        cleaned["lifecycle"]["status_quote"] = status_quote
    else:
        if status:
            rejects.append({"axis": "lifecycle", "field": "status", "value": status, "quote": status_quote, "reason": "quote not found"})
        cleaned["lifecycle"]["status"] = "UNKNOWN"

    supersedes_clean = []
    for s in lc.get("supersedes", []) or []:
        if isinstance(s, dict) and validate_quote(s.get("quote", ""), ft_norm):
            supersedes_clean.append(s["value"])
        else:
            rejects.append({"axis": "lifecycle", "field": "supersedes", "value": s.get("value") if isinstance(s, dict) else s, "quote": s.get("quote") if isinstance(s, dict) else None, "reason": "quote not found"})
    cleaned["lifecycle"]["supersedes"] = supersedes_clean

    for field in ["superseded_by", "evolves_from"]:
        val = lc.get(field)
        quote = lc.get(f"{field}_quote")
        if val is None:
            cleaned["lifecycle"][field] = None
        elif quote and validate_quote(quote, ft_norm):
            cleaned["lifecycle"][field] = val
            cleaned["lifecycle"][f"{field}_quote"] = quote
        else:
            rejects.append({"axis": "lifecycle", "field": field, "value": val, "quote": quote, "reason": "quote not found"})
            cleaned["lifecycle"][field] = None

    return cleaned, rejects


def call_llm(prompt_user: str) -> dict:
    payload = {
        "model": VLLM_MODEL,
        "messages": [
            {"role": "system", "content": PROMPT_SYSTEM_V2_LOCKED},
            {"role": "user", "content": prompt_user},
        ],
        "temperature": 0.0,
        "max_tokens": 1500,
        "response_format": {"type": "json_object"},
    }
    t0 = time.time()
    r = httpx.post(f"{VLLM_URL}/v1/chat/completions", json=payload, timeout=90.0)
    r.raise_for_status()
    data = r.json()
    elapsed = time.time() - t0
    content = data["choices"][0]["message"]["content"]
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = {"_parse_error": True, "raw": content[:500]}
    return {"result": parsed, "elapsed_s": elapsed, "tokens": data.get("usage", {})}


def load_cache_for_doc(doc_id: str) -> dict | None:
    for cf in CACHE_DIR.glob("*.v5cache.json"):
        try:
            data = json.loads(cf.read_text(encoding="utf-8"))
            if data.get("extraction", {}).get("document_id") == doc_id or data.get("document_id") == doc_id:
                return data
        except Exception:
            continue
    return None


def main() -> None:
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    md = [
        f"# Phase B / Test 3b — FrameBuilder V2 evidence-locked — {TS}",
        "",
        f"**vLLM** : `{VLLM_URL}` · **Model** : `{VLLM_MODEL}`",
        "",
        "Renforcement Test 3 : prompt impose `evidence_quote` pour chaque field, validator post-LLM rejette les quotes absentes du full_text. **0 hallucination tolérée**.",
        "",
    ]

    total_extracted = 0
    total_rejected = 0
    total_validated = 0

    for doc_id in TARGET_DOCS:
        print(f"\n=== {doc_id} ===")
        with driver.session() as s:
            dc_data = s.run("""
                MATCH (dc:DocumentContext) WHERE dc.tenant_id=$t AND dc.doc_id=$d
                RETURN dc.primary_subject AS subject, dc.document_type AS doc_type, dc.language AS language
            """, t=TENANT_ID, d=doc_id).single()
            passages = s.run("""
                MATCH (c:Claim) WHERE c.tenant_id=$t AND c.doc_id=$d AND c.passage_text IS NOT NULL
                RETURN c.passage_text AS passage ORDER BY c.passage_id LIMIT 5
            """, t=TENANT_ID, d=doc_id).data()

        if not dc_data:
            md.append(f"## {doc_id}\n\n❌ Not found.\n")
            continue

        cache = load_cache_for_doc(doc_id)
        full_text_full = ""
        full_text_excerpt = ""
        markers_info = "—"
        if cache:
            ext = cache.get("extraction", {})
            full_text_full = ext.get("full_text", "") or ""
            full_text_excerpt = full_text_full[:1500]
            dc_cache = ext.get("doc_context", {})
            sm = dc_cache.get("strong_markers", []) or []
            wm = dc_cache.get("weak_markers", []) or []
            markers_info = f"strong={sm[:5]}, weak={wm[:5]}"

        user_prompt = f"""Document inputs (the ONLY sources of truth):

**doc_id**: `{doc_id}`
**primary_subject** (KG): {dc_data.get('subject', 'N/A')}
**document_type**: {dc_data.get('doc_type', 'N/A')}
**cache markers**: {markers_info}

**First 1500 chars of full_text** (the AUTHORITATIVE source for evidence_quotes):
{full_text_excerpt}

**First 3 passages from claims**:
{chr(10).join(f"  - {p['passage'][:300]}" for p in passages[:3])}

Extract the evidence-locked ApplicabilityFrame V2. For EACH non-null value, provide its `*_quote` field with a verbatim citation from the inputs above. If you cannot cite, set the value to null."""

        try:
            llm_out = call_llm(user_prompt)
            print(f"  LLM: {llm_out['elapsed_s']:.1f}s, {llm_out['tokens'].get('total_tokens', 0)} tokens")
        except Exception as e:
            print(f"  ERROR: {e}")
            md.append(f"## {doc_id}\n\n❌ LLM error: {e}\n")
            continue

        raw_frame = llm_out["result"]
        cleaned_frame, rejects = validate_frame(raw_frame, full_text_full)

        # Counts
        def count_fields(f: dict) -> int:
            count = 0
            for axis in ["scope", "temporality", "lifecycle"]:
                axis_data = f.get(axis, {}) or {}
                for k, v in axis_data.items():
                    if k.endswith("_quote"):
                        continue
                    if isinstance(v, list):
                        count += len(v)
                    elif v is not None and v != "UNKNOWN":
                        count += 1
            return count

        # Count raw extracted (look at scope/temporality/lifecycle in raw_frame)
        raw_count = 0
        for axis in ["scope", "temporality", "lifecycle"]:
            axis_data = raw_frame.get(axis, {}) or {}
            for k, v in axis_data.items():
                if k.endswith("_quote"):
                    continue
                if isinstance(v, list):
                    raw_count += len(v)
                elif v is not None and v != "UNKNOWN":
                    raw_count += 1

        validated_count = count_fields(cleaned_frame)
        total_extracted += raw_count
        total_rejected += len(rejects)
        total_validated += validated_count

        md.append(f"## {doc_id}")
        md.append("")
        md.append(f"**LLM elapsed** : {llm_out['elapsed_s']:.1f}s · **tokens** : {llm_out['tokens'].get('total_tokens', 0)}")
        md.append(f"**Fields extraits par LLM** : {raw_count}")
        md.append(f"**Fields rejetés (quote not found)** : {len(rejects)}")
        md.append(f"**Fields validés (evidence-locked)** : {validated_count}")
        md.append("")

        md.append("### Frame V2 raw (LLM output)")
        md.append("```json")
        md.append(json.dumps(raw_frame, ensure_ascii=False, indent=2)[:3000])
        md.append("```")
        md.append("")

        md.append("### Frame V2 cleaned (post-validator)")
        md.append("```json")
        md.append(json.dumps(cleaned_frame, ensure_ascii=False, indent=2))
        md.append("```")
        md.append("")

        if rejects:
            md.append("### ⚠️ Rejets (potentielles hallucinations)")
            md.append("")
            for r in rejects:
                md.append(f"- **{r['axis']}.{r['field']}** = `{r['value']}` · quote=`{r.get('quote', '—')}` · reason: {r['reason']}")
            md.append("")
        else:
            md.append("### ✅ Aucun rejet — toutes les valeurs sont evidence-locked")
            md.append("")

    driver.close()

    md.append("## Synthèse Test 3b (evidence-locked)")
    md.append("")
    md.append(f"- **Fields extraits par LLM** (3 docs) : {total_extracted}")
    md.append(f"- **Fields rejetés** (quote not in source) : {total_rejected}")
    md.append(f"- **Fields validés** (evidence-locked) : {total_validated}")
    if total_extracted:
        rejection_rate = total_rejected / total_extracted * 100
        md.append(f"- **Taux de rejet (= taux d'hallucination potentiel)** : {rejection_rate:.0f}%")
    md.append("")
    if total_rejected == 0:
        md.append("✅ **Verdict** : 0 hallucination détectée sur 3 docs. Pattern evidence-locked viable pour S1a.")
    else:
        md.append(f"⚠️ **Verdict** : {total_rejected} rejets détectés. Le validator est essentiel — sans lui, ces fields auraient pollué le KG avec des hallucinations.")
    md.append("")

    MD_PATH.write_text("\n".join(md), encoding="utf-8")
    print(f"\n✅ Report: {MD_PATH}")
    print(f"  Extracted: {total_extracted}")
    print(f"  Rejected: {total_rejected}")
    print(f"  Validated: {total_validated}")


if __name__ == "__main__":
    main()
