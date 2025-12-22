"""
🤖 OSMOSE Agentique - Extractor Orchestrator

Routing intelligent pour extraction concepts.
Parallélisation massive pour traitement mono-document rapide.
"""

from typing import Dict, Any, Optional, List, Tuple
import logging
import asyncio
import os
from enum import Enum
from asyncio import Semaphore
from pydantic import model_validator

from ..base import BaseAgent, AgentRole, AgentState, ToolInput, ToolOutput, SegmentWithConcepts

logger = logging.getLogger(__name__)


class ExtractionRoute(str, Enum):
    """Routes d'extraction disponibles."""
    NO_LLM = "NO_LLM"  # NER + Clustering uniquement
    SMALL = "SMALL"    # gpt-4o-mini
    BIG = "BIG"        # gpt-4o ou Claude Sonnet


class RoutingReason(str, Enum):
    """Raisons de routing Phase 1.8."""
    LOW_QUALITY_NER = "LOW_QUALITY_NER"  # < 3 entities ET > 200 tokens → SMALL
    SPARSE_ENTITIES = "SPARSE_ENTITIES"  # Peu d'entities → SMALL
    DENSE_ENTITIES = "DENSE_ENTITIES"    # Beaucoup d'entities → BIG
    BUDGET_FALLBACK = "BUDGET_FALLBACK"  # Fallback budget


class PrepassAnalyzerInput(ToolInput):
    """Input pour PrepassAnalyzer tool."""
    segment_text: str
    language: str = "en"


class PrepassAnalyzerOutput(ToolOutput):
    """Output pour PrepassAnalyzer tool."""
    entity_count: int = 0
    entity_density: float = 0.0
    recommended_route: str = "NO_LLM"
    reasoning: str = ""

    @model_validator(mode='after')
    def sync_from_data(self):
        """Synchronise les attributs depuis data si data est fourni."""
        if self.data and not self.entity_count:
            self.entity_count = self.data.get("entity_count", 0)
        if self.data and not self.entity_density:
            self.entity_density = self.data.get("entity_density", 0.0)
        if self.data and self.recommended_route == "NO_LLM":
            self.recommended_route = self.data.get("recommended_route", "NO_LLM")
        if self.data and not self.reasoning:
            self.reasoning = self.data.get("reasoning", "")
        return self


class ExtractConceptsInput(ToolInput):
    """Input pour ExtractConcepts tool."""
    segment: Dict[str, Any]
    route: str
    use_llm: bool = False
    document_context: Optional[str] = None  # Phase 1.8: Contexte document pour désambiguïsation
    technical_density_hint: float = 0.0  # Phase 1.8.2: Hint LLM pour stratégie extraction domain-agnostic


class ExtractConceptsOutput(ToolOutput):
    """Output pour ExtractConcepts tool."""
    concepts: List[Dict[str, Any]] = []
    cost_incurred: float = 0.0
    llm_calls: int = 0

    @model_validator(mode='after')
    def sync_from_data(self):
        """Synchronise les attributs depuis data si data est fourni."""
        if self.data and not self.concepts:
            self.concepts = self.data.get("concepts", [])
        if self.data and not self.cost_incurred:
            self.cost_incurred = self.data.get("cost_incurred", 0.0)
        if self.data and not self.llm_calls:
            self.llm_calls = self.data.get("llm_calls", 0)
        return self


