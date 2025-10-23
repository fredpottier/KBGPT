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
    PROMOTE = "promote"
    EXTRACT_RELATIONS = "extract_relations"  # Phase 2 OSMOSE
    FINALIZE = "finalize"
    ERROR = "error"
    DONE = "done"


class SupervisorAgent(BaseAgent):
    """
    Supervisor Agent - FSM Master.

    Pipeline FSM:
    INIT → BUDGET_CHECK → SEGMENT → EXTRACT → MINE_PATTERNS → GATE_CHECK → PROMOTE → EXTRACT_RELATIONS → FINALIZE → DONE

    Transitions conditionnelles:
    - BUDGET_CHECK fail → ERROR
    - GATE_CHECK fail → EXTRACT (retry avec BIG model)
    - Any step timeout → ERROR
    - Max steps reached → ERROR

    Phase 2 OSMOSE: EXTRACT_RELATIONS ajoutée après PROMOTE
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

        # Phase 2 OSMOSE: Composants extraction relations
        self.relation_extraction_engine = None  # Lazy load
        self.relation_writer = None  # Lazy load

        # FSM transitions (état actuel → états suivants possibles)
        self.fsm_transitions: Dict[FSMState, List[FSMState]] = {
            FSMState.INIT: [FSMState.BUDGET_CHECK],
            FSMState.BUDGET_CHECK: [FSMState.SEGMENT, FSMState.ERROR],
            FSMState.SEGMENT: [FSMState.EXTRACT, FSMState.ERROR],
            FSMState.EXTRACT: [FSMState.MINE_PATTERNS, FSMState.ERROR],
            FSMState.MINE_PATTERNS: [FSMState.GATE_CHECK, FSMState.ERROR],
            FSMState.GATE_CHECK: [FSMState.PROMOTE, FSMState.EXTRACT, FSMState.ERROR],  # Retry si fail
            FSMState.PROMOTE: [FSMState.EXTRACT_RELATIONS, FSMState.ERROR],  # Phase 2
            FSMState.EXTRACT_RELATIONS: [FSMState.FINALIZE, FSMState.ERROR],  # Phase 2
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
        if fsm_state == FSMState.INIT:
            logger.debug("[SUPERVISOR] INIT: Starting pipeline")
            return FSMState.BUDGET_CHECK

        elif fsm_state == FSMState.BUDGET_CHECK:
            # Vérifier budget disponible
            budget_ok = await self.budget_manager.check_budget(state)
            if budget_ok:
                logger.debug("[SUPERVISOR] BUDGET_CHECK: OK, proceeding to SEGMENT")
                return FSMState.SEGMENT
            else:
                logger.warning("[SUPERVISOR] BUDGET_CHECK: Budget insufficient")
                state.errors.append("Budget insufficient")
                return FSMState.ERROR

        elif fsm_state == FSMState.SEGMENT:
            # Segmentation (utilise SemanticPipeline existant)
            logger.debug("[SUPERVISOR] SEGMENT: Calling TopicSegmenter")

            # Si segments déjà présents (passés par osmose_agentique), les garder
            if len(state.segments) > 0:
                logger.info(f"[SUPERVISOR] SEGMENT: Segments already present ({len(state.segments)}), skipping segmentation")
                return FSMState.EXTRACT

            # TODO: Intégrer TopicSegmenter si segments vides
            logger.warning("[SUPERVISOR] SEGMENT: No segments found, should call TopicSegmenter here (TODO)")
            state.segments = []  # Placeholder pour éviter erreur
            return FSMState.EXTRACT

        elif fsm_state == FSMState.EXTRACT:
            # Extraction concepts via Extractor Orchestrator
            logger.debug("[SUPERVISOR] EXTRACT: Calling ExtractorOrchestrator")
            state = await self.extractor.execute(state)
            return FSMState.MINE_PATTERNS

        elif fsm_state == FSMState.MINE_PATTERNS:
            # Mining patterns cross-segments
            logger.debug("[SUPERVISOR] MINE_PATTERNS: Calling PatternMiner")
            state = await self.miner.execute(state)
            return FSMState.GATE_CHECK

        elif fsm_state == FSMState.GATE_CHECK:
            # Quality gate check
            logger.debug("[SUPERVISOR] GATE_CHECK: Calling GatekeeperDelegate")
            state = await self.gatekeeper.execute(state)

            # Si qualité insuffisante et budget permet, retry avec BIG model
            if len(state.promoted) == 0 and state.budget_remaining["BIG"] > 0:
                logger.warning("[SUPERVISOR] GATE_CHECK: Quality low, retrying with BIG")
                return FSMState.EXTRACT  # Retry
            else:
                return FSMState.PROMOTE

        elif fsm_state == FSMState.PROMOTE:
            # Promotion Proto→Published
            logger.debug("[SUPERVISOR] PROMOTE: Promoting candidates")
            # TODO: Appel à Neo4j pour promotion
            return FSMState.EXTRACT_RELATIONS  # Phase 2: Transition vers extraction relations

        elif fsm_state == FSMState.EXTRACT_RELATIONS:
            # Phase 2 OSMOSE: Extraction relations entre concepts promus
            logger.info("[SUPERVISOR] EXTRACT_RELATIONS: Extracting relations between canonical concepts")

            # Skip si aucun concept promu
            if not state.promoted or len(state.promoted) == 0:
                logger.warning("[SUPERVISOR] EXTRACT_RELATIONS: No promoted concepts, skipping relation extraction")
                return FSMState.FINALIZE

            # Récupérer texte complet document
            full_text = state.full_text or ""
            if not full_text:
                logger.warning("[SUPERVISOR] EXTRACT_RELATIONS: No full_text in state, skipping")
                return FSMState.FINALIZE

            # Lazy load composants Phase 2
            if self.relation_extraction_engine is None:
                from knowbase.relations import RelationExtractionEngine, Neo4jRelationshipWriter
                self.relation_extraction_engine = RelationExtractionEngine(
                    strategy="llm_first",  # LLM-first comme demandé
                    llm_model="gpt-4o-mini",
                    min_confidence=0.60
                )
                self.relation_writer = Neo4jRelationshipWriter(
                    tenant_id=state.tenant_id
                )
                logger.info("[SUPERVISOR] EXTRACT_RELATIONS: Initialized relation extraction components")

            # Préparer concepts pour extraction
            # PROBLÈME: state.promoted ne contient pas surface_forms (schema mismatch)
            # SOLUTION: Récupérer depuis Neo4j les CanonicalConcepts avec surface_form
            from knowbase.common.clients.neo4j_client import get_neo4j_client
            neo4j_client = get_neo4j_client()

            concepts = []
            if neo4j_client and neo4j_client.is_connected():
                # Query Neo4j pour récupérer les CanonicalConcepts du document actuel
                query = """
                MATCH (c:CanonicalConcept)
                WHERE c.tenant_id = $tenant_id
                RETURN c.canonical_id AS concept_id,
                       c.canonical_name AS canonical_name,
                       c.surface_form AS surface_form,
                       c.concept_type AS concept_type
                LIMIT 1000
                """
                try:
                    with neo4j_client.driver.session(database=neo4j_client.database) as session:
                        result = session.run(query, tenant_id=state.tenant_id)
                        for record in result:
                            # Convertir surface_form (string) → surface_forms (liste)
                            surface_form = record.get("surface_form", "")
                            surface_forms = [surface_form] if surface_form else []

                            concepts.append({
                                "concept_id": record["concept_id"],
                                "canonical_name": record["canonical_name"],
                                "surface_forms": surface_forms,
                                "concept_type": record.get("concept_type", "UNKNOWN")
                            })
                    logger.info(
                        f"[SUPERVISOR] EXTRACT_RELATIONS: Retrieved {len(concepts)} concepts from Neo4j "
                        f"with surface_forms"
                    )
                except Exception as e:
                    logger.error(
                        f"[SUPERVISOR] EXTRACT_RELATIONS: Error querying Neo4j for concepts: {e}. "
                        f"Falling back to state.promoted without surface_forms"
                    )
                    # Fallback: utiliser state.promoted sans surface_forms (meilleur que rien)
                    for concept_data in state.promoted:
                        concepts.append({
                            "concept_id": concept_data.get("concept_id"),
                            "canonical_name": concept_data.get("canonical_name"),
                            "surface_forms": [],  # Vide si erreur Neo4j
                            "concept_type": concept_data.get("concept_type", "UNKNOWN")
                        })
            else:
                logger.warning(
                    "[SUPERVISOR] EXTRACT_RELATIONS: Neo4j not available, "
                    "falling back to state.promoted without surface_forms"
                )
                # Fallback: utiliser state.promoted sans surface_forms
                for concept_data in state.promoted:
                    concepts.append({
                        "concept_id": concept_data.get("concept_id"),
                        "canonical_name": concept_data.get("canonical_name"),
                        "surface_forms": [],
                        "concept_type": concept_data.get("concept_type", "UNKNOWN")
                    })

            logger.info(f"[SUPERVISOR] EXTRACT_RELATIONS: Extracting relations from {len(concepts)} canonical concepts")

            try:
                # Extraction relations
                extraction_result = self.relation_extraction_engine.extract_relations(
                    concepts=concepts,
                    full_text=full_text,
                    document_id=state.document_id,
                    document_name=state.document_name or "unknown",
                    chunk_ids=state.chunk_ids or []
                )

                logger.info(
                    f"[SUPERVISOR] EXTRACT_RELATIONS: Extracted {extraction_result.total_relations_extracted} relations "
                    f"in {extraction_result.extraction_time_seconds:.2f}s"
                )

                # Persistance dans Neo4j
                if extraction_result.relations:
                    write_stats = self.relation_writer.write_relations(
                        relations=extraction_result.relations,
                        document_id=state.document_id,
                        document_name=state.document_name or "unknown"
                    )

                    logger.info(
                        f"[SUPERVISOR] EXTRACT_RELATIONS: ✅ Wrote {write_stats['created']} new, "
                        f"updated {write_stats['updated']}, skipped {write_stats['skipped']} relations"
                    )

                    # Stocker stats dans state
                    state.relation_extraction_stats = {
                        "total_extracted": extraction_result.total_relations_extracted,
                        "total_created": write_stats["created"],
                        "total_updated": write_stats["updated"],
                        "total_skipped": write_stats["skipped"],
                        "relations_by_type": {k.value: v for k, v in extraction_result.relations_by_type.items()},
                        "extraction_time_seconds": extraction_result.extraction_time_seconds
                    }
                else:
                    logger.info("[SUPERVISOR] EXTRACT_RELATIONS: No relations extracted")
                    state.relation_extraction_stats = {"total_extracted": 0}

            except Exception as e:
                logger.error(
                    f"[SUPERVISOR] EXTRACT_RELATIONS: Error during relation extraction: {e}",
                    exc_info=True
                )
                state.errors.append(f"Relation extraction failed: {str(e)}")
                # Continue vers FINALIZE même en cas d'erreur (relation extraction non-critique)

            return FSMState.FINALIZE

        elif fsm_state == FSMState.FINALIZE:
            # Finalisation: chunking + upload Qdrant
            logger.info("[SUPERVISOR] FINALIZE: Chunking document and uploading to Qdrant")

            # Récupérer texte complet
            full_text = state.full_text or ""
            if not full_text:
                logger.warning("[SUPERVISOR] FINALIZE: No full_text available, skipping chunking")
                return FSMState.DONE

            try:
                # Lazy load TextChunker
                from knowbase.ingestion.text_chunker import get_text_chunker
                chunker = get_text_chunker()

                # Récupérer concepts canoniques pour enrichir chunks
                canonical_concepts = []
                try:
                    query = """
                    MATCH (c:CanonicalConcept)
                    WHERE c.tenant_id = $tenant_id AND c.document_id = $document_id
                    RETURN c.canonical_id AS concept_id,
                           c.canonical_name AS name,
                           c.concept_type AS type
                    """
                    with self.neo4j.driver.session(database=self.neo4j.database) as session:
                        result = session.run(query, tenant_id=state.tenant_id, document_id=state.document_id)
                        canonical_concepts = [dict(record) for record in result]
                    logger.info(f"[SUPERVISOR] FINALIZE: Retrieved {len(canonical_concepts)} canonical concepts for chunking")
                except Exception as e:
                    logger.warning(f"[SUPERVISOR] FINALIZE: Failed to retrieve concepts: {e}")

                # Chunking document
                chunks = chunker.chunk_document(
                    text=full_text,
                    document_id=state.document_id,
                    document_name=state.document_name or "unknown",
                    segment_id="full_document",
                    concepts=canonical_concepts,
                    tenant_id=state.tenant_id
                )

                logger.info(f"[SUPERVISOR] FINALIZE: Created {len(chunks)} chunks")

                # Upload to Qdrant
                if chunks:
                    from knowbase.common.qdrant_client import get_qdrant_client
                    qdrant_client = get_qdrant_client()

                    if qdrant_client:
                        # Préparer points Qdrant
                        points = []
                        for i, chunk in enumerate(chunks):
                            points.append({
                                "id": chunk.get("chunk_id"),
                                "vector": chunk.get("embedding", []),
                                "payload": {
                                    "tenant_id": state.tenant_id,
                                    "document_id": state.document_id,
                                    "document_name": state.document_name or "unknown",
                                    "chunk_index": i,
                                    "text": chunk.get("text", ""),
                                    "token_count": chunk.get("token_count", 0),
                                    **chunk_metadata
                                }
                            })

                        # Upload batch
                        try:
                            qdrant_client.upsert(
                                collection_name="knowbase",
                                points=points
                            )
                            logger.info(
                                f"[SUPERVISOR] FINALIZE: ✅ Uploaded {len(points)} chunks to Qdrant collection 'knowbase'"
                            )
                        except Exception as e:
                            logger.error(f"[SUPERVISOR] FINALIZE: Error uploading to Qdrant: {e}")
                    else:
                        logger.warning("[SUPERVISOR] FINALIZE: Qdrant client not available")
                else:
                    logger.warning("[SUPERVISOR] FINALIZE: No chunks created")

            except Exception as e:
                logger.error(
                    f"[SUPERVISOR] FINALIZE: Error during chunking/upload: {e}",
                    exc_info=True
                )
                # Continue vers DONE même en cas d'erreur (chunking non-critique)

            logger.debug("[SUPERVISOR] FINALIZE: Computing final metrics")
            return FSMState.DONE

        elif fsm_state == FSMState.ERROR:
            # Gestion erreur
            logger.error(f"[SUPERVISOR] ERROR state reached. Errors: {state.errors}")
            return FSMState.DONE

        else:
            logger.error(f"[SUPERVISOR] Unknown FSM state: {fsm_state}")
            return FSMState.ERROR
