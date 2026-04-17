#!/usr/bin/env python3
"""
relink_noun_chunks.py — Re-lie les claims orphelines via spaCy noun chunks.

Couche 1 de l'ADR Entity Extraction Domain-Agnostic :
- Extrait les noun chunks (groupes nominaux) via spaCy
- Chaque entité est un span EXACT du texte source (text-anchored)
- Filtre IDF pour exclure les termes trop génériques
- Crée les Entity nodes et relations ABOUT manquantes

Usage :
    docker compose exec app python scripts/relink_noun_chunks.py --dry-run
    docker compose exec app python scripts/relink_noun_chunks.py --execute
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from typing import Dict, List, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("[OSMOSE] relink_noun_chunks")


def get_neo4j_driver():
    from neo4j import GraphDatabase
    uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(uri, auth=(user, password))


def load_orphan_claims(session, tenant_id: str) -> list:
    """Charge les claims sans aucune relation ABOUT."""
    from knowbase.claimfirst.models.claim import Claim
    result = session.run("""
        MATCH (c:Claim {tenant_id: $tid})
        WHERE NOT EXISTS { MATCH (c)-[:ABOUT]->(:Entity) }
        RETURN c.claim_id AS claim_id, c.text AS text, c.doc_id AS doc_id
    """, tid=tenant_id)
    claims = []
    for r in result:
        claims.append(Claim.model_construct(
            claim_id=r["claim_id"],
            text=r["text"] or "",
            doc_id=r["doc_id"] or "",
            tenant_id=tenant_id,
            unit_ids=[],
            claim_type="FACTUAL",
            verbatim_quote=r["text"] or "",
            passage_id="unknown",
        ))
    return claims


def load_entity_index(session, tenant_id: str) -> Dict[str, str]:
    """Charge normalized_name → entity_id pour toutes les entités existantes."""
    result = session.run("""
        MATCH (e:Entity {tenant_id: $tid})
        RETURN e.normalized_name AS norm, e.entity_id AS eid
    """, tid=tenant_id)
    return {r["norm"]: r["eid"] for r in result if r["norm"]}


def build_idf_checker():
    """Construit un checker IDF depuis corpus_stats."""
    try:
        from knowbase.common.corpus_stats import is_generic_by_idf
        # Tester que ça fonctionne
        is_generic_by_idf("test")
        logger.info("IDF checker actif")
        return is_generic_by_idf
    except Exception as e:
        logger.warning(f"Impossible de charger corpus_stats: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(description="Re-lie les claims orphelines via noun chunks spaCy")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--tenant-id", default="default")
    parser.add_argument("--limit", type=int, default=0, help="Limiter le nombre de claims (0 = toutes)")
    args = parser.parse_args()

    if not args.execute and not args.dry_run:
        print("Usage: --execute ou --dry-run")
        sys.exit(1)

    driver = get_neo4j_driver()

    # 1. Charger les orphelins
    with driver.session() as session:
        claims = load_orphan_claims(session, args.tenant_id)
        entity_index = load_entity_index(session, args.tenant_id)

    logger.info(f"Claims orphelines: {len(claims)}")
    logger.info(f"Entités existantes: {len(entity_index)}")

    if not claims:
        logger.info("Aucune claim orpheline.")
        return

    if args.limit > 0:
        claims = claims[:args.limit]
        logger.info(f"Limité à {len(claims)} claims")

    # 2. IDF checker
    idf_checker = build_idf_checker()

    # 3. Charger les domain_terms depuis le domain pack actif
    domain_terms = set()
    try:
        from knowbase.domain_packs.registry import get_pack_registry
        registry = get_pack_registry()
        for pack in registry.get_active_packs(args.tenant_id):
            ctx = pack.get_context_defaults() if hasattr(pack, 'get_context_defaults') else {}
            if not ctx:
                # Charger directement depuis le fichier (builtin prioritaire, plus récent)
                import json
                from pathlib import Path
                candidates = [
                    Path("/app/src/knowbase/domain_packs") / pack.name / "context_defaults.json",
                    Path(f"/data/packs/{pack.name}/context_defaults.json"),
                ]
                for ctx_path in candidates:
                    if ctx_path.exists():
                        ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
                        break
            terms = ctx.get("domain_terms", [])
            domain_terms.update(terms)
            # Aussi ajouter les acronymes du pack comme domain_terms
            for acr in ctx.get("common_acronyms", {}):
                domain_terms.add(acr)
            logger.info(f"Domain pack '{pack.name}': {len(terms)} domain_terms, {len(ctx.get('common_acronyms', {}))} acronymes")
    except Exception as e:
        logger.warning(f"Impossible de charger domain_terms: {e}")

    logger.info(f"Domain terms total: {len(domain_terms)}")

    # 4. Extraire les noun chunks
    from knowbase.claimfirst.extractors.noun_chunk_extractor import NounChunkExtractor

    extractor = NounChunkExtractor(
        use_idf_filter=idf_checker is not None,
        domain_terms=domain_terms,
    )
    # 5. Extraire
    new_entities, links = extractor.extract_from_claims(
        claims=claims,
        tenant_id=args.tenant_id,
        existing_entity_index=entity_index,
        idf_checker=idf_checker,
    )

    # Stats
    claims_with_links = len(set(cid for cid, _ in links))
    claims_still_orphan = len(claims) - claims_with_links

    logger.info(f"\n{'='*60}")
    logger.info(f"RÉSULTATS")
    logger.info(f"{'='*60}")
    logger.info(f"Claims analysées: {len(claims)}")
    logger.info(f"Claims re-liées: {claims_with_links}")
    logger.info(f"Claims toujours orphelines: {claims_still_orphan}")
    logger.info(f"Nouvelles entités: {len(new_entities)}")
    logger.info(f"Liens ABOUT à créer: {len(links)}")
    logger.info(f"Stats extracteur: {dict(extractor.stats)}")

    # Top nouvelles entités
    from collections import Counter
    entity_counts = Counter()
    for _, eid in links:
        for e in new_entities:
            if e.entity_id == eid:
                entity_counts[e.name] += 1
                break
        else:
            # Entité existante
            for norm, existing_eid in entity_index.items():
                if existing_eid == eid:
                    entity_counts[f"[existing] {norm}"] += 1
                    break

    logger.info(f"\nTop 20 entités (nouvelles + existantes):")
    for name, cnt in entity_counts.most_common(20):
        logger.info(f"  {name:50s} {cnt:4d} liens")

    if args.dry_run:
        logger.info(f"\n=== DRY RUN — aucune modification ===")
        driver.close()
        return

    # 4. Persister
    logger.info(f"\nPersistance...")
    start = time.time()

    BATCH_SIZE = 500
    with driver.session() as session:
        # 4a. Créer les nouvelles entités (taguées source='noun_chunk' pour rollback)
        if new_entities:
            batch = [e.to_neo4j_properties() for e in new_entities]
            for item in batch:
                item["source"] = "noun_chunk"
            for i in range(0, len(batch), BATCH_SIZE):
                session.run("""
                    UNWIND $batch AS item
                    MERGE (e:Entity {normalized_name: item.normalized_name, tenant_id: item.tenant_id})
                    ON CREATE SET e += item, e.source = 'noun_chunk'
                    ON MATCH SET e.mention_count = e.mention_count + 1
                """, batch=batch[i:i+BATCH_SIZE])
            logger.info(f"  {len(new_entities)} entités créées/mises à jour (source=noun_chunk)")

        # 4b. Créer les liens ABOUT (par normalized_name pour éviter le bug entity_id)
        link_batch = []
        entity_norm_by_id = {e.entity_id: e.normalized_name for e in new_entities}
        for cid, eid in links:
            norm = entity_norm_by_id.get(eid)
            if not norm:
                # Entité existante — trouver le normalized_name
                for n, existing_eid in entity_index.items():
                    if existing_eid == eid:
                        norm = n
                        break
            if norm:
                link_batch.append({"claim_id": cid, "normalized_name": norm})

        total_created = 0
        for i in range(0, len(link_batch), BATCH_SIZE):
            result = session.run("""
                UNWIND $batch AS item
                MATCH (c:Claim {claim_id: item.claim_id})
                MATCH (e:Entity {normalized_name: item.normalized_name, tenant_id: c.tenant_id})
                MERGE (c)-[r:ABOUT]->(e)
                ON CREATE SET r.method = 'noun_chunk'
                RETURN count(r) AS created
            """, batch=link_batch[i:i+BATCH_SIZE])
            created = result.single()["created"]
            total_created += created
            logger.info(f"  Batch {i//BATCH_SIZE + 1}: {created} liens")

    elapsed = time.time() - start
    logger.info(f"\nTerminé: {total_created} liens ABOUT créés en {elapsed:.1f}s")

    # 5. Vérification finale
    with driver.session() as session:
        result = session.run("""
            MATCH (c:Claim {tenant_id: $tid})
            WITH count(c) AS total,
                 sum(CASE WHEN EXISTS { MATCH (c)-[:ABOUT]->() } THEN 1 ELSE 0 END) AS linked
            RETURN total, linked, total - linked AS orphans,
                   round(100.0 * linked / total) AS pct_linked
        """, tid=args.tenant_id)
        r = result.single()
        logger.info(f"\nÉtat final du KG:")
        logger.info(f"  Total claims: {r['total']}")
        logger.info(f"  Claims liées: {r['linked']} ({r['pct_linked']}%)")
        logger.info(f"  Orphelines restantes: {r['orphans']}")

    driver.close()


if __name__ == "__main__":
    main()
