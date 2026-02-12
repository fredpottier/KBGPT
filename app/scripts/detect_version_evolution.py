#!/usr/bin/env python3
"""
Détection rétroactive de l'évolution temporelle entre documents successifs.

Pour chaque ComparableSubject avec doc_count >= 2, compare les claims entre
versions adjacentes (triées par axe primaire) pour détecter :
  - UNCHANGED : même claim S|P|O
  - MODIFIED : même S+P, objet différent
  - ADDED : claim uniquement dans la nouvelle version
  - REMOVED : claim uniquement dans l'ancienne version

Caractéristiques :
  - Paires adjacentes uniquement (pas O(n²))
  - ABSTAIN si axe ambigu (ordering_confidence == UNKNOWN)
  - Guard-rail multi-candidats S+P (skip si N>1 match dans un doc)
  - Stockage old_object_raw / new_object_raw
  - Idempotent : deux runs = même graphe

Usage (dans le conteneur Docker) :
    python app/scripts/detect_version_evolution.py --dry-run --tenant default
    python app/scripts/detect_version_evolution.py --execute --tenant default
    python app/scripts/detect_version_evolution.py --execute --purge-first --tenant default
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from typing import Dict, List

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


def load_claims_for_doc(session, tenant_id: str, doc_id: str) -> List[dict]:
    """Charge les claims avec structured_form pour un document donné."""
    result = session.run(
        """
        MATCH (c:Claim {tenant_id: $tenant_id, doc_id: $doc_id})
        WHERE c.structured_form_json IS NOT NULL
        RETURN c.claim_id AS claim_id,
               c.doc_id AS doc_id,
               c.structured_form_json AS structured_form_json,
               c.confidence AS confidence,
               c.text AS text
        """,
        tenant_id=tenant_id,
        doc_id=doc_id,
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
            "text": record["text"] or "",
        })
    return claims


def count_evolution_chains(session, tenant_id: str) -> int:
    """Compte les relations CHAINS_TO method=version_evolution existantes."""
    result = session.run(
        """
        MATCH (c1:Claim {tenant_id: $tenant_id})-[r:CHAINS_TO]->(c2:Claim)
        WHERE r.method = 'version_evolution'
        RETURN count(r) AS chain_count
        """,
        tenant_id=tenant_id,
    )
    record = result.single()
    return record["chain_count"] if record else 0


def purge_evolution_chains(session, tenant_id: str) -> int:
    """Supprime les CHAINS_TO method=version_evolution uniquement."""
    result = session.run(
        """
        MATCH (c1:Claim {tenant_id: $tenant_id})-[r:CHAINS_TO]->(c2:Claim)
        WHERE r.method = 'version_evolution'
        DELETE r
        RETURN count(r) AS deleted
        """,
        tenant_id=tenant_id,
    )
    record = result.single()
    return record["deleted"] if record else 0


def persist_evolution_link(session, link, tenant_id: str) -> bool:
    """
    Persiste un EvolutionLink comme edge CHAINS_TO dans Neo4j.

    Propriétés obligatoires pour method=version_evolution (invariant).
    """
    from knowbase.claimfirst.composition.evolution_detector import (
        ClaimEvolution,
        validate_evolution_edge_props,
    )
    from knowbase.claimfirst.models.entity import Entity

    vp = link.version_pair
    chain_type = f"evolution_{link.evolution_type.value}"

    # Construire join_key_name à partir du subject du claim
    join_key_name = vp.subject_name

    props = {
        "method": "version_evolution",
        "chain_type": chain_type,
        "cross_doc": True,
        "comparable_subject_id": vp.subject_id,
        "axis_key": vp.axis_key,
        "old_axis_value": vp.old_value,
        "new_axis_value": vp.new_value,
        "evolution_type": link.evolution_type.value,
        "similarity_score": link.similarity_score,
        "diff_summary": link.diff_summary or "",
        "old_object_raw": link.old_object_raw or "",
        "new_object_raw": link.new_object_raw or "",
        "join_key_name": join_key_name,
    }

    # Valider les propriétés obligatoires
    validate_evolution_edge_props(props)

    # ADDED : pas de source_claim_id → on ne peut pas créer d'edge
    if link.evolution_type == ClaimEvolution.ADDED:
        # Pas d'edge (pas de claim source)
        return False

    # REMOVED : pas de target_claim_id → on ne peut pas créer d'edge
    if link.evolution_type == ClaimEvolution.REMOVED:
        # Pas d'edge (pas de claim target)
        return False

    result = session.run(
        """
        MATCH (c1:Claim {claim_id: $source_id, tenant_id: $tenant_id})
        MATCH (c2:Claim {claim_id: $target_id, tenant_id: $tenant_id})
        MERGE (c1)-[r:CHAINS_TO]->(c2)
        SET r.confidence = $confidence,
            r.method = $method,
            r.chain_type = $chain_type,
            r.derived = true,
            r.cross_doc = $cross_doc,
            r.source_doc_id = $source_doc_id,
            r.target_doc_id = $target_doc_id,
            r.comparable_subject_id = $comparable_subject_id,
            r.axis_key = $axis_key,
            r.old_axis_value = $old_axis_value,
            r.new_axis_value = $new_axis_value,
            r.evolution_type = $evolution_type,
            r.similarity_score = $similarity_score,
            r.diff_summary = $diff_summary,
            r.old_object_raw = $old_object_raw,
            r.new_object_raw = $new_object_raw,
            r.join_key_name = $join_key_name
        RETURN r IS NOT NULL AS created
        """,
        source_id=link.source_claim_id,
        target_id=link.target_claim_id,
        tenant_id=tenant_id,
        confidence=link.similarity_score,
        method=props["method"],
        chain_type=props["chain_type"],
        cross_doc=props["cross_doc"],
        source_doc_id=vp.old_doc_id,
        target_doc_id=vp.new_doc_id,
        comparable_subject_id=vp.subject_id,
        axis_key=vp.axis_key,
        old_axis_value=vp.old_value,
        new_axis_value=vp.new_value,
        evolution_type=link.evolution_type.value,
        similarity_score=link.similarity_score,
        diff_summary=link.diff_summary or "",
        old_object_raw=link.old_object_raw or "",
        new_object_raw=link.new_object_raw or "",
        join_key_name=join_key_name,
    )
    record = result.single()
    return bool(record and record["created"])


def main():
    parser = argparse.ArgumentParser(
        description="Détection rétroactive de l'évolution temporelle entre documents successifs"
    )
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Afficher sans modifier (défaut)")
    parser.add_argument("--execute", action="store_true",
                        help="Exécuter les modifications")
    parser.add_argument("--tenant", default="default",
                        help="Tenant ID (default: 'default')")
    parser.add_argument("--purge-first", action="store_true",
                        help="Purger les evolution chains existantes avant le run")
    parser.add_argument("--axis-key", default="auto",
                        help="Axe de tri (auto=détection automatique, ou 'release_id', 'year', etc.)")
    args = parser.parse_args()

    if args.execute:
        args.dry_run = False

    from knowbase.claimfirst.composition.evolution_detector import (
        ClaimEvolution,
        VersionEvolutionDetector,
    )

    driver = get_neo4j_driver()

    try:
        with driver.session() as session:
            # 1. Détecter les paires de versions
            logger.info(
                f"[OSMOSE] Détection des paires de versions "
                f"(tenant={args.tenant}, axis={args.axis_key})..."
            )

            axis_priority = None
            if args.axis_key != "auto":
                axis_priority = [args.axis_key]

            detector = VersionEvolutionDetector(axis_priority=axis_priority)
            pairs = detector.detect_version_pairs(session, args.tenant)
            logger.info(f"  → {len(pairs)} paires de versions détectées")

            if not pairs:
                logger.info("Aucune paire de versions trouvée.")
                stats = detector.get_stats()
                logger.info(f"  Stats: {stats}")
                return

            # Afficher les paires
            for i, pair in enumerate(pairs):
                logger.info(
                    f"  [{i+1}] {pair.subject_name}: "
                    f"{pair.old_value} → {pair.new_value} "
                    f"(axis={pair.axis_key}, confidence={pair.axis_confidence})"
                )
                logger.info(
                    f"      old_doc={pair.old_doc_id[:50]}"
                )
                logger.info(
                    f"      new_doc={pair.new_doc_id[:50]}"
                )

            # 2. Comparer les claims pour chaque paire
            all_links = []
            evolution_summary: Dict[str, int] = defaultdict(int)

            for pair in pairs:
                logger.info(
                    f"\n[OSMOSE] Comparaison: {pair.subject_name} "
                    f"({pair.old_value} → {pair.new_value})..."
                )

                old_claims = load_claims_for_doc(session, args.tenant, pair.old_doc_id)
                new_claims = load_claims_for_doc(session, args.tenant, pair.new_doc_id)

                logger.info(
                    f"  Claims: old={len(old_claims)}, new={len(new_claims)}"
                )

                links = detector.compare_claims(old_claims, new_claims, pair)
                all_links.extend(links)

                # Stats par type
                pair_summary: Dict[str, int] = defaultdict(int)
                for link in links:
                    pair_summary[link.evolution_type.value] += 1
                    evolution_summary[link.evolution_type.value] += 1

                for etype, count in sorted(pair_summary.items()):
                    logger.info(f"    {etype}: {count}")

            # 3. Résumé global
            logger.info(f"\n{'='*60}")
            logger.info("RÉSUMÉ DÉTECTION ÉVOLUTION TEMPORELLE")
            logger.info(f"{'='*60}")
            logger.info(f"Paires de versions : {len(pairs)}")
            logger.info(f"Liens d'évolution  : {len(all_links)}")
            for etype, count in sorted(evolution_summary.items()):
                logger.info(f"  {etype:12s} : {count}")

            # Stats du détecteur
            stats = detector.get_stats()
            logger.info(f"\nStats détecteur:")
            for k, v in sorted(stats.items()):
                logger.info(f"  {k}: {v}")

            # Liens persistables (UNCHANGED + MODIFIED uniquement)
            persistable = [
                l for l in all_links
                if l.evolution_type in (ClaimEvolution.UNCHANGED, ClaimEvolution.MODIFIED)
            ]
            logger.info(f"\nLiens persistables (UNCHANGED+MODIFIED) : {len(persistable)}")

            # Compter les existants
            existing = count_evolution_chains(session, args.tenant)
            logger.info(f"CHAINS_TO version_evolution existantes : {existing}")

            if args.dry_run:
                logger.info(f"\n[DRY-RUN] Aucune modification effectuée.")
                logger.info("    Utilisez --execute pour appliquer.")

                # Afficher quelques exemples
                modified_links = [
                    l for l in all_links
                    if l.evolution_type == ClaimEvolution.MODIFIED
                ]
                if modified_links:
                    logger.info(f"\n  Exemples de MODIFIED (top 10) :")
                    for link in modified_links[:10]:
                        logger.info(
                            f"    {link.source_claim_id[:20]} → {link.target_claim_id[:20]}"
                        )
                        logger.info(
                            f"      {link.diff_summary}"
                        )
                return

            # 4. Purge si demandé
            if args.purge_first:
                logger.info(f"\n[OSMOSE] Purge des evolution chains existantes...")
                deleted = purge_evolution_chains(session, args.tenant)
                logger.info(f"  → {deleted} edges version_evolution supprimés")

            # 5. Persister
            logger.info(
                f"\n[OSMOSE] Persistance des {len(persistable)} liens d'évolution..."
            )
            persisted = 0
            for link in persistable:
                if persist_evolution_link(session, link, args.tenant):
                    persisted += 1

            logger.info(f"  → {persisted} edges CHAINS_TO version_evolution créés/mis à jour")

            # 6. Vérification finale
            final = count_evolution_chains(session, args.tenant)
            logger.info(f"\n  Total CHAINS_TO version_evolution : {final}")

            # Stats par type
            if final > 0:
                result = session.run(
                    """
                    MATCH (:Claim {tenant_id: $tid})-[r:CHAINS_TO {method: 'version_evolution'}]->()
                    RETURN r.chain_type AS chain_type, count(r) AS cnt
                    ORDER BY cnt DESC
                    """,
                    tid=args.tenant,
                )
                logger.info(f"\n  Par chain_type :")
                for record in result:
                    logger.info(f"    {record['chain_type']}: {record['cnt']}")

            logger.info("\n[OSMOSE] Détection évolution temporelle terminée.")

    finally:
        driver.close()


if __name__ == "__main__":
    main()
