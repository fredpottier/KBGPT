"""
Phase 2.9 OSMOSE - Catalogue Builder pour extraction segment-level

Construit un catalogue hybride (local + global) pour chaque segment,
optimisant le taux d'utilisation des concepts par le LLM.

Architecture:
- Concepts locaux: Extraits du segment actuel (10-40)
- Top-K globaux: Fréquents cross-documents (10-15)
- Hub concepts: Déjà bien connectés dans le KG (5-10)
- Concepts adjacents: Même topic que segment (5-10)

Total: 40-60 concepts max par segment (vs 400+ document-level)
"""

import json
import logging
from typing import Dict, List, Tuple, Optional, Any, Set
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CatalogueConfig:
    """Configuration pour la construction du catalogue hybride."""
    top_k_global: int = 15  # Nombre de concepts globaux fréquents
    hub_min_degree: int = 3  # Degré minimum pour être un hub
    hub_limit: int = 10  # Nombre max de hubs
    adjacent_limit: int = 10  # Nombre max de concepts du même topic
    max_catalogue_size: int = 60  # Taille max du catalogue final
    # Phase 2.9.2: Filtrage par concept_kind
    filter_non_keepable: bool = True  # Exclure structural/generic/fragment du catalogue factuel
    include_non_keepable_limit: int = 0  # Max non-keepable à inclure (0 = aucun)


@dataclass
class HybridCatalogue:
    """Résultat de la construction du catalogue hybride."""
    catalogue_json: str  # JSON pour le prompt LLM
    index_to_concept: Dict[str, Dict[str, Any]]  # Mapping c1 -> concept data
    stats: Dict[str, int] = field(default_factory=dict)


