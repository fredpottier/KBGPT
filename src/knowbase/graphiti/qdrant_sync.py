"""
Service Synchronisation Qdrant ↔ Graphiti - Phase 1 Critère 1.3

Synchronisation bidirectionnelle entre:
- Qdrant: chunks vectoriels (similarity search)
- Graphiti: episodes/facts (knowledge graph)

Usage:
    from knowbase.graphiti.qdrant_sync import sync_service

    # Ingestion enrichie (chunks + episode)
    result = await sync_service.ingest_with_kg(
        content=slide_content,
        metadata=metadata,
        tenant_id="bouygues"
    )

    # Enrichir chunks existants avec episode_id
    await sync_service.link_chunks_to_episode(
        chunk_ids=chunk_ids,
        episode_id=episode_uuid
    )
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    """Résultat synchronisation Qdrant ↔ Graphiti"""
    chunk_ids: List[str]
    episode_id: str
    episode_name: str
    facts_count: int
    success: bool
    error: Optional[str] = None


class QdrantGraphitiSyncService:
    """
    Service synchronisation Qdrant ↔ Graphiti

    Responsabilités:
    - Créer episodes Graphiti depuis chunks Qdrant
    - Lier chunks ↔ episodes (metadata bidirectionnelle)
    - Enrichir chunks avec entities/facts Graphiti
    """

    def __init__(
        self,
        qdrant_client,
        graphiti_client,
        collection_name: str = "knowbase"
    ):
        """
        Args:
            qdrant_client: Client Qdrant
            graphiti_client: Client Graphiti
            collection_name: Collection Qdrant (défaut: knowbase)
        """
        self.qdrant_client = qdrant_client
        self.graphiti_client = graphiti_client
        self.collection_name = collection_name

    async def ingest_with_kg(
        self,
        content: str,
        metadata: Dict[str, Any],
        tenant_id: str,
        source_description: str,
        create_chunks: bool = True
    ) -> SyncResult:
        """
        Ingestion enrichie : chunks Qdrant + episode Graphiti

        Args:
            content: Contenu texte (slide, PDF page, etc.)
            metadata: Métadonnées Qdrant
            tenant_id: ID tenant
            source_description: Description source (ex: "PPTX slide_001.pptx")
            create_chunks: Si True, créer chunks Qdrant (sinon juste episode)

        Returns:
            SyncResult avec chunk_ids + episode_id
        """
        try:
            chunk_ids = []

            # 1. Créer chunks Qdrant (si demandé)
            if create_chunks:
                # Import local pour éviter circular import
                from knowbase.ingestion.chunking import chunk_text

                chunks = chunk_text(content, metadata=metadata)

                # Upsert Qdrant
                chunk_ids = await self.qdrant_client.upsert_chunks(
                    chunks=chunks,
                    collection_name=self.collection_name
                )

                logger.info(f"✅ Created {len(chunk_ids)} chunks in Qdrant")

            # 2. Créer episode Graphiti
            episode_name = self._generate_episode_name(metadata)

            episode = await self.graphiti_client.add_episode(
                name=episode_name,
                episode_body=content,
                source_description=source_description,
                reference_time=datetime.now(),
                tenant_id=tenant_id
            )

            logger.info(
                f"✅ Created episode {episode.uuid} ({episode_name}) "
                f"with {len(episode.facts)} facts"
            )

            # 3. Lier chunks → episode (metadata Qdrant)
            if chunk_ids:
                await self.link_chunks_to_episode(
                    chunk_ids=chunk_ids,
                    episode_id=episode.uuid,
                    episode_name=episode_name
                )

            return SyncResult(
                chunk_ids=chunk_ids,
                episode_id=episode.uuid,
                episode_name=episode_name,
                facts_count=len(episode.facts),
                success=True
            )

        except Exception as e:
            logger.error(f"❌ Sync failed: {e}", exc_info=True)
            return SyncResult(
                chunk_ids=[],
                episode_id="",
                episode_name="",
                facts_count=0,
                success=False,
                error=str(e)
            )

    async def link_chunks_to_episode(
        self,
        chunk_ids: List[str],
        episode_id: str,
        episode_name: str
    ):
        """
        Lier chunks Qdrant → episode Graphiti (metadata)

        Args:
            chunk_ids: IDs chunks Qdrant
            episode_id: UUID episode Graphiti
            episode_name: Nom episode
        """
        if not chunk_ids:
            return

        # Metadata à ajouter aux chunks
        episode_metadata = {
            "episode_id": episode_id,
            "episode_name": episode_name,
            "has_knowledge_graph": True
        }

        # Update metadata Qdrant avec set_payload
        # Note: Qdrant utilise set_payload pour enrichir metadata existante
        self.qdrant_client.set_payload(
            collection_name=self.collection_name,
            payload=episode_metadata,
            points=chunk_ids
        )

        logger.info(
            f"✅ Linked {len(chunk_ids)} chunks to episode {episode_id}"
        )

    def enrich_chunks_with_entities(
        self,
        chunk_ids: List[str],
        episode_id: str
    ) -> int:
        """
        Enrichir chunks avec entities/facts depuis episode Graphiti

        Args:
            chunk_ids: IDs chunks à enrichir
            episode_id: UUID episode Graphiti

        Returns:
            Nombre chunks enrichis
        """
        # Récupérer episode + facts (synchrone)
        episode = self.graphiti_client.get_episode(
            episode_uuid=episode_id
        )

        if not episode:
            logger.warning(f"Episode {episode_id} not found")
            return 0

        # Extraire entities depuis facts
        entities = self._extract_entities_from_facts(episode.facts)

        if not entities:
            logger.info(f"No entities found in episode {episode_id}")
            return 0

        # Enrichir metadata chunks
        entity_metadata = {
            "entities": entities,
            "facts_count": len(episode.facts)
        }

        self.qdrant_client.set_payload(
            collection_name=self.collection_name,
            payload=entity_metadata,
            points=chunk_ids
        )

        logger.info(
            f"✅ Enriched {len(chunk_ids)} chunks with {len(entities)} entities"
        )

        return len(chunk_ids)

    async def get_episode_for_chunks(
        self,
        chunk_ids: List[str]
    ) -> Optional[str]:
        """
        Récupérer episode_id depuis chunks Qdrant

        Args:
            chunk_ids: IDs chunks

        Returns:
            episode_id ou None
        """
        if not chunk_ids:
            return None

        # Récupérer premier chunk pour extraire episode_id
        chunks = await self.qdrant_client.retrieve(
            collection_name=self.collection_name,
            ids=[chunk_ids[0]]
        )

        if chunks and chunks[0].payload:
            return chunks[0].payload.get("episode_id")

        return None

    def _generate_episode_name(self, metadata: Dict[str, Any]) -> str:
        """
        Générer nom episode depuis metadata

        Args:
            metadata: Métadonnées chunk

        Returns:
            Nom episode (ex: "PPTX: slide_001.pptx - Page 5")
        """
        filename = metadata.get("filename", "unknown")
        page = metadata.get("page_number", "")
        source_type = metadata.get("source_type", "document")

        if page:
            return f"{source_type.upper()}: {filename} - Page {page}"
        else:
            return f"{source_type.upper()}: {filename}"

    def _extract_entities_from_facts(
        self,
        facts: List[Any]
    ) -> List[str]:
        """
        Extraire liste entities depuis facts Graphiti

        Args:
            facts: Facts Graphiti

        Returns:
            Liste noms entities uniques
        """
        entities = set()

        for fact in facts:
            # Extraire entities depuis fact (subject, object)
            if hasattr(fact, 'fact_embedding'):
                # Fact a des embeddings avec entities
                entities.add(fact.fact_embedding.get('subject', ''))
                entities.add(fact.fact_embedding.get('object', ''))

        # Filtrer vides
        return [e for e in entities if e]


# Instance globale (singleton)
_sync_service_instance = None


def get_sync_service(qdrant_client, graphiti_client) -> QdrantGraphitiSyncService:
    """
    Récupérer instance service sync (singleton)

    Args:
        qdrant_client: Client Qdrant
        graphiti_client: Client Graphiti

    Returns:
        QdrantGraphitiSyncService
    """
    global _sync_service_instance
    if _sync_service_instance is None:
        _sync_service_instance = QdrantGraphitiSyncService(
            qdrant_client=qdrant_client,
            graphiti_client=graphiti_client
        )
    return _sync_service_instance
