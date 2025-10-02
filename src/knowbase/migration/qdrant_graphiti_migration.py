"""
Service Migration Qdrant → Graphiti - Phase 1 Critère 1.5

Migre chunks Qdrant existants (sans knowledge graph) vers Graphiti.

Use cases:
1. Migration initiale après déploiement pipeline KG
2. Traitement chunks importés par ancien pipeline
3. Homogénéisation base (tous chunks avec episode_id)

Architecture:
- Groupe chunks par source (filename, import_id)
- Extraction entities/relations via LLM (optionnel)
- Création episodes Graphiti
- Update metadata chunks Qdrant

Usage:
    from knowbase.migration.qdrant_graphiti_migration import migrate_tenant

    result = await migrate_tenant(
        tenant_id="acme_corp",
        dry_run=True,  # Simulation sans modification
        extract_entities=True  # Extraction LLM (coûteux)
    )
"""

import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime
from collections import defaultdict

from knowbase.common.clients.qdrant_client import get_qdrant_client
from knowbase.graphiti.graphiti_client import get_graphiti_client
from knowbase.graphiti.qdrant_sync import get_sync_service

logger = logging.getLogger(__name__)


@dataclass
class MigrationStats:
    """Statistiques migration"""
    chunks_total: int
    chunks_already_migrated: int
    chunks_to_migrate: int
    sources_found: int
    episodes_created: int
    chunks_migrated: int
    errors: int
    duration_seconds: float
    dry_run: bool

    def to_dict(self) -> Dict[str, Any]:
        """Convertir en dict pour API"""
        return {
            "chunks_total": self.chunks_total,
            "chunks_already_migrated": self.chunks_already_migrated,
            "chunks_to_migrate": self.chunks_to_migrate,
            "sources_found": self.sources_found,
            "episodes_created": self.episodes_created,
            "chunks_migrated": self.chunks_migrated,
            "errors": self.errors,
            "duration_seconds": self.duration_seconds,
            "dry_run": self.dry_run
        }

    def print_report(self):
        """Afficher rapport migration"""
        print("\n" + "="*70)
        print(f"RAPPORT MIGRATION {'(DRY-RUN)' if self.dry_run else ''}")
        print("="*70)
        print(f"\n📊 Chunks Qdrant:")
        print(f"   - Total: {self.chunks_total}")
        print(f"   - Déjà migrés: {self.chunks_already_migrated}")
        print(f"   - À migrer: {self.chunks_to_migrate}")
        print(f"\n📦 Sources identifiées: {self.sources_found}")
        print(f"\n✅ Résultats:")
        print(f"   - Episodes créés: {self.episodes_created}")
        print(f"   - Chunks migrés: {self.chunks_migrated}")
        print(f"   - Erreurs: {self.errors}")
        print(f"\n⏱️  Durée: {self.duration_seconds:.2f}s")
        print("="*70 + "\n")


