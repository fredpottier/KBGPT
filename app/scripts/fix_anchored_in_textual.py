#!/usr/bin/env python3
"""
Fix ANCHORED_IN relations using textual matching.

ADR: ADR_COVERAGE_PROPERTY_NOT_NODE - Correction

Le script migrate_coverage_to_option_c.py a créé des ANCHORED_IN incorrects
car il utilisait les positions per-page (charspan) au lieu des positions
document-wide (charspan_docwide).

Ce script corrige en:
1. Supprimant les ANCHORED_IN → DocItem incorrects (source='migration_phase2')
2. Recréant les ANCHORED_IN en cherchant les DocItems qui CONTIENNENT
   le concept_name du ProtoConcept (recherche textuelle)

Usage:
    docker-compose exec app python scripts/fix_anchored_in_textual.py
    docker-compose exec app python scripts/fix_anchored_in_textual.py --dry-run
    docker-compose exec app python scripts/fix_anchored_in_textual.py --doc-id <doc_id>
"""

import argparse
import logging
import sys
from typing import Dict, Any, List, Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


def get_neo4j_client():
    """Récupère le client Neo4j."""
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    from knowbase.config.settings import get_settings

    settings = get_settings()
    return get_neo4j_client(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
        database="neo4j"
    )


def get_stats(neo4j_client, tenant_id: str = "default", doc_id: Optional[str] = None) -> Dict[str, Any]:
    """Récupère les statistiques des ANCHORED_IN."""
    doc_filter = "AND p.doc_id = $doc_id" if doc_id else ""

    query = f"""
    MATCH (p:ProtoConcept {{tenant_id: $tenant_id}})-[r:ANCHORED_IN]->(d)
    {f"WHERE p.doc_id = $doc_id" if doc_id else ""}
    RETURN labels(d)[0] AS target_type, r.source AS source, count(*) AS cnt
    ORDER BY target_type, source
    """

    stats = {"by_target": {}, "total": 0}

    with neo4j_client.driver.session(database="neo4j") as session:
        params = {"tenant_id": tenant_id}
        if doc_id:
            params["doc_id"] = doc_id
        result = session.run(query, **params)
        for record in result:
            key = f"{record['target_type']}:{record['source']}"
            stats["by_target"][key] = record["cnt"]
            stats["total"] += record["cnt"]

    return stats


def delete_incorrect_anchors(
    neo4j_client,
    tenant_id: str = "default",
    doc_id: Optional[str] = None,
    dry_run: bool = False
) -> int:
    """Supprime les ANCHORED_IN incorrects (source='migration_phase2')."""
    logger.info("[Phase 1] Suppression des ANCHORED_IN incorrects...")

    doc_filter = "AND p.doc_id = $doc_id" if doc_id else ""

    if dry_run:
        count_query = f"""
        MATCH (p:ProtoConcept {{tenant_id: $tenant_id}})-[r:ANCHORED_IN {{source: 'migration_phase2'}}]->(d:DocItem)
        {f"WHERE p.doc_id = $doc_id" if doc_id else ""}
        RETURN count(r) AS cnt
        """
        with neo4j_client.driver.session(database="neo4j") as session:
            params = {"tenant_id": tenant_id}
            if doc_id:
                params["doc_id"] = doc_id
            result = session.run(count_query, **params)
            record = result.single()
            cnt = record["cnt"] if record else 0
            logger.info(f"[Phase 1] DRY-RUN: {cnt} ANCHORED_IN à supprimer")
            return cnt

    delete_query = f"""
    MATCH (p:ProtoConcept {{tenant_id: $tenant_id}})-[r:ANCHORED_IN {{source: 'migration_phase2'}}]->(d:DocItem)
    {f"WHERE p.doc_id = $doc_id" if doc_id else ""}
    DELETE r
    RETURN count(r) AS deleted
    """

    with neo4j_client.driver.session(database="neo4j") as session:
        params = {"tenant_id": tenant_id}
        if doc_id:
            params["doc_id"] = doc_id
        result = session.run(delete_query, **params)
        record = result.single()
        deleted = record["deleted"] if record else 0
        logger.info(f"[Phase 1] ✅ Supprimé {deleted} ANCHORED_IN incorrects")
        return deleted


