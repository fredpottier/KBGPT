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
    FINALIZE = "finalize"
    ERROR = "error"
    DONE = "done"


class SupervisorAgent(BaseAgent):
    """
    Supervisor Agent - FSM Master.

    Pipeline FSM:
    INIT → BUDGET_CHECK → SEGMENT → EXTRACT → MINE_PATTERNS → GATE_CHECK → PROMOTE → FINALIZE → DONE

    Transitions conditionnelles:
    - BUDGET_CHECK fail → ERROR
    - GATE_CHECK fail → EXTRACT (retry avec BIG model)
    - Any step timeout → ERROR
    - Max steps reached → ERROR
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

        # FSM transitions (état actuel → états suivants possibles)
        self.fsm_transitions: Dict[FSMState, List[FSMState]] = {
            FSMState.INIT: [FSMState.BUDGET_CHECK],
            FSMState.BUDGET_CHECK: [FSMState.SEGMENT, FSMState.ERROR],
            FSMState.SEGMENT: [FSMState.EXTRACT, FSMState.ERROR],
            FSMState.EXTRACT: [FSMState.MINE_PATTERNS, FSMState.ERROR],
            FSMState.MINE_PATTERNS: [FSMState.GATE_CHECK, FSMState.ERROR],
            FSMState.GATE_CHECK: [FSMState.PROMOTE, FSMState.EXTRACT, FSMState.ERROR],  # Retry si fail
            FSMState.PROMOTE: [FSMState.FINALIZE, FSMState.ERROR],
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
            return FSMState.FINALIZE

        elif fsm_state == FSMState.FINALIZE:
            # Finalisation métriques
            logger.debug("[SUPERVISOR] FINALIZE: Computing final metrics")
            return FSMState.DONE

        elif fsm_state == FSMState.ERROR:
            # Gestion erreur
            logger.error(f"[SUPERVISOR] ERROR state reached. Errors: {state.errors}")
            return FSMState.DONE

        else:
            logger.error(f"[SUPERVISOR] Unknown FSM state: {fsm_state}")
            return FSMState.ERROR
