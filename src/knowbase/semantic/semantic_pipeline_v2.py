"""
🌊 OSMOSE Semantic Intelligence V2.1 - Pipeline End-to-End

Pipeline complet d'ingestion sémantique V2.1.

Flow:
1. TopicSegmenter → Segmentation sémantique
2. MultilingualConceptExtractor → Extraction concepts (NER + Clustering + LLM)
3. SemanticIndexer → Canonicalisation cross-lingual
4. ConceptLinker → Linking cross-documents
5. Staging Proto-KG (Neo4j + Qdrant)

Semaine 10 Phase 1 V2.1 - Integration Finale
"""

from typing import Dict, List, Optional
import logging
import time
from datetime import datetime

from knowbase.semantic.models import (
    Topic,
    Concept,
    CanonicalConcept,
    ConceptConnection,
    SemanticProfile
)
from knowbase.semantic.config import get_semantic_config, SemanticConfig
from knowbase.semantic.segmentation.topic_segmenter import TopicSegmenter
from knowbase.semantic.extraction.concept_extractor import MultilingualConceptExtractor
from knowbase.semantic.indexing.semantic_indexer import SemanticIndexer
from knowbase.semantic.linking.concept_linker import ConceptLinker
from knowbase.common.llm_router import LLMRouter

logger = logging.getLogger(__name__)


