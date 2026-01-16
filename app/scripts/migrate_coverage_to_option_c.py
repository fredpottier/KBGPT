#!/usr/bin/env python3
"""
Migration Script: CoverageChunk → Option C (DocItem)

ADR: ADR_COVERAGE_PROPERTY_NOT_NODE

Ce script migre les données existantes:
0. Phase 0: Recalcule le charspan document-wide (cumulative) pour les DocItems
1. Phase 1: Résout les section_id textuels vers UUID (ProtoConcepts → SectionContext)
2. Phase 2: Crée les relations ANCHORED_IN vers DocItem (remplace DocumentChunk)
4. Phase 4: Met à jour MENTIONED_IN pour utiliser section_id UUID

Usage:
    docker-compose exec app python scripts/migrate_coverage_to_option_c.py
    docker-compose exec app python scripts/migrate_coverage_to_option_c.py --dry-run
    docker-compose exec app python scripts/migrate_coverage_to_option_c.py --phase 0
"""

import argparse
import logging
import sys
from typing import Dict, Any, Optional

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


def get_stats(neo4j_client, tenant_id: str = "default") -> Dict[str, Any]:
    """Récupère les statistiques actuelles."""
    stats = {
        "text_section_ids": 0,
        "uuid_section_ids": 0,
        "anchored_to_chunk": 0,
        "anchored_to_docitem": 0,
        "docitems_with_charspan": 0,
    }

    queries = [
        # ProtoConcepts avec section_id texte (cluster_*)
        ("text_section_ids", """
            MATCH (p:ProtoConcept {tenant_id: $tenant_id})
            WHERE p.section_id IS NOT NULL AND p.section_id STARTS WITH 'cluster'
            RETURN count(p) as count
        """),
        # ProtoConcepts avec section_id UUID (sec_*)
        ("uuid_section_ids", """
            MATCH (p:ProtoConcept {tenant_id: $tenant_id})
            WHERE p.section_id IS NOT NULL AND p.section_id STARTS WITH 'sec_'
            RETURN count(p) as count
        """),
        # ANCHORED_IN vers DocumentChunk
        ("anchored_to_chunk", """
            MATCH ()-[r:ANCHORED_IN]->(dc:DocumentChunk {tenant_id: $tenant_id})
            RETURN count(r) as count
        """),
        # ANCHORED_IN vers DocItem
        ("anchored_to_docitem", """
            MATCH ()-[r:ANCHORED_IN]->(di:DocItem {tenant_id: $tenant_id})
            RETURN count(r) as count
        """),
        # DocItems avec charspan
        ("docitems_with_charspan", """
            MATCH (d:DocItem {tenant_id: $tenant_id})
            WHERE d.charspan_start IS NOT NULL
            RETURN count(d) as count
        """),
    ]

    with neo4j_client.driver.session(database="neo4j") as session:
        for key, query in queries:
            result = session.run(query, tenant_id=tenant_id)
            record = result.single()
            if record:
                stats[key] = record["count"]

    return stats