def build_hybrid_catalogue(
    segment_id: str,
    segment_text: str,
    local_concept_ids: List[str],
    all_promoted: List[Dict[str, Any]],
    neo4j_client: Any,
    tenant_id: str,
    topic_id: Optional[str] = None,
    config: Optional[CatalogueConfig] = None
) -> HybridCatalogue:
    """
    Construit un catalogue hybride pour un segment.

    Stratégie:
    1. Concepts locaux du segment (priorité max)
    2. Top-K globaux (fréquents cross-documents)
    3. Hub concepts (déjà bien connectés)
    4. Concepts adjacents (même topic)

    Args:
        segment_id: ID du segment
        segment_text: Texte du segment
        local_concept_ids: IDs des concepts extraits de ce segment
        all_promoted: Tous les concepts promus du document
        neo4j_client: Client Neo4j pour requêtes
        tenant_id: ID tenant
        topic_id: ID topic du segment (optionnel)
        config: Configuration catalogue

    Returns:
        HybridCatalogue avec JSON et mapping
    """
    config = config or CatalogueConfig()

    logger.info(
        f"[OSMOSE:CatalogueBuilder] Building hybrid catalogue for segment {segment_id}: "
        f"{len(local_concept_ids)} local concepts"
    )

    # Index pour éviter doublons
    used_concept_ids: Set[str] = set()
    catalogue_concepts: List[Dict[str, Any]] = []

    stats = {
        "local": 0,
        "global_top_k": 0,
        "hubs": 0,
        "adjacent": 0,
        "total": 0,
        "filtered_non_keepable": 0  # Phase 2.9.2
    }

    # Phase 2.9.2: Compteur pour non-keepable inclus
    non_keepable_included = 0

    # 1. Concepts locaux (priorité max, mais filtrés par is_keepable)
    local_concepts = _get_concepts_by_ids(local_concept_ids, all_promoted)
    for concept in local_concepts:
        concept_id = _get_concept_id(concept)
        if not concept_id or concept_id in used_concept_ids:
            continue

        # Phase 2.9.2: Vérifier is_keepable
        is_keepable = concept.get("is_keepable", True)  # Default True pour rétrocompatibilité

        if not is_keepable and config.filter_non_keepable:
            # Concept non-keepable (structural/generic/fragment)
            if non_keepable_included < config.include_non_keepable_limit:
                # Inclure quand même si sous la limite
                catalogue_concepts.append(concept)
                used_concept_ids.add(concept_id)
                stats["local"] += 1
                non_keepable_included += 1
            else:
                stats["filtered_non_keepable"] += 1
                logger.debug(
                    f"[OSMOSE:CatalogueBuilder] Filtered non-keepable: {concept.get('name', concept_id)[:30]} "
                    f"(kind={concept.get('concept_kind', 'unknown')})"
                )
        else:
            # Concept keepable ou filtrage désactivé
            catalogue_concepts.append(concept)
            used_concept_ids.add(concept_id)
            stats["local"] += 1

    logger.debug(f"[OSMOSE:CatalogueBuilder] Added {stats['local']} local concepts")

    # 2. Top-K globaux (fréquents cross-documents)
    if len(catalogue_concepts) < config.max_catalogue_size:
        try:
            global_top_k = neo4j_client.get_top_concepts_by_occurrence(
                tenant_id=tenant_id,
                limit=config.top_k_global,
                exclude_ids=list(used_concept_ids)
            )

            for concept in global_top_k:
                if len(catalogue_concepts) >= config.max_catalogue_size:
                    break
                concept_id = _get_concept_id(concept)
                if concept_id and concept_id not in used_concept_ids:
                    catalogue_concepts.append(concept)
                    used_concept_ids.add(concept_id)
                    stats["global_top_k"] += 1

            logger.debug(f"[OSMOSE:CatalogueBuilder] Added {stats['global_top_k']} global top-k concepts")
        except Exception as e:
            logger.warning(f"[OSMOSE:CatalogueBuilder] Failed to get global top-k: {e}")

    # 3. Hub concepts (bien connectés dans le KG)
    if len(catalogue_concepts) < config.max_catalogue_size:
        try:
            hub_concepts = neo4j_client.get_hub_concepts(
                tenant_id=tenant_id,
                min_degree=config.hub_min_degree,
                limit=config.hub_limit,
                exclude_ids=list(used_concept_ids)
            )

            for concept in hub_concepts:
                if len(catalogue_concepts) >= config.max_catalogue_size:
                    break
                concept_id = _get_concept_id(concept)
                if concept_id and concept_id not in used_concept_ids:
                    catalogue_concepts.append(concept)
                    used_concept_ids.add(concept_id)
                    stats["hubs"] += 1

            logger.debug(f"[OSMOSE:CatalogueBuilder] Added {stats['hubs']} hub concepts")
        except Exception as e:
            logger.warning(f"[OSMOSE:CatalogueBuilder] Failed to get hub concepts: {e}")

    # 4. Concepts adjacents (même topic)
    if topic_id and len(catalogue_concepts) < config.max_catalogue_size:
        adjacent_concepts = [
            c for c in all_promoted
            if c.get("topic_id") == topic_id
            and _get_concept_id(c) not in used_concept_ids
        ][:config.adjacent_limit]

        for concept in adjacent_concepts:
            if len(catalogue_concepts) >= config.max_catalogue_size:
                break
            concept_id = _get_concept_id(concept)
            if concept_id and concept_id not in used_concept_ids:
                catalogue_concepts.append(concept)
                used_concept_ids.add(concept_id)
                stats["adjacent"] += 1

        logger.debug(f"[OSMOSE:CatalogueBuilder] Added {stats['adjacent']} adjacent concepts")

    stats["total"] = len(catalogue_concepts)

    # Construire catalogue indexé pour LLM
    catalogue_json, index_to_concept = _build_indexed_catalogue(catalogue_concepts)

    # Phase 2.9.2: Log avec filtrage non-keepable
    filtered_msg = ""
    if stats.get("filtered_non_keepable", 0) > 0:
        filtered_msg = f", filtered_non_keepable={stats['filtered_non_keepable']}"

    logger.info(
        f"[OSMOSE:CatalogueBuilder] Catalogue built: {stats['total']} concepts "
        f"(local={stats['local']}, global={stats['global_top_k']}, "
        f"hubs={stats['hubs']}, adjacent={stats['adjacent']}{filtered_msg})"
    )

    return HybridCatalogue(
        catalogue_json=catalogue_json,
        index_to_concept=index_to_concept,
        stats=stats
    )


