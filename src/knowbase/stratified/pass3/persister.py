"""
OSMOSE Pipeline V2 - Pass 3 Persister
======================================
Ref: doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md

Persiste les entités canoniques dans Neo4j:
- CanonicalConcept avec relations SAME_AS
- CanonicalTheme avec relations ALIGNED_TO
"""

import logging
from typing import Dict, List

from knowbase.stratified.models import (
    CanonicalConcept,
    CanonicalTheme,
)
from knowbase.stratified.pass3.entity_resolver import Pass3Result

logger = logging.getLogger(__name__)


class Pass3PersisterV2:
    """
    Persiste les résultats Pass 3 dans Neo4j.

    Crée:
    - CanonicalConcept -[:SAME_AS]-> Concept (pour chaque concept fusionné)
    - CanonicalTheme -[:ALIGNED_TO]-> Theme (pour chaque thème aligné)
    """

    def __init__(self, neo4j_driver=None, tenant_id: str = "default"):
        """
        Args:
            neo4j_driver: Driver Neo4j
            tenant_id: Identifiant du tenant
        """
        self.driver = neo4j_driver
        self.tenant_id = tenant_id

    def persist(self, result: Pass3Result) -> Dict[str, int]:
        """
        Persiste un Pass3Result dans Neo4j.

        Args:
            result: Résultat Pass 3 à persister

        Returns:
            Dict avec compteurs
        """
        if not self.driver:
            logger.warning("[OSMOSE:Pass3:Persist] No Neo4j driver configured")
            return {"error": "no_driver"}

        stats = {
            "canonical_concepts": 0,
            "canonical_themes": 0,
            "same_as_relations": 0,
            "aligned_to_relations": 0,
        }

        with self.driver.session() as session:
            # Créer CanonicalConcept
            for cc in result.canonical_concepts:
                session.execute_write(
                    self._create_canonical_concept_tx,
                    cc,
                    self.tenant_id
                )
                stats["canonical_concepts"] += 1
                stats["same_as_relations"] += len(cc.merged_from)

            # Créer CanonicalTheme
            for ct in result.canonical_themes:
                session.execute_write(
                    self._create_canonical_theme_tx,
                    ct,
                    self.tenant_id
                )
                stats["canonical_themes"] += 1
                stats["aligned_to_relations"] += len(ct.aligned_from)

        logger.info(
            f"[OSMOSE:Pass3:Persist] {stats['canonical_concepts']} CanonicalConcept, "
            f"{stats['canonical_themes']} CanonicalTheme"
        )
        return stats

    @staticmethod
    def _create_canonical_concept_tx(tx, cc: CanonicalConcept, tenant_id: str):
        """Transaction: créer CanonicalConcept et relations SAME_AS."""
        # Créer le nœud CanonicalConcept
        create_query = """
        MERGE (cc:CanonicalConcept {canonical_id: $canonical_id, tenant_id: $tenant_id})
        SET cc.name = $name,
            cc.created_at = datetime()
        """
        tx.run(create_query, {
            "canonical_id": cc.canonical_id,
            "tenant_id": tenant_id,
            "name": cc.name,
        })

        # Créer les relations SAME_AS vers les concepts fusionnés
        for concept_id in cc.merged_from:
            link_query = """
            MATCH (cc:CanonicalConcept {canonical_id: $canonical_id, tenant_id: $tenant_id})
            MATCH (c:Concept {concept_id: $concept_id, tenant_id: $tenant_id})
            MERGE (cc)-[:SAME_AS]->(c)
            """
            tx.run(link_query, {
                "canonical_id": cc.canonical_id,
                "concept_id": concept_id,
                "tenant_id": tenant_id,
            })

    @staticmethod
    def _create_canonical_theme_tx(tx, ct: CanonicalTheme, tenant_id: str):
        """Transaction: créer CanonicalTheme et relations ALIGNED_TO."""
        # Créer le nœud CanonicalTheme
        create_query = """
        MERGE (ct:CanonicalTheme {canonical_id: $canonical_id, tenant_id: $tenant_id})
        SET ct.name = $name,
            ct.created_at = datetime()
        """
        tx.run(create_query, {
            "canonical_id": ct.canonical_id,
            "tenant_id": tenant_id,
            "name": ct.name,
        })

        # Créer les relations ALIGNED_TO vers les thèmes alignés
        for theme_id in ct.aligned_from:
            link_query = """
            MATCH (ct:CanonicalTheme {canonical_id: $canonical_id, tenant_id: $tenant_id})
            MATCH (t:Theme {theme_id: $theme_id, tenant_id: $tenant_id})
            MERGE (ct)-[:ALIGNED_TO]->(t)
            """
            tx.run(link_query, {
                "canonical_id": ct.canonical_id,
                "theme_id": theme_id,
                "tenant_id": tenant_id,
            })


def persist_pass3_result(
    result: Pass3Result,
    neo4j_driver=None,
    tenant_id: str = "default"
) -> Dict[str, int]:
    """Fonction utilitaire pour persister Pass3Result."""
    persister = Pass3PersisterV2(neo4j_driver=neo4j_driver, tenant_id=tenant_id)
    return persister.persist(result)