def migrate_phase0_recalculate_charspan(
    neo4j_client,
    tenant_id: str = "default",
    dry_run: bool = False
) -> Dict[str, int]:
    """
    Phase 0: Recalcule le charspan document-wide (cumulative par page).

    Le charspan Docling est per-page (chaque page commence à 0). Cette phase:
    1. Calcule max(charspan_end) par page pour chaque document
    2. Calcule l'offset cumulatif par page
    3. Met à jour DocItems: charspan_docwide = charspan + page_offset
    """
    logger.info("[Phase 0] Recalcul du charspan document-wide...")

    # Trouver tous les documents avec DocItems ayant des charspan
    find_docs_query = """
    MATCH (di:DocItem {tenant_id: $tenant_id})
    WHERE di.charspan_start IS NOT NULL
    RETURN DISTINCT di.doc_id as doc_id
    """

    with neo4j_client.driver.session(database="neo4j") as session:
        result = session.run(find_docs_query, tenant_id=tenant_id)
        doc_ids = [record["doc_id"] for record in result]

        if not doc_ids:
            logger.info("[Phase 0] Aucun document avec DocItems ayant charspan")
            return {"processed": 0}

        logger.info(f"[Phase 0] {len(doc_ids)} documents à traiter...")

        if dry_run:
            return {"to_process": len(doc_ids), "processed": 0}

        total_updated = 0

        for idx, doc_id in enumerate(doc_ids):
            # 1. Calculer max(charspan_end) par page + un padding de 1
            get_page_offsets_query = """
            MATCH (di:DocItem {tenant_id: $tenant_id, doc_id: $doc_id})
            WHERE di.charspan_end IS NOT NULL AND di.page_no IS NOT NULL
            WITH di.page_no as page, max(di.charspan_end) + 1 as page_size
            ORDER BY page
            WITH collect({page: page, size: page_size}) as pages
            // Calculer offset cumulatif
            WITH reduce(
                acc = {offsets: [], cumul: 0},
                p IN pages |
                {
                    offsets: acc.offsets + [{page: p.page, offset: acc.cumul}],
                    cumul: acc.cumul + p.size
                }
            ).offsets as offsets
            UNWIND offsets as o
            RETURN o.page as page, o.offset as offset
            """

            result = session.run(get_page_offsets_query, tenant_id=tenant_id, doc_id=doc_id)
            page_offsets = {record["page"]: record["offset"] for record in result}

            if not page_offsets:
                continue

            # 2. Mettre à jour tous les DocItems de ce document avec l'offset de leur page
            # Utiliser UNWIND pour batch processing
            offset_list = [{"page": p, "offset": o} for p, o in page_offsets.items()]

            update_query = """
            UNWIND $offsets as po
            MATCH (di:DocItem {tenant_id: $tenant_id, doc_id: $doc_id})
            WHERE di.page_no = po.page AND di.charspan_start IS NOT NULL
            SET di.charspan_start_docwide = di.charspan_start + po.offset,
                di.charspan_end_docwide = di.charspan_end + po.offset
            RETURN count(di) as updated
            """

            result = session.run(
                update_query,
                tenant_id=tenant_id,
                doc_id=doc_id,
                offsets=offset_list
            )
            record = result.single()
            if record:
                total_updated += record["updated"]

            if (idx + 1) % 5 == 0:
                logger.info(f"[Phase 0] Progression: {idx + 1}/{len(doc_ids)} documents...")

        logger.info(f"[Phase 0] ✅ Mis à jour charspan_docwide pour {total_updated} DocItems")
        return {"updated": total_updated}


