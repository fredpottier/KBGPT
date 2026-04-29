#!/usr/bin/env python3
"""
Phase B / Test 3c — FrameBuilder V2 evidence-locked + sémantique pur (anti-pattern lexical).

Améliorations vs Test 3b :
1. Prompt 100% sémantique (pas de keywords/patterns) — multilingue, domain-agnostic
2. Distingue explicitement les 3 dates (publication vs validity_start vs validity_end)
3. Input élargi à 5000 chars (au lieu de 1500) pour donner plus de contexte
4. Test étendu sur 4 docs : cs25_amdt_28 (EN aero), dualuse_reg_2021_821 (EN reg avec validity≠publication),
   dualuse_reg_428_2009 (EN reg simple), cs25_change_amdt_26 (EN aero pauvre)

Cible V3.3 : extraire correctement les 3 dates DISTINCTES pour dualuse_reg_2021_821
sans avoir indiqué de regex ni de keywords explicites.
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
MD_PATH = OUTPUT_DIR / f"audit_phase_b_test3c_{TS}.md"

TARGET_DOCS = [
    "cs25_amdt_28_32f1a9ac",
    "dualuse_reg_2021_821_original_65eef5dc",  # le cas critique : publication ≠ validity_start
    "dualuse_reg_428_2009_original_372b7ac3",
    "cs25_change_amdt_26_28f2c375",
]

INPUT_CHARS = 5000  # élargi vs Test 3b (1500)

# Prompt 100% sémantique — pas de keywords ni patterns lexicaux
PROMPT_SYSTEM_V3_SEMANTIC = """You are a document analyst extracting an evidence-locked ApplicabilityFrame V2 from any kind of document (regulatory, technical, legal, medical, etc.) in any language.

The frame has 3 ORTHOGONAL axes:

## Axis 1: Scope (invariant — what the document/rules apply to)
- product_version: the named product/system/standard version this document concerns
- region: the geographical/jurisdictional area
- edition: the version/amendment/revision number of THIS document
- conditions: list of textual conditions limiting applicability
- subject_class: a short domain class label

## Axis 2: Temporality — THREE DISTINCT DATES (do NOT confuse them)
- **publication_date**: when THIS document itself was authored/issued/published.
  This is the date the document came into existence as a written artifact.
  Look for the date that identifies WHEN someone wrote/published the document.

- **validity_start**: when the RULES described in this document BEGIN TO APPLY.
  This is the date from which compliance is required.
  Critical: this is OFTEN DIFFERENT from publication_date.
  A document published on 2024-10-12 may state that its rules apply from 2025-01-01.
  Look for explicit statements about when the rules become operative/effective/applicable.
  If the document does not explicitly state a separate effective date, leave validity_start NULL
  — DO NOT default to publication_date. Unknown is better than wrong.

- **validity_end**: when the rules cease to apply (or null if still active or unstated).
  Look for explicit cessation/expiration/repeal statements about THIS document's rules.

## Axis 3: Lifecycle (current status)
- status: ACTIVE | DEPRECATED | SUPERSEDED | REPEALED | DRAFT | UNKNOWN
- supersedes: list of prior documents this replaces
- superseded_by: document that replaces this (or null)
- evolves_from: predecessor document (or null)

## Output requirements (V3.3 evidence-locked)
For EVERY non-null value, provide an `evidence_quote` field with a verbatim citation
from the inputs (max 100 chars). The system will verify the quote is literally in the source.

If you cannot find a verbatim citation, the value MUST be null. No inferences.
DO NOT use prior knowledge about the document. ONLY use what is explicitly written.

Multilingual / multi-domain: the LLM should handle EN/FR/DE/ES/IT/... and any
domain (regulatory/technical/medical/legal/IT/aerospace/...) by understanding the
SEMANTIC of the text, not by matching specific keywords.

