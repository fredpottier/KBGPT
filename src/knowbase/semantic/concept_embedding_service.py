"""
Concept Embedding Service - OSMOSE Multilingue

Service responsable de:
1. Definir le contrat de representation des concepts (embedding text)
2. Synchroniser les concepts Neo4j vers Qdrant (embeddings cross-lingues)
3. Fournir un mode degrade si collection absente

Architecture:
- Un seul CanonicalConcept (canonical_id unique)
- canonical_name = langue pivot (souvent EN)
- surface_forms = variantes observees (FR, EN, acronymes)
- Matching = embeddings cross-lingues via multilingual-e5-large

Version: 1.0.0
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum

from knowbase.config.settings import Settings
from knowbase.common.logging import setup_logging

_settings = Settings()
logger = setup_logging(_settings.logs_dir, "concept_embedding_service.log")


# =============================================================================
# CONSTANTS
# =============================================================================

# Nom de la collection Qdrant pour les concepts
QDRANT_CONCEPTS_COLLECTION = "osmos_concepts"

# Version du contrat d'embedding (incrementer si le format change)
EMBEDDING_VERSION = "concept_v1"

# Dimensions de l'embedding (multilingual-e5-large)
EMBEDDING_DIMENSION = 1024


# =============================================================================
# CONTRAT DE REPRESENTATION (Etape 0)
# =============================================================================

def build_concept_embedding_text(
    canonical_name: str,
    unified_definition: Optional[str] = None,
    summary: Optional[str] = None,
    surface_forms: Optional[List[str]] = None,
) -> str:
    """
    Contrat de representation deterministe pour l'embedding d'un concept.

    IMPORTANT: Cette fonction definit LE texte exact qui sera encode.
    Toute modification doit incrementer EMBEDDING_VERSION.

    Format:
        canonical_name
        [ — unified_definition]
        [ — summary]
        [ — aliases: form1, form2, ...]

    Args:
        canonical_name: Nom canonique du concept (obligatoire)
        unified_definition: Definition unifiee (optionnel)
        summary: Resume du concept (optionnel)
        surface_forms: Variantes/aliases (optionnel)

    Returns:
        Texte deterministe pour l'embedding
    """
    parts = [canonical_name]

    # Ajouter definition si presente (tronquee a 500 chars)
    if unified_definition and unified_definition.strip():
        definition = unified_definition.strip()[:500]
        parts.append(f" — {definition}")

    # Ajouter summary si present (tronque a 300 chars)
    if summary and summary.strip():
        summ = summary.strip()[:300]
        parts.append(f" — {summ}")

    # Ajouter surface forms (triees pour determinisme)
    if surface_forms:
        # Filtrer les vides, deduplier, trier
        forms = sorted(set(f.strip() for f in surface_forms if f and f.strip()))
        # Exclure le canonical_name s'il est dans les forms
        forms = [f for f in forms if f.lower() != canonical_name.lower()]
        if forms:
            parts.append(f" — aliases: {', '.join(forms[:10])}")  # Max 10 aliases

    return "".join(parts)


def compute_embedding_hash(embedding_text: str) -> str:
    """
    Calcule un hash stable du texte d'embedding.

    Utilise pour detecter si un concept a change et necessite re-embedding.
    """
    return hashlib.sha256(embedding_text.encode("utf-8")).hexdigest()[:16]


# =============================================================================
# DATA CLASSES
# =============================================================================

class SyncStatus(str, Enum):
    """Statut de synchronisation d'un concept."""
    CREATED = "created"
    UPDATED = "updated"
    UNCHANGED = "unchanged"
    FAILED = "failed"


@dataclass
class ConceptSyncResult:
    """Resultat de synchronisation d'un concept."""
    canonical_id: str
    canonical_name: str
    status: SyncStatus
    error: Optional[str] = None


@dataclass
class SyncBatchResult:
    """Resultat d'un batch de synchronisation."""
    total: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    failed: int = 0
    duration_ms: float = 0.0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "created": self.created,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "failed": self.failed,
            "duration_ms": round(self.duration_ms, 1),
            "success_rate": round((self.created + self.updated + self.unchanged) / max(self.total, 1) * 100, 1),
            "errors": self.errors[:10],  # Max 10 erreurs
        }