def migrate_phase1_section_ids(
    neo4j_client,
    tenant_id: str = "default",
    dry_run: bool = False
) -> Dict[str, int]:
    """
    Phase 1: Migre les section_id textuels vers UUID.

    Pour chaque ProtoConcept avec un anchor SPAN, trouve le DocItem correspondant
    et copie son section_id UUID.
    """
    logger.info("[Phase 1] Migration des section_id vers UUID...")

    if dry_run:
        # Count only - utilise charspan_docwide avec fallback sur charspan original
        count_query = """
        MATCH (p:ProtoConcept {tenant_id: $tenant_id})-[r:ANCHORED_IN]->(dc:DocumentChunk)
        WHERE r.span_start IS NOT NULL
        MATCH (di:DocItem {tenant_id: $tenant_id, doc_id: p.document_id})
        WHERE di.section_id IS NOT NULL
          AND di.section_id STARTS WITH 'sec_'
          AND (
              // Priorité: charspan_docwide (calculé en Phase 0)
              (di.charspan_start_docwide IS NOT NULL
               AND di.charspan_start_docwide <= r.span_start
               AND di.charspan_end_docwide >= r.span_start)
              OR
              // Fallback: charspan original
              (di.charspan_start_docwide IS NULL
               AND di.charspan_start IS NOT NULL
               AND di.charspan_start <= r.span_start
               AND di.charspan_end >= r.span_start)
          )
        WITH p, di
        WHERE p.section_id IS NULL OR NOT p.section_id STARTS WITH 'sec_'
        RETURN count(DISTINCT p) as to_migrate
        """
        with neo4j_client.driver.session(database="neo4j") as session:
            result = session.run(count_query, tenant_id=tenant_id)
            record = result.single()
            to_migrate = record["to_migrate"] if record else 0
            logger.info(f"[Phase 1] DRY-RUN: {to_migrate} ProtoConcepts à migrer")
            return {"to_migrate": to_migrate, "migrated": 0}

    # Migration réelle - utilise charspan_docwide avec fallback
    migrate_query = """
    MATCH (p:ProtoConcept {tenant_id: $tenant_id})-[r:ANCHORED_IN]->(dc:DocumentChunk)
    WHERE r.span_start IS NOT NULL
    MATCH (di:DocItem {tenant_id: $tenant_id, doc_id: p.document_id})
    WHERE di.section_id IS NOT NULL
      AND di.section_id STARTS WITH 'sec_'
      AND (
          // Priorité: charspan_docwide (calculé en Phase 0)
          (di.charspan_start_docwide IS NOT NULL
           AND di.charspan_start_docwide <= r.span_start
           AND di.charspan_end_docwide >= r.span_start)
          OR
          // Fallback: charspan original
          (di.charspan_start_docwide IS NULL
           AND di.charspan_start IS NOT NULL
           AND di.charspan_start <= r.span_start
           AND di.charspan_end >= r.span_start)
      )
    WITH p, di, r
    WHERE p.section_id IS NULL OR NOT p.section_id STARTS WITH 'sec_'
    SET p.section_id = di.section_id,
        p.section_id_migrated_at = datetime(),
        p.section_id_source = 'migration_phase1'
    RETURN count(DISTINCT p) as migrated
    """

    with neo4j_client.driver.session(database="neo4j") as session:
        result = session.run(migrate_query, tenant_id=tenant_id)
        record = result.single()
        migrated = record["migrated"] if record else 0
        logger.info(f"[Phase 1] ✅ Migré {migrated} section_ids vers UUID")
        return {"migrated": migrated}


def migrate_phase2_anchored_in(
    neo4j_client,
    tenant_id: str = "default",
    dry_run: bool = False
) -> Dict[str, int]:
    """
    Phase 2: Crée les relations ANCHORED_IN vers DocItem.

    Pour chaque ProtoConcept avec un anchor vers DocumentChunk, crée une
    relation équivalente vers le DocItem correspondant (le plus spécifique).
    """
    logger.info("[Phase 2] Création des ANCHORED_IN → DocItem...")

    if dry_run:
        # Count ProtoConcepts qui ont besoin de migration
        count_query = """
        MATCH (p:ProtoConcept {tenant_id: $tenant_id})-[r:ANCHORED_IN]->(dc:DocumentChunk)
        WHERE r.span_start IS NOT NULL
          AND NOT EXISTS {
              MATCH (p)-[:ANCHORED_IN]->(di:DocItem)
          }
        RETURN count(DISTINCT p) as to_create
        """
        with neo4j_client.driver.session(database="neo4j") as session:
            result = session.run(count_query, tenant_id=tenant_id)
            record = result.single()
            to_create = record["to_create"] if record else 0
            logger.info(f"[Phase 2] DRY-RUN: {to_create} ProtoConcepts à migrer vers DocItem")
            return {"to_create": to_create, "created": 0}

    # Migration réelle - Approche bulk
    # Utilise charspan_docwide (calculé en Phase 0) avec fallback sur charspan original
    migrate_bulk_query = """
    CALL {
        // Trouver les ProtoConcepts à migrer (sans ANCHORED_IN → DocItem)
        MATCH (p:ProtoConcept {tenant_id: $tenant_id})-[r:ANCHORED_IN]->(dc:DocumentChunk)
        WHERE r.span_start IS NOT NULL
          AND NOT EXISTS {
              MATCH (p)-[:ANCHORED_IN]->(:DocItem)
          }
        RETURN p, r
    }
    // Trouver le DocItem correspondant via charspan_docwide ou charspan original
    MATCH (di:DocItem {tenant_id: $tenant_id, doc_id: p.document_id})
    WHERE (
        // Priorité: charspan_docwide (calculé en Phase 0)
        (di.charspan_start_docwide IS NOT NULL
         AND di.charspan_start_docwide <= r.span_start
         AND di.charspan_end_docwide >= r.span_start)
        OR
        // Fallback: charspan original
        (di.charspan_start_docwide IS NULL
         AND di.charspan_start IS NOT NULL
         AND di.charspan_start <= r.span_start
         AND di.charspan_end >= r.span_start)
    )
    WITH p, r, di,
         // Calculer la taille du range pour trier par spécificité
         CASE
             WHEN di.charspan_start_docwide IS NOT NULL
             THEN di.charspan_end_docwide - di.charspan_start_docwide
             ELSE di.charspan_end - di.charspan_start
         END AS range_size
    ORDER BY range_size ASC
    WITH p, r, collect(di)[0] AS best_di
    WHERE best_di IS NOT NULL
    MERGE (p)-[new_r:ANCHORED_IN]->(best_di)
    ON CREATE SET
        new_r.char_start = r.span_start,
        new_r.char_end = r.span_end,
        new_r.role = coalesce(r.role, 'mention'),
        new_r.created_at = datetime(),
        new_r.source = 'migration_phase2'
    RETURN count(new_r) as created
    """

    with neo4j_client.driver.session(database="neo4j") as session:
        result = session.run(migrate_bulk_query, tenant_id=tenant_id)
        record = result.single()
        created = record["created"] if record else 0
        logger.info(f"[Phase 2] ✅ Créé {created} relations ANCHORED_IN → DocItem")
        return {"created": created}


