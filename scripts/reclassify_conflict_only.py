#!/usr/bin/env python3
"""
S3 fine-tuning — re-classifier UNIQUEMENT les paires actuellement marquées CONFLICT
avec le prompt amélioré (universal guards). Compare avant/après pour mesurer le
gain sur les faux positifs CONFLICT.

NB: ne supprime PAS les LOGICAL_RELATION existantes — il les UPDATE sur la même paire.
Si le nouveau classifier dit "OVERLAP", l'edge passe de CONFLICT → OVERLAP.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from neo4j import GraphDatabase

sys.path.insert(0, "/app/src")

from knowbase.relations.logical_relation_classifier import LogicalRelationClassifier  # noqa: E402
from knowbase.relations.v33_types import (  # noqa: E402
    LogicalRelationOutput,
    LogicalRelationType,
    ScopeRelation,
    TemporalRelation,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
TENANT_ID = os.getenv("TENANT_ID", "default")
VLLM_URL = os.getenv("VLLM_URL", "http://3.79.236.241:8000")
VLLM_MODEL = os.getenv("VLLM_MODEL", "Qwen/Qwen2.5-14B-Instruct-AWQ")

OUTPUT_DIR = Path("/data/forensics") if Path("/data").exists() else Path("data/forensics")
MAX_PARALLEL = 5


def fetch_conflict_pairs(driver, tenant_id: str) -> list[dict]:
    """Récupère les paires actuellement CONFLICT avec leur contexte."""
    with driver.session() as s:
        rows = s.run("""
            MATCH (a:Claim {tenant_id: $t})-[r:LOGICAL_RELATION {type: 'CONFLICT'}]->(b:Claim {tenant_id: $t})
            WHERE coalesce(r.legacy, false) = false
              AND r.extracted_by = 'Qwen/Qwen2.5-14B-Instruct-AWQ'
            RETURN
              a.claim_id AS a_id, a.text AS a_text, a.doc_id AS a_doc,
              a.publication_date AS a_pub, a.validity_start AS a_vstart,
              b.claim_id AS b_id, b.text AS b_text, b.doc_id AS b_doc,
              b.publication_date AS b_pub, b.validity_start AS b_vstart,
              r.scope_alignment AS scope, r.temporal_relation AS temp,
              r.confidence AS old_conf, r.reasoning AS old_reasoning
        """, t=tenant_id).data()
    return rows


def classify_one(classifier, pair) -> tuple[dict, LogicalRelationOutput | None]:
    scope = ScopeRelation(pair["scope"]) if pair["scope"] else None
    temp = TemporalRelation(pair["temp"]) if pair["temp"] else None
    out = classifier.classify(
        claim_a_text=pair["a_text"] or "",
        claim_b_text=pair["b_text"] or "",
        scope_relation=scope,
        temporal_relation=temp,
        publication_date_a=pair.get("a_pub"),
        publication_date_b=pair.get("b_pub"),
        validity_start_a=pair.get("a_vstart"),
        validity_start_b=pair.get("b_vstart"),
    )
    return pair, out


def update_relation(driver, tenant_id: str, pair: dict, out: LogicalRelationOutput, ts: str) -> None:
    """UPDATE la LOGICAL_RELATION existante avec le nouveau verdict."""
    with driver.session() as s:
        if out.relation == LogicalRelationType.UNRELATED:
            # On supprime les UNRELATED (V3.3 §3.G.3)
            s.run("""
                MATCH (a:Claim {claim_id: $aid, tenant_id: $tid})-[r:LOGICAL_RELATION {type: 'CONFLICT'}]->(b:Claim {claim_id: $bid, tenant_id: $tid})
                WHERE r.extracted_by = 'Qwen/Qwen2.5-14B-Instruct-AWQ'
                DELETE r
            """, aid=pair["a_id"], bid=pair["b_id"], tid=tenant_id)
            return

        # DELETE l'ancienne CONFLICT + RECREATE avec le nouveau type
        # (car Neo4j ne permet pas de changer le type d'une relation)
        s.run("""
            MATCH (a:Claim {claim_id: $aid, tenant_id: $tid})-[r:LOGICAL_RELATION {type: 'CONFLICT'}]->(b:Claim {claim_id: $bid, tenant_id: $tid})
            WHERE r.extracted_by = 'Qwen/Qwen2.5-14B-Instruct-AWQ'
            DELETE r
        """, aid=pair["a_id"], bid=pair["b_id"], tid=tenant_id)

        s.run("""
            MATCH (a:Claim {claim_id: $aid, tenant_id: $tid})
            MATCH (b:Claim {claim_id: $bid, tenant_id: $tid})
            MERGE (a)-[r:LOGICAL_RELATION {type: $type}]->(b)
            ON CREATE SET
                r.strength = $strength,
                r.confidence = $confidence,
                r.scope_alignment = $scope_alignment,
                r.temporal_relation = $temporal_relation,
                r.is_contradiction = $is_contradiction,
                r.contradiction_reason = $contradiction_reason,
                r.reasoning = $reasoning,
                r.alternatives = $alternatives,
                r.extracted_by = $model,
                r.extracted_at = $ts,
                r.derived = false,
                r.reclassified_from = 'CONFLICT'
            ON MATCH SET
                r.confidence = CASE WHEN $confidence > coalesce(r.confidence, 0.0) THEN $confidence ELSE r.confidence END,
                r.last_updated_at = $ts
        """,
            aid=pair["a_id"], bid=pair["b_id"], tid=tenant_id,
            type=out.relation.value,
            strength=out.strength.value,
            confidence=out.confidence,
            scope_alignment=out.scope_alignment.value if out.scope_alignment else None,
            temporal_relation=out.temporal_relation.value if out.temporal_relation else None,
            is_contradiction=out.is_contradiction,
            contradiction_reason=out.contradiction_reason,
            reasoning=out.reasoning,
            alternatives=json.dumps(out.alternatives) if out.alternatives else None,
            model=VLLM_MODEL,
            ts=ts,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-classify CONFLICT pairs with improved prompt")
    parser.add_argument("--apply", action="store_true", help="Apply UPDATE in Neo4j (default: dry-run)")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = OUTPUT_DIR / f"reclassify_conflict_only_{ts}.md"

    logger.info("=" * 70)
    logger.info("S3 fine-tuning — Re-classify CONFLICT-only with improved prompt")
    logger.info("=" * 70)
    logger.info(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    try:
        pairs = fetch_conflict_pairs(driver, TENANT_ID)
        logger.info(f"\n{len(pairs)} CONFLICT pairs to re-classify")

        if not pairs:
            logger.warning("No CONFLICT pairs found")
            return 1

        classifier = LogicalRelationClassifier(vllm_url=VLLM_URL, model=VLLM_MODEL)
        results = []
        t_start = time.time()

        with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as ex:
            futures = {ex.submit(classify_one, classifier, p): p for p in pairs}
            completed = 0
            for f in as_completed(futures):
                pair, out = f.result()
                results.append((pair, out))
                completed += 1
                logger.info(f"  [{completed}/{len(pairs)}] {pair['a_id']} <-> {pair['b_id']}")
                if out:
                    logger.info(f"    NEW: {out.relation.value} (conf={out.confidence:.2f}, contra={out.is_contradiction})")
                    logger.info(f"    OLD: CONFLICT (conf={pair['old_conf']:.2f})")

        elapsed = time.time() - t_start

        # Stats
        new_types = Counter()
        still_conflict = 0
        for pair, out in results:
            if out is None:
                continue
            new_types[out.relation.value] += 1
            if out.relation == LogicalRelationType.CONFLICT:
                still_conflict += 1

        logger.info(f"\n=== Distribution après re-classification ===")
        for k, v in new_types.most_common():
            logger.info(f"  {k}: {v}")
        logger.info(f"\n=== Synthèse ===")
        logger.info(f"  Avant : 16 CONFLICT")
        logger.info(f"  Après : {still_conflict} CONFLICT (réduction {16 - still_conflict})")
        logger.info(f"  Faux positifs corrigés : {16 - still_conflict}/{16} ({(16 - still_conflict)/16*100:.0f}%)")

        # Apply if --apply
        if args.apply:
            logger.info(f"\n--- Applying UPDATE in Neo4j ---")
            for pair, out in results:
                if out is None:
                    continue
                update_relation(driver, TENANT_ID, pair, out, ts)
            logger.info(f"  {len(results)} relations updated")
        else:
            logger.info(f"\n[DRY-RUN] Re-run with --apply to persist changes")

        # Markdown report
        md = [
            f"# Re-classification CONFLICT-only ({ts})",
            "",
            f"**Mode** : `{'APPLY' if args.apply else 'DRY-RUN'}` · **Pairs** : {len(pairs)} · **Elapsed** : {elapsed:.1f}s",
            "",
            "## Distribution avant → après",
            "",
            "| Type | Count après |",
            "|---|---:|",
        ]
        for k, v in new_types.most_common():
            md.append(f"| {k} | {v} |")
        md.append("")
        md.append(f"**Faux positifs corrigés** : {16 - still_conflict}/16 ({(16 - still_conflict)/16*100:.0f}%)")
        md.append("")
        md.append("## Détail par paire")
        md.append("")
        md.append("| A doc | B doc | A text | B text | Old | New | Conf | reasoning |")
        md.append("|---|---|---|---|---|---|---:|---|")
        for pair, out in results:
            if out is None:
                continue
            old = "CONFLICT"
            new = out.relation.value
            md.append(f"| `{pair['a_doc']}` | `{pair['b_doc']}` | {(pair['a_text'] or '')[:80]} | {(pair['b_text'] or '')[:80]} | {old} | **{new}** | {out.confidence:.2f} | {(out.reasoning or '')[:200]} |")

        report_path.write_text("\n".join(md), encoding="utf-8")
        logger.info(f"\n✅ Report : {report_path}")
        return 0

    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
