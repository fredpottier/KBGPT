#!/usr/bin/env python3
"""
Phase B / Test 1 — Parse filenames + caches markers pour valider la couverture Tier 1+2.

Pour chaque DocumentContext, déterminer la publication_date depuis :
- Tier 1.A : filename pattern (`_YYYY_` ou `_YYYY` ou amdt_NN mapping)
- Tier 1.B : cache `extraction.doc_context.strong_markers` / `weak_markers`
- Tier 1.C : cache `extraction.doc_context.document_context.entity_hints` (regulations explicites)
- Tier 2 : DocumentContext.primary_subject (déjà persisté Neo4j)

Output un rapport montrant la convergence (ou absence) des 4 sources.
Si 17/17 docs ont au moins 2 sources convergentes → Tier 1+2 OK sans LLM.

Usage : docker exec knowbase-app python /tmp/audit_phase_b_test1_filenames_caches.py
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
TENANT_ID = os.getenv("TENANT_ID", "default")

CACHE_DIR = Path("/data/extraction_cache") if Path("/data").exists() else Path("data/extraction_cache")
OUTPUT_DIR = Path("/data/forensics") if Path("/data").exists() else Path("data/forensics")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TS = datetime.now().strftime("%Y%m%d_%H%M%S")
MD_PATH = OUTPUT_DIR / f"audit_phase_b_test1_{TS}.md"

# CS-25 amdt → year mapping (publié par EASA)
# Sources : EASA ED Decision register
CS25_AMDT_TO_YEAR = {
    22: 2018,  # ED Decision 2018/005/R
    23: 2019,
    24: 2020,
    25: 2020,  # ED Decision 2020/024/R
    26: 2021,
    27: 2022,
    28: 2023,  # ED Decision 2023/021/R (confirmé via cache markers)
}


def parse_filename_year(doc_id: str) -> dict[str, Any]:
    """Extract year(s) from doc_id / filename pattern."""
    result = {"raw_doc_id": doc_id, "filename_year": None, "amdt_number": None, "filename_inferred_year": None}

    # Pattern dualuse_reg/del_YYYY_NNNN
    m = re.search(r"_(reg|del)_(\d{4})_(\d+)", doc_id)
    if m:
        result["filename_year"] = int(m.group(2))
        result["filename_inferred_year"] = int(m.group(2))
        return result

    # Pattern dualuse_reg_NNNN_YYYY (older format)
    m = re.search(r"_(\d+)_(\d{4})_original", doc_id)
    if m:
        result["filename_year"] = int(m.group(2))
        result["filename_inferred_year"] = int(m.group(2))
        return result

    # Pattern cs25_amdt_NN or cs25_change_amdt_NN
    m = re.search(r"cs25_(?:change_)?amdt_(\d+)", doc_id)
    if m:
        amdt = int(m.group(1))
        result["amdt_number"] = amdt
        result["filename_inferred_year"] = CS25_AMDT_TO_YEAR.get(amdt)

    return result


def parse_cache_markers(cache_data: dict) -> dict[str, Any]:
    """Extract temporal signals from cache extraction.doc_context."""
    ext = cache_data.get("extraction", {}) or {}
    dc = ext.get("doc_context", {}) or {}
    inner_dc = dc.get("document_context", {}) or {}

    strong_markers = dc.get("strong_markers", []) or []
    weak_markers = dc.get("weak_markers", []) or []
    entity_hints = inner_dc.get("entity_hints", []) or []

    # Find years in markers
    years_in_markers: list[int] = []
    for m in (strong_markers + weak_markers):
        for y in re.findall(r"\b(19|20)\d{2}\b", str(m)):
            year = int(y + str(m).split(y)[1][:2])  # reconstitue année complète
            # Plus simple : refaire la regex
        for y in re.findall(r"\b((?:19|20)\d{2})\b", str(m)):
            years_in_markers.append(int(y))

    # Years in entity_hints (regulations like "ED Decision 2023/021/R")
    years_in_entities: list[int] = []
    for eh in entity_hints:
        label = eh.get("label", "")
        type_hint = eh.get("type_hint", "")
        if type_hint in ("regulation", "standard", "law"):
            for y in re.findall(r"\b((?:19|20)\d{2})\b", label):
                years_in_entities.append(int(y))

    return {
        "strong_markers": strong_markers,
        "weak_markers": weak_markers,
        "entity_hints_count": len(entity_hints),
        "years_in_markers": sorted(set(years_in_markers)),
        "years_in_entities": sorted(set(years_in_entities)),
    }


def load_caches_by_doc_id() -> dict[str, dict]:
    """Map doc_id_prefix (8 chars) → cache content."""
    cache_map: dict[str, dict] = {}
    for cf in CACHE_DIR.glob("*.v5cache.json"):
        try:
            data = json.loads(cf.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  WARN: failed to load {cf.name}: {e}")
            continue
        # extract document_id from cache (format: prefix-hash)
        doc_id_in_cache = data.get("extraction", {}).get("document_id") or data.get("document_id")
        if doc_id_in_cache:
            cache_map[doc_id_in_cache] = data
    return cache_map


def main() -> None:
    print(f"Loading caches from {CACHE_DIR}...")
    cache_map = load_caches_by_doc_id()
    print(f"  Loaded {len(cache_map)} caches")

    # Get doc_ids from Neo4j
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as s:
        rows = s.run("""
            MATCH (dc:DocumentContext) WHERE dc.tenant_id=$t
            RETURN dc.doc_id AS doc_id, dc.primary_subject AS subject
            ORDER BY dc.doc_id
        """, t=TENANT_ID).data()
    driver.close()

    print(f"Found {len(rows)} DocumentContext in Neo4j")

    md_lines = [
        f"# Phase B / Test 1 — Couverture Tier 1+2 (filenames + caches markers) — {TS}",
        "",
        "Objectif : valider que la publication_date est extractible **sans LLM** depuis les 4 sources :",
        "1. **Tier 1.A** — Filename parsing (year ou amdt_number → year)",
        "2. **Tier 1.B** — Cache `strong_markers` / `weak_markers`",
        "3. **Tier 1.C** — Cache `entity_hints` (regulations explicites)",
        "4. **Tier 2** — DocumentContext.primary_subject (Neo4j)",
        "",
        "**Critère de réussite** : 17/17 docs ont au moins 2 sources convergentes sur la même année.",
        "",
        "## Résultats par doc",
        "",
        "| doc_id | filename_year | amdt→year | cache markers | cache entities | primary_subject | **inferred_year** | sources convergentes |",
        "|---|---|---|---|---|---|---|---|",
    ]

    full_coverage = 0
    partial_coverage = 0
    no_coverage = 0

    for r in rows:
        doc_id = r["doc_id"]
        subject = r["subject"] or ""

        # Tier 1.A — filename
        fn_info = parse_filename_year(doc_id)

        # Tier 1.B/C — cache
        cache_info = {"years_in_markers": [], "years_in_entities": []}
        if doc_id in cache_map:
            cache_info = parse_cache_markers(cache_map[doc_id])

        # Tier 2 — primary_subject (chercher année dans le subject)
        years_in_subject = sorted(set(int(y) for y in re.findall(r"\b((?:19|20)\d{2})\b", subject)))

        # Convergence
        all_years: list[int] = []
        if fn_info["filename_inferred_year"]:
            all_years.append(fn_info["filename_inferred_year"])
        all_years.extend(cache_info["years_in_markers"])
        all_years.extend(cache_info["years_in_entities"])
        all_years.extend(years_in_subject)

        # most common year
        from collections import Counter
        if all_years:
            counter = Counter(all_years)
            most_common = counter.most_common(1)[0]
            inferred_year = most_common[0]
            sources_count = sum(1 for src in [
                fn_info["filename_inferred_year"] == inferred_year,
                inferred_year in cache_info["years_in_markers"],
                inferred_year in cache_info["years_in_entities"],
                inferred_year in years_in_subject,
            ] if src)
        else:
            inferred_year = None
            sources_count = 0

        if sources_count >= 2:
            full_coverage += 1
            status_icon = "✅"
        elif sources_count == 1:
            partial_coverage += 1
            status_icon = "⚠️"
        else:
            no_coverage += 1
            status_icon = "❌"

        # Format row
        fn_y = str(fn_info["filename_year"] or "—")
        amdt_y = f"{fn_info['amdt_number']}→{fn_info['filename_inferred_year']}" if fn_info['amdt_number'] else "—"
        markers_y = ",".join(str(y) for y in cache_info["years_in_markers"]) or "—"
        entities_y = ",".join(str(y) for y in cache_info["years_in_entities"]) or "—"
        subject_short = (subject[:40] + "…") if len(subject) > 40 else subject
        subject_y_str = ",".join(str(y) for y in years_in_subject) or "—"
        if subject_y_str != "—":
            subject_short += f" ({subject_y_str})"

        md_lines.append(
            f"| `{doc_id}` | {fn_y} | {amdt_y} | {markers_y} | {entities_y} | {subject_short} | **{inferred_year or '—'}** | {status_icon} {sources_count} |"
        )

    md_lines.append("")
    md_lines.append("## Synthèse")
    md_lines.append("")
    total = len(rows)
    md_lines.append(f"- ✅ **Full coverage** (≥2 sources convergentes) : {full_coverage}/{total} ({full_coverage/total*100:.0f}%)")
    md_lines.append(f"- ⚠️ **Partial coverage** (1 source) : {partial_coverage}/{total}")
    md_lines.append(f"- ❌ **No coverage** : {no_coverage}/{total}")
    md_lines.append("")
    if full_coverage == total:
        md_lines.append("**Verdict** : Tier 1+2 couvrent 100% des docs sans LLM. ✅ Plan S1a peut sauter le LLM Tier 2 fallback (ou le réserver à 0 calls).")
    elif partial_coverage > 0:
        md_lines.append(f"**Verdict** : {partial_coverage} docs nécessitent un LLM Tier 2 fallback ou une heuristique additionnelle.")
    else:
        md_lines.append("**Verdict** : Tier 1+2 insuffisants — révision stratégie nécessaire.")

    MD_PATH.write_text("\n".join(md_lines), encoding="utf-8")
    print(f"\n✅ Report: {MD_PATH}")
    print(f"  Full coverage: {full_coverage}/{total}")
    print(f"  Partial: {partial_coverage}/{total}")
    print(f"  None: {no_coverage}/{total}")


if __name__ == "__main__":
    main()