class SemanticPipelineV2:
    """
    Pipeline sémantique V2.1 complet - Orchestration end-to-end.

    Composants:
    - TopicSegmenter: Segmentation sémantique (windowing + clustering)
    - MultilingualConceptExtractor: Extraction concepts multilingues
    - SemanticIndexer: Canonicalisation cross-lingual
    - ConceptLinker: Linking cross-documents

    USP KnowWhere:
    - Cross-lingual unification automatique
    - Language-agnostic knowledge graph
    - Meilleur que Copilot/Gemini sur documents multilingues
    """

    def __init__(
        self,
        llm_router: LLMRouter,
        config: Optional[SemanticConfig] = None
    ):
        """
        Initialise le pipeline V2.1.

        Args:
            llm_router: Router LLM pour extraction et canonicalisation
            config: Configuration (optionnel, charge depuis YAML)
        """
        self.llm_router = llm_router
        self.config = config or get_semantic_config()

        # ⚙️ Configurer niveau de log depuis YAML
        self._configure_logging()

        # Composants
        self.topic_segmenter = TopicSegmenter(self.config)
        self.concept_extractor = MultilingualConceptExtractor(llm_router, self.config)
        self.semantic_indexer = SemanticIndexer(llm_router, self.config)
        self.concept_linker = ConceptLinker(llm_router, self.config)

        logger.info("[OSMOSE] SemanticPipelineV2 initialized")

    def _configure_logging(self):
        """Configure le niveau de log depuis la config YAML."""
        try:
            log_level_str = self.config.logging.level.upper()
            log_level = getattr(logging, log_level_str, logging.INFO)

            # Configurer logger "knowbase.semantic" et ses enfants
            semantic_logger = logging.getLogger("knowbase.semantic")
            semantic_logger.setLevel(log_level)

            # S'assurer qu'il y a au moins un handler
            if not semantic_logger.handlers:
                handler = logging.StreamHandler()
                handler.setLevel(log_level)
                formatter = logging.Formatter(
                    "[OSMOSE] %(asctime)s - %(name)s - %(levelname)s - %(message)s"
                )
                handler.setFormatter(formatter)
                semantic_logger.addHandler(handler)

            logger.info(f"[OSMOSE] Logger configured: level={log_level_str}")
        except Exception as e:
            logger.warning(f"[OSMOSE] Failed to configure logging: {e}")

    async def process_document(
        self,
        document_id: str,
        document_title: str,
        document_path: str,
        text_content: str,
        tenant_id: str = "default",
        enable_llm: bool = True,
        enable_hierarchy: bool = True,
        enable_relations: bool = True
    ) -> Dict:
        """
        Traite un document via pipeline V2.1 complet.

        Pipeline:
        1. TopicSegmenter → Topics sémantiques
        2. ConceptExtractor → Concepts par topic
        3. SemanticIndexer → Concepts canoniques unifiés
        4. ConceptLinker → Connexions concept ↔ document
        5. SemanticProfile → Métriques et metadata

        Args:
            document_id: ID unique du document
            document_title: Titre du document
            document_path: Chemin du document
            text_content: Texte complet du document
            tenant_id: Tenant ID (multi-tenancy)
            enable_llm: Activer extraction LLM si insuffisant
            enable_hierarchy: Activer construction hiérarchies
            enable_relations: Activer extraction relations

        Returns:
            Résultat du processing avec métriques
        """
        logger.info(f"[DEBUG] 🎯 SemanticPipelineV2.process_document() CALLED for {document_id}")
        logger.info(f"[DEBUG] 🔍 text_content length: {len(text_content)}, tenant: {tenant_id}")

        start_time = time.time()

        logger.info(
            f"[OSMOSE] 🌊 Processing document '{document_title}' "
            f"(id={document_id}, tenant={tenant_id})"
        )

        try:
            # 1. Topic Segmentation
            logger.info("[OSMOSE] Step 1/5: Topic Segmentation")
            logger.info(f"[DEBUG] 🎯 Calling topic_segmenter.segment_document()...")
            topics = await self.topic_segmenter.segment_document(
                document_id=document_id,
                text=text_content,
                detect_language=True
            )
            logger.info(f"[OSMOSE] ✅ {len(topics)} topics segmented")

            if not topics:
                logger.warning("[OSMOSE] No topics found, aborting pipeline")
                return self._build_result(
                    document_id=document_id,
                    document_path=document_path,
                    tenant_id=tenant_id,
                    topics=[],
                    all_concepts=[],
                    canonical_concepts=[],
                    connections=[],
                    processing_time_ms=int((time.time() - start_time) * 1000),
                    success=False,
                    error="No topics found"
                )

            # 2. Concept Extraction
            logger.info("[OSMOSE] Step 2/5: Concept Extraction")
            all_concepts: List[Concept] = []

            for i, topic in enumerate(topics):
                logger.debug(
                    f"[OSMOSE] Extracting concepts from topic {i+1}/{len(topics)}"
                )
                concepts = await self.concept_extractor.extract_concepts(
                    topic=topic,
                    enable_llm=enable_llm
                )
                all_concepts.extend(concepts)

                # Stocker concepts dans topic pour traçabilité
                topic.concepts = concepts

            logger.info(f"[OSMOSE] ✅ {len(all_concepts)} concepts extracted")

            if not all_concepts:
                logger.warning("[OSMOSE] No concepts extracted, aborting pipeline")
                return self._build_result(
                    document_id=document_id,
                    document_path=document_path,
                    tenant_id=tenant_id,
                    topics=topics,
                    all_concepts=[],
                    canonical_concepts=[],
                    connections=[],
                    processing_time_ms=int((time.time() - start_time) * 1000),
                    success=False,
                    error="No concepts extracted"
                )

            # 3. Semantic Indexing (Canonicalization)
            logger.info("[OSMOSE] Step 3/5: Semantic Indexing (Canonicalization)")
            canonical_concepts = await self.semantic_indexer.canonicalize_concepts(
                concepts=all_concepts,
                enable_hierarchy=enable_hierarchy,
                enable_relations=enable_relations
            )
            logger.info(
                f"[OSMOSE] ✅ {len(canonical_concepts)} canonical concepts created "
                f"(unified from {len(all_concepts)})"
            )

            # 4. Concept Linking
            logger.info("[OSMOSE] Step 4/5: Concept Linking")
            connections = self.concept_linker.link_concepts_to_documents(
                canonical_concepts=canonical_concepts,
                document_id=document_id,
                document_title=document_title,
                document_text=text_content
            )
            logger.info(
                f"[OSMOSE] ✅ {len(connections)} concept-document connections created"
            )

            # 5. Build Semantic Profile
            logger.info("[OSMOSE] Step 5/5: Building Semantic Profile")
            processing_time_ms = int((time.time() - start_time) * 1000)

            # Détection langues
            languages_detected = list(set(c.language for c in all_concepts))

            semantic_profile = SemanticProfile(
                document_id=document_id,
                document_path=document_path,
                tenant_id=tenant_id,
                overall_complexity=self._calculate_overall_complexity(topics),
                complexity_zones=[],  # Simplifié pour Phase 1
                domain="general",  # Simplifié pour Phase 1
                domain_confidence=0.0,
                total_topics=len(topics),
                total_concepts=len(all_concepts),
                total_canonical_concepts=len(canonical_concepts),
                languages_detected=languages_detected,
                processing_time_ms=processing_time_ms
            )

            logger.info(
                f"[OSMOSE] ✅ Pipeline V2.1 complete: "
                f"{len(topics)} topics, {len(all_concepts)} concepts, "
                f"{len(canonical_concepts)} canonical, {len(connections)} connections "
                f"({processing_time_ms}ms)"
            )

            # Retourner résultat
            return self._build_result(
                document_id=document_id,
                document_path=document_path,
                tenant_id=tenant_id,
                topics=topics,
                all_concepts=all_concepts,
                canonical_concepts=canonical_concepts,
                connections=connections,
                processing_time_ms=processing_time_ms,
                semantic_profile=semantic_profile,
                success=True
            )

        except Exception as e:
            logger.error(f"[OSMOSE] ❌ Pipeline failed: {e}", exc_info=True)
            processing_time_ms = int((time.time() - start_time) * 1000)

            return self._build_result(
                document_id=document_id,
                document_path=document_path,
                tenant_id=tenant_id,
                topics=[],
                all_concepts=[],
                canonical_concepts=[],
                connections=[],
                processing_time_ms=processing_time_ms,
                success=False,
                error=str(e)
            )

    def _calculate_overall_complexity(self, topics: List[Topic]) -> float:
        """
        Calcule complexité globale du document basée sur topics.

        Critères:
        - Nombre de topics
        - Cohesion moyenne
        - Nombre d'anchors moyen

        Returns:
            Score complexité [0.0, 1.0]
        """
        if not topics:
            return 0.0

        # Moyenne cohesion
        avg_cohesion = sum(t.cohesion_score for t in topics) / len(topics)

        # Normaliser nombre de topics (plus = plus complexe)
        topic_count_score = min(len(topics) / 10.0, 1.0)

        # Complexité = mix cohesion inverse + topic count
        complexity = (1.0 - avg_cohesion) * 0.5 + topic_count_score * 0.5

        return complexity

    def _build_result(
        self,
        document_id: str,
        document_path: str,
        tenant_id: str,
        topics: List[Topic],
        all_concepts: List[Concept],
        canonical_concepts: List[CanonicalConcept],
        connections: List[ConceptConnection],
        processing_time_ms: int,
        semantic_profile: Optional[SemanticProfile] = None,
        success: bool = True,
        error: Optional[str] = None
    ) -> Dict:
        """
        Construit résultat du pipeline.

        Returns:
            Dict avec toutes les métriques et données
        """
        result = {
            "document_id": document_id,
            "document_path": document_path,
            "tenant_id": tenant_id,
            "success": success,
            "processing_time_ms": processing_time_ms,
            "metrics": {
                "topics_count": len(topics),
                "concepts_count": len(all_concepts),
                "canonical_concepts_count": len(canonical_concepts),
                "connections_count": len(connections),
                "languages_detected": list(set(c.language for c in all_concepts)) if all_concepts else [],
                "average_topic_cohesion": sum(t.cohesion_score for t in topics) / len(topics) if topics else 0.0
            },
            "data": {
                "topics": [self._topic_to_dict(t) for t in topics],
                "concepts": [self._concept_to_dict(c) for c in all_concepts],
                "canonical_concepts": [self._canonical_to_dict(c) for c in canonical_concepts],
                "connections": [self._connection_to_dict(c) for c in connections]
            }
        }

        if semantic_profile:
            result["semantic_profile"] = {
                "overall_complexity": semantic_profile.overall_complexity,
                "domain": semantic_profile.domain,
                "total_topics": semantic_profile.total_topics,
                "total_concepts": semantic_profile.total_concepts,
                "total_canonical_concepts": semantic_profile.total_canonical_concepts,
                "languages_detected": semantic_profile.languages_detected
            }

        if error:
            result["error"] = error

        return result

    def _topic_to_dict(self, topic: Topic) -> Dict:
        """Convertit Topic en dict"""
        return {
            "topic_id": topic.topic_id,
            "section_path": topic.section_path,
            "windows_count": len(topic.windows),
            "anchors": topic.anchors,
            "cohesion_score": topic.cohesion_score,
            "concepts_count": len(topic.concepts)
        }

    def _concept_to_dict(self, concept: Concept) -> Dict:
        """Convertit Concept en dict"""
        return {
            "concept_id": concept.concept_id,
            "name": concept.name,
            "type": concept.type.value,
            "language": concept.language,
            "confidence": concept.confidence,
            "extraction_method": concept.extraction_method,
            "source_topic_id": concept.source_topic_id
        }

    def _canonical_to_dict(self, canonical: CanonicalConcept) -> Dict:
        """Convertit CanonicalConcept en dict"""
        return {
            "canonical_id": canonical.canonical_id,
            "canonical_name": canonical.canonical_name,
            "aliases": canonical.aliases,
            "languages": canonical.languages,
            "type": canonical.type.value,
            "definition": canonical.definition,
            "support": canonical.support,
            "confidence": canonical.confidence,
            "hierarchy_parent": canonical.hierarchy_parent,
            "hierarchy_children": canonical.hierarchy_children,
            "related_concepts": canonical.related_concepts
        }

    def _connection_to_dict(self, connection: ConceptConnection) -> Dict:
        """Convertit ConceptConnection en dict"""
        return {
            "connection_id": connection.connection_id,
            "document_id": connection.document_id,
            "document_title": connection.document_title,
            "document_role": connection.document_role.value,
            "canonical_concept_name": connection.canonical_concept_name,
            "similarity": connection.similarity,
            "context": connection.context[:200] if connection.context else ""  # Tronquer
        }


