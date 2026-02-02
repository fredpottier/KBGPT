"""
OSMOSE Layer R Bridge — Pont bidirectionnel Neo4j ↔ Qdrant.

Après Pass 1 (persist Neo4j) et Layer R upsert (Qdrant), ce module
crée le lien entre les deux:
- Direction 1 (Neo4j → Qdrant): Information.layer_r_point_ids
- Direction 2 (Qdrant ← Neo4j): payload.anchored_informations

Clé de jointure: item_id extrait du format composé tenant:doc_id:item_id
(Information.anchor.docitem_id) vs SubChunk.item_ids (format brut).

Ref: ADR Bridge Bidirectionnel Neo4j ↔ Qdrant Layer R
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from knowbase.stratified.models import Pass1Result

logger = logging.getLogger(__name__)


# ============================================================================
# DATACLASSES
# ============================================================================

@dataclass
class InfoSummary:
    """Résumé minimal d'une Information pour le payload Qdrant."""
    info_id: str
    concept_id: str
    concept_name: str
    info_type: str
    confidence: float


@dataclass
class BridgeStats:
    """Statistiques du cross-référencement Layer R."""
    informations_processed: int = 0
    qdrant_points_enriched: int = 0
    neo4j_nodes_updated: int = 0
    orphan_informations: int = 0


# ============================================================================
# FONCTION PRINCIPALE
# ============================================================================

def cross_reference_layer_r(
    pass1_result: Pass1Result,
    concepts_by_id: Dict[str, str],
    doc_id: str,
    tenant_id: str,
    neo4j_driver=None,
) -> BridgeStats:
    """
    Crée le pont bidirectionnel entre Neo4j Information et Qdrant SubChunks.

    Args:
        pass1_result: Résultat Pass 1 avec informations et concepts
        concepts_by_id: Mapping concept_id → concept_name
        doc_id: ID du document
        tenant_id: ID du tenant
        neo4j_driver: Driver Neo4j (optionnel, pour Direction 1)

    Returns:
        BridgeStats avec compteurs
    """
    from knowbase.retrieval.qdrant_layer_r import COLLECTION_NAME

    stats = BridgeStats()

    if not pass1_result.informations:
        logger.info("[OSMOSE:LayerR:Bridge] Aucune information à cross-référencer")
        return stats

    # A. Construire mapping item_id → [InfoSummary]
    item_id_to_infos: Dict[str, List[InfoSummary]] = {}
    info_id_to_item_ids: Dict[str, str] = {}  # info_id → item_id (pour lookup inverse)

    for info in pass1_result.informations:
        docitem_id = info.anchor.docitem_id
        # Extraire item_id du format composé tenant:doc_id:item_id
        parts = docitem_id.split(":", 2)
        item_id = parts[2] if len(parts) >= 3 else docitem_id

        summary = InfoSummary(
            info_id=info.info_id,
            concept_id=info.concept_id,
            concept_name=concepts_by_id.get(info.concept_id, ""),
            info_type=info.type.value,
            confidence=info.confidence,
        )

        item_id_to_infos.setdefault(item_id, []).append(summary)
        info_id_to_item_ids[info.info_id] = item_id
        stats.informations_processed += 1

    logger.info(
        f"[OSMOSE:LayerR:Bridge] {stats.informations_processed} informations → "
        f"{len(item_id_to_infos)} item_ids distincts"
    )

    # B. Scroll tous les points Qdrant du document
    try:
        point_data = _scroll_all_points_for_doc(doc_id, tenant_id)
    except Exception as e:
        logger.warning(f"[OSMOSE:LayerR:Bridge] Scroll Qdrant échoué: {e}")
        return stats

    if not point_data:
        logger.warning(
            f"[OSMOSE:LayerR:Bridge] Aucun point Qdrant pour doc_id={doc_id}"
        )
        stats.orphan_informations = stats.informations_processed
        return stats

    logger.info(
        f"[OSMOSE:LayerR:Bridge] {len(point_data)} points Qdrant pour doc_id={doc_id}"
    )

    # C. Joindre: pour chaque point, trouver les informations via item_ids
    point_id_to_infos: Dict[str, List[InfoSummary]] = {}
    info_id_to_point_ids: Dict[str, List[str]] = {}
    matched_item_ids: set = set()

    for point_id, payload in point_data.items():
        point_item_ids = payload.get("item_ids", [])
        if not point_item_ids:
            continue

        matched_infos = []
        for pid in point_item_ids:
            if pid in item_id_to_infos:
                matched_infos.extend(item_id_to_infos[pid])
                matched_item_ids.add(pid)

        if matched_infos:
            point_id_to_infos[point_id] = matched_infos
            for info_summary in matched_infos:
                info_id_to_point_ids.setdefault(info_summary.info_id, []).append(
                    point_id
                )

    # Compter les orphans (informations sans sub-chunk correspondant)
    all_info_item_ids = set(info_id_to_item_ids.values())
    orphan_item_ids = all_info_item_ids - matched_item_ids
    stats.orphan_informations = sum(
        len(infos)
        for iid, infos in item_id_to_infos.items()
        if iid in orphan_item_ids
    )

    if stats.orphan_informations > 0:
        logger.warning(
            f"[OSMOSE:LayerR:Bridge] {stats.orphan_informations} informations orphelines "
            f"(item_ids non trouvés dans Qdrant)"
        )

    # D. Direction 2 (Qdrant ← Neo4j): set_payload avec anchored_informations
    if point_id_to_infos:
        try:
            stats.qdrant_points_enriched = _batch_update_qdrant_payloads(
                point_id_to_infos
            )
        except Exception as e:
            logger.warning(f"[OSMOSE:LayerR:Bridge] Update Qdrant échoué: {e}")

    # E. Direction 1 (Neo4j → Qdrant): SET Information.layer_r_point_ids
    if neo4j_driver and info_id_to_point_ids:
        try:
            stats.neo4j_nodes_updated = _batch_update_neo4j_info_nodes(
                neo4j_driver, info_id_to_point_ids, tenant_id
            )
        except Exception as e:
            logger.warning(f"[OSMOSE:LayerR:Bridge] Update Neo4j échoué: {e}")

    return stats


