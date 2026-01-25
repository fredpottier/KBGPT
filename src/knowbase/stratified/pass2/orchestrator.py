"""
OSMOSE Pipeline V2 - Pass 2 Orchestrator
=========================================
Ref: doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md

Orchestre Pass 2 (Enrichissement):
- Extraction des relations inter-concepts
- Classification fine (optionnel)
- Persistence dans Neo4j
"""

import logging
from typing import Dict, List, Optional

from knowbase.stratified.models import (
    Concept,
    Information,
    Pass1Result,
)
from knowbase.stratified.pass2.relation_extractor import (
    RelationExtractorV2,
    Pass2Result,
    ConceptRelation,
)
from knowbase.stratified.pass2.persister import Pass2PersisterV2

logger = logging.getLogger(__name__)


class Pass2OrchestratorV2:
    """
    Orchestrateur Pass 2 pour Pipeline V2.

    Enrichit le graphe sémantique avec les relations entre concepts.
    """

    def __init__(
        self,
        llm_client=None,
        neo4j_driver=None,
        allow_fallback: bool = False,
        tenant_id: str = "default"
    ):
        """
        Args:
            llm_client: Client LLM compatible
            neo4j_driver: Driver Neo4j pour persistence
            allow_fallback: Autorise fallback heuristique
            tenant_id: Identifiant du tenant
        """
        self.llm_client = llm_client
        self.neo4j_driver = neo4j_driver
        self.allow_fallback = allow_fallback
        self.tenant_id = tenant_id

        self.relation_extractor = RelationExtractorV2(
            llm_client=llm_client,
            allow_fallback=allow_fallback
        )
        self.persister = Pass2PersisterV2(
            neo4j_driver=neo4j_driver,
            tenant_id=tenant_id
        )

    def process(
        self,
        pass1_result: Pass1Result,
        persist: bool = True
    ) -> Pass2Result:
        """
        Exécute Pass 2 sur un résultat Pass 1.

        Args:
            pass1_result: Résultat de Pass 1
            persist: Si True, persiste dans Neo4j

        Returns:
            Pass2Result avec les relations
        """
        doc_id = pass1_result.doc.doc_id

        logger.info(f"[OSMOSE:Pass2] Début enrichissement: {doc_id}")

        # Extraire les relations
        result = self.relation_extractor.extract_relations(
            doc_id=doc_id,
            concepts=pass1_result.concepts,
            informations=pass1_result.informations
        )

        # Persister si demandé
        if persist and self.neo4j_driver:
            persist_stats = self.persister.persist(result)
            logger.info(f"[OSMOSE:Pass2] Persistence: {persist_stats}")

        logger.info(
            f"[OSMOSE:Pass2] TERMINÉ: {result.stats.relations_extracted} relations, "
            f"{result.stats.avg_relations_per_concept:.2f} rel/concept"
        )

        return result

    def process_from_neo4j(
        self,
        doc_id: str,
        persist: bool = True
    ) -> Pass2Result:
        """
        Exécute Pass 2 en chargeant les données depuis Neo4j.

        Args:
            doc_id: Identifiant du document
            persist: Si True, persiste les relations

        Returns:
            Pass2Result
        """
        if not self.neo4j_driver:
            raise RuntimeError("Neo4j driver requis pour charger les données")

        # Charger concepts et informations depuis Neo4j
        concepts, informations = self._load_from_neo4j(doc_id)

        logger.info(
            f"[OSMOSE:Pass2] Chargé {len(concepts)} concepts, "
            f"{len(informations)} informations depuis Neo4j"
        )

        # Extraire les relations
        result = self.relation_extractor.extract_relations(
            doc_id=doc_id,
            concepts=concepts,
            informations=informations
        )

        # Persister si demandé
        if persist:
            persist_stats = self.persister.persist(result)
            logger.info(f"[OSMOSE:Pass2] Persistence: {persist_stats}")

        return result

    def _load_from_neo4j(self, doc_id: str) -> tuple:
        """Charge les concepts et informations depuis Neo4j."""
        concepts = []
        informations = []

        with self.neo4j_driver.session() as session:
            # Charger concepts
            concept_query = """
            MATCH (d:Document {doc_id: $doc_id, tenant_id: $tenant_id})
                  -[:HAS_SUBJECT]->(:Subject)
                  -[:HAS_THEME]->(t:Theme)
                  -[:HAS_CONCEPT]->(c:Concept)
            RETURN c.concept_id AS concept_id,
                   c.name AS name,
                   c.role AS role,
                   c.variants AS variants,
                   c.lex_key AS lex_key,
                   t.theme_id AS theme_id
            """
            result = session.run(concept_query, {
                "doc_id": doc_id,
                "tenant_id": self.tenant_id
            })

            from knowbase.stratified.models import ConceptRole
            for record in result:
                concept = Concept(
                    concept_id=record["concept_id"],
                    theme_id=record["theme_id"],
                    name=record["name"],
                    role=ConceptRole(record["role"]) if record["role"] else ConceptRole.STANDARD,
                    variants=record["variants"] or [],
                    lex_key=record["lex_key"]
                )
                concepts.append(concept)

            # Charger informations
            info_query = """
            MATCH (d:Document {doc_id: $doc_id, tenant_id: $tenant_id})
                  -[:HAS_SUBJECT]->(:Subject)
                  -[:HAS_THEME]->(:Theme)
                  -[:HAS_CONCEPT]->(c:Concept)
                  -[:HAS_INFORMATION]->(i:Information)
                  -[a:ANCHORED_IN]->(di:DocItem)
            RETURN i.info_id AS info_id,
                   i.text AS text,
                   i.type AS type,
                   i.confidence AS confidence,
                   c.concept_id AS concept_id,
                   di.docitem_id AS docitem_id,
                   a.span_start AS span_start,
                   a.span_end AS span_end
            """
            result = session.run(info_query, {
                "doc_id": doc_id,
                "tenant_id": self.tenant_id
            })

            from knowbase.stratified.models import AssertionType, Anchor
            for record in result:
                info = Information(
                    info_id=record["info_id"],
                    concept_id=record["concept_id"],
                    text=record["text"],
                    type=AssertionType(record["type"]) if record["type"] else AssertionType.FACTUAL,
                    confidence=record["confidence"] or 0.8,
                    anchor=Anchor(
                        docitem_id=record["docitem_id"],
                        span_start=record["span_start"] or 0,
                        span_end=record["span_end"] or 0
                    )
                )
                informations.append(info)

        return concepts, informations


def run_pass2(
    pass1_result: Pass1Result,
    llm_client=None,
    neo4j_driver=None,
    tenant_id: str = "default",
    **kwargs
) -> Pass2Result:
    """
    Fonction utilitaire pour exécuter Pass 2.

    Args:
        pass1_result: Résultat de Pass 1
        llm_client: Client LLM
        neo4j_driver: Driver Neo4j
        tenant_id: Identifiant du tenant

    Returns:
        Pass2Result
    """
    orchestrator = Pass2OrchestratorV2(
        llm_client=llm_client,
        neo4j_driver=neo4j_driver,
        tenant_id=tenant_id,
        **kwargs
    )
    return orchestrator.process(pass1_result)
