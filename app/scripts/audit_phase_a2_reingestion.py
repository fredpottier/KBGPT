#!/usr/bin/env python3
"""Audit post-réingestion PHASE A2 — bilan de la réingestion 39 docs.

À lancer une fois le job ClaimFirst process-all terminé sur les 39 caches.
Read-only sur Neo4j. Persiste un JSON détaillé pour archivage.

Sections couvertes :
  T1 — Counts globaux KG (docs, claims, entities, facets, clusters, relations)
  T2 — Distribution `valid_from_marker` (qualité de l'extraction date par doc)
  T3 — Distribution `valid_from_source` (cascade S2/S3/S4 quel layer a tranché)
  T4 — Distribution `valid_from` par année (détecte les anomalies temporelles)
  T5 — Liste détaillée des docs `valid_from = NULL` (validation manuelle qualité S4)
  T6 — Cohérence Claim.valid_from ↔ DocumentContext.valid_from de leur doc
  T7 — Audit claims par doc (top/bottom, variance)
  T8 — Re-run Gate-B bitemporel sur le nouveau KG

Usage :
  docker exec knowbase-app python scripts/audit_phase_a2_reingestion.py [--tenant default] [--out FILE.json]
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)


def get_client():
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    return get_neo4j_client()


def run(client, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with client.driver.session() as session:
        return [dict(r) for r in session.run(query, params or {})]


# ─────────────────────────────────────────────────────────────────────────────
# T1 — Counts globaux
# ─────────────────────────────────────────────────────────────────────────────


def t1_global_counts(client, tenant_id: str) -> dict[str, Any]:
    rows = run(client, """
        MATCH (d:Document {tenant_id: $tenant}) WITH count(d) AS docs
        OPTIONAL MATCH (dc:DocumentContext {tenant_id: $tenant}) WITH docs, count(dc) AS doc_contexts
        OPTIONAL MATCH (c:Claim {tenant_id: $tenant}) WITH docs, doc_contexts, count(c) AS claims
        OPTIONAL MATCH (e:Entity {tenant_id: $tenant}) WITH docs, doc_contexts, claims, count(e) AS entities
        OPTIONAL MATCH (f:Facet {tenant_id: $tenant}) WITH docs, doc_contexts, claims, entities, count(f) AS facets
        OPTIONAL MATCH (cc:ClaimCluster {tenant_id: $tenant}) WITH docs, doc_contexts, claims, entities, facets, count(cc) AS clusters
        OPTIONAL MATCH (sa:SubjectAnchor) WITH docs, doc_contexts, claims, entities, facets, clusters, count(sa) AS subject_anchors
        OPTIONAL MATCH (cs:ComparableSubject) WITH docs, doc_contexts, claims, entities, facets, clusters, subject_anchors, count(cs) AS comparable_subjects
        OPTIONAL MATCH ()-[r]->() WITH docs, doc_contexts, claims, entities, facets, clusters, subject_anchors, comparable_subjects, count(r) AS total_relations
        RETURN docs, doc_contexts, claims, entities, facets, clusters, subject_anchors, comparable_subjects, total_relations
    """, {"tenant": tenant_id})
    return rows[0] if rows else {}


# ─────────────────────────────────────────────────────────────────────────────
# T2/T3 — Distribution marker / source
# ─────────────────────────────────────────────────────────────────────────────


def t2_marker_distribution(client, tenant_id: str) -> dict[str, Any]:
    # Sur les Claims
    claim_rows = run(client, """
        MATCH (c:Claim {tenant_id: $tenant})
        RETURN coalesce(c.valid_from_marker, 'unset') AS marker, count(c) AS n
        ORDER BY n DESC
    """, {"tenant": tenant_id})
    # Sur les DocumentContext
    doc_rows = run(client, """
        MATCH (dc:DocumentContext {tenant_id: $tenant})
        RETURN coalesce(dc.valid_from_marker, 'unset') AS marker, count(dc) AS n
        ORDER BY n DESC
    """, {"tenant": tenant_id})
    return {"by_claim": claim_rows, "by_document": doc_rows}


def t3_source_distribution(client, tenant_id: str) -> dict[str, Any]:
    claim_rows = run(client, """
        MATCH (c:Claim {tenant_id: $tenant})
        RETURN coalesce(c.valid_from_source, 'null') AS source, count(c) AS n
        ORDER BY n DESC
    """, {"tenant": tenant_id})
    doc_rows = run(client, """
        MATCH (dc:DocumentContext {tenant_id: $tenant})
        RETURN coalesce(dc.valid_from_source, 'null') AS source, count(dc) AS n
        ORDER BY n DESC
    """, {"tenant": tenant_id})
    return {"by_claim": claim_rows, "by_document": doc_rows}


# ─────────────────────────────────────────────────────────────────────────────
# T4 — Distribution `valid_from` par année
# ─────────────────────────────────────────────────────────────────────────────


def t4_year_distribution(client, tenant_id: str) -> dict[str, Any]:
    rows = run(client, """
        MATCH (dc:DocumentContext {tenant_id: $tenant})
        WHERE dc.valid_from IS NOT NULL
        RETURN substring(toString(dc.valid_from), 0, 4) AS year, count(dc) AS n
        ORDER BY year
    """, {"tenant": tenant_id})
    # Distribution des claims aussi (pour vérifier qu'ils héritent bien)
    claim_rows = run(client, """
        MATCH (c:Claim {tenant_id: $tenant})
        WHERE c.valid_from IS NOT NULL
        RETURN substring(toString(c.valid_from), 0, 4) AS year, count(c) AS n
        ORDER BY year
    """, {"tenant": tenant_id})
    return {"by_document": rows, "by_claim": claim_rows}


# ─────────────────────────────────────────────────────────────────────────────
# T5 — Docs avec valid_from = NULL (à valider manuellement)
# ─────────────────────────────────────────────────────────────────────────────


def t5_null_valid_from(client, tenant_id: str) -> dict[str, Any]:
    rows = run(client, """
        MATCH (dc:DocumentContext {tenant_id: $tenant})
        WHERE dc.valid_from IS NULL
        OPTIONAL MATCH (c:Claim {tenant_id: $tenant, doc_id: dc.doc_id})
        WITH dc, count(c) AS n_claims
        RETURN dc.doc_id AS doc_id,
               dc.valid_from_marker AS marker,
               dc.valid_from_warning AS warning,
               n_claims
        ORDER BY n_claims DESC
    """, {"tenant": tenant_id})
    return {"count": len(rows), "docs": rows}


# ─────────────────────────────────────────────────────────────────────────────
# T6 — Cohérence Claim ↔ DocumentContext
# ─────────────────────────────────────────────────────────────────────────────


def t6_coherence(client, tenant_id: str) -> dict[str, Any]:
    """Pour chaque claim, vérifie que valid_from == DocumentContext.valid_from de son doc.

    Tolère les deux NULL ou les deux égaux. Flagge les divergences."""
    rows = run(client, """
        MATCH (c:Claim {tenant_id: $tenant})
        MATCH (dc:DocumentContext {tenant_id: $tenant, doc_id: c.doc_id})
        WITH c, dc,
             CASE
               WHEN c.valid_from IS NULL AND dc.valid_from IS NULL THEN 'both_null'
               WHEN c.valid_from IS NULL AND dc.valid_from IS NOT NULL THEN 'claim_null_doc_set'
               WHEN c.valid_from IS NOT NULL AND dc.valid_from IS NULL THEN 'claim_set_doc_null'
               WHEN toString(c.valid_from) = toString(dc.valid_from) THEN 'equal'
               ELSE 'diverged'
             END AS status
        RETURN status, count(c) AS n
        ORDER BY n DESC
    """, {"tenant": tenant_id})
    return {"distribution": rows}


# ─────────────────────────────────────────────────────────────────────────────
# T7 — Audit claims par doc
# ─────────────────────────────────────────────────────────────────────────────


def t7_claims_per_doc(client, tenant_id: str) -> dict[str, Any]:
    rows = run(client, """
        MATCH (dc:DocumentContext {tenant_id: $tenant})
        OPTIONAL MATCH (c:Claim {tenant_id: $tenant, doc_id: dc.doc_id})
        WITH dc, count(c) AS n_claims
        RETURN dc.doc_id AS doc_id,
               dc.valid_from AS valid_from,
               dc.valid_from_marker AS marker,
               dc.valid_from_source AS source,
               n_claims
        ORDER BY n_claims DESC
    """, {"tenant": tenant_id})

    if not rows:
        return {"total_docs": 0, "claims_total": 0, "stats": {}}

    counts = [r["n_claims"] for r in rows]
    return {
        "total_docs": len(rows),
        "claims_total": sum(counts),
        "stats": {
            "min": min(counts),
            "max": max(counts),
            "mean": round(sum(counts) / len(counts), 1),
            "docs_with_zero_claims": sum(1 for c in counts if c == 0),
        },
        "top_5_largest": rows[:5],
        "bottom_5_smallest": rows[-5:],
    }


# ─────────────────────────────────────────────────────────────────────────────
# T8 — Re-run Gate-B (subset critique)
# ─────────────────────────────────────────────────────────────────────────────


def t8_gate_b_critical(client, tenant_id: str) -> dict[str, Any]:
    """Subset critique du Gate-B : couverture timestamps + indexes ONLINE."""
    # 1. Coverage ingested_at (bloquant Gate-B)
    cov_rows = run(client, """
        MATCH (c:Claim {tenant_id: $tenant})
        RETURN count(c) AS total,
               sum(CASE WHEN c.ingested_at IS NULL THEN 1 ELSE 0 END) AS missing_ingested,
               sum(CASE WHEN c.valid_from IS NOT NULL THEN 1 ELSE 0 END) AS with_valid_from,
               sum(CASE WHEN c.valid_from_marker IS NOT NULL THEN 1 ELSE 0 END) AS with_marker,
               sum(CASE WHEN c.valid_from_source IS NOT NULL THEN 1 ELSE 0 END) AS with_source
    """, {"tenant": tenant_id})

    # 2. Indexes bitemporels ONLINE
    idx_rows = run(client, """
        SHOW INDEXES YIELD name, state
        WHERE name IN ['claim_active','claim_event_time','claim_ingested','claim_valid_from_marker']
        RETURN name, state
    """)

    coverage = cov_rows[0] if cov_rows else {}
    indexes_ok = all(r.get("state") == "ONLINE" for r in idx_rows) and len(idx_rows) == 4

    return {
        "coverage": coverage,
        "ingested_at_complete": coverage.get("total", 0) > 0 and coverage.get("missing_ingested", 1) == 0,
        "indexes_count_ok": len(idx_rows) == 4,
        "indexes_all_online": indexes_ok,
        "indexes": idx_rows,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrateur
# ─────────────────────────────────────────────────────────────────────────────


def _pp_dist(label: str, rows: list[dict[str, Any]], key: str) -> None:
    """Pretty-print a distribution."""
    total = sum(r["n"] for r in rows) or 1
    for r in rows:
        pct = 100 * r["n"] / total
        logger.info(f"      {r[key]:<35} {r['n']:>6}  ({pct:5.1f}%)")


def main():
    ap = argparse.ArgumentParser(description="Audit post-réingestion PHASE A2")
    ap.add_argument("--tenant", default="default")
    ap.add_argument(
        "--out",
        default=None,
        help="Chemin JSON (default: data/benchmark/phase_a2/audit_<ts>.json)",
    )
    args = ap.parse_args()

    logger.info(f"\n=== AUDIT POST-RÉINGESTION PHASE A2 — tenant={args.tenant} ===\n")
    client = get_client()
    report: dict[str, Any] = {
        "tenant_id": args.tenant,
        "executed_at": datetime.now(timezone.utc).isoformat(),
    }

    # T1
    logger.info("▶ T1 — Counts globaux")
    t1 = t1_global_counts(client, args.tenant)
    report["t1_counts"] = t1
    for k, v in t1.items():
        logger.info(f"    {k:<25} {v}")

    # T2 — marker
    logger.info("\n▶ T2 — Distribution `valid_from_marker`")
    t2 = t2_marker_distribution(client, args.tenant)
    report["t2_marker"] = t2
    logger.info("  Sur les DocumentContext :")
    _pp_dist("doc", t2["by_document"], "marker")
    logger.info("  Sur les Claims :")
    _pp_dist("claim", t2["by_claim"], "marker")

    # T3 — source
    logger.info("\n▶ T3 — Distribution `valid_from_source`")
    t3 = t3_source_distribution(client, args.tenant)
    report["t3_source"] = t3
    logger.info("  Sur les DocumentContext :")
    _pp_dist("doc", t3["by_document"], "source")
    logger.info("  Sur les Claims :")
    _pp_dist("claim", t3["by_claim"], "source")

    # T4 — années
    logger.info("\n▶ T4 — Distribution `valid_from` par année")
    t4 = t4_year_distribution(client, args.tenant)
    report["t4_year"] = t4
    logger.info("  Sur les DocumentContext :")
    _pp_dist("doc", t4["by_document"], "year")

    # T5 — NULL valid_from
    logger.info("\n▶ T5 — Documents avec `valid_from = NULL`")
    t5 = t5_null_valid_from(client, args.tenant)
    report["t5_null"] = t5
    logger.info(f"    {t5['count']} doc(s) sans date d'effet extraite")
    for d in t5["docs"][:10]:
        logger.info(f"      • {d['doc_id'][:60]:<60} {d['n_claims']:>5} claims — marker={d['marker']} warning={d.get('warning','-')}")
    if t5["count"] > 10:
        logger.info(f"      ... ({t5['count'] - 10} autres dans le JSON)")

    # T6 — cohérence
    logger.info("\n▶ T6 — Cohérence Claim ↔ DocumentContext (héritage valid_from)")
    t6 = t6_coherence(client, args.tenant)
    report["t6_coherence"] = t6
    for r in t6["distribution"]:
        logger.info(f"      {r['status']:<25} {r['n']}")

    # T7 — claims par doc
    logger.info("\n▶ T7 — Audit claims par doc")
    t7 = t7_claims_per_doc(client, args.tenant)
    report["t7_per_doc"] = t7
    stats = t7.get("stats", {})
    logger.info(f"    Total docs : {t7['total_docs']}, total claims : {t7['claims_total']}")
    logger.info(f"    Claims/doc : min={stats.get('min')}, max={stats.get('max')}, "
                f"mean={stats.get('mean')}, docs_avec_0_claims={stats.get('docs_with_zero_claims')}")
    logger.info("    Top 5 docs (claims):")
    for d in t7.get("top_5_largest", []):
        logger.info(f"      • {d['doc_id'][:55]:<55} {d['n_claims']:>4} claims (marker={d.get('marker')})")

    # T8 — Gate-B critical
    logger.info("\n▶ T8 — Gate-B critical (couverture ingested_at + indexes)")
    t8 = t8_gate_b_critical(client, args.tenant)
    report["t8_gate_b"] = t8
    cov = t8.get("coverage", {})
    logger.info(f"    Total claims : {cov.get('total', 0)}")
    logger.info(f"    Missing ingested_at : {cov.get('missing_ingested', 0)} (attendu 0)")
    logger.info(f"    With valid_from non-NULL : {cov.get('with_valid_from', 0)}")
    logger.info(f"    With valid_from_marker : {cov.get('with_marker', 0)}")
    logger.info(f"    With valid_from_source : {cov.get('with_source', 0)}")
    logger.info(f"    4 indexes bitemporels ONLINE : {t8.get('indexes_all_online')}")

    # Verdict global
    coverage_ok = t8.get("ingested_at_complete", False)
    indexes_ok = t8.get("indexes_all_online", False)
    marker_propagated = cov.get("with_marker", 0) == cov.get("total", -1)
    overall = coverage_ok and indexes_ok and marker_propagated

    logger.info(f"\n=== Verdict global : {'✅ PASS' if overall else '❌ ATTENTION'} ===")
    if not coverage_ok:
        logger.info(f"  ❌ Coverage ingested_at incomplete ({cov.get('missing_ingested')} missing)")
    if not indexes_ok:
        logger.info(f"  ❌ Indexes bitemporels manquants ou non-ONLINE")
    if not marker_propagated:
        logger.info(f"  ❌ `valid_from_marker` non propagé sur tous les claims (§9.6 KO ?)")

    # Persist JSON
    out_path = (
        Path(args.out)
        if args.out
        else Path(f"data/benchmark/phase_a2/audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    logger.info(f"\nRapport persisté : {out_path}")

    sys.exit(0 if overall else 1)


if __name__ == "__main__":
    main()
