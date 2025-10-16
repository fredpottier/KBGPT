"""
🤖 OSMOSE Agentique - Extractor Orchestrator

Routing intelligent pour extraction concepts.
"""

from typing import Dict, Any, Optional, List
import logging
from enum import Enum
from pydantic import model_validator

from ..base import BaseAgent, AgentRole, AgentState, ToolInput, ToolOutput

logger = logging.getLogger(__name__)


class ExtractionRoute(str, Enum):
    """Routes d'extraction disponibles."""
    NO_LLM = "NO_LLM"  # NER + Clustering uniquement
    SMALL = "SMALL"    # gpt-4o-mini
    BIG = "BIG"        # gpt-4o ou Claude Sonnet


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

        # Lazy-init pour MultilingualConceptExtractor (créé au premier appel)
        self._concept_extractor = None
        self._llm_router = None
        self._semantic_config = None

        logger.info("[EXTRACTOR] Initialized with routing thresholds (NO_LLM<3, SMALL≤8, BIG>8)")

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
        Exécute l'extraction concepts pour tous les segments.

        Args:
            state: État actuel (doit contenir state.segments)
            instruction: Ignored (agent autonome)

        Returns:
            État mis à jour avec state.candidates rempli
        """
        logger.info(f"[EXTRACTOR] Starting extraction for {len(state.segments)} segments")

        if not state.segments:
            logger.warning("[EXTRACTOR] No segments to process, skipping")
            return state

        # Réinitialiser candidates
        state.candidates = []

        # Traiter chaque segment
        for idx, segment in enumerate(state.segments):
            logger.debug(f"[EXTRACTOR] Processing segment {idx+1}/{len(state.segments)}")

            # Étape 1: Analyser segment avec PrepassAnalyzer
            prepass_input = PrepassAnalyzerInput(
                segment_text=segment.get("text", ""),
                language=segment.get("language", "en")
            )

            prepass_result = await self.call_tool("prepass_analyzer", prepass_input)

            if not prepass_result.success:
                logger.error(f"[EXTRACTOR] PrepassAnalyzer failed for segment {idx}: {prepass_result.message}")
                continue

            # prepass_result est déjà un PrepassAnalyzerOutput (hérite de ToolOutput)
            prepass_output = prepass_result
            recommended_route = prepass_output.recommended_route

            logger.info(
                f"[EXTRACTOR] Segment {idx}: {prepass_output.entity_count} entities, "
                f"density {prepass_output.entity_density:.2f}, route={recommended_route}"
            )

            # Étape 2: Appliquer fallback si budget insuffisant
            final_route = self._apply_budget_fallback(recommended_route, state)

            if final_route != recommended_route:
                logger.warning(
                    f"[EXTRACTOR] Budget fallback: {recommended_route} → {final_route}"
                )

            # Étape 3: Extraire concepts avec route choisie
            extract_input = ExtractConceptsInput(
                segment=segment,
                route=final_route,
                use_llm=(final_route != ExtractionRoute.NO_LLM)
            )

            extract_result = await self.call_tool("extract_concepts", extract_input)

            if not extract_result.success:
                logger.error(f"[EXTRACTOR] Extraction failed for segment {idx}: {extract_result.message}")
                continue

            # extract_result est déjà un ExtractConceptsOutput (hérite de ToolOutput)
            extract_output = extract_result

            # Mettre à jour état
            state.candidates.extend(extract_output.concepts)
            state.cost_incurred += extract_output.cost_incurred

            # Mettre à jour compteurs LLM
            if final_route == ExtractionRoute.SMALL:
                state.llm_calls_count["SMALL"] += extract_output.llm_calls
                state.budget_remaining["SMALL"] -= extract_output.llm_calls
            elif final_route == ExtractionRoute.BIG:
                state.llm_calls_count["BIG"] += extract_output.llm_calls
                state.budget_remaining["BIG"] -= extract_output.llm_calls

            logger.info(
                f"[EXTRACTOR] Segment {idx}: {len(extract_output.concepts)} concepts, "
                f"cost ${extract_output.cost_incurred:.3f}, route={final_route}"
            )

        # Log final
        logger.info(
            f"[EXTRACTOR] Extraction complete: {len(state.candidates)} candidates, "
            f"cost ${state.cost_incurred:.2f}, "
            f"budget remaining SMALL={state.budget_remaining['SMALL']} BIG={state.budget_remaining['BIG']}"
        )

        return state

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
            from ...semantic.utils.ner_manager import MultilingualNER
            from ...semantic.config import get_semantic_config

            segment_text = tool_input.segment_text
            language = tool_input.language

            # NER spaCy
            semantic_config = get_semantic_config()
            ner_manager = MultilingualNER(semantic_config)
            entities = ner_manager.extract_entities(segment_text, language)

            entity_count = len(entities)
            word_count = len(segment_text.split())
            entity_density = entity_count / max(word_count, 1)

            # Routing logic
            if entity_count < self.no_llm_threshold:
                route = ExtractionRoute.NO_LLM
                reasoning = f"{entity_count} entities < {self.no_llm_threshold}, NO_LLM suffisant"
            elif entity_count <= self.small_threshold:
                route = ExtractionRoute.SMALL
                reasoning = f"{entity_count} entities, complexité modérée → SMALL"
            else:
                route = ExtractionRoute.BIG
                reasoning = f"{entity_count} entities > {self.small_threshold}, segment dense → BIG"

            logger.debug(f"[EXTRACTOR:PrepassAnalyzer] {entity_count} entities, density {entity_density:.2f}, route={route}")

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
            # Import local pour éviter dépendance circulaire
            from ...semantic.models import Topic, Window
            import asyncio

            segment = tool_input.segment
            route = tool_input.route
            use_llm = tool_input.use_llm

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
            extractor = self._get_concept_extractor()

            # Extraire concepts avec MultilingualConceptExtractor
            # Note: La méthode extract_concepts est async
            concepts_list = await extractor.extract_concepts(topic, enable_llm=use_llm)

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
