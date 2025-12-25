"""
Phase 2.8+ - UnresolvedMention Writer for Neo4j

Writes UnresolvedMention nodes to Neo4j for entities mentioned in text
but not found in the concept catalogue.

These mentions can later be promoted to CanonicalConcepts if they appear frequently.

Author: Claude Code
Date: 2025-12-21
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ulid import ULID

from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.config.settings import get_settings
from knowbase.relations.llm_relation_extractor import UnresolvedMention

logger = logging.getLogger(__name__)


class UnresolvedMentionWriter:
    """
    Writes UnresolvedMention nodes to Neo4j.

    Implements:
    - MERGE for deduplication (same mention_text + tenant_id)
    - Occurrence counting (increments if mention already exists)
    - Status tracking (pending | promoted | rejected)
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
            "errors": 0
        }

    def _execute_query(self, query: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Execute a Cypher query using the Neo4j driver session.

        Args:
            query: Cypher query string
            params: Query parameters

        Returns:
            List of record dicts
        """
        if not self.neo4j_client.driver:
            raise RuntimeError("Neo4j driver not connected")

        database = getattr(self.neo4j_client, 'database', 'neo4j')
        with self.neo4j_client.driver.session(database=database) as session:
            result = session.run(query, params)
            return [dict(record) for record in result]

    def write_mention(
        self,
        mention: UnresolvedMention,
        source_doc_id: str,
        source_chunk_id: str
    ) -> Optional[str]:
        """
        Write or update an UnresolvedMention in Neo4j.

        Uses MERGE to deduplicate on (mention_text, tenant_id).
        Increments occurrence_count if mention already exists.

        Args:
            mention: UnresolvedMention dataclass
            source_doc_id: Source document ID
            source_chunk_id: Source chunk ID

        Returns:
            mention_id if successful, None if error
        """
        mention_text = mention.mention.strip()

        if not mention_text:
            logger.warning("[UnresolvedMentionWriter] Empty mention text, skipping")
            return None

        # Generate ULID for new mentions
        new_mention_id = f"um_{ULID()}"

        query = """
        MERGE (um:UnresolvedMention {
            mention_text: $mention_text,
            tenant_id: $tenant_id
        })
        ON CREATE SET
            um.mention_id = $mention_id,
            um.context = $context,
            um.suggested_type = $suggested_type,
            um.source_doc_id = $source_doc_id,
            um.source_chunk_id = $source_chunk_id,
            um.occurrence_count = 1,
            um.status = "pending",
            um.created_at = datetime(),
            um.updated_at = datetime()
        ON MATCH SET
            um.occurrence_count = um.occurrence_count + 1,
            um.updated_at = datetime()
        RETURN um.mention_id AS id, um.occurrence_count AS count
        """

        try:
            result = self._execute_query(query, {
                "mention_text": mention_text,
                "tenant_id": self.tenant_id,
                "mention_id": new_mention_id,
                "context": mention.context[:500] if mention.context else "",
                "suggested_type": mention.suggested_type,
                "source_doc_id": source_doc_id,
                "source_chunk_id": source_chunk_id
            })

            if result:
                mention_id = result[0]["id"]
                count = result[0]["count"]

                if count == 1:
                    self._stats["created"] += 1
                    logger.debug(
                        f"[UnresolvedMentionWriter] Created: '{mention_text}' ({mention_id})"
                    )
                else:
                    self._stats["updated"] += 1
                    logger.debug(
                        f"[UnresolvedMentionWriter] Updated: '{mention_text}' (count={count})"
                    )

                return mention_id

            return None

        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"[UnresolvedMentionWriter] Error writing mention: {e}")
            return None

    def write_batch(
        self,
        mentions: List[UnresolvedMention],
        source_doc_id: str,
        source_chunk_id: str
    ) -> int:
        """
        Write multiple mentions.

        Args:
            mentions: List of UnresolvedMention
            source_doc_id: Source document ID
            source_chunk_id: Source chunk ID

        Returns:
            Number of successfully written mentions
        """
        written = 0
        for mention in mentions:
            if self.write_mention(mention, source_doc_id, source_chunk_id):
                written += 1

        return written

    def get_pending_mentions(
        self,
        min_occurrences: int = 1,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Get pending mentions for review.

        Args:
            min_occurrences: Minimum occurrence count
            limit: Maximum number of results

        Returns:
            List of mention dicts
        """
        query = """
        MATCH (um:UnresolvedMention {tenant_id: $tenant_id, status: "pending"})
        WHERE um.occurrence_count >= $min_occurrences
        RETURN um.mention_id AS mention_id,
               um.mention_text AS mention_text,
               um.context AS context,
               um.suggested_type AS suggested_type,
               um.occurrence_count AS occurrence_count,
               um.source_doc_id AS source_doc_id,
               um.created_at AS created_at
        ORDER BY um.occurrence_count DESC
        LIMIT $limit
        """

        return self._execute_query(query, {
            "tenant_id": self.tenant_id,
            "min_occurrences": min_occurrences,
            "limit": limit
        })

    def promote_to_concept(
        self,
        mention_id: str,
        concept_type: str = "UNKNOWN"
    ) -> Optional[str]:
        """
        Promote an UnresolvedMention to a CanonicalConcept.

        Creates a new CanonicalConcept and marks the mention as "promoted".

        Args:
            mention_id: ID of the mention to promote
            concept_type: Type for the new concept

        Returns:
            New canonical_id if successful, None if error
        """
        canonical_id = f"cc_{ULID()}"

        query = """
        MATCH (um:UnresolvedMention {mention_id: $mention_id, tenant_id: $tenant_id})
        WHERE um.status = "pending"
        SET um.status = "promoted",
            um.promoted_to = $canonical_id,
            um.updated_at = datetime()

        CREATE (cc:CanonicalConcept {
            canonical_id: $canonical_id,
            tenant_id: $tenant_id,
            canonical_name: um.mention_text,
            concept_type: $concept_type,
            surface_forms: [um.mention_text],
            total_occurrences: um.occurrence_count,
            schema_version: "2.8.0",
            created_at: datetime(),
            status: "active",
            source: "unresolved_promotion"
        })

        RETURN cc.canonical_id AS id
        """

        try:
            result = self._execute_query(query, {
                "mention_id": mention_id,
                "tenant_id": self.tenant_id,
                "canonical_id": canonical_id,
                "concept_type": concept_type
            })

            if result:
                logger.info(
                    f"[UnresolvedMentionWriter] Promoted {mention_id} → {canonical_id}"
                )
                return result[0]["id"]

            return None

        except Exception as e:
            logger.error(f"[UnresolvedMentionWriter] Error promoting mention: {e}")
            return None

    def reject_mention(self, mention_id: str) -> bool:
        """
        Mark a mention as rejected (won't be promoted).

        Args:
            mention_id: ID of the mention to reject

        Returns:
            True if successful
        """
        query = """
        MATCH (um:UnresolvedMention {mention_id: $mention_id, tenant_id: $tenant_id})
        SET um.status = "rejected",
            um.updated_at = datetime()
        RETURN um.mention_id AS id
        """

        try:
            result = self._execute_query(query, {
                "mention_id": mention_id,
                "tenant_id": self.tenant_id
            })
            return bool(result)

        except Exception as e:
            logger.error(f"[UnresolvedMentionWriter] Error rejecting mention: {e}")
            return False

    def get_stats(self) -> Dict[str, int]:
        """Get write statistics."""
        return self._stats.copy()

    def reset_stats(self) -> None:
        """Reset statistics."""
        self._stats = {
            "created": 0,
            "updated": 0,
            "errors": 0
        }


# Singleton-like access
_writer_instance: Optional[UnresolvedMentionWriter] = None


def get_unresolved_mention_writer(
    tenant_id: str = "default",
    **kwargs
) -> UnresolvedMentionWriter:
    """Get or create UnresolvedMentionWriter instance."""
    global _writer_instance
    if _writer_instance is None or _writer_instance.tenant_id != tenant_id:
        _writer_instance = UnresolvedMentionWriter(tenant_id=tenant_id, **kwargs)
    return _writer_instance