Output JSON schema:
{
  "scope": {
    "product_version": "..." | null, "product_version_quote": "..." | null,
    "region": "..." | null, "region_quote": "..." | null,
    "edition": "..." | null, "edition_quote": "..." | null,
    "conditions": [{"value": "...", "quote": "..."}],
    "subject_class": "..." | null, "subject_class_quote": "..." | null
  },
  "temporality": {
    "publication_date": "YYYY" | "YYYY-MM-DD" | null, "publication_date_quote": "..." | null,
    "validity_start": "YYYY-MM-DD" | null, "validity_start_quote": "..." | null,
    "validity_end": "YYYY-MM-DD" | null, "validity_end_quote": "..." | null,
    "publication_validity_relationship": "same_date" | "validity_after_publication" | "validity_before_publication" | "unknown"
  },
  "lifecycle": {
    "status": "ACTIVE" | "DEPRECATED" | "SUPERSEDED" | "REPEALED" | "DRAFT" | "UNKNOWN",
    "status_quote": "..." | null,
    "supersedes": [{"value": "...", "quote": "..."}],
    "superseded_by": "..." | null, "superseded_by_quote": "..." | null,
    "evolves_from": "..." | null, "evolves_from_quote": "..." | null
  }
}"""


def normalize_for_match(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def validate_quote(quote: str | None, full_text_normalized: str) -> bool:
    if not quote:
        return False
    return normalize_for_match(quote) in full_text_normalized


def validate_frame(frame: dict, full_text: str) -> tuple[dict, list[dict]]:
    rejects = []
    cleaned: dict = {"scope": {}, "temporality": {}, "lifecycle": {}}
    ft_norm = normalize_for_match(full_text)

    scope = frame.get("scope", {}) or {}
    for field in ["product_version", "region", "edition", "subject_class"]:
        val, q = scope.get(field), scope.get(f"{field}_quote")
        if val is None:
            cleaned["scope"][field] = None
        elif validate_quote(q, ft_norm):
            cleaned["scope"][field] = val
            cleaned["scope"][f"{field}_quote"] = q
        else:
            rejects.append({"axis": "scope", "field": field, "value": val, "quote": q, "reason": "quote not found"})
            cleaned["scope"][field] = None

    conds_clean = []
    for c in scope.get("conditions", []) or []:
        if isinstance(c, dict) and validate_quote(c.get("quote", ""), ft_norm):
            conds_clean.append(c["value"])
        elif isinstance(c, dict):
            rejects.append({"axis": "scope", "field": "conditions", "value": c.get("value"), "quote": c.get("quote"), "reason": "quote not found"})
    cleaned["scope"]["conditions"] = conds_clean

    temp = frame.get("temporality", {}) or {}
    for field in ["publication_date", "validity_start", "validity_end"]:
        val, q = temp.get(field), temp.get(f"{field}_quote")
        if val is None:
            cleaned["temporality"][field] = None
        elif validate_quote(q, ft_norm):
            cleaned["temporality"][field] = val
            cleaned["temporality"][f"{field}_quote"] = q
        else:
            rejects.append({"axis": "temporality", "field": field, "value": val, "quote": q, "reason": "quote not found"})
            cleaned["temporality"][field] = None
    cleaned["temporality"]["publication_validity_relationship"] = temp.get("publication_validity_relationship", "unknown")

    lc = frame.get("lifecycle", {}) or {}
    status, sq = lc.get("status"), lc.get("status_quote")
    if status and status != "UNKNOWN" and validate_quote(sq, ft_norm):
        cleaned["lifecycle"]["status"] = status
        cleaned["lifecycle"]["status_quote"] = sq
    else:
        if status and status != "UNKNOWN":
            rejects.append({"axis": "lifecycle", "field": "status", "value": status, "quote": sq, "reason": "quote not found"})
        cleaned["lifecycle"]["status"] = "UNKNOWN"

    sups_clean = []
    for s in lc.get("supersedes", []) or []:
        if isinstance(s, dict) and validate_quote(s.get("quote", ""), ft_norm):
            sups_clean.append(s["value"])
        elif isinstance(s, dict):
            rejects.append({"axis": "lifecycle", "field": "supersedes", "value": s.get("value"), "quote": s.get("quote"), "reason": "quote not found"})
    cleaned["lifecycle"]["supersedes"] = sups_clean

    for field in ["superseded_by", "evolves_from"]:
        val, q = lc.get(field), lc.get(f"{field}_quote")
        if val is None:
            cleaned["lifecycle"][field] = None
        elif validate_quote(q, ft_norm):
            cleaned["lifecycle"][field] = val
            cleaned["lifecycle"][f"{field}_quote"] = q
        else:
            rejects.append({"axis": "lifecycle", "field": field, "value": val, "quote": q, "reason": "quote not found"})
            cleaned["lifecycle"][field] = None

    return cleaned, rejects


def call_llm(prompt_user: str) -> dict:
    payload = {
        "model": VLLM_MODEL,
        "messages": [
            {"role": "system", "content": PROMPT_SYSTEM_V3_SEMANTIC},
            {"role": "user", "content": prompt_user},
        ],
        "temperature": 0.0,
        "max_tokens": 2000,
        "response_format": {"type": "json_object"},
    }
    t0 = time.time()
    r = httpx.post(f"{VLLM_URL}/v1/chat/completions", json=payload, timeout=120.0)
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
        f"# Phase B / Test 3c — FrameBuilder V2 sémantique pur + evidence-locked — {TS}",
        "",
        f"**vLLM** : `{VLLM_URL}` · **Model** : `{VLLM_MODEL}` · **Input** : {INPUT_CHARS} chars",
        "",
        "Renforcement Test 3b : prompt **100% sémantique** (anti-pattern : aucun keyword, aucun regex, multilingue/domain-agnostic).",
        "Distinction explicite des 3 dates : publication_date (rédaction) vs validity_start (mise en application) vs validity_end (cessation).",
        "",
        "**Cas critique** : `dualuse_reg_2021_821` doit avoir publication_date=2021-06-11 ET validity_start=2021-09-09 (deux dates DIFFÉRENTES).",
        "",
    ]

    total_extracted = 0
    total_rejected = 0

    for doc_id in TARGET_DOCS:
        print(f"\n=== {doc_id} ===")
        with driver.session() as s:
            dc_data = s.run("""
                MATCH (dc:DocumentContext) WHERE dc.tenant_id=$t AND dc.doc_id=$d
                RETURN dc.primary_subject AS subject, dc.document_type AS doc_type, dc.language AS language
            """, t=TENANT_ID, d=doc_id).single()

        if not dc_data:
            md.append(f"## {doc_id}\n\n❌ Not found.\n")
            continue

        cache = load_cache_for_doc(doc_id)
        full_text_full = ""
        full_text_excerpt = ""
        if cache:
            full_text_full = cache.get("extraction", {}).get("full_text", "") or ""
            full_text_excerpt = full_text_full[:INPUT_CHARS]

        user_prompt = f"""Document inputs (the ONLY sources of truth for evidence_quotes):

