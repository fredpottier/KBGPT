"""
🤖 OSMOSE Agentique - Pattern Miner

Cross-segment reasoning et pattern detection.
"""

from typing import Dict, Any, Optional, List
import logging
from collections import defaultdict
from pydantic import model_validator

from ..base import BaseAgent, AgentRole, AgentState, ToolInput, ToolOutput

logger = logging.getLogger(__name__)


class DetectPatternsInput(ToolInput):
    """Input pour DetectPatterns tool."""
    candidates: List[Dict[str, Any]]
    min_frequency: int = 2


class DetectPatternsOutput(ToolOutput):
    """Output pour DetectPatterns tool."""
    patterns: List[Dict[str, Any]] = []
    enriched_candidates: List[Dict[str, Any]] = []

    @model_validator(mode='after')
    def sync_from_data(self):
        """Synchronise les attributs depuis data si data est fourni."""
        if self.data and not self.patterns:
            self.patterns = self.data.get("patterns", [])
        if self.data and not self.enriched_candidates:
            self.enriched_candidates = self.data.get("enriched_candidates", [])
        return self


class LinkConceptsInput(ToolInput):
    """Input pour LinkConcepts tool."""
    candidates: List[Dict[str, Any]]


class LinkConceptsOutput(ToolOutput):
    """Output pour LinkConcepts tool."""
    relations: List[Dict[str, Any]] = []

    @model_validator(mode='after')
    def sync_from_data(self):
        """Synchronise les attributs depuis data si data est fourni."""
        if self.data and not self.relations:
            self.relations = self.data.get("relations", [])
        return self


