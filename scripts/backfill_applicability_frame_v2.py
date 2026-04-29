#!/usr/bin/env python3
"""
S1a — Backfill ApplicabilityFrame V2 sur les 17 DocumentContext existants.

Pour chaque DocumentContext :
1. Tier 1 déterministe : parse filename + cache markers + primary_subject
2. Tier 2 LLM evidence-locked sémantique : FrameBuilderV2 (Qwen2.5-14B vLLM)
3. Validator post-LLM : evidence-locked + date_role correct
4. Persiste applicability_frame_v2_json + temporal_frame_json sur DocumentContext

Idempotent : skip les docs déjà ayant `applicability_frame_v2_json` (sauf --force).

Coût mesuré Phase B Test 3c : ~9-15s par doc, ~5 min total sur 17 docs.

Usage :
    docker exec knowbase-app python /tmp/backfill_applicability_frame_v2.py
    docker exec knowbase-app python /tmp/backfill_applicability_frame_v2.py --force
    docker exec knowbase-app python /tmp/backfill_applicability_frame_v2.py --doc-id cs25_amdt_28_32f1a9ac

Environment :
    NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD : Neo4j connection
    VLLM_URL : vLLM endpoint (ex: http://18.199.218.46:8000)
    TENANT_ID : tenant à backfiller (default: "default")
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from neo4j import GraphDatabase

sys.path.insert(0, "/app/src")

from knowbase.claimfirst.applicability.evidence_validator_v2 import compute_rejection_rate  # noqa: E402
from knowbase.claimfirst.applicability.frame_builder_v2 import FrameBuilderV2  # noqa: E402
from knowbase.claimfirst.applicability.tier1_deterministic import (  # noqa: E402
    extract_tier1_hints,
    load_cache_for_doc_id,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
TENANT_ID = os.getenv("TENANT_ID", "default")

VLLM_URL = os.getenv("VLLM_URL", "http://18.199.218.46:8000")
VLLM_MODEL = os.getenv("VLLM_MODEL", "Qwen/Qwen2.5-14B-Instruct-AWQ")

CACHE_DIR = Path("/data/extraction_cache") if Path("/data").exists() else Path("data/extraction_cache")
OUTPUT_DIR = Path("/data/forensics") if Path("/data").exists() else Path("data/forensics")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def get_full_text_from_cache(doc_id: str) -> str | None:
    """Lit le full_text depuis le cache .v5cache.json."""
    cache = load_cache_for_doc_id(doc_id, CACHE_DIR)
    if not cache:
        return None
    return cache.get("extraction", {}).get("full_text", "") or ""


def fetch_doc_contexts(driver, tenant_id: str, doc_id_filter: str | None = None, force: bool = False):
    """Récupère les DocumentContext à backfiller."""
    where_clauses = ["dc.tenant_id = $t"]
    params = {"t": tenant_id}
    if doc_id_filter:
        where_clauses.append("dc.doc_id = $d")
        params["d"] = doc_id_filter
    if not force:
        where_clauses.append("dc.applicability_frame_v2_json IS NULL")
    where_str = " AND ".join(where_clauses)

    with driver.session() as s:
        rows = s.run(f"""
            MATCH (dc:DocumentContext)
            WHERE {where_str}
            RETURN
              dc.doc_id AS doc_id,
              dc.primary_subject AS primary_subject,
              dc.document_type AS document_type,
              dc.language AS language
            ORDER BY dc.doc_id
        """, **params).data()
    return rows


def persist_frame_v2(driver, doc_id: str, tenant_id: str, frame_json: dict, ts: str) -> None:
    """Persiste le frame V2 sur DocumentContext."""
    # Sépare TemporalFrame pour query plus efficace
    temporal_frame_json = {
        "publication_date": frame_json.get("temporality", {}).get("publication_date"),
        "validity_start": frame_json.get("temporality", {}).get("validity_start"),
        "validity_end": frame_json.get("temporality", {}).get("validity_end"),
        "publication_validity_relationship": frame_json.get("temporality", {}).get(
            "publication_validity_relationship"
        ),
    }

    # Extract scalar publication_date pour index Neo4j (claim_publication_date utilise tenant_id+publication_date)
    pub_date_field = frame_json.get("temporality", {}).get("publication_date") or {}
    pub_date_value = pub_date_field.get("value") if isinstance(pub_date_field, dict) else None

    with driver.session() as s:
        s.run("""
            MATCH (dc:DocumentContext {doc_id: $doc_id, tenant_id: $tenant_id})
            SET dc.applicability_frame_v2_json = $frame_json,
                dc.temporal_frame_json = $temporal_json,
                dc.publication_date = $pub_date,
                dc.applicability_frame_v2_built_at = $ts,
                dc.applicability_frame_v2_method = $method
        """,
            doc_id=doc_id,
            tenant_id=tenant_id,
            frame_json=json.dumps(frame_json, ensure_ascii=False),
            temporal_json=json.dumps(temporal_frame_json, ensure_ascii=False),
            pub_date=pub_date_value,
            ts=ts,
            method=frame_json.get("method", "unknown"),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="S1a backfill ApplicabilityFrame V2")
    parser.add_argument("--force", action="store_true", help="Re-backfill even if applicability_frame_v2_json already set")
    parser.add_argument("--doc-id", help="Backfill only this doc_id")
    parser.add_argument("--dry-run", action="store_true", help="Build frames but do not persist")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = OUTPUT_DIR / f"backfill_applicability_v2_{ts}.md"
    summary_path = OUTPUT_DIR / f"backfill_applicability_v2_{ts}.json"

    logger.info("=" * 70)
    logger.info("S1a — Backfill ApplicabilityFrame V2")
    logger.info("=" * 70)
    logger.info(f"Tenant : {TENANT_ID}")
    logger.info(f"vLLM : {VLLM_URL} (model: {VLLM_MODEL})")
    logger.info(f"Cache dir : {CACHE_DIR}")
    logger.info(f"Force : {args.force} · Dry-run : {args.dry_run} · Doc filter : {args.doc_id or 'none'}")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    builder = FrameBuilderV2(vllm_url=VLLM_URL, model=VLLM_MODEL)

    try:
        rows = fetch_doc_contexts(driver, TENANT_ID, args.doc_id, args.force)
        logger.info(f"\n{len(rows)} DocumentContext to process")

        results: list[dict] = []
        md_lines = [
            f"# S1a — Backfill ApplicabilityFrame V2 — {ts}",
            "",
            f"**vLLM** : `{VLLM_URL}` · **Model** : `{VLLM_MODEL}`",
            f"**Docs processed** : {len(rows)}",
            "",
        ]

        t_start = time.time()
        for i, row in enumerate(rows, 1):
            doc_id = row["doc_id"]
            primary_subject = row["primary_subject"]
            doc_type = row["document_type"]
            language = row["language"]

            logger.info(f"\n[{i}/{len(rows)}] {doc_id}")

            # Load full_text + cache
            full_text = get_full_text_from_cache(doc_id) or ""
            if not full_text:
                logger.warning(f"  ⚠ No cache/full_text found for {doc_id} — skipping")
                results.append({"doc_id": doc_id, "status": "skipped_no_cache"})
                continue
            logger.info(f"  full_text : {len(full_text):,} chars")

            cache = load_cache_for_doc_id(doc_id, CACHE_DIR)

            # Tier 1 hints
            tier1 = extract_tier1_hints(doc_id, cache, primary_subject)
            logger.info(
                f"  Tier 1 : year={tier1.publication_year} ({tier1.confidence}, {tier1.sources_count} sources), "
                f"edition={tier1.edition_label}, region={tier1.region}"
            )

            # LLM Tier 2 + Validator
            try:
                frame = builder.build(
                    doc_id=doc_id,
                    full_text=full_text,
                    primary_subject=primary_subject,
                    document_type=doc_type,
                    language=language,
                    tier1_hints=tier1,
                )
            except Exception as e:
                logger.error(f"  ❌ Build failed: {e}")
                results.append({"doc_id": doc_id, "status": "build_failed", "error": str(e)})
                md_lines.append(f"## {doc_id}\n\n❌ Build failed: {e}\n")
                continue

            n_rejected, n_total, rejection_rate = compute_rejection_rate(frame)
            logger.info(
                f"  Frame : method={frame.method}, "
                f"validated={n_total - n_rejected}, rejected={n_rejected} ({rejection_rate:.0f}%)"
            )

            # Persist
            if not args.dry_run:
                persist_frame_v2(driver, doc_id, TENANT_ID, frame.to_json_dict(), ts)
                logger.info(f"  ✅ Persisted to DocumentContext")

            results.append({
                "doc_id": doc_id,
                "status": "ok",
                "method": frame.method,
                "tier1_year": tier1.publication_year,
                "tier1_confidence": tier1.confidence,
                "tier1_sources_count": tier1.sources_count,
                "fields_validated": n_total - n_rejected,
                "fields_rejected": n_rejected,
                "rejection_rate_pct": round(rejection_rate, 1),
                "publication_date": (
                    frame.temporality.publication_date.value
                    if frame.temporality.publication_date else None
                ),
                "validity_start": (
                    frame.temporality.validity_start.value
                    if frame.temporality.validity_start else None
                ),
                "lifecycle_status": frame.lifecycle.status.value,
            })

            # Markdown
            md_lines.append(f"## {doc_id}")
            md_lines.append("")
            md_lines.append(f"- **method** : `{frame.method}`")
            md_lines.append(f"- **Tier 1** : year={tier1.publication_year} ({tier1.confidence}), edition={tier1.edition_label}")
            md_lines.append(f"- **Validation** : {n_total - n_rejected} validated / {n_rejected} rejected ({rejection_rate:.0f}%)")
            md_lines.append(f"- **publication_date** : `{results[-1]['publication_date']}`")
            md_lines.append(f"- **validity_start** : `{results[-1]['validity_start']}`")
            md_lines.append(f"- **lifecycle.status** : `{results[-1]['lifecycle_status']}`")
            if frame.rejected_fields:
                md_lines.append(f"- **Rejets** :")
                for r in frame.rejected_fields[:5]:
                    md_lines.append(
                        f"  - {r.get('axis')}.{r.get('field')} = `{r.get('value')}` "
                        f"({r.get('reason')})"
                    )
            md_lines.append("")

        elapsed = time.time() - t_start

        # Synthesis
        ok_count = sum(1 for r in results if r["status"] == "ok")
        skipped = sum(1 for r in results if r["status"] != "ok")
        avg_rejection = (
            sum(r.get("rejection_rate_pct", 0) for r in results if r["status"] == "ok") / max(ok_count, 1)
        )
        with_pub_date = sum(1 for r in results if r.get("publication_date"))
        with_validity_start = sum(1 for r in results if r.get("validity_start"))

        md_lines.append("## Synthèse")
        md_lines.append("")
        md_lines.append(f"- Docs processed : {len(rows)}")
        md_lines.append(f"- ✅ OK : {ok_count}")
        md_lines.append(f"- ⚠ Skipped/failed : {skipped}")
        md_lines.append(f"- Avg rejection rate : {avg_rejection:.1f}% (cible ≤ 5%)")
        md_lines.append(f"- Docs avec publication_date : {with_pub_date}/{ok_count}")
        md_lines.append(f"- Docs avec validity_start : {with_validity_start}/{ok_count}")
        md_lines.append(f"- Elapsed : {elapsed:.1f}s ({elapsed/max(len(rows),1):.1f}s/doc)")
        md_lines.append("")

        # Write reports
        report_path.write_text("\n".join(md_lines), encoding="utf-8")
        summary_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

        logger.info(f"\n--- Synthèse ---")
        logger.info(f"  OK : {ok_count}/{len(rows)}")
        logger.info(f"  Avg rejection : {avg_rejection:.1f}%")
        logger.info(f"  publication_date : {with_pub_date}/{ok_count}")
        logger.info(f"  validity_start : {with_validity_start}/{ok_count}")
        logger.info(f"  Total elapsed : {elapsed:.1f}s")
        logger.info(f"  Report : {report_path}")

        return 0 if ok_count == len(rows) else 1

    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
