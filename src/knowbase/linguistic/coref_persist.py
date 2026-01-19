"""
OSMOSE Linguistic Layer - Persistance Neo4j pour la coréférence

Ce module gère la persistance des structures de coréférence dans Neo4j:
- MentionSpan nodes
- CoreferenceChain nodes
- CorefDecision nodes (audit)
- Relations: HAS_MENTION, COREFERS_TO, MENTION_IN_DOCITEM, MATCHES_PROTOCONCEPT

Contraintes d'unicité et indexes conformes à l'ADR.

Ref: doc/ongoing/IMPLEMENTATION_PLAN_ADR_COMPLETION.md - Section 10.4
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime

from knowbase.common.clients.neo4j_client import Neo4jClient
from knowbase.linguistic.coref_models import (
    MentionSpan,
    CoreferenceChain,
    CorefDecision,
    CorefLink,
    CorefGraphResult,
)

logger = logging.getLogger(__name__)


class CorefPersistence:
    """
    Gestionnaire de persistance Neo4j pour la CorefGraph.

    Opérations:
    - Création des contraintes et indexes
    - Persistance des MentionSpan, CoreferenceChain, CorefDecision
    - Création des relations
    - Requêtes de lecture pour consommation
    """

    def __init__(
        self,
        neo4j_client: Optional[Neo4jClient] = None,
        tenant_id: str = "default",
    ):
        """
        Initialise le gestionnaire de persistance.

        Args:
            neo4j_client: Client Neo4j (créé si None)
            tenant_id: ID du tenant
        """
        self.neo4j_client = neo4j_client or Neo4jClient()
        self.tenant_id = tenant_id

    def ensure_constraints_and_indexes(self) -> bool:
        """
        Crée les contraintes et indexes Neo4j pour la coréférence.

        Returns:
            True si succès
        """
        queries = [
            # Contrainte d'unicité pour MentionSpan
            """
            CREATE CONSTRAINT mentionspan_unique IF NOT EXISTS
            FOR (m:MentionSpan)
            REQUIRE (m.tenant_id, m.doc_version_id, m.item_id, m.span_start, m.span_end) IS UNIQUE
            """,
            # Contrainte d'unicité pour CoreferenceChain
            """
            CREATE CONSTRAINT corefchain_unique IF NOT EXISTS
            FOR (c:CoreferenceChain)
            REQUIRE (c.tenant_id, c.chain_id) IS UNIQUE
            """,
            # Contrainte d'unicité pour CorefDecision
            """
            CREATE CONSTRAINT corefdecision_unique IF NOT EXISTS
            FOR (d:CorefDecision)
            REQUIRE (d.tenant_id, d.decision_id) IS UNIQUE
            """,
            # Index pour MentionSpan par document
            """
            CREATE INDEX mentionspan_doc IF NOT EXISTS
            FOR (m:MentionSpan) ON (m.tenant_id, m.doc_version_id)
            """,
            # Index pour MentionSpan par type
            """
            CREATE INDEX mentionspan_type IF NOT EXISTS
            FOR (m:MentionSpan) ON (m.tenant_id, m.mention_type)
            """,
            # Index pour CoreferenceChain par document
            """
            CREATE INDEX corefchain_doc IF NOT EXISTS
            FOR (c:CoreferenceChain) ON (c.tenant_id, c.doc_version_id)
            """,
            # Index pour CorefDecision par document
            """
            CREATE INDEX corefdecision_doc IF NOT EXISTS
            FOR (d:CorefDecision) ON (d.tenant_id, d.doc_version_id)
            """,
        ]

        try:
            for query in queries:
                self.neo4j_client.execute_query(query.strip())
            logger.info("[OSMOSE:CorefPersist] Constraints and indexes created")
            return True
        except Exception as e:
            logger.error(f"[OSMOSE:CorefPersist] Failed to create constraints: {e}")
            return False

    def persist_coref_graph(
        self,
        result: CorefGraphResult,
    ) -> Dict[str, int]:
        """
        Persiste un CorefGraphResult complet dans Neo4j.

        Args:
            result: Résultat de résolution de coréférence

        Returns:
            Dict avec les compteurs de création
        """
        stats = {
            "mention_spans": 0,
            "chains": 0,
            "links": 0,
            "decisions": 0,
        }

        try:
            # 1. Persister les MentionSpan
            for span in result.mention_spans:
                if self._create_mention_span(span):
                    stats["mention_spans"] += 1

            # 2. Persister les CoreferenceChain et relations HAS_MENTION
            for chain in result.chains:
                if self._create_chain_with_mentions(chain):
                    stats["chains"] += 1

            # 3. Persister les CorefLink (relations COREFERS_TO)
            for link in result.links:
                if self._create_coref_link(link):
                    stats["links"] += 1

            # 4. Persister les CorefDecision (audit)
            for decision in result.decisions:
                if self._create_coref_decision(decision):
                    stats["decisions"] += 1

            logger.info(
                f"[OSMOSE:CorefPersist] Persisted graph for {result.doc_id}: "
                f"{stats['mention_spans']} spans, {stats['chains']} chains, "
                f"{stats['links']} links, {stats['decisions']} decisions"
            )

        except Exception as e:
            logger.error(f"[OSMOSE:CorefPersist] Error persisting graph: {e}")

        return stats

    def _create_mention_span(self, span: MentionSpan) -> bool:
        """Crée un node MentionSpan."""
        query = """
        MERGE (m:MentionSpan {
            tenant_id: $tenant_id,
            doc_version_id: $doc_version_id,
            item_id: $docitem_id,
            span_start: $span_start,
            span_end: $span_end
        })
        ON CREATE SET
            m.doc_id = $doc_id,
            m.chunk_id = $chunk_id,
            m.surface = $surface,
            m.mention_type = $mention_type,
            m.lang = $lang,
            m.sentence_index = $sentence_index,
            m.mention_id = $mention_id,
            m.created_at = datetime($created_at)
        RETURN m.mention_id AS id
        """
        try:
            props = span.to_neo4j_props()
            result = self.neo4j_client.execute_query(query, **props)
            return len(result) > 0
        except Exception as e:
            logger.error(f"[OSMOSE:CorefPersist] Failed to create MentionSpan: {e}")
            return False

    def _create_chain_with_mentions(self, chain: CoreferenceChain) -> bool:
        """Crée un node CoreferenceChain et ses relations HAS_MENTION."""
        # Créer la chaîne
        create_chain_query = """
        MERGE (c:CoreferenceChain {
            tenant_id: $tenant_id,
            chain_id: $chain_id
        })
        ON CREATE SET
            c.doc_id = $doc_id,
            c.doc_version_id = $doc_version_id,
            c.method = $method,
            c.confidence = $confidence,
            c.created_at = datetime($created_at)
        RETURN c.chain_id AS id
        """
        try:
            props = chain.to_neo4j_props()
            self.neo4j_client.execute_query(create_chain_query, **props)

            # Créer les relations HAS_MENTION
            for mention_id in chain.mention_ids:
                role = "REPRESENTATIVE" if mention_id == chain.representative_mention_id else "MEMBER"
                self._create_has_mention_relation(
                    chain.chain_id,
                    mention_id,
                    role,
                    self.tenant_id
                )

            return True
        except Exception as e:
            logger.error(f"[OSMOSE:CorefPersist] Failed to create chain: {e}")
            return False

    def _create_has_mention_relation(
        self,
        chain_id: str,
        mention_id: str,
        role: str,
        tenant_id: str
    ) -> bool:
        """Crée une relation HAS_MENTION entre chaîne et mention."""
        query = """
        MATCH (c:CoreferenceChain {tenant_id: $tenant_id, chain_id: $chain_id})
        MATCH (m:MentionSpan {tenant_id: $tenant_id, mention_id: $mention_id})
        MERGE (c)-[r:HAS_MENTION]->(m)
        ON CREATE SET r.role = $role
        RETURN r
        """
        try:
            result = self.neo4j_client.execute_query(
                query,
                tenant_id=tenant_id,
                chain_id=chain_id,
                mention_id=mention_id,
                role=role
            )
            return len(result) > 0
        except Exception as e:
            logger.error(f"[OSMOSE:CorefPersist] Failed to create HAS_MENTION: {e}")
            return False

    def _create_coref_link(self, link: CorefLink) -> bool:
        """Crée une relation COREFERS_TO entre deux MentionSpan."""
        query = """
        MATCH (source:MentionSpan {tenant_id: $tenant_id, mention_id: $source_id})
        MATCH (target:MentionSpan {tenant_id: $tenant_id, mention_id: $target_id})
        MERGE (source)-[r:COREFERS_TO]->(target)
        ON CREATE SET
            r.method = $method,
            r.confidence = $confidence,
            r.scope = $scope,
            r.window_chars = $window_chars,
            r.link_id = $link_id,
            r.created_at = datetime($created_at)
        RETURN r
        """
        try:
            props = link.to_neo4j_props()
            result = self.neo4j_client.execute_query(
                query,
                tenant_id=self.tenant_id,
                source_id=link.source_mention_id,
                target_id=link.target_mention_id,
                **props
            )
            return len(result) > 0
        except Exception as e:
            logger.error(f"[OSMOSE:CorefPersist] Failed to create COREFERS_TO: {e}")
            return False

    def _create_coref_decision(self, decision: CorefDecision) -> bool:
        """Crée un node CorefDecision (audit)."""
        query = """
        MERGE (d:CorefDecision {
            tenant_id: $tenant_id,
            decision_id: $decision_id
        })
        ON CREATE SET
            d.doc_version_id = $doc_version_id,
            d.mention_span_key = $mention_span_key,
            d.candidate_count = $candidate_count,
            d.chosen_candidate_key = $chosen_candidate_key,
            d.decision_type = $decision_type,
            d.confidence = $confidence,
            d.method = $method,
            d.reason_code = $reason_code,
            d.reason_detail = $reason_detail,
            d.created_at = datetime($created_at)
        RETURN d.decision_id AS id
        """
        try:
            props = decision.to_neo4j_props()
            result = self.neo4j_client.execute_query(query, **props)
            return len(result) > 0
        except Exception as e:
            logger.error(f"[OSMOSE:CorefPersist] Failed to create CorefDecision: {e}")
            return False

    def create_mention_in_docitem_relation(
        self,
        mention_id: str,
        docitem_id: str,
    ) -> bool:
        """Crée la relation MENTION_IN_DOCITEM."""
        query = """
        MATCH (m:MentionSpan {tenant_id: $tenant_id, mention_id: $mention_id})
        MATCH (d:DocItem {tenant_id: $tenant_id, item_id: $docitem_id})
        MERGE (m)-[r:MENTION_IN_DOCITEM]->(d)
        RETURN r
        """
        try:
            result = self.neo4j_client.execute_query(
                query,
                tenant_id=self.tenant_id,
                mention_id=mention_id,
                docitem_id=docitem_id
            )
            return len(result) > 0
        except Exception as e:
            logger.error(f"[OSMOSE:CorefPersist] Failed to create MENTION_IN_DOCITEM: {e}")
            return False

    def create_mention_in_chunk_relation(
        self,
        mention_id: str,
        chunk_id: str,
    ) -> bool:
        """Crée la relation MENTION_IN_CHUNK."""
        query = """
        MATCH (m:MentionSpan {tenant_id: $tenant_id, mention_id: $mention_id})
        MATCH (c:TypeAwareChunk {tenant_id: $tenant_id, chunk_id: $chunk_id})
        MERGE (m)-[r:MENTION_IN_CHUNK]->(c)
        RETURN r
        """
        try:
            result = self.neo4j_client.execute_query(
                query,
                tenant_id=self.tenant_id,
                mention_id=mention_id,
                chunk_id=chunk_id
            )
            return len(result) > 0
        except Exception as e:
            logger.error(f"[OSMOSE:CorefPersist] Failed to create MENTION_IN_CHUNK: {e}")
            return False

    def create_matches_protoconcept_relation(
        self,
        mention_id: str,
        concept_id: str,
        confidence: float = 0.0,
        method: str = "lexical_match",
    ) -> bool:
        """
        Crée la relation MATCHES_PROTOCONCEPT.

        NOTE GOUVERNANCE: Ce lien exprime un alignement lexical/ancré,
        PAS une identité ontologique. Voir ADR Section 10.4.2.
        """
        query = """
        MATCH (m:MentionSpan {tenant_id: $tenant_id, mention_id: $mention_id})
        MATCH (p:ProtoConcept {tenant_id: $tenant_id, concept_id: $concept_id})
        MERGE (m)-[r:MATCHES_PROTOCONCEPT]->(p)
        ON CREATE SET
            r.confidence = $confidence,
            r.method = $method,
            r.created_at = datetime()
        RETURN r
        """
        try:
            result = self.neo4j_client.execute_query(
                query,
                tenant_id=self.tenant_id,
                mention_id=mention_id,
                concept_id=concept_id,
                confidence=confidence,
                method=method
            )
            return len(result) > 0
        except Exception as e:
            logger.error(f"[OSMOSE:CorefPersist] Failed to create MATCHES_PROTOCONCEPT: {e}")
            return False

    # =========================================================================
    # Requêtes de lecture (pour consommation par Pass 1/Pass 2+)
    # =========================================================================

    def get_coref_graph_for_document(
        self,
        doc_version_id: str,
    ) -> Dict[str, Any]:
        """
        Récupère la CorefGraph pour un document.

        Args:
            doc_version_id: ID de version du document

        Returns:
            Dict avec chains, mentions, et links
        """
        # Récupérer les chaînes
        chains_query = """
        MATCH (c:CoreferenceChain {tenant_id: $tenant_id, doc_version_id: $doc_version_id})
        RETURN c
        """
        chains_result = self.neo4j_client.execute_query(
            chains_query,
            tenant_id=self.tenant_id,
            doc_version_id=doc_version_id
        )

        # Récupérer les mentions
        mentions_query = """
        MATCH (m:MentionSpan {tenant_id: $tenant_id, doc_version_id: $doc_version_id})
        RETURN m
        """
        mentions_result = self.neo4j_client.execute_query(
            mentions_query,
            tenant_id=self.tenant_id,
            doc_version_id=doc_version_id
        )

        # Récupérer les liens COREFERS_TO
        links_query = """
        MATCH (m1:MentionSpan {tenant_id: $tenant_id, doc_version_id: $doc_version_id})
              -[r:COREFERS_TO]->(m2:MentionSpan)
        RETURN m1.mention_id AS source, m2.mention_id AS target,
               r.confidence AS confidence, r.scope AS scope
        """
        links_result = self.neo4j_client.execute_query(
            links_query,
            tenant_id=self.tenant_id,
            doc_version_id=doc_version_id
        )

        return {
            "chains": [dict(r["c"]) for r in chains_result] if chains_result else [],
            "mentions": [dict(r["m"]) for r in mentions_result] if mentions_result else [],
            "links": [dict(r) for r in links_result] if links_result else [],
        }

    def get_antecedent_for_mention(
        self,
        mention_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Récupère l'antécédent d'une mention (via COREFERS_TO).

        Utilisé par l'extracteur de relations pour résolution runtime.

        Args:
            mention_id: ID de la mention (pronom)

        Returns:
            Dict avec les infos de l'antécédent ou None
        """
        query = """
        MATCH (m:MentionSpan {tenant_id: $tenant_id, mention_id: $mention_id})
              -[r:COREFERS_TO]->(antecedent:MentionSpan)
        RETURN antecedent.mention_id AS mention_id,
               antecedent.surface AS surface,
               antecedent.span_start AS span_start,
               antecedent.span_end AS span_end,
               r.confidence AS confidence
        LIMIT 1
        """
        try:
            result = self.neo4j_client.execute_query(
                query,
                tenant_id=self.tenant_id,
                mention_id=mention_id
            )
            if result:
                return dict(result[0])
            return None
        except Exception as e:
            logger.error(f"[OSMOSE:CorefPersist] Failed to get antecedent: {e}")
            return None

    def get_matching_protoconcept(
        self,
        mention_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Récupère le ProtoConcept associé à une mention (via MATCHES_PROTOCONCEPT).

        NOTE GOUVERNANCE: Ce lien est un alignement lexical/ancré,
        pas une identité ontologique.

        Args:
            mention_id: ID de la mention

        Returns:
            Dict avec les infos du ProtoConcept ou None
        """
        query = """
        MATCH (m:MentionSpan {tenant_id: $tenant_id, mention_id: $mention_id})
              -[r:MATCHES_PROTOCONCEPT]->(p:ProtoConcept)
        RETURN p.concept_id AS concept_id,
               p.concept_name AS label,
               p.entity_type AS entity_type,
               r.confidence AS match_confidence
        LIMIT 1
        """
        try:
            result = self.neo4j_client.execute_query(
                query,
                tenant_id=self.tenant_id,
                mention_id=mention_id
            )
            if result:
                return dict(result[0])
            return None
        except Exception as e:
            logger.error(f"[OSMOSE:CorefPersist] Failed to get ProtoConcept: {e}")
            return None

    def check_coref_exists_for_document(
        self,
        doc_version_id: str,
    ) -> bool:
        """
        Vérifie si la coréférence a déjà été calculée pour un document.

        Utilisé pour l'idempotence (skip_if_exists).

        Args:
            doc_version_id: ID de version du document

        Returns:
            True si des MentionSpan existent pour ce document
        """
        query = """
        MATCH (m:MentionSpan {tenant_id: $tenant_id, doc_version_id: $doc_version_id})
        RETURN count(m) AS count
        LIMIT 1
        """
        try:
            result = self.neo4j_client.execute_query(
                query,
                tenant_id=self.tenant_id,
                doc_version_id=doc_version_id
            )
            if result:
                return result[0]["count"] > 0
            return False
        except Exception as e:
            logger.error(f"[OSMOSE:CorefPersist] Failed to check existence: {e}")
            return False

    def delete_coref_for_document(
        self,
        doc_version_id: str,
    ) -> int:
        """
        Supprime toutes les données de coréférence pour un document.

        Args:
            doc_version_id: ID de version du document

        Returns:
            Nombre de nodes supprimés
        """
        queries = [
            # Supprimer les CorefDecision
            """
            MATCH (d:CorefDecision {tenant_id: $tenant_id, doc_version_id: $doc_version_id})
            DETACH DELETE d
            RETURN count(d) AS count
            """,
            # Supprimer les CoreferenceChain
            """
            MATCH (c:CoreferenceChain {tenant_id: $tenant_id, doc_version_id: $doc_version_id})
            DETACH DELETE c
            RETURN count(c) AS count
            """,
            # Supprimer les MentionSpan
            """
            MATCH (m:MentionSpan {tenant_id: $tenant_id, doc_version_id: $doc_version_id})
            DETACH DELETE m
            RETURN count(m) AS count
            """,
        ]

        total_deleted = 0
        try:
            for query in queries:
                result = self.neo4j_client.execute_query(
                    query,
                    tenant_id=self.tenant_id,
                    doc_version_id=doc_version_id
                )
                if result:
                    total_deleted += result[0]["count"]

            logger.info(
                f"[OSMOSE:CorefPersist] Deleted {total_deleted} nodes "
                f"for doc_version_id={doc_version_id}"
            )
        except Exception as e:
            logger.error(f"[OSMOSE:CorefPersist] Failed to delete: {e}")

        return total_deleted
