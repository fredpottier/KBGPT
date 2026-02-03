# src/knowbase/claimfirst/persistence/claim_persister.py
"""
ClaimPersister - Persistance Neo4j pour le pipeline Claim-First.

Persiste tous les artefacts du pipeline:
- Passages
- Claims
- Entities
- Facets
- ClaimClusters
- Relations (SUPPORTED_BY, ABOUT, HAS_FACET, IN_CLUSTER, etc.)

Utilise MERGE pour l'idempotence.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from knowbase.claimfirst.models.claim import Claim
from knowbase.claimfirst.models.entity import Entity
from knowbase.claimfirst.models.facet import Facet
from knowbase.claimfirst.models.passage import Passage
from knowbase.claimfirst.models.result import ClaimFirstResult, ClaimCluster, ClaimRelation

logger = logging.getLogger(__name__)


class ClaimPersister:
    """
    Persiste les résultats du pipeline Claim-First dans Neo4j.

    Utilise MERGE pour garantir l'idempotence.
    """

    def __init__(self, driver, tenant_id: str = "default"):
        """
        Initialise le persister.

        Args:
            driver: Neo4j driver
            tenant_id: Tenant ID par défaut
        """
        self.driver = driver
        self.tenant_id = tenant_id

        self.stats = {
            "passages_created": 0,
            "claims_created": 0,
            "entities_created": 0,
            "facets_created": 0,
            "clusters_created": 0,
            "relations_created": 0,
        }

    def persist(self, result: ClaimFirstResult) -> dict:
        """
        Persiste un résultat complet du pipeline.

        Args:
            result: ClaimFirstResult à persister

        Returns:
            Statistiques de persistance
        """
        with self.driver.session() as session:
            # 1. Passages
            for passage in result.passages:
                self._persist_passage(session, passage)

            # 2. Claims
            for claim in result.claims:
                self._persist_claim(session, claim)

            # 3. Entities
            for entity in result.entities:
                self._persist_entity(session, entity)

            # 4. Facets
            for facet in result.facets:
                self._persist_facet(session, facet)

            # 5. ClaimClusters
            for cluster in result.clusters:
                self._persist_cluster(session, cluster)

            # 6. Relations Passage → Document (FROM)
            self._persist_passage_document_links(session, result.passages, result.doc_id)

            # 7. Relations Claim → Passage (SUPPORTED_BY)
            for claim_id, passage_id in result.claim_passage_links:
                self._persist_supported_by(session, claim_id, passage_id)

            # 8. Relations Claim → Entity (ABOUT)
            for claim_id, entity_id in result.claim_entity_links:
                self._persist_about(session, claim_id, entity_id)

            # 9. Relations Claim → Facet (HAS_FACET)
            for claim_id, facet_id in result.claim_facet_links:
                self._persist_has_facet(session, claim_id, facet_id)

            # 10. Relations Claim → Cluster (IN_CLUSTER)
            for claim_id, cluster_id in result.claim_cluster_links:
                self._persist_in_cluster(session, claim_id, cluster_id)

            # 11. Relations inter-claims (CONTRADICTS, REFINES, QUALIFIES)
            for relation in result.relations:
                self._persist_claim_relation(session, relation)

        logger.info(
            f"[OSMOSE:ClaimPersister] Persisted: "
            f"{self.stats['passages_created']} passages, "
            f"{self.stats['claims_created']} claims, "
            f"{self.stats['entities_created']} entities, "
            f"{self.stats['facets_created']} facets, "
            f"{self.stats['clusters_created']} clusters, "
            f"{self.stats['relations_created']} relations"
        )

        return dict(self.stats)

    def _persist_passage(self, session, passage: Passage) -> None:
        """Persiste un Passage."""
        props = passage.to_neo4j_properties()
        query = """
        MERGE (p:Passage {passage_id: $passage_id})
        SET p += $props
        """
        session.run(query, passage_id=passage.passage_id, props=props)
        self.stats["passages_created"] += 1

    def _persist_claim(self, session, claim: Claim) -> None:
        """Persiste une Claim."""
        props = claim.to_neo4j_properties()
        query = """
        MERGE (c:Claim {claim_id: $claim_id})
        SET c += $props
        """
        session.run(query, claim_id=claim.claim_id, props=props)
        self.stats["claims_created"] += 1

    def _persist_entity(self, session, entity: Entity) -> None:
        """Persiste une Entity (MERGE sur normalized_name)."""
        props = entity.to_neo4j_properties()
        query = """
        MERGE (e:Entity {normalized_name: $normalized_name, tenant_id: $tenant_id})
        ON CREATE SET e += $props
        ON MATCH SET e.mention_count = e.mention_count + 1
        """
        session.run(
            query,
            normalized_name=entity.normalized_name,
            tenant_id=entity.tenant_id,
            props=props,
        )
        self.stats["entities_created"] += 1

    def _persist_facet(self, session, facet: Facet) -> None:
        """Persiste une Facet."""
        props = facet.to_neo4j_properties()
        query = """
        MERGE (f:Facet {facet_id: $facet_id})
        SET f += $props
        """
        session.run(query, facet_id=facet.facet_id, props=props)
        self.stats["facets_created"] += 1

    def _persist_cluster(self, session, cluster: ClaimCluster) -> None:
        """Persiste un ClaimCluster."""
        props = cluster.to_neo4j_properties()
        query = """
        MERGE (cc:ClaimCluster {cluster_id: $cluster_id})
        SET cc += $props
        """
        session.run(query, cluster_id=cluster.cluster_id, props=props)
        self.stats["clusters_created"] += 1

    def _persist_passage_document_links(
        self,
        session,
        passages: List[Passage],
        doc_id: str,
    ) -> None:
        """Crée les relations Passage → Document (FROM)."""
        query = """
        MATCH (p:Passage {passage_id: $passage_id})
        MATCH (d:Document {doc_id: $doc_id})
        MERGE (p)-[:FROM]->(d)
        """
        for passage in passages:
            session.run(query, passage_id=passage.passage_id, doc_id=doc_id)
            self.stats["relations_created"] += 1

    def _persist_supported_by(
        self,
        session,
        claim_id: str,
        passage_id: str,
    ) -> None:
        """Crée la relation Claim -[:SUPPORTED_BY]-> Passage."""
        query = """
        MATCH (c:Claim {claim_id: $claim_id})
        MATCH (p:Passage {passage_id: $passage_id})
        MERGE (c)-[:SUPPORTED_BY]->(p)
        """
        session.run(query, claim_id=claim_id, passage_id=passage_id)
        self.stats["relations_created"] += 1

    def _persist_about(
        self,
        session,
        claim_id: str,
        entity_id: str,
    ) -> None:
        """
        Crée la relation Claim -[:ABOUT]-> Entity.

        Note: Pas de {role} en V1 (INV-4).
        """
        query = """
        MATCH (c:Claim {claim_id: $claim_id})
        MATCH (e:Entity {entity_id: $entity_id})
        MERGE (c)-[:ABOUT]->(e)
        """
        session.run(query, claim_id=claim_id, entity_id=entity_id)
        self.stats["relations_created"] += 1

    def _persist_has_facet(
        self,
        session,
        claim_id: str,
        facet_id: str,
    ) -> None:
        """Crée la relation Claim -[:HAS_FACET]-> Facet."""
        query = """
        MATCH (c:Claim {claim_id: $claim_id})
        MATCH (f:Facet {facet_id: $facet_id})
        MERGE (c)-[:HAS_FACET]->(f)
        """
        session.run(query, claim_id=claim_id, facet_id=facet_id)
        self.stats["relations_created"] += 1

    def _persist_in_cluster(
        self,
        session,
        claim_id: str,
        cluster_id: str,
    ) -> None:
        """Crée la relation Claim -[:IN_CLUSTER]-> ClaimCluster."""
        query = """
        MATCH (c:Claim {claim_id: $claim_id})
        MATCH (cc:ClaimCluster {cluster_id: $cluster_id})
        MERGE (c)-[:IN_CLUSTER]->(cc)
        """
        session.run(query, claim_id=claim_id, cluster_id=cluster_id)
        self.stats["relations_created"] += 1

    def _persist_claim_relation(
        self,
        session,
        relation: ClaimRelation,
    ) -> None:
        """Crée une relation inter-claims (CONTRADICTS, REFINES, QUALIFIES)."""
        props = relation.to_neo4j_properties()
        rel_type = relation.relation_type.value

        query = f"""
        MATCH (c1:Claim {{claim_id: $source_id}})
        MATCH (c2:Claim {{claim_id: $target_id}})
        MERGE (c1)-[r:{rel_type}]->(c2)
        SET r += $props
        """
        session.run(
            query,
            source_id=relation.source_claim_id,
            target_id=relation.target_claim_id,
            props=props,
        )
        self.stats["relations_created"] += 1

    def delete_document_claims(
        self,
        doc_id: str,
        tenant_id: Optional[str] = None,
    ) -> dict:
        """
        Supprime toutes les claims d'un document.

        Utile pour le retraitement.

        Args:
            doc_id: Document ID
            tenant_id: Tenant ID (optionnel)

        Returns:
            Statistiques de suppression
        """
        tenant_id = tenant_id or self.tenant_id
        stats = {"claims_deleted": 0, "passages_deleted": 0, "relations_deleted": 0}

        with self.driver.session() as session:
            # Supprimer les relations d'abord
            rel_query = """
            MATCH (c:Claim {doc_id: $doc_id, tenant_id: $tenant_id})-[r]->()
            DELETE r
            RETURN count(r) as count
            """
            result = session.run(rel_query, doc_id=doc_id, tenant_id=tenant_id)
            stats["relations_deleted"] = result.single()["count"]

            # Supprimer les claims
            claim_query = """
            MATCH (c:Claim {doc_id: $doc_id, tenant_id: $tenant_id})
            DELETE c
            RETURN count(c) as count
            """
            result = session.run(claim_query, doc_id=doc_id, tenant_id=tenant_id)
            stats["claims_deleted"] = result.single()["count"]

            # Supprimer les passages
            passage_query = """
            MATCH (p:Passage {doc_id: $doc_id, tenant_id: $tenant_id})
            WHERE NOT EXISTS {
                MATCH (c:Claim)-[:SUPPORTED_BY]->(p)
            }
            DELETE p
            RETURN count(p) as count
            """
            result = session.run(passage_query, doc_id=doc_id, tenant_id=tenant_id)
            stats["passages_deleted"] = result.single()["count"]

        logger.info(
            f"[OSMOSE:ClaimPersister] Deleted claims for doc {doc_id}: "
            f"{stats['claims_deleted']} claims, "
            f"{stats['passages_deleted']} passages, "
            f"{stats['relations_deleted']} relations"
        )

        return stats

    def get_stats(self) -> dict:
        """Retourne les statistiques de persistance."""
        return dict(self.stats)

    def reset_stats(self) -> None:
        """Réinitialise les statistiques."""
        self.stats = {
            "passages_created": 0,
            "claims_created": 0,
            "entities_created": 0,
            "facets_created": 0,
            "clusters_created": 0,
            "relations_created": 0,
        }


__all__ = [
    "ClaimPersister",
]
