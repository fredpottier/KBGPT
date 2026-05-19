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

from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Any
import asyncio
import hashlib
import logging
import os
import re
from datetime import datetime
from functools import lru_cache

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
from knowbase.common.llm_router import LLMRouter, TaskType, get_llm_router  # Phase 1.8: Document Context
from knowbase.ontology.domain_context_injector import get_domain_context_injector  # Domain Context injection
from knowbase.entity_resolution.deferred_reevaluator import get_deferred_reevaluator  # Phase 2.12: Entity Resolution

# ===== OSMOSE Refactored Modules =====
from knowbase.ingestion.osmose_utils import (
    OsmoseComponentFactory,
    should_process_with_osmose,
    calculate_adaptive_timeout,
)
from knowbase.ingestion.osmose_enrichment import (
    enrich_anchors_with_context,
    extract_document_metadata,
    generate_document_summary,
    cross_reference_chunks_and_concepts,
)
from knowbase.ingestion.osmose_persistence import (
    persist_hybrid_anchor_to_neo4j,
    extract_intra_document_relations,
    trigger_entity_resolution_reevaluation,
    # ADR_COVERAGE_PROPERTY_NOT_NODE - Phase 1 & 2 (Option C)
    resolve_section_ids_for_proto_concepts,
    anchor_proto_concepts_to_docitems,
)
# ===== ADR Option C 2026-01 (remplace Dual Chunking) =====
# CoverageChunks supprimés - ADR_COVERAGE_PROPERTY_NOT_NODE
# ANCHORED_IN pointe maintenant vers DocItem (voir anchor_proto_concepts_to_docitems)

# ===== Phase 2 - Hybrid Anchor Model =====
from knowbase.config.feature_flags import is_feature_enabled, get_hybrid_anchor_config
from knowbase.ingestion.enrichment_tracker import (
    get_enrichment_tracker,
    EnrichmentStatus
)  # ADR 2024-12-30: Enrichment tracking
from knowbase.navigation import get_navigation_layer_builder  # ADR: Navigation Layer

# ===== PR2 - Assertion Context (ADR_ASSERTION_AWARE_KG) =====
from knowbase.extraction_v2.context import (
    AnchorContextAnalyzer,
    get_anchor_context_analyzer,
    DocContextFrame,
    DocScope,
)

# Logger pour ce module (pas de manipulation du root logger pour eviter les doublons)
logger = logging.getLogger(__name__)

# Cache global pour les résumés de documents (Phase 1.8)
# Clé: hash(document_id), Valeur: résumé généré
_document_context_cache: Dict[str, str] = {}


