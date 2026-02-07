#!/usr/bin/env python3
"""
Détection rétroactive des chaînes S/P/O cross-document dans Neo4j.

Pour chaque paire de documents, si claim_A.object == claim_B.subject (normalisé)
ET A et B sont dans des documents différents, crée une relation CHAINS_TO cross-doc.

Caractéristiques :
  - Exclusion des hub entities (trop fréquentes pour être informatives)
  - Ranking déterministe : prédicat priority → IDF → tie-break claim_id
  - Caps par join_key et par paire de documents
  - Jointure par entity_id (robuste) avec fallback normalized_name
  - Idempotent : deux runs = même graphe

Usage (dans le conteneur Docker) :
    python scripts/detect_cross_doc_chains.py --dry-run --tenant default
    python scripts/detect_cross_doc_chains.py --execute --tenant default
    python scripts/detect_cross_doc_chains.py --execute --purge-first --tenant default
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from typing import Dict, List, Set, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def get_neo4j_driver():
    """Crée une connexion Neo4j."""
    from neo4j import GraphDatabase

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    neo4j_user = os.getenv("NEO4J_USER", "neo4j")
    neo4j_password = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")
    return GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_password))


def load_claims_with_sf(session, tenant_id: str) -> List[dict]:
    """Charge les claims avec structured_form depuis Neo4j."""
    result = session.run(
        """
        MATCH (c:Claim {tenant_id: $tenant_id})
        WHERE c.structured_form_json IS NOT NULL
        RETURN c.claim_id AS claim_id,
               c.doc_id AS doc_id,
               c.structured_form_json AS structured_form_json,
               c.confidence AS confidence
        ORDER BY c.doc_id
        """,
        tenant_id=tenant_id,
    )
    claims = []
    for record in result:
        try:
            sf = json.loads(record["structured_form_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        claims.append({
            "claim_id": record["claim_id"],
            "doc_id": record["doc_id"],
            "structured_form": sf,
            "confidence": record["confidence"] or 0.5,
        })
    return claims


def build_entity_index(session, tenant_id: str) -> Dict[str, str]:
    """Construit un index normalized_name → entity_id depuis Neo4j."""
    result = session.run(
        """
        MATCH (e:Entity {tenant_id: $tenant_id})
        RETURN e.normalized_name AS norm, e.entity_id AS eid
        """,
        tenant_id=tenant_id,
    )
    return {r["norm"]: r["eid"] for r in result if r["norm"]}


def detect_hub_entities(
    session,
    tenant_id: str,
    max_hub_claims: int = 200,
    max_ratio: float = 150.0,
) -> Tuple[Set[str], List[dict]]:
    """
    Détecte les hub entities (trop fréquentes pour être des join_keys informatifs).

    Critères :
      - Ubiquité : présent dans TOUS les documents
      - Densité : > max_hub_claims claims
      - Ratio : claims/docs > max_ratio

    Un entity est hub si TOUS les 3 critères sont remplis (ubiquité + densité)
    OU si la densité seule dépasse le seuil.

    Returns:
        Tuple (set de normalized_names, liste de détails hub)
    """
    # D'abord, compter le nombre total de documents
    doc_count_result = session.run(
        """
        MATCH (c:Claim {tenant_id: $tenant_id})
        WHERE c.structured_form_json IS NOT NULL
        RETURN count(DISTINCT c.doc_id) AS total_docs
        """,
        tenant_id=tenant_id,
    )
    total_docs = doc_count_result.single()["total_docs"]

    if total_docs == 0:
        return set(), []

    # Analyser les entities
    result = session.run(
        """
        MATCH (e:Entity {tenant_id: $tenant_id})<-[:ABOUT]-(c:Claim)
        WHERE c.structured_form_json IS NOT NULL
        WITH e, count(DISTINCT c.doc_id) AS nb_docs, count(c) AS nb_claims
        RETURN e.normalized_name AS name, nb_docs, nb_claims
        ORDER BY nb_claims DESC
        """,
        tenant_id=tenant_id,
    )

    hubs: Set[str] = set()
    hub_details: List[dict] = []

    for record in result:
        name = record["name"]
        nb_docs = record["nb_docs"]
        nb_claims = record["nb_claims"]
        ratio = nb_claims / nb_docs if nb_docs > 0 else 0

        is_hub = False
        reasons = []

        # Critère densité seule (entité très fréquente)
        if nb_claims > max_hub_claims:
            is_hub = True
            reasons.append(f"densité={nb_claims}>{max_hub_claims}")

        # Critère ubiquité + ratio
        if nb_docs >= total_docs and ratio > max_ratio:
            is_hub = True
            reasons.append(f"ubiquité={nb_docs}/{total_docs}, ratio={ratio:.0f}>{max_ratio}")

        if is_hub:
            hubs.add(name)
            hub_details.append({
                "name": name,
                "nb_docs": nb_docs,
                "nb_claims": nb_claims,
                "ratio": ratio,
                "reasons": reasons,
            })

    return hubs, hub_details


def count_cross_doc_chains(session, tenant_id: str) -> int:
    """Compte les relations CHAINS_TO cross-doc existantes."""
    result = session.run(
        """
        MATCH (c1:Claim {tenant_id: $tenant_id})-[r:CHAINS_TO]->(c2:Claim)
        WHERE r.cross_doc = true
        RETURN count(r) AS chain_count
        """,
        tenant_id=tenant_id,
    )
    record = result.single()
    return record["chain_count"] if record else 0


def count_intra_doc_chains(session, tenant_id: str) -> int:
    """Compte les relations CHAINS_TO intra-doc existantes."""
    result = session.run(
        """
        MATCH (c1:Claim {tenant_id: $tenant_id})-[r:CHAINS_TO]->(c2:Claim)
        WHERE coalesce(r.cross_doc, false) = false
        RETURN count(r) AS chain_count
        """,
        tenant_id=tenant_id,
    )
    record = result.single()
    return record["chain_count"] if record else 0


def purge_cross_doc_chains(session, tenant_id: str) -> int:
    """Supprime les CHAINS_TO cross-doc uniquement."""
    result = session.run(
        """
        MATCH (c1:Claim {tenant_id: $tenant_id})-[r:CHAINS_TO]->(c2:Claim)
        WHERE r.cross_doc = true
        DELETE r
        RETURN count(r) AS deleted
        """,
        tenant_id=tenant_id,
    )
    record = result.single()
    return record["deleted"] if record else 0


def persist_cross_doc_chain(session, link, tenant_id: str, idf: float) -> bool:
    """Persiste un ChainLink cross-doc comme edge CHAINS_TO dans Neo4j."""
    result = session.run(
        """
        MATCH (c1:Claim {claim_id: $source_id, tenant_id: $tenant_id})
        MATCH (c2:Claim {claim_id: $target_id, tenant_id: $tenant_id})
        MERGE (c1)-[r:CHAINS_TO]->(c2)
        SET r.confidence = 1.0,
            r.basis = $basis,
            r.join_key = $join_key,
            r.join_key_idf = $idf,
            r.method = 'spo_join_cross_doc',
            r.join_method = $join_method,
            r.derived = true,
            r.cross_doc = true,
            r.source_doc_id = $source_doc_id,
            r.target_doc_id = $target_doc_id,
            r.join_key_freq = $freq
        RETURN r IS NOT NULL AS created
        """,
        source_id=link.source_claim_id,
        target_id=link.target_claim_id,
        tenant_id=tenant_id,
        basis=f"join_key={link.join_key}",
        join_key=link.join_key,
        idf=idf,
        join_method=link.join_method,
        source_doc_id=link.source_doc_id,
        target_doc_id=link.target_doc_id,
        freq=link.join_key_freq,
    )
    record = result.single()
    return bool(record and record["created"])


def main():
    parser = argparse.ArgumentParser(
        description="Détection rétroactive des chaînes S/P/O cross-document dans Neo4j"
    )
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Afficher sans modifier (défaut)")
    parser.add_argument("--execute", action="store_true",
                        help="Exécuter les modifications")
    parser.add_argument("--tenant", default="default",
                        help="Tenant ID (default: 'default')")
    parser.add_argument("--max-hub-claims", type=int, default=200,
                        help="Seuil densité hub (default: 200)")
    parser.add_argument("--max-ratio", type=float, default=150.0,
                        help="Seuil ratio claims/docs hub (default: 150.0)")
    parser.add_argument("--max-edges-per-key", type=int, default=5,
                        help="Max edges cross-doc par join_key (default: 5)")
    parser.add_argument("--max-edges-per-doc-pair", type=int, default=50,
                        help="Max edges cross-doc par paire de docs (default: 50)")
    parser.add_argument("--purge-first", action="store_true",
                        help="Purger les cross-doc existantes avant le run")
    args = parser.parse_args()

    if args.execute:
        args.dry_run = False

    from knowbase.claimfirst.composition.chain_detector import ChainDetector

    driver = get_neo4j_driver()

    try:
        with driver.session() as session:
            # 1. Charger les claims avec structured_form
            logger.info(
                f"[OSMOSE] Chargement des claims avec structured_form "
                f"(tenant={args.tenant})..."
            )
            claims = load_claims_with_sf(session, args.tenant)
            logger.info(f"  → {len(claims)} claims avec structured_form")

            if not claims:
                logger.info("Aucune claim avec structured_form à traiter.")
                return

            # Stats par document
            by_doc: Dict[str, int] = defaultdict(int)
            for c in claims:
                by_doc[c["doc_id"]] += 1
            logger.info(f"  → {len(by_doc)} documents")
            for doc_id, count in sorted(by_doc.items()):
                logger.info(f"    {doc_id[:50]}: {count} claims")

            if len(by_doc) < 2:
                logger.info("Un seul document — pas de cross-doc possible.")
                return

            # 2. Construire l'entity index
            logger.info("\n[OSMOSE] Construction de l'entity index...")
            entity_index = build_entity_index(session, args.tenant)
            logger.info(f"  → {len(entity_index)} entries")

            # 3. Détecter les hubs
            logger.info(
                f"\n[OSMOSE] Détection des hubs (max_claims={args.max_hub_claims}, "
                f"max_ratio={args.max_ratio})..."
            )
            hub_entities, hub_details = detect_hub_entities(
                session, args.tenant,
                max_hub_claims=args.max_hub_claims,
                max_ratio=args.max_ratio,
            )
            logger.info(f"  → {len(hub_entities)} hubs exclus")
            for hub in hub_details:
                logger.info(
                    f"    '{hub['name']}': {hub['nb_claims']} claims, "
                    f"{hub['nb_docs']} docs, ratio={hub['ratio']:.0f} "
                    f"({', '.join(hub['reasons'])})"
                )

            # 4. Calculer l'IDF
            logger.info("\n[OSMOSE] Calcul de l'IDF par join_key...")
            idf_map = ChainDetector.compute_idf(claims, entity_index=entity_index)
            logger.info(f"  → {len(idf_map)} join_keys avec IDF")

            # 5. Détecter les chaînes cross-doc
            logger.info(
                f"\n[OSMOSE] Détection des chaînes cross-doc "
                f"(max_per_key={args.max_edges_per_key}, "
                f"max_per_doc_pair={args.max_edges_per_doc_pair})..."
            )
            detector = ChainDetector(
                max_edges_per_key_cross_doc=args.max_edges_per_key,
                max_edges_per_doc_pair=args.max_edges_per_doc_pair,
            )
            links = detector.detect_cross_doc(
                claims,
                hub_entities=hub_entities,
                entity_index=entity_index,
                idf_map=idf_map,
            )
            logger.info(f"  → {len(links)} chaînes cross-doc détectées")

            # Stats détaillées
            cross_stats = detector.get_cross_doc_stats()
            logger.info(f"  → claims_with_sf: {cross_stats['claims_with_sf']}")
            logger.info(f"  → join_keys_found: {cross_stats['join_keys_found']}")
            logger.info(f"  → join_keys_capped: {cross_stats['join_keys_capped']}")
            logger.info(f"  → joins_by_entity_id: {cross_stats['joins_by_entity_id']}")
            logger.info(f"  → joins_by_normalized: {cross_stats['joins_by_normalized']}")
            logger.info(f"  → doc_pairs_capped: {cross_stats['doc_pairs_capped']}")

            # Distribution par paire de docs
            doc_pair_counts: Dict[str, int] = defaultdict(int)
            join_keys_used: Dict[str, int] = defaultdict(int)
            for link in links:
                dp_key = f"{link.source_doc_id[:30]} ↔ {link.target_doc_id[:30]}"
                doc_pair_counts[dp_key] += 1
                join_keys_used[link.join_key] += 1

            logger.info(f"\n  Par paire de docs:")
            for dp, count in sorted(
                doc_pair_counts.items(), key=lambda x: x[1], reverse=True
            ):
                logger.info(f"    {dp}: {count}")

            logger.info(f"\n  Top join_keys (par nombre d'edges):")
            for jk, count in sorted(
                join_keys_used.items(), key=lambda x: x[1], reverse=True
            )[:20]:
                jk_idf = idf_map.get(jk, 0.0)
                logger.info(f"    '{jk}': {count} edges (idf={jk_idf:.2f})")

            # Métriques qualité
            total_edges = len(links)
            unique_join_keys = len(join_keys_used)
            if total_edges > 0:
                ratio = unique_join_keys / total_edges
                logger.info(f"\n  Ratio join_keys/edges: {ratio:.3f}")

                entity_id_pct = (
                    cross_stats["joins_by_entity_id"] / total_edges * 100
                    if total_edges > 0
                    else 0
                )
                logger.info(f"  Joins par entity_id: {entity_id_pct:.1f}%")
                logger.info(
                    f"  Joins par normalized: {100 - entity_id_pct:.1f}% (fallback)"
                )

            # 6. Compter les existantes
            existing_cross = count_cross_doc_chains(session, args.tenant)
            existing_intra = count_intra_doc_chains(session, args.tenant)
            logger.info(f"\n  CHAINS_TO intra-doc existantes: {existing_intra}")
            logger.info(f"  CHAINS_TO cross-doc existantes: {existing_cross}")

            # 7. Résumé
            logger.info(f"\n{'='*60}")
            logger.info("RÉSUMÉ DÉTECTION CROSS-DOC CHAINS_TO")
            logger.info(f"{'='*60}")
            logger.info(f"Claims avec SF      : {len(claims)} ({len(by_doc)} documents)")
            logger.info(f"Entity index        : {len(entity_index)} entries")
            logger.info(f"Hubs exclus         : {len(hub_entities)}")
            logger.info(f"Join keys trouvés   : {cross_stats['join_keys_found']}")
            logger.info(f"Chaînes cross-doc   : {len(links)}")
            logger.info(f"CHAINS_TO intra-doc : {existing_intra} (inchangées)")
            logger.info(f"CHAINS_TO cross-doc : {existing_cross} (avant)")

            if args.dry_run:
                logger.info(f"\n[DRY-RUN] Aucune modification effectuée.")
                logger.info("    Utilisez --execute pour appliquer.")
                return

            # 8. Purge si demandé
            if args.purge_first:
                logger.info(
                    f"\n[OSMOSE] Purge des cross-doc existantes..."
                )
                deleted = purge_cross_doc_chains(session, args.tenant)
                logger.info(f"  → {deleted} edges cross-doc supprimées")

            # 9. Persister les chaînes
            logger.info(f"\n[OSMOSE] Persistance des {len(links)} chaînes cross-doc...")
            persisted = 0
            for link in links:
                jk_idf = idf_map.get(link.join_key, 0.0)
                if persist_cross_doc_chain(session, link, args.tenant, jk_idf):
                    persisted += 1

            logger.info(f"  → {persisted} edges CHAINS_TO cross-doc créés/mis à jour")

            # 10. Vérification finale
            final_cross = count_cross_doc_chains(session, args.tenant)
            final_intra = count_intra_doc_chains(session, args.tenant)
            logger.info(f"\n  Total CHAINS_TO intra-doc: {final_intra}")
            logger.info(f"  Total CHAINS_TO cross-doc: {final_cross}")
            logger.info(f"  Total CHAINS_TO global   : {final_intra + final_cross}")

            logger.info("\n[OSMOSE] Détection cross-doc terminée.")

    finally:
        driver.close()


if __name__ == "__main__":
    main()