def migrate_phase4_mentioned_in(
    neo4j_client,
    tenant_id: str = "default",
    dry_run: bool = False
) -> Dict[str, int]:
    """
    Phase 4: Crée/répare les relations MENTIONED_IN vers SectionContext.

    Pour chaque CanonicalConcept, trouve les SectionContext correspondants
    via les ProtoConcepts liés et crée les relations MENTIONED_IN.
    """
    logger.info("[Phase 4] Création des MENTIONED_IN → SectionContext...")

    if dry_run:
        # Count only
        count_query = """
        MATCH (cc:CanonicalConcept {tenant_id: $tenant_id})<-[:INSTANCE_OF]-(p:ProtoConcept)
        WHERE p.section_id IS NOT NULL AND p.section_id STARTS WITH 'sec_'
        MATCH (s:SectionContext {section_id: p.section_id, tenant_id: $tenant_id})
        WHERE NOT (cc)-[:MENTIONED_IN]->(s)
        RETURN count(DISTINCT cc) as concepts_to_link,
               count(DISTINCT s) as sections_to_link
        """
        with neo4j_client.driver.session(database="neo4j") as session:
            result = session.run(count_query, tenant_id=tenant_id)
            record = result.single()
            if record:
                logger.info(
                    f"[Phase 4] DRY-RUN: {record['concepts_to_link']} CanonicalConcepts "
                    f"à lier vers {record['sections_to_link']} SectionContexts"
                )
                return {"to_link": record['concepts_to_link'], "created": 0}
            return {"to_link": 0, "created": 0}

    # Migration réelle
    migrate_query = """
    MATCH (cc:CanonicalConcept {tenant_id: $tenant_id})<-[:INSTANCE_OF]-(p:ProtoConcept)
    WHERE p.section_id IS NOT NULL AND p.section_id STARTS WITH 'sec_'
    MATCH (s:SectionContext {section_id: p.section_id, tenant_id: $tenant_id})
    WHERE NOT (cc)-[:MENTIONED_IN]->(s)
    WITH cc, s, count(p) as mention_count
    MERGE (cc)-[r:MENTIONED_IN]->(s)
    ON CREATE SET
        r.mention_count = mention_count,
        r.created_at = datetime(),
        r.source = 'migration_phase4'
    RETURN count(r) as created
    """

    with neo4j_client.driver.session(database="neo4j") as session:
        result = session.run(migrate_query, tenant_id=tenant_id)
        record = result.single()
        created = record["created"] if record else 0
        logger.info(f"[Phase 4] ✅ Créé {created} relations MENTIONED_IN → SectionContext")
        return {"created": created}


