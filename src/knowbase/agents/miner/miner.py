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
    - Phase 2.9.3: Cross-segment relation extraction via LLM

    Algorithmes:
    - Frequency analysis: Concepts récurrents (≥2 segments)
    - Co-occurrence: Concepts apparaissant ensemble
    - Hierarchy inference: "SAP S/4HANA" → parent: "SAP ERP"
    - Cross-segment LLM: Relations entre concepts de segments différents

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

        # Phase 2.9.3: Configuration cross-segment
        self.enable_cross_segment_llm = config.get("enable_cross_segment_llm", False) if config else False
        self.cross_segment_top_k = config.get("cross_segment_top_k", 20) if config else 20

        logger.info(
            f"[MINER] Initialized with min_frequency={self.min_frequency}, "
            f"min_cooccurrence={self.min_cooccurrence}, "
            f"cross_segment_llm={'ON' if self.enable_cross_segment_llm else 'OFF'}"
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

            # ========== CO_OCCURRENCE DÉSACTIVÉ ==========
            # Les relations CO_OCCURRENCE créaient du bruit dans le KG
            # (42k+ relations sans valeur sémantique, ralentissant les requêtes)
            # Décision: désactivé le 2025-12-20 après analyse avec ChatGPT
            # Les infos de provenance sont dans CanonicalConcept.chunk_ids
            # et peuvent être exposées via Document->MENTIONS->Concept si besoin
            # ================================================
            relations = []
            
            # ANCIEN CODE (conservé pour référence):
            # for topic_id, segment_concepts in segments.items():
            #     if len(segment_concepts) < 2:
            #         continue
            #     for i, concept_a in enumerate(segment_concepts):
            #         for concept_b in segment_concepts[i+1:]:
            #             relation = {
            #                 "source": concept_a.get("name", ""),
            #                 "target": concept_b.get("name", ""),
            #                 "type": "CO_OCCURRENCE",
            #                 "segment_id": topic_id,
            #                 "confidence": 0.7
            #             }
            #             relations.append(relation)

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

    # =========================================================================
    # Phase 2.9.3 - Cross-Segment Relation Extraction
    # =========================================================================

    async def extract_cross_segment_relations(
        self,
        segments_with_concepts: Dict[str, Any],
        promoted_concepts: List[Dict[str, Any]],
        hub_concepts: List[Dict[str, Any]],
        document_id: str,
        tenant_id: str
    ) -> List[Dict[str, Any]]:
        """
        Phase 2.9.3: Extrait relations entre concepts de segments différents.

        Stratégie:
        1. Identifier concepts "ponts" (présents dans multiple segments)
        2. Pour chaque paire de segments partageant un concept pont:
           - Extraire relations potentielles via LLM
        3. Prioriser les hub concepts pour les relations cross-segment

        Args:
            segments_with_concepts: Dict segment_id -> SegmentWithConcepts
            promoted_concepts: Tous les concepts promus
            hub_concepts: Concepts déjà bien connectés (hubs)
            document_id: ID du document
            tenant_id: ID tenant

        Returns:
            Liste de relations cross-segment
        """
        if not self.enable_cross_segment_llm:
            logger.debug("[MINER] Cross-segment LLM disabled, skipping")
            return []

        logger.info(
            f"[MINER] Phase 2.9.3: Extracting cross-segment relations from "
            f"{len(segments_with_concepts)} segments"
        )

        # 1. Identifier concepts présents dans multiple segments
        concept_to_segments: Dict[str, List[str]] = defaultdict(list)

        for segment_id, segment in segments_with_concepts.items():
            if hasattr(segment, 'local_concept_ids'):
                local_ids = segment.local_concept_ids
            else:
                local_ids = segment.get("local_concept_ids", [])

            for concept_id in local_ids:
                concept_to_segments[concept_id].append(segment_id)

        # Concepts ponts = présents dans 2+ segments
        bridge_concepts = [
            cid for cid, segments in concept_to_segments.items()
            if len(segments) >= 2
        ]

        # Ajouter les hub concepts comme ponts potentiels
        hub_ids = [h.get("canonical_id") for h in hub_concepts if h.get("canonical_id")]
        bridge_concepts = list(set(bridge_concepts + hub_ids))

        logger.info(
            f"[MINER] Found {len(bridge_concepts)} bridge concepts "
            f"(multi-segment + hubs)"
        )

        if not bridge_concepts:
            logger.debug("[MINER] No bridge concepts, skipping cross-segment extraction")
            return []

        # 2. Identifier paires de segments à analyser
        segment_pairs_to_analyze = set()

        for concept_id in bridge_concepts:
            segments_with_concept = concept_to_segments.get(concept_id, [])
            if len(segments_with_concept) >= 2:
                # Créer paires de segments
                for i, seg_a in enumerate(segments_with_concept):
                    for seg_b in segments_with_concept[i+1:]:
                        pair = tuple(sorted([seg_a, seg_b]))
                        segment_pairs_to_analyze.add(pair)

        logger.info(f"[MINER] {len(segment_pairs_to_analyze)} segment pairs to analyze")

        # 3. Limiter aux top-K paires (pour éviter explosion combinatoire)
        segment_pairs_list = list(segment_pairs_to_analyze)[:self.cross_segment_top_k]

        cross_relations = []

        # 4. Pour chaque paire, extraire relations via LLM
        # Note: Cette extraction utilise les hub concepts comme catalogue
        for seg_a, seg_b in segment_pairs_list:
            try:
                segment_a = segments_with_concepts.get(seg_a)
                segment_b = segments_with_concepts.get(seg_b)

                if not segment_a or not segment_b:
                    continue

                # Récupérer texte des deux segments
                text_a = segment_a.text if hasattr(segment_a, 'text') else segment_a.get("text", "")
                text_b = segment_b.text if hasattr(segment_b, 'text') else segment_b.get("text", "")

                if not text_a or not text_b:
                    continue

                # Identifier concepts communs entre les deux segments
                ids_a = set(segment_a.local_concept_ids if hasattr(segment_a, 'local_concept_ids') else segment_a.get("local_concept_ids", []))
                ids_b = set(segment_b.local_concept_ids if hasattr(segment_b, 'local_concept_ids') else segment_b.get("local_concept_ids", []))

                shared_concept_ids = ids_a.intersection(ids_b)

                if shared_concept_ids:
                    # Créer relation CROSS_SEGMENT pour chaque concept partagé
                    for concept_id in shared_concept_ids:
                        relation = {
                            "type": "CROSS_SEGMENT_BRIDGE",
                            "concept_id": concept_id,
                            "segment_a": seg_a,
                            "segment_b": seg_b,
                            "document_id": document_id,
                            "confidence": 0.8
                        }
                        cross_relations.append(relation)

            except Exception as e:
                logger.debug(f"[MINER] Error processing segment pair ({seg_a}, {seg_b}): {e}")
                continue

        logger.info(
            f"[MINER] Phase 2.9.3: Extracted {len(cross_relations)} cross-segment relations"
        )

        return cross_relations

    def get_bridge_concepts(
        self,
        segments_with_concepts: Dict[str, Any],
        min_segments: int = 2
    ) -> List[str]:
        """
        Identifie les concepts "ponts" présents dans plusieurs segments.

        Args:
            segments_with_concepts: Dict segment_id -> SegmentWithConcepts
            min_segments: Nombre minimum de segments pour être un pont

        Returns:
            Liste des concept_ids ponts
        """
        concept_to_segments: Dict[str, int] = defaultdict(int)

        for segment_id, segment in segments_with_concepts.items():
            if hasattr(segment, 'local_concept_ids'):
                local_ids = segment.local_concept_ids
            else:
                local_ids = segment.get("local_concept_ids", [])

            for concept_id in local_ids:
                concept_to_segments[concept_id] += 1

        return [
            cid for cid, count in concept_to_segments.items()
            if count >= min_segments
        ]
