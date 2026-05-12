#!/usr/bin/env python3
"""
S3.F.1 — Build golden set d'annotation manuelle.

Extrait ~50 paires diversifiées depuis les LOGICAL_RELATION V3.3 du KG :
- 15 CONFLICT (priorité absolue : valider la précision)
- 10 EXCEPTION (deuxième type sensible)
- 5 SUBSET + 5 SUPERSET (ensembles)
- 10 EQUIVALENT (régression — ne doit pas devenir CONFLICT)
- 5 OVERLAP

Le golden set est persisté dans Neo4j comme un nouveau label `:GoldenPair`
avec la prédiction du classifier et un champ `human_label` (à remplir
manuellement via l'UI ou un script d'annotation).

Schéma :
    (a:Claim)-[:GOLDEN_PAIR_OF]->(g:GoldenPair)<-[:GOLDEN_PAIR_OF]-(b:Claim)
    g.predicted_type, g.predicted_confidence, g.predicted_strength
    g.human_label (null tant que non annoté)
    g.human_notes (texte libre)
    g.created_at

Output : data/forensics/golden_set_<ts>.jsonl pour annotation hors-ligne aussi.

Usage :
    docker exec knowbase-app python /tmp/build_golden_set.py
    docker exec knowbase-app python /tmp/build_golden_set.py --conflict-only --size 30
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from neo4j import GraphDatabase

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
TENANT_ID = os.getenv("TENANT_ID", "default")

OUTPUT_DIR = Path("/data/forensics") if Path("/data").exists() else Path("data/forensics")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# Quotas par défaut (total 50)
DEFAULT_QUOTAS = {
    "CONFLICT": 16,       # Tous (16 disponibles)
    "EXCEPTION": 10,
    "SUBSET": 1,          # Total 1 disponible
    "SUPERSET": 1,        # Total 1 disponible
    "DEFINITION_OF": 1,   # Total 1 disponible
    "EQUIVALENT": 14,     # Échantillon de régression (sur 3 222)
    "OVERLAP": 7,         # Échantillon (sur 432)
}


def fetch_pairs_for_type(driver, tenant_id: str, rel_type: str, limit: int) -> list[dict]:
    """Récupère N paires d'un type donné, avec un mix conf élevé / moyen."""
    with driver.session() as s:
        rows = s.run("""
            MATCH (a:Claim {tenant_id: $t})-[r:LOGICAL_RELATION]->(b:Claim {tenant_id: $t})
            WHERE r.type = $type
              AND coalesce(r.legacy, false) = false
            RETURN
              a.claim_id AS a_id, a.text AS a_text, a.doc_id AS a_doc,
              a.publication_date AS a_pub, a.validity_start AS a_vstart,
              b.claim_id AS b_id, b.text AS b_text, b.doc_id AS b_doc,
              b.publication_date AS b_pub, b.validity_start AS b_vstart,
              r.type AS predicted_type, r.strength AS predicted_strength,
              r.confidence AS predicted_confidence,
              r.is_contradiction AS predicted_is_contradiction,
              r.scope_alignment AS scope_alignment,
              r.temporal_relation AS temporal_relation,
              r.reasoning AS predicted_reasoning,
              r.contradiction_reason AS predicted_contradiction_reason
            ORDER BY rand()
            LIMIT $lim
        """, t=tenant_id, type=rel_type, lim=limit).data()
    return rows


def persist_golden_pair(driver, tenant_id: str, pair: dict, ts: str) -> None:
    """Crée un node :GoldenPair lié aux 2 claims."""
    golden_id = f"golden_{pair['a_id']}_{pair['b_id']}"[:64]
    with driver.session() as s:
        s.run("""
            MATCH (a:Claim {claim_id: $aid, tenant_id: $tid})
            MATCH (b:Claim {claim_id: $bid, tenant_id: $tid})
            MERGE (g:GoldenPair {golden_id: $gid, tenant_id: $tid})
            ON CREATE SET
                g.predicted_type = $ptype,
                g.predicted_strength = $pstrength,
                g.predicted_confidence = $pconf,
                g.predicted_is_contradiction = $pcontra,
                g.predicted_reasoning = $preasoning,
                g.predicted_contradiction_reason = $pcontra_reason,
                g.scope_alignment = $scope,
                g.temporal_relation = $temp,
                g.human_label = null,
                g.human_notes = null,
                g.annotated_at = null,
                g.created_at = $ts
            MERGE (a)-[:GOLDEN_PAIR_OF {role: 'a'}]->(g)
            MERGE (b)-[:GOLDEN_PAIR_OF {role: 'b'}]->(g)
        """,
            aid=pair["a_id"], bid=pair["b_id"], tid=tenant_id, gid=golden_id,
            ptype=pair["predicted_type"],
            pstrength=pair["predicted_strength"],
            pconf=pair["predicted_confidence"],
            pcontra=pair["predicted_is_contradiction"],
            preasoning=pair["predicted_reasoning"],
            pcontra_reason=pair["predicted_contradiction_reason"],
            scope=pair["scope_alignment"],
            temp=pair["temporal_relation"],
            ts=ts,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build golden set for S3.F")
    parser.add_argument("--size", type=int, default=50, help="Total target size (default 50)")
    parser.add_argument("--conflict-only", action="store_true", help="Only sample CONFLICT pairs")
    parser.add_argument("--no-persist", action="store_true", help="Just dump JSONL, don't create GoldenPair nodes")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = OUTPUT_DIR / f"golden_set_{ts}.jsonl"

    logger.info("=" * 70)
    logger.info(f"S3.F.1 — Build golden set ({args.size} pairs)")
    logger.info("=" * 70)

    if args.conflict_only:
        quotas = {"CONFLICT": args.size}
    else:
        quotas = DEFAULT_QUOTAS

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    all_pairs = []

    try:
        for rel_type, quota in quotas.items():
            pairs = fetch_pairs_for_type(driver, TENANT_ID, rel_type, quota)
            logger.info(f"  {rel_type}: {len(pairs)} pairs (quota {quota})")
            for p in pairs:
                p["_quota_type"] = rel_type
            all_pairs.extend(pairs)

        logger.info(f"\nTotal collected: {len(all_pairs)} pairs")

        # Persist GoldenPair nodes
        if not args.no_persist:
            logger.info("\n--- Persisting GoldenPair nodes ---")
            for pair in all_pairs:
                persist_golden_pair(driver, TENANT_ID, pair, ts)
            logger.info(f"  Persisted {len(all_pairs)} GoldenPair nodes")

        # Dump JSONL
        with out_path.open("w", encoding="utf-8") as f:
            for p in all_pairs:
                f.write(json.dumps(p, ensure_ascii=False, default=str) + "\n")
        logger.info(f"\n✅ Dumped JSONL: {out_path}")
        logger.info(f"\n📋 Next step: annoter les paires via /admin/relations/golden-set (UI)")
        logger.info(f"             puis lancer scripts/eval_classifier_golden.py pour mesurer précision")

        return 0
    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
