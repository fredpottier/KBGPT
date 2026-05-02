#!/usr/bin/env python3
"""
S1b — Backfill TemporalFrame claim-level sur les 40 196 claims.

Cascade simplifiée (cf. plan zazzy-beaming-crane.md) :

1. **Tier 5 default** (Cypher pure, ~2 min) :
   - Claim.publication_date = DocumentContext.publication_date (inherit)
   - Claim.validity_start = NULL (NE PAS hériter publication_date — invariant V3.3)
   - Claim.lifecycle_status = "UNKNOWN" (déféré S3 cross-doc SUPERSEDES)

2. **Tier 3 pre-filter** : sélectionner les claims dont passage_text contient
   un signal numérique de date (regex universel, pas de keywords).
   Audit Phase A : ~3 401 claims (8.5%).

3. **Tier 4 LLM** sur ces candidates (parallel=10, ~37 min EC2 vLLM) :
   - Extract validity_start/end claim-level avec date_role + evidence_quote
   - Validator V3.3 rejette les quotes non présentes ou date_role incorrects
   - Override le default Tier 5 si validation OK

4. **Audit doc-by-doc** : ratio Tier 5 vs Tier 4 par doc. Si >50% Tier 5
   sur un doc → flag pour décision retraitement ciblé.

Idempotent :
- Skip claims avec `temporal_axis_source` déjà set (sauf --force)
- Skip claims sans passage_text

Usage :
    docker exec knowbase-app python /tmp/backfill_temporal_frame_claim_level.py
    docker exec knowbase-app python /tmp/backfill_temporal_frame_claim_level.py --tier5-only
    docker exec knowbase-app python /tmp/backfill_temporal_frame_claim_level.py --max-claims 100
    docker exec knowbase-app python /tmp/backfill_temporal_frame_claim_level.py --doc-id cs25_amdt_28_32f1a9ac

Environment :
    NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, TENANT_ID
    VLLM_URL : EC2 vLLM endpoint (ex: http://18.199.218.46:8000)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional

from neo4j import GraphDatabase

sys.path.insert(0, "/app/src")

from knowbase.claimfirst.temporal.temporal_extractor import (  # noqa: E402
    ClaimTemporalResult,
    TemporalExtractor,
    has_temporal_signal,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
TENANT_ID = os.getenv("TENANT_ID", "default")

VLLM_URL = os.getenv("VLLM_URL", "http://18.199.218.46:8000")
VLLM_MODEL = os.getenv("VLLM_MODEL", "Qwen/Qwen2.5-14B-Instruct-AWQ")

OUTPUT_DIR = Path("/data/forensics") if Path("/data").exists() else Path("data/forensics")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MAX_PARALLEL = 10
BATCH_SIZE = 1000


# ============================================================================
# Step 1 — Tier 5 default (Cypher pure)
# ============================================================================

def apply_tier5_default(driver, tenant_id: str, force: bool = False) -> dict:
    """
    Applique le default Tier 5 : inherit publication_date depuis DocumentContext.
    NE PAS hériter validity_start (invariant V3.3).
    """
    where = "c.tenant_id = $t"
    if not force:
        where += " AND c.temporal_axis_source IS NULL"

    with driver.session() as s:
        result = s.run(f"""
            MATCH (c:Claim)
            WHERE {where}
            MATCH (dc:DocumentContext) WHERE dc.doc_id = c.doc_id AND dc.tenant_id = $t
            SET c.publication_date = dc.publication_date,
                c.validity_start = null,
                c.validity_end = null,
                c.lifecycle_status = 'UNKNOWN',
                c.temporal_axis_source = 'tier5_doc_inherit',
                c.temporal_confidence = 'medium',
                c.temporal_backfilled_at = $ts
            RETURN count(c) AS updated
        """, t=tenant_id, ts=datetime.now().isoformat())
        return {"tier5_updated": result.single()["updated"]}


# ============================================================================
# Step 2 — Sélection candidates Tier 3
# ============================================================================

def fetch_tier3_candidates(driver, tenant_id: str, doc_id: Optional[str] = None,
                           max_claims: Optional[int] = None) -> list[dict]:
    """
    Sélectionne les claims candidates pour Tier 4 LLM.

    Pré-filtre : passage_text contient un signal numérique (regex Python
    après fetch — Cypher ne supporte pas notre regex Python complet).
    """
    where_clauses = ["c.tenant_id = $t", "c.passage_text IS NOT NULL"]
    params = {"t": tenant_id}
    if doc_id:
        where_clauses.append("c.doc_id = $d")
        params["d"] = doc_id
    where_str = " AND ".join(where_clauses)

    limit_clause = f"LIMIT {max_claims}" if max_claims else ""

    with driver.session() as s:
        rows = s.run(f"""
            MATCH (c:Claim) WHERE {where_str}
            RETURN c.claim_id AS claim_id, c.doc_id AS doc_id, c.text AS claim_text,
                   c.passage_text AS passage_text
            {limit_clause}
        """, **params).data()

    # Filtre Python (regex universel sur passage_text)
    candidates = [r for r in rows if has_temporal_signal(r["passage_text"])]
    return candidates


# ============================================================================
# Step 3 — Tier 4 LLM batch (parallel)
# ============================================================================

def process_one_claim(extractor: TemporalExtractor, claim: dict) -> ClaimTemporalResult:
    """Worker function pour ThreadPoolExecutor."""
    return extractor.extract(
        claim_id=claim["claim_id"],
        claim_text=claim["claim_text"] or "",
        passage_text=claim["passage_text"] or "",
    )


def persist_tier4_result(driver, tenant_id: str, result: ClaimTemporalResult, ts: str) -> None:
    """Persist le résultat Tier 4 sur le claim si au moins une date a été extraite."""
    if not (result.publication_date or result.validity_start or result.validity_end):
        # Aucun override : skip persist (le Tier 5 default est déjà en place)
        return

    set_clauses = ["c.temporal_axis_source = 'tier4_llm'", "c.temporal_backfilled_at = $ts"]
    params = {"cid": result.claim_id, "t": tenant_id, "ts": ts}

    if result.publication_date and result.publication_date.value:
        set_clauses.append("c.publication_date = $pub")
        params["pub"] = result.publication_date.value
    if result.validity_start and result.validity_start.value:
        set_clauses.append("c.validity_start = $vstart")
        params["vstart"] = result.validity_start.value
    if result.validity_end and result.validity_end.value:
        set_clauses.append("c.validity_end = $vend")
        params["vend"] = result.validity_end.value

    # Stocker un JSON détaillé pour debug
    detail = {
        "publication_date": result.publication_date.model_dump(mode="json") if result.publication_date else None,
        "validity_start": result.validity_start.model_dump(mode="json") if result.validity_start else None,
        "validity_end": result.validity_end.model_dump(mode="json") if result.validity_end else None,
        "rejected": result.rejected_fields,
    }
    set_clauses.append("c.temporal_detail_json = $detail")
    params["detail"] = json.dumps(detail, ensure_ascii=False)

    with driver.session() as s:
        s.run(f"""
            MATCH (c:Claim {{claim_id: $cid, tenant_id: $t}})
            SET {', '.join(set_clauses)}
        """, **params)


def main() -> int:
    parser = argparse.ArgumentParser(description="S1b backfill TemporalFrame claim-level")
    parser.add_argument("--force", action="store_true", help="Force re-process even if temporal_axis_source set")
    parser.add_argument("--doc-id", help="Process only this doc_id")
    parser.add_argument("--max-claims", type=int, help="Limit total claims processed (for testing)")
    parser.add_argument("--tier5-only", action="store_true", help="Apply Tier 5 default only, skip Tier 4 LLM")
    parser.add_argument("--tier4-only", action="store_true", help="Skip Tier 5, only run Tier 4 LLM (assumes Tier 5 already done)")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = OUTPUT_DIR / f"backfill_temporal_claim_{ts}.md"
    summary_path = OUTPUT_DIR / f"backfill_temporal_claim_{ts}.json"

    logger.info("=" * 70)
    logger.info("S1b — Backfill TemporalFrame claim-level")
    logger.info("=" * 70)
    logger.info(f"Tenant : {TENANT_ID}")
    logger.info(f"vLLM : {VLLM_URL} (model: {VLLM_MODEL})")
    logger.info(f"Mode : tier5-only={args.tier5_only} · tier4-only={args.tier4_only} · force={args.force}")
    if args.doc_id:
        logger.info(f"Doc filter : {args.doc_id}")
    if args.max_claims:
        logger.info(f"Max claims : {args.max_claims}")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    summary: dict = {"timestamp": ts, "tenant_id": TENANT_ID}

    try:
        # === Step 1 — Tier 5 default ===
        if not args.tier4_only:
            logger.info("\n--- Step 1: Tier 5 default (Cypher inherit doc-level) ---")
            t0 = time.time()
            tier5_stats = apply_tier5_default(driver, TENANT_ID, force=args.force)
            logger.info(f"  Tier 5 : {tier5_stats['tier5_updated']:,} claims updated in {time.time() - t0:.1f}s")
            summary.update(tier5_stats)
        else:
            logger.info("--- Step 1: SKIPPED (tier4-only mode) ---")

        if args.tier5_only:
            logger.info("\n✅ Tier 5 only mode — done.")
            summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
            return 0

        # === Step 2 — Sélection candidates Tier 3 ===
        logger.info("\n--- Step 2: Sélection candidates Tier 3 (regex numérique universel) ---")
        candidates = fetch_tier3_candidates(driver, TENANT_ID, args.doc_id, args.max_claims)
        logger.info(f"  Candidates : {len(candidates):,}")
        summary["tier3_candidates"] = len(candidates)

        if not candidates:
            logger.info("\nNo candidates — skipping Tier 4 LLM.")
            summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
            return 0

        # === Step 3 — Tier 4 LLM batch ===
        logger.info(f"\n--- Step 3: Tier 4 LLM batch (parallel={MAX_PARALLEL}) ---")
        extractor = TemporalExtractor(vllm_url=VLLM_URL, model=VLLM_MODEL)
        results: list[ClaimTemporalResult] = []
        t_start = time.time()
        completed = 0

        with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as ex:
            futures = {ex.submit(process_one_claim, extractor, c): c for c in candidates}
            for f in as_completed(futures):
                try:
                    res = f.result()
                except Exception as e:
                    claim = futures[f]
                    logger.warning(f"  ❌ {claim['claim_id']}: {e}")
                    continue
                results.append(res)
                # Persist immediately if any date was extracted
                if res.publication_date or res.validity_start or res.validity_end:
                    persist_tier4_result(driver, TENANT_ID, res, ts)
                completed += 1
                if completed % 100 == 0:
                    elapsed = time.time() - t_start
                    rate = completed / elapsed if elapsed else 0
                    eta_s = (len(candidates) - completed) / rate if rate else 0
                    logger.info(f"  {completed}/{len(candidates)} ({elapsed:.0f}s, {rate:.1f}/s, ETA {eta_s:.0f}s)")

        elapsed_total = time.time() - t_start

        # === Stats ===
        n_with_pub = sum(1 for r in results if r.publication_date)
        n_with_vstart = sum(1 for r in results if r.validity_start)
        n_with_vend = sum(1 for r in results if r.validity_end)
        n_total_rejects = sum(len(r.rejected_fields) for r in results)
        n_with_override = sum(
            1 for r in results
            if r.publication_date or r.validity_start or r.validity_end
        )

        summary.update({
            "tier4_processed": len(results),
            "tier4_with_publication_date": n_with_pub,
            "tier4_with_validity_start": n_with_vstart,
            "tier4_with_validity_end": n_with_vend,
            "tier4_with_any_override": n_with_override,
            "tier4_total_rejects": n_total_rejects,
            "tier4_elapsed_s": elapsed_total,
        })

        # === Audit doc-by-doc ===
        with driver.session() as s:
            doc_audit = s.run("""
                MATCH (c:Claim) WHERE c.tenant_id=$t
                RETURN c.doc_id AS doc_id,
                       count(c) AS total,
                       sum(CASE WHEN c.temporal_axis_source = 'tier4_llm' THEN 1 ELSE 0 END) AS tier4,
                       sum(CASE WHEN c.temporal_axis_source = 'tier5_doc_inherit' THEN 1 ELSE 0 END) AS tier5,
                       sum(CASE WHEN c.validity_start IS NOT NULL THEN 1 ELSE 0 END) AS with_validity_start
                ORDER BY total DESC
            """, t=TENANT_ID).data()
        summary["doc_audit"] = doc_audit

        # === Markdown report ===
        md_lines = [
            f"# S1b — Backfill TemporalFrame claim-level — {ts}",
            "",
            f"**Tenant** : `{TENANT_ID}`",
            "",
            "## Step 1 — Tier 5 default",
            "",
            f"- Claims updated : {summary.get('tier5_updated', 0):,}",
            "",
            "## Step 2 — Tier 3 candidates",
            "",
            f"- Candidates with temporal signal : {summary['tier3_candidates']:,}",
            "",
            "## Step 3 — Tier 4 LLM batch",
            "",
            f"- Processed : {len(results):,}",
            f"- With publication_date : {n_with_pub} ({n_with_pub/max(len(results),1)*100:.0f}%)",
            f"- With validity_start : {n_with_vstart} ({n_with_vstart/max(len(results),1)*100:.0f}%)",
            f"- With validity_end : {n_with_vend} ({n_with_vend/max(len(results),1)*100:.0f}%)",
            f"- With any override : {n_with_override} ({n_with_override/max(len(results),1)*100:.0f}%)",
            f"- Total fields rejected (validator) : {n_total_rejects}",
            f"- Elapsed total : {elapsed_total:.0f}s ({elapsed_total/max(len(results),1):.1f}s/claim)",
            f"- Throughput : {len(results)/max(elapsed_total,1):.1f} claims/s",
            "",
            "## Audit doc-by-doc",
            "",
            "| doc_id | total | tier4 | tier5 | with_validity_start |",
            "|---|---:|---:|---:|---:|",
        ]
        for da in doc_audit:
            md_lines.append(
                f"| `{da['doc_id']}` | {da['total']:,} | {da['tier4']:,} | {da['tier5']:,} | {da['with_validity_start']:,} |"
            )
        md_lines.append("")

        report_path.write_text("\n".join(md_lines), encoding="utf-8")
        summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")

        logger.info("\n--- Synthèse ---")
        logger.info(f"  Tier 5 : {summary.get('tier5_updated', 0):,} claims")
        logger.info(f"  Tier 3 candidates : {summary['tier3_candidates']:,}")
        logger.info(f"  Tier 4 processed : {len(results):,}")
        logger.info(f"  With override : {n_with_override}")
        logger.info(f"    publication_date : {n_with_pub}")
        logger.info(f"    validity_start : {n_with_vstart}")
        logger.info(f"    validity_end : {n_with_vend}")
        logger.info(f"  Total elapsed : {elapsed_total:.0f}s")
        logger.info(f"  Report : {report_path}")

        return 0

    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
