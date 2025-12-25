"""
OSMOSE Integration Wrapper - Phase 1.5

Connecte les pipelines d'ingestion existants (PPTX/PDF) avec le pipeline
sémantique OSMOSE Phase 1 V2.1.

Ce module permet:
- Double storage: Qdrant "knowbase" (chunks) + Proto-KG (concepts)
- Feature flags pour activation progressive
- Réutilisation code existant
- Migration sans breaking changes

Architecture:
    Document → Ingestion Pipeline → Qdrant "knowbase"
                                  ↓
                      OSMOSE Semantic Pipeline → Proto-KG (Neo4j + Qdrant)

Author: OSMOSE Phase 1.5
Date: 2025-10-14
"""

from pathlib import Path
from typing import Dict, List, Optional, Any
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime

from knowbase.semantic.semantic_pipeline_v2 import SemanticPipelineV2, process_document_semantic_v2
from knowbase.common.llm_router import get_llm_router
from knowbase.common.clients.qdrant_client import get_qdrant_client
from knowbase.config.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class OsmoseIntegrationConfig:
    """Configuration pour l'intégration OSMOSE."""

    # Feature flags
    enable_osmose: bool = True
    osmose_for_pptx: bool = True
    osmose_for_pdf: bool = True

    # Filtres
    min_text_length: int = 500  # Skip si texte < 500 caractères
    max_text_length: int = 1_000_000  # Skip si texte trop long

    # Performance
    timeout_seconds: int = 300  # 5 minutes max par document
    enable_hierarchy: bool = True
    enable_relations: bool = True

    # Storage
    store_in_proto_kg: bool = True
    proto_kg_collection: str = "concepts_proto"

    # Tenant
    default_tenant_id: str = "default"

    # Phase 2 - Typed Relations (RelationExtractionEngine)
    enable_phase2_relations: bool = True  # Extraction relations typées Phase 2
    phase2_relation_strategy: str = "llm_first"  # "llm_first", "hybrid", "pattern_only"
    phase2_relation_min_confidence: float = 0.60  # Seuil minimum confidence

    @classmethod
    def from_env(cls) -> "OsmoseIntegrationConfig":
        """Charge configuration depuis variables d'environnement."""
        settings = get_settings()

        # Settings est un objet Pydantic BaseSettings, pas un dict
        # Utiliser getattr() avec valeur par défaut
        return cls(
            enable_osmose=getattr(settings, "enable_osmose_pipeline", True),
            osmose_for_pptx=getattr(settings, "osmose_for_pptx", True),
            osmose_for_pdf=getattr(settings, "osmose_for_pdf", True),
            min_text_length=getattr(settings, "osmose_min_text_length", 500),
            max_text_length=getattr(settings, "osmose_max_text_length", 1_000_000),
            timeout_seconds=getattr(settings, "osmose_timeout_seconds", 300),
            enable_hierarchy=getattr(settings, "osmose_enable_hierarchy", True),
            enable_relations=getattr(settings, "osmose_enable_relations", True),
            store_in_proto_kg=getattr(settings, "osmose_store_proto_kg", True),
            proto_kg_collection=getattr(settings, "osmose_proto_kg_collection", "concepts_proto"),
            default_tenant_id=getattr(settings, "osmose_default_tenant", "default"),
            # Phase 2 - Typed Relations
            enable_phase2_relations=getattr(settings, "osmose_enable_phase2_relations", True),
            phase2_relation_strategy=getattr(settings, "osmose_phase2_relation_strategy", "llm_first"),
            phase2_relation_min_confidence=getattr(settings, "osmose_phase2_relation_min_confidence", 0.60),
        )


