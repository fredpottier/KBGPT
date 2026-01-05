"""
OSMOSE Utils - Factory Methods et Helpers.

Module extrait de osmose_agentique.py pour améliorer la modularité.
Contient les factory methods (lazy init) et fonctions utilitaires.

Author: OSMOSE Refactoring
Date: 2025-01-05
"""

from typing import Dict, Optional, Any
import logging

from knowbase.agents.supervisor.supervisor import SupervisorAgent
from knowbase.semantic.segmentation.topic_segmenter import get_topic_segmenter
from knowbase.semantic.config import get_semantic_config
from knowbase.ingestion.text_chunker import get_text_chunker
from knowbase.common.llm_router import LLMRouter, get_llm_router
from knowbase.config.feature_flags import is_feature_enabled

logger = logging.getLogger(__name__)


class OsmoseComponentFactory:
    """
    Factory pour les composants OSMOSE avec lazy initialization.

    Centralise la création et le cache des composants partagés
    pour éviter les instanciations multiples.
    """

    def __init__(self, tenant_id: str = "default", supervisor_config: Optional[Dict[str, Any]] = None):
        """
        Initialise la factory.

        Args:
            tenant_id: ID tenant pour les composants multi-tenant
            supervisor_config: Configuration SupervisorAgent (FSM, retry)
        """
        self.tenant_id = tenant_id
        self.supervisor_config = supervisor_config or {}

        # Cache des composants (lazy init)
        self._supervisor: Optional[SupervisorAgent] = None
        self._topic_segmenter = None
        self._text_chunker = None
        self._llm_router: Optional[LLMRouter] = None
        self._hybrid_chunker = None
        self._hybrid_extractor = None
        self._heuristic_classifier = None
        self._anchor_scorer = None
        self._pass2_orchestrator = None

        # Feature flag
        self.use_hybrid_anchor = is_feature_enabled("phase_2_hybrid_anchor")

    def get_supervisor(self) -> SupervisorAgent:
        """Lazy init du SupervisorAgent."""
        if self._supervisor is None:
            self._supervisor = SupervisorAgent(config=self.supervisor_config)
            logger.info("[OSMOSE:Factory] SupervisorAgent initialized")
        return self._supervisor

    def get_topic_segmenter(self):
        """Lazy init du TopicSegmenter."""
        if self._topic_segmenter is None:
            semantic_config = get_semantic_config()
            self._topic_segmenter = get_topic_segmenter(semantic_config)
            logger.info("[OSMOSE:Factory] TopicSegmenter initialized")
        return self._topic_segmenter

    def get_text_chunker(self):
        """Lazy init du TextChunker (Phase 1.6)."""
        if self._text_chunker is None:
            self._text_chunker = get_text_chunker(
                model_name="intfloat/multilingual-e5-large",
                chunk_size=512,
                overlap=128
            )
            logger.info("[OSMOSE:Factory] TextChunker initialized (512 tokens, overlap 128)")
        return self._text_chunker

    def get_llm_router(self) -> LLMRouter:
        """Lazy init du LLMRouter singleton (Phase 1.8, avec support Burst Mode)."""
        if self._llm_router is None:
            self._llm_router = get_llm_router()
            logger.info("[OSMOSE:Factory] LLMRouter initialized (Phase 1.8)")
        return self._llm_router

    # =========================================================================
    # Phase 2 - Hybrid Anchor Model Components
    # =========================================================================

    def get_hybrid_chunker(self):
        """Lazy init du HybridAnchorChunker (Phase 2)."""
        if self._hybrid_chunker is None:
            from knowbase.ingestion.hybrid_anchor_chunker import get_hybrid_anchor_chunker
            self._hybrid_chunker = get_hybrid_anchor_chunker(tenant_id=self.tenant_id)
            logger.info("[OSMOSE:Factory] HybridAnchorChunker initialized")
        return self._hybrid_chunker

    def get_hybrid_extractor(self):
        """Lazy init du HybridAnchorExtractor (Phase 2)."""
        if self._hybrid_extractor is None:
            from knowbase.semantic.extraction.hybrid_anchor_extractor import (
                get_hybrid_anchor_extractor
            )
            self._hybrid_extractor = get_hybrid_anchor_extractor(tenant_id=self.tenant_id)
            logger.info("[OSMOSE:Factory] HybridAnchorExtractor initialized")
        return self._hybrid_extractor

    def get_heuristic_classifier(self):
        """Lazy init du HeuristicClassifier (Phase 2)."""
        if self._heuristic_classifier is None:
            from knowbase.semantic.classification.heuristic_classifier import (
                get_heuristic_classifier
            )
            self._heuristic_classifier = get_heuristic_classifier(tenant_id=self.tenant_id)
            logger.info("[OSMOSE:Factory] HeuristicClassifier initialized")
        return self._heuristic_classifier

    def get_anchor_scorer(self):
        """Lazy init du AnchorBasedScorer (Phase 2)."""
        if self._anchor_scorer is None:
            from knowbase.agents.gatekeeper.anchor_based_scorer import AnchorBasedScorer
            self._anchor_scorer = AnchorBasedScorer(tenant_id=self.tenant_id)
            logger.info("[OSMOSE:Factory] AnchorBasedScorer initialized")
        return self._anchor_scorer

    def get_pass2_orchestrator(self):
        """Lazy init du Pass2Orchestrator (Phase 2)."""
        if self._pass2_orchestrator is None:
            from knowbase.ingestion.pass2_orchestrator import get_pass2_orchestrator
            self._pass2_orchestrator = get_pass2_orchestrator(tenant_id=self.tenant_id)
            logger.info("[OSMOSE:Factory] Pass2Orchestrator initialized")
        return self._pass2_orchestrator


