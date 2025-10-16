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
from datetime import datetime

from knowbase.agents.supervisor.supervisor import SupervisorAgent
from knowbase.agents.base import AgentState
from knowbase.ingestion.osmose_integration import (
    OsmoseIntegrationConfig,
    OsmoseIntegrationResult
)
from knowbase.semantic.segmentation.topic_segmenter import get_topic_segmenter
from knowbase.semantic.config import get_semantic_config

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

        Formule :
        - Temps de base : 120s (2 min)
        - Temps par segment : 60s (1 min) (extraction NER + potentiel LLM)
        - Temps FSM overhead : 60s (mining, gatekeeper, promotion)
        - Min : 180s (3 min), Max : 1800s (30 min)

        Exemples :
        - 1 segment : 120 + 60*1 + 60 = 240s (4 min)
        - 10 segments : 120 + 60*10 + 60 = 780s (13 min)
        - 20 segments : 120 + 60*20 + 60 = 1380s (23 min)
        - 30+ segments : 120 + 60*30 + 60 = 1980s → capped à 1800s (30 min)

        Args:
            num_segments: Nombre de segments détectés

        Returns:
            Timeout en secondes
        """
        base_time = 120  # 2 min base
        time_per_segment = 60  # 60s (1 min) par segment
        fsm_overhead = 60  # 1 min pour mining, gatekeeper, promotion

        calculated_timeout = base_time + (time_per_segment * num_segments) + fsm_overhead

        # Bornes: min 180s (3 min), max 1800s (30 min)
        min_timeout = 180
        max_timeout = 1800

        adaptive_timeout = max(min_timeout, min(calculated_timeout, max_timeout))

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

            # Étape 1: Créer AgentState initial
            tenant = tenant_id or self.config.default_tenant_id

            initial_state = AgentState(
                document_id=document_id,
                tenant_id=tenant,
                full_text=text_content  # Stocker texte complet pour filtrage contextuel
            )

            # Stocker métadonnées document dans state (custom fields)
            # Note: AgentState devra être étendu pour supporter ces champs
            # Pour l'instant, on les log uniquement
            logger.info(
                f"[OSMOSE AGENTIQUE] AgentState created: "
                f"doc={document_id}, tenant={tenant}, "
                f"budgets={initial_state.budget_remaining}"
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