# ============================================
# Helper Functions pour integration facile
# ============================================

async def process_document_semantic_v2(
    document_id: str,
    document_title: str,
    document_path: str,
    text_content: str,
    llm_router: LLMRouter,
    tenant_id: str = "default",
    config: Optional[SemanticConfig] = None
) -> Dict:
    """
    Helper function pour traiter un document.

    Usage:
    ```python
    from knowbase.common.llm_router import get_llm_router

    llm_router = get_llm_router()
    result = await process_document_semantic_v2(
        document_id="doc_001",
        document_title="ISO 27001 Guide",
        document_path="/docs/iso27001.pdf",
        text_content="...",
        llm_router=llm_router
    )

    print(f"Topics: {result['metrics']['topics_count']}")
    print(f"Canonical concepts: {result['metrics']['canonical_concepts_count']}")
    ```

    Args:
        document_id: ID unique du document
        document_title: Titre du document
        document_path: Chemin du document
        text_content: Texte complet
        llm_router: Router LLM
        tenant_id: Tenant ID (multi-tenancy)
        config: Configuration optionnelle

    Returns:
        Résultat du processing avec métriques
    """
    pipeline = SemanticPipelineV2(llm_router=llm_router, config=config)

    return await pipeline.process_document(
        document_id=document_id,
        document_title=document_title,
        document_path=document_path,
        text_content=text_content,
        tenant_id=tenant_id
    )