def create_textual_anchors(
    neo4j_client,
    tenant_id: str = "default",
    doc_id: Optional[str] = None,
    dry_run: bool = False
) -> int:
    """
    Crée les ANCHORED_IN en cherchant les DocItems contenant le concept_name.

    Stratégie:
    1. Pour chaque ProtoConcept sans ANCHORED_IN → DocItem
    2. Chercher les DocItems de la même section qui contiennent concept_name
    3. Prendre le premier DocItem trouvé (par reading_order_index)
    """
    logger.info("[Phase 2] Création des ANCHORED_IN par recherche textuelle...")

    doc_filter = "AND p.doc_id = $doc_id" if doc_id else ""

    if dry_run:
        count_query = f"""
        MATCH (p:ProtoConcept {{tenant_id: $tenant_id}})
        WHERE p.concept_name IS NOT NULL
          AND NOT EXISTS {{ MATCH (p)-[:ANCHORED_IN]->(d:DocItem) }}
          {f"AND p.doc_id = $doc_id" if doc_id else ""}
        RETURN count(DISTINCT p) AS cnt
        """
        with neo4j_client.driver.session(database="neo4j") as session:
            params = {"tenant_id": tenant_id}
            if doc_id:
                params["doc_id"] = doc_id
            result = session.run(count_query, **params)
            record = result.single()
            cnt = record["cnt"] if record else 0
            logger.info(f"[Phase 2] DRY-RUN: {cnt} ProtoConcepts à ancrer")
            return cnt

    # Créer les anchors par recherche textuelle
    # On cherche les DocItems dont le texte contient le concept_name (case-insensitive)
    # Priorité aux DocItems de la même section
    create_query = f"""
    MATCH (p:ProtoConcept {{tenant_id: $tenant_id}})
    WHERE p.concept_name IS NOT NULL
      AND size(p.concept_name) > 2
      AND NOT EXISTS {{ MATCH (p)-[:ANCHORED_IN]->(d:DocItem) }}
      {f"AND p.doc_id = $doc_id" if doc_id else ""}

    // Chercher les DocItems contenant le concept_name
    MATCH (d:DocItem {{tenant_id: $tenant_id, doc_id: p.doc_id}})
    WHERE d.text IS NOT NULL
      AND toLower(d.text) CONTAINS toLower(p.concept_name)

    // Priorité: même section, puis par ordre de lecture
    WITH p, d,
         CASE WHEN d.section_id = p.section_id THEN 0 ELSE 1 END AS section_priority,
         coalesce(d.reading_order_index, 0) AS roi
    ORDER BY section_priority, roi

    // Prendre le meilleur DocItem pour chaque ProtoConcept
    WITH p, collect(d)[0] AS best_d
    WHERE best_d IS NOT NULL

    // Créer la relation
    MERGE (p)-[r:ANCHORED_IN]->(best_d)
    ON CREATE SET
        r.source = 'textual_fix',
        r.created_at = datetime(),
        r.match_type = 'concept_name_contains'

    RETURN count(r) AS created
    """

    with neo4j_client.driver.session(database="neo4j") as session:
        params = {"tenant_id": tenant_id}
        if doc_id:
            params["doc_id"] = doc_id
        result = session.run(create_query, **params)
        record = result.single()
        created = record["created"] if record else 0
        logger.info(f"[Phase 2] ✅ Créé {created} ANCHORED_IN par recherche textuelle")
        return created


def verify_anchors(neo4j_client, tenant_id: str = "default", doc_id: Optional[str] = None, limit: int = 5):
    """Vérifie quelques ANCHORED_IN pour validation manuelle."""
    logger.info("[Vérification] Échantillon de ANCHORED_IN créés...")

    doc_filter = "AND p.doc_id = $doc_id" if doc_id else ""

    query = f"""
    MATCH (p:ProtoConcept {{tenant_id: $tenant_id}})-[r:ANCHORED_IN {{source: 'textual_fix'}}]->(d:DocItem)
    {f"WHERE p.doc_id = $doc_id" if doc_id else ""}
    RETURN p.concept_name AS concept,
           d.item_id AS docitem,
           d.section_id AS section,
           substring(d.text, 0, 100) AS text_preview
    LIMIT $limit
    """

    with neo4j_client.driver.session(database="neo4j") as session:
        params = {"tenant_id": tenant_id, "limit": limit}
        if doc_id:
            params["doc_id"] = doc_id
        result = session.run(query, **params)

        for record in result:
            concept = record["concept"]
            text = record["text_preview"]
            # Vérifier que le concept est dans le texte
            is_valid = concept.lower() in text.lower() if text else False
            status = "✅" if is_valid else "❌"

            print(f"\n{status} Concept: {concept}")
            print(f"   DocItem: {record['docitem']}")
            print(f"   Section: {record['section']}")
            print(f"   Text: {text}...")