async def migrate_tenant(
    tenant_id: str,
    collection_name: str = "knowbase",
    dry_run: bool = True,
    extract_entities: bool = False,
    limit: Optional[int] = None
) -> MigrationStats:
    """
    Migrer chunks Qdrant existants → episodes Graphiti

    Args:
        tenant_id: ID tenant à migrer
        collection_name: Collection Qdrant (défaut: knowbase)
        dry_run: Si True, simulation sans modification (défaut: True)
        extract_entities: Si True, extraction entities via LLM (coûteux, défaut: False)
        limit: Limite nombre chunks à traiter (None = tous)

    Returns:
        MigrationStats avec résultats détaillés

    Example:
        # Dry-run pour analyser
        stats = await migrate_tenant("acme_corp", dry_run=True)
        stats.print_report()

        # Migration réelle
        stats = await migrate_tenant("acme_corp", dry_run=False)
    """
    start_time = datetime.now()

    logger.info(f"🚀 Début migration tenant: {tenant_id}")
    if dry_run:
        logger.info("⚠️ MODE DRY-RUN: Aucune modification ne sera appliquée")

    qdrant_client = get_qdrant_client()
    graphiti_client = get_graphiti_client()
    sync_service = get_sync_service(qdrant_client, graphiti_client)

    # 1. RÉCUPÉRER CHUNKS QDRANT
    logger.info(f"📊 Récupération chunks Qdrant (collection: {collection_name})...")

    chunks, _ = qdrant_client.scroll(
        collection_name=collection_name,
        limit=limit or 10000,
        with_payload=True,
        scroll_filter=None
    )

    logger.info(f"   Trouvé {len(chunks)} chunks total")

    # 2. FILTRER CHUNKS SANS KNOWLEDGE GRAPH
    chunks_without_kg = [
        c for c in chunks
        if c.payload and not c.payload.get("has_knowledge_graph", False)
    ]

    chunks_with_kg = len(chunks) - len(chunks_without_kg)

    logger.info(f"   - {chunks_with_kg} chunks déjà avec KG (skip)")
    logger.info(f"   - {len(chunks_without_kg)} chunks à migrer")

    # 3. GROUPER PAR SOURCE
    logger.info(f"📦 Groupement chunks par source...")

    chunks_by_source = defaultdict(list)

    for chunk in chunks_without_kg:
        # Identifier source depuis metadata
        filename = chunk.payload.get("filename", "unknown")
        import_id = chunk.payload.get("import_id", "")
        solution = chunk.payload.get("solution", "")

        # Clé source unique
        source_key = f"{filename}_{import_id}" if import_id else filename

        chunks_by_source[source_key].append(chunk)

    logger.info(f"   Identifié {len(chunks_by_source)} sources distinctes")

    # Afficher aperçu sources
    for source, source_chunks in list(chunks_by_source.items())[:5]:
        logger.info(f"     - {source}: {len(source_chunks)} chunks")

    if len(chunks_by_source) > 5:
        logger.info(f"     ... et {len(chunks_by_source) - 5} autres sources")

    # 4. CRÉER EPISODES GRAPHITI
    episodes_created = 0
    chunks_migrated = 0
    errors = 0

    for source_key, source_chunks in chunks_by_source.items():
        logger.info(f"\n🌐 Traitement source: {source_key} ({len(source_chunks)} chunks)")

        try:
            # 4.1. Combiner contenu chunks
            combined_content = _combine_chunks_content(source_chunks)

            # 4.2. Extraction entities/relations (optionnel)
            entities = []
            relations = []

            if extract_entities:
                logger.info(f"   🤖 Extraction entities via LLM...")
                # TODO: Implémenter extraction LLM
                # entities, relations = await extract_entities_from_content(combined_content)
                logger.warning(f"   ⚠️ Extraction entities non implémentée (skip)")

            # 4.3. Créer episode Graphiti
            episode_name = f"Migration: {source_key}"
            episode_content = f"""Migration automatique chunks Qdrant → Graphiti

Source: {source_key}
Chunks migrés: {len(source_chunks)}
Date migration: {datetime.now().isoformat()}

Contenu combiné:
{combined_content[:5000]}...  # Limité à 5000 chars
"""

            if not dry_run:
                # Créer episode Graphiti
                logger.info(f"   📤 Création episode Graphiti...")

                messages = [{
                    "content": episode_content,
                    "role_type": "user"
                }]

                # Ajouter entities/relations si extraites
                if entities:
                    messages[0]["entities"] = entities
                if relations:
                    messages[0]["relations"] = relations

                result = graphiti_client.add_episode(
                    group_id=tenant_id,
                    messages=messages
                )

                logger.info(f"   ✅ Episode créé")
                episodes_created += 1

                # 4.4. Générer episode_id (custom)
                # Note: API Graphiti ne retourne pas UUID, on génère le nôtre
                episode_id = f"migrated_{tenant_id}_{source_key}_{datetime.now().strftime('%Y%m%d')}"

                # 4.5. Update chunks Qdrant avec episode_id
                logger.info(f"   📝 Update metadata {len(source_chunks)} chunks...")

                chunk_ids = [str(c.id) for c in source_chunks]

                await sync_service.link_chunks_to_episode(
                    chunk_ids=chunk_ids,
                    episode_id=episode_id,
                    episode_name=episode_name
                )

                # Ajouter flag migration
                qdrant_client.set_payload(
                    collection_name=collection_name,
                    payload={"migrated_at": datetime.now().isoformat()},
                    points=chunk_ids
                )

                chunks_migrated += len(source_chunks)
                logger.info(f"   ✅ {len(source_chunks)} chunks migrés")

            else:
                # DRY-RUN: simulation
                logger.info(f"   [DRY-RUN] Aurait créé episode: {episode_name}")
                logger.info(f"   [DRY-RUN] Aurait migré {len(source_chunks)} chunks")
                episodes_created += 1
                chunks_migrated += len(source_chunks)

        except Exception as e:
            logger.error(f"   ❌ Erreur source {source_key}: {e}", exc_info=True)
            errors += 1

    # 5. STATISTIQUES FINALES
    duration = (datetime.now() - start_time).total_seconds()

    stats = MigrationStats(
        chunks_total=len(chunks),
        chunks_already_migrated=chunks_with_kg,
        chunks_to_migrate=len(chunks_without_kg),
        sources_found=len(chunks_by_source),
        episodes_created=episodes_created,
        chunks_migrated=chunks_migrated,
        errors=errors,
        duration_seconds=duration,
        dry_run=dry_run
    )

    logger.info(f"✅ Migration terminée en {duration:.2f}s")

    return stats


