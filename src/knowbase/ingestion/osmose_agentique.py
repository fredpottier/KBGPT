"""
OSMOSE Agentique - Phase 1.5 Integration

Remplace SemanticPipelineV2 par Architecture Agentique (6 agents).

Architecture:
    Document → OsmoseAgentique → SupervisorAgent (FSM) → Proto-KG
                                      ↓
                     ExtractorOrchestrator → PatternMiner
                           → GatekeeperDelegate → Neo4j Published

Author: OSMOSE Phase 1.5
Date: 2025-10-15
"""

from pathlib import Path
from typing import Dict, List, Optional, Any
import asyncio
import logging
import os
from datetime import datetime

from knowbase.agents.supervisor.supervisor import SupervisorAgent
from knowbase.agents.base import AgentState
from knowbase.ingestion.osmose_integration import (
    OsmoseIntegrationConfig,
    OsmoseIntegrationResult
)
from knowbase.semantic.segmentation.topic_segmenter import get_topic_segmenter
from knowbase.semantic.config import get_semantic_config
from knowbase.ingestion.text_chunker import get_text_chunker  # Phase 1.6: Chunking
from knowbase.common.clients.qdrant_client import upsert_chunks  # Phase 1.6: Qdrant
from knowbase.semantic.extraction.document_context_generator import (  # Phase 1.8: P0.1
    get_document_context_generator,
    DocumentContext
)

# Configuration du root logger pour que tous les loggers enfants (agents) héritent des handlers
# IMPORTANT: Récupérer les handlers du logger parent (pptx_pipeline) pour les copier au root logger
# Cela permet aux loggers enfants (agents) d'écrire dans le même fichier de log
root_logger = logging.getLogger()

# Trouver le handler du fichier ingest_debug.log depuis n'importe quel logger parent
parent_handlers_found = False
for parent_name in ["knowbase.ingestion.pipelines.pptx_pipeline", "knowbase.ingestion"]:
    parent_logger = logging.getLogger(parent_name)
    if parent_logger.handlers:
        for handler in parent_logger.handlers:
            # Copier le handler au root logger s'il n'est pas déjà présent
            if handler not in root_logger.handlers:
                root_logger.addHandler(handler)
                parent_handlers_found = True
        break

# Si aucun handler parent trouvé, ajouter au moins un StreamHandler pour debug
if not parent_handlers_found and not root_logger.hasHandlers():
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    root_logger.addHandler(console_handler)

# S'assurer que le root logger a le bon niveau
root_logger.setLevel(logging.INFO)

logger = logging.getLogger(__name__)