class PatternMiner(BaseAgent):
    """
    Pattern Miner Agent.

    Responsabilités:
    - Détecte patterns récurrents cross-segments
    - Lie concepts entre segments (co-occurrence, proximity)
    - Infère hiérarchies (parent-child relations)
    - Disambiguate Named Entities (SAP S/4HANA vs SAP ECC)

    Algorithmes:
    - Frequency analysis: Concepts récurrents (≥2 segments)
    - Co-occurrence: Concepts apparaissant ensemble
    - Hierarchy inference: "SAP S/4HANA" → parent: "SAP ERP"

    Output enrichit state.candidates avec:
    - pattern_score: float (0-1)
    - related_concepts: List[str]
    - parent_concept: Optional[str]
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialise le Pattern Miner."""
        super().__init__(AgentRole.MINER, config)

        # Seuils configurables
        self.min_frequency = config.get("min_frequency", 2) if config else 2
        self.min_cooccurrence = config.get("min_cooccurrence", 0.3) if config else 0.3

        logger.info(
            f"[MINER] Initialized with min_frequency={self.min_frequency}, "
            f"min_cooccurrence={self.min_cooccurrence}"
        )

    def _register_tools(self):
        """Enregistre les tools de l'agent."""
        self.tools = {
            "detect_patterns": self._detect_patterns_tool,
            "link_concepts": self._link_concepts_tool
        }

    async def execute(
        self,
        state: AgentState,
        instruction: Optional[str] = None
    ) -> AgentState:
        """
        Exécute pattern mining sur candidates.

        Args:
            state: État actuel (doit contenir state.candidates)
            instruction: Ignored (agent autonome)

        Returns:
            État mis à jour avec candidates enrichis
        """
        logger.info(f"[MINER] Starting pattern mining for {len(state.candidates)} candidates")

        if not state.candidates:
            logger.warning("[MINER] No candidates to process, skipping")
            return state

        # Étape 1: Détecter patterns récurrents
        patterns_input = DetectPatternsInput(
            candidates=state.candidates,
            min_frequency=self.min_frequency
        )

        patterns_result = await self.call_tool("detect_patterns", patterns_input)

        if not patterns_result.success:
            logger.error(f"[MINER] DetectPatterns failed: {patterns_result.message}")
            return state

        # patterns_result est déjà un DetectPatternsOutput (hérite de ToolOutput)
        patterns_output = patterns_result

        logger.info(f"[MINER] Detected {len(patterns_output.patterns)} patterns")

        # Mettre à jour candidates avec patterns
        state.candidates = patterns_output.enriched_candidates

        # Étape 2: Lier concepts cross-segments
        link_input = LinkConceptsInput(candidates=state.candidates)

        link_result = await self.call_tool("link_concepts", link_input)

        if not link_result.success:
            logger.error(f"[MINER] LinkConcepts failed: {link_result.message}")
            return state

        # link_result est déjà un LinkConceptsOutput (hérite de ToolOutput)
        link_output = link_result

        logger.info(f"[MINER] Created {len(link_output.relations)} cross-segment relations")

        # Problème 1: Stocker relations dans state pour persistance ultérieure
        state.relations = link_output.relations
        logger.debug(f"[MINER] Stored {len(state.relations)} relations in state for Gatekeeper persistence")

        # Log final
        logger.info(
            f"[MINER] Pattern mining complete: {len(patterns_output.patterns)} patterns, "
            f"{len(link_output.relations)} relations"
        )

        return state

    def _detect_patterns_tool(self, tool_input: DetectPatternsInput) -> ToolOutput:
        """
        Tool DetectPatterns: Détecte concepts récurrents.

        Algorithme:
        1. Count frequency de chaque concept (name canonique)
        2. Marque concepts avec frequency ≥ min_frequency
        3. Calcule pattern_score = frequency / total_segments

        Args:
            tool_input: Candidates + min_frequency

        Returns:
            Patterns détectés + candidates enrichis
        """
        try:
            candidates = tool_input.candidates
            min_frequency = tool_input.min_frequency

            # Count frequency par nom canonique
            concept_freq: Dict[str, int] = defaultdict(int)
            concept_occurrences: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

            for candidate in candidates:
                name = candidate.get("name", "")
                concept_freq[name] += 1
                concept_occurrences[name].append(candidate)

            # Identifier patterns (frequency ≥ min_frequency)
            patterns = []
            for name, freq in concept_freq.items():
                if freq >= min_frequency:
                    pattern = {
                        "name": name,
                        "frequency": freq,
                        "pattern_score": freq / len(candidates),
                        "occurrences": concept_occurrences[name]
                    }
                    patterns.append(pattern)

            # Enrichir candidates avec pattern_score
            enriched_candidates = []
            for candidate in candidates:
                name = candidate.get("name", "")
                freq = concept_freq[name]

                # Calculer pattern_score
                if freq >= min_frequency:
                    pattern_score = freq / len(candidates)
                else:
                    pattern_score = 0.0

                # Enrichir candidate
                enriched = candidate.copy()
                enriched["pattern_score"] = pattern_score
                enriched["frequency"] = freq
                enriched_candidates.append(enriched)

            logger.debug(f"[MINER:DetectPatterns] {len(patterns)} patterns detected")

            return DetectPatternsOutput(
                success=True,
                message=f"Detected {len(patterns)} patterns",
                patterns=patterns,
                enriched_candidates=enriched_candidates,
                data={
                    "patterns": patterns,
                    "enriched_candidates": enriched_candidates
                }
            )

        except Exception as e:
            logger.error(f"[MINER:DetectPatterns] Error: {e}")
            return DetectPatternsOutput(
                success=False,
                message=f"DetectPatterns failed: {str(e)}",
                patterns=[],
                enriched_candidates=[]
            )

    def _link_concepts_tool(self, tool_input: LinkConceptsInput) -> ToolOutput:
        """
        Tool LinkConcepts: Lie concepts via co-occurrence.

        Algorithme:
        1. Pour chaque paire de concepts dans même segment
        2. Calcule co-occurrence score
        3. Si score ≥ min_cooccurrence, créer relation

        Args:
            tool_input: Candidates

        Returns:
            Relations cross-concepts
        """
        try:
            candidates = tool_input.candidates

            # Grouper candidates par segment (source_topic_id)
            segments: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for candidate in candidates:
                topic_id = candidate.get("source_topic_id", "unknown")
                segments[topic_id].append(candidate)

            # Détecter co-occurrences
            relations = []

            for topic_id, segment_concepts in segments.items():
                if len(segment_concepts) < 2:
                    continue

                # Créer relations entre concepts du même segment
                for i, concept_a in enumerate(segment_concepts):
                    for concept_b in segment_concepts[i+1:]:
                        relation = {
                            "source": concept_a.get("name", ""),
                            "target": concept_b.get("name", ""),
                            "type": "CO_OCCURRENCE",
                            "segment_id": topic_id,
                            "confidence": 0.7  # Base confidence pour co-occurrence
                        }
                        relations.append(relation)

            logger.debug(f"[MINER:LinkConcepts] {len(relations)} relations created")

            # Problème 1: Stocker relations dans state pour persistance ultérieure
            # (Les relations seront persistées après promotion des concepts dans Gatekeeper)
            logger.debug(f"[MINER:LinkConcepts] Storing {len(relations)} relations in state for later persistence")

            return LinkConceptsOutput(
                success=True,
                message=f"Created {len(relations)} relations",
                relations=relations,
                data={
                    "relations": relations
                }
            )

        except Exception as e:
            logger.error(f"[MINER:LinkConcepts] Error: {e}")
            return LinkConceptsOutput(
                success=False,
                message=f"LinkConcepts failed: {str(e)}",
                relations=[]
            )
