#!/usr/bin/env python3
"""
Phase B / Test 3 — Dry-run FrameBuilder V2 sur cs25_amdt_28.

Objectif : valider que le LLM peut produire un ApplicabilityFrame V2 cohérent
avec les 3 axes orthogonaux V3.3 :
- Scope (invariant) : product_version, region, edition, conditions
- Temporality (mutable) : publication_date, validity_start, validity_end
- Lifecycle (metadata) : status, supersedes/superseded_by, evolves_from

Inputs :
- DocumentContext.primary_subject (Neo4j)
- DocumentContext.applicability_frame_v1 JSON (Neo4j) — pour comparaison
- Cache .v5cache.json — premiers passages + markers

Output : rapport markdown avec le frame V2 généré + comparaison V1 vs V2.

Usage : docker exec knowbase-app python /tmp/audit_phase_b_test3.py
"""
from __future__ import annotations

import json
import os
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
MD_PATH = OUTPUT_DIR / f"audit_phase_b_test3_{TS}.md"
JSON_PATH = OUTPUT_DIR / f"audit_phase_b_test3_{TS}.json"

# Test sur 3 docs représentatifs (1 cs25 récent, 1 dualuse_reg ancien, 1 cs25_change_amdt sans markers)
TARGET_DOCS = [
    "cs25_amdt_28_32f1a9ac",
    "dualuse_reg_428_2009_original_372b7ac3",
    "cs25_change_amdt_26_28f2c375",
]

PROMPT_SYSTEM = """You are a regulatory analyst extracting ApplicabilityFrame V2 from a regulatory document.

The frame has 3 ORTHOGONAL axes (V3.3 schema):

1. **Scope** (invariant — what the rule applies to):
   - product_version: e.g., "CS-25", "Boeing 737-800", null if no specific product
   - region: e.g., "EU", "US", "ICAO", "global"
   - edition: e.g., "Amendment 28", "Revision 3", null if not applicable
   - conditions: array of textual conditions ["altitude > 10000 ft", "passenger aircraft only"]
   - subject_class: domain class, e.g., "aircraft_certification", "dual_use_export", "medical_device"

2. **Temporality** (mutable — when the rule applies):
   - publication_date: when published (YYYY format minimum)
   - validity_start: when applicable (YYYY-MM-DD or null)
   - validity_end: null if still active, YYYY-MM-DD if superseded/repealed

3. **Lifecycle** (metadata — current status):
   - status: ACTIVE | DEPRECATED | SUPERSEDED | REPEALED | DRAFT | UNKNOWN
   - supersedes: array of doc references this replaces, e.g., ["CS-25 Amendment 27"]
   - superseded_by: doc reference that replaces this, or null
   - evolves_from: predecessor doc reference, or null

Extract from inputs (filename, primary_subject, markers, first passages).
Return JSON with the 3 nested objects {scope, temporality, lifecycle}, plus
"reasoning" array (2-3 short bullets explaining the extraction).
Use null for unknown values, never hallucinate."""


