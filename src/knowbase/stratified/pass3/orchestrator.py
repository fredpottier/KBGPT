"""
OSMOSE Pipeline V2 - Pass 3 Orchestrator
=========================================
Ref: doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md

Orchestre Pass 3 (Consolidation Corpus):
- Résolution d'entités cross-documents
- Création des CanonicalConcept/CanonicalTheme
- Persistence dans Neo4j

Modes:
- BATCH: Traitement de tout le corpus
- INCREMENTAL: Intégration d'un nouveau document
"""

import logging
from typing import Dict, List, Optional
from enum import Enum

from knowbase.stratified.models import (
    Concept,
    Theme,
    CanonicalConcept,
    CanonicalTheme,
)
from knowbase.stratified.pass3.entity_resolver import (
    EntityResolverV2,
    Pass3Result,
)
from knowbase.stratified.pass3.persister import Pass3PersisterV2

logger = logging.getLogger(__name__)


class Pass3Mode(str, Enum):
    """Mode d'exécution Pass 3."""
    BATCH = "batch"           # Traitement complet du corpus
    INCREMENTAL = "incremental"  # Ajout d'un document


class Pass3OrchestratorV2:
    """
    Orchestrateur Pass 3 pour Pipeline V2.

    Consolide le graphe sémantique au niveau corpus.
    """

    def __init__(
        self,
        llm_client=None,
        neo4j_driver=None,
        embedding_client=None,
        allow_fallback: bool = False,
        tenant_id: str = "default"
    ):
        """
        Args:
            llm_client: Client LLM pour validation des ambigus
            neo4j_driver: Driver Neo4j
            embedding_client: Client pour embeddings
            allow_fallback: Autorise fallback heuristique
            tenant_id: Identifiant du tenant
        """
        self.llm_client = llm_client
        self.neo4j_driver = neo4j_driver
        self.embedding_client = embedding_client
        self.allow_fallback = allow_fallback
        self.tenant_id = tenant_id

        self.entity_resolver = EntityResolverV2(
            llm_client=llm_client,
            embedding_client=embedding_client,
            allow_fallback=allow_fallback
        )
        self.persister = Pass3PersisterV2(
            neo4j_driver=neo4j_driver,
            tenant_id=tenant_id
        )

    def process_batch(
        self,
        persist: bool = True
    ) -> Pass3Result:
        """
        Exécute Pass 3 en mode batch sur tout le corpus.

        Args:
            persist: Si True, persiste dans Neo4j

        Returns:
            Pass3Result
        """
        if not self.neo4j_driver:
            raise RuntimeError("Neo4j driver requis pour le mode batch")

        logger.info("[OSMOSE:Pass3] Début consolidation BATCH")

        # Charger tous les concepts et thèmes du corpus
        concepts, themes = self._load_all_from_neo4j()

        logger.info(
            f"[OSMOSE:Pass3] Chargé {len(concepts)} concepts, {len(themes)} thèmes"
        )

        # Résoudre les entités
        result = self.entity_resolver.resolve(concepts, themes)

        # Persister si demandé
        if persist:
            persist_stats = self.persister.persist(result)
            logger.info(f"[OSMOSE:Pass3] Persistence: {persist_stats}")

        return result

    def process_incremental(
        self,
        new_concepts: List[Concept],
        persist: bool = True
    ) -> Pass3Result:
        """
        Exécute Pass 3 en mode incrémental pour un nouveau document.

        Args:
            new_concepts: Concepts du nouveau document
            persist: Si True, persiste les modifications

        Returns:
            Pass3Result
        """
        logger.info(f"[OSMOSE:Pass3] Début consolidation INCREMENTAL: {len(new_concepts)} concepts")

        # Charger les canoniques existants
        existing_canonical = self._load_canonical_concepts()

        # Résolution incrémentale
        updated_canonical, mapping = self.entity_resolver.resolve_incremental(
            new_concepts=new_concepts,
            existing_canonical=existing_canonical
        )

        # Créer le résultat
        new_canonical = [cc for cc in updated_canonical if cc not in existing_canonical]

        result = Pass3Result(
            canonical_concepts=new_canonical,
            canonical_themes=[],
            stats=self.entity_resolver.resolve(new_concepts, []).stats
        )

        # Persister si demandé
        if persist and new_canonical:
            persist_stats = self.persister.persist(result)
            logger.info(f"[OSMOSE:Pass3] Persistence: {persist_stats}")

        logger.info(
            f"[OSMOSE:Pass3] TERMINÉ: {len(new_canonical)} nouveaux canonical, "
            f"{len(mapping)} mappings"
        )

        return result

    def _load_all_from_neo4j(self) -> tuple:
        """Charge tous les concepts et thèmes du corpus."""
        concepts = []
        themes = []

        with self.neo4j_driver.session() as session:
            # Charger tous les concepts
            concept_query = """
            MATCH (c:Concept {tenant_id: $tenant_id})
            OPTIONAL MATCH (t:Theme)-[:HAS_CONCEPT]->(c)
            RETURN c.concept_id AS concept_id,
                   c.name AS name,
                   c.role AS role,
                   c.variants AS variants,
                   c.lex_key AS lex_key,
                   t.theme_id AS theme_id
            """
            result = session.run(concept_query, {"tenant_id": self.tenant_id})

            from knowbase.stratified.models import ConceptRole
            for record in result:
                concept = Concept(
                    concept_id=record["concept_id"],
                    theme_id=record["theme_id"] or "",
                    name=record["name"],
                    role=ConceptRole(record["role"]) if record["role"] else ConceptRole.STANDARD,
                    variants=record["variants"] or [],
                    lex_key=record["lex_key"]
                )
                concepts.append(concept)

            # Charger tous les thèmes
            theme_query = """
            MATCH (t:Theme {tenant_id: $tenant_id})
            RETURN t.theme_id AS theme_id,
                   t.name AS name
            """
            result = session.run(theme_query, {"tenant_id": self.tenant_id})

            for record in result:
                theme = Theme(
                    theme_id=record["theme_id"],
                    name=record["name"]
                )
                themes.append(theme)

        return concepts, themes

    def _load_canonical_concepts(self) -> List[CanonicalConcept]:
        """Charge les CanonicalConcept existants."""
        if not self.neo4j_driver:
            return []

        canonical = []

        with self.neo4j_driver.session() as session:
            query = """
            MATCH (cc:CanonicalConcept {tenant_id: $tenant_id})
            OPTIONAL MATCH (cc)-[:SAME_AS]->(c:Concept)
            RETURN cc.canonical_id AS canonical_id,
                   cc.name AS name,
                   collect(c.concept_id) AS merged_from
            """
            result = session.run(query, {"tenant_id": self.tenant_id})

            for record in result:
                cc = CanonicalConcept(
                    canonical_id=record["canonical_id"],
                    name=record["name"],
                    merged_from=record["merged_from"] or []
                )
                canonical.append(cc)

        return canonical


def run_pass3_batch(
    neo4j_driver=None,
    llm_client=None,
    tenant_id: str = "default",
    **kwargs
) -> Pass3Result:
    """
    Fonction utilitaire pour exécuter Pass 3 en mode batch.
    """
    orchestrator = Pass3OrchestratorV2(
        neo4j_driver=neo4j_driver,
        llm_client=llm_client,
        tenant_id=tenant_id,
        **kwargs
    )
    return orchestrator.process_batch()


def run_pass3_incremental(
    new_concepts: List[Concept],
    neo4j_driver=None,
    llm_client=None,
    tenant_id: str = "default",
    **kwargs
) -> Pass3Result:
    """
    Fonction utilitaire pour exécuter Pass 3 en mode incrémental.
    """
    orchestrator = Pass3OrchestratorV2(
        neo4j_driver=neo4j_driver,
        llm_client=llm_client,
        tenant_id=tenant_id,
        **kwargs
    )
    return orchestrator.process_incremental(new_concepts)
