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
from knowbase.common.clients.neo4j_client import Neo4jClient, get_neo4j_client
import os

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
        neo4j_client: Optional[Neo4jClient] = None,
        tenant_id: str = "default"
    ):
        """
        Initialise Neo4j writer.

        Args:
            neo4j_client: Client Neo4j (default: singleton from env)
            tenant_id: Tenant ID pour isolation multi-tenant
        """
        # Fix 2025-10-20: Utiliser get_neo4j_client() pour lire config depuis .env
        if neo4j_client:
            self.neo4j = neo4j_client
        else:
            self.neo4j = get_neo4j_client(
                uri=os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
                user=os.getenv("NEO4J_USER", "neo4j"),
                password=os.getenv("NEO4J_PASSWORD", "password")
            )

        self.tenant_id = tenant_id

        logger.info(
            f"[OSMOSE:Neo4jRelationshipWriter] Initialized (tenant={tenant_id}, uri={self.neo4j.uri})"
        )

    def _execute_query(
        self,
        query: str,
        **params
    ) -> List[Dict[str, Any]]:
        """
        Exécuter requête Cypher Neo4j.

        Args:
            query: Query Cypher
            **params: Paramètres query

        Returns:
            Liste résultats (records as dicts)
        """
        if not self.neo4j.is_connected():
            logger.error("[OSMOSE:Neo4jRelationshipWriter] Neo4j not connected")
            return []

        try:
            with self.neo4j.driver.session(database=self.neo4j.database) as session:
                result = session.run(query, **params)
                return [dict(record) for record in result]
        except Exception as e:
            logger.error(
                f"[OSMOSE:Neo4jRelationshipWriter] Query execution failed: {e}",
                exc_info=True
            )
            return []

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
        1. Résoudre IDs concepts source/target
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
        # Résoudre les IDs des concepts (peuvent être des noms)
        resolved_source = self._resolve_concept_id(relation.source_concept)
        resolved_target = self._resolve_concept_id(relation.target_concept)

        if not resolved_source or not resolved_target:
            logger.warning(
                f"[OSMOSE:Neo4jRelationshipWriter] Concepts not found: "
                f"{relation.source_concept} or {relation.target_concept}"
            )
            return "skipped"

        # Vérifier si relation existe déjà (avec IDs résolus)
        existing = self._get_existing_relation(
            source_id=resolved_source,
            target_id=resolved_target,
            relation_type=relation.relation_type
        )

        if existing:
            # Relation existe, comparer confidence
            existing_confidence = existing.get("confidence", 0.0)
            new_confidence = relation.metadata.confidence

            if new_confidence > existing_confidence:
                # Update relation avec nouvelle confidence
                self._update_relation_with_ids(relation, resolved_source, resolved_target)
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
            # Nouvelle relation, créer (avec IDs résolus)
            self._create_relation_with_ids(relation, resolved_source, resolved_target)
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
        Cherche par canonical_id OU canonical_name (pour compatibilité LLM).

        Args:
            source_id: ID ou nom concept source
            target_id: ID ou nom concept target

        Returns:
            True si les deux existent
        """
        # Résoudre les IDs (peuvent être des noms de concepts)
        resolved_source = self._resolve_concept_id(source_id)
        resolved_target = self._resolve_concept_id(target_id)

        return resolved_source is not None and resolved_target is not None

    def _resolve_concept_id(self, concept_ref: str) -> Optional[str]:
        """
        Résoudre une référence de concept en canonical_id.

        Stratégie de matching:
        1. Si c'est un UUID valide, chercher par canonical_id
        2. Sinon chercher par canonical_name (exact match, case-insensitive)
        3. Sinon chercher par surface_form

        Args:
            concept_ref: ID ou nom du concept

        Returns:
            canonical_id si trouvé, None sinon
        """
        # Cache pour éviter requêtes répétées
        if not hasattr(self, '_concept_cache'):
            self._concept_cache = {}

        if concept_ref in self._concept_cache:
            return self._concept_cache[concept_ref]

        # Stratégie 1: Recherche par canonical_id (si ressemble à UUID)
        if len(concept_ref) == 36 and '-' in concept_ref:
            query = """
            MATCH (c:CanonicalConcept {canonical_id: $ref, tenant_id: $tenant_id})
            RETURN c.canonical_id as id
            LIMIT 1
            """
            result = self._execute_query(query, ref=concept_ref, tenant_id=self.tenant_id)
            if result:
                self._concept_cache[concept_ref] = result[0]["id"]
                return result[0]["id"]

        # Stratégie 2: Recherche par canonical_name (case-insensitive)
        query = """
        MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
        WHERE toLower(c.canonical_name) = toLower($ref)
        RETURN c.canonical_id as id
        LIMIT 1
        """
        result = self._execute_query(query, ref=concept_ref, tenant_id=self.tenant_id)
        if result:
            self._concept_cache[concept_ref] = result[0]["id"]
            return result[0]["id"]

        # Stratégie 3: Recherche par surface_form
        query = """
        MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
        WHERE toLower(c.surface_form) = toLower($ref)
        RETURN c.canonical_id as id
        LIMIT 1
        """
        result = self._execute_query(query, ref=concept_ref, tenant_id=self.tenant_id)
        if result:
            self._concept_cache[concept_ref] = result[0]["id"]
            return result[0]["id"]

        # Stratégie 4: Recherche fuzzy (contient le terme)
        query = """
        MATCH (c:CanonicalConcept {tenant_id: $tenant_id})
        WHERE toLower(c.canonical_name) CONTAINS toLower($ref)
           OR toLower($ref) CONTAINS toLower(c.canonical_name)
        RETURN c.canonical_id as id, c.canonical_name as name
        LIMIT 1
        """
        result = self._execute_query(query, ref=concept_ref, tenant_id=self.tenant_id)
        if result:
            self._concept_cache[concept_ref] = result[0]["id"]
            logger.debug(
                f"[OSMOSE:Neo4jRelationshipWriter] Fuzzy matched '{concept_ref}' → '{result[0]['name']}'"
            )
            return result[0]["id"]

        # Pas trouvé
        self._concept_cache[concept_ref] = None
        return None

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
        rel_type_str = relation_type.value if hasattr(relation_type, 'value') else relation_type

        query = f"""
        MATCH (source:CanonicalConcept {{canonical_id: $source_id, tenant_id: $tenant_id}})
        -[r:{rel_type_str}]->
        (target:CanonicalConcept {{canonical_id: $target_id, tenant_id: $tenant_id}})
        RETURN properties(r) as rel_props
        """

        result = self._execute_query(
            query,
            source_id=source_id,
            target_id=target_id,
            tenant_id=self.tenant_id
        )

        if result:
            return result[0]["rel_props"]

        return None

    def _create_relation_with_ids(
        self,
        relation: TypedRelation,
        source_id: str,
        target_id: str
    ) -> None:
        """
        Créer nouvelle relation dans Neo4j avec IDs résolus.

        Args:
            relation: Relation à créer
            source_id: canonical_id résolu du concept source
            target_id: canonical_id résolu du concept target
        """
        rel_type_str = relation.relation_type.value if hasattr(relation.relation_type, 'value') else relation.relation_type

        # Préparer metadata
        metadata = self._prepare_metadata(relation)

        # Query MERGE pour éviter duplicates
        query = f"""
        MATCH (source:CanonicalConcept {{canonical_id: $source_id, tenant_id: $tenant_id}})
        MATCH (target:CanonicalConcept {{canonical_id: $target_id, tenant_id: $tenant_id}})
        MERGE (source)-[r:{rel_type_str}]->(target)
        SET r = $metadata
        RETURN r
        """

        self._execute_query(
            query,
            source_id=source_id,
            target_id=target_id,
            tenant_id=self.tenant_id,
            metadata=metadata
        )

    def _update_relation_with_ids(
        self,
        relation: TypedRelation,
        source_id: str,
        target_id: str
    ) -> None:
        """
        Mettre à jour relation existante avec IDs résolus.

        Args:
            relation: Relation avec nouvelles valeurs
            source_id: canonical_id résolu du concept source
            target_id: canonical_id résolu du concept target
        """
        rel_type_str = relation.relation_type.value if hasattr(relation.relation_type, 'value') else relation.relation_type

        # Préparer metadata
        metadata = self._prepare_metadata(relation)

        # Update relation
        query = f"""
        MATCH (source:CanonicalConcept {{canonical_id: $source_id, tenant_id: $tenant_id}})
        -[r:{rel_type_str}]->
        (target:CanonicalConcept {{canonical_id: $target_id, tenant_id: $tenant_id}})
        SET r = $metadata
        RETURN r
        """

        self._execute_query(
            query,
            source_id=source_id,
            target_id=target_id,
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

        result = self._execute_query(
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
            MATCH (source:CanonicalConcept {canonical_id: $concept_id, tenant_id: $tenant_id})
            -[r]->
            (target:CanonicalConcept {tenant_id: $tenant_id})
            RETURN type(r) as relation_type, properties(r) as metadata,
                   target.canonical_id as target_id, target.canonical_name as target_name
            """
        elif direction == "incoming":
            query = """
            MATCH (source:CanonicalConcept {tenant_id: $tenant_id})
            -[r]->
            (target:CanonicalConcept {canonical_id: $concept_id, tenant_id: $tenant_id})
            RETURN type(r) as relation_type, properties(r) as metadata,
                   source.canonical_id as source_id, source.canonical_name as source_name
            """
        else:  # both
            query = """
            MATCH (source:CanonicalConcept {canonical_id: $concept_id, tenant_id: $tenant_id})
            -[r]->
            (target:CanonicalConcept {tenant_id: $tenant_id})
            RETURN 'outgoing' as direction, type(r) as relation_type,
                   properties(r) as metadata, target.canonical_id as other_id,
                   target.canonical_name as other_name
            UNION
            MATCH (source:CanonicalConcept {tenant_id: $tenant_id})
            -[r]->
            (target:CanonicalConcept {canonical_id: $concept_id, tenant_id: $tenant_id})
            RETURN 'incoming' as direction, type(r) as relation_type,
                   properties(r) as metadata, source.canonical_id as other_id,
                   source.canonical_name as other_name
            """

        result = self._execute_query(
            query,
            concept_id=concept_id,
            tenant_id=self.tenant_id
        )

        return [dict(record) for record in result] if result else []