@dataclass
class OsmoseIntegrationResult:
    """Résultat OSMOSE Pure (sans legacy)."""

    # Métadonnées document
    document_id: str
    document_title: str
    document_path: str
    document_type: str  # "pptx" ou "pdf"

    # Résultats OSMOSE (seule source de vérité)
    osmose_success: bool = False
    osmose_error: Optional[str] = None

    # Métriques extraction
    concepts_extracted: int = 0  # Total concepts bruts extraits
    canonical_concepts: int = 0  # Concepts canoniques après unification
    topics_segmented: int = 0  # Topics identifiés
    concept_connections: int = 0  # Connexions cross-documents

    # Storage Proto-KG
    proto_kg_concepts_stored: int = 0  # Concepts dans Neo4j
    proto_kg_relations_stored: int = 0  # Relations dans Neo4j
    proto_kg_embeddings_stored: int = 0  # Embeddings dans Qdrant concepts_proto

    # Phase 2 - Typed Relations (RelationExtractionEngine)
    phase2_relations_extracted: int = 0  # Relations typées extraites
    phase2_relations_stored: int = 0  # Relations typées stockées dans Neo4j
    phase2_relations_by_type: Dict[str, int] = field(default_factory=dict)  # Stats par type

    # Performance
    osmose_duration_seconds: float = 0.0
    total_duration_seconds: float = 0.0

    # Timestamps
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise en dictionnaire."""
        return {
            "document_id": self.document_id,
            "document_title": self.document_title,
            "document_path": self.document_path,
            "document_type": self.document_type,
            "osmose_pure": {
                "success": self.osmose_success,
                "error": self.osmose_error,
                "concepts_extracted": self.concepts_extracted,
                "canonical_concepts": self.canonical_concepts,
                "topics_segmented": self.topics_segmented,
                "concept_connections": self.concept_connections,
                "duration_seconds": self.osmose_duration_seconds,
            },
            "proto_kg_storage": {
                "concepts_stored": self.proto_kg_concepts_stored,
                "relations_stored": self.proto_kg_relations_stored,
                "embeddings_stored": self.proto_kg_embeddings_stored,
            },
            "phase2_relations": {
                "relations_extracted": self.phase2_relations_extracted,
                "relations_stored": self.phase2_relations_stored,
                "relations_by_type": self.phase2_relations_by_type,
            },
            "total_duration_seconds": self.total_duration_seconds,
            "timestamp": self.timestamp,
        }


class OsmoseIntegrationService:
    """
    Service d'intégration OSMOSE.

    Orchestre les pipelines d'ingestion classique (chunks) et OSMOSE (concepts).
    """

    def __init__(
        self,
        config: Optional[OsmoseIntegrationConfig] = None,
        semantic_pipeline: Optional[SemanticPipelineV2] = None
    ):
        """
        Initialise le service d'intégration.

        Args:
            config: Configuration (charge depuis env si None)
            semantic_pipeline: Pipeline sémantique (crée si None)
        """
        self.config = config or OsmoseIntegrationConfig.from_env()
        self.semantic_pipeline = semantic_pipeline

        logger.info(f"[OSMOSE] Integration service initialized - OSMOSE enabled: {self.config.enable_osmose}")

    async def _get_semantic_pipeline(self) -> SemanticPipelineV2:
        """Lazy init du pipeline sémantique."""
        if self.semantic_pipeline is None:
            from knowbase.semantic.config import get_semantic_config

            llm_router = get_llm_router()
            semantic_config = get_semantic_config(reload=True)  # Force reload config

            # SemanticPipelineV2 crée ses propres composants en interne
            self.semantic_pipeline = SemanticPipelineV2(
                llm_router=llm_router,
                config=semantic_config
            )

            logger.info("[OSMOSE] Semantic pipeline initialized")

        return self.semantic_pipeline

    async def _extract_phase2_relations(
        self,
        canonical_concepts: List[Dict[str, Any]],
        text_content: str,
        document_id: str,
        document_name: str,
        tenant_id: str = "default"
    ) -> Dict[str, Any]:
        """
        Extraction relations typées Phase 2 via RelationExtractionEngine.

        Cette méthode utilise le module Phase 2 pour extraire des relations
        sémantiques typées (PART_OF, REQUIRES, REPLACES, etc.) entre les concepts.

        Args:
            canonical_concepts: Concepts canoniques extraits par OSMOSE
            text_content: Texte complet du document
            document_id: ID du document
            document_name: Nom du document
            tenant_id: ID tenant

        Returns:
            Dict avec statistiques:
            {
                "relations_extracted": int,
                "relations_stored": int,
                "relations_by_type": Dict[str, int]
            }
        """
        stats = {
            "relations_extracted": 0,
            "relations_stored": 0,
            "relations_by_type": {}
        }

        if not self.config.enable_phase2_relations:
            logger.info(f"[OSMOSE Phase 2] Typed relations extraction disabled")
            return stats

        if not canonical_concepts:
            logger.info(f"[OSMOSE Phase 2] No concepts to extract relations from")
            return stats

        try:
            from knowbase.relations.extraction_engine import RelationExtractionEngine
            from knowbase.relations.neo4j_writer import Neo4jRelationshipWriter
            from knowbase.config.feature_flags import is_feature_enabled

            # Vérifier feature flag global
            if not is_feature_enabled("enable_llm_relation_enrichment"):
                logger.info(
                    "[OSMOSE Phase 2] LLM relation enrichment feature flag disabled, "
                    "using pattern_only strategy"
                )
                strategy = "pattern_only"
            else:
                strategy = self.config.phase2_relation_strategy

            logger.info(
                f"[OSMOSE Phase 2] Extracting typed relations for {document_id} "
                f"({len(canonical_concepts)} concepts, strategy={strategy})"
            )

            # Convertir concepts OSMOSE vers format RelationExtractionEngine
            concepts_for_extraction = []
            for concept in canonical_concepts:
                concepts_for_extraction.append({
                    "concept_id": f"concept-{concept.get('canonical_name', '').lower().replace(' ', '-')}",
                    "canonical_name": concept.get("canonical_name", ""),
                    "surface_forms": concept.get("aliases", []),
                    "concept_type": concept.get("concept_type", "ENTITY")
                })

            # Initialiser le moteur d'extraction
            engine = RelationExtractionEngine(
                strategy=strategy,
                llm_model="gpt-4o-mini",
                min_confidence=self.config.phase2_relation_min_confidence,
                language="EN"  # Multi-lingual via patterns
            )

            # Extraire les relations
            extraction_result = engine.extract_relations(
                concepts=concepts_for_extraction,
                full_text=text_content,
                document_id=document_id,
                document_name=document_name,
                chunk_ids=[]
            )

            stats["relations_extracted"] = extraction_result.total_relations_extracted
            stats["relations_by_type"] = {
                str(k.value if hasattr(k, 'value') else k): v
                for k, v in extraction_result.relations_by_type.items()
            }

            logger.info(
                f"[OSMOSE Phase 2] Extracted {stats['relations_extracted']} typed relations "
                f"in {extraction_result.extraction_time_seconds:.2f}s"
            )

            # Stocker dans Neo4j si relations extraites
            if extraction_result.relations:
                writer = Neo4jRelationshipWriter(tenant_id=tenant_id)

                write_stats = writer.write_relations(
                    relations=extraction_result.relations,
                    document_id=document_id,
                    document_name=document_name
                )

                stats["relations_stored"] = write_stats.get("created", 0) + write_stats.get("updated", 0)

                logger.info(
                    f"[OSMOSE Phase 2] ✅ Stored {stats['relations_stored']} typed relations "
                    f"(created: {write_stats.get('created', 0)}, updated: {write_stats.get('updated', 0)})"
                )

            return stats

        except ImportError as e:
            logger.warning(f"[OSMOSE Phase 2] RelationExtractionEngine not available: {e}")
            return stats

        except Exception as e:
            logger.error(
                f"[OSMOSE Phase 2] Typed relations extraction failed for {document_id}: {e}",
                exc_info=True
            )
            return stats

    def _should_process_with_osmose(
        self,
        document_type: str,
        text_content: str
    ) -> tuple[bool, Optional[str]]:
        """
        Détermine si le document doit être traité avec OSMOSE.

        Args:
            document_type: Type document ("pptx" ou "pdf")
            text_content: Contenu textuel du document

        Returns:
            (should_process, skip_reason)
        """
        # Feature flag global désactivé
        if not self.config.enable_osmose:
            return False, "OSMOSE globally disabled"

        # Feature flag par type de document
        if document_type == "pptx" and not self.config.osmose_for_pptx:
            return False, "OSMOSE disabled for PPTX"

        if document_type == "pdf" and not self.config.osmose_for_pdf:
            return False, "OSMOSE disabled for PDF"

        # Filtre par longueur texte
        text_length = len(text_content)

        if text_length < self.config.min_text_length:
            return False, f"Text too short: {text_length} < {self.config.min_text_length}"

        if text_length > self.config.max_text_length:
            return False, f"Text too long: {text_length} > {self.config.max_text_length}"

        return True, None

    async def _store_osmose_results(
        self,
        osmose_result: Dict[str, Any],
        document_id: str,
        tenant_id: str = "default"
    ) -> Dict[str, int]:
        """
        Stocke les résultats OSMOSE dans Proto-KG (Neo4j + Qdrant).

        Architecture Proto-KG:
        - Neo4j: Concepts canoniques + relations sémantiques
        - Qdrant "concepts_proto": Embeddings des concepts

        Args:
            osmose_result: Résultats du pipeline OSMOSE
            document_id: ID du document
            tenant_id: Tenant ID pour multi-tenancy

        Returns:
            Dict avec statistiques de stockage (concepts_stored, relations_stored, embeddings_stored)
        """
        stats = {
            "concepts_stored": 0,
            "relations_stored": 0,
            "embeddings_stored": 0
        }

        if not self.config.store_in_proto_kg:
            logger.info(f"[OSMOSE PURE] Proto-KG storage disabled - skipping for {document_id}")
            return stats

        try:
            # Extraire données depuis result["data"]
            osmose_data = osmose_result.get("data", {})
            canonical_concepts = osmose_data.get("canonical_concepts", [])
            concept_connections = osmose_data.get("connections", [])
            topics = osmose_data.get("topics", [])

            logger.info(
                f"[OSMOSE PURE] Proto-KG storage for {document_id}: "
                f"{len(canonical_concepts)} canonical concepts, "
                f"{len(concept_connections)} connections, "
                f"{len(topics)} topics"
            )

            # ===== 1. Stockage Neo4j (Graph Structure) =====
            from knowbase.api.services.proto_kg_service import ProtoKGService

            proto_kg_service = ProtoKGService(tenant_id=tenant_id)

            # Créer nœuds pour chaque concept canonique
            neo4j_concept_ids = []
            for concept in canonical_concepts:
                try:
                    # Créer nœud Concept dans Neo4j
                    concept_node_id = await proto_kg_service.create_canonical_concept(
                        canonical_name=concept.get("canonical_name"),
                        concept_type=concept.get("concept_type", "ENTITY"),
                        unified_definition=concept.get("unified_definition", ""),
                        aliases=concept.get("aliases", []),
                        languages=concept.get("languages", []),
                        source_documents=[document_id],
                        parent_concept=concept.get("parent_concept"),
                        quality_score=concept.get("quality_score", 0.0)
                    )
                    if concept_node_id:
                        neo4j_concept_ids.append(concept_node_id)
                        stats["concepts_stored"] += 1

                except Exception as e:
                    logger.error(f"[OSMOSE PURE] Neo4j concept creation failed: {e}")

            # Créer relations entre concepts
            for connection in concept_connections:
                try:
                    rel_id = await proto_kg_service.create_concept_relation(
                        source_concept=connection.get("canonical_concept_name"),
                        target_concept=connection.get("related_concept"),
                        relation_type=connection.get("relation_type", "RELATED_TO"),
                        document_id=connection.get("document_id"),
                        document_role=connection.get("document_role", "REFERENCES")
                    )
                    if rel_id:
                        stats["relations_stored"] += 1

                except Exception as e:
                    logger.error(f"[OSMOSE PURE] Neo4j relation creation failed: {e}")

            logger.info(f"[OSMOSE PURE] Neo4j: {stats['concepts_stored']} concepts + {stats['relations_stored']} relations")

            # ===== 2. Stockage Qdrant concepts_proto (Embeddings) =====
            from qdrant_client.models import PointStruct
            import uuid

            qdrant_client = get_qdrant_client()

            # Créer collection concepts_proto si nécessaire
            from knowbase.common.clients import ensure_qdrant_collection
            ensure_qdrant_collection(self.config.proto_kg_collection, 1024)  # multilingual-e5-large

            # Encoder les concepts avec multilingual-e5-large (via EmbeddingModelManager)
            from knowbase.common.clients.embeddings import get_embedding_manager
            embedding_manager = get_embedding_manager()
            embedder = embedding_manager.get_model()  # Utilise le manager avec auto-unload

            points = []
            for i, concept in enumerate(canonical_concepts):
                canonical_name = concept.get("canonical_name", "")
                definition = concept.get("unified_definition", "")

                # Créer texte pour embedding (nom + définition)
                text_for_embedding = f"{canonical_name}. {definition}"

                # Encoder
                embedding = embedder.encode([text_for_embedding], normalize_embeddings=True)[0].tolist()

                # Créer point Qdrant
                point = PointStruct(
                    id=str(uuid.uuid4()),
                    vector=embedding,
                    payload={
                        "canonical_name": canonical_name,
                        "concept_type": concept.get("concept_type", "ENTITY"),
                        "unified_definition": definition[:1000],  # Max 1000 chars
                        "aliases": concept.get("aliases", [])[:20],  # Max 20 aliases
                        "languages": concept.get("languages", []),
                        "source_documents": [document_id],
                        "quality_score": concept.get("quality_score", 0.0),
                        "tenant_id": tenant_id,
                        "neo4j_concept_id": neo4j_concept_ids[i] if i < len(neo4j_concept_ids) else None
                    }
                )
                points.append(point)

            # Upsert dans Qdrant
            if points:
                qdrant_client.upsert(
                    collection_name=self.config.proto_kg_collection,
                    points=points
                )
                stats["embeddings_stored"] = len(points)
                logger.info(f"[OSMOSE PURE] Qdrant: {len(points)} concept embeddings stored")

            logger.info(
                f"[OSMOSE PURE] Proto-KG storage completed for {document_id}:\n"
                f"  - {stats['concepts_stored']} concepts in Neo4j\n"
                f"  - {stats['relations_stored']} relations in Neo4j\n"
                f"  - {stats['embeddings_stored']} embeddings in Qdrant concepts_proto"
            )
            return stats

        except Exception as e:
            logger.error(f"[OSMOSE PURE] Proto-KG storage failed for {document_id}: {e}", exc_info=True)
            return stats  # Retourner stats même en cas d'erreur (peut être partiellement rempli)

    async def process_document_with_osmose(
        self,
        document_id: str,
        document_title: str,
        document_path: Path,
        text_content: str,
        tenant_id: Optional[str] = None
    ) -> OsmoseIntegrationResult:
        """
        Pipeline OSMOSE Pure - Seule source de vérité.

        Cette fonction remplace complètement l'ingestion legacy.
        Pas de chunks, pas de Qdrant "knowbase" - uniquement Proto-KG.

        Args:
            document_id: ID unique du document
            document_title: Titre du document
            document_path: Chemin du fichier
            text_content: Contenu textuel extrait
            tenant_id: ID tenant (multi-tenancy)

        Returns:
            Résultat OSMOSE Pure (concepts canoniques + Proto-KG)
        """
        start_time = asyncio.get_event_loop().time()

        # Déterminer type de document
        document_type = document_path.suffix.lower().replace(".", "")

        # Résultat OSMOSE Pure
        result = OsmoseIntegrationResult(
            document_id=document_id,
            document_title=document_title,
            document_path=str(document_path),
            document_type=document_type,
        )

        # Vérifier si OSMOSE doit être activé (filtres)
        logger.info(f"[DEBUG] 🎯 OSMOSE Step 1: Checking should_process for {document_id}")
        should_process, skip_reason = self._should_process_with_osmose(
            document_type, text_content
        )
        logger.info(f"[DEBUG] 🔍 should_process={should_process}, skip_reason={skip_reason}")

        if not should_process:
            logger.warning(f"[OSMOSE PURE] Skipping document {document_id}: {skip_reason}")
            result.osmose_success = False
            result.osmose_error = skip_reason
            result.total_duration_seconds = asyncio.get_event_loop().time() - start_time
            return result

        # Traitement OSMOSE Pure
        logger.info(f"[OSMOSE PURE] Processing document {document_id} ({len(text_content)} chars)")
        logger.info(f"[DEBUG] 🎯 OSMOSE Step 2: Starting semantic pipeline processing")
        osmose_start = asyncio.get_event_loop().time()

        try:
            logger.info(f"[OSMOSE PURE] Processing document {document_id} with semantic pipeline...")
            logger.info(f"[DEBUG] 🎯 OSMOSE Step 3: Calling _get_semantic_pipeline()")

            # Appeler pipeline OSMOSE V2.1
            pipeline = await self._get_semantic_pipeline()
            logger.info(f"[DEBUG] 🎯 OSMOSE Step 4: Pipeline obtained, calling process_document()")

            osmose_result = await asyncio.wait_for(
                pipeline.process_document(
                    document_id=document_id,
                    document_title=document_title,
                    document_path=str(document_path),
                    text_content=text_content,
                    tenant_id=tenant_id or self.config.default_tenant_id,
                    enable_llm=True
                ),
                timeout=self.config.timeout_seconds
            )
            logger.info(f"[DEBUG] 🎯 OSMOSE Step 5: process_document() returned, result keys: {list(osmose_result.keys()) if isinstance(osmose_result, dict) else type(osmose_result)}")

            # Extraire métriques OSMOSE depuis result["data"]
            osmose_data = osmose_result.get("data", {})
            result.concepts_extracted = len(osmose_data.get("concepts", []))
            result.canonical_concepts = len(osmose_data.get("canonical_concepts", []))
            result.topics_segmented = len(osmose_data.get("topics", []))
            result.concept_connections = len(osmose_data.get("connections", []))

            logger.info(
                f"[DEBUG] 🔍 Métriques extraites: "
                f"concepts={result.concepts_extracted}, "
                f"canonical={result.canonical_concepts}, "
                f"topics={result.topics_segmented}, "
                f"connections={result.concept_connections}"
            )

            # Stocker dans Proto-KG (Neo4j + Qdrant concepts_proto)
            storage_stats = await self._store_osmose_results(
                osmose_result,
                document_id,
                tenant_id or self.config.default_tenant_id
            )

            # Métriques Proto-KG storage
            if isinstance(storage_stats, dict):
                result.proto_kg_concepts_stored = storage_stats.get("concepts_stored", 0)
                result.proto_kg_relations_stored = storage_stats.get("relations_stored", 0)
                result.proto_kg_embeddings_stored = storage_stats.get("embeddings_stored", 0)

            # ===== Phase 2: Extraction Relations Typées =====
            # Utilise RelationExtractionEngine pour extraire des relations sémantiques
            # typées (PART_OF, REQUIRES, REPLACES, etc.) entre concepts
            canonical_concepts_list = osmose_data.get("canonical_concepts", [])

            if canonical_concepts_list and self.config.enable_phase2_relations:
                logger.info(f"[DEBUG] 🎯 OSMOSE Step 6: Starting Phase 2 typed relations extraction")

                phase2_stats = await self._extract_phase2_relations(
                    canonical_concepts=canonical_concepts_list,
                    text_content=text_content,
                    document_id=document_id,
                    document_name=document_title,
                    tenant_id=tenant_id or self.config.default_tenant_id
                )

                # Métriques Phase 2
                result.phase2_relations_extracted = phase2_stats.get("relations_extracted", 0)
                result.phase2_relations_stored = phase2_stats.get("relations_stored", 0)
                result.phase2_relations_by_type = phase2_stats.get("relations_by_type", {})

                logger.info(
                    f"[DEBUG] 🔍 Phase 2 stats: "
                    f"extracted={result.phase2_relations_extracted}, "
                    f"stored={result.phase2_relations_stored}"
                )

            result.osmose_success = True
            result.osmose_error = None

            logger.info(
                f"[OSMOSE PURE] ✅ Document {document_id} processed successfully:\n"
                f"  - {result.canonical_concepts} canonical concepts\n"
                f"  - {result.concept_connections} cross-document connections\n"
                f"  - {result.topics_segmented} topics segmented\n"
                f"  - Proto-KG: {result.proto_kg_concepts_stored} concepts + {result.proto_kg_relations_stored} relations stored\n"
                f"  - Phase 2: {result.phase2_relations_extracted} typed relations extracted, {result.phase2_relations_stored} stored"
            )

        except asyncio.TimeoutError:
            error_msg = f"OSMOSE processing timeout after {self.config.timeout_seconds}s"
            logger.error(f"[OSMOSE] {error_msg} for document {document_id}")
            result.osmose_success = False
            result.osmose_error = error_msg

        except Exception as e:
            error_msg = f"OSMOSE processing failed: {str(e)}"
            logger.error(f"[OSMOSE] {error_msg} for document {document_id}", exc_info=True)
            result.osmose_success = False
            result.osmose_error = error_msg

        # Timing final
        osmose_end = asyncio.get_event_loop().time()
        result.osmose_duration_seconds = osmose_end - osmose_start
        result.total_duration_seconds = osmose_end - start_time

        return result


# Helper function pour simplifier l'usage
async def process_document_with_osmose(
    document_id: str,
    document_title: str,
    document_path: Path,
    text_content: str,
    tenant_id: Optional[str] = None,
    config: Optional[OsmoseIntegrationConfig] = None
) -> OsmoseIntegrationResult:
    """
    Helper function pour traiter un document avec OSMOSE Pure.

    Mode OSMOSE Pure: Remplace complètement l'ingestion legacy.
    Pas de chunks, pas de Qdrant "knowbase" - uniquement Proto-KG.

    Usage:
        from knowbase.ingestion.osmose_integration import process_document_with_osmose

        result = await process_document_with_osmose(
            document_id="doc_123",
            document_title="SAP HANA Guide",
            document_path=Path("/path/to/doc.pdf"),
            text_content="...",  # Texte complet du document
            tenant_id="default"
        )

        if result.osmose_success:
            print(f"[OSMOSE PURE] Extracted {result.canonical_concepts} canonical concepts")
            print(f"[OSMOSE PURE] Stored {result.proto_kg_concepts_stored} in Neo4j")

    Args:
        document_id: ID unique du document
        document_title: Titre du document
        document_path: Chemin du fichier
        text_content: Contenu textuel extrait (full text)
        tenant_id: ID tenant (multi-tenancy)
        config: Configuration custom (charge depuis env si None)

    Returns:
        OsmoseIntegrationResult avec métriques Proto-KG
    """
    service = OsmoseIntegrationService(config=config)

    return await service.process_document_with_osmose(
        document_id=document_id,
        document_title=document_title,
        document_path=document_path,
        text_content=text_content,
        tenant_id=tenant_id
    )