# ============================================================================
# FONCTIONS INTERNES
# ============================================================================

def _scroll_all_points_for_doc(
    doc_id: str,
    tenant_id: str,
) -> Dict[str, dict]:
    """
    Scroll tous les points Qdrant d'un document.

    Returns:
        Dict point_id (str) → payload (dict)
    """
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    from knowbase.common.clients.qdrant_client import get_qdrant_client
    from knowbase.retrieval.qdrant_layer_r import COLLECTION_NAME

    client = get_qdrant_client()
    if not client.collection_exists(COLLECTION_NAME):
        logger.warning(
            f"[OSMOSE:LayerR:Bridge] Collection {COLLECTION_NAME} inexistante"
        )
        return {}

    scroll_filter = Filter(
        must=[
            FieldCondition(key="doc_id", match=MatchValue(value=doc_id)),
            FieldCondition(key="tenant_id", match=MatchValue(value=tenant_id)),
        ]
    )

    result = {}
    offset = None
    batch_size = 100

    while True:
        points, next_offset = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=scroll_filter,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )

        for point in points:
            # point.id peut être un UUID — le convertir en string
            result[str(point.id)] = point.payload or {}

        if next_offset is None:
            break
        offset = next_offset

    return result


def _batch_update_qdrant_payloads(
    point_id_to_infos: Dict[str, List[InfoSummary]],
) -> int:
    """
    Met à jour le payload Qdrant avec anchored_informations.

    set_payload est idempotent: relance = même résultat.

    Returns:
        Nombre de points enrichis
    """
    from knowbase.common.clients.qdrant_client import get_qdrant_client
    from knowbase.retrieval.qdrant_layer_r import COLLECTION_NAME

    client = get_qdrant_client()
    count = 0

    for point_id, infos in point_id_to_infos.items():
        anchored_informations = [
            {
                "info_id": info.info_id,
                "concept_id": info.concept_id,
                "concept_name": info.concept_name,
                "type": info.info_type,
                "confidence": info.confidence,
            }
            for info in infos
        ]

        client.set_payload(
            collection_name=COLLECTION_NAME,
            payload={"anchored_informations": anchored_informations},
            points=[point_id],
        )
        count += 1

    return count


def _batch_update_neo4j_info_nodes(
    driver,
    info_id_to_point_ids: Dict[str, List[str]],
    tenant_id: str,
) -> int:
    """
    Met à jour les nœuds Information Neo4j avec layer_r_point_ids.

    Utilise UNWIND pour le batch. SET est idempotent.

    Returns:
        Nombre de nœuds mis à jour
    """
    data = [
        {"info_id": info_id, "point_ids": point_ids}
        for info_id, point_ids in info_id_to_point_ids.items()
    ]

    query = """
    UNWIND $data AS row
    MATCH (i:Information {info_id: row.info_id, tenant_id: $tenant_id})
    SET i.layer_r_point_ids = row.point_ids
    RETURN count(i) AS updated
    """

    with driver.session() as session:
        result = session.run(query, {"data": data, "tenant_id": tenant_id})
        record = result.single()
        return record["updated"] if record else 0
