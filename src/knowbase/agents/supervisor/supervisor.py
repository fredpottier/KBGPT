"""
🤖 OSMOSE Agentique - Supervisor Agent

FSM Master pour orchestration des agents spécialisés.
"""

from typing import Dict, Any, Optional, List
from enum import Enum
import logging
import time

from ..base import BaseAgent, AgentRole, AgentState, ToolOutput
from ..extractor import ExtractorOrchestrator
from ..miner import PatternMiner
from ..gatekeeper import GatekeeperDelegate
from ..budget import BudgetManager
from ..dispatcher import LLMDispatcher

logger = logging.getLogger(__name__)


class FSMState(str, Enum):
    """États de la FSM du Supervisor."""
    INIT = "init"
    BUDGET_CHECK = "budget_check"
    SEGMENT = "segment"
    EXTRACT = "extract"
    MINE_PATTERNS = "mine_patterns"
    GATE_CHECK = "gate_check"
    EXTRACT_RELATIONS = "extract_relations"  # Phase 2 OSMOSE
    FINALIZE = "finalize"
    ERROR = "error"
    DONE = "done"


class SupervisorAgent(BaseAgent):
    """
    Supervisor Agent - FSM Master.

    Pipeline FSM:
    INIT → BUDGET_CHECK → SEGMENT → EXTRACT → MINE_PATTERNS → GATE_CHECK → EXTRACT_RELATIONS → FINALIZE → DONE

    Transitions conditionnelles:
    - BUDGET_CHECK fail → ERROR
    - GATE_CHECK fail → EXTRACT (retry avec BIG model)
    - Any step timeout → ERROR
    - Max steps reached → ERROR

    Note: La promotion vers Neo4j est gérée par GatekeeperDelegate dans GATE_CHECK.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialise le Supervisor Agent."""
        super().__init__(AgentRole.SUPERVISOR, config)

        # Instancier les agents spécialistes
        self.budget_manager = BudgetManager(config)
        self.extractor = ExtractorOrchestrator(config)
        self.miner = PatternMiner(config)
        self.gatekeeper = GatekeeperDelegate(config)
        self.dispatcher = LLMDispatcher(config)

        # Phase 2.8+ OSMOSE: Composants extraction relations (ID-First architecture)
        self.llm_relation_extractor = None  # Lazy load - LLMRelationExtractor ID-First
        self.raw_assertion_writer = None  # Lazy load - RawAssertionWriter pour Neo4j nodes
        self.unresolved_mention_writer = None  # Lazy load - UnresolvedMentionWriter pour Neo4j

        # FSM transitions (état actuel → états suivants possibles)
        self.fsm_transitions: Dict[FSMState, List[FSMState]] = {
            FSMState.INIT: [FSMState.BUDGET_CHECK],
            FSMState.BUDGET_CHECK: [FSMState.SEGMENT, FSMState.ERROR],
            FSMState.SEGMENT: [FSMState.EXTRACT, FSMState.ERROR],
            FSMState.EXTRACT: [FSMState.MINE_PATTERNS, FSMState.ERROR],
            FSMState.MINE_PATTERNS: [FSMState.GATE_CHECK, FSMState.ERROR],
            FSMState.GATE_CHECK: [FSMState.EXTRACT_RELATIONS, FSMState.EXTRACT, FSMState.ERROR],  # Retry si fail
            FSMState.EXTRACT_RELATIONS: [FSMState.FINALIZE, FSMState.ERROR],
            FSMState.FINALIZE: [FSMState.DONE, FSMState.ERROR],
            FSMState.ERROR: [FSMState.DONE],  # Terminaison forcée
            FSMState.DONE: []  # État terminal
        }

        logger.info("[SUPERVISOR] Initialized with FSM and 5 specialist agents")

    def _register_tools(self):
        """Le Supervisor n'a pas de tools directs (coordonne les autres agents)."""
        pass

    async def execute(
        self,
        state: AgentState,
        instruction: Optional[str] = None
    ) -> AgentState:
        """
        Exécute la FSM complète pour un document.

        Args:
            state: État initial
            instruction: Ignored (Supervisor est autonome)

        Returns:
            État final après traitement
        """
        logger.info(f"[SUPERVISOR] Starting FSM for document {state.document_id}")

        # DEBUG: Vérifier réception des segments
        logger.info(
            f"[SUPERVISOR] 🔍 DEBUG: Received {len(state.segments)} segments from osmose_agentique"
        )
        if state.segments:
            logger.info(
                f"[SUPERVISOR] 🔍 DEBUG: First segment keys: {list(state.segments[0].keys())}"
            )
        else:
            logger.error("[SUPERVISOR] 🔍 DEBUG: WARNING - No segments received!")

        # Initialiser FSM
        current_fsm_state = FSMState.INIT
        state.current_step = current_fsm_state.value

        while current_fsm_state != FSMState.DONE:
            # Vérifications globales
            if not self.validate_state(state):
                logger.error("[SUPERVISOR] State validation failed, forcing ERROR → DONE transition")
                current_fsm_state = FSMState.ERROR
                state.current_step = current_fsm_state.value
                state.errors.append("Timeout or max steps reached")
                # Forcer transition vers DONE immédiatement (ne pas continuer la boucle)
                break

            # Incrémenter compteur steps
            state.steps_count += 1

            logger.info(
                f"[SUPERVISOR] Step {state.steps_count}/{state.max_steps}: "
                f"FSM state = {current_fsm_state.value}"
            )

            # Exécuter action selon état FSM
            try:
                next_state = await self._execute_fsm_step(current_fsm_state, state)

                # Valider transition
                if next_state not in self.fsm_transitions[current_fsm_state]:
                    logger.error(
                        f"[SUPERVISOR] Invalid FSM transition: "
                        f"{current_fsm_state.value} → {next_state.value}"
                    )
                    next_state = FSMState.ERROR

                current_fsm_state = next_state
                state.current_step = current_fsm_state.value

            except Exception as e:
                logger.error(f"[SUPERVISOR] FSM step failed: {e}")
                state.errors.append(f"FSM step {current_fsm_state.value} failed: {str(e)}")
                current_fsm_state = FSMState.ERROR
                state.current_step = current_fsm_state.value

        # Log final
        elapsed = time.time() - state.started_at
        logger.info(
            f"[SUPERVISOR] FSM completed for {state.document_id} in {elapsed:.1f}s. "
            f"Steps: {state.steps_count}, Cost: ${state.cost_incurred:.2f}, "
            f"Promoted: {len(state.promoted)}"
        )

        return state

    async def _execute_fsm_step(
        self,
        fsm_state: FSMState,
        state: AgentState
    ) -> FSMState:
        """
        Exécute une étape de la FSM.

        Args:
            fsm_state: État FSM actuel
            state: État partagé

        Returns:
            Prochain état FSM
        """
        # Timer pour mesurer le temps de chaque étape
        step_start = time.time()

        if fsm_state == FSMState.INIT:
            logger.debug("[SUPERVISOR] INIT: Starting pipeline")
            return FSMState.BUDGET_CHECK

        elif fsm_state == FSMState.BUDGET_CHECK:
            # Vérifier budget disponible
            budget_ok = await self.budget_manager.check_budget(state)
            elapsed = time.time() - step_start
            if budget_ok:
                logger.info(f"[SUPERVISOR] ⏱️ BUDGET_CHECK: OK in {elapsed:.1f}s, proceeding to SEGMENT")
                return FSMState.SEGMENT
            else:
                logger.warning(f"[SUPERVISOR] ⏱️ BUDGET_CHECK: Budget insufficient ({elapsed:.1f}s)")
                state.errors.append("Budget insufficient")
                return FSMState.ERROR

        elif fsm_state == FSMState.SEGMENT:
            # Segmentation (utilise SemanticPipeline existant)
            logger.info("[SUPERVISOR] ⏱️ SEGMENT: START")

            # Si segments déjà présents (passés par osmose_agentique), les garder
            if len(state.segments) > 0:
                elapsed = time.time() - step_start
                logger.info(f"[SUPERVISOR] ⏱️ SEGMENT: Segments already present ({len(state.segments)}) in {elapsed:.1f}s, skipping segmentation")
                return FSMState.EXTRACT

            # TODO: Intégrer TopicSegmenter si segments vides
            elapsed = time.time() - step_start
            logger.warning(f"[SUPERVISOR] ⏱️ SEGMENT: No segments found ({elapsed:.1f}s), should call TopicSegmenter here (TODO)")
            state.segments = []  # Placeholder pour éviter erreur
            return FSMState.EXTRACT

        elif fsm_state == FSMState.EXTRACT:
            # Extraction concepts via Extractor Orchestrator
            logger.info("[SUPERVISOR] ⏱️ EXTRACT: START - Calling ExtractorOrchestrator")
            state = await self.extractor.execute(state)
            elapsed = time.time() - step_start
            logger.info(f"[SUPERVISOR] ⏱️ EXTRACT: COMPLETE in {elapsed:.1f}s")
            return FSMState.MINE_PATTERNS

        elif fsm_state == FSMState.MINE_PATTERNS:
            # Mining patterns cross-segments
            logger.info("[SUPERVISOR] ⏱️ MINE_PATTERNS: START - Calling PatternMiner")
            state = await self.miner.execute(state)
            elapsed = time.time() - step_start
            logger.info(f"[SUPERVISOR] ⏱️ MINE_PATTERNS: COMPLETE in {elapsed:.1f}s")
            return FSMState.GATE_CHECK

        elif fsm_state == FSMState.GATE_CHECK:
            # Quality gate check + promotion vers Neo4j (gérée par GatekeeperDelegate)
            logger.info("[SUPERVISOR] ⏱️ GATE_CHECK: START - Calling GatekeeperDelegate")
            state = await self.gatekeeper.execute(state)
            elapsed = time.time() - step_start

            # Si qualité insuffisante et budget permet, retry avec BIG model
            if len(state.promoted) == 0 and state.budget_remaining["BIG"] > 0:
                logger.warning(f"[SUPERVISOR] ⏱️ GATE_CHECK: Quality low ({elapsed:.1f}s), retrying with BIG")
                return FSMState.EXTRACT  # Retry
            else:
                logger.info(f"[SUPERVISOR] ⏱️ GATE_CHECK: COMPLETE in {elapsed:.1f}s - {len(state.promoted)} concepts promoted to Neo4j")
                return FSMState.EXTRACT_RELATIONS

        elif fsm_state == FSMState.EXTRACT_RELATIONS:
            # =================================================================
            # Phase 2.9 OSMOSE: SEGMENT-LEVEL Relation Extraction
            # =================================================================
            logger.info(
                f"[SUPERVISOR] ⏱️ EXTRACT_RELATIONS (Phase 2.9 Segment-Level): START - "
                f"promoted={len(state.promoted) if state.promoted else 0}, "
                f"segments_with_concepts={len(state.segments_with_concepts)}"
            )

            # Skip si aucun concept promu
            if not state.promoted or len(state.promoted) == 0:
                logger.warning("[SUPERVISOR] EXTRACT_RELATIONS: No promoted concepts, skipping")
                return FSMState.FINALIZE

            # Préparer connexion Neo4j
            from knowbase.common.clients.neo4j_client import get_neo4j_client
            neo4j_client = get_neo4j_client()

            # Phase 2.9: Lazy load composants
            if self.llm_relation_extractor is None:
                from knowbase.relations import (
                    LLMRelationExtractor,
                    RawAssertionWriter,
                    UnresolvedMentionWriter,
                )
                from knowbase.common.llm_router import LLMRouter

                self.llm_relation_extractor = LLMRelationExtractor(
                    llm_router=LLMRouter(),
                    model="gpt-4o-mini",
                    use_id_first=True
                )
                self.raw_assertion_writer = RawAssertionWriter(
                    tenant_id=state.tenant_id,
                    extractor_version="v2.9.0",
                    model_used="gpt-4o-mini",
                    neo4j_client=neo4j_client
                )
                self.unresolved_mention_writer = UnresolvedMentionWriter(
                    tenant_id=state.tenant_id,
                    neo4j_client=neo4j_client
                )
                logger.info(
                    "[SUPERVISOR] EXTRACT_RELATIONS: Initialized Phase 2.9 components"
                )

            # Préparer promoted concepts comme dict pour lookup rapide
            promoted_by_id = {}
            for concept_data in state.promoted:
                canonical_id = concept_data.get("canonical_id") or concept_data.get("concept_id")
                if canonical_id:
                    promoted_by_id[canonical_id] = {
                        "canonical_id": canonical_id,
                        "canonical_name": concept_data.get("canonical_name", ""),
                        "surface_forms": concept_data.get("surface_forms", []),
                        "concept_type": concept_data.get("concept_type") or "UNKNOWN",
                        "segment_id": concept_data.get("segment_id", ""),
                        "topic_id": concept_data.get("topic_id", "")
                    }

            # =================================================================
            # Phase 2.9: Extraction SEGMENT-LEVEL avec catalogue hybride
            # =================================================================

            total_written = 0
            total_skipped = 0
            total_unresolved = 0
            segment_stats = []

            # Vérifier si on a des segments avec concepts
            if state.segments_with_concepts:
                logger.info(
                    f"[SUPERVISOR] EXTRACT_RELATIONS: Phase 2.9 SEGMENT-LEVEL mode - "
                    f"{len(state.segments_with_concepts)} segments"
                )

                from knowbase.relations.catalogue_builder import (
                    build_hybrid_catalogue,
                    CatalogueConfig
                )

                config = CatalogueConfig(
                    top_k_global=15,
                    hub_min_degree=3,
                    hub_limit=10,
                    adjacent_limit=10,
                    max_catalogue_size=60
                )

                # Traiter chaque segment
                for segment_id, segment in state.segments_with_concepts.items():
                    try:
                        # Récupérer texte et local_concept_ids
                        if hasattr(segment, 'text'):
                            segment_text = segment.text
                            local_ids = segment.local_concept_ids
                            topic_id = segment.topic_id
                        else:
                            segment_text = segment.get("text", "")
                            local_ids = segment.get("local_concept_ids", [])
                            topic_id = segment.get("topic_id", "")

                        # DEBUG Phase 2.9.1: Tracer les segments et leur contenu
                        logger.info(
                            f"[SUPERVISOR] 🔍 DEBUG Segment {segment_id}: "
                            f"text_len={len(segment_text) if segment_text else 0}, "
                            f"local_concepts={len(local_ids) if local_ids else 0}"
                        )

                        if not segment_text or not local_ids:
                            logger.warning(
                                f"[SUPERVISOR] ⚠️ Segment {segment_id}: SKIPPED - "
                                f"text_empty={not segment_text}, concepts_empty={not local_ids}"
                            )
                            continue

                        # Construire catalogue hybride pour ce segment
                        catalogue = build_hybrid_catalogue(
                            segment_id=segment_id,
                            segment_text=segment_text,
                            local_concept_ids=local_ids,
                            all_promoted=list(promoted_by_id.values()),
                            neo4j_client=neo4j_client,
                            tenant_id=state.tenant_id,
                            topic_id=topic_id,
                            config=config
                        )

                        logger.debug(
                            f"[SUPERVISOR] Segment {segment_id}: catalogue {catalogue.stats['total']} concepts "
                            f"(local={catalogue.stats['local']}, global={catalogue.stats['global_top_k']}, "
                            f"hubs={catalogue.stats['hubs']})"
                        )

                        # Extraction ID-First avec ce catalogue
                        concepts_for_segment = [
                            promoted_by_id[cid]
                            for cid in catalogue.index_to_concept.keys()
                            if cid.startswith("c") and catalogue.index_to_concept[cid]["canonical_id"] in promoted_by_id
                        ]

                        # Reconstruire la liste depuis index_to_concept
                        concepts_for_segment = []
                        for idx, concept_info in catalogue.index_to_concept.items():
                            cid = concept_info["canonical_id"]
                            if cid in promoted_by_id:
                                concepts_for_segment.append(promoted_by_id[cid])

                        if not concepts_for_segment:
                            logger.debug(f"[SUPERVISOR] Segment {segment_id}: no valid concepts")
                            continue

                        # Extraction relations pour ce segment
                        extraction_result = self.llm_relation_extractor.extract_relations_id_first(
                            concepts=concepts_for_segment,
                            full_text=segment_text,
                            document_id=state.document_id,
                            chunk_id=f"{state.document_id}_{segment_id}"
                        )

                        # Écrire RawAssertions
                        segment_written = 0
                        segment_skipped = 0

                        for rel in extraction_result.relations:
                            try:
                                result_id = self.raw_assertion_writer.write_assertion(
                                    subject_concept_id=rel.subject_concept_id,
                                    object_concept_id=rel.object_concept_id,
                                    predicate_raw=rel.predicate_raw,
                                    evidence_text=rel.evidence,
                                    source_doc_id=state.document_id,
                                    source_chunk_id=f"{state.document_id}_{segment_id}",
                                    confidence=rel.confidence,
                                    source_language="multi",
                                    subject_surface_form=rel.subject_surface_form,
                                    object_surface_form=rel.object_surface_form,
                                    flags=rel.flags
                                )

                                if result_id:
                                    segment_written += 1
                                else:
                                    segment_skipped += 1
                            except Exception as e:
                                logger.debug(f"[SUPERVISOR] Error writing assertion: {e}")
                                segment_skipped += 1

                        # Écrire UnresolvedMentions
                        segment_unresolved = 0
                        if extraction_result.unresolved_mentions:
                            segment_unresolved = self.unresolved_mention_writer.write_batch(
                                mentions=extraction_result.unresolved_mentions,
                                source_doc_id=state.document_id,
                                source_chunk_id=f"{state.document_id}_{segment_id}"
                            )

                        total_written += segment_written
                        total_skipped += segment_skipped
                        total_unresolved += segment_unresolved

                        segment_stats.append({
                            "segment_id": segment_id,
                            "catalogue_size": catalogue.stats["total"],
                            "relations_written": segment_written,
                            "unresolved": segment_unresolved
                        })

                        logger.debug(
                            f"[SUPERVISOR] Segment {segment_id}: {segment_written} relations written"
                        )

                    except Exception as e:
                        logger.warning(f"[SUPERVISOR] Segment {segment_id} failed: {e}")
                        continue

            else:
                # Fallback: Mode document-level (Phase 2.8 legacy)
                logger.info(
                    "[SUPERVISOR] EXTRACT_RELATIONS: No segments_with_concepts, "
                    "falling back to document-level extraction"
                )

                full_text = state.full_text or ""
                if full_text and promoted_by_id:
                    extraction_result = self.llm_relation_extractor.extract_relations_id_first(
                        concepts=list(promoted_by_id.values()),
                        full_text=full_text,
                        document_id=state.document_id,
                        chunk_id=state.chunk_ids[0] if state.chunk_ids else "chunk_0"
                    )

                    for rel in extraction_result.relations:
                        try:
                            result_id = self.raw_assertion_writer.write_assertion(
                                subject_concept_id=rel.subject_concept_id,
                                object_concept_id=rel.object_concept_id,
                                predicate_raw=rel.predicate_raw,
                                evidence_text=rel.evidence,
                                source_doc_id=state.document_id,
                                source_chunk_id=state.chunk_ids[0] if state.chunk_ids else "chunk_0",
                                confidence=rel.confidence,
                                source_language="multi",
                                subject_surface_form=rel.subject_surface_form,
                                object_surface_form=rel.object_surface_form,
                                flags=rel.flags
                            )
                            if result_id:
                                total_written += 1
                            else:
                                total_skipped += 1
                        except:
                            total_skipped += 1

                    if extraction_result.unresolved_mentions:
                        total_unresolved = self.unresolved_mention_writer.write_batch(
                            mentions=extraction_result.unresolved_mentions,
                            source_doc_id=state.document_id,
                            source_chunk_id=state.chunk_ids[0] if state.chunk_ids else "chunk_0"
                        )

            # Stats finales
            writer_stats = self.raw_assertion_writer.get_stats()
            mention_stats = self.unresolved_mention_writer.get_stats()

            logger.info(
                f"[SUPERVISOR] EXTRACT_RELATIONS: ✅ Phase 2.9 Segment-Level - "
                f"Written {total_written} RawAssertions from {len(segment_stats)} segments, "
                f"skipped {total_skipped}, unresolved {total_unresolved}"
            )

            # Stocker stats dans state
            state.relation_extraction_stats = {
                "total_written": total_written,
                "total_skipped": total_skipped,
                "duplicates": writer_stats.get("skipped_duplicate", 0),
                "unresolved_written": total_unresolved,
                "segments_processed": len(segment_stats),
                "segment_stats": segment_stats,
                "phase": "2.9_segment_level"
            }

            elapsed = time.time() - step_start
            logger.info(f"[SUPERVISOR] ⏱️ EXTRACT_RELATIONS (Phase 2.9): COMPLETE in {elapsed:.1f}s")
            return FSMState.FINALIZE

        elif fsm_state == FSMState.FINALIZE:
            step_start = time.time()

            # NOTE: Chunking + upload Qdrant désormais fait dans OSMOSE Agentique (osmose_agentique.py:420-450)
            # Évite duplication et gain de 60-70s de processing
            logger.info("[SUPERVISOR] ⏱️ FINALIZE: Chunking already done by OSMOSE Agentique, skipping")

            elapsed = time.time() - step_start
            logger.info(f"[SUPERVISOR] ⏱️ FINALIZE: COMPLETE in {elapsed:.1f}s")
            logger.debug("[SUPERVISOR] FINALIZE: Computing final metrics")
            return FSMState.DONE

        elif fsm_state == FSMState.ERROR:
            # Gestion erreur
            logger.error(f"[SUPERVISOR] ERROR state reached. Errors: {state.errors}")
            return FSMState.DONE

        else:
            logger.error(f"[SUPERVISOR] Unknown FSM state: {fsm_state}")
            return FSMState.ERROR