class OsmoseAgentiqueService:
    """
    Service d'intégration OSMOSE Architecture Agentique Phase 1.5.

    Remplace l'approche directe SemanticPipelineV2 par l'orchestration
    via SupervisorAgent (FSM Master).

    Avantages Phase 1.5:
    - Routing intelligent NO_LLM/SMALL/BIG (maîtrise coûts)
    - Budget caps durs (SMALL: 120, BIG: 8, VISION: 2)
    - Quality gates (STRICT/BALANCED/PERMISSIVE)
    - Rate limiting (500/100/50 RPM)
    - Retry logic (1 retry BIG si Gate < 30%)
    - Multi-tenant quotas (Redis)
    """

    def __init__(
        self,
        config: Optional[OsmoseIntegrationConfig] = None,
        supervisor_config: Optional[Dict[str, Any]] = None
    ):
        """
        Initialise le service agentique.

        Args:
            config: Configuration OSMOSE (legacy, filtres, feature flags)
            supervisor_config: Configuration SupervisorAgent (FSM, retry)
        """
        self.config = config or OsmoseIntegrationConfig.from_env()
        self.supervisor_config = supervisor_config or {}
        self.supervisor: Optional[SupervisorAgent] = None
        self.topic_segmenter = None  # Lazy init
        self.text_chunker = None  # Lazy init (Phase 1.6)
        self.document_context_generator = None  # Lazy init (Phase 1.8: P0.1)

        logger.info(
            f"[OSMOSE AGENTIQUE] Service initialized - OSMOSE enabled: {self.config.enable_osmose}"
        )

    def _get_supervisor(self) -> SupervisorAgent:
        """Lazy init du SupervisorAgent."""
        if self.supervisor is None:
            self.supervisor = SupervisorAgent(config=self.supervisor_config)
            logger.info("[OSMOSE AGENTIQUE] SupervisorAgent initialized")

        return self.supervisor

    def _get_topic_segmenter(self):
        """Lazy init du TopicSegmenter."""
        if self.topic_segmenter is None:
            semantic_config = get_semantic_config()
            self.topic_segmenter = get_topic_segmenter(semantic_config)
            logger.info("[OSMOSE AGENTIQUE] TopicSegmenter initialized")

        return self.topic_segmenter

    def _get_text_chunker(self):
        """Lazy init du TextChunker (Phase 1.6)."""
        if self.text_chunker is None:
            self.text_chunker = get_text_chunker(
                model_name="intfloat/multilingual-e5-large",
                chunk_size=512,
                overlap=128
            )
            logger.info("[OSMOSE AGENTIQUE] TextChunker initialized (512 tokens, overlap 128)")

        return self.text_chunker

    def _get_document_context_generator(self):
        """Lazy init du DocumentContextGenerator (Phase 1.8: P0.1)."""
        if self.document_context_generator is None:
            # Récupérer LLMRouter depuis config
            from knowbase.common.llm_router import get_llm_router
            llm_router = get_llm_router()

            self.document_context_generator = get_document_context_generator(
                llm_router=llm_router,
                cache_ttl_seconds=3600  # 1h cache
            )
            logger.info("[OSMOSE AGENTIQUE] DocumentContextGenerator initialized (cache_ttl=1h)")

        return self.document_context_generator

    def _cross_reference_chunks_and_concepts(
        self,
        chunks: List[Dict[str, Any]],
        chunk_ids: List[str],
        concept_to_chunk_ids: Dict[str, List[str]],
        tenant_id: str
    ) -> None:
        """
        Établit le cross-référencement bidirectionnel Neo4j ↔ Qdrant.

        Après création des chunks, cette méthode :
        1. Récupère le mapping Proto → Canonical depuis Neo4j
        2. Met à jour les chunks Qdrant avec canonical_concept_ids
        3. Met à jour les CanonicalConcepts Neo4j avec chunk_ids

        Args:
            chunks: Liste des chunks créés
            chunk_ids: IDs des chunks dans Qdrant
            concept_to_chunk_ids: Mapping proto_id → chunk_ids
            tenant_id: ID tenant
        """
        from knowbase.common.clients.neo4j_client import get_neo4j_client
        from knowbase.common.clients.qdrant_client import get_qdrant_client
        from knowbase.config.settings import get_settings

        settings = get_settings()
        neo4j_client = get_neo4j_client(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database="neo4j"
        )
        qdrant_client = get_qdrant_client()

        try:
            # Étape 1: Récupérer mapping Proto → Canonical depuis Neo4j
            proto_to_canonical = {}
            with neo4j_client.driver.session(database="neo4j") as session:
                result = session.run("""
                    MATCH (p:ProtoConcept)-[:PROMOTED_TO]->(c:CanonicalConcept)
                    WHERE p.tenant_id = $tenant_id
                    RETURN p.concept_id as proto_id, c.canonical_id as canonical_id
                """, tenant_id=tenant_id)

                for record in result:
                    proto_to_canonical[record["proto_id"]] = record["canonical_id"]

            logger.info(
                f"[OSMOSE AGENTIQUE:CrossRef] Retrieved {len(proto_to_canonical)} Proto→Canonical mappings"
            )

            # Étape 2: Construire mapping chunk_id → canonical_concept_ids
            chunk_to_canonicals = {}
            canonical_to_chunks = {}  # Pour update Neo4j

            for chunk, chunk_id in zip(chunks, chunk_ids):
                proto_ids = chunk.get("proto_concept_ids", [])
                canonical_ids = []

                for proto_id in proto_ids:
                    canonical_id = proto_to_canonical.get(proto_id)
                    if canonical_id:
                        canonical_ids.append(canonical_id)
                        # Mapper Canonical → Chunks pour Neo4j update
                        if canonical_id not in canonical_to_chunks:
                            canonical_to_chunks[canonical_id] = []
                        canonical_to_chunks[canonical_id].append(chunk_id)

                if canonical_ids:
                    chunk_to_canonicals[chunk_id] = canonical_ids

            logger.info(
                f"[OSMOSE AGENTIQUE:CrossRef] Mapped {len(chunk_to_canonicals)} chunks to canonical concepts"
            )

            # Étape 3: Update chunks Qdrant avec canonical_concept_ids (batch)
            if chunk_to_canonicals:
                # Utiliser set_payload pour update uniquement le champ (plus efficace)
                for chunk_id, canonical_ids in chunk_to_canonicals.items():
                    qdrant_client.set_payload(
                        collection_name="knowbase",
                        payload={"canonical_concept_ids": canonical_ids},
                        points=[chunk_id]
                    )

                logger.info(
                    f"[OSMOSE AGENTIQUE:CrossRef] ✅ Updated {len(chunk_to_canonicals)} chunks in Qdrant with canonical_concept_ids"
                )

            # Étape 4: Update CanonicalConcepts Neo4j avec chunk_ids (batch)
            if canonical_to_chunks:
                with neo4j_client.driver.session(database="neo4j") as session:
                    for canonical_id, chunk_list in canonical_to_chunks.items():
                        session.run("""
                            MATCH (c:CanonicalConcept {canonical_id: $canonical_id, tenant_id: $tenant_id})
                            SET c.chunk_ids = $chunk_ids
                        """, canonical_id=canonical_id, tenant_id=tenant_id, chunk_ids=chunk_list)

                logger.info(
                    f"[OSMOSE AGENTIQUE:CrossRef] ✅ Updated {len(canonical_to_chunks)} CanonicalConcepts in Neo4j with chunk_ids"
                )

            # Log résumé
            logger.info(
                f"[OSMOSE AGENTIQUE:CrossRef] ✅ Cross-reference complete: "
                f"{len(chunk_to_canonicals)} chunks ↔ {len(canonical_to_chunks)} concepts"
            )

        except Exception as e:
            logger.error(f"[OSMOSE AGENTIQUE:CrossRef] Error during cross-reference: {e}", exc_info=True)
            raise

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

    def _calculate_adaptive_timeout(self, num_segments: int) -> int:
        """
        Calcule un timeout adaptatif basé sur la complexité du document.

        Formule Phase 2 OSMOSE (avec extraction relations LLM):
        - Temps de base : 120s (2 min)
        - Temps par segment : 90s (60s extraction NER + 30s relation extraction LLM)
        - Temps FSM overhead : 120s (mining, gatekeeper, promotion, relation writing, indexing)
        - Min : 600s (10 min), Max : settings.osmose_timeout_seconds (défaut 1h, configurable)

        Rationale Phase 2:
        - Extraction relations LLM ajoute ~30-50% overhead par segment
        - Documents larges (500+ concepts) peuvent prendre 60-90 min avec Phase 2
        - Cas réel observé: 553 concepts, 2246 relations → 48 min (timeout à 30 min!)

        Architecture centralisée timeouts (Phase 2 refactor):
        - Utilise settings.osmose_timeout_seconds (property calculée depuis MAX_DOCUMENT_PROCESSING_TIME)
        - Timeout unifié: 1 seule variable à configurer (MAX_DOCUMENT_PROCESSING_TIME)

        Exemples (avec max par défaut 3600s / 1h):
        - 1 segment : 120 + 90*1 + 120 = 330s → clamped à min=600s (10 min)
        - 10 segments : 120 + 90*10 + 120 = 1140s (19 min)
        - 20 segments : 120 + 90*20 + 120 = 2040s (34 min)
        - 30 segments : 120 + 90*30 + 120 = 2940s (49 min) ✅ OK pour doc 230 slides
        - 50 segments : 120 + 90*50 + 120 = 4740s (79 min) → capped à max=3600s (1h)
        - 60 segments : 120 + 90*60 + 120 = 5640s → capped à max=3600s (1h)

        Args:
            num_segments: Nombre de segments détectés

        Returns:
            Timeout en secondes
        """
        from knowbase.config.settings import get_settings

        settings = get_settings()

        base_time = 120  # 2 min base
        time_per_segment = 90  # 90s (1.5 min) par segment (extraction + relations Phase 2)
        fsm_overhead = 120  # 2 min pour mining, gatekeeper, promotion, relation writing, indexing

        calculated_timeout = base_time + (time_per_segment * num_segments) + fsm_overhead

        # Bornes: utilise architecture centralisée via settings
        min_timeout = 600  # Minimum absolu: 10 minutes (réduit car max augmenté à 1h)
        max_timeout = settings.osmose_timeout_seconds  # Depuis MAX_DOCUMENT_PROCESSING_TIME

        adaptive_timeout = max(min_timeout, min(calculated_timeout, max_timeout))

        logger.info(
            f"⏱️ Adaptive timeout: {adaptive_timeout}s "
            f"(calculated={calculated_timeout}s, max={max_timeout}s, min={min_timeout}s, segments={num_segments})"
        )

        return adaptive_timeout

    async def process_document_agentique(
        self,
        document_id: str,
        document_title: str,
        document_path: Path,
        text_content: str,
        tenant_id: Optional[str] = None
    ) -> OsmoseIntegrationResult:
        """
        Pipeline OSMOSE Agentique - Architecture Phase 1.5.

        Remplace SemanticPipelineV2 par SupervisorAgent (FSM Master).

        FSM Pipeline:
        INIT → BUDGET_CHECK → SEGMENT → EXTRACT → MINE_PATTERNS
             → GATE_CHECK → PROMOTE → FINALIZE → DONE

        Args:
            document_id: ID unique du document
            document_title: Titre du document
            document_path: Chemin du fichier
            text_content: Contenu textuel extrait
            tenant_id: ID tenant (multi-tenancy)

        Returns:
            Résultat OSMOSE avec métriques agentiques
        """
        start_time = asyncio.get_event_loop().time()

        # Déterminer type de document
        document_type = document_path.suffix.lower().replace(".", "")

        # Résultat OSMOSE
        result = OsmoseIntegrationResult(
            document_id=document_id,
            document_title=document_title,
            document_path=str(document_path),
            document_type=document_type,
        )

        # Vérifier filtres activation
        should_process, skip_reason = self._should_process_with_osmose(
            document_type, text_content
        )

        if not should_process:
            logger.warning(
                f"[OSMOSE AGENTIQUE] Skipping document {document_id}: {skip_reason}"
            )
            result.osmose_success = False
            result.osmose_error = skip_reason
            result.total_duration_seconds = asyncio.get_event_loop().time() - start_time
            return result

        # Traitement OSMOSE Agentique
        logger.info(
            f"[OSMOSE AGENTIQUE] Processing document {document_id} "
            f"({len(text_content)} chars) with SupervisorAgent FSM"
        )

        osmose_start = asyncio.get_event_loop().time()

        try:
            # Configuration logging pour agents : copier tous les handlers actifs au root logger
            # IMPORTANT: Ceci doit être fait ICI (au runtime) et non au niveau module
            root_logger = logging.getLogger()
            current_handlers = []

            # Récupérer TOUS les handlers de TOUS les loggers actifs
            for logger_name in logging.Logger.manager.loggerDict:
                active_logger = logging.getLogger(logger_name)
                if active_logger.handlers:
                    for handler in active_logger.handlers:
                        if handler not in root_logger.handlers:
                            root_logger.addHandler(handler)
                            current_handlers.append(f"{logger_name}:{type(handler).__name__}")

            # S'assurer que le root logger a le bon niveau
            root_logger.setLevel(logging.INFO)

            logger.info(
                f"[OSMOSE AGENTIQUE] 🔧 Logger configured: root has {len(root_logger.handlers)} handlers "
                f"(copied from: {', '.join(current_handlers[:3]) if current_handlers else 'none'})"
            )

            # Étape 0: Phase 1.8 P0.1 - Génération contexte document global
            # Ce contexte sera passé aux extractors pour améliorer précision
            document_context: Optional[DocumentContext] = None

            try:
                context_gen = self._get_document_context_generator()
                document_context = await context_gen.generate_context(
                    document_id=document_id,
                    full_text=text_content,
                    max_sample_length=3000
                )

                if document_context:
                    logger.info(
                        f"[OSMOSE AGENTIQUE:P0.1] ✅ Document context generated: "
                        f"{document_context.to_short_summary()}"
                    )
                else:
                    logger.warning(
                        f"[OSMOSE AGENTIQUE:P0.1] Failed to generate document context, "
                        f"continuing without context"
                    )
            except Exception as e:
                logger.error(
                    f"[OSMOSE AGENTIQUE:P0.1] Error generating document context: {e}",
                    exc_info=True
                )
                # Non-bloquant: continuer sans contexte

            # Étape 1: Créer AgentState initial
            tenant = tenant_id or self.config.default_tenant_id

            initial_state = AgentState(
                document_id=document_id,
                tenant_id=tenant,
                full_text=text_content  # Stocker texte complet pour filtrage contextuel
            )

            # Stocker contexte document dans state pour transmission aux extractors
            # IMPORTANT: AgentState doit être étendu pour supporter document_context
            # Pour l'instant, on le stockera dans custom_data dict
            if document_context:
                if not hasattr(initial_state, 'custom_data'):
                    initial_state.custom_data = {}
                initial_state.custom_data['document_context'] = document_context

            # Stocker métadonnées document dans state (custom fields)
            # Note: AgentState devra être étendu pour supporter ces champs
            # Pour l'instant, on les log uniquement
            logger.info(
                f"[OSMOSE AGENTIQUE] AgentState created: "
                f"doc={document_id}, tenant={tenant}, "
                f"budgets={initial_state.budget_remaining}, "
                f"context={'YES' if document_context else 'NO'}"
            )

            # Étape 2: Segmentation sémantique avec TopicSegmenter
            segmenter = self._get_topic_segmenter()

            try:
                # Appel TopicSegmenter (async)
                topics = await segmenter.segment_document(
                    document_id=document_id,
                    text=text_content,
                    detect_language=True
                )

                # Convertir Topic objects → dicts pour AgentState.segments
                initial_state.segments = []
                for topic in topics:
                    # Concaténer textes des windows pour obtenir le texte complet du segment
                    segment_text = " ".join([w.text for w in topic.windows])

                    # Déterminer langue (si détectée dans anchors ou windows)
                    # Fallback: "en" si non détecté
                    segment_language = "en"  # TODO: Extraire de topic metadata si disponible

                    segment_dict = {
                        "topic_id": topic.topic_id,
                        "text": segment_text,
                        "language": segment_language,
                        "start_page": 0,  # TODO: Extraire de windows metadata
                        "end_page": 1,    # TODO: Extraire de windows metadata
                        "keywords": topic.anchors,  # NER entities + TF-IDF keywords
                        "cohesion_score": topic.cohesion_score,
                        "section_path": topic.section_path
                    }

                    initial_state.segments.append(segment_dict)

                logger.info(
                    f"[OSMOSE AGENTIQUE] TopicSegmenter: {len(initial_state.segments)} segments "
                    f"(avg cohesion: {sum(t.cohesion_score for t in topics) / max(len(topics), 1):.2f})"
                )

                # Calculer timeout adaptatif basé sur nombre de segments
                adaptive_timeout = self._calculate_adaptive_timeout(len(initial_state.segments))
                initial_state.timeout_seconds = adaptive_timeout
                logger.info(
                    f"[OSMOSE AGENTIQUE] Adaptive timeout: {adaptive_timeout}s "
                    f"({len(initial_state.segments)} segments)"
                )

            except Exception as e:
                logger.error(f"[OSMOSE AGENTIQUE] TopicSegmenter failed: {e}")
                logger.warning("[OSMOSE AGENTIQUE] Falling back to single-segment (full document)")

                # Fallback: Document complet = 1 segment
                initial_state.segments = [{
                    "topic_id": "seg-fallback",
                    "text": text_content,
                    "language": "en",
                    "start_page": 0,
                    "end_page": 1,
                    "keywords": [],
                    "cohesion_score": 1.0,
                    "section_path": "full_document"
                }]

                # Calculer timeout adaptatif même pour fallback
                adaptive_timeout = self._calculate_adaptive_timeout(1)
                initial_state.timeout_seconds = adaptive_timeout
                logger.info(
                    f"[OSMOSE AGENTIQUE] Adaptive timeout (fallback): {adaptive_timeout}s (1 segment)"
                )

            # Étape 3: Lancer SupervisorAgent FSM
            supervisor = self._get_supervisor()

            # DEBUG: Vérifier que les segments sont bien présents
            logger.info(
                f"[OSMOSE AGENTIQUE] 🔍 DEBUG: Passing {len(initial_state.segments)} segments to SupervisorAgent"
            )
            if initial_state.segments:
                logger.info(
                    f"[OSMOSE AGENTIQUE] 🔍 DEBUG: First segment keys: {list(initial_state.segments[0].keys())}"
                )

            final_state = await asyncio.wait_for(
                supervisor.execute(initial_state),
                timeout=self.config.timeout_seconds
            )

            logger.info(
                f"[OSMOSE AGENTIQUE] SupervisorAgent FSM completed: "
                f"state={final_state.current_step}, steps={final_state.steps_count}, "
                f"cost=${final_state.cost_incurred:.3f}, "
                f"promoted={len(final_state.promoted)}"
            )

            # Étape 3.5: Phase 1.6 - Créer chunks dans Qdrant avec cross-référence
            # IMPORTANT: Utiliser final_state.promoted (avec proto_concept_id Neo4j) au lieu de candidates
            if final_state.promoted:  # Seulement si concepts promus (avec proto_concept_id)
                try:
                    text_chunker = self._get_text_chunker()

                    # Créer chunks avec embeddings + attribution concepts
                    # NOTE: final_state.promoted contient maintenant proto_concept_id Neo4j
                    chunks = text_chunker.chunk_document(
                        text=text_content,
                        document_id=document_id,
                        document_name=document_title,
                        segment_id=initial_state.segments[0]["topic_id"] if initial_state.segments else "seg-0",
                        concepts=final_state.promoted,  # Concepts promus avec proto_concept_id Neo4j
                        tenant_id=tenant
                    )

                    if chunks:
                        # Insérer chunks dans Qdrant
                        chunk_ids = upsert_chunks(
                            chunks=chunks,
                            collection_name="knowbase",
                            tenant_id=tenant
                        )

                        # Construire mapping concept_id → chunk_ids pour Gatekeeper
                        concept_to_chunk_ids = {}
                        for chunk, chunk_id in zip(chunks, chunk_ids):
                            for proto_id in chunk.get("proto_concept_ids", []):
                                if proto_id not in concept_to_chunk_ids:
                                    concept_to_chunk_ids[proto_id] = []
                                concept_to_chunk_ids[proto_id].append(chunk_id)

                        # Stocker dans state pour utilisation par Gatekeeper
                        final_state.concept_to_chunk_ids = concept_to_chunk_ids

                        logger.info(
                            f"[OSMOSE AGENTIQUE:Chunks] Created {len(chunks)} chunks in Qdrant "
                            f"({len(concept_to_chunk_ids)} concepts referenced)"
                        )

                        # ===== Phase 1.6: Cross-référencement bidirectionnel Neo4j ↔ Qdrant =====
                        try:
                            self._cross_reference_chunks_and_concepts(
                                chunks=chunks,
                                chunk_ids=chunk_ids,
                                concept_to_chunk_ids=concept_to_chunk_ids,
                                tenant_id=tenant
                            )
                        except Exception as e:
                            logger.error(
                                f"[OSMOSE AGENTIQUE:CrossRef] Error cross-referencing chunks and concepts: {e}",
                                exc_info=True
                            )
                            # Non-bloquant : continuer même si cross-ref échoue
                    else:
                        logger.warning(
                            f"[OSMOSE AGENTIQUE:Chunks] No chunks created for document {document_id}"
                        )

                except Exception as e:
                    logger.error(f"[OSMOSE AGENTIQUE:Chunks] Error creating chunks: {e}", exc_info=True)
                    # Non-bloquant : continuer sans chunks

            # Étape 4: Mapper résultats vers OsmoseIntegrationResult
            osmose_duration = asyncio.get_event_loop().time() - osmose_start

            result.osmose_success = final_state.current_step == "done" and len(final_state.errors) == 0
            result.osmose_error = "; ".join(final_state.errors) if final_state.errors else None

            result.concepts_extracted = len(final_state.candidates)
            result.canonical_concepts = len(final_state.promoted)

            # Métriques Phase 1.5 (nouvelles)
            result.osmose_duration_seconds = osmose_duration
            result.total_duration_seconds = asyncio.get_event_loop().time() - start_time

            # Métriques agentiques (extension OsmoseIntegrationResult nécessaire)
            # Pour l'instant, log uniquement
            logger.info(
                f"[OSMOSE AGENTIQUE] Metrics: "
                f"cost=${final_state.cost_incurred:.3f}, "
                f"llm_calls={final_state.llm_calls_count}, "
                f"budget_remaining={final_state.budget_remaining}, "
                f"promotion_rate={len(final_state.promoted)/len(final_state.candidates)*100 if final_state.candidates else 0:.1f}%"
            )

            # ===== Compter métriques réelles Proto-KG (Neo4j + Qdrant) =====
            try:
                from knowbase.common.clients.neo4j_client import get_neo4j_client
                from knowbase.common.clients.qdrant_client import get_qdrant_client
                from knowbase.config.settings import get_settings

                settings = get_settings()
                neo4j_client = get_neo4j_client(
                    uri=settings.neo4j_uri,
                    user=settings.neo4j_user,
                    password=settings.neo4j_password,
                    database="neo4j"
                )
                qdrant_client = get_qdrant_client()

                # Compter ProtoConcept dans Neo4j
                with neo4j_client.driver.session(database="neo4j") as session:
                    result_proto = session.run(
                        "MATCH (n:ProtoConcept) WHERE n.tenant_id = $tenant_id RETURN count(n) as cnt",
                        tenant_id=tenant_id
                    )
                    record_proto = result_proto.single()
                    proto_count = record_proto["cnt"] if record_proto else 0

                # Compter CanonicalConcept dans Neo4j
                with neo4j_client.driver.session(database="neo4j") as session:
                    result_canonical = session.run(
                        "MATCH (n:CanonicalConcept) WHERE n.tenant_id = $tenant_id RETURN count(n) as cnt",
                        tenant_id=tenant_id
                    )
                    record_canonical = result_canonical.single()
                    canonical_count = record_canonical["cnt"] if record_canonical else 0

                # Compter relations dans Neo4j
                with neo4j_client.driver.session(database="neo4j") as session:
                    result_rels = session.run(
                        "MATCH ()-[r]->() WHERE r.tenant_id = $tenant_id RETURN count(r) as cnt",
                        tenant_id=tenant_id
                    )
                    record_rels = result_rels.single()
                    relations_count = record_rels["cnt"] if record_rels else 0

                # Compter chunks dans Qdrant
                try:
                    collection_info = qdrant_client.get_collection(settings.qdrant_collection)
                    chunks_count = collection_info.points_count
                except Exception:
                    chunks_count = 0

                # Remplir les champs Proto-KG metrics
                result.proto_kg_concepts_stored = proto_count + canonical_count  # Total concepts
                result.proto_kg_relations_stored = relations_count
                result.proto_kg_embeddings_stored = chunks_count

                logger.info(
                    f"[OSMOSE AGENTIQUE:Proto-KG] Real metrics: "
                    f"{proto_count} ProtoConcept + {canonical_count} CanonicalConcept = {proto_count + canonical_count} total, "
                    f"{relations_count} relations, {chunks_count} chunks in Qdrant"
                )

            except Exception as e:
                logger.warning(f"[OSMOSE AGENTIQUE:Proto-KG] Could not query real metrics: {e}")
                # Laisser les valeurs à 0 par défaut en cas d'erreur

            # Log succès
            if result.osmose_success:
                logger.info(
                    f"[OSMOSE AGENTIQUE] ✅ Document {document_id} processed successfully: "
                    f"{result.canonical_concepts} concepts promoted in {osmose_duration:.1f}s"
                )
            else:
                logger.error(
                    f"[OSMOSE AGENTIQUE] ❌ Document {document_id} processing failed: "
                    f"{result.osmose_error}"
                )

            return result

        except asyncio.TimeoutError:
            error_msg = f"OSMOSE Agentique timeout after {self.config.timeout_seconds}s"
            logger.error(f"[OSMOSE AGENTIQUE] {error_msg} for document {document_id}")

            result.osmose_success = False
            result.osmose_error = error_msg
            result.osmose_duration_seconds = self.config.timeout_seconds
            result.total_duration_seconds = asyncio.get_event_loop().time() - start_time

            return result

        except Exception as e:
            error_msg = f"OSMOSE Agentique error: {str(e)}"
            logger.error(
                f"[OSMOSE AGENTIQUE] {error_msg} for document {document_id}",
                exc_info=True
            )

            result.osmose_success = False
            result.osmose_error = error_msg
            result.osmose_duration_seconds = asyncio.get_event_loop().time() - osmose_start
            result.total_duration_seconds = asyncio.get_event_loop().time() - start_time

            return result


# Helper function pour compatibility
async def process_document_with_osmose_agentique(
    document_id: str,
    document_title: str,
    document_path: Path,
    text_content: str,
    tenant_id: Optional[str] = None,
    config: Optional[OsmoseIntegrationConfig] = None
) -> OsmoseIntegrationResult:
    """
    Helper function pour traitement document avec OSMOSE Agentique.

    Compatible avec signature legacy `process_document_with_osmose()`.

    Args:
        document_id: ID unique du document
        document_title: Titre du document
        document_path: Chemin du fichier
        text_content: Contenu textuel extrait
        tenant_id: ID tenant (multi-tenancy)
        config: Configuration OSMOSE

    Returns:
        Résultat OSMOSE Agentique
    """
    service = OsmoseAgentiqueService(config=config)

    return await service.process_document_agentique(
        document_id=document_id,
        document_title=document_title,
        document_path=document_path,
        text_content=text_content,
        tenant_id=tenant_id
    )