def compute_kpis(neo4j_client, tenant_id: str = "default") -> Dict[str, float]:
    """
    Calcule les KPIs définis dans l'ADR.

    - ABR (Anchor Bind Rate): % ProtoConcepts SPAN avec ANCHORED_IN valide
    - OR (Orphan Ratio): % ProtoConcepts sans ANCHORED_IN
    - SAR (Section Alignment Rate): % ProtoConcepts dont section_id matche SectionContext
    """
    logger.info("[KPIs] Calcul des métriques...")

    kpi_query = """
    // ABR: Anchor Bind Rate
    MATCH (p:ProtoConcept {tenant_id: $tenant_id})
    WHERE p.anchor_status = 'SPAN'
    WITH collect(DISTINCT p) as span_protos
    UNWIND span_protos as p
    OPTIONAL MATCH (p)-[:ANCHORED_IN]->(di:DocItem)
    WITH count(DISTINCT p) as total_span,
         count(DISTINCT CASE WHEN di IS NOT NULL THEN p END) as bound_span

    // OR: Orphan Ratio (tous les ProtoConcepts)
    MATCH (p2:ProtoConcept {tenant_id: $tenant_id})
    WITH total_span, bound_span, count(p2) as total_protos
    MATCH (orphan:ProtoConcept {tenant_id: $tenant_id})
    WHERE NOT (orphan)-[:ANCHORED_IN]->()
    WITH total_span, bound_span, total_protos, count(orphan) as orphans

    // SAR: Section Alignment Rate
    MATCH (p3:ProtoConcept {tenant_id: $tenant_id})
    WHERE p3.section_id IS NOT NULL AND p3.section_id STARTS WITH 'sec_'
    WITH total_span, bound_span, total_protos, orphans, count(p3) as with_uuid_section
    MATCH (p4:ProtoConcept {tenant_id: $tenant_id})
    WHERE p4.section_id IS NOT NULL AND p4.section_id STARTS WITH 'sec_'
    MATCH (s:SectionContext {section_id: p4.section_id, tenant_id: $tenant_id})
    WITH total_span, bound_span, total_protos, orphans, with_uuid_section,
         count(DISTINCT p4) as aligned

    RETURN
        total_span, bound_span,
        CASE WHEN total_span > 0 THEN toFloat(bound_span) / total_span * 100 ELSE 0 END as abr,
        total_protos, orphans,
        CASE WHEN total_protos > 0 THEN toFloat(orphans) / total_protos * 100 ELSE 0 END as orphan_ratio,
        with_uuid_section, aligned,
        CASE WHEN with_uuid_section > 0 THEN toFloat(aligned) / with_uuid_section * 100 ELSE 0 END as sar
    """

    with neo4j_client.driver.session(database="neo4j") as session:
        result = session.run(kpi_query, tenant_id=tenant_id)
        record = result.single()
        if record:
            return {
                "abr": record["abr"],
                "abr_detail": f"{record['bound_span']}/{record['total_span']}",
                "orphan_ratio": record["orphan_ratio"],
                "orphan_detail": f"{record['orphans']}/{record['total_protos']}",
                "sar": record["sar"],
                "sar_detail": f"{record['aligned']}/{record['with_uuid_section']}",
            }
        return {"abr": 0, "orphan_ratio": 100, "sar": 0}