def compute_kpis(neo4j_client, tenant_id: str = "default", doc_id: Optional[str] = None) -> Dict[str, Any]:
    """Calcule les KPIs d'ancrage."""
    doc_filter = "AND p.doc_id = $doc_id" if doc_id else ""

    query = f"""
    // Total ProtoConcepts
    MATCH (p:ProtoConcept {{tenant_id: $tenant_id}})
    {f"WHERE p.doc_id = $doc_id" if doc_id else ""}
    WITH count(p) AS total

    // Avec ANCHORED_IN → DocItem
    MATCH (p2:ProtoConcept {{tenant_id: $tenant_id}})
    {f"WHERE p2.document_id = $doc_id" if doc_id else ""}
    OPTIONAL MATCH (p2)-[:ANCHORED_IN]->(d:DocItem)
    WITH total, count(DISTINCT CASE WHEN d IS NOT NULL THEN p2 END) AS anchored_to_docitem

    // Avec ANCHORED_IN correct (textual_fix)
    MATCH (p3:ProtoConcept {{tenant_id: $tenant_id}})
    {f"WHERE p3.document_id = $doc_id" if doc_id else ""}
    OPTIONAL MATCH (p3)-[r:ANCHORED_IN {{source: 'textual_fix'}}]->(d2:DocItem)
    WITH total, anchored_to_docitem,
         count(DISTINCT CASE WHEN d2 IS NOT NULL THEN p3 END) AS textual_anchored

    RETURN total, anchored_to_docitem, textual_anchored,
           CASE WHEN total > 0
                THEN toFloat(anchored_to_docitem) / total * 100
                ELSE 0 END AS anchor_rate,
           CASE WHEN total > 0
                THEN toFloat(textual_anchored) / total * 100
                ELSE 0 END AS textual_rate
    """

    with neo4j_client.driver.session(database="neo4j") as session:
        params = {"tenant_id": tenant_id}
        if doc_id:
            params["doc_id"] = doc_id
        result = session.run(query, **params)
        record = result.single()
        if record:
            return {
                "total": record["total"],
                "anchored_to_docitem": record["anchored_to_docitem"],
                "textual_anchored": record["textual_anchored"],
                "anchor_rate": record["anchor_rate"],
                "textual_rate": record["textual_rate"],
            }
        return {}


def main():
    parser = argparse.ArgumentParser(
        description="Fix ANCHORED_IN relations using textual matching"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche les opérations sans les exécuter"
    )
    parser.add_argument(
        "--doc-id",
        type=str,
        help="Traiter uniquement ce document"
    )
    parser.add_argument(
        "--tenant",
        type=str,
        default="default",
        help="Tenant ID (défaut: default)"
    )
    parser.add_argument(
        "--skip-delete",
        action="store_true",
        help="Ne pas supprimer les anciens ANCHORED_IN"
    )
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Vérifier uniquement les ANCHORED_IN existants"
    )

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Fix ANCHORED_IN - Recherche Textuelle")
    logger.info("ADR: ADR_COVERAGE_PROPERTY_NOT_NODE - Correction")
    logger.info("=" * 60)

    try:
        neo4j_client = get_neo4j_client()
        if not neo4j_client.is_connected():
            logger.error("❌ Neo4j non connecté")
            sys.exit(1)

        # Stats initiales
        logger.info("\n📊 Statistiques initiales:")
        stats = get_stats(neo4j_client, args.tenant, args.doc_id)
        for key, cnt in stats["by_target"].items():
            logger.info(f"  - {key}: {cnt}")
        logger.info(f"  Total: {stats['total']}")

        if args.verify_only:
            verify_anchors(neo4j_client, args.tenant, args.doc_id)
            kpis = compute_kpis(neo4j_client, args.tenant, args.doc_id)
            logger.info("\n📈 KPIs:")
            logger.info(f"  - Total ProtoConcepts: {kpis.get('total', 0)}")
            logger.info(f"  - Ancrés vers DocItem: {kpis.get('anchored_to_docitem', 0)} ({kpis.get('anchor_rate', 0):.1f}%)")
            logger.info(f"  - Via textual_fix: {kpis.get('textual_anchored', 0)} ({kpis.get('textual_rate', 0):.1f}%)")
            sys.exit(0)

        # Phase 1: Supprimer les incorrects
        if not args.skip_delete:
            logger.info("\n" + "=" * 40)
            delete_incorrect_anchors(neo4j_client, args.tenant, args.doc_id, args.dry_run)

        # Phase 2: Créer par recherche textuelle
        logger.info("\n" + "=" * 40)
        create_textual_anchors(neo4j_client, args.tenant, args.doc_id, args.dry_run)

        # Vérification
        if not args.dry_run:
            logger.info("\n" + "=" * 40)
            verify_anchors(neo4j_client, args.tenant, args.doc_id)

        # Stats finales
        if not args.dry_run:
            logger.info("\n" + "=" * 40)
            logger.info("📊 Statistiques finales:")
            stats = get_stats(neo4j_client, args.tenant, args.doc_id)
            for key, cnt in stats["by_target"].items():
                logger.info(f"  - {key}: {cnt}")

            kpis = compute_kpis(neo4j_client, args.tenant, args.doc_id)
            logger.info("\n📈 KPIs:")
            logger.info(f"  - Total ProtoConcepts: {kpis.get('total', 0)}")
            logger.info(f"  - Ancrés vers DocItem: {kpis.get('anchored_to_docitem', 0)} ({kpis.get('anchor_rate', 0):.1f}%)")
            logger.info(f"  - Via textual_fix: {kpis.get('textual_anchored', 0)} ({kpis.get('textual_rate', 0):.1f}%)")

        logger.info("\n✅ Correction terminée")

    except Exception as e:
        logger.error(f"❌ Erreur: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
