"""
Phase 2.8/2.10/2.12 - CanonicalRelation Writer for Neo4j

Persists CanonicalRelation nodes to Neo4j with MERGE for upsert.
Creates typed edges for ALL relations with maturity metadata (agnostic architecture).
Links to RawAssertions via AGGREGATES edges.

Architecture: KG Agnostique (voir doc/ongoing/KG_AGNOSTIC_ARCHITECTURE.md)
- Couche 1-2 (Stockage/Topologie): Toutes les arêtes sont créées
- Couche 3 (Politique): Filtrage externe selon domaine/tenant

Author: Claude Code
Date: 2025-12-24
Updated: 2025-12-26 - Architecture agnostique, arêtes pour toutes maturités
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.config.settings import get_settings
from knowbase.relations.types import (
    CanonicalRelation,
    RelationMaturity,
    RelationType,
    RelationStatus,
)

logger = logging.getLogger(__name__)


class CanonicalRelationWriter:
    """
    Writes CanonicalRelation nodes to Neo4j.

    Architecture Agnostique (Couches 1-2):
    - Stocke TOUTES les relations indépendamment de leur maturité
    - Crée des arêtes typées navigables pour TOUTES les relations
    - Les métadonnées (maturity, confidence) permettent le filtrage politique

    Implements:
    - MERGE for upsert (create or update)
    - AGGREGATES edges linking to RawAssertions
    - Typed direct edges for ALL relations (REQUIRES, USES, etc.) with metadata
    - RELATES_FROM/RELATES_TO edges to CanonicalConcepts
    """

    def __init__(
        self,
        neo4j_client: Optional[Neo4jClient] = None,
        tenant_id: str = "default"
    ):
        """
        Initialize writer.

        Args:
            neo4j_client: Neo4j client instance (creates one if not provided)
            tenant_id: Tenant ID for multi-tenancy
        """
        if neo4j_client is None:
            settings = get_settings()
            neo4j_client = Neo4jClient(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password
            )
        self.neo4j_client = neo4j_client
        self.tenant_id = tenant_id

        self._stats = {
            "created": 0,
            "updated": 0,
            "aggregates_edges": 0,
            "typed_edges": 0,
            "concept_edges": 0,
            "errors": 0
        }

    def _execute_query(self, query: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Execute a Cypher query."""
        if not self.neo4j_client.driver:
            raise RuntimeError("Neo4j driver not connected")

        database = getattr(self.neo4j_client, 'database', 'neo4j')
        with self.neo4j_client.driver.session(database=database) as session:
            result = session.run(query, params)
            return [dict(record) for record in result]

    def write_relation(self, relation: CanonicalRelation) -> str:
        """
        Write a CanonicalRelation to Neo4j.

        Uses MERGE to create or update based on canonical_relation_id.

        Args:
            relation: CanonicalRelation instance

        Returns:
            canonical_relation_id
        """
        try:
            # MERGE the canonical relation node
            self._merge_relation_node(relation)

            # Link to subject and object concepts
            self._link_to_concepts(relation)

            # Link to supporting RawAssertions
            self._link_to_raw_assertions(relation)

            # Create typed edge for ALL relations (architecture agnostique)
            # La maturité est stockée sur l'arête pour filtrage politique ultérieur
            self._create_typed_edge(relation)

            logger.debug(f"[CanonicalRelationWriter] Written: {relation.canonical_relation_id}")
            return relation.canonical_relation_id

        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"[CanonicalRelationWriter] Error writing relation: {e}")
            raise

    def _merge_relation_node(self, relation: CanonicalRelation) -> None:
        """Merge CanonicalRelation node (upsert)."""
        query = """
        MERGE (cr:CanonicalRelation {canonical_relation_id: $canonical_relation_id})
        ON CREATE SET
            cr.tenant_id = $tenant_id,
            cr.relation_type = $relation_type,
            cr.predicate_norm = $predicate_norm,
            cr.subject_concept_id = $subject_concept_id,
            cr.object_concept_id = $object_concept_id,
            cr.distinct_documents = $distinct_documents,
            cr.distinct_chunks = $distinct_chunks,
            cr.total_assertions = $total_assertions,
            cr.first_seen_utc = datetime($first_seen_utc),
            cr.last_seen_utc = datetime($last_seen_utc),
            cr.extractor_versions = $extractor_versions,
            cr.predicate_profile_json = $predicate_profile_json,
            cr.confidence_mean = $confidence_mean,
            cr.confidence_p50 = $confidence_p50,
            cr.quality_score = $quality_score,
            cr.maturity = $maturity,
            cr.status = $status,
            cr.mapping_version = $mapping_version,
            cr.last_rebuilt_at = datetime($last_rebuilt_at),
            cr._created = true
        ON MATCH SET
            cr.distinct_documents = $distinct_documents,
            cr.distinct_chunks = $distinct_chunks,
            cr.total_assertions = $total_assertions,
            cr.last_seen_utc = datetime($last_seen_utc),
            cr.extractor_versions = $extractor_versions,
            cr.predicate_profile_json = $predicate_profile_json,
            cr.confidence_mean = $confidence_mean,
            cr.confidence_p50 = $confidence_p50,
            cr.quality_score = $quality_score,
            cr.maturity = $maturity,
            cr.status = $status,
            cr.mapping_version = $mapping_version,
            cr.last_rebuilt_at = datetime($last_rebuilt_at),
            cr._created = false
        RETURN cr._created AS created
        """

        # Serialize predicate profile
        predicate_profile_data = {
            "top_predicates_raw": relation.predicate_profile.top_predicates_raw,
            "predicate_cluster_id": relation.predicate_profile.predicate_cluster_id,
            "cluster_label_confidence": relation.predicate_profile.cluster_label_confidence
        }

        # Handle enum values
        relation_type_str = relation.relation_type.value if isinstance(relation.relation_type, RelationType) else str(relation.relation_type)
        maturity_str = relation.maturity.value if isinstance(relation.maturity, RelationMaturity) else str(relation.maturity)
        status_str = relation.status.value if isinstance(relation.status, RelationStatus) else str(relation.status)

        params = {
            "canonical_relation_id": relation.canonical_relation_id,
            "tenant_id": relation.tenant_id,
            "relation_type": relation_type_str,
            "predicate_norm": relation.predicate_norm,
            "subject_concept_id": relation.subject_concept_id,
            "object_concept_id": relation.object_concept_id,
            "distinct_documents": relation.distinct_documents,
            "distinct_chunks": relation.distinct_chunks,
            "total_assertions": relation.total_assertions,
            "first_seen_utc": relation.first_seen_utc.isoformat() if relation.first_seen_utc else datetime.utcnow().isoformat(),
            "last_seen_utc": relation.last_seen_utc.isoformat() if relation.last_seen_utc else datetime.utcnow().isoformat(),
            "extractor_versions": relation.extractor_versions,
            "predicate_profile_json": json.dumps(predicate_profile_data),
            "confidence_mean": relation.confidence_mean,
            "confidence_p50": relation.confidence_p50,
            "quality_score": relation.quality_score,
            "maturity": maturity_str,
            "status": status_str,
            "mapping_version": relation.mapping_version,
            "last_rebuilt_at": relation.last_rebuilt_at.isoformat() if relation.last_rebuilt_at else datetime.utcnow().isoformat()
        }

        results = self._execute_query(query, params)
        if results and results[0].get("created"):
            self._stats["created"] += 1
        else:
            self._stats["updated"] += 1

    def _link_to_concepts(self, relation: CanonicalRelation) -> None:
        """Create RELATES_FROM and RELATES_TO edges to CanonicalConcepts."""
        # RELATES_FROM edge (CanonicalRelation → Subject CanonicalConcept)
        query_from = """
        MATCH (cr:CanonicalRelation {canonical_relation_id: $canonical_relation_id})
        MATCH (c:CanonicalConcept {canonical_id: $subject_concept_id, tenant_id: $tenant_id})
        MERGE (cr)-[:RELATES_FROM]->(c)
        """
        self._execute_query(query_from, {
            "canonical_relation_id": relation.canonical_relation_id,
            "subject_concept_id": relation.subject_concept_id,
            "tenant_id": relation.tenant_id
        })

        # RELATES_TO edge (CanonicalRelation → Object CanonicalConcept)
        query_to = """
        MATCH (cr:CanonicalRelation {canonical_relation_id: $canonical_relation_id})
        MATCH (c:CanonicalConcept {canonical_id: $object_concept_id, tenant_id: $tenant_id})
        MERGE (cr)-[:RELATES_TO]->(c)
        """
        self._execute_query(query_to, {
            "canonical_relation_id": relation.canonical_relation_id,
            "object_concept_id": relation.object_concept_id,
            "tenant_id": relation.tenant_id
        })

        self._stats["concept_edges"] += 2

    def _link_to_raw_assertions(self, relation: CanonicalRelation) -> None:
        """Create AGGREGATES edges from CanonicalRelation to RawAssertions."""
        relation_type_str = relation.relation_type.value if isinstance(relation.relation_type, RelationType) else str(relation.relation_type)

        query = """
        MATCH (cr:CanonicalRelation {canonical_relation_id: $canonical_relation_id})
        MATCH (ra:RawAssertion)
        WHERE ra.tenant_id = $tenant_id
          AND ra.subject_concept_id = $subject_concept_id
          AND ra.object_concept_id = $object_concept_id
          AND ra.relation_type = $relation_type
        MERGE (cr)-[:AGGREGATES]->(ra)
        RETURN count(ra) AS count
        """

        results = self._execute_query(query, {
            "canonical_relation_id": relation.canonical_relation_id,
            "tenant_id": relation.tenant_id,
            "subject_concept_id": relation.subject_concept_id,
            "object_concept_id": relation.object_concept_id,
            "relation_type": relation_type_str
        })

        if results:
            self._stats["aggregates_edges"] += results[0].get("count", 0)

    def _create_typed_edge(self, relation: CanonicalRelation) -> None:
        """
        Create typed direct edge between concepts for ALL relations.

        Architecture Agnostique:
        - L'arête est TOUJOURS créée (Couche 2: Topologie)
        - Les métadonnées permettent le filtrage politique (Couche 3)
        - La visibilité finale dépend du domaine/tenant

        Métadonnées sur l'arête:
        - canonical_relation_id: Lien vers le nœud CanonicalRelation (audit)
        - maturity: CANDIDATE | VALIDATED | CONTEXT_DEPENDENT | etc.
        - confidence: Score de confiance (0.0 - 1.0)
        - source_count: Nombre de documents sources
        - first_seen / last_seen: Timestamps de provenance

        For example: (Subject)-[:REQUIRES {maturity: "CANDIDATE", confidence: 0.87}]->(Object)
        """
        relation_type_str = relation.relation_type.value if isinstance(relation.relation_type, RelationType) else str(relation.relation_type)
        maturity_str = relation.maturity.value if isinstance(relation.maturity, RelationMaturity) else str(relation.maturity)

        # Build edge with full metadata for policy filtering
        # NOTE: RETURN is required for the Neo4j Python driver to commit the transaction
        query = f"""
        MATCH (s:CanonicalConcept {{canonical_id: $subject_id, tenant_id: $tenant_id}})
        MATCH (o:CanonicalConcept {{canonical_id: $object_id, tenant_id: $tenant_id}})
        MERGE (s)-[r:{relation_type_str} {{canonical_relation_id: $canonical_relation_id}}]->(o)
        SET r.maturity = $maturity,
            r.confidence = $confidence,
            r.source_count = $source_count,
            r.first_seen = $first_seen,
            r.last_seen = $last_seen,
            r.predicate_norm = $predicate_norm,
            r.last_updated = datetime()
        RETURN count(r) AS created
        """

        try:
            self._execute_query(query, {
                "subject_id": relation.subject_concept_id,
                "object_id": relation.object_concept_id,
                "tenant_id": relation.tenant_id,
                "canonical_relation_id": relation.canonical_relation_id,
                "maturity": maturity_str,
                "confidence": relation.confidence_p50,
                "source_count": relation.distinct_documents,
                "first_seen": relation.first_seen_utc.isoformat() if relation.first_seen_utc else datetime.utcnow().isoformat(),
                "last_seen": relation.last_seen_utc.isoformat() if relation.last_seen_utc else datetime.utcnow().isoformat(),
                "predicate_norm": relation.predicate_norm
            })
            self._stats["typed_edges"] += 1
        except Exception as e:
            # If typed edge fails (e.g., invalid type name), log but don't fail
            logger.warning(f"[CanonicalRelationWriter] Could not create typed edge {relation_type_str}: {e}")

    def write_batch(self, relations: List[CanonicalRelation]) -> List[str]:
        """
        Write multiple CanonicalRelations.

        Args:
            relations: List of CanonicalRelation instances

        Returns:
            List of written canonical_relation_ids
        """
        written_ids = []
        for relation in relations:
            try:
                relation_id = self.write_relation(relation)
                written_ids.append(relation_id)
            except Exception as e:
                logger.error(f"[CanonicalRelationWriter] Error writing relation {relation.canonical_relation_id}: {e}")

        logger.info(
            f"[CanonicalRelationWriter] Written {len(written_ids)}/{len(relations)} relations "
            f"(created={self._stats['created']}, updated={self._stats['updated']}, "
            f"typed_edges={self._stats['typed_edges']})"
        )

        return written_ids

    def get_stats(self) -> Dict[str, int]:
        """Get write statistics."""
        return self._stats.copy()

    def reset_stats(self) -> None:
        """Reset statistics."""
        self._stats = {
            "created": 0,
            "updated": 0,
            "aggregates_edges": 0,
            "typed_edges": 0,
            "concept_edges": 0,
            "errors": 0
        }


# Singleton-like access
_writer_instance: Optional[CanonicalRelationWriter] = None


def get_canonical_relation_writer(
    tenant_id: str = "default",
    **kwargs
) -> CanonicalRelationWriter:
    """Get or create CanonicalRelationWriter instance."""
    global _writer_instance
    if _writer_instance is None or _writer_instance.tenant_id != tenant_id:
        _writer_instance = CanonicalRelationWriter(tenant_id=tenant_id, **kwargs)
    return _writer_instance
