"""
Neo4j Client pour OSMOSE Architecture Agentique.

Utilisé pour:
- Proto-KG storage (concepts Proto extractés par NER)
- Published-KG storage (concepts validés par Gatekeeper)
- Multi-tenant isolation via tenant_id
- Cross-document concept linking

Author: OSMOSE Phase 1.5
Date: 2025-10-15
"""

from neo4j import GraphDatabase, Driver, ManagedTransaction
import logging
from typing import Optional, Dict, List, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class Neo4jClient:
    """
    Client Neo4j pour OSMOSE Agentique.

    Fonctionnalités:
    - Multi-tenant isolation (tenant_id filtering)
    - Proto-KG: Concepts extraits (non validés)
    - Published-KG: Concepts validés et promus
    - Atomic operations (transactions)
    - Connection pooling
    """

    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        user: str = "neo4j",
        password: str = "password",
        database: str = "neo4j"
    ):
        """
        Initialise client Neo4j.

        Args:
            uri: Neo4j URI (bolt://...)
            user: Neo4j username
            password: Neo4j password
            database: Database name (default: neo4j)
        """
        self.uri = uri
        self.user = user
        self.database = database

        try:
            self.driver: Driver = GraphDatabase.driver(
                uri,
                auth=(user, password),
                max_connection_lifetime=3600,
                max_connection_pool_size=50,
                connection_acquisition_timeout=120
            )

            # Test connexion
            self.driver.verify_connectivity()

            logger.info(f"[NEO4J] Connected to {uri} (database: {database})")

        except Exception as e:
            logger.error(f"[NEO4J] Connection failed: {e}")
            self.driver = None

    def is_connected(self) -> bool:
        """Vérifie si Neo4j est connecté."""
        if self.driver is None:
            return False

        try:
            self.driver.verify_connectivity()
            return True
        except:
            return False

    def close(self):
        """Ferme connexion Neo4j."""
        if self.driver:
            self.driver.close()
            logger.info("[NEO4J] Connection closed")

    # ========================================================================
    # Proto-KG: Concepts extraits (non validés)
    # ========================================================================

    def create_proto_concept(
        self,
        tenant_id: str,
        concept_name: str,
        concept_type: str,
        segment_id: str,
        document_id: str,
        extraction_method: str = "NER",
        confidence: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Crée concept Proto-KG (extrait, non validé).

        Args:
            tenant_id: ID tenant (isolation)
            concept_name: Nom concept extrait
            concept_type: Type (Product, Process, etc.)
            segment_id: ID segment source
            document_id: ID document source
            extraction_method: NER, Regex, LLM, etc.
            confidence: Score confiance extraction (0-1)
            metadata: Métadonnées additionnelles

        Returns:
            concept_id créé
        """
        if not self.is_connected():
            logger.warning("[NEO4J] Not connected, skipping Proto concept creation")
            return ""

        import json

        metadata = metadata or {}
        # Convertir metadata en JSON string pour Neo4j (ne supporte pas les Maps)
        metadata_json = json.dumps(metadata)

        query = """
        CREATE (c:ProtoConcept {
            concept_id: randomUUID(),
            tenant_id: $tenant_id,
            concept_name: $concept_name,
            concept_type: $concept_type,
            segment_id: $segment_id,
            document_id: $document_id,
            extraction_method: $extraction_method,
            confidence: $confidence,
            created_at: datetime(),
            metadata_json: $metadata_json
        })
        RETURN c.concept_id AS concept_id
        """

        try:
            with self.driver.session(database=self.database) as session:
                result = session.run(
                    query,
                    tenant_id=tenant_id,
                    concept_name=concept_name,
                    concept_type=concept_type,
                    segment_id=segment_id,
                    document_id=document_id,
                    extraction_method=extraction_method,
                    confidence=confidence,
                    metadata_json=metadata_json
                )

                record = result.single()
                concept_id = record["concept_id"]

                logger.debug(
                    f"[NEO4J:Proto] Created {concept_type} '{concept_name}' "
                    f"(tenant={tenant_id}, method={extraction_method})"
                )

                return concept_id

        except Exception as e:
            logger.error(f"[NEO4J:Proto] Error creating concept: {e}")
            return ""

    def get_proto_concepts(
        self,
        tenant_id: str,
        segment_id: Optional[str] = None,
        document_id: Optional[str] = None,
        concept_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Récupère concepts Proto-KG avec filtres.

        Args:
            tenant_id: ID tenant (obligatoire)
            segment_id: Filtrer par segment (optionnel)
            document_id: Filtrer par document (optionnel)
            concept_type: Filtrer par type (optionnel)

        Returns:
            Liste concepts Proto
        """
        if not self.is_connected():
            logger.warning("[NEO4J] Not connected, returning empty list")
            return []

        # Build query dynamique avec filtres
        filters = ["c.tenant_id = $tenant_id"]
        params = {"tenant_id": tenant_id}

        if segment_id:
            filters.append("c.segment_id = $segment_id")
            params["segment_id"] = segment_id

        if document_id:
            filters.append("c.document_id = $document_id")
            params["document_id"] = document_id

        if concept_type:
            filters.append("c.concept_type = $concept_type")
            params["concept_type"] = concept_type

        where_clause = " AND ".join(filters)

        query = f"""
        MATCH (c:ProtoConcept)
        WHERE {where_clause}
        RETURN c.concept_id AS concept_id,
               c.concept_name AS concept_name,
               c.concept_type AS concept_type,
               c.segment_id AS segment_id,
               c.document_id AS document_id,
               c.extraction_method AS extraction_method,
               c.confidence AS confidence,
               c.metadata AS metadata,
               c.created_at AS created_at
        ORDER BY c.created_at DESC
        """

        try:
            with self.driver.session(database=self.database) as session:
                result = session.run(query, **params)

                concepts = []
                for record in result:
                    concepts.append({
                        "concept_id": record["concept_id"],
                        "concept_name": record["concept_name"],
                        "concept_type": record["concept_type"],
                        "segment_id": record["segment_id"],
                        "document_id": record["document_id"],
                        "extraction_method": record["extraction_method"],
                        "confidence": record["confidence"],
                        "metadata": record["metadata"],
                        "created_at": record["created_at"]
                    })

                logger.debug(
                    f"[NEO4J:Proto] Retrieved {len(concepts)} concepts "
                    f"(tenant={tenant_id}, filters={len(filters)})"
                )

                return concepts

        except Exception as e:
            logger.error(f"[NEO4J:Proto] Error retrieving concepts: {e}")
            return []

    # ========================================================================
    # Published-KG: Concepts validés (promus par Gatekeeper)
    # ========================================================================

    def find_canonical_concept(
        self,
        tenant_id: str,
        canonical_name: str
    ) -> Optional[str]:
        """
        Chercher un CanonicalConcept existant par nom canonique et tenant.

        Args:
            tenant_id: ID tenant
            canonical_name: Nom canonique à chercher

        Returns:
            canonical_id si trouvé, None sinon
        """
        if not self.is_connected():
            return None

        query = """
        MATCH (c:CanonicalConcept {tenant_id: $tenant_id, canonical_name: $canonical_name})
        RETURN c.canonical_id AS canonical_id
        LIMIT 1
        """

        try:
            with self.driver.session(database=self.database) as session:
                result = session.run(
                    query,
                    tenant_id=tenant_id,
                    canonical_name=canonical_name
                )

                record = result.single()

                if record:
                    canonical_id = record["canonical_id"]
                    logger.debug(
                        f"[NEO4J:Dedup] Found existing CanonicalConcept '{canonical_name}' "
                        f"(id={canonical_id[:8]})"
                    )
                    return canonical_id
                else:
                    return None

        except Exception as e:
            logger.error(f"[NEO4J:Dedup] Error finding canonical concept: {e}")
            return None

    def promote_to_published(
        self,
        tenant_id: str,
        proto_concept_id: str,
        canonical_name: str,
        unified_definition: str,
        quality_score: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None,
        decision_trace_json: Optional[str] = None,
        surface_form: Optional[str] = None,
        deduplicate: bool = True
    ) -> str:
        """
        Promouvoir concept Proto → Published (validation Gatekeeper).

        Problème 2 (Déduplication): Si deduplicate=True (défaut), vérifie si
        un CanonicalConcept existe déjà avec ce canonical_name. Si oui, lie
        le ProtoConcept à l'existant au lieu de créer un doublon.

        Args:
            tenant_id: ID tenant
            proto_concept_id: ID concept Proto à promouvoir
            canonical_name: Nom canonique unifié
            unified_definition: Définition sémantique unifiée
            quality_score: Score qualité Gatekeeper (0-1)
            metadata: Métadonnées additionnelles
            decision_trace_json: JSON trace décision canonicalisation (P0.3)
            surface_form: Nom brut extrait avant canonicalisation (P1.3)
            deduplicate: Si True, vérifier existence avant création (défaut: True)

        Returns:
            canonical_id créé ou existant (ou "" si échec)
        """
        if not self.is_connected():
            logger.warning("[NEO4J] Not connected, skipping promotion")
            return ""

        import json

        metadata = metadata or {}
        # Convertir metadata en JSON string pour Neo4j (ne supporte pas les Maps)
        metadata_json = json.dumps(metadata)

        # Problème 2: Déduplication - chercher concept existant
        if deduplicate:
            existing_canonical_id = self.find_canonical_concept(tenant_id, canonical_name)

            if existing_canonical_id:
                # Lier ProtoConcept à CanonicalConcept existant
                link_query = """
                MATCH (proto:ProtoConcept {concept_id: $proto_concept_id, tenant_id: $tenant_id})
                MATCH (canonical:CanonicalConcept {canonical_id: $existing_canonical_id, tenant_id: $tenant_id})

                // Créer lien Proto → Canonical existant
                MERGE (proto)-[:PROMOTED_TO {
                    promoted_at: datetime(),
                    deduplication: true
                }]->(canonical)

                RETURN canonical.canonical_id AS canonical_id,
                       canonical.canonical_name AS canonical_name
                """

                try:
                    with self.driver.session(database=self.database) as session:
                        result = session.run(
                            link_query,
                            proto_concept_id=proto_concept_id,
                            tenant_id=tenant_id,
                            existing_canonical_id=existing_canonical_id
                        )

                        record = result.single()

                        if record:
                            logger.info(
                                f"[NEO4J:Dedup] Linked ProtoConcept to existing CanonicalConcept '{canonical_name}' "
                                f"(proto={proto_concept_id[:8]}, canonical={existing_canonical_id[:8]})"
                            )
                            return existing_canonical_id
                        else:
                            logger.warning(
                                f"[NEO4J:Dedup] Failed to link Proto to existing Canonical: {proto_concept_id}"
                            )
                            return ""

                except Exception as e:
                    logger.error(f"[NEO4J:Dedup] Error linking to existing concept: {e}")
                    # Fallback: continuer avec création normale
                    logger.info(f"[NEO4J:Dedup] Fallback to normal creation")

        # Créer nouveau CanonicalConcept (si pas de déduplication ou échec)
        query = """
        MATCH (proto:ProtoConcept {concept_id: $proto_concept_id, tenant_id: $tenant_id})

        // Créer CanonicalConcept (P1.3: ajout surface_form)
        CREATE (canonical:CanonicalConcept {
            canonical_id: randomUUID(),
            tenant_id: $tenant_id,
            canonical_name: $canonical_name,
            surface_form: $surface_form,
            concept_type: proto.concept_type,
            unified_definition: $unified_definition,
            quality_score: $quality_score,
            promoted_at: datetime(),
            metadata_json: $metadata_json,
            decision_trace_json: $decision_trace_json
        })

        // Lien Proto → Canonical
        CREATE (proto)-[:PROMOTED_TO {promoted_at: datetime()}]->(canonical)

        RETURN canonical.canonical_id AS canonical_id,
               canonical.canonical_name AS canonical_name,
               canonical.surface_form AS surface_form
        """

        try:
            with self.driver.session(database=self.database) as session:
                result = session.run(
                    query,
                    proto_concept_id=proto_concept_id,
                    tenant_id=tenant_id,
                    canonical_name=canonical_name,
                    surface_form=surface_form,
                    unified_definition=unified_definition,
                    quality_score=quality_score,
                    metadata_json=metadata_json,
                    decision_trace_json=decision_trace_json
                )

                record = result.single()

                if record:
                    canonical_id = record["canonical_id"]

                    # P1.3: Log surface_form si présent
                    surface_info = f", surface='{surface_form}'" if surface_form else ""

                    logger.info(
                        f"[NEO4J:Published] Created NEW CanonicalConcept '{canonical_name}' "
                        f"(proto={proto_concept_id[:8]}, quality={quality_score:.2f}{surface_info})"
                    )

                    return canonical_id
                else:
                    logger.warning(
                        f"[NEO4J:Published] Proto concept not found: {proto_concept_id}"
                    )
                    return ""

        except Exception as e:
            logger.error(f"[NEO4J:Published] Error promoting concept: {e}")
            return ""

    def get_published_concepts(
        self,
        tenant_id: str,
        concept_type: Optional[str] = None,
        min_quality_score: float = 0.0
    ) -> List[Dict[str, Any]]:
        """
        Récupère concepts Published-KG (validés).

        Args:
            tenant_id: ID tenant
            concept_type: Filtrer par type (optionnel)
            min_quality_score: Score qualité minimum (0-1)

        Returns:
            Liste concepts Published
        """
        if not self.is_connected():
            logger.warning("[NEO4J] Not connected, returning empty list")
            return []

        filters = [
            "c.tenant_id = $tenant_id",
            "c.quality_score >= $min_quality_score"
        ]
        params = {
            "tenant_id": tenant_id,
            "min_quality_score": min_quality_score
        }

        if concept_type:
            filters.append("c.concept_type = $concept_type")
            params["concept_type"] = concept_type

        where_clause = " AND ".join(filters)

        query = f"""
        MATCH (c:CanonicalConcept)
        WHERE {where_clause}
        RETURN c.canonical_id AS canonical_id,
               c.canonical_name AS canonical_name,
               c.concept_type AS concept_type,
               c.unified_definition AS unified_definition,
               c.quality_score AS quality_score,
               c.metadata AS metadata,
               c.promoted_at AS promoted_at
        ORDER BY c.quality_score DESC, c.promoted_at DESC
        """

        try:
            with self.driver.session(database=self.database) as session:
                result = session.run(query, **params)

                concepts = []
                for record in result:
                    concepts.append({
                        "canonical_id": record["canonical_id"],
                        "canonical_name": record["canonical_name"],
                        "concept_type": record["concept_type"],
                        "unified_definition": record["unified_definition"],
                        "quality_score": record["quality_score"],
                        "metadata": record["metadata"],
                        "promoted_at": record["promoted_at"]
                    })

                logger.debug(
                    f"[NEO4J:Published] Retrieved {len(concepts)} concepts "
                    f"(tenant={tenant_id}, min_quality={min_quality_score})"
                )

                return concepts

        except Exception as e:
            logger.error(f"[NEO4J:Published] Error retrieving concepts: {e}")
            return []

    # ========================================================================
    # Linking: Cross-document concept relationships
    # ========================================================================

    def create_concept_link(
        self,
        tenant_id: str,
        source_concept_id: str,
        target_concept_id: str,
        relationship_type: str = "RELATED_TO",
        weight: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Créer lien entre 2 concepts Published.

        Args:
            tenant_id: ID tenant
            source_concept_id: ID concept source
            target_concept_id: ID concept target
            relationship_type: Type relation (RELATED_TO, DEPENDS_ON, etc.)
            weight: Poids relation (0-1)
            metadata: Métadonnées additionnelles

        Returns:
            True si lien créé
        """
        if not self.is_connected():
            logger.warning("[NEO4J] Not connected, skipping link creation")
            return False

        metadata = metadata or {}

        # Aplatir metadata en propriétés individuelles (Neo4j n'accepte pas Map comme valeur)
        metadata_set_clauses = []
        metadata_params = {}

        for key, value in metadata.items():
            # Convertir clés metadata en propriétés rel.metadata_<key>
            safe_key = f"metadata_{key}"
            metadata_set_clauses.append(f"rel.{safe_key} = ${safe_key}")
            metadata_params[safe_key] = value

        metadata_set_str = ", ".join(metadata_set_clauses) if metadata_set_clauses else ""

        query = f"""
        MATCH (source:CanonicalConcept {{canonical_id: $source_concept_id, tenant_id: $tenant_id}})
        MATCH (target:CanonicalConcept {{canonical_id: $target_concept_id, tenant_id: $tenant_id}})

        MERGE (source)-[rel:{relationship_type}]->(target)
        SET rel.weight = $weight,
            rel.created_at = datetime()
        """

        if metadata_set_str:
            query += f", {metadata_set_str}"

        query += " RETURN rel"

        try:
            with self.driver.session(database=self.database) as session:
                params = {
                    "source_concept_id": source_concept_id,
                    "target_concept_id": target_concept_id,
                    "tenant_id": tenant_id,
                    "weight": weight
                }
                params.update(metadata_params)

                result = session.run(query, **params)

                if result.single():
                    logger.debug(
                        f"[NEO4J:Link] Created {relationship_type} "
                        f"(source={source_concept_id[:8]}, target={target_concept_id[:8]})"
                    )
                    return True
                else:
                    logger.warning(
                        f"[NEO4J:Link] Concepts not found for linking "
                        f"(tenant={tenant_id})"
                    )
                    return False

        except Exception as e:
            logger.error(f"[NEO4J:Link] Error creating link: {e}")
            return False

    # ========================================================================
    # Stats & Monitoring
    # ========================================================================

    def get_tenant_stats(self, tenant_id: str) -> Dict[str, int]:
        """
        Récupère statistiques KG pour tenant.

        Args:
            tenant_id: ID tenant

        Returns:
            Dict avec stats (proto_count, published_count, links_count)
        """
        if not self.is_connected():
            logger.warning("[NEO4J] Not connected, returning empty stats")
            return {"proto_count": 0, "published_count": 0, "links_count": 0}

        query = """
        MATCH (proto:ProtoConcept {tenant_id: $tenant_id})
        WITH count(proto) AS proto_count

        MATCH (canonical:CanonicalConcept {tenant_id: $tenant_id})
        WITH proto_count, count(canonical) AS published_count

        MATCH (c1:CanonicalConcept {tenant_id: $tenant_id})-[rel]->(c2:CanonicalConcept {tenant_id: $tenant_id})
        WITH proto_count, published_count, count(rel) AS links_count

        RETURN proto_count, published_count, links_count
        """

        try:
            with self.driver.session(database=self.database) as session:
                result = session.run(query, tenant_id=tenant_id)
                record = result.single()

                if record:
                    return {
                        "proto_count": record["proto_count"],
                        "published_count": record["published_count"],
                        "links_count": record["links_count"]
                    }
                else:
                    return {"proto_count": 0, "published_count": 0, "links_count": 0}

        except Exception as e:
            logger.error(f"[NEO4J:Stats] Error retrieving stats: {e}")
            return {"proto_count": 0, "published_count": 0, "links_count": 0}


# Singleton instance
_neo4j_client: Optional[Neo4jClient] = None


def get_neo4j_client(
    uri: str = "bolt://localhost:7687",
    user: str = "neo4j",
    password: str = "password",
    database: str = "neo4j"
) -> Neo4jClient:
    """
    Récupère instance singleton Neo4j client.

    Args:
        uri: Neo4j URI
        user: Neo4j username
        password: Neo4j password
        database: Database name

    Returns:
        Neo4jClient instance
    """
    global _neo4j_client

    if _neo4j_client is None:
        _neo4j_client = Neo4jClient(
            uri=uri,
            user=user,
            password=password,
            database=database
        )

    return _neo4j_client
