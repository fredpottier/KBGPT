"""
Tests pour SupervisorAgent.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.knowbase.agents.supervisor.supervisor import (
    SupervisorAgent,
    FSMState
)
from src.knowbase.agents.base import AgentState


class TestSupervisorAgent:
    """Tests pour SupervisorAgent."""

    @pytest.fixture
    def supervisor(self):
        """Fixture SupervisorAgent."""
        return SupervisorAgent(config={})

    @pytest.fixture
    def initial_state(self):
        """Fixture AgentState initial."""
        return AgentState(
            document_id="test-doc-123",
            tenant_id="test-tenant"
        )

    def test_supervisor_initialization(self, supervisor):
        """Test initialisation SupervisorAgent."""
        assert supervisor.role.value == "supervisor"
        assert supervisor.budget_manager is not None
        assert supervisor.extractor is not None
        assert supervisor.miner is not None
        assert supervisor.gatekeeper is not None
        assert supervisor.dispatcher is not None

    def test_fsm_transitions_structure(self, supervisor):
        """Test structure FSM transitions."""
        assert FSMState.INIT in supervisor.fsm_transitions
        assert FSMState.BUDGET_CHECK in supervisor.fsm_transitions[FSMState.INIT]
        assert FSMState.SEGMENT in supervisor.fsm_transitions[FSMState.BUDGET_CHECK]
        assert FSMState.EXTRACT in supervisor.fsm_transitions[FSMState.SEGMENT]
        assert FSMState.DONE in supervisor.fsm_transitions[FSMState.ERROR]
        assert supervisor.fsm_transitions[FSMState.DONE] == []

    def test_fsm_state_enum(self):
        """Test énumération FSMState."""
        assert FSMState.INIT.value == "init"
        assert FSMState.BUDGET_CHECK.value == "budget_check"
        assert FSMState.SEGMENT.value == "segment"
        assert FSMState.EXTRACT.value == "extract"
        assert FSMState.MINE_PATTERNS.value == "mine_patterns"
        assert FSMState.GATE_CHECK.value == "gate_check"
        assert FSMState.PROMOTE.value == "promote"
        assert FSMState.FINALIZE.value == "finalize"
        assert FSMState.ERROR.value == "error"
        assert FSMState.DONE.value == "done"

    @pytest.mark.asyncio
    async def test_execute_fsm_step_init(self, supervisor, initial_state):
        """Test exécution étape INIT."""
        next_state = await supervisor._execute_fsm_step(FSMState.INIT, initial_state)

        assert next_state == FSMState.BUDGET_CHECK

    @pytest.mark.asyncio
    async def test_execute_fsm_step_budget_check_ok(self, supervisor, initial_state):
        """Test exécution étape BUDGET_CHECK avec budget OK."""
        # Mock budget_manager.check_budget pour retourner True
        supervisor.budget_manager.check_budget = AsyncMock(return_value=True)

        next_state = await supervisor._execute_fsm_step(FSMState.BUDGET_CHECK, initial_state)

        assert next_state == FSMState.SEGMENT

    @pytest.mark.asyncio
    async def test_execute_fsm_step_budget_check_fail(self, supervisor, initial_state):
        """Test exécution étape BUDGET_CHECK avec budget insuffisant."""
        # Mock budget_manager.check_budget pour retourner False
        supervisor.budget_manager.check_budget = AsyncMock(return_value=False)

        next_state = await supervisor._execute_fsm_step(FSMState.BUDGET_CHECK, initial_state)

        assert next_state == FSMState.ERROR
        assert "Budget insufficient" in initial_state.errors

    @pytest.mark.asyncio
    async def test_execute_fsm_step_segment(self, supervisor, initial_state):
        """Test exécution étape SEGMENT."""
        next_state = await supervisor._execute_fsm_step(FSMState.SEGMENT, initial_state)

        assert next_state == FSMState.EXTRACT
        # Segments sera vide (TODO: Intégrer TopicSegmenter)
        assert isinstance(initial_state.segments, list)

    @pytest.mark.asyncio
    async def test_execute_fsm_step_extract(self, supervisor, initial_state):
        """Test exécution étape EXTRACT."""
        # Mock extractor.execute
        supervisor.extractor.execute = AsyncMock(return_value=initial_state)

        next_state = await supervisor._execute_fsm_step(FSMState.EXTRACT, initial_state)

        assert next_state == FSMState.MINE_PATTERNS
        supervisor.extractor.execute.assert_called_once_with(initial_state)

    @pytest.mark.asyncio
    async def test_execute_fsm_step_mine_patterns(self, supervisor, initial_state):
        """Test exécution étape MINE_PATTERNS."""
        # Mock miner.execute
        supervisor.miner.execute = AsyncMock(return_value=initial_state)

        next_state = await supervisor._execute_fsm_step(FSMState.MINE_PATTERNS, initial_state)

        assert next_state == FSMState.GATE_CHECK
        supervisor.miner.execute.assert_called_once_with(initial_state)

    @pytest.mark.asyncio
    async def test_execute_fsm_step_gate_check_promoted(self, supervisor, initial_state):
        """Test exécution étape GATE_CHECK avec concepts promoted."""
        # Mock gatekeeper.execute avec promoted non vide
        initial_state.promoted = [{"name": "SAP S/4HANA"}]
        supervisor.gatekeeper.execute = AsyncMock(return_value=initial_state)

        next_state = await supervisor._execute_fsm_step(FSMState.GATE_CHECK, initial_state)

        assert next_state == FSMState.PROMOTE

    @pytest.mark.asyncio
    async def test_execute_fsm_step_gate_check_retry(self, supervisor, initial_state):
        """Test exécution étape GATE_CHECK avec retry (no promoted + budget BIG)."""
        # Mock gatekeeper.execute avec promoted vide + budget BIG > 0
        initial_state.promoted = []
        initial_state.budget_remaining["BIG"] = 5
        supervisor.gatekeeper.execute = AsyncMock(return_value=initial_state)

        next_state = await supervisor._execute_fsm_step(FSMState.GATE_CHECK, initial_state)

        assert next_state == FSMState.EXTRACT  # Retry

    @pytest.mark.asyncio
    async def test_execute_fsm_step_promote(self, supervisor, initial_state):
        """Test exécution étape PROMOTE."""
        next_state = await supervisor._execute_fsm_step(FSMState.PROMOTE, initial_state)

        assert next_state == FSMState.FINALIZE

    @pytest.mark.asyncio
    async def test_execute_fsm_step_finalize(self, supervisor, initial_state):
        """Test exécution étape FINALIZE."""
        next_state = await supervisor._execute_fsm_step(FSMState.FINALIZE, initial_state)

        assert next_state == FSMState.DONE

    @pytest.mark.asyncio
    async def test_execute_fsm_step_error(self, supervisor, initial_state):
        """Test exécution étape ERROR."""
        initial_state.errors.append("Test error")

        next_state = await supervisor._execute_fsm_step(FSMState.ERROR, initial_state)

        assert next_state == FSMState.DONE

    @pytest.mark.asyncio
    async def test_execute_full_fsm_simple_path(self, supervisor, initial_state):
        """Test exécution FSM complète (path simple sans retry)."""
        # Mock tous les agents
        supervisor.budget_manager.check_budget = AsyncMock(return_value=True)
        supervisor.extractor.execute = AsyncMock(return_value=initial_state)
        supervisor.miner.execute = AsyncMock(return_value=initial_state)

        # Gatekeeper retourne promoted non vide
        initial_state.promoted = [{"name": "SAP S/4HANA"}]
        supervisor.gatekeeper.execute = AsyncMock(return_value=initial_state)

        # Exécuter FSM
        final_state = await supervisor.execute(initial_state)

        # Vérifier état final
        assert final_state.current_step == FSMState.DONE.value
        assert final_state.steps_count > 0
        assert final_state.steps_count <= final_state.max_steps

    @pytest.mark.asyncio
    async def test_execute_fsm_validation_failure(self, supervisor):
        """Test exécution FSM avec validation failure (timeout)."""
        # État avec timeout très court
        state = AgentState(
            document_id="test-doc",
            timeout_seconds=0  # Timeout immédiat
        )

        # Mock agents
        supervisor.budget_manager.check_budget = AsyncMock(return_value=True)

        # Exécuter FSM (devrait échouer sur timeout)
        final_state = await supervisor.execute(state)

        # Vérifier que FSM s'est arrêté en ERROR
        assert final_state.current_step == FSMState.DONE.value
        # Steps_count devrait être petit (échec rapide)
        assert final_state.steps_count < 10

    @pytest.mark.asyncio
    async def test_execute_fsm_max_steps_reached(self, supervisor):
        """Test exécution FSM avec max_steps atteint."""
        # État avec max_steps très bas
        state = AgentState(
            document_id="test-doc",
            max_steps=2
        )

        # Mock agents
        supervisor.budget_manager.check_budget = AsyncMock(return_value=True)

        # Exécuter FSM
        final_state = await supervisor.execute(state)

        # Vérifier que FSM s'est arrêté
        assert final_state.current_step == FSMState.DONE.value
        assert final_state.steps_count <= 2

    def test_fsm_transition_validation(self, supervisor, initial_state):
        """Test validation transitions FSM."""
        # Transition valide
        assert FSMState.SEGMENT in supervisor.fsm_transitions[FSMState.BUDGET_CHECK]

        # Transition invalide
        assert FSMState.PROMOTE not in supervisor.fsm_transitions[FSMState.INIT]
