"""
Service Concept Explainer (Phase 2 - Intelligence Avancée).

POC "Explain this Concept" - Exploitation du cross-référencement Neo4j ↔ Qdrant
pour fournir des explications enrichies sur les concepts avec sources et relations.
"""

from __future__ import annotations

from typing import List, Optional, Dict, Any
import logging

from neo4j import GraphDatabase

from knowbase.api.schemas.concepts import (
    ConceptExplanation,
    ConceptExplanationRequest,
    SourceChunk,
    RelatedConcept,
)
from knowbase.common.clients.qdrant_client import get_chunks_by_concept
from knowbase.config.settings import get_settings
from knowbase.common.logging import setup_logging

settings = get_settings()
logger = setup_logging(settings.logs_dir, "concept_explainer_service.log")


class ConceptExplainerService:
    """Service pour expliquer les concepts via cross-référencement Neo4j ↔ Qdrant."""

    def __init__(self, tenant_id: str = "default"):
        """
        Initialise le service Concept Explainer.

        Args:
            tenant_id: ID du tenant pour isolation multi-tenant
        """
        self.tenant_id = tenant_id
        self.driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password)
        )

    def close(self):
        """Ferme la connexion Neo4j."""
        if self.driver:
            self.driver.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def explain_concept(
        self,
        request: ConceptExplanationRequest
    ) -> Optional[ConceptExplanation]:
        """
        Explique un concept en combinant données Neo4j et Qdrant.

        Flux:
        1. Récupérer CanonicalConcept depuis Neo4j (name, aliases, chunk_ids)
        2. Récupérer chunks depuis Qdrant via chunk_ids
        3. Récupérer relations depuis Neo4j
        4. Combiner tout dans ConceptExplanation

        Args:
            request: Requête avec canonical_id et paramètres

        Returns:
            ConceptExplanation ou None si concept non trouvé
        """
        logger.info(
            f"[EXPLAINER] Explaining concept {request.canonical_id} "
            f"(chunks={request.include_chunks}, relations={request.include_relations})"
        )

        with self.driver.session() as session:
            # 1. Récupérer CanonicalConcept depuis Neo4j
            concept_data = session.execute_read(
                self._get_canonical_concept_tx,
                request.canonical_id,
                self.tenant_id
            )

            if not concept_data:
                logger.warning(
                    f"[EXPLAINER] Concept {request.canonical_id} not found in Neo4j"
                )
                return None

            # 2. Construire réponse de base
            explanation = ConceptExplanation(
                canonical_id=request.canonical_id,
                name=concept_data["name"],
                aliases=concept_data.get("aliases", []),
                summary=concept_data.get("summary"),
                metadata={
                    "total_chunks": len(concept_data.get("chunk_ids", [])),
                    "created_at": concept_data.get("created_at"),
                }
            )

            # 3. Enrichir avec chunks Qdrant si demandé
            if request.include_chunks:
                source_chunks = self._get_source_chunks(
                    request.canonical_id,
                    max_chunks=request.max_chunks
                )
                explanation.source_chunks = source_chunks
                logger.debug(
                    f"[EXPLAINER] Retrieved {len(source_chunks)} chunks for concept"
                )

            # 4. Enrichir avec relations Neo4j si demandé
            if request.include_relations:
                related_concepts = session.execute_read(
                    self._get_related_concepts_tx,
                    request.canonical_id,
                    self.tenant_id,
                    request.max_relations
                )
                explanation.related_concepts = related_concepts
                logger.debug(
                    f"[EXPLAINER] Retrieved {len(related_concepts)} related concepts"
                )

            logger.info(
                f"[EXPLAINER] ✅ Successfully explained concept {request.canonical_id} "
                f"({len(explanation.source_chunks)} chunks, "
                f"{len(explanation.related_concepts)} relations)"
            )

            return explanation

    @staticmethod
    def _get_canonical_concept_tx(
        tx,
        canonical_id: str,
        tenant_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Récupère CanonicalConcept depuis Neo4j.

        Args:
            tx: Transaction Neo4j
            canonical_id: ID du concept
            tenant_id: ID tenant

        Returns:
            Dict avec données concept ou None si non trouvé
        """
        query = """
        MATCH (c:CanonicalConcept {canonical_id: $canonical_id, tenant_id: $tenant_id})
        RETURN c.canonical_id AS canonical_id,
               c.name AS name,
               c.aliases AS aliases,
               c.chunk_ids AS chunk_ids,
               c.summary AS summary,
               c.created_at AS created_at
        LIMIT 1
        """

        result = tx.run(query, canonical_id=canonical_id, tenant_id=tenant_id)
        record = result.single()

        if not record:
            return None

        return {
            "canonical_id": record["canonical_id"],
            "name": record["name"],
            "aliases": record["aliases"] or [],
            "chunk_ids": record["chunk_ids"] or [],
            "summary": record.get("summary"),
            "created_at": str(record.get("created_at", ""))
        }

    def _get_source_chunks(
        self,
        canonical_concept_id: str,
        max_chunks: int = 10
    ) -> List[SourceChunk]:
        """
        Récupère chunks sources depuis Qdrant.

        Args:
            canonical_concept_id: ID du concept
            max_chunks: Nombre max de chunks à retourner

        Returns:
            Liste de SourceChunk avec métadonnées
        """
        try:
            # Utiliser fonction existante de qdrant_client
            chunks = get_chunks_by_concept(
                canonical_concept_id=canonical_concept_id,
                collection_name=settings.qdrant_collection,
                tenant_id=self.tenant_id,
                limit=max_chunks
            )

            # Convertir en SourceChunk
            source_chunks = []
            for chunk in chunks:
                payload = chunk.get("payload", {})

                source_chunk = SourceChunk(
                    chunk_id=str(chunk.get("id", "")),
                    text=payload.get("text", ""),
                    document_name=payload.get("document_name"),
                    slide_number=payload.get("slide_number"),
                    page_number=payload.get("page_number"),
                    score=None  # Pas de score pour récupération directe
                )
                source_chunks.append(source_chunk)

            return source_chunks

        except Exception as e:
            logger.error(
                f"[EXPLAINER] Error retrieving chunks from Qdrant: {e}",
                exc_info=True
            )
            return []

    @staticmethod
    def _get_related_concepts_tx(
        tx,
        canonical_id: str,
        tenant_id: str,
        max_relations: int = 10
    ) -> List[RelatedConcept]:
        """
        Récupère concepts liés via relations Neo4j.

        Récupère à la fois relations sortantes et entrantes.

        Args:
            tx: Transaction Neo4j
            canonical_id: ID du concept source
            tenant_id: ID tenant
            max_relations: Nombre max de relations à retourner

        Returns:
            Liste de RelatedConcept
        """
        query = """
        MATCH (c:CanonicalConcept {canonical_id: $canonical_id, tenant_id: $tenant_id})

        // Relations sortantes: (c)-[r]->(target)
        OPTIONAL MATCH (c)-[r_out]->(target:CanonicalConcept {tenant_id: $tenant_id})

        // Relations entrantes: (source)-[r]->(c)
        OPTIONAL MATCH (source:CanonicalConcept {tenant_id: $tenant_id})-[r_in]->(c)

        WITH c,
             collect(DISTINCT {
                 canonical_id: target.canonical_id,
                 name: target.name,
                 relationship_type: type(r_out),
                 direction: 'outgoing'
             }) AS outgoing_relations,
             collect(DISTINCT {
                 canonical_id: source.canonical_id,
                 name: source.name,
                 relationship_type: type(r_in),
                 direction: 'incoming'
             }) AS incoming_relations

        RETURN outgoing_relations + incoming_relations AS all_relations
        LIMIT $max_relations
        """

        result = tx.run(
            query,
            canonical_id=canonical_id,
            tenant_id=tenant_id,
            max_relations=max_relations
        )
        record = result.single()

        if not record or not record["all_relations"]:
            return []

        # Convertir en RelatedConcept (filtrer None)
        related_concepts = []
        for rel in record["all_relations"]:
            # Filtrer relations vides (OPTIONAL MATCH peut retourner null)
            if not rel["canonical_id"] or not rel["name"]:
                continue

            related_concept = RelatedConcept(
                canonical_id=rel["canonical_id"],
                name=rel["name"],
                relationship_type=rel["relationship_type"],
                direction=rel["direction"]
            )
            related_concepts.append(related_concept)

        return related_concepts[:max_relations]


__all__ = [
    "ConceptExplainerService",
]
