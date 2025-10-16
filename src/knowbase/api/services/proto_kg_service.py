"""
Proto-KG Service - OSMOSE Phase 1.5

Service pour gérer le Proto-KG (Knowledge Graph de staging) avec :
- Neo4j : Concepts canoniques + relations sémantiques
- Qdrant : Embeddings des concepts

Le Proto-KG est la couche de staging avant promotion vers le KG production.
Il contient les concepts extraits par OSMOSE avec canonicalisation cross-lingual.

Author: OSMOSE Phase 1.5
Date: 2025-10-14
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class ProtoKGService:
    """
    Service pour gérer le Proto-KG (Neo4j + Qdrant).

    Le Proto-KG contient:
    - Concepts canoniques (cross-lingual)
    - Relations sémantiques entre concepts
    - Connexions Document-Concept avec DocumentRole
    - Hiérarchies de concepts (parent-child)
    """

    def __init__(self, tenant_id: str = "default"):
        """
        Initialise le service Proto-KG.

        Args:
            tenant_id: ID tenant pour multi-tenancy
        """
        self.tenant_id = tenant_id
        self.neo4j_driver = None

        # Lazy init du driver Neo4j
        self._init_neo4j_driver()

    def _init_neo4j_driver(self):
        """Initialise la connexion Neo4j."""
        try:
            from neo4j import GraphDatabase
            from knowbase.config.settings import get_settings

            settings = get_settings()

            # Settings Pydantic : attributs en lowercase, alias en uppercase pour env vars
            neo4j_uri = settings.neo4j_uri
            neo4j_user = settings.neo4j_user
            neo4j_password = settings.neo4j_password

            # 🔍 DEBUG: Afficher credentials utilisés (masquer password)
            logger.info(f"[DEBUG Proto-KG] Connecting to Neo4j: uri={neo4j_uri}, user={neo4j_user}, password={'*' * len(neo4j_password)}")

            self.neo4j_driver = GraphDatabase.driver(
                neo4j_uri,
                auth=(neo4j_user, neo4j_password)
            )

            logger.info(f"[Proto-KG] Neo4j driver initialized for tenant {self.tenant_id}")

        except Exception as e:
            logger.error(f"[Proto-KG] Neo4j driver init failed: {e}")
            self.neo4j_driver = None

    async def create_canonical_concept(
        self,
        canonical_name: str,
        concept_type: str,
        unified_definition: str,
        aliases: List[str],
        languages: List[str],
        source_documents: List[str],
        parent_concept: Optional[str] = None,
        quality_score: float = 0.0
    ) -> str:
        """
        Crée un nœud Concept canonique dans Neo4j.

        Args:
            canonical_name: Nom canonique du concept (priorité anglais)
            concept_type: Type (ENTITY, PRACTICE, STANDARD, TOOL, ROLE)
            unified_definition: Définition unifiée (fusion LLM)
            aliases: Liste des alias (variantes linguistiques)
            languages: Langues détectées
            source_documents: IDs des documents sources
            parent_concept: Nom du concept parent (hiérarchie)
            quality_score: Score qualité (0-1)

        Returns:
            ID du nœud créé dans Neo4j
        """
        if not self.neo4j_driver:
            logger.warning("[Proto-KG] Neo4j driver not available")
            return ""

        try:
            with self.neo4j_driver.session() as session:
                query = """
                MERGE (c:CanonicalConcept {
                    canonical_name: $canonical_name,
                    tenant_id: $tenant_id
                })
                ON CREATE SET
                    c.concept_type = $concept_type,
                    c.unified_definition = $unified_definition,
                    c.aliases = $aliases,
                    c.languages = $languages,
                    c.source_documents = $source_documents,
                    c.quality_score = $quality_score,
                    c.created_at = datetime()
                ON MATCH SET
                    c.unified_definition = $unified_definition,
                    c.aliases = $aliases,
                    c.languages = $languages,
                    c.source_documents = c.source_documents + $source_documents,
                    c.quality_score = $quality_score,
                    c.updated_at = datetime()
                RETURN id(c) as concept_id
                """

                result = session.run(
                    query,
                    canonical_name=canonical_name,
                    tenant_id=self.tenant_id,
                    concept_type=concept_type,
                    unified_definition=unified_definition[:2000],  # Max 2000 chars
                    aliases=aliases[:50],  # Max 50 aliases
                    languages=languages,
                    source_documents=source_documents,
                    quality_score=quality_score
                )

                record = result.single()
                concept_id = str(record["concept_id"]) if record else ""

                # Créer relation parent-child si parent fourni
                if parent_concept and concept_id:
                    await self._create_parent_child_relation(canonical_name, parent_concept)

                logger.debug(f"[Proto-KG] Concept created: {canonical_name} (ID: {concept_id})")
                return concept_id

        except Exception as e:
            logger.error(f"[Proto-KG] Concept creation failed for {canonical_name}: {e}")
            return ""

    async def _create_parent_child_relation(
        self,
        child_name: str,
        parent_name: str
    ):
        """
        Crée une relation PARENT_OF entre deux concepts.

        Args:
            child_name: Nom du concept enfant
            parent_name: Nom du concept parent
        """
        if not self.neo4j_driver:
            return

        try:
            with self.neo4j_driver.session() as session:
                query = """
                MATCH (parent:CanonicalConcept {canonical_name: $parent_name, tenant_id: $tenant_id})
                MATCH (child:CanonicalConcept {canonical_name: $child_name, tenant_id: $tenant_id})
                MERGE (parent)-[r:PARENT_OF]->(child)
                ON CREATE SET r.created_at = datetime()
                RETURN id(r) as rel_id
                """

                result = session.run(
                    query,
                    parent_name=parent_name,
                    child_name=child_name,
                    tenant_id=self.tenant_id
                )

                record = result.single()
                if record:
                    logger.debug(f"[Proto-KG] Parent-child relation created: {parent_name} → {child_name}")

        except Exception as e:
            logger.error(f"[Proto-KG] Parent-child relation failed: {e}")

    async def create_concept_relation(
        self,
        source_concept: str,
        target_concept: str,
        relation_type: str,
        document_id: str,
        document_role: str = "REFERENCES"
    ) -> str:
        """
        Crée une relation sémantique entre deux concepts.

        Args:
            source_concept: Nom canonique du concept source
            target_concept: Nom canonique du concept cible
            relation_type: Type de relation (RELATED_TO, IMPLEMENTS, etc.)
            document_id: ID du document où la relation est mentionnée
            document_role: Rôle du document (DEFINES, IMPLEMENTS, AUDITS, etc.)

        Returns:
            ID de la relation créée
        """
        if not self.neo4j_driver:
            logger.warning("[Proto-KG] Neo4j driver not available")
            return ""

        try:
            with self.neo4j_driver.session() as session:
                # Utiliser MERGE pour éviter duplications
                query = f"""
                MATCH (source:CanonicalConcept {{canonical_name: $source_concept, tenant_id: $tenant_id}})
                MATCH (target:CanonicalConcept {{canonical_name: $target_concept, tenant_id: $tenant_id}})
                MERGE (source)-[r:{relation_type}]->(target)
                ON CREATE SET
                    r.document_ids = [$document_id],
                    r.document_roles = [$document_role],
                    r.created_at = datetime()
                ON MATCH SET
                    r.document_ids = r.document_ids + $document_id,
                    r.document_roles = r.document_roles + $document_role,
                    r.updated_at = datetime()
                RETURN id(r) as rel_id
                """

                result = session.run(
                    query,
                    source_concept=source_concept,
                    target_concept=target_concept,
                    document_id=document_id,
                    document_role=document_role,
                    tenant_id=self.tenant_id
                )

                record = result.single()
                rel_id = str(record["rel_id"]) if record else ""

                logger.debug(
                    f"[Proto-KG] Relation created: {source_concept} -{relation_type}-> {target_concept}"
                )
                return rel_id

        except Exception as e:
            logger.error(f"[Proto-KG] Relation creation failed: {e}")
            return ""

    async def get_concept_by_name(
        self,
        canonical_name: str
    ) -> Optional[Dict[str, Any]]:
        """
        Récupère un concept par son nom canonique.

        Args:
            canonical_name: Nom canonique du concept

        Returns:
            Dictionnaire avec les propriétés du concept ou None
        """
        if not self.neo4j_driver:
            return None

        try:
            with self.neo4j_driver.session() as session:
                query = """
                MATCH (c:CanonicalConcept {canonical_name: $canonical_name, tenant_id: $tenant_id})
                RETURN c
                """

                result = session.run(
                    query,
                    canonical_name=canonical_name,
                    tenant_id=self.tenant_id
                )

                record = result.single()
                if record:
                    concept_node = record["c"]
                    return dict(concept_node)

                return None

        except Exception as e:
            logger.error(f"[Proto-KG] Concept retrieval failed for {canonical_name}: {e}")
            return None

    async def get_concept_relations(
        self,
        canonical_name: str,
        max_depth: int = 1
    ) -> List[Dict[str, Any]]:
        """
        Récupère les relations d'un concept (depth-first).

        Args:
            canonical_name: Nom canonique du concept
            max_depth: Profondeur maximale de traversée

        Returns:
            Liste des relations
        """
        if not self.neo4j_driver:
            return []

        try:
            with self.neo4j_driver.session() as session:
                query = """
                MATCH (c:CanonicalConcept {canonical_name: $canonical_name, tenant_id: $tenant_id})
                MATCH (c)-[r*1..{max_depth}]-(related:CanonicalConcept)
                RETURN type(r[0]) as relation_type, related.canonical_name as related_concept
                LIMIT 100
                """

                result = session.run(
                    query.replace("{max_depth}", str(max_depth)),
                    canonical_name=canonical_name,
                    tenant_id=self.tenant_id
                )

                relations = []
                for record in result:
                    relations.append({
                        "relation_type": record["relation_type"],
                        "related_concept": record["related_concept"]
                    })

                return relations

        except Exception as e:
            logger.error(f"[Proto-KG] Relations retrieval failed for {canonical_name}: {e}")
            return []

    def close(self):
        """Ferme la connexion Neo4j."""
        if self.neo4j_driver:
            self.neo4j_driver.close()
            logger.info(f"[Proto-KG] Neo4j driver closed for tenant {self.tenant_id}")
