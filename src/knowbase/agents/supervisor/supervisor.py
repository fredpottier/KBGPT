"""
🤖 OSMOSE Agentique - Supervisor Agent

FSM Master pour orchestration des agents spécialisés.
"""

from typing import Dict, Any, Optional, List, Tuple
from enum import Enum
import logging
import time
import asyncio
import os

from ..base import BaseAgent, AgentRole, AgentState, ToolOutput
from ..extractor import ExtractorOrchestrator
from ..miner import PatternMiner
from ..gatekeeper import GatekeeperDelegate
from ..budget import BudgetManager
from ..dispatcher import LLMDispatcher
from knowbase.common.token_tracker import get_token_tracker

logger = logging.getLogger(__name__)


class FSMState(str, Enum):
    """États de la FSM du Supervisor."""
    INIT = "init"
    BUDGET_CHECK = "budget_check"
    SEGMENT = "segment"
    EXTRACT = "extract"
    CLASSIFY_CONCEPTS = "classify_concepts"  # Phase 2.9.2: Classification domain-agnostic
    MINE_PATTERNS = "mine_patterns"
    GATE_CHECK = "gate_check"
    EXTRACT_RELATIONS = "extract_relations"  # Phase 2 OSMOSE
    EXTRACT_DOC_LEVEL = "extract_doc_level"  # Phase 2.9.4: Cross-segment relations (Bucket 3)
    FINALIZE = "finalize"
    ERROR = "error"
    DONE = "done"


