"""
🤖 OSMOSE Agentique - Extractor Orchestrator

Routing intelligent pour extraction concepts.
"""

from typing import Dict, Any, Optional, List
import logging
from enum import Enum

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

        logger.info("[EXTRACTOR] Initialized with routing thresholds (NO_LLM<3, SMALL≤8, BIG>8)")

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

            prepass_result = self.call_tool("prepass_analyzer", prepass_input)

            if not prepass_result.success:
                logger.error(f"[EXTRACTOR] PrepassAnalyzer failed for segment {idx}: {prepass_result.message}")
                continue

            prepass_output = PrepassAnalyzerOutput(**prepass_result.data)
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

            extract_result = self.call_tool("extract_concepts", extract_input)

            if not extract_result.success:
                logger.error(f"[EXTRACTOR] Extraction failed for segment {idx}: {extract_result.message}")
                continue

            extract_output = ExtractConceptsOutput(**extract_result.data)

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
            from ...semantic.utils.ner_manager import NERManager

            segment_text = tool_input.segment_text
            language = tool_input.language

            # NER spaCy
            ner_manager = NERManager()
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

            return ToolOutput(
                success=True,
                message="PrepassAnalyzer completed",
                data={
                    "entity_count": entity_count,
                    "entity_density": entity_density,
                    "recommended_route": route,
                    "reasoning": reasoning
                }
            )

        except Exception as e:
            logger.error(f"[EXTRACTOR:PrepassAnalyzer] Error: {e}")
            return ToolOutput(
                success=False,
                message=f"PrepassAnalyzer failed: {str(e)}"
            )

    def _extract_concepts_tool(self, tool_input: ExtractConceptsInput) -> ToolOutput:
        """
        Tool ExtractConcepts: Extrait concepts selon route choisie.

        Args:
            tool_input: Segment + route + use_llm flag

        Returns:
            Liste concepts, cost, llm_calls
        """
        try:
            # Import local pour éviter dépendance circulaire
            from ...semantic.extraction.concept_extractor import ConceptExtractor
            from ...semantic.models.semantic_types import Topic

            segment = tool_input.segment
            route = tool_input.route
            use_llm = tool_input.use_llm

            # Créer Topic object pour ConceptExtractor
            topic = Topic(
                topic_id=segment.get("topic_id", "unknown"),
                text=segment.get("text", ""),
                language=segment.get("language", "en"),
                start_page=segment.get("start_page", 0),
                end_page=segment.get("end_page", 0),
                keywords=segment.get("keywords", [])
            )

            # Instancier ConceptExtractor
            extractor = ConceptExtractor()

            # Extraire concepts (synchrone pour simplifier, TODO: async)
            # Note: Utilise methods=['NER', 'CLUSTERING'] ou ['NER', 'CLUSTERING', 'LLM']
            # TODO: Implémenter logique route SMALL vs BIG (model selection)

            # Pour l'instant: mock simple
            concepts = []
            cost = 0.0
            llm_calls = 0

            if route == ExtractionRoute.NO_LLM:
                # NER + Clustering uniquement
                # TODO: Appeler ConceptExtractor avec enable_llm=False
                concepts = []  # Mock
                cost = 0.0
                llm_calls = 0

            elif route == ExtractionRoute.SMALL:
                # NER + Clustering + LLM (gpt-4o-mini)
                # TODO: Appeler ConceptExtractor avec enable_llm=True, model=SMALL
                concepts = []  # Mock
                cost = 0.002  # Mock: ~$0.002/segment pour SMALL
                llm_calls = 1

            elif route == ExtractionRoute.BIG:
                # NER + Clustering + LLM (gpt-4o)
                # TODO: Appeler ConceptExtractor avec enable_llm=True, model=BIG
                concepts = []  # Mock
                cost = 0.015  # Mock: ~$0.015/segment pour BIG
                llm_calls = 1

            logger.debug(f"[EXTRACTOR:ExtractConcepts] {len(concepts)} concepts extracted, route={route}, cost=${cost:.3f}")

            return ToolOutput(
                success=True,
                message="Concepts extracted successfully",
                data={
                    "concepts": concepts,
                    "cost_incurred": cost,
                    "llm_calls": llm_calls
                }
            )

        except Exception as e:
            logger.error(f"[EXTRACTOR:ExtractConcepts] Error: {e}")
            return ToolOutput(
                success=False,
                message=f"Extraction failed: {str(e)}"
            )