def main():
    parser = argparse.ArgumentParser(
        description="Migration CoverageChunk → Option C (DocItem)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Affiche les opérations sans les exécuter"
    )
    parser.add_argument(
        "--phase",
        type=int,
        choices=[0, 1, 2, 4],
        help="Exécute uniquement la phase spécifiée (0=charspan, 1=section_id, 2=ANCHORED_IN, 4=MENTIONED_IN)"
    )
    parser.add_argument(
        "--tenant",
        type=str,
        default="default",
        help="Tenant ID (défaut: default)"
    )
    parser.add_argument(
        "--kpis-only",
        action="store_true",
        help="Affiche uniquement les KPIs sans migration"
    )

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Migration CoverageChunk → Option C (DocItem)")
    logger.info("ADR: ADR_COVERAGE_PROPERTY_NOT_NODE")
    logger.info("=" * 60)

    try:
        neo4j_client = get_neo4j_client()
        if not neo4j_client.is_connected():
            logger.error("❌ Neo4j non connecté")
            sys.exit(1)

        # Stats initiales
        logger.info("\n📊 Statistiques initiales:")
        stats = get_stats(neo4j_client, args.tenant)
        logger.info(f"  - ProtoConcepts avec section_id texte: {stats['text_section_ids']}")
        logger.info(f"  - ProtoConcepts avec section_id UUID: {stats['uuid_section_ids']}")
        logger.info(f"  - ANCHORED_IN → DocumentChunk: {stats['anchored_to_chunk']}")
        logger.info(f"  - ANCHORED_IN → DocItem: {stats['anchored_to_docitem']}")
        logger.info(f"  - DocItems avec charspan: {stats['docitems_with_charspan']}")

        if args.kpis_only:
            kpis = compute_kpis(neo4j_client, args.tenant)
            logger.info("\n📈 KPIs actuels:")
            logger.info(f"  - ABR (Anchor Bind Rate): {kpis['abr']:.1f}% ({kpis['abr_detail']})")
            logger.info(f"  - OR (Orphan Ratio): {kpis['orphan_ratio']:.1f}% ({kpis['orphan_detail']})")
            logger.info(f"  - SAR (Section Alignment): {kpis['sar']:.1f}% ({kpis['sar_detail']})")
            sys.exit(0)

        # Exécution des phases
        if args.phase is None or args.phase == 0:
            logger.info("\n" + "=" * 40)
            migrate_phase0_recalculate_charspan(neo4j_client, args.tenant, args.dry_run)

        if args.phase is None or args.phase == 1:
            logger.info("\n" + "=" * 40)
            migrate_phase1_section_ids(neo4j_client, args.tenant, args.dry_run)

        if args.phase is None or args.phase == 2:
            logger.info("\n" + "=" * 40)
            migrate_phase2_anchored_in(neo4j_client, args.tenant, args.dry_run)

        if args.phase is None or args.phase == 4:
            logger.info("\n" + "=" * 40)
            migrate_phase4_mentioned_in(neo4j_client, args.tenant, args.dry_run)

        # KPIs finaux
        if not args.dry_run:
            logger.info("\n" + "=" * 40)
            kpis = compute_kpis(neo4j_client, args.tenant)
            logger.info("📈 KPIs après migration:")
            logger.info(f"  - ABR (Anchor Bind Rate): {kpis['abr']:.1f}% ({kpis['abr_detail']})")
            logger.info(f"  - OR (Orphan Ratio): {kpis['orphan_ratio']:.1f}% ({kpis['orphan_detail']})")
            logger.info(f"  - SAR (Section Alignment): {kpis['sar']:.1f}% ({kpis['sar_detail']})")

            # Alertes si KPIs sous les seuils
            if kpis['abr'] < 95:
                logger.warning(f"⚠️ ABR < 95% - Invariant coverage potentiellement violé")
            if kpis['orphan_ratio'] > 5:
                logger.warning(f"⚠️ Orphan Ratio > 5% - Trop de ProtoConcepts sans ancrage")
            if kpis['sar'] < 95:
                logger.warning(f"⚠️ SAR < 95% - section_id non alignés avec SectionContext")

        logger.info("\n✅ Migration terminée")

    except Exception as e:
        logger.error(f"❌ Erreur: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