class SupervisorAgent(BaseAgent):
    """
    Supervisor Agent - FSM Master.

    Pipeline FSM:
    INIT → BUDGET_CHECK → SEGMENT → EXTRACT → CLASSIFY_CONCEPTS → MINE_PATTERNS → GATE_CHECK → EXTRACT_RELATIONS → EXTRACT_DOC_LEVEL → FINALIZE → DONE

    Transitions conditionnelles:
    - BUDGET_CHECK fail → ERROR
    - GATE_CHECK fail → EXTRACT (retry avec BIG model)
    - Any step timeout → ERROR
    - Max steps reached → ERROR

    Phase 2.9.2: CLASSIFY_CONCEPTS classe chaque concept en:
    - entity/abstract/rule_like (keepable) → participent aux relations factuelles
    - structural/generic/fragment (non-keepable) → exclus des relations factuelles

    Phase 2.9.4: EXTRACT_DOC_LEVEL cible uniquement les concepts Bucket 3:
    - Haute qualité (>= 0.9)
    - Types: entity, role, standard
    - Isolés après segment-level
    - Extrait relations cross-segment uniquement

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

        # Phase 2.9.2: Classifier pour concept_kind
        self.concept_classifier = None  # Lazy load

        # Phase 2.9.3: Parallélisation EXTRACT_RELATIONS
        self.max_parallel_relations = int(os.getenv("MAX_PARALLEL_SEGMENTS", "30"))
        max_rpm = int(os.getenv("OPENAI_MAX_RPM", "500"))
        max_concurrent_llm = min(max_rpm // 3, self.max_parallel_relations)
        self.relations_semaphore = asyncio.Semaphore(max_concurrent_llm)

        # Phase 2.9.4: Extracteur doc-level pour Bucket 3
        self.doc_level_extractor = None  # Lazy load

        # FSM transitions (état actuel → états suivants possibles)
        self.fsm_transitions: Dict[FSMState, List[FSMState]] = {
            FSMState.INIT: [FSMState.BUDGET_CHECK],
            FSMState.BUDGET_CHECK: [FSMState.SEGMENT, FSMState.ERROR],
            FSMState.SEGMENT: [FSMState.EXTRACT, FSMState.ERROR],
            FSMState.EXTRACT: [FSMState.CLASSIFY_CONCEPTS, FSMState.ERROR],
            FSMState.CLASSIFY_CONCEPTS: [FSMState.MINE_PATTERNS, FSMState.ERROR],  # Phase 2.9.2
            FSMState.MINE_PATTERNS: [FSMState.GATE_CHECK, FSMState.ERROR],
            FSMState.GATE_CHECK: [FSMState.EXTRACT_RELATIONS, FSMState.EXTRACT, FSMState.ERROR],  # Retry si fail
            FSMState.EXTRACT_RELATIONS: [FSMState.EXTRACT_DOC_LEVEL, FSMState.ERROR],  # Phase 2.9.4
            FSMState.EXTRACT_DOC_LEVEL: [FSMState.FINALIZE, FSMState.ERROR],  # Phase 2.9.4
            FSMState.FINALIZE: [FSMState.DONE, FSMState.ERROR],
            FSMState.ERROR: [FSMState.DONE],  # Terminaison forcée
            FSMState.DONE: []  # État terminal
        }

        logger.info("[SUPERVISOR] Initialized with FSM and 5 specialist agents")

    def _register_tools(self):
        """Le Supervisor n'a pas de tools directs (coordonne les autres agents)."""
        pass

    async def _process_single_segment_relations(
        self,
        segment_id: str,
        segment_data: Any,
        unique_promoted: List[Dict[str, Any]],
        promoted_by_id: Dict[str, Any],
        state: AgentState,
        neo4j_client: Any,
        config: Any
    ) -> Optional[Dict[str, Any]]:
        """
        Traite UN segment pour extraction de relations (Phase 2.9.3 - Parallèle).

        Args:
            segment_id: ID du segment
            segment_data: Données du segment (SegmentWithConcepts)
            unique_promoted: Liste dédupliquée des concepts promus
            promoted_by_id: Dict des concepts par ID
            state: État global
            neo4j_client: Client Neo4j
            config: CatalogueConfig

        Returns:
            Dict avec stats du segment ou None si échec
        """
        from knowbase.relations.catalogue_builder import build_hybrid_catalogue

        try:
            # Récupérer texte et local_concept_ids
            if hasattr(segment_data, 'text'):
                segment_text = segment_data.text
                local_ids = segment_data.local_concept_ids
                topic_id = segment_data.topic_id
            else:
                segment_text = segment_data.get("text", "")
                local_ids = segment_data.get("local_concept_ids", [])
                topic_id = segment_data.get("topic_id", "")

            if not segment_text or not local_ids:
                return None

            # Construire catalogue hybride pour ce segment
            catalogue = build_hybrid_catalogue(
                segment_id=segment_id,
                segment_text=segment_text,
                local_concept_ids=local_ids,
                all_promoted=unique_promoted,
                neo4j_client=neo4j_client,
                tenant_id=state.tenant_id,
                topic_id=topic_id,
                config=config
            )

            if catalogue.stats.get('total', 0) == 0:
                return None

            # Reconstruire la liste depuis index_to_concept
            concepts_for_segment = []
            for idx, concept_info in catalogue.index_to_concept.items():
                cid = concept_info["canonical_id"]
                if cid in promoted_by_id:
                    concepts_for_segment.append(promoted_by_id[cid])

            if not concepts_for_segment:
                return None

            # Extraction relations avec rate limiting (via semaphore)
            async with self.relations_semaphore:
                # Wrapper synchrone → async
                extraction_result = await asyncio.to_thread(
                    self.llm_relation_extractor.extract_relations_id_first,
                    concepts=concepts_for_segment,
                    full_text=segment_text,
                    document_id=state.document_id,
                    chunk_id=f"{state.document_id}_{segment_id}"
                )

            # Écrire RawAssertions (rapide, pas besoin de paralléliser)
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
                except Exception:
                    segment_skipped += 1

            # Écrire UnresolvedMentions
            segment_unresolved = 0
            if extraction_result.unresolved_mentions:
                segment_unresolved = self.unresolved_mention_writer.write_batch(
                    mentions=extraction_result.unresolved_mentions,
                    source_doc_id=state.document_id,
                    source_chunk_id=f"{state.document_id}_{segment_id}"
                )

            logger.info(
                f"[SUPERVISOR] Segment {segment_id}: {segment_written} relations, "
                f"{segment_unresolved} unresolved"
            )

            return {
                "segment_id": segment_id,
                "catalogue_size": catalogue.stats["total"],
                "relations_written": segment_written,
                "relations_skipped": segment_skipped,
                "unresolved": segment_unresolved
            }

        except Exception as e:
            logger.warning(f"[SUPERVISOR] Segment {segment_id} failed: {e}")
            return None

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
        print(f"[DEBUG SUPERVISOR] >>> ENTRY execute() for document {state.document_id}")

        # DEBUG: Vérifier réception des segments
        logger.info(
            f"[SUPERVISOR] 🔍 DEBUG: Received {len(state.segments)} segments from osmose_agentique"
        )
        print(f"[DEBUG SUPERVISOR] Received {len(state.segments)} segments")
        if state.segments:
            logger.info(
                f"[SUPERVISOR] 🔍 DEBUG: First segment keys: {list(state.segments[0].keys())}"
            )
        else:
            logger.error("[SUPERVISOR] 🔍 DEBUG: WARNING - No segments received!")
            print("[DEBUG SUPERVISOR] WARNING - No segments received!")

        # Initialiser FSM
        current_fsm_state = FSMState.INIT
        state.current_step = current_fsm_state.value
        print(f"[DEBUG SUPERVISOR] FSM initialized, starting loop...")

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
            print(f"[DEBUG SUPERVISOR] Step {state.steps_count}: FSM state = {current_fsm_state.value}")

            # Exécuter action selon état FSM
            try:
                print(f"[DEBUG SUPERVISOR] >>> Executing FSM step: {current_fsm_state.value}...")
                next_state = await self._execute_fsm_step(current_fsm_state, state)
                print(f"[DEBUG SUPERVISOR] <<< FSM step {current_fsm_state.value} done -> next: {next_state.value}")

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

        # Phase 2.9.3: Afficher résumé des appels LLM et coûts
        try:
            token_tracker = get_token_tracker()
            summary = token_tracker.get_session_summary()
            print(summary)
            logger.info(f"[SUPERVISOR] LLM cost summary:\n{summary}")
        except Exception as e:
            logger.warning(f"[SUPERVISOR] Could not generate LLM cost summary: {e}")

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
            print("[DEBUG SUPERVISOR] FSM INIT -> BUDGET_CHECK")
            # Phase 2.9.3: Démarrer session token tracking
            token_tracker = get_token_tracker()
            token_tracker.start_session()
            return FSMState.BUDGET_CHECK

        elif fsm_state == FSMState.BUDGET_CHECK:
            # Vérifier budget disponible
            print("[DEBUG SUPERVISOR] FSM BUDGET_CHECK: checking budget...")
            budget_ok = await self.budget_manager.check_budget(state)
            print(f"[DEBUG SUPERVISOR] FSM BUDGET_CHECK: result={budget_ok}")
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
            print(f"[DEBUG SUPERVISOR] FSM SEGMENT: {len(state.segments)} segments present")

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
            print("[DEBUG SUPERVISOR] FSM EXTRACT: >>> Calling ExtractorOrchestrator...")
            state = await self.extractor.execute(state)
            elapsed = time.time() - step_start
            logger.info(f"[SUPERVISOR] ⏱️ EXTRACT: COMPLETE in {elapsed:.1f}s")
            print(f"[DEBUG SUPERVISOR] FSM EXTRACT: <<< COMPLETE in {elapsed:.1f}s, candidates={len(state.candidates)}")
            return FSMState.CLASSIFY_CONCEPTS  # Phase 2.9.2: Vers classification

        elif fsm_state == FSMState.CLASSIFY_CONCEPTS:
            # =================================================================
            # Phase 2.9.2: Classification domain-agnostic des concepts
            # =================================================================
            logger.info(f"[SUPERVISOR] ⏱️ CLASSIFY_CONCEPTS: START - {len(state.candidates)} candidates")
            print(f"[DEBUG SUPERVISOR] FSM CLASSIFY_CONCEPTS: >>> Starting with {len(state.candidates)} candidates...")

            if not state.candidates:
                logger.warning("[SUPERVISOR] CLASSIFY_CONCEPTS: No candidates to classify")
                elapsed = time.time() - step_start
                return FSMState.MINE_PATTERNS

            # Lazy load du classifier
            if self.concept_classifier is None:
                from ..classifier import ConceptKindClassifier
                from knowbase.common.llm_router import get_llm_router

                self.concept_classifier = ConceptKindClassifier(
                    llm_router=get_llm_router(),
                    model="gpt-4o-mini",
                    batch_size=30,
                    use_heuristics=True
                )
                logger.info("[SUPERVISOR] CLASSIFY_CONCEPTS: Classifier initialized")

            # Classifier les concepts
            from ..classifier import enrich_concepts_with_kind, ConceptForClassification
            concepts_for_classification = [
                ConceptForClassification(
                    id=c.get("concept_id", f"c_{i}"),
                    label=c.get("name", ""),
                    context=c.get("definition")
                )
                for i, c in enumerate(state.candidates)
            ]
            classification_result = await self.concept_classifier.classify_batch_async(
                concepts_for_classification
            )

            # Enrichir les concepts avec leur classification
            state.candidates = enrich_concepts_with_kind(state.candidates, classification_result)

            # Stats
            keepable = classification_result.keepable_count
            non_keepable = classification_result.non_keepable_count
            elapsed = time.time() - step_start

            logger.info(
                f"[SUPERVISOR] ⏱️ CLASSIFY_CONCEPTS: COMPLETE in {elapsed:.1f}s - "
                f"{keepable} keepable, {non_keepable} filtered (structural/generic/fragment)"
            )
            print(
                f"[DEBUG SUPERVISOR] FSM CLASSIFY_CONCEPTS: <<< COMPLETE in {elapsed:.1f}s, "
                f"keepable={keepable}, filtered={non_keepable}"
            )

            return FSMState.MINE_PATTERNS

        elif fsm_state == FSMState.MINE_PATTERNS:
            # Mining patterns cross-segments
            logger.info("[SUPERVISOR] ⏱️ MINE_PATTERNS: START - Calling PatternMiner")
            print("[DEBUG SUPERVISOR] FSM MINE_PATTERNS: >>> Calling PatternMiner...")
            state = await self.miner.execute(state)
            elapsed = time.time() - step_start
            logger.info(f"[SUPERVISOR] ⏱️ MINE_PATTERNS: COMPLETE in {elapsed:.1f}s")
            print(f"[DEBUG SUPERVISOR] FSM MINE_PATTERNS: <<< COMPLETE in {elapsed:.1f}s")
            return FSMState.GATE_CHECK

        elif fsm_state == FSMState.GATE_CHECK:
            # Quality gate check + promotion vers Neo4j (gérée par GatekeeperDelegate)
            logger.info("[SUPERVISOR] ⏱️ GATE_CHECK: START - Calling GatekeeperDelegate")
            print("[DEBUG SUPERVISOR] FSM GATE_CHECK: >>> Calling GatekeeperDelegate...")
            state = await self.gatekeeper.execute(state)
            elapsed = time.time() - step_start
            print(f"[DEBUG SUPERVISOR] FSM GATE_CHECK: <<< COMPLETE in {elapsed:.1f}s, promoted={len(state.promoted)}")

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
            print(f"[DEBUG SUPERVISOR] FSM EXTRACT_RELATIONS: >>> Starting...")
            logger.info(
                f"[SUPERVISOR] ⏱️ EXTRACT_RELATIONS (Phase 2.9 Segment-Level): START - "
                f"promoted={len(state.promoted) if state.promoted else 0}, "
                f"segments_with_concepts={len(state.segments_with_concepts)}"
            )
            print(f"[DEBUG SUPERVISOR] FSM EXTRACT_RELATIONS: promoted={len(state.promoted) if state.promoted else 0}, segments_with_concepts={len(state.segments_with_concepts)}")

            # Skip si aucun concept promu
            if not state.promoted or len(state.promoted) == 0:
                logger.warning("[SUPERVISOR] EXTRACT_RELATIONS: No promoted concepts, skipping")
                return FSMState.EXTRACT_DOC_LEVEL

            print(f"[DEBUG SUPERVISOR] EXTRACT_RELATIONS: passed promoted check, getting neo4j_client...")

            # Préparer connexion Neo4j
            from knowbase.common.clients.neo4j_client import get_neo4j_client
            neo4j_client = get_neo4j_client()
            print(f"[DEBUG SUPERVISOR] EXTRACT_RELATIONS: neo4j_client obtained")

            # Phase 2.9: Lazy load composants
            if self.llm_relation_extractor is None:
                print(f"[DEBUG SUPERVISOR] EXTRACT_RELATIONS: initializing Phase 2.9 components...")
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
                print(f"[DEBUG SUPERVISOR] EXTRACT_RELATIONS: Phase 2.9 components initialized")

            # Préparer promoted concepts comme dict pour lookup rapide
            print(f"[DEBUG SUPERVISOR] EXTRACT_RELATIONS: preparing promoted_by_id dict...")
            promoted_by_id = {}
            for concept_data in state.promoted:
                canonical_id = concept_data.get("canonical_id") or concept_data.get("concept_id")
                original_concept_id = concept_data.get("concept_id", "")
                if canonical_id:
                    concept_entry = {
                        "canonical_id": canonical_id,
                        "concept_id": original_concept_id,  # Phase 2.9.1: Préserver aussi concept_id original
                        "canonical_name": concept_data.get("canonical_name", ""),
                        "surface_forms": concept_data.get("surface_forms", []),
                        "concept_type": concept_data.get("concept_type") or "UNKNOWN",
                        "segment_id": concept_data.get("segment_id", ""),
                        "topic_id": concept_data.get("topic_id", "")
                    }
                    promoted_by_id[canonical_id] = concept_entry
                    # Phase 2.9.1: Indexer AUSSI par concept_id original pour matching
                    if original_concept_id and original_concept_id != canonical_id:
                        promoted_by_id[original_concept_id] = concept_entry

            # =================================================================
            # Phase 2.9: Extraction SEGMENT-LEVEL avec catalogue hybride
            # =================================================================
            # Phase 2.9.1: Dédupliquer values car promoted_by_id a 2 clés par concept
            unique_promoted = list({id(v): v for v in promoted_by_id.values()}.values())
            print(f"[DEBUG SUPERVISOR] EXTRACT_RELATIONS: promoted_by_id has {len(promoted_by_id)} entries, {len(unique_promoted)} unique concepts")

            total_written = 0
            total_skipped = 0
            total_unresolved = 0
            segment_stats = []

            # Vérifier si on a des segments avec concepts
            print(f"[DEBUG SUPERVISOR] EXTRACT_RELATIONS: checking segments_with_concepts (len={len(state.segments_with_concepts) if state.segments_with_concepts else 0})")
            if state.segments_with_concepts:
                print(f"[DEBUG SUPERVISOR] EXTRACT_RELATIONS: entering SEGMENT-LEVEL mode")
                logger.info(
                    f"[SUPERVISOR] EXTRACT_RELATIONS: Phase 2.9 SEGMENT-LEVEL mode - "
                    f"{len(state.segments_with_concepts)} segments"
                )

                print(f"[DEBUG SUPERVISOR] EXTRACT_RELATIONS: importing catalogue_builder...")
                from knowbase.relations.catalogue_builder import (
                    build_hybrid_catalogue,
                    CatalogueConfig
                )
                print(f"[DEBUG SUPERVISOR] EXTRACT_RELATIONS: catalogue_builder imported")

                config = CatalogueConfig(
                    top_k_global=15,
                    hub_min_degree=3,
                    hub_limit=10,
                    adjacent_limit=10,
                    max_catalogue_size=60
                )

                # =================================================================
                # Phase 2.9.3: Traitement PARALLÈLE des segments (comme EXTRACT)
                # =================================================================
                segments_list = list(state.segments_with_concepts.items())
                num_segments = len(segments_list)
                num_batches = (num_segments + self.max_parallel_relations - 1) // self.max_parallel_relations

                logger.info(
                    f"[SUPERVISOR] EXTRACT_RELATIONS: PARALLEL mode - "
                    f"{num_segments} segments in {num_batches} batches "
                    f"(max {self.max_parallel_relations} parallel)"
                )
                print(f"[DEBUG SUPERVISOR] EXTRACT_RELATIONS: {num_segments} segments in {num_batches} batches")

                all_results = []

                for batch_idx in range(num_batches):
                    start_idx = batch_idx * self.max_parallel_relations
                    end_idx = min(start_idx + self.max_parallel_relations, num_segments)
                    batch_segments = segments_list[start_idx:end_idx]

                    logger.info(
                        f"[SUPERVISOR] 📦 Processing batch {batch_idx + 1}/{num_batches} "
                        f"(segments {start_idx + 1}-{end_idx})"
                    )
                    print(f"[DEBUG SUPERVISOR] EXTRACT_RELATIONS: batch {batch_idx + 1}/{num_batches} ({len(batch_segments)} segments)")

                    # Créer tâches pour ce batch
                    tasks = [
                        self._process_single_segment_relations(
                            segment_id=seg_id,
                            segment_data=seg_data,
                            unique_promoted=unique_promoted,
                            promoted_by_id=promoted_by_id,
                            state=state,
                            neo4j_client=neo4j_client,
                            config=config
                        )
                        for seg_id, seg_data in batch_segments
                    ]

                    # Exécuter batch en parallèle
                    batch_results = await asyncio.gather(*tasks, return_exceptions=True)

                    # Filtrer erreurs
                    for result in batch_results:
                        if isinstance(result, Exception):
                            logger.error(f"[SUPERVISOR] ❌ Segment processing failed: {result}")
                        elif result is not None:
                            all_results.append(result)

                    logger.info(
                        f"[SUPERVISOR] ✅ Batch {batch_idx + 1}/{num_batches} completed: "
                        f"{len([r for r in batch_results if r is not None and not isinstance(r, Exception)])} segments processed"
                    )

                # Agréger résultats
                for result in all_results:
                    total_written += result.get("relations_written", 0)
                    total_skipped += result.get("relations_skipped", 0)
                    total_unresolved += result.get("unresolved", 0)
                    segment_stats.append(result)

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
            return FSMState.EXTRACT_DOC_LEVEL

        elif fsm_state == FSMState.EXTRACT_DOC_LEVEL:
            # Phase 2.9.4: Extraction relations cross-segment pour concepts Bucket 3
            step_start = time.time()
            logger.info("[SUPERVISOR] EXTRACT_DOC_LEVEL: Starting cross-segment relation extraction")

            # Lazy load doc-level extractor
            if self.doc_level_extractor is None:
                from knowbase.relations.doc_level_extractor import DocLevelRelationExtractor
                from knowbase.common.llm_router import LLMRouter

                llm_router = LLMRouter()
                self.doc_level_extractor = DocLevelRelationExtractor(
                    llm_router=llm_router,
                    model="gpt-4o-mini",
                    min_confidence=0.85
                )

            # Collecter les relations segment-level déjà extraites
            existing_relations = state.extraction_results.get("segment_level_relations", [])

            # Récupérer texte document complet (nécessaire pour identify_bucket3_concepts)
            document_text = state.input_text or ""
            if not document_text:
                # Fallback: concaténer segments
                for seg in state.segments:
                    if isinstance(seg, dict):
                        document_text += seg.get("text", "") + "\n\n"
                    else:
                        document_text += getattr(seg, "text", "") + "\n\n"

            # Identifier concepts Bucket 3 (retourne tuple avec existing_rel_strings formatés)
            bucket3_concepts, existing_rel_strings = self.doc_level_extractor.identify_bucket3_concepts(
                all_concepts=state.promoted,
                existing_relations=existing_relations,
                quality_threshold=0.9,
                allowed_types=["entity", "role", "standard"],
                document_text=document_text
            )

            if not bucket3_concepts:
                logger.info("[SUPERVISOR] EXTRACT_DOC_LEVEL: No Bucket 3 concepts found, skipping")
                elapsed = time.time() - step_start
                logger.info(f"[SUPERVISOR] ⏱️ EXTRACT_DOC_LEVEL: SKIPPED in {elapsed:.1f}s")
                return FSMState.FINALIZE

            # Extraire relations doc-level (avec existing_rel_strings pour anti-doublon)
            doc_result = self.doc_level_extractor.extract_doc_level_relations(
                bucket3_concepts=bucket3_concepts,
                document_text=document_text,
                document_id=state.document_id,
                existing_relations=existing_rel_strings
            )

            # Écrire les relations extraites
            if doc_result.relations and self.raw_assertion_writer:
                doc_level_written = 0
                for rel in doc_result.relations:
                    try:
                        result_id = self.raw_assertion_writer.write_assertion(
                            subject_concept_id=rel.subject_concept_id,
                            object_concept_id=rel.object_concept_id,
                            predicate_raw=rel.predicate,
                            evidence_text=rel.evidence,
                            source_doc_id=state.document_id,
                            source_chunk_id=f"{state.document_id}_doc_level",
                            confidence=rel.confidence,
                            source_language="multi",
                            subject_surface_form=rel.subject_label,
                            object_surface_form=rel.object_label,
                            flags=["doc_level", "cross_segment"]
                        )
                        if result_id:
                            doc_level_written += 1
                    except Exception as e:
                        logger.warning(f"[SUPERVISOR] EXTRACT_DOC_LEVEL: Failed to write relation: {e}")

                logger.info(
                    f"[SUPERVISOR] EXTRACT_DOC_LEVEL: Wrote {doc_level_written} cross-segment relations"
                )

            # Stocker stats
            state.extraction_results["doc_level"] = {
                "concepts_processed": doc_result.concepts_processed,
                "concepts_connected": doc_result.concepts_connected,
                "relations_extracted": len(doc_result.relations)
            }

            elapsed = time.time() - step_start
            logger.info(
                f"[SUPERVISOR] ⏱️ EXTRACT_DOC_LEVEL (Phase 2.9.4): COMPLETE in {elapsed:.1f}s "
                f"({doc_result.concepts_connected}/{doc_result.concepts_processed} concepts connected)"
            )
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