class ExtractorOrchestrator(BaseAgent):
    """
    Extractor Orchestrator Agent.

    Responsabilités:
    - Analyse segments avec PrepassAnalyzer (NER spaCy)
    - Route vers NO_LLM/SMALL/BIG selon densité entities
    - Extrait concepts avec budget awareness
    - Fallback graceful si budget insuffisant

    Règles routing:
    - NO_LLM: < 3 entities détectées par PrepassAnalyzer
    - SMALL: 3-8 entities, budget SMALL > 0
    - BIG: > 8 entities, budget BIG > 0

    Fallback chain:
    BIG (si budget 0) → SMALL → NO_LLM
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialise l'Extractor Orchestrator."""
        super().__init__(AgentRole.EXTRACTOR, config)

        # Seuils routing (configurables)
        self.no_llm_threshold = config.get("no_llm_threshold", 3) if config else 3
        self.small_threshold = config.get("small_threshold", 8) if config else 8

        # Phase 1.8: Seuils LOW_QUALITY_NER
        self.low_quality_ner_entity_threshold = config.get("low_quality_ner_entities", 3) if config else 3
        self.low_quality_ner_token_threshold = config.get("low_quality_ner_tokens", 200) if config else 200

        # Configuration parallélisation (optimisé pour 8 vCPU)
        self.max_parallel_segments = int(os.getenv("MAX_PARALLEL_SEGMENTS", "5"))

        # Rate limiter LLM (selon tier OpenAI)
        max_rpm = int(os.getenv("OPENAI_MAX_RPM", "500"))
        # Heuristique: max_rpm / 60s * 20s avg_call_duration = concurrent calls
        max_concurrent_llm = min(max_rpm // 3, self.max_parallel_segments)
        self.llm_semaphore = Semaphore(max_concurrent_llm)

        # Lazy-init pour MultilingualConceptExtractor (créé au premier appel)
        self._concept_extractor = None
        self._llm_router = None
        self._semantic_config = None

        logger.info(
            f"[EXTRACTOR] Initialized with routing thresholds (NO_LLM<3, SMALL≤8, BIG>8), "
            f"max_parallel={self.max_parallel_segments}, rate_limit={max_concurrent_llm} concurrent LLM calls"
        )

    def _get_concept_extractor(self):
        """
        Lazy-init du MultilingualConceptExtractor.

        Returns:
            MultilingualConceptExtractor configuré
        """
        if self._concept_extractor is None:
            from ...semantic.extraction.concept_extractor import MultilingualConceptExtractor
            from ...semantic.config import get_semantic_config
            from ...common.llm_router import get_llm_router

            self._semantic_config = get_semantic_config()
            self._llm_router = get_llm_router()
            self._concept_extractor = MultilingualConceptExtractor(
                self._llm_router,
                self._semantic_config
            )
            logger.debug("[EXTRACTOR] MultilingualConceptExtractor initialized")

        return self._concept_extractor

    def _register_tools(self):
        """Enregistre les tools de l'agent."""
        self.tools = {
            "prepass_analyzer": self._prepass_analyzer_tool,
            "extract_concepts": self._extract_concepts_tool
        }

    async def execute(
        self,
        state: AgentState,
        instruction: Optional[str] = None
    ) -> AgentState:
        """
        Exécute l'extraction concepts pour tous les segments EN PARALLÈLE.

        Parallélisation par batches pour respecter rate limits LLM.

        Args:
            state: État actuel (doit contenir state.segments)
            instruction: Ignored (agent autonome)

        Returns:
            État mis à jour avec state.candidates rempli
        """
        # DEBUG Phase 2.9
        print(f"[DEBUG EXTRACTOR] >>> ENTRY execute() with {len(state.segments)} segments")
        logger.info(f"[EXTRACTOR] 🚀 Starting PARALLEL extraction for {len(state.segments)} segments")

        if not state.segments:
            logger.warning("[EXTRACTOR] No segments to process, skipping")
            return state

        # Réinitialiser candidates
        state.candidates = []

        # Traiter en parallèle par batches
        all_results = []
        num_batches = (len(state.segments) + self.max_parallel_segments - 1) // self.max_parallel_segments

        for batch_idx in range(num_batches):
            start_idx = batch_idx * self.max_parallel_segments
            end_idx = min(start_idx + self.max_parallel_segments, len(state.segments))
            batch_segments = state.segments[start_idx:end_idx]

            # DEBUG Phase 2.9
            print(f"[DEBUG EXTRACTOR] Processing batch {batch_idx + 1}/{num_batches} (segments {start_idx + 1}-{end_idx})")
            logger.info(
                f"[EXTRACTOR] 📦 Processing batch {batch_idx + 1}/{num_batches} "
                f"(segments {start_idx + 1}-{end_idx})"
            )

            # Créer tâches pour ce batch
            tasks = [
                self._process_single_segment(start_idx + i, seg, state)
                for i, seg in enumerate(batch_segments)
            ]

            # Exécuter batch en parallèle
            print(f"[DEBUG EXTRACTOR] >>> asyncio.gather() starting for batch {batch_idx + 1}...")
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            print(f"[DEBUG EXTRACTOR] <<< asyncio.gather() done for batch {batch_idx + 1}, got {len(batch_results)} results")

            # Filtrer erreurs
            for result in batch_results:
                if isinstance(result, Exception):
                    logger.error(f"[EXTRACTOR] ❌ Segment processing failed: {result}")
                elif result is not None:
                    all_results.append(result)

            logger.info(f"[EXTRACTOR] ✅ Batch {batch_idx + 1} completed: {len(batch_results)} segments processed")

        # Agréger tous les résultats
        logger.info(f"[EXTRACTOR] 📊 Aggregating {len(all_results)} segment results")

        # Phase 2.9: Initialiser segments_with_concepts pour extraction segment-level
        state.segments_with_concepts = {}

        for idx, segment_id, extract_output, final_route in all_results:
            if extract_output is None:
                continue

            # Phase 2.8.1: Propager segment_id à chaque concept AVANT agrégation
            # Fix Bug #1: segment_id était "unknown" car non propagé ici
            concept_ids_for_segment = []
            for concept in extract_output.concepts:
                concept["segment_id"] = segment_id
                # Phase 2.9: Collecter IDs pour le segment
                concept_id = concept.get("concept_id", "")
                if concept_id:
                    concept_ids_for_segment.append(concept_id)

            # Mettre à jour état
            state.candidates.extend(extract_output.concepts)
            state.cost_incurred += extract_output.cost_incurred

            # Phase 2.9: Stocker segment avec ses concepts locaux
            # Récupérer le texte et topic_id du segment original
            original_segment = next(
                (s for s in state.segments if s.get("segment_id") == segment_id),
                {}
            )

            # DEBUG Phase 2.9.1: Tracer la correspondance segment_id
            segment_text = original_segment.get("text", "")
            if not original_segment:
                logger.warning(
                    f"[EXTRACTOR] ⚠️ DEBUG: segment_id='{segment_id}' NOT FOUND in state.segments! "
                    f"Available segment_ids: {[s.get('segment_id', 'MISSING') for s in state.segments[:5]]}"
                )
            elif not segment_text:
                logger.warning(
                    f"[EXTRACTOR] ⚠️ DEBUG: segment_id='{segment_id}' found but text is empty!"
                )
            else:
                logger.debug(
                    f"[EXTRACTOR] ✅ DEBUG: segment_id='{segment_id}' matched, text_len={len(segment_text)}"
                )

            state.segments_with_concepts[segment_id] = SegmentWithConcepts(
                segment_id=segment_id,
                text=segment_text,
                topic_id=original_segment.get("topic_id", ""),
                local_concept_ids=concept_ids_for_segment,
                catalogue_concept_ids=[]  # Sera rempli par CatalogueBuilder dans Supervisor
            )

            # Mettre à jour compteurs LLM
            if final_route == ExtractionRoute.SMALL:
                state.llm_calls_count["SMALL"] += extract_output.llm_calls
                state.budget_remaining["SMALL"] -= extract_output.llm_calls
            elif final_route == ExtractionRoute.BIG:
                state.llm_calls_count["BIG"] += extract_output.llm_calls
                state.budget_remaining["BIG"] -= extract_output.llm_calls

        # Log final
        logger.info(
            f"[EXTRACTOR] ✅ Extraction complete: {len(state.candidates)} candidates, "
            f"cost ${state.cost_incurred:.2f}, "
            f"budget remaining SMALL={state.budget_remaining['SMALL']} BIG={state.budget_remaining['BIG']}, "
            f"segments_with_concepts={len(state.segments_with_concepts)} (Phase 2.9)"
        )

        return state

    async def _process_single_segment(
        self,
        idx: int,
        segment: dict,
        state: AgentState
    ) -> Optional[Tuple[int, str, Any, str]]:
        """
        Traite UN segment (prepass + extraction) avec rate limiting.

        Args:
            idx: Index du segment
            segment: Données du segment
            state: État global (pour budget)

        Returns:
            (idx, segment_id, extract_output, final_route) ou None si échec
        """
        segment_id = segment.get("segment_id", f"seg_{idx}")

        try:
            # DEBUG Phase 2.9
            print(f"[DEBUG EXTRACTOR] _process_single_segment({idx + 1}) START - segment_id={segment_id}")
            logger.debug(f"[EXTRACTOR] 🔄 Segment {idx + 1} START")

            # Étape 1: Analyser segment avec PrepassAnalyzer (pas de rate limit, local NER)
            prepass_input = PrepassAnalyzerInput(
                segment_text=segment.get("text", ""),
                language=segment.get("language", "en")
            )

            print(f"[DEBUG EXTRACTOR] Segment {idx + 1}: calling prepass_analyzer...")
            prepass_result = await self.call_tool("prepass_analyzer", prepass_input)
            print(f"[DEBUG EXTRACTOR] Segment {idx + 1}: prepass_analyzer done, success={prepass_result.success}")

            if not prepass_result.success:
                logger.error(f"[EXTRACTOR] PrepassAnalyzer failed for segment {idx}: {prepass_result.message}")
                return None

            prepass_output = prepass_result
            recommended_route = prepass_output.recommended_route

            logger.debug(
                f"[EXTRACTOR] Segment {idx + 1}: {prepass_output.entity_count} entities, "
                f"density {prepass_output.entity_density:.2f}, route={recommended_route}"
            )

            # Étape 2: Appliquer fallback si budget insuffisant
            final_route = self._apply_budget_fallback(recommended_route, state)

            if final_route != recommended_route:
                logger.warning(
                    f"[EXTRACTOR] Segment {idx + 1}: Budget fallback {recommended_route} → {final_route}"
                )

            # Étape 3: Extraire concepts avec rate limiting
            # Phase 1.8: Récupérer document_context depuis state si disponible
            document_context = getattr(state, 'document_context', None)
            # Phase 1.8.2: Récupérer technical_density_hint (domain-agnostic)
            technical_density_hint = getattr(state, 'technical_density_hint', 0.0)

            print(f"[DEBUG EXTRACTOR] Segment {idx + 1}: acquiring LLM semaphore for route={final_route}...")
            async with self.llm_semaphore:  # Rate limiter pour appels LLM
                print(f"[DEBUG EXTRACTOR] Segment {idx + 1}: semaphore acquired, calling extract_concepts...")
                extract_input = ExtractConceptsInput(
                    segment=segment,
                    route=final_route,
                    use_llm=(final_route != ExtractionRoute.NO_LLM),
                    document_context=document_context,  # Phase 1.8
                    technical_density_hint=technical_density_hint  # Phase 1.8.2
                )

                extract_result = await self.call_tool("extract_concepts", extract_input)
                print(f"[DEBUG EXTRACTOR] Segment {idx + 1}: extract_concepts done, success={extract_result.success}")

            if not extract_result.success:
                logger.error(f"[EXTRACTOR] Extraction failed for segment {idx}: {extract_result.message}")
                return None

            extract_output = extract_result

            logger.info(
                f"[EXTRACTOR] ✅ Segment {idx + 1} DONE: {len(extract_output.concepts)} concepts, "
                f"cost ${extract_output.cost_incurred:.3f}, route={final_route}"
            )

            return (idx, segment_id, extract_output, final_route)

        except Exception as e:
            logger.error(f"[EXTRACTOR] ❌ Segment {idx + 1} FAILED with exception: {e}", exc_info=True)
            return None

    def _apply_budget_fallback(
        self,
        recommended_route: str,
        state: AgentState
    ) -> str:
        """
        Applique fallback si budget insuffisant.

        Fallback chain: BIG → SMALL → NO_LLM

        Args:
            recommended_route: Route recommandée par PrepassAnalyzer
            state: État actuel avec budgets

        Returns:
            Route finale après fallback
        """
        if recommended_route == ExtractionRoute.BIG:
            if state.budget_remaining["BIG"] > 0:
                return ExtractionRoute.BIG
            elif state.budget_remaining["SMALL"] > 0:
                logger.warning("[EXTRACTOR] BIG budget exhausted, fallback to SMALL")
                return ExtractionRoute.SMALL
            else:
                logger.warning("[EXTRACTOR] All LLM budgets exhausted, fallback to NO_LLM")
                return ExtractionRoute.NO_LLM

        elif recommended_route == ExtractionRoute.SMALL:
            if state.budget_remaining["SMALL"] > 0:
                return ExtractionRoute.SMALL
            else:
                logger.warning("[EXTRACTOR] SMALL budget exhausted, fallback to NO_LLM")
                return ExtractionRoute.NO_LLM

        else:  # NO_LLM
            return ExtractionRoute.NO_LLM

    def _prepass_analyzer_tool(self, tool_input: PrepassAnalyzerInput) -> ToolOutput:
        """
        Tool PrepassAnalyzer: Analyse densité entities avec NER spaCy.

        Args:
            tool_input: Segment text + language

        Returns:
            Entity count, density, recommended route
        """
        try:
            # Import local pour éviter dépendance circulaire
            from ...semantic.utils.ner_manager import get_ner_manager
            from ...semantic.config import get_semantic_config

            segment_text = tool_input.segment_text
            language = tool_input.language

            # NER spaCy - utiliser singleton pour éviter reload modèles à chaque segment
            semantic_config = get_semantic_config()
            ner_manager = get_ner_manager(semantic_config)
            entities = ner_manager.extract_entities(segment_text, language)

            entity_count = len(entities)
            word_count = len(segment_text.split())
            entity_density = entity_count / max(word_count, 1)

            # Phase 1.8: Routing logic avec LOW_QUALITY_NER detection
            # Améliore rappel concepts de 70% → 85% via LLM sur segments problématiques

            # Condition LOW_QUALITY_NER: < 3 entities ET > 200 tokens
            # Signifie: segment long mais NER trouve peu → NER rate probablement des concepts → LLM requis
            is_low_quality_ner = (
                entity_count < self.low_quality_ner_entity_threshold and
                word_count > self.low_quality_ner_token_threshold
            )

            if is_low_quality_ner:
                # Phase 1.8: Forcer SMALL pour segments LOW_QUALITY_NER
                route = ExtractionRoute.SMALL
                routing_reason = RoutingReason.LOW_QUALITY_NER
                reasoning = (
                    f"[PHASE1.8:LOW_QUALITY_NER] {entity_count} entities < {self.low_quality_ner_entity_threshold} "
                    f"ET {word_count} tokens > {self.low_quality_ner_token_threshold} → SMALL LLM requis"
                )
                logger.info(f"[EXTRACTOR:PrepassAnalyzer] {reasoning}")
            elif entity_count <= self.small_threshold:
                # Peu d'entities → SMALL (LLM pour enrichir)
                route = ExtractionRoute.SMALL
                routing_reason = RoutingReason.SPARSE_ENTITIES
                reasoning = f"{entity_count} entities (sparse) → SMALL LLM"
            else:
                # Beaucoup d'entities → BIG (LLM pour structurer)
                route = ExtractionRoute.BIG
                routing_reason = RoutingReason.DENSE_ENTITIES
                reasoning = f"{entity_count} entities > {self.small_threshold}, segment dense → BIG"

            logger.debug(
                f"[EXTRACTOR:PrepassAnalyzer] {entity_count} entities, {word_count} tokens, "
                f"density {entity_density:.2f}, route={route}, reason={routing_reason.value}"
            )

            return PrepassAnalyzerOutput(
                success=True,
                message="PrepassAnalyzer completed",
                entity_count=entity_count,
                entity_density=entity_density,
                recommended_route=route,
                reasoning=reasoning,
                data={
                    "entity_count": entity_count,
                    "entity_density": entity_density,
                    "recommended_route": route,
                    "reasoning": reasoning
                }
            )

        except Exception as e:
            logger.error(f"[EXTRACTOR:PrepassAnalyzer] Error: {e}")
            return PrepassAnalyzerOutput(
                success=False,
                message=f"PrepassAnalyzer failed: {str(e)}",
                entity_count=0,
                entity_density=0.0,
                recommended_route="NO_LLM",
                reasoning=f"Error: {str(e)}"
            )

    async def _extract_concepts_tool(self, tool_input: ExtractConceptsInput) -> ToolOutput:
        """
        Tool ExtractConcepts: Extrait concepts selon route choisie.

        Args:
            tool_input: Segment + route + use_llm flag

        Returns:
            Liste concepts, cost, llm_calls
        """
        try:
            # DEBUG Phase 2.9
            print(f"[DEBUG EXTRACTOR] _extract_concepts_tool: route={tool_input.route}, use_llm={tool_input.use_llm}")

            # Import local pour éviter dépendance circulaire
            from ...semantic.models import Topic, Window
            import asyncio

            segment = tool_input.segment
            route = tool_input.route
            use_llm = tool_input.use_llm
            document_context = tool_input.document_context  # Phase 1.8
            technical_density_hint = tool_input.technical_density_hint  # Phase 1.8.2

            # Créer Topic object pour MultilingualConceptExtractor
            # Note: Topic attend des attributs spécifiques (document_id, section_path, windows, anchors)
            segment_text = segment.get("text", "")

            # Créer une Window à partir du texte du segment
            window = Window(
                text=segment_text,
                start=0,
                end=len(segment_text)
            )

            topic = Topic(
                topic_id=segment.get("topic_id", "unknown"),
                document_id=segment.get("document_id", "unknown"),  # Devra être passé par le state
                section_path=segment.get("section_path", "unknown"),
                windows=[window],
                anchors=segment.get("keywords", []),  # keywords du segment = anchors
                cohesion_score=segment.get("cohesion_score", 0.8)
            )

            # Obtenir MultilingualConceptExtractor (lazy-init)
            print(f"[DEBUG EXTRACTOR] Getting concept extractor (lazy-init)...")
            extractor = self._get_concept_extractor()
            print(f"[DEBUG EXTRACTOR] Concept extractor obtained")

            # Extraire concepts avec MultilingualConceptExtractor
            # Note: La méthode extract_concepts est async
            # Phase 1.8: Passer document_context pour désambiguïsation
            # Phase 1.8.2: Passer technical_density_hint pour stratégie domain-agnostic
            print(f"[DEBUG EXTRACTOR] >>> Calling extractor.extract_concepts() with enable_llm={use_llm}...")
            concepts_list = await extractor.extract_concepts(
                topic,
                enable_llm=use_llm,
                document_context=document_context,
                technical_density_hint=technical_density_hint
            )
            print(f"[DEBUG EXTRACTOR] <<< extractor.extract_concepts() returned {len(concepts_list)} concepts")

            # Convertir List[Concept] en List[Dict] pour JSON serialization
            concepts_dicts = []
            for concept in concepts_list:
                concepts_dicts.append({
                    "concept_id": concept.concept_id,
                    "name": concept.name,
                    "type": concept.type.value if hasattr(concept.type, 'value') else str(concept.type),
                    "definition": concept.definition,
                    "context": concept.context,
                    "language": concept.language,
                    "confidence": concept.confidence,
                    "source_topic_id": concept.source_topic_id,
                    "extraction_method": concept.extraction_method,
                    "related_concepts": concept.related_concepts
                })

            # Estimer cost et llm_calls selon route
            # TODO: Récupérer les vrais coûts depuis LLMRouter
            cost = 0.0
            llm_calls = 0

            if route == ExtractionRoute.SMALL and use_llm:
                cost = 0.002  # Estimation: ~$0.002/segment pour SMALL (gpt-4o-mini)
                llm_calls = 1
            elif route == ExtractionRoute.BIG and use_llm:
                cost = 0.015  # Estimation: ~$0.015/segment pour BIG (gpt-4o)
                llm_calls = 1
            # NO_LLM: cost=0, llm_calls=0

            logger.debug(
                f"[EXTRACTOR:ExtractConcepts] {len(concepts_dicts)} concepts extracted, "
                f"route={route}, use_llm={use_llm}, cost=${cost:.3f}"
            )

            return ExtractConceptsOutput(
                success=True,
                message="Concepts extracted successfully",
                concepts=concepts_dicts,
                cost_incurred=cost,
                llm_calls=llm_calls,
                data={
                    "concepts": concepts_dicts,
                    "cost_incurred": cost,
                    "llm_calls": llm_calls
                }
            )

        except Exception as e:
            logger.error(f"[EXTRACTOR:ExtractConcepts] Error: {e}", exc_info=True)
            return ExtractConceptsOutput(
                success=False,
                message=f"Extraction failed: {str(e)}",
                concepts=[],
                cost_incurred=0.0,
                llm_calls=0,
                data={
                    "concepts": [],
                    "cost_incurred": 0.0,
                    "llm_calls": 0
                }
            )