def _resolve_vllm_url_for_doc_extraction() -> Optional[str]:
    """Résout l'URL vLLM pour le S4 LLM du DocumentValidFromExtractor.

    A1.3.C — Priorité Redis burst state actif > env VLLM_URL > None (skip S4).
    Reste cohérent avec la charte "1 LLM = 1 lifecycle = 1 monitoring" pour
    l'ingestion : on utilise le même vLLM EC2 Burst que ClaimFirst Phase 2.
    """
    # 1. Redis burst state (instance EC2 active)
    try:
        from knowbase.ingestion.burst.provider_switch import (
            get_burst_state_from_redis,
        )

        state = get_burst_state_from_redis()
        if state and state.get("active") and state.get("vllm_url"):
            return state["vllm_url"]
    except Exception:
        pass

    # 2. Env var VLLM_URL (fallback explicite si configuré)
    import os

    return os.getenv("VLLM_URL") or None


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
        self.llm_router = None  # Lazy init (Phase 1.8: Document Context)

        # ===== Phase 2 - Hybrid Anchor Model =====
        self.hybrid_chunker = None  # Lazy init
        self.hybrid_extractor = None  # Lazy init
        self.heuristic_classifier = None  # Lazy init
        self.anchor_scorer = None  # Lazy init
        self.pass2_orchestrator = None  # Lazy init

        # Check if Hybrid Anchor Model is enabled
        self.use_hybrid_anchor = is_feature_enabled("phase_2_hybrid_anchor")

        # Check if Stratified Pipeline V2 is enabled
        # Si V2 activé: Skip ProtoConcepts et autres nodes legacy (ADR ARCH_STRATIFIED_PIPELINE_V2)
        self.use_stratified_v2 = is_feature_enabled("stratified_pipeline_v2")

        logger.info(
            f"[OSMOSE AGENTIQUE] Service initialized - OSMOSE enabled: {self.config.enable_osmose}, "
            f"Hybrid Anchor Model: {self.use_hybrid_anchor}, Stratified V2: {self.use_stratified_v2}"
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

    def _get_llm_router(self) -> LLMRouter:
        """Lazy init du LLMRouter singleton (Phase 1.8, avec support Burst Mode)."""
        if self.llm_router is None:
            self.llm_router = get_llm_router()  # Singleton avec Burst Mode
            logger.info("[OSMOSE AGENTIQUE] LLMRouter initialized (Phase 1.8)")

        return self.llm_router

    # =========================================================================
    # Phase 2 - Hybrid Anchor Model Lazy Init Methods
    # =========================================================================

    def _get_hybrid_chunker(self):
        """Lazy init du HybridAnchorChunker (Phase 2)."""
        if self.hybrid_chunker is None:
            from knowbase.ingestion.hybrid_anchor_chunker import get_hybrid_anchor_chunker
            self.hybrid_chunker = get_hybrid_anchor_chunker(
                tenant_id=self.config.default_tenant_id
            )
            logger.info("[OSMOSE:HybridAnchor] HybridAnchorChunker initialized")

        return self.hybrid_chunker

    def _get_hybrid_extractor(self):
        """Lazy init du HybridAnchorExtractor (Phase 2)."""
        if self.hybrid_extractor is None:
            from knowbase.semantic.extraction.hybrid_anchor_extractor import (
                get_hybrid_anchor_extractor
            )
            self.hybrid_extractor = get_hybrid_anchor_extractor(
                tenant_id=self.config.default_tenant_id
            )
            logger.info("[OSMOSE:HybridAnchor] HybridAnchorExtractor initialized")

        return self.hybrid_extractor

    def _get_heuristic_classifier(self):
        """Lazy init du HeuristicClassifier (Phase 2)."""
        if self.heuristic_classifier is None:
            from knowbase.semantic.classification.heuristic_classifier import (
                get_heuristic_classifier
            )
            self.heuristic_classifier = get_heuristic_classifier(
                tenant_id=self.config.default_tenant_id
            )
            logger.info("[OSMOSE:HybridAnchor] HeuristicClassifier initialized")

        return self.heuristic_classifier

    def _get_anchor_scorer(self):
        """Lazy init du AnchorBasedScorer (Phase 2)."""
        if self.anchor_scorer is None:
            from knowbase.agents.gatekeeper.anchor_based_scorer import (
                AnchorBasedScorer
            )
            self.anchor_scorer = AnchorBasedScorer(
                tenant_id=self.config.default_tenant_id
            )
            logger.info("[OSMOSE:HybridAnchor] AnchorBasedScorer initialized")

        return self.anchor_scorer

    def _get_pass2_orchestrator(self):
        """Lazy init du Pass2Orchestrator (Phase 2)."""
        if self.pass2_orchestrator is None:
            from knowbase.ingestion.pass2_orchestrator import get_pass2_orchestrator
            self.pass2_orchestrator = get_pass2_orchestrator(
                tenant_id=self.config.default_tenant_id
            )
            logger.info("[OSMOSE:HybridAnchor] Pass2Orchestrator initialized")

        return self.pass2_orchestrator

    # =========================================================================
    # PR2 - Assertion Context Enrichment (ADR_ASSERTION_AWARE_KG)
    # =========================================================================

    async def _enrich_anchors_with_context(
        self,
        proto_concepts: List[Any],
        doc_context_frame: Optional[DocContextFrame] = None,
    ) -> None:
        """
        Enrichit les anchors des ProtoConcepts avec contexte d'assertion.

        Applique l'analyse de contexte (polarity, scope, markers) sur chaque
        anchor et calcule le contexte agrege du ProtoConcept.

        ADR: doc/ongoing/ADR_ASSERTION_AWARE_KG.md - PR2

        Args:
            proto_concepts: Liste des ProtoConcepts a enrichir (modifies in-place)
            doc_context_frame: Contexte documentaire (si disponible)
        """
        if not proto_concepts:
            return

        analyzer = get_anchor_context_analyzer()

        # Compteurs pour stats
        anchors_enriched = 0
        protos_with_context = 0

        for proto in proto_concepts:
            if not hasattr(proto, 'anchors') or not proto.anchors:
                continue

            # Analyser chaque anchor
            for anchor in proto.anchors:
                try:
                    # Extraire le passage (surface_form) de l'anchor
                    passage = getattr(anchor, 'surface_form', '')
                    if not passage:
                        continue

                    # Analyse sync (heuristiques uniquement pour Pass 1)
                    anchor_context = analyzer.analyze_sync(
                        passage=passage,
                        doc_context=doc_context_frame,
                    )

                    # Enrichir l'anchor avec les resultats
                    # (conversion vers les champs du schema Pydantic)
                    anchor.polarity = anchor_context.polarity
                    anchor.scope = anchor_context.scope
                    anchor.local_markers = [
                        {"value": m.value, "evidence": m.evidence, "confidence": m.confidence}
                        for m in anchor_context.local_markers
                    ]
                    anchor.is_override = anchor_context.is_override
                    anchor.qualifier_source = anchor_context.qualifier_source
                    anchor.context_confidence = anchor_context.confidence

                    anchors_enriched += 1

                except Exception as e:
                    logger.debug(
                        f"[OSMOSE:PR2:Context] Failed to enrich anchor: {e}"
                    )

            # Calculer le contexte agrege du ProtoConcept
            if hasattr(proto, 'compute_context'):
                try:
                    proto.context = proto.compute_context()
                    protos_with_context += 1
                except Exception as e:
                    logger.debug(
                        f"[OSMOSE:PR2:Context] Failed to compute proto context: {e}"
                    )

        logger.info(
            f"[OSMOSE:PR2:Context] Enriched {anchors_enriched} anchors, "
            f"{protos_with_context} ProtoConcepts with aggregated context"
        )

    def _extract_document_metadata(self, full_text: str) -> Dict[str, Any]:
        """
        Extrait métadonnées basiques du document sans LLM.

        Phase 1.8: Extraction heuristique titre, headers, mots-clés.

        Args:
            full_text: Texte complet du document

        Returns:
            Dict avec title, headers, keywords
        """
        metadata: Dict[str, Any] = {
            "title": None,
            "headers": [],
            "keywords": []
        }

        lines = full_text.split("\n")
        non_empty_lines = [l.strip() for l in lines if l.strip()]

        # Heuristique titre: première ligne non-vide courte (<100 chars)
        if non_empty_lines:
            first_line = non_empty_lines[0]
            if len(first_line) < 100:
                metadata["title"] = first_line

        # Extraction headers via patterns (# Header, HEADER:, Header majuscule isolé)
        header_patterns = [
            r'^#{1,3}\s+(.+)$',  # Markdown headers
            r'^([A-Z][A-Z0-9\s]{2,50}):?\s*$',  # UPPERCASE headers
            r'^(\d+\.?\s+[A-Z].{5,80})$',  # Numbered headers
        ]

        for line in non_empty_lines[:50]:  # Limiter aux 50 premières lignes
            for pattern in header_patterns:
                match = re.match(pattern, line)
                if match:
                    header = match.group(1).strip()
                    if header and len(header) < 100 and header not in metadata["headers"]:
                        metadata["headers"].append(header)
                        if len(metadata["headers"]) >= 10:
                            break
            if len(metadata["headers"]) >= 10:
                break

        # Extraction mots-clés: termes SAP fréquents + noms propres capitalisés
        sap_keywords = set()

        # Pattern SAP: "SAP X", "S/4HANA", "BTP", etc.
        sap_pattern = r'\b(SAP\s+\w+(?:\s+\w+)?|S/4HANA(?:\s+Cloud)?|BTP|Fiori|HANA|SuccessFactors|Ariba|Concur)\b'
        for match in re.finditer(sap_pattern, full_text, re.IGNORECASE):
            term = match.group(1)
            if term:
                sap_keywords.add(term)

        # Pattern noms propres: mots capitalisés répétés
        proper_nouns = re.findall(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b', full_text)
        noun_counts = Counter(proper_nouns)

        # Garder les plus fréquents (>2 occurrences)
        for noun, count in noun_counts.most_common(20):
            if count > 2 and noun not in ["The", "This", "That", "These", "What", "How", "Where"]:
                sap_keywords.add(noun)

        metadata["keywords"] = list(sap_keywords)[:15]

        return metadata

    async def _generate_document_summary(
        self,
        document_id: str,
        full_text: str,
        max_length: int = 500
    ) -> tuple:
        """
        Génère un résumé contextuel du document, évalue sa densité technique,
        et extrait les contraintes document-level.

        Délègue à osmose_enrichment.generate_document_summary().

        Returns:
            Tuple (summary, technical_density, document_context)
        """
        llm_router = self._get_llm_router()
        return await generate_document_summary(
            document_id=document_id,
            full_text=full_text,
            llm_router=llm_router,
            max_length=max_length,
        )

    def _cross_reference_chunks_and_concepts(
        self,
        chunks: List[Dict[str, Any]],
        chunk_ids: List[str],
        concept_to_chunk_ids: Dict[str, List[str]],
        tenant_id: str
    ) -> None:
        """
        Établit le cross-référencement bidirectionnel Neo4j ↔ Qdrant.

        Délègue à osmose_enrichment.cross_reference_chunks_and_concepts().
        """
        cross_reference_chunks_and_concepts(
            chunks=chunks,
            chunk_ids=chunk_ids,
            concept_to_chunk_ids=concept_to_chunk_ids,
            tenant_id=tenant_id,
        )

    def _should_process_with_osmose(
        self,
        document_type: str,
        text_content: str
    ) -> tuple[bool, Optional[str]]:
        """
        Détermine si le document doit être traité avec OSMOSE.

        Délègue à osmose_utils.should_process_with_osmose().
        """
        return should_process_with_osmose(
            document_type=document_type,
            text_content=text_content,
            enable_osmose=self.config.enable_osmose,
            osmose_for_pptx=self.config.osmose_for_pptx,
            osmose_for_pdf=self.config.osmose_for_pdf,
            min_text_length=self.config.min_text_length,
            max_text_length=self.config.max_text_length,
        )

    def _calculate_adaptive_timeout(self, num_segments: int) -> int:
        """
        Calcule un timeout adaptatif basé sur la complexité du document.

        Délègue à osmose_utils.calculate_adaptive_timeout().
        """
        return calculate_adaptive_timeout(num_segments)

    async def process_document_agentique(
        self,
        document_id: str,
        document_title: str,
        document_path: Path,
        text_content: str,
        tenant_id: Optional[str] = None,
        doc_context_frame: Optional["DocContextFrame"] = None,  # PR4: DocContextFrame
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
            doc_context_frame: DocContextFrame pour assertions (PR4)

        Returns:
            Résultat OSMOSE avec métriques agentiques
        """
        start_time = asyncio.get_event_loop().time()
        print(f"[DEBUG OSMOSE] >>> ENTRY process_document_agentique: doc={document_id}")
        # PR4 DEBUG: Log DocContext reception
        if doc_context_frame:
            logger.info(
                f"[OSMOSE:PR4] DocContext received: doc_scope={doc_context_frame.doc_scope.value}, "
                f"markers={doc_context_frame.strong_markers + doc_context_frame.weak_markers}"
            )
        else:
            logger.warning(f"[OSMOSE:PR4] DocContext is None for {document_id}")

        # Déterminer type de document
        document_type = document_path.suffix.lower().replace(".", "")
        print(f"[DEBUG OSMOSE] Document type: {document_type}")

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

        # ===== Pipeline V2: Skip ProtoConcepts et autres nodes legacy =====
        # ADR ARCH_STRATIFIED_PIPELINE_V2: Si V2 activé, le traitement sémantique
        # (ProtoConcepts, MentionSpan, etc.) est fait par Pass 1 stratifié, pas ici.
        # L'import ne fait que le structural graph (DocItem, TypeAwareChunk).
        if self.use_stratified_v2:
            logger.info(
                f"[OSMOSE:V2] 🌊 Stratified Pipeline V2 active - skipping legacy node creation "
                f"for {document_id}. Semantic processing delegated to Pass 1 stratifié."
            )
            # Retourner un résultat minimal - le vrai travail est fait par Pass 1
            result.osmose_success = True
            result.osmose_error = None
            result.concepts_extracted = 0
            result.canonical_concepts = 0
            result.total_duration_seconds = asyncio.get_event_loop().time() - start_time
            return result

        # ===== Phase 2: Hybrid Anchor Model =====
        # Si le feature flag est activé, utiliser le nouveau pipeline
        if self.use_hybrid_anchor:
            logger.info(
                f"[OSMOSE:HybridAnchor] 🌊 Using Hybrid Anchor Model pipeline for {document_id}"
            )
            return await self.process_document_hybrid_anchor(
                document_id=document_id,
                document_title=document_title,
                document_path=document_path,
                text_content=text_content,
                tenant_id=tenant_id,
                doc_context_frame=doc_context_frame,  # PR4: Propager DocContextFrame
            )

        # ===== Legacy: OSMOSE Agentique (Phase 1.5) =====
        logger.info(
            f"[OSMOSE AGENTIQUE] Processing document {document_id} "
            f"({len(text_content)} chars) with SupervisorAgent FSM"
        )

        osmose_start = asyncio.get_event_loop().time()

        try:
            # Étape 1: Créer AgentState initial
            tenant = tenant_id or self.config.default_tenant_id

            initial_state = AgentState(
                document_id=document_id,
                tenant_id=tenant,
                full_text=text_content,  # Stocker texte complet pour filtrage contextuel
                input_text=text_content  # Phase 2.9: Texte pour extraction doc-level
            )

            logger.info(
                f"[OSMOSE AGENTIQUE] AgentState created: "
                f"doc={document_id}, tenant={tenant}, "
                f"budgets={initial_state.budget_remaining}"
            )

            # Phase 1.8: Générer document_context pour désambiguïsation concepts
            # Phase 1.8.2: Récupérer aussi technical_density_hint (domain-agnostic)
            # ADR Document Context Markers: Récupérer document_context_constraints
            print(f"[DEBUG OSMOSE] Phase 1.8: Generating document context...")
            try:
                document_context, technical_density_hint, doc_context_constraints = await self._generate_document_summary(
                    document_id=document_id,
                    full_text=text_content,
                    max_length=500
                )
                initial_state.document_context = document_context
                initial_state.technical_density_hint = technical_density_hint
                # TODO: Utiliser doc_context_constraints pour filtrage markers (ADR)
                logger.info(
                    f"[PHASE1.8:Context] Document context generated ({len(document_context)} chars, "
                    f"technical_density={technical_density_hint:.2f})"
                )
            except Exception as e:
                logger.warning(f"[PHASE1.8:Context] Failed to generate context: {e}")
                print(f"[DEBUG OSMOSE] Phase 1.8: Context generation FAILED: {e}")
                # Non-bloquant: continuer sans contexte, hint par défaut 0.5
                initial_state.technical_density_hint = 0.5

            print(f"[DEBUG OSMOSE] Phase 1.8: Context done. Starting segmentation...")

            # Étape 2: Segmentation sémantique avec TopicSegmenter
            segmenter = self._get_topic_segmenter()
            print(f"[DEBUG OSMOSE] TopicSegmenter obtained, calling segment_document...")

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
                        "segment_id": topic.topic_id,  # Phase 2.9 FIX: Alias pour compatibilité orchestrator
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
                    "segment_id": "seg-fallback",  # Phase 2.9 FIX: Alias pour compatibilité orchestrator
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
            print(f"[DEBUG OSMOSE] Segmentation done. Getting SupervisorAgent...")
            supervisor = self._get_supervisor()
            print(f"[DEBUG OSMOSE] SupervisorAgent obtained.")

            # DEBUG: Vérifier que les segments sont bien présents
            logger.info(
                f"[OSMOSE AGENTIQUE] 🔍 DEBUG: Passing {len(initial_state.segments)} segments to SupervisorAgent"
            )
            print(f"[DEBUG OSMOSE] Passing {len(initial_state.segments)} segments to SupervisorAgent")
            if initial_state.segments:
                logger.info(
                    f"[OSMOSE AGENTIQUE] 🔍 DEBUG: First segment keys: {list(initial_state.segments[0].keys())}"
                )
                print(f"[DEBUG OSMOSE] First segment keys: {list(initial_state.segments[0].keys())}")

            print(f"[DEBUG OSMOSE] >>> Calling supervisor.execute() with timeout={self.config.timeout_seconds}s...")
            final_state = await asyncio.wait_for(
                supervisor.execute(initial_state),
                timeout=self.config.timeout_seconds
            )
            print(f"[DEBUG OSMOSE] <<< supervisor.execute() COMPLETED")

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
                        tenant_id=tenant,
                    )

                    if chunks:
                        # Insérer chunks dans Qdrant
                        chunk_ids = upsert_chunks(
                            chunks=chunks,
                            collection_name="knowbase",
                            tenant_id=tenant,
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
                                tenant_id=tenant,
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

                # Compter relations dans Neo4j (entre concepts du tenant)
                with neo4j_client.driver.session(database="neo4j") as session:
                    result_rels = session.run(
                        """
                        MATCH (a:CanonicalConcept)-[r]->(b:CanonicalConcept)
                        WHERE a.tenant_id = $tenant_id AND b.tenant_id = $tenant_id
                        RETURN count(r) as cnt
                        """,
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

                # Phase 2.12: Notify Entity Resolution for reevaluation trigger
                try:
                    reevaluator = get_deferred_reevaluator(tenant_id or "default")
                    should_reevaluate = reevaluator.notify_document_ingested()
                    if should_reevaluate:
                        # Trigger async reevaluation (non-blocking)
                        asyncio.create_task(self._trigger_entity_resolution_reevaluation(tenant_id))
                except Exception as er_error:
                    logger.warning(f"[OSMOSE AGENTIQUE] Entity resolution notification failed: {er_error}")
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

    # =========================================================================
    # Phase 2 - Hybrid Anchor Model Pipeline
    # =========================================================================

    async def process_document_hybrid_anchor(
        self,
        document_id: str,
        document_title: str,
        document_path: Path,
        text_content: str,
        tenant_id: Optional[str] = None,
        doc_context_frame: Optional["DocContextFrame"] = None,  # PR4: DocContextFrame
    ) -> OsmoseIntegrationResult:
        """
        Pipeline Hybrid Anchor Model - Phase 2.

        Architecture à 2 Passes:
        - Pass 1 (~10 min): EXTRACT → GATE_CHECK → RELATIONS → CHUNK
        - Pass 2 (async): CLASSIFY_FINE → ENRICH_RELATIONS → CROSS_DOC

        ADR: doc/ongoing/ADR_HYBRID_ANCHOR_MODEL.md

        Args:
            document_id: ID unique du document
            document_title: Titre du document
            document_path: Chemin du fichier
            text_content: Contenu textuel extrait
            tenant_id: ID tenant
            doc_context_frame: DocContextFrame pour assertions (PR4)

        Returns:
            OsmoseIntegrationResult
        """
        start_time = asyncio.get_event_loop().time()
        tenant = tenant_id or self.config.default_tenant_id

        logger.info(
            f"[OSMOSE:HybridAnchor] 🌊 Starting Pass 1 for document {document_id} "
            f"({len(text_content)} chars)"
        )

        # Résultat
        document_type = document_path.suffix.lower().replace(".", "")
        result = OsmoseIntegrationResult(
            document_id=document_id,
            document_title=document_title,
            document_path=str(document_path),
            document_type=document_type,
        )

        # ADR 2024-12-30: Track enrichment state
        enrichment_tracker = get_enrichment_tracker(tenant)
        enrichment_tracker.update_pass1_status(
            document_id=document_id,
            status=EnrichmentStatus.IN_PROGRESS
        )

        try:
            # ===== PASS 1: Socle de Vérité Exploitable =====

            # Étape 1: Segmentation
            segmenter = self._get_topic_segmenter()
            topics = await segmenter.segment_document(
                document_id=document_id,
                text=text_content,
                detect_language=True
            )

            segments = []
            for topic in topics:
                # 2026-01: CRITICAL FIX - Utiliser le texte ORIGINAL, pas reconstruit
                # Le texte reconstruit par join() ne correspond pas au texte utilisé par le chunker
                # ce qui causait des positions d'anchors incorrectes (85 ANCHORED_IN au lieu de 243)
                if topic.windows:
                    min_start = min(w.start for w in topic.windows)
                    max_end = max(w.end for w in topic.windows)
                    segment_length = max_end - min_start
                    # Extraire directement du texte original
                    segment_text = text_content[topic.char_offset : topic.char_offset + segment_length]
                else:
                    segment_text = ""

                segments.append({
                    "segment_id": topic.topic_id,
                    "text": segment_text,
                    "section_id": topic.section_path,
                    # 2024-12-30: Propager char_offset pour positions globales des anchors
                    "char_offset": topic.char_offset,
                })

            logger.info(
                f"[OSMOSE:HybridAnchor] Segmentation: {len(segments)} segments"
            )

            # Étape 2: Générer contexte document
            document_context = ""
            try:
                document_context, _, _ = await self._generate_document_summary(
                    document_id=document_id,
                    full_text=text_content,
                    max_length=500
                )
            except Exception as e:
                logger.warning(f"[OSMOSE:HybridAnchor] Document context failed: {e}")

            # Étape 3: EXTRACT_CONCEPTS + ANCHOR_RESOLUTION
            extractor = self._get_hybrid_extractor()
            extraction_result = await extractor.extract_batch(
                segments=segments,
                document_id=document_id,
                document_context=document_context,
                max_concurrent=5
            )

            proto_concepts = extraction_result.proto_concepts
            logger.info(
                f"[OSMOSE:HybridAnchor] Extraction: {len(proto_concepts)} ProtoConcepts "
                f"({len(extraction_result.rejected_concepts)} rejected)"
            )

            # Étape 3.5: PR2 - Enrich anchors with assertion context
            # ADR: ADR_ASSERTION_AWARE_KG.md - PR2
            try:
                # Utiliser le DocContextFrame passé en paramètre (PR4),
                # sinon essayer de le reconstruire depuis extraction_result
                if doc_context_frame is None:
                    if hasattr(extraction_result, 'doc_context') and extraction_result.doc_context:
                        doc_context_frame = extraction_result.doc_context
                    else:
                        # Fallback: creer un DocContextFrame minimal GENERAL
                        doc_context_frame = DocContextFrame(
                            document_id=document_id,
                            doc_scope=DocScope.GENERAL,
                            scope_confidence=0.5,
                        )

                await self._enrich_anchors_with_context(
                    proto_concepts=proto_concepts,
                    doc_context_frame=doc_context_frame,
                )
            except Exception as ctx_err:
                logger.warning(
                    f"[OSMOSE:PR2:Context] Anchor context enrichment failed: {ctx_err}"
                )
                # Non-bloquant: continuer sans enrichissement contexte

            # Étape 4: Classification heuristique (Pass 1)
            classifier = self._get_heuristic_classifier()
            for pc in proto_concepts:
                surface = pc.anchors[0].surface_form if pc.anchors else ""
                classification = classifier.classify(
                    label=pc.concept_name,
                    context=pc.definition or "",
                    quote=surface
                )
                pc.type_heuristic = classification.concept_type.value

            # ================================================================
            # ADR_UNIFIED_CORPUS_PROMOTION: Étape 5 - Promotion DÉFÉRÉE
            # ================================================================
            # La promotion est maintenant effectuée en Pass 2.0 (corpus_promotion)
            # Pass 1 ne crée PLUS de CanonicalConcepts, seulement des ProtoConcepts
            # Cela permet une promotion corpus-aware avec vue sur tous les documents
            #
            # Anciennes lignes supprimées:
            # - scorer.score_proto_concepts()
            # - scorer.determine_promotion()
            # - create_canonical_from_protos()
            # ================================================================

            # En Pass 1, on ne crée plus de CanonicalConcepts
            canonical_concepts = []

            logger.info(
                f"[OSMOSE:HybridAnchor] Pass 1: {len(proto_concepts)} ProtoConcepts extracted, "
                f"promotion deferred to Pass 2.0 (ADR_UNIFIED_CORPUS_PROMOTION)"
            )

            # Étape 6: CHUNKING document-centric avec anchors
            chunker = self._get_hybrid_chunker()

            # 2026-01: Collecter TOUS les anchors des proto-concepts (pas juste promoted)
            # pour que les relations ANCHORED_IN soient créées pour tous les concepts SPAN
            # + mapping concept_id → label pour enrichir le payload Qdrant
            all_anchors = []
            concept_labels: Dict[str, str] = {}
            for pc in proto_concepts:
                if pc.anchors:  # Seulement si le concept a des anchors valides
                    all_anchors.extend(pc.anchors)
                    concept_labels[pc.concept_id] = pc.concept_name

            # 2026-01: DEBUG - Log plage des anchors collectés
            if all_anchors:
                anchor_min = min(a.span_start for a in all_anchors)
                anchor_max = max(a.span_end for a in all_anchors)
                logger.info(
                    f"[OSMOSE:HybridAnchor:DEBUG] Anchors collected: {len(all_anchors)} "
                    f"covering [{anchor_min}-{anchor_max}], document length={len(text_content)}"
                )

            # ================================================================
            # ADR Dual Chunking 2026-01: Étape 6a - RetrievalChunks
            # ================================================================
            # Ces chunks sont layout-aware avec min_tokens=50
            # Ils sont vectorisés dans Qdrant pour le retrieval
            retrieval_chunks = chunker.chunk_document(
                text=text_content,
                document_id=document_id,
                document_name=document_title,
                anchors=all_anchors,
                concept_labels=concept_labels,
                tenant_id=tenant,
                segments=segments
            )

            logger.info(
                f"[OSMOSE:DualChunk] RetrievalChunks: {len(retrieval_chunks)} chunks"
            )

            # ================================================================
            # ADR_COVERAGE_PROPERTY_NOT_NODE: CoverageChunks supprimés
            # ================================================================
            # L'ancien système Dual Chunking est remplacé par Option C:
            # - ANCHORED_IN pointe vers DocItem (pas CoverageChunk)
            # - DocItem a charspan_docwide pour alignement positions
            # - Voir anchor_proto_concepts_to_docitems() plus bas

            # Étape 7: Persister RetrievalChunks dans Qdrant
            # Note: Les anchored_concepts du payload Qdrant restent inchangés pour l'instant
            # (alimentés via les alignements dans une future itération)
            if retrieval_chunks:
                chunk_ids = upsert_chunks(
                    chunks=retrieval_chunks,
                    collection_name="knowbase",
                    tenant_id=tenant,
                )
                logger.info(
                    f"[OSMOSE:HybridAnchor] Qdrant: {len(chunk_ids)} RetrievalChunks inserted"
                )

            # ================================================================
            # ADR_COVERAGE_PROPERTY_NOT_NODE - Phase 1: Résolution section_id
            # ================================================================
            # Résout les section_id textuels vers les UUID des SectionContext
            # AVANT la persistance pour que les ProtoConcepts aient le bon section_id
            resolved_sections = resolve_section_ids_for_proto_concepts(
                proto_concepts=proto_concepts,
                doc_id=document_id,
                tenant_id=tenant,
            )
            logger.info(
                f"[OSMOSE:OptionC] Phase 1: Resolved {resolved_sections} section_ids to UUID"
            )

            # Étape 8: Persister dans Neo4j (concepts + Document node)
            # PR4: Inclut Document node + EXTRACTED_FROM avec propriétés assertion
            # 2026-01: Persister TOUS les ProtoConcepts (pas juste promoted_protos)
            await self._persist_hybrid_anchor_to_neo4j(
                proto_concepts=proto_concepts,
                canonical_concepts=canonical_concepts,
                document_id=document_id,
                document_name=document_title,
                tenant_id=tenant,
                chunks=None,  # 2026-01: Ne pas créer chunks ici, utiliser Dual Chunking
                doc_context_frame=doc_context_frame,
                document_path=document_path,  # A1.3.C : pour extraction document_valid_from
            )

            # ================================================================
            # ADR_COVERAGE_PROPERTY_NOT_NODE - Phase 2: ANCHORED_IN → DocItem
            # ================================================================
            # Crée les relations ANCHORED_IN vers DocItem (remplace DocumentChunk)
            # Les DocItems ont les charspan précis et le section_id UUID
            anchored_to_docitem = anchor_proto_concepts_to_docitems(
                proto_concepts=proto_concepts,
                doc_id=document_id,
                tenant_id=tenant,
            )
            logger.info(
                f"[OSMOSE:OptionC] Phase 2: Created {anchored_to_docitem} "
                f"ANCHORED_IN → DocItem relations"
            )

            # ================================================================
            # Étape 8b: Navigation Layer - DÉFÉRÉE À PASS 2.0
            # ================================================================
            # ADR_UNIFIED_CORPUS_PROMOTION: La Navigation Layer nécessite les
            # CanonicalConcepts qui sont maintenant créés en Pass 2.0.
            # La construction de la Navigation Layer est donc déférée à Pass 2.0
            # après la phase CORPUS_PROMOTION.
            # ================================================================
            logger.debug(
                f"[OSMOSE:HybridAnchor] Navigation Layer deferred to Pass 2.0 "
                f"(ADR_UNIFIED_CORPUS_PROMOTION)"
            )

            # ================================================================
            # RELATIONS: Déplacées vers Pass 2 (ADR 2024-12-30)
            # ================================================================
            # Invariant: Pass 1 ne produit PAS de relations.
            # - RAG utilisable immédiatement après Pass 1
            # - Relations extraites en Pass 2 au niveau SEGMENT (non chunk)
            # - Pass 2 utilise scoring pour sélectionner segments pertinents
            # - Voir: doc/ongoing/ADR_HYBRID_ANCHOR_MODEL.md (Addendum 2024-12-30)
            # ================================================================

            # ===== PASS 2: Enrichissement (async) =====
            # ADR_UNIFIED_CORPUS_PROMOTION: Pass 2 est TOUJOURS planifié car
            # la promotion des ProtoConcepts en CanonicalConcepts se fait
            # maintenant dans la phase CORPUS_PROMOTION de Pass 2.0
            pass2_config = get_hybrid_anchor_config("pass2_config", tenant)
            pass2_mode = pass2_config.get("mode", "background") if pass2_config else "background"

            if pass2_mode != "disabled":
                orchestrator = self._get_pass2_orchestrator()

                # Pass 2.0 commence par CORPUS_PROMOTION qui crée les CanonicalConcepts
                # On passe les ProtoConcepts pour référence (optionnel)
                protos_for_pass2 = [
                    {
                        "concept_id": getattr(proto, 'concept_id', ''),
                        "concept_name": getattr(proto, 'concept_name', ''),
                        "definition": getattr(proto, 'definition', ''),
                        "type_heuristic": getattr(proto, 'type_heuristic', 'abstract'),
                        "section_id": getattr(proto, 'section_id', None),
                    }
                    for proto in proto_concepts
                    if getattr(proto, 'concept_id', None)  # Filtrer les protos sans concept_id
                ]

                # Planifier Pass 2
                from knowbase.ingestion.pass2_orchestrator import Pass2Mode
                mode_enum = Pass2Mode(pass2_mode)

                await orchestrator.schedule_pass2(
                    document_id=document_id,
                    concepts=protos_for_pass2,  # ProtoConcepts (promotion en Pass 2.0)
                    mode=mode_enum
                )

                logger.info(
                    f"[OSMOSE:HybridAnchor] Pass 2 scheduled ({pass2_mode}): "
                    f"{len(protos_for_pass2)} proto_concepts for CORPUS_PROMOTION"
                )

            # ===== Finaliser résultat =====
            pass1_duration = asyncio.get_event_loop().time() - start_time

            result.osmose_success = True
            result.concepts_extracted = len(proto_concepts)
            # ADR_UNIFIED_CORPUS_PROMOTION: canonical_concepts = 0 en Pass 1
            # La promotion se fait en Pass 2.0 (phase CORPUS_PROMOTION)
            result.canonical_concepts = 0
            result.osmose_duration_seconds = pass1_duration
            result.total_duration_seconds = pass1_duration

            # ADR 2024-12-30: Update enrichment tracking - Pass 1 complete
            # ADR_UNIFIED_CORPUS_PROMOTION: concepts_promoted = 0, promotion en Pass 2.0
            enrichment_tracker.update_pass1_status(
                document_id=document_id,
                status=EnrichmentStatus.COMPLETE,
                concepts_extracted=len(proto_concepts),
                concepts_promoted=0,  # Promotion déférée à Pass 2.0
                chunks_created=len(retrieval_chunks)  # ADR Option C: CoverageChunks supprimés
            )
            # Mark Pass 2 as pending (ready for CORPUS_PROMOTION + enrichment)
            enrichment_tracker.update_pass2_status(
                document_id=document_id,
                status=EnrichmentStatus.PENDING
            )

            logger.info(
                f"[OSMOSE:HybridAnchor] ✅ Pass 1 complete for {document_id}: "
                f"{len(proto_concepts)} ProtoConcepts, "
                f"{len(retrieval_chunks)} chunks in {pass1_duration:.1f}s "
                f"(promotion deferred to Pass 2.0)"
            )

            return result

        except Exception as e:
            error_msg = f"Hybrid Anchor Model error: {str(e)}"
            logger.error(
                f"[OSMOSE:HybridAnchor] ❌ {error_msg} for document {document_id}",
                exc_info=True
            )

            result.osmose_success = False
            result.osmose_error = error_msg
            result.total_duration_seconds = asyncio.get_event_loop().time() - start_time

            # ADR 2024-12-30: Update enrichment tracking - Pass 1 failed
            enrichment_tracker.update_pass1_status(
                document_id=document_id,
                status=EnrichmentStatus.FAILED,
                error=error_msg
            )

            return result

    async def _persist_hybrid_anchor_to_neo4j(
        self,
        proto_concepts: List[Any],
        canonical_concepts: List[Any],
        document_id: str,
        tenant_id: str,
        chunks: Optional[List[Dict[str, Any]]] = None,
        document_name: Optional[str] = None,
        doc_context_frame: Optional[DocContextFrame] = None,
        document_path: Optional[Path] = None,
    ) -> Dict[str, int]:
        """
        Persiste les concepts Hybrid Anchor dans Neo4j.

        Délègue à osmose_persistence.persist_hybrid_anchor_to_neo4j().

        Phase A1.3.C (ADR_BITEMPOREL_CLAIMS) :
        Si `document_path` fourni, extrait `document_valid_from` via la cascade
        S2 > S3 > S1+batch > S4 LLM (DocumentValidFromExtractor) et le persiste
        sur le noeud :Document avec son marker_type.
        """
        document_valid_from: Optional[str] = None
        document_valid_from_marker: Optional[str] = None

        if document_path is not None and document_path.exists():
            try:
                from knowbase.ingestion.document_valid_from_extractor import (
                    DocumentValidFromExtractor,
                    S4LLMConfig,
                )

                # Résoudre URL vLLM (Redis burst state > env VLLM_URL > skip S4)
                vllm_url = _resolve_vllm_url_for_doc_extraction()
                s4_config = S4LLMConfig(vllm_url=vllm_url) if vllm_url else S4LLMConfig()
                extractor = DocumentValidFromExtractor(
                    s4_config=s4_config,
                    enable_s4_llm=vllm_url is not None,
                )

                # Extraction synchrone (PDF I/O + regex + httpx) — to_thread pour ne pas bloquer
                result = await asyncio.to_thread(extractor.extract, document_path)
                document_valid_from = result.value
                document_valid_from_marker = result.marker_type.value

                logger.info(
                    f"[OSMOSE:DocValidFrom] doc_id={document_id} "
                    f"valid_from={document_valid_from} marker={document_valid_from_marker} "
                    f"source={result.source}"
                )
            except Exception as e:
                # Comportement gracieux : si extraction échoue, on persiste sans valid_from
                # (le claim héritera de ingested_at via le fallback bitemporel)
                logger.warning(
                    f"[OSMOSE:DocValidFrom] extraction failed for {document_id}: {e}"
                )

        return await persist_hybrid_anchor_to_neo4j(
            proto_concepts=proto_concepts,
            canonical_concepts=canonical_concepts,
            document_id=document_id,
            tenant_id=tenant_id,
            chunks=chunks,
            document_name=document_name,
            doc_context_frame=doc_context_frame,
            document_valid_from=document_valid_from,
            document_valid_from_marker=document_valid_from_marker,
        )

    # NOTE: Le reste de l'ancienne implémentation a été supprimé.
    # L'implémentation complète est maintenant dans osmose_persistence.py.

    async def _persist_hybrid_anchor_to_neo4j_PLACEHOLDER(self) -> None:
        """Placeholder pour maintenir la structure du fichier après édition."""
        pass

    async def _DELETED_persist_hybrid_anchor_to_neo4j(
        self,
    ) -> None:
        """
        DELETED - Cette section contenait ~380 lignes de code Neo4j.
        L'implémentation a été déplacée vers osmose_persistence.py.
        """
        # Ce placeholder sera supprimé par l'édition suivante
        pass

    # === FIN SECTION SUPPRIMÉE ===

    # OSMOSE Persistence methods delegation done - see osmose_persistence.py

    # Orphan code block removed - was part of _persist_hybrid_anchor_to_neo4j
    # Implementation moved to osmose_persistence.py
    #
    # The following orphan code section was cleaned up (lines ~1334-1703):
    # - Cypher queries for Document, ProtoConcept, CanonicalConcept nodes
    # - INSTANCE_OF, EXTRACTED_FROM, ANCHORED_IN relations
    # - Stats tracking and logging
    # All this logic is now in osmose_persistence.persist_hybrid_anchor_to_neo4j()
    #
    async def _extract_intra_document_relations(
        self,
        canonical_concepts: List[Any],
        text_content: str,
        document_id: str,
        tenant_id: str,
        document_chunks: Optional[List[Dict[str, Any]]] = None
    ) -> int:
        """Délègue à osmose_persistence.extract_intra_document_relations()."""
        return await extract_intra_document_relations(
            canonical_concepts=canonical_concepts,
            text_content=text_content,
            document_id=document_id,
            tenant_id=tenant_id,
            document_chunks=document_chunks,
        )

    async def _trigger_entity_resolution_reevaluation(
        self,
        tenant_id: Optional[str] = None
    ) -> None:
        """Délègue à osmose_persistence.trigger_entity_resolution_reevaluation()."""
        await trigger_entity_resolution_reevaluation(tenant_id=tenant_id)


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
    # DEBUG Phase 2.9: Trace entrée fonction
    print(f"[DEBUG OSMOSE] >>> ENTRY process_document_with_osmose_agentique: doc={document_id}, text_len={len(text_content)}")
    logger.info(f"[DEBUG OSMOSE] >>> ENTRY process_document_with_osmose_agentique: doc={document_id}")

    service = OsmoseAgentiqueService(config=config)
    print(f"[DEBUG OSMOSE] OsmoseAgentiqueService created, calling process_document_agentique...")

    return await service.process_document_agentique(
        document_id=document_id,
        document_title=document_title,
        document_path=document_path,
        text_content=text_content,
        tenant_id=tenant_id
    )