@dataclass
class ConceptSemanticStatus:
    """
    Statut du service semantic concepts (pour observabilite).

    Permet de savoir si le matching cross-lingue est disponible.
    """
    available: bool = False
    collection_exists: bool = False
    concept_count: int = 0
    embedding_version: str = EMBEDDING_VERSION
    last_sync: Optional[str] = None
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "collection_exists": self.collection_exists,
            "concept_count": self.concept_count,
            "embedding_version": self.embedding_version,
            "last_sync": self.last_sync,
            "message": self.message,
        }


# =============================================================================
# SERVICE PRINCIPAL
# =============================================================================

class ConceptEmbeddingService:
    """
    Service de gestion des embeddings de concepts.

    Responsabilites:
    1. Creer/gerer la collection Qdrant osmos_concepts
    2. Synchroniser les concepts Neo4j vers Qdrant
    3. Fournir le statut du service (observabilite)
    """

    def __init__(
        self,
        qdrant_client=None,
        neo4j_driver=None,
        embedder=None,
    ):
        self._qdrant_client = qdrant_client
        self._neo4j_driver = neo4j_driver
        self._embedder = embedder
        self._last_sync: Optional[datetime] = None

    # =========================================================================
    # LAZY LOADING
    # =========================================================================

    def _get_qdrant_client(self):
        """Recupere le client Qdrant (lazy loading)."""
        if self._qdrant_client is None:
            try:
                from qdrant_client import QdrantClient
                from knowbase.config.settings import Settings
                settings = Settings()
                self._qdrant_client = QdrantClient(url=settings.qdrant_url)
            except Exception as e:
                logger.error(f"[CONCEPT-EMB] Failed to connect to Qdrant: {e}")
                raise
        return self._qdrant_client

    def _get_neo4j_driver(self):
        """Recupere le driver Neo4j (lazy loading)."""
        if self._neo4j_driver is None:
            try:
                from knowbase.neo4j_custom.client import get_neo4j_client
                self._neo4j_driver = get_neo4j_client()
            except Exception as e:
                logger.error(f"[CONCEPT-EMB] Failed to connect to Neo4j: {e}")
                raise
        return self._neo4j_driver

    def _get_embedder(self):
        """Recupere l'embedder multilingue (lazy loading)."""
        if self._embedder is None:
            try:
                from knowbase.common.clients.embeddings import get_sentence_transformer
                self._embedder = get_sentence_transformer()
            except Exception as e:
                logger.error(f"[CONCEPT-EMB] Failed to initialize embedder: {e}")
                raise
        return self._embedder

    # =========================================================================
    # ETAPE 1: COLLECTION QDRANT
    # =========================================================================

    def ensure_collection_exists(self) -> bool:
        """
        Cree la collection Qdrant si elle n'existe pas.

        Returns:
            True si collection existe ou creee, False si erreur
        """
        try:
            client = self._get_qdrant_client()
            collections = client.get_collections().collections

            if any(c.name == QDRANT_CONCEPTS_COLLECTION for c in collections):
                logger.info(f"[CONCEPT-EMB] Collection {QDRANT_CONCEPTS_COLLECTION} exists")
                return True

            # Creer la collection
            from qdrant_client.models import Distance, VectorParams

            client.create_collection(
                collection_name=QDRANT_CONCEPTS_COLLECTION,
                vectors_config=VectorParams(
                    size=EMBEDDING_DIMENSION,
                    distance=Distance.COSINE,
                ),
            )

            # Creer les index payload pour filtrage efficace
            client.create_payload_index(
                collection_name=QDRANT_CONCEPTS_COLLECTION,
                field_name="tenant_id",
                field_schema="keyword",
            )
            client.create_payload_index(
                collection_name=QDRANT_CONCEPTS_COLLECTION,
                field_name="concept_type",
                field_schema="keyword",
            )
            client.create_payload_index(
                collection_name=QDRANT_CONCEPTS_COLLECTION,
                field_name="embedding_version",
                field_schema="keyword",
            )

            logger.info(f"[CONCEPT-EMB] Created collection {QDRANT_CONCEPTS_COLLECTION}")
            return True

        except Exception as e:
            logger.error(f"[CONCEPT-EMB] Failed to ensure collection: {e}")
            return False

    def get_collection_stats(self) -> Dict[str, Any]:
        """Recupere les stats de la collection."""
        try:
            client = self._get_qdrant_client()
            info = client.get_collection(QDRANT_CONCEPTS_COLLECTION)
            return {
                "points_count": info.points_count,
                "vectors_count": info.vectors_count,
                "status": info.status.value if info.status else "unknown",
            }
        except Exception as e:
            return {"error": str(e)}

    # =========================================================================
    # ETAPE 2: SYNCHRONISATION NEO4J -> QDRANT
    # =========================================================================

    def fetch_concepts_from_neo4j(
        self,
        tenant_id: str = "default",
        modified_since: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Recupere les concepts depuis Neo4j.

        Args:
            tenant_id: Tenant ID
            modified_since: Si specifie, ne retourne que les concepts modifies depuis
            limit: Limite le nombre de concepts (pour tests)

        Returns:
            Liste de concepts avec leurs proprietes
        """
        driver = self._get_neo4j_driver()

        # Construire la requete
        where_clause = "WHERE c.tenant_id = $tenant_id"
        params = {"tenant_id": tenant_id}

        if modified_since:
            where_clause += " AND c.updated_at >= $modified_since"
            params["modified_since"] = modified_since.isoformat()

        limit_clause = f"LIMIT {limit}" if limit else ""

        cypher = f"""
        MATCH (c:CanonicalConcept)
        {where_clause}
        OPTIONAL MATCH (c)-[:HAS_SURFACE_FORM]->(sf:SurfaceForm)
        WITH c, collect(DISTINCT sf.form) AS surface_forms
        RETURN
            c.canonical_id AS canonical_id,
            c.canonical_name AS canonical_name,
            c.concept_type AS concept_type,
            c.unified_definition AS unified_definition,
            c.summary AS summary,
            c.quality_score AS quality_score,
            c.updated_at AS updated_at,
            surface_forms
        ORDER BY c.canonical_name
        {limit_clause}
        """

        concepts = []
        try:
            # Utiliser execute_query du client wrapper
            client = self._get_neo4j_driver()
            results = client.execute_query(cypher, params)

            for record in results:
                concepts.append({
                    "canonical_id": record.get("canonical_id"),
                    "canonical_name": record.get("canonical_name"),
                    "concept_type": record.get("concept_type"),
                    "unified_definition": record.get("unified_definition"),
                    "summary": record.get("summary"),
                    "quality_score": record.get("quality_score") or 0.5,
                    "surface_forms": record.get("surface_forms") or [],
                    "updated_at": record.get("updated_at"),
                })

            logger.info(f"[CONCEPT-EMB] Fetched {len(concepts)} concepts from Neo4j")
            return concepts

        except Exception as e:
            logger.error(f"[CONCEPT-EMB] Failed to fetch concepts: {e}")
            return []

    def sync_concepts(
        self,
        tenant_id: str = "default",
        incremental: bool = True,
        batch_size: int = 100,
    ) -> SyncBatchResult:
        """
        Synchronise les concepts Neo4j vers Qdrant.

        Args:
            tenant_id: Tenant ID
            incremental: Si True, ne sync que les concepts modifies depuis last_sync
            batch_size: Taille des batches pour l'upsert

        Returns:
            SyncBatchResult avec stats
        """
        start_time = time.time()
        result = SyncBatchResult()

        # Assurer que la collection existe
        if not self.ensure_collection_exists():
            result.failed = 1
            result.errors.append("Failed to create/access collection")
            return result

        # Determiner la date de reference pour sync incremental
        modified_since = None
        if incremental and self._last_sync:
            modified_since = self._last_sync
            logger.info(f"[CONCEPT-EMB] Incremental sync since {modified_since}")

        # Recuperer les concepts
        concepts = self.fetch_concepts_from_neo4j(
            tenant_id=tenant_id,
            modified_since=modified_since,
        )
        result.total = len(concepts)

        if not concepts:
            logger.info("[CONCEPT-EMB] No concepts to sync")
            result.duration_ms = (time.time() - start_time) * 1000
            return result

        # Recuperer les hashes existants pour detecter les changements
        existing_hashes = self._get_existing_hashes(tenant_id)

        # Preparer les points a upsert
        points_to_upsert = []
        embedder = self._get_embedder()

        for concept in concepts:
            try:
                # Construire le texte d'embedding (contrat de representation)
                embedding_text = build_concept_embedding_text(
                    canonical_name=concept["canonical_name"],
                    unified_definition=concept["unified_definition"],
                    summary=concept["summary"],
                    surface_forms=concept["surface_forms"],
                )

                # Calculer le hash pour detecter les changements
                text_hash = compute_embedding_hash(embedding_text)
                canonical_id = concept["canonical_id"]

                # Verifier si le concept a change
                existing_hash = existing_hashes.get(canonical_id)
                if existing_hash == text_hash:
                    result.unchanged += 1
                    continue

                # Generer l'embedding avec prefix "passage" pour e5
                # Note: e5 utilise "passage: " pour documents, "query: " pour recherches
                prefixed_text = f"passage: {embedding_text}"
                embedding = embedder.encode([prefixed_text])[0]

                # Construire le payload
                payload = {
                    "canonical_id": canonical_id,
                    "canonical_name": concept["canonical_name"],
                    "concept_type": concept["concept_type"] or "UNKNOWN",
                    "tenant_id": tenant_id,
                    "quality_score": concept["quality_score"],
                    "surface_forms": concept["surface_forms"],
                    "embedding_version": EMBEDDING_VERSION,
                    "embedding_hash": text_hash,
                    "updated_at": datetime.utcnow().isoformat(),
                }

                # Utiliser canonical_id comme point ID (hash pour Qdrant)
                point_id = self._canonical_id_to_point_id(canonical_id)

                points_to_upsert.append({
                    "id": point_id,
                    "vector": embedding.tolist(),
                    "payload": payload,
                })

                if existing_hash is None:
                    result.created += 1
                else:
                    result.updated += 1

            except Exception as e:
                result.failed += 1
                result.errors.append(f"{concept['canonical_name']}: {str(e)}")
                logger.warning(f"[CONCEPT-EMB] Failed to process {concept['canonical_name']}: {e}")

        # Upsert par batches
        if points_to_upsert:
            self._upsert_points_batch(points_to_upsert, batch_size)

        # Mettre a jour last_sync
        self._last_sync = datetime.utcnow()

        result.duration_ms = (time.time() - start_time) * 1000
        logger.info(
            f"[CONCEPT-EMB] Sync completed: {result.created} created, "
            f"{result.updated} updated, {result.unchanged} unchanged, "
            f"{result.failed} failed ({result.duration_ms:.0f}ms)"
        )

        return result

    def _canonical_id_to_point_id(self, canonical_id: str) -> str:
        """
        Convertit un canonical_id en point ID Qdrant.

        Utilise un hash pour avoir un ID stable et unique.
        """
        # Qdrant accepte les UUIDs ou integers
        # On utilise un hash du canonical_id
        hash_bytes = hashlib.sha256(canonical_id.encode()).digest()[:16]
        # Convertir en UUID format
        import uuid
        return str(uuid.UUID(bytes=hash_bytes))

    def _get_existing_hashes(self, tenant_id: str) -> Dict[str, str]:
        """
        Recupere les hashes existants pour un tenant.

        Permet de detecter les concepts qui ont change.
        """
        try:
            client = self._get_qdrant_client()
            from qdrant_client.models import Filter, FieldCondition, MatchValue

            # Scroll tous les points du tenant
            hashes = {}
            offset = None

            while True:
                results, offset = client.scroll(
                    collection_name=QDRANT_CONCEPTS_COLLECTION,
                    scroll_filter=Filter(
                        must=[
                            FieldCondition(
                                key="tenant_id",
                                match=MatchValue(value=tenant_id),
                            )
                        ]
                    ),
                    limit=1000,
                    offset=offset,
                    with_payload=["canonical_id", "embedding_hash"],
                    with_vectors=False,
                )

                for point in results:
                    canonical_id = point.payload.get("canonical_id")
                    embedding_hash = point.payload.get("embedding_hash")
                    if canonical_id and embedding_hash:
                        hashes[canonical_id] = embedding_hash

                if offset is None:
                    break

            return hashes

        except Exception as e:
            logger.warning(f"[CONCEPT-EMB] Failed to get existing hashes: {e}")
            return {}

    def _upsert_points_batch(
        self,
        points: List[Dict[str, Any]],
        batch_size: int = 100,
    ) -> None:
        """Upsert les points par batches."""
        client = self._get_qdrant_client()
        from qdrant_client.models import PointStruct

        for i in range(0, len(points), batch_size):
            batch = points[i:i + batch_size]
            point_structs = [
                PointStruct(
                    id=p["id"],
                    vector=p["vector"],
                    payload=p["payload"],
                )
                for p in batch
            ]
            client.upsert(
                collection_name=QDRANT_CONCEPTS_COLLECTION,
                points=point_structs,
            )
            logger.debug(f"[CONCEPT-EMB] Upserted batch {i//batch_size + 1}")

    # =========================================================================
    # ETAPE 5: OBSERVABILITE
    # =========================================================================

    def get_status(self, tenant_id: str = "default") -> ConceptSemanticStatus:
        """
        Retourne le statut du service semantic concepts.

        Permet au frontend/API de savoir si le matching cross-lingue est disponible.
        """
        status = ConceptSemanticStatus()

        try:
            client = self._get_qdrant_client()
            collections = client.get_collections().collections

            status.collection_exists = any(
                c.name == QDRANT_CONCEPTS_COLLECTION for c in collections
            )

            if not status.collection_exists:
                status.message = f"Collection {QDRANT_CONCEPTS_COLLECTION} not found"
                return status

            # Compter les concepts du tenant
            from qdrant_client.models import Filter, FieldCondition, MatchValue

            count_result = client.count(
                collection_name=QDRANT_CONCEPTS_COLLECTION,
                count_filter=Filter(
                    must=[
                        FieldCondition(
                            key="tenant_id",
                            match=MatchValue(value=tenant_id),
                        )
                    ]
                ),
            )
            status.concept_count = count_result.count

            if status.concept_count == 0:
                status.message = f"No concepts indexed for tenant {tenant_id}"
                return status

            # Service disponible
            status.available = True
            status.last_sync = self._last_sync.isoformat() if self._last_sync else None
            status.message = f"{status.concept_count} concepts indexed"

        except Exception as e:
            status.message = f"Error: {str(e)}"
            logger.warning(f"[CONCEPT-EMB] Status check failed: {e}")

        return status


# =============================================================================
# SINGLETON
# =============================================================================

_concept_embedding_service: Optional[ConceptEmbeddingService] = None


def get_concept_embedding_service() -> ConceptEmbeddingService:
    """Retourne l'instance singleton du ConceptEmbeddingService."""
    global _concept_embedding_service
    if _concept_embedding_service is None:
        _concept_embedding_service = ConceptEmbeddingService()
    return _concept_embedding_service


__all__ = [
    "QDRANT_CONCEPTS_COLLECTION",
    "EMBEDDING_VERSION",
    "EMBEDDING_DIMENSION",
    "build_concept_embedding_text",
    "compute_embedding_hash",
    "SyncStatus",
    "ConceptSyncResult",
    "SyncBatchResult",
    "ConceptSemanticStatus",
    "ConceptEmbeddingService",
    "get_concept_embedding_service",
]
