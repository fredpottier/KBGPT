# Phase 2 OSMOSE - Neo4j Relationship Writer
# Persistance relations typées dans Neo4j

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from knowbase.relations.types import (
    TypedRelation,
    RelationType,
    RelationStatus,
    RelationStrength
)
from knowbase.db.neo4j_manager import Neo4jManager

logger = logging.getLogger(__name__)


class Neo4jRelationshipWriter:
    """
    Writer pour persister relations typées dans Neo4j.

    Architecture:
    - Upsert relations entre CanonicalConcept nodes
    - Gestion metadata complète (confidence, source_doc, etc.)
    - Support 12 types relations (9 core + 3 optionnels)
    - Validation existence concepts source/target
    - Update relations existantes si nouvelle confidence > ancienne

    Phase 2 OSMOSE - Semaines 14-15
    """

    def __init__(
        self,
        neo4j_manager: Optional[Neo4jManager] = None,
        tenant_id: str = "default"
    ):
        """
        Initialise Neo4j writer.

        Args:
            neo4j_manager: Manager Neo4j (default: nouveau instance)
            tenant_id: Tenant ID pour isolation multi-tenant
        """
        self.neo4j = neo4j_manager or Neo4jManager()
        self.tenant_id = tenant_id

        logger.info(
            f"[OSMOSE:Neo4jRelationshipWriter] Initialized (tenant={tenant_id})"
        )

    def write_relations(
        self,
        relations: List[TypedRelation],
        document_id: str,
        document_name: str
    ) -> Dict[str, Any]:
        """
        Écrire relations dans Neo4j.

        Pipeline:
        1. Valider existence concepts source/target
        2. Pour chaque relation:
            - Vérifier si relation existe déjà
            - Si existe: update si nouvelle confidence > ancienne
            - Si nouvelle: créer relation
        3. Logger statistiques

        Args:
            relations: Liste relations à persister
            document_id: ID document source
            document_name: Nom document source

        Returns:
            Statistiques écriture:
            {
                "total_relations": int,
                "created": int,
                "updated": int,
                "skipped": int,
                "errors": int,
                "relations_by_type": Dict[RelationType, int]
            }
        """
        logger.info(
            f"[OSMOSE:Neo4jRelationshipWriter] Writing {len(relations)} relations "
            f"from {document_name}"
        )

        stats = {
            "total_relations": len(relations),
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "errors": 0,
            "relations_by_type": {}
        }

        for relation in relations:
            try:
                # Upsert relation
                result = self._upsert_relation(
                    relation=relation,
                    document_id=document_id,
                    document_name=document_name
                )

                # Update stats
                if result == "created":
                    stats["created"] += 1
                elif result == "updated":
                    stats["updated"] += 1
                else:  # skipped
                    stats["skipped"] += 1

                # Count by type
                rel_type = relation.relation_type
                stats["relations_by_type"][rel_type] = \
                    stats["relations_by_type"].get(rel_type, 0) + 1

            except Exception as e:
                logger.error(
                    f"[OSMOSE:Neo4jRelationshipWriter] Error writing relation "
                    f"{relation.source_concept} → {relation.target_concept}: {e}",
                    exc_info=True
                )
                stats["errors"] += 1

        logger.info(
            f"[OSMOSE:Neo4jRelationshipWriter] ✅ Wrote {stats['created']} new, "
            f"updated {stats['updated']}, skipped {stats['skipped']}, "
            f"errors {stats['errors']}"
        )

        return stats

    def _upsert_relation(
        self,
        relation: TypedRelation,
        document_id: str,
        document_name: str
    ) -> str:
        """
        Upsert une relation dans Neo4j.

        Logique:
        1. Vérifier existence concepts source/target
        2. Si relation existe:
            - Comparer confidence
            - Si nouvelle > ancienne: update
            - Sinon: skip
        3. Si relation n'existe pas: créer

        Args:
            relation: Relation à upserter
            document_id: ID document source
            document_name: Nom document

        Returns:
            "created", "updated", ou "skipped"
        """
        # Validation: concepts existent-ils ?
        if not self._concepts_exist(relation.source_concept, relation.target_concept):
            logger.warning(
                f"[OSMOSE:Neo4jRelationshipWriter] Concepts not found: "
                f"{relation.source_concept} or {relation.target_concept}"
            )
            return "skipped"

        # Vérifier si relation existe déjà
        existing = self._get_existing_relation(
            source_id=relation.source_concept,
            target_id=relation.target_concept,
            relation_type=relation.relation_type
        )

        if existing:
            # Relation existe, comparer confidence
            existing_confidence = existing.get("confidence", 0.0)
            new_confidence = relation.metadata.confidence

            if new_confidence > existing_confidence:
                # Update relation avec nouvelle confidence
                self._update_relation(relation)
                logger.debug(
                    f"[OSMOSE:Neo4jRelationshipWriter] Updated {relation.relation_type} "
                    f"(conf: {existing_confidence:.2f} → {new_confidence:.2f})"
                )
                return "updated"
            else:
                # Skip, confidence existante meilleure
                logger.debug(
                    f"[OSMOSE:Neo4jRelationshipWriter] Skipped {relation.relation_type} "
                    f"(existing conf {existing_confidence:.2f} >= new {new_confidence:.2f})"
                )
                return "skipped"
        else:
            # Nouvelle relation, créer
            self._create_relation(relation)
            logger.debug(
                f"[OSMOSE:Neo4jRelationshipWriter] Created {relation.relation_type} "
                f"{relation.source_concept} → {relation.target_concept} "
                f"(conf: {relation.metadata.confidence:.2f})"
            )
            return "created"

    def _concepts_exist(
        self,
        source_id: str,
        target_id: str
    ) -> bool:
        """
        Vérifier que concepts source et target existent dans Neo4j.

        Args:
            source_id: ID concept source
            target_id: ID concept target

        Returns:
            True si les deux existent
        """
        query = """
        MATCH (source:CanonicalConcept {concept_id: $source_id, tenant_id: $tenant_id})
        MATCH (target:CanonicalConcept {concept_id: $target_id, tenant_id: $tenant_id})
        RETURN count(source) as source_count, count(target) as target_count
        """

        result = self.neo4j.execute_query(
            query,
            source_id=source_id,
            target_id=target_id,
            tenant_id=self.tenant_id
        )

        if result:
            record = result[0]
            return record["source_count"] > 0 and record["target_count"] > 0

        return False

    def _get_existing_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: RelationType
    ) -> Optional[Dict[str, Any]]:
        """
        Récupérer relation existante si elle existe.

        Args:
            source_id: ID concept source
            target_id: ID concept target
            relation_type: Type relation

        Returns:
            Metadata relation si existe, None sinon
        """
        # Construire query dynamique selon type relation
        rel_type_str = relation_type.value

        query = f"""
        MATCH (source:CanonicalConcept {{concept_id: $source_id, tenant_id: $tenant_id}})
        -[r:{rel_type_str}]->
        (target:CanonicalConcept {{concept_id: $target_id, tenant_id: $tenant_id}})
        RETURN properties(r) as rel_props
        """

        result = self.neo4j.execute_query(
            query,
            source_id=source_id,
            target_id=target_id,
            tenant_id=self.tenant_id
        )

        if result:
            return result[0]["rel_props"]

        return None

    def _create_relation(
        self,
        relation: TypedRelation
    ) -> None:
        """
        Créer nouvelle relation dans Neo4j.

        Args:
            relation: Relation à créer
        """
        rel_type_str = relation.relation_type.value

        # Préparer metadata
        metadata = self._prepare_metadata(relation)

        # Query MERGE pour éviter duplicates
        query = f"""
        MATCH (source:CanonicalConcept {{concept_id: $source_id, tenant_id: $tenant_id}})
        MATCH (target:CanonicalConcept {{concept_id: $target_id, tenant_id: $tenant_id}})
        MERGE (source)-[r:{rel_type_str}]->(target)
        SET r = $metadata
        RETURN r
        """

        self.neo4j.execute_query(
            query,
            source_id=relation.source_concept,
            target_id=relation.target_concept,
            tenant_id=self.tenant_id,
            metadata=metadata
        )

    def _update_relation(
        self,
        relation: TypedRelation
    ) -> None:
        """
        Mettre à jour relation existante.

        Args:
            relation: Relation avec nouvelles valeurs
        """
        rel_type_str = relation.relation_type.value

        # Préparer metadata
        metadata = self._prepare_metadata(relation)

        # Update relation
        query = f"""
        MATCH (source:CanonicalConcept {{concept_id: $source_id, tenant_id: $tenant_id}})
        -[r:{rel_type_str}]->
        (target:CanonicalConcept {{concept_id: $target_id, tenant_id: $tenant_id}})
        SET r = $metadata
        RETURN r
        """

        self.neo4j.execute_query(
            query,
            source_id=relation.source_concept,
            target_id=relation.target_concept,
            tenant_id=self.tenant_id,
            metadata=metadata
        )

    def _prepare_metadata(
        self,
        relation: TypedRelation
    ) -> Dict[str, Any]:
        """
        Préparer metadata pour Neo4j.

        Convertit TypedRelation → Dict metadata Neo4j-compatible.

        Args:
            relation: Relation source

        Returns:
            Dict metadata pour Neo4j
        """
        metadata = {
            "confidence": relation.metadata.confidence,
            "extraction_method": relation.metadata.extraction_method.value,
            "source_doc_id": relation.metadata.source_doc_id,
            "source_chunk_ids": relation.metadata.source_chunk_ids,
            "language": relation.metadata.language,
            "created_at": relation.metadata.created_at.isoformat(),
            "strength": relation.metadata.strength.value,
            "status": relation.metadata.status.value,
            "require_validation": relation.metadata.require_validation
        }

        # Ajouter evidence si présente
        if relation.evidence:
            metadata["evidence"] = relation.evidence

        # Ajouter context si présent
        if relation.context:
            metadata["context"] = relation.context

        # Metadata spécifiques REPLACES
        if relation.relation_type == RelationType.REPLACES:
            if relation.metadata.breaking_changes:
                metadata["breaking_changes"] = relation.metadata.breaking_changes
            if relation.metadata.migration_effort:
                metadata["migration_effort"] = relation.metadata.migration_effort
            if relation.metadata.backward_compatible is not None:
                metadata["backward_compatible"] = relation.metadata.backward_compatible

        # Metadata temporelles
        if relation.metadata.timeline_position is not None:
            metadata["timeline_position"] = relation.metadata.timeline_position
        if relation.metadata.release_date:
            metadata["release_date"] = relation.metadata.release_date.isoformat()
        if relation.metadata.eol_date:
            metadata["eol_date"] = relation.metadata.eol_date.isoformat()

        return metadata

    def delete_relations_by_document(
        self,
        document_id: str
    ) -> int:
        """
        Supprimer toutes relations extraites d'un document.

        Utile pour ré-import clean d'un document.

        Args:
            document_id: ID document

        Returns:
            Nombre relations supprimées
        """
        query = """
        MATCH (source:CanonicalConcept {tenant_id: $tenant_id})
        -[r]->
        (target:CanonicalConcept {tenant_id: $tenant_id})
        WHERE r.source_doc_id = $document_id
        DELETE r
        RETURN count(r) as deleted_count
        """

        result = self.neo4j.execute_query(
            query,
            tenant_id=self.tenant_id,
            document_id=document_id
        )

        deleted_count = result[0]["deleted_count"] if result else 0

        logger.info(
            f"[OSMOSE:Neo4jRelationshipWriter] Deleted {deleted_count} relations "
            f"from document {document_id}"
        )

        return deleted_count

    def get_relations_by_concept(
        self,
        concept_id: str,
        direction: str = "both"  # "outgoing", "incoming", "both"
    ) -> List[Dict[str, Any]]:
        """
        Récupérer toutes relations d'un concept.

        Args:
            concept_id: ID concept
            direction: Direction relations ("outgoing", "incoming", "both")

        Returns:
            Liste relations avec metadata
        """
        if direction == "outgoing":
            query = """
            MATCH (source:CanonicalConcept {concept_id: $concept_id, tenant_id: $tenant_id})
            -[r]->
            (target:CanonicalConcept {tenant_id: $tenant_id})
            RETURN type(r) as relation_type, properties(r) as metadata,
                   target.concept_id as target_id, target.canonical_name as target_name
            """
        elif direction == "incoming":
            query = """
            MATCH (source:CanonicalConcept {tenant_id: $tenant_id})
            -[r]->
            (target:CanonicalConcept {concept_id: $concept_id, tenant_id: $tenant_id})
            RETURN type(r) as relation_type, properties(r) as metadata,
                   source.concept_id as source_id, source.canonical_name as source_name
            """
        else:  # both
            query = """
            MATCH (source:CanonicalConcept {concept_id: $concept_id, tenant_id: $tenant_id})
            -[r]->
            (target:CanonicalConcept {tenant_id: $tenant_id})
            RETURN 'outgoing' as direction, type(r) as relation_type,
                   properties(r) as metadata, target.concept_id as other_id,
                   target.canonical_name as other_name
            UNION
            MATCH (source:CanonicalConcept {tenant_id: $tenant_id})
            -[r]->
            (target:CanonicalConcept {concept_id: $concept_id, tenant_id: $tenant_id})
            RETURN 'incoming' as direction, type(r) as relation_type,
                   properties(r) as metadata, source.concept_id as other_id,
                   source.canonical_name as other_name
            """

        result = self.neo4j.execute_query(
            query,
            concept_id=concept_id,
            tenant_id=self.tenant_id
        )

        return [dict(record) for record in result] if result else []
