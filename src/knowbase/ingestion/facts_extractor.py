"""
Module insertion et gestion facts structurés Neo4j.

IMPORTANT: L'extraction de facts est maintenant intégrée dans le prompt unifié
slide (slide_default_v3_unified_facts) pour éviter un appel LLM séparé.
Ce module ne contient que l'insertion Neo4j et la détection de conflits.
"""

from __future__ import annotations

from typing import List, Dict, Any

from knowbase.api.schemas.facts import FactCreate
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "facts_extractor.log")


async def insert_facts_to_neo4j(
    facts: List[FactCreate],
    tenant_id: str = "default",
) -> List[str]:
    """
    Insère facts dans Neo4j avec status='proposed'.

    Args:
        facts: Liste facts à insérer
        tenant_id: ID tenant pour multi-tenancy

    Returns:
        List[str]: UUIDs facts insérés avec succès
    """
    from knowbase.api.services.facts_service import FactsService

    if not facts:
        logger.debug("✅ Aucun fact à insérer")
        return []

    facts_service = FactsService(tenant_id=tenant_id)
    inserted_uuids = []

    for fact in facts:
        try:
            fact_response = facts_service.create_fact(fact)
            inserted_uuids.append(fact_response.uuid)

            logger.info(
                f"  ✅ Fact inserted: {fact_response.uuid[:8]}... | "
                f"{fact.subject} → {fact.predicate} = {fact.value}{fact.unit}"
            )

        except Exception as e:
            logger.error(
                f"  ❌ Insertion échouée: {e.__class__.__name__} | "
                f"{fact.subject} → {fact.predicate}"
            )
            continue

    success_rate = len(inserted_uuids) / len(facts) * 100 if facts else 0
    logger.info(
        f"📊 Facts insérés: {len(inserted_uuids)}/{len(facts)} "
        f"({success_rate:.1f}% success)"
    )

    return inserted_uuids


async def detect_and_log_conflicts(
    inserted_fact_uuids: List[str],
    tenant_id: str = "default",
    threshold_pct: float = 0.05,
) -> List[Dict[str, Any]]:
    """
    Détecte conflits pour facts nouvellement insérés.

    Args:
        inserted_fact_uuids: UUIDs facts à vérifier
        tenant_id: ID tenant
        threshold_pct: Seuil différence critique (default 5%)

    Returns:
        List[Dict]: Conflits critiques détectés
    """
    from knowbase.api.services.facts_service import FactsService

    if not inserted_fact_uuids:
        logger.debug("✅ Aucun fact à vérifier pour conflits")
        return []

    facts_service = FactsService(tenant_id=tenant_id)

    try:
        # Détection globale conflits
        all_conflicts = facts_service.detect_conflicts()

        # Filtrer conflits impliquant facts nouvellement insérés
        relevant_conflicts = [
            c for c in all_conflicts
            if c.fact_proposed.uuid in inserted_fact_uuids
        ]

        if not relevant_conflicts:
            logger.info("✅ Aucun conflit détecté pour nouveaux facts")
            return []

        # Filtrer conflits critiques (> seuil)
        critical_conflicts = [
            c for c in relevant_conflicts
            if c.value_diff_pct > threshold_pct
        ]

        # Logger conflits
        for conflict in relevant_conflicts:
            emoji = "🚨" if conflict.value_diff_pct > threshold_pct else "⚠️"
            logger.warning(
                f"{emoji} CONFLICT {conflict.conflict_type} | "
                f"{conflict.fact_proposed.subject} → {conflict.fact_proposed.predicate} | "
                f"Proposed: {conflict.fact_proposed.value}{conflict.fact_proposed.unit} | "
                f"Approved: {conflict.fact_approved.value}{conflict.fact_approved.unit} | "
                f"Diff: {conflict.value_diff_pct * 100:.1f}%"
            )

        logger.info(
            f"📊 Conflits détectés: {len(relevant_conflicts)} total, "
            f"{len(critical_conflicts)} critiques (>{threshold_pct*100}%)"
        )

        # Convertir en dict pour notification
        return [
            {
                "conflict_type": c.conflict_type,
                "value_diff_pct": c.value_diff_pct,
                "fact_proposed": {
                    "uuid": c.fact_proposed.uuid,
                    "subject": c.fact_proposed.subject,
                    "predicate": c.fact_proposed.predicate,
                    "value": c.fact_proposed.value,
                    "unit": c.fact_proposed.unit,
                },
                "fact_approved": {
                    "uuid": c.fact_approved.uuid,
                    "subject": c.fact_approved.subject,
                    "predicate": c.fact_approved.predicate,
                    "value": c.fact_approved.value,
                    "unit": c.fact_approved.unit,
                },
            }
            for c in critical_conflicts
        ]

    except Exception as e:
        logger.error(f"❌ Détection conflits échouée: {e}")
        return []


__all__ = [
    "insert_facts_to_neo4j",
    "detect_and_log_conflicts",
]