# =========================================================================
# Helper Functions
# =========================================================================

def should_process_with_osmose(
    document_type: str,
    text_content: str,
    enable_osmose: bool,
    osmose_for_pptx: bool,
    osmose_for_pdf: bool,
    min_text_length: int,
    max_text_length: int
) -> tuple[bool, Optional[str]]:
    """
    Détermine si le document doit être traité avec OSMOSE.

    Args:
        document_type: Type document ("pptx" ou "pdf")
        text_content: Contenu textuel du document
        enable_osmose: Feature flag global
        osmose_for_pptx: Feature flag PPTX
        osmose_for_pdf: Feature flag PDF
        min_text_length: Longueur min texte
        max_text_length: Longueur max texte

    Returns:
        (should_process, skip_reason)
    """
    # Feature flag global désactivé
    if not enable_osmose:
        return False, "OSMOSE globally disabled"

    # Feature flag par type de document
    if document_type == "pptx" and not osmose_for_pptx:
        return False, "OSMOSE disabled for PPTX"

    if document_type == "pdf" and not osmose_for_pdf:
        return False, "OSMOSE disabled for PDF"

    # Filtre par longueur texte
    text_length = len(text_content)

    if text_length < min_text_length:
        return False, f"Text too short: {text_length} < {min_text_length}"

    if text_length > max_text_length:
        return False, f"Text too long: {text_length} > {max_text_length}"

    return True, None


def calculate_adaptive_timeout(num_segments: int) -> int:
    """
    Calcule un timeout adaptatif basé sur la complexité du document.

    Formule Phase 2 OSMOSE (avec extraction relations LLM):
    - Temps de base : 120s (2 min)
    - Temps par segment : 90s (60s extraction NER + 30s relation extraction LLM)
    - Temps FSM overhead : 120s (mining, gatekeeper, promotion, relation writing, indexing)
    - Min : 600s (10 min), Max : settings.osmose_timeout_seconds (défaut 1h)

    Args:
        num_segments: Nombre de segments détectés

    Returns:
        Timeout en secondes
    """
    from knowbase.config.settings import get_settings

    settings = get_settings()

    base_time = 120  # 2 min base
    time_per_segment = 90  # 90s (1.5 min) par segment
    fsm_overhead = 120  # 2 min overhead

    calculated_timeout = base_time + (time_per_segment * num_segments) + fsm_overhead

    # Bornes
    min_timeout = 600  # 10 minutes minimum
    max_timeout = settings.osmose_timeout_seconds

    adaptive_timeout = max(min_timeout, min(calculated_timeout, max_timeout))

    logger.info(
        f"[OSMOSE:Timeout] Adaptive: {adaptive_timeout}s "
        f"(calculated={calculated_timeout}s, max={max_timeout}s, segments={num_segments})"
    )

    return adaptive_timeout


__all__ = [
    "OsmoseComponentFactory",
    "should_process_with_osmose",
    "calculate_adaptive_timeout",
]
