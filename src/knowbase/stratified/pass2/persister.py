"""
OSMOSE Pipeline V2 - Pass 2 Persister
======================================
Ref: doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md

Persiste les relations Pass 2 dans Neo4j:
- Relations entre Concepts avec type et evidence
"""

import logging
from typing import Dict, List

from knowbase.stratified.pass2.relation_extractor import (
    Pass2Result,
    ConceptRelation,
)

logger = logging.getLogger(__name__)


class Pass2PersisterV2:
    """
    Persiste les relations Pass 2 dans Neo4j.

    Crée les relations:
    - Concept -[relation_type]-> Concept
    avec propriétés: confidence, evidence_info_ids, justification
    """

    def __init__(self, neo4j_driver=None, tenant_id: str = "default"):
        """
        Args:
            neo4j_driver: Driver Neo4j
            tenant_id: Identifiant du tenant
        """
        self.driver = neo4j_driver
        self.tenant_id = tenant_id

    def persist(self, result: Pass2Result) -> Dict[str, int]:
        """
        Persiste un Pass2Result dans Neo4j.

        Args:
            result: Résultat Pass 2 à persister

        Returns:
            Dict avec compteurs
        """
        if not self.driver:
            logger.warning("[OSMOSE:Pass2:Persist] No Neo4j driver configured")
            return {"error": "no_driver"}

        stats = {"relations_created": 0}

        with self.driver.session() as session:
            for relation in result.relations:
                session.execute_write(
                    self._create_relation_tx,
                    relation,
                    self.tenant_id
                )
                stats["relations_created"] += 1

        logger.info(f"[OSMOSE:Pass2:Persist] {stats['relations_created']} relations créées")
        return stats

    @staticmethod
    def _create_relation_tx(tx, relation: ConceptRelation, tenant_id: str):
        """Transaction: créer relation entre concepts."""
        # Utiliser APOC pour créer une relation dynamique si disponible
        # Sinon, créer une relation générique RELATED_TO avec type en propriété
        query = """
        MATCH (source:Concept {concept_id: $source_id, tenant_id: $tenant_id})
        MATCH (target:Concept {concept_id: $target_id, tenant_id: $tenant_id})
        MERGE (source)-[r:CONCEPT_RELATION {relation_id: $relation_id}]->(target)
        SET r.type = $relation_type,
            r.confidence = $confidence,
            r.evidence_info_ids = $evidence,
            r.justification = $justification,
            r.created_at = datetime()
        """
        tx.run(query, {
            "source_id": relation.source_concept_id,
            "target_id": relation.target_concept_id,
            "tenant_id": tenant_id,
            "relation_id": relation.relation_id,
            "relation_type": relation.relation_type,
            "confidence": relation.confidence,
            "evidence": relation.evidence_info_ids,
            "justification": relation.justification,
        })

    def delete_pass2_data(self, doc_id: str) -> int:
        """Supprime les relations Pass 2 pour un document."""
        if not self.driver:
            return 0

        with self.driver.session() as session:
            result = session.execute_write(
                self._delete_pass2_data_tx,
                doc_id,
                self.tenant_id
            )
            return result

    @staticmethod
    def _delete_pass2_data_tx(tx, doc_id: str, tenant_id: str) -> int:
        """Transaction: supprimer relations Pass 2."""
        query = """
        MATCH (d:Document {doc_id: $doc_id, tenant_id: $tenant_id})
              -[:HAS_SUBJECT]->(:Subject)
              -[:HAS_THEME]->(:Theme)
              -[:HAS_CONCEPT]->(c:Concept)
        MATCH (c)-[r:CONCEPT_RELATION]->()
        DELETE r
        RETURN count(r) AS deleted
        """
        result = tx.run(query, {"doc_id": doc_id, "tenant_id": tenant_id})
        record = result.single()
        return record["deleted"] if record else 0


def persist_pass2_result(
    result: Pass2Result,
    neo4j_driver=None,
    tenant_id: str = "default"
) -> Dict[str, int]:
    """Fonction utilitaire pour persister Pass2Result."""
    persister = Pass2PersisterV2(neo4j_driver=neo4j_driver, tenant_id=tenant_id)
    return persister.persist(result)