def _combine_chunks_content(chunks: List[Any], max_chars: int = 10000) -> str:
    """
    Combiner contenu de plusieurs chunks

    Args:
        chunks: Liste chunks Qdrant
        max_chars: Limite taille contenu combiné

    Returns:
        Contenu combiné (limité à max_chars)
    """
    combined = []

    for chunk in chunks:
        text = chunk.payload.get("text", "")
        if text:
            combined.append(text)

        # Limiter taille totale
        combined_text = "\n\n".join(combined)
        if len(combined_text) > max_chars:
            break

    return combined_text[:max_chars]


async def analyze_migration_needs(
    tenant_id: str,
    collection_name: str = "knowbase"
) -> Dict[str, Any]:
    """
    Analyser besoin migration sans modifier données

    Retourne statistiques sur chunks à migrer, sources, etc.

    Args:
        tenant_id: ID tenant
        collection_name: Collection Qdrant

    Returns:
        Dict avec statistiques analyse
    """
    logger.info(f"📊 Analyse besoins migration pour tenant: {tenant_id}")

    qdrant_client = get_qdrant_client()

    # Récupérer chunks
    chunks, _ = qdrant_client.scroll(
        collection_name=collection_name,
        limit=10000,
        with_payload=True
    )

    # Analyser
    chunks_without_kg = [
        c for c in chunks
        if c.payload and not c.payload.get("has_knowledge_graph", False)
    ]

    # Grouper par source
    chunks_by_source = defaultdict(list)
    for chunk in chunks_without_kg:
        filename = chunk.payload.get("filename", "unknown")
        chunks_by_source[filename].append(chunk)

    # Sources avec plus de chunks
    top_sources = sorted(
        chunks_by_source.items(),
        key=lambda x: len(x[1]),
        reverse=True
    )[:10]

    analysis = {
        "tenant_id": tenant_id,
        "chunks_total": len(chunks),
        "chunks_with_kg": len(chunks) - len(chunks_without_kg),
        "chunks_without_kg": len(chunks_without_kg),
        "sources_count": len(chunks_by_source),
        "top_sources": [
            {"filename": source, "chunks_count": len(source_chunks)}
            for source, source_chunks in top_sources
        ],
        "migration_recommended": len(chunks_without_kg) > 0
    }

    logger.info(f"   Chunks sans KG: {analysis['chunks_without_kg']}/{analysis['chunks_total']}")
    logger.info(f"   Sources: {analysis['sources_count']}")

    return analysis