def call_llm(prompt_user: str) -> dict:
    payload = {
        "model": VLLM_MODEL,
        "messages": [
            {"role": "system", "content": PROMPT_SYSTEM},
            {"role": "user", "content": prompt_user},
        ],
        "temperature": 0.0,
        "max_tokens": 800,
        "response_format": {"type": "json_object"},
    }
    t0 = time.time()
    r = httpx.post(f"{VLLM_URL}/v1/chat/completions", json=payload, timeout=60.0)
    r.raise_for_status()
    data = r.json()
    elapsed = time.time() - t0
    content = data["choices"][0]["message"]["content"]
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        parsed = {"_parse_error": True, "raw": content[:500]}
    return {
        "result": parsed,
        "elapsed_s": elapsed,
        "tokens": data.get("usage", {}),
    }


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
        f"# Phase B / Test 3 — Dry-run FrameBuilder V2 (3 axes) — {TS}",
        "",
        f"**vLLM** : `{VLLM_URL}` · **Model** : `{VLLM_MODEL}`",
        "",
        "Objectif : valider que le LLM peut produire un ApplicabilityFrame V2 (Scope/Temporality/Lifecycle)",
        "cohérent à partir de filename + primary_subject + cache markers + premiers passages.",
        "",
    ]

    all_results = []

    for doc_id in TARGET_DOCS:
        print(f"\n=== {doc_id} ===")

        # 1. Get DocumentContext from Neo4j
        with driver.session() as s:
            dc_data = s.run("""
                MATCH (dc:DocumentContext) WHERE dc.tenant_id=$t AND dc.doc_id=$d
                RETURN
                  dc.primary_subject AS subject,
                  dc.applicability_frame_json AS frame_v1,
                  dc.applicability_frame_method AS frame_v1_method,
                  dc.document_type AS doc_type,
                  dc.language AS language
            """, t=TENANT_ID, d=doc_id).single()

            # Get first 3 passages from claims
            passages = s.run("""
                MATCH (c:Claim) WHERE c.tenant_id=$t AND c.doc_id=$d AND c.passage_text IS NOT NULL
                RETURN c.passage_text AS passage
                ORDER BY c.passage_id
                LIMIT 5
            """, t=TENANT_ID, d=doc_id).data()

        if not dc_data:
            md.append(f"## {doc_id}\n\n❌ DocumentContext not found, skipping.\n")
            continue

        # 2. Load cache markers
        cache = load_cache_for_doc(doc_id)
        markers_info = "—"
        full_text_excerpt = "—"
        if cache:
            ext = cache.get("extraction", {})
            dc_cache = ext.get("doc_context", {})
            inner_dc = dc_cache.get("document_context", {})
            sm = dc_cache.get("strong_markers", []) or []
            wm = dc_cache.get("weak_markers", []) or []
            eh = inner_dc.get("entity_hints", []) or []
            markers_info = f"strong={sm[:5]}, weak={wm[:5]}, entity_hints={len(eh)}"
            ft = ext.get("full_text", "") or ""
            full_text_excerpt = ft[:1500]

        # 3. Build LLM input
        user_prompt = f"""Document inputs:

**doc_id** (filename-derived): `{doc_id}`
**primary_subject** (from KG): {dc_data.get('subject', 'N/A')}
**document_type**: {dc_data.get('doc_type', 'N/A')}
**language**: {dc_data.get('language', 'N/A')}
**cache markers**: {markers_info}

**First 1500 chars of full_text**:
{full_text_excerpt}

**First 3 passages from claims**:
{chr(10).join(f"  - {p['passage'][:300]}" for p in passages[:3])}

Extract the ApplicabilityFrame V2 with 3 orthogonal axes."""

        # 4. Call LLM
        try:
            llm_out = call_llm(user_prompt)
            print(f"  Done in {llm_out['elapsed_s']:.1f}s ({llm_out['tokens']})")
        except Exception as e:
            print(f"  ERROR: {e}")
            md.append(f"## {doc_id}\n\n❌ LLM error: {e}\n")
            continue

        # 5. Parse v1 frame for comparison
        frame_v1_str = dc_data.get("frame_v1", "") or ""
        try:
            frame_v1 = json.loads(frame_v1_str) if frame_v1_str else None
        except Exception:
            frame_v1 = {"_parse_error": frame_v1_str[:200]}

        all_results.append({
            "doc_id": doc_id,
            "primary_subject": dc_data.get("subject"),
            "frame_v1_method": dc_data.get("frame_v1_method"),
            "frame_v1": frame_v1,
            "frame_v2_llm_output": llm_out["result"],
            "elapsed_s": llm_out["elapsed_s"],
            "tokens": llm_out["tokens"],
        })

        # 6. Render to markdown
        md.append(f"## {doc_id}")
        md.append("")
        md.append(f"**primary_subject** : `{dc_data.get('subject', 'N/A')}`")
        md.append(f"**document_type** : `{dc_data.get('doc_type', 'N/A')}`")
        md.append(f"**LLM elapsed** : {llm_out['elapsed_s']:.1f}s ({llm_out['tokens'].get('total_tokens', 0)} tokens)")
        md.append("")

        md.append("### ApplicabilityFrame V1 existant (pour comparaison)")
        md.append("")
        md.append("```json")
        md.append(json.dumps(frame_v1, ensure_ascii=False, indent=2)[:1500] if frame_v1 else "(empty)")
        md.append("```")
        md.append("")

        md.append("### ApplicabilityFrame V2 généré (3 axes orthogonaux)")
        md.append("")
        md.append("```json")
        md.append(json.dumps(llm_out["result"], ensure_ascii=False, indent=2))
        md.append("```")
        md.append("")

    driver.close()

    # === Synthèse ===
    md.append("## Synthèse")
    md.append("")
    md.append("**Critères d'évaluation manuelle (à remplir par user après lecture)** :")
    md.append("- ✅/❌ Le LLM produit du JSON valide pour les 3 axes ?")
    md.append("- ✅/❌ Scope axis cohérent (product_version, region, edition correctement extraits) ?")
    md.append("- ✅/❌ Temporality axis cohérent (publication_date, validity_start) ?")
    md.append("- ✅/❌ Lifecycle axis cohérent (status, supersedes/superseded_by) ?")
    md.append("- ✅/❌ Pas d'hallucination (cite uniquement ce qui est dans les inputs) ?")
    md.append("- ✅/❌ Cohérence avec V1 sur les champs communs (release_id, doc_year) ?")
    md.append("")
    avg_tokens = sum(r["tokens"].get("total_tokens", 0) for r in all_results) / max(len(all_results), 1)
    md.append(f"**Coût moyen par doc** : {avg_tokens:.0f} tokens, {sum(r['elapsed_s'] for r in all_results)/max(len(all_results),1):.1f}s")
    md.append(f"**Estimation pour 17 docs S1a** : ~{17 * sum(r['elapsed_s'] for r in all_results)/max(len(all_results),1):.0f}s ({avg_tokens*17/1000:.1f}K tokens)")
    md.append("")

    JSON_PATH.write_text(json.dumps(all_results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    MD_PATH.write_text("\n".join(md), encoding="utf-8")
    print(f"\n✅ Report: {MD_PATH}")


if __name__ == "__main__":
    main()