**doc_id (filename-derived)**: `{doc_id}`
**primary_subject (from KG)**: {dc_data.get('subject', 'N/A')}
**document_type**: {dc_data.get('doc_type', 'N/A')}
**language**: {dc_data.get('language', 'N/A')}

**First {INPUT_CHARS} chars of full_text** (the AUTHORITATIVE source):
{full_text_excerpt}

Extract the evidence-locked ApplicabilityFrame V2.

Reminder of the 3 distinct dates:
- publication_date: when THIS document was authored
- validity_start: when its RULES begin to apply (different from publication if document says so)
- validity_end: when its rules cease (or null)

DO NOT default validity_start to publication_date. If unstated, leave null."""

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
                    if k.endswith("_quote") or k == "publication_validity_relationship":
                        continue
                    if isinstance(v, list):
                        count += len(v)
                    elif v is not None and v != "UNKNOWN":
                        count += 1
            return count

        raw_count = 0
        for axis in ["scope", "temporality", "lifecycle"]:
            axis_data = raw_frame.get(axis, {}) or {}
            for k, v in axis_data.items():
                if k.endswith("_quote") or k == "publication_validity_relationship":
                    continue
                if isinstance(v, list):
                    raw_count += len(v)
                elif v is not None and v != "UNKNOWN":
                    raw_count += 1

        validated_count = count_fields(cleaned_frame)
        total_extracted += raw_count
        total_rejected += len(rejects)

        md.append(f"## {doc_id}")
        md.append("")
        md.append(f"**LLM elapsed** : {llm_out['elapsed_s']:.1f}s · **tokens** : {llm_out['tokens'].get('total_tokens', 0)}")
        md.append(f"**Fields extraits / validés / rejetés** : {raw_count} / {validated_count} / {len(rejects)}")

        # Highlight publication vs validity distinction
        cl_temp = cleaned_frame["temporality"]
        pub = cl_temp.get("publication_date")
        vstart = cl_temp.get("validity_start")
        relation = cl_temp.get("publication_validity_relationship")
        md.append("")
        md.append(f"**Distinction temporelle critique** :")
        md.append(f"- publication_date = `{pub}`")
        md.append(f"- validity_start = `{vstart}`")
        md.append(f"- relationship = `{relation}`")
        if pub and vstart and pub != vstart:
            md.append(f"- ✅ **Distinction réussie** : 2 dates DIFFÉRENTES extraites")
        elif pub and not vstart:
            md.append(f"- ⚠️ Validity_start null (peut être correct si non explicité)")
        elif pub == vstart:
            md.append(f"- ❌ **PROBLÈME** : LLM a probablement défaulté validity_start sur publication_date")
        md.append("")

        md.append("### Frame V2 cleaned (evidence-locked)")
        md.append("```json")
        md.append(json.dumps(cleaned_frame, ensure_ascii=False, indent=2))
        md.append("```")
        md.append("")

        if rejects:
            md.append("### ⚠️ Rejets")
            md.append("")
            for r in rejects:
                md.append(f"- **{r['axis']}.{r['field']}** = `{r['value']}` · quote=`{(r.get('quote') or '—')[:60]}` · {r['reason']}")
            md.append("")

    driver.close()

    md.append("## Synthèse Test 3c")
    md.append("")
    md.append(f"- **Fields extraits** : {total_extracted}")
    md.append(f"- **Fields validés** : {total_extracted - total_rejected}")
    md.append(f"- **Fields rejetés** (hallucinations potentielles) : {total_rejected}")
    md.append(f"- **Taux d'hallucination** : {total_rejected/max(total_extracted,1)*100:.0f}%")
    md.append("")
    md.append("**Critère clé** : `dualuse_reg_2021_821` doit avoir publication_date ≠ validity_start.")
    md.append("Si oui → le LLM distingue correctement les 2 dates par compréhension sémantique seule.")
    md.append("Si non → reformuler le prompt ou élargir l'input.")
    md.append("")

    MD_PATH.write_text("\n".join(md), encoding="utf-8")
    print(f"\n✅ Report: {MD_PATH}")
    print(f"  Extracted: {total_extracted}, Rejected: {total_rejected}")


if __name__ == "__main__":
    main()