def _get_concepts_by_ids(
    concept_ids: List[str],
    all_concepts: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Récupère les concepts par leurs IDs.

    Fix Phase 2.9.1: Indexe par BOTH concept_id ET canonical_id pour gérer
    le mismatch entre local_concept_ids (pré-canonicalisation) et
    all_promoted (post-canonicalisation Gatekeeper).
    """
    id_to_concept = {}
    for c in all_concepts:
        # Index par canonical_id (post-Gatekeeper)
        canonical_id = c.get("canonical_id")
        if canonical_id:
            id_to_concept[canonical_id] = c

        # Index AUSSI par concept_id (pré-canonicalisation, depuis ExtractorOrchestrator)
        concept_id = c.get("concept_id")
        if concept_id:
            id_to_concept[concept_id] = c

    matched = [id_to_concept[cid] for cid in concept_ids if cid in id_to_concept]

    # Debug log si mismatch important
    if len(matched) < len(concept_ids) * 0.5:
        logger.warning(
            f"[OSMOSE:CatalogueBuilder] ID mismatch: {len(matched)}/{len(concept_ids)} concepts found. "
            f"Sample requested IDs: {concept_ids[:3]}, "
            f"Sample available IDs: {list(id_to_concept.keys())[:5]}"
        )

    return matched


def _get_concept_id(concept: Dict[str, Any]) -> Optional[str]:
    """Extrait l'ID canonique d'un concept."""
    return concept.get("canonical_id") or concept.get("concept_id")


def _build_indexed_catalogue(
    concepts: List[Dict[str, Any]]
) -> Tuple[str, Dict[str, Dict[str, Any]]]:
    """
    Construit le catalogue JSON avec index (c1, c2...) et le mapping.

    Args:
        concepts: Liste des concepts à inclure

    Returns:
        (catalogue_json_str, index_to_concept_map)
    """
    catalogue = []
    index_to_concept = {}

    for i, concept in enumerate(concepts):
        index = f"c{i + 1}"  # c1, c2, c3...

        canonical_id = _get_concept_id(concept)
        canonical_name = concept.get("canonical_name") or concept.get("name", "")
        surface_forms = concept.get("surface_forms", [])
        concept_type = concept.get("concept_type") or concept.get("type", "UNKNOWN")

        if not canonical_id or not canonical_name:
            logger.debug(f"[OSMOSE:CatalogueBuilder] Skipping concept without ID/name: {concept}")
            continue

        # Phase 2.9.2: Récupérer concept_kind si disponible
        concept_kind = concept.get("concept_kind", "abstract")  # Default abstract

        # Entry pour le catalogue LLM
        catalogue_entry = {
            "idx": index,
            "name": canonical_name,
            "aliases": surface_forms[:5] if surface_forms else [],  # Limiter à 5
            "type": str(concept_type).lower(),
            "kind": concept_kind  # Phase 2.9.2: entity/abstract/rule_like
        }
        catalogue.append(catalogue_entry)

        # Mapping pour résolution
        index_to_concept[index] = {
            "canonical_id": canonical_id,
            "canonical_name": canonical_name,
            "concept_type": concept_type,
            "concept_kind": concept_kind  # Phase 2.9.2
        }

    catalogue_json = json.dumps(catalogue, ensure_ascii=False, indent=2)

    return catalogue_json, index_to_concept


def build_catalogue_for_segment_batch(
    segments_with_concepts: Dict[str, Any],
    all_promoted: List[Dict[str, Any]],
    neo4j_client: Any,
    tenant_id: str,
    config: Optional[CatalogueConfig] = None
) -> Dict[str, HybridCatalogue]:
    """
    Construit les catalogues hybrides pour tous les segments d'un document.

    Args:
        segments_with_concepts: Dict segment_id -> SegmentWithConcepts
        all_promoted: Tous les concepts promus
        neo4j_client: Client Neo4j
        tenant_id: ID tenant
        config: Configuration

    Returns:
        Dict segment_id -> HybridCatalogue
    """
    config = config or CatalogueConfig()
    catalogues = {}

    logger.info(
        f"[OSMOSE:CatalogueBuilder] Building catalogues for {len(segments_with_concepts)} segments"
    )

    for segment_id, segment in segments_with_concepts.items():
        # Extraire données du segment
        if hasattr(segment, 'text'):
            # SegmentWithConcepts object
            segment_text = segment.text
            local_ids = segment.local_concept_ids
            topic_id = segment.topic_id
        else:
            # Dict format
            segment_text = segment.get("text", "")
            local_ids = segment.get("local_concept_ids", [])
            topic_id = segment.get("topic_id")

        catalogues[segment_id] = build_hybrid_catalogue(
            segment_id=segment_id,
            segment_text=segment_text,
            local_concept_ids=local_ids,
            all_promoted=all_promoted,
            neo4j_client=neo4j_client,
            tenant_id=tenant_id,
            topic_id=topic_id,
            config=config
        )

    # Log résumé
    total_concepts = sum(cat.stats["total"] for cat in catalogues.values())
    avg_per_segment = total_concepts / len(catalogues) if catalogues else 0

    logger.info(
        f"[OSMOSE:CatalogueBuilder] Built {len(catalogues)} catalogues, "
        f"avg {avg_per_segment:.1f} concepts/segment"
    )

    return catalogues
