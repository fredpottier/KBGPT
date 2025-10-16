"""
Tests pour BaseAgent et AgentState.
"""

import pytest
import time
from src.knowbase.agents.base import (
    BaseAgent,
    AgentRole,
    AgentState,
    ToolInput,
    ToolOutput
)


class TestAgentState:
    """Tests pour AgentState."""

    def test_agent_state_initialization(self):
        """Test initialisation AgentState avec valeurs par défaut."""
        state = AgentState(
            document_id="test-doc-123",
            tenant_id="tenant-1"
        )

        assert state.document_id == "test-doc-123"
        assert state.tenant_id == "tenant-1"
        assert state.budget_remaining == {"SMALL": 120, "BIG": 8, "VISION": 2}
        assert state.segments == []
        assert state.candidates == []
        assert state.promoted == []
        assert state.cost_incurred == 0.0
        assert state.llm_calls_count == {"SMALL": 0, "BIG": 0, "VISION": 0}
        assert state.current_step == "init"
        assert state.steps_count == 0
        assert state.max_steps == 50
        assert state.timeout_seconds == 300
        assert state.errors == []

    def test_agent_state_budget_tracking(self):
        """Test tracking budget dans AgentState."""
        state = AgentState(document_id="test-doc")

        # Consommer budget
        state.budget_remaining["SMALL"] -= 10
        state.llm_calls_count["SMALL"] += 10
        state.cost_incurred += 0.02

        assert state.budget_remaining["SMALL"] == 110
        assert state.llm_calls_count["SMALL"] == 10
        assert state.cost_incurred == pytest.approx(0.02)

    def test_agent_state_timeout_check(self):
        """Test vérification timeout."""
        state = AgentState(document_id="test-doc", timeout_seconds=1)

        # Simuler passage du temps
        time.sleep(1.1)

        elapsed = time.time() - state.started_at
        assert elapsed > state.timeout_seconds


class TestBaseAgent:
    """Tests pour BaseAgent."""

    class MockAgent(BaseAgent):
        """Agent mock pour tests."""

        def _register_tools(self):
            self.tools = {
                "test_tool": self._test_tool
            }

        async def execute(self, state: AgentState, instruction=None):
            return state

        def _test_tool(self, tool_input: ToolInput) -> ToolOutput:
            return ToolOutput(
                success=True,
                message="Test tool executed",
                data={"result": "ok"}
            )

    def test_base_agent_initialization(self):
        """Test initialisation BaseAgent."""
        agent = self.MockAgent(AgentRole.SUPERVISOR, config={"test": "value"})

        assert agent.role == AgentRole.SUPERVISOR
        assert agent.config == {"test": "value"}
        assert "test_tool" in agent.tools

    def test_base_agent_call_tool_success(self):
        """Test appel tool avec succès."""
        agent = self.MockAgent(AgentRole.SUPERVISOR)

        result = agent.call_tool("test_tool", ToolInput())

        assert result.success is True
        assert result.message == "Test tool executed"
        assert result.data["result"] == "ok"

    def test_base_agent_call_tool_not_found(self):
        """Test appel tool inexistant."""
        agent = self.MockAgent(AgentRole.SUPERVISOR)

        result = agent.call_tool("unknown_tool", ToolInput())

        assert result.success is False
        assert "not found" in result.message.lower()

    def test_base_agent_validate_state_ok(self):
        """Test validation état OK."""
        agent = self.MockAgent(AgentRole.SUPERVISOR)
        state = AgentState(document_id="test-doc")

        assert agent.validate_state(state) is True

    def test_base_agent_validate_state_max_steps(self):
        """Test validation état avec max_steps atteint."""
        agent = self.MockAgent(AgentRole.SUPERVISOR)
        state = AgentState(document_id="test-doc", max_steps=10)
        state.steps_count = 11

        assert agent.validate_state(state) is False

    def test_base_agent_validate_state_timeout(self):
        """Test validation état avec timeout dépassé."""
        agent = self.MockAgent(AgentRole.SUPERVISOR)
        state = AgentState(document_id="test-doc", timeout_seconds=1)

        # Simuler timeout
        time.sleep(1.1)

        assert agent.validate_state(state) is False

    def test_base_agent_get_tool_names(self):
        """Test récupération noms tools."""
        agent = self.MockAgent(AgentRole.SUPERVISOR)

        tool_names = agent.get_tool_names()

        assert "test_tool" in tool_names
        assert len(tool_names) == 1


class TestToolInputOutput:
    """Tests pour ToolInput et ToolOutput."""

    def test_tool_output_initialization(self):
        """Test initialisation ToolOutput."""
        output = ToolOutput(
            success=True,
            message="Success",
            data={"key": "value"}
        )

        assert output.success is True
        assert output.message == "Success"
        assert output.data == {"key": "value"}

    def test_tool_output_defaults(self):
        """Test valeurs par défaut ToolOutput."""
        output = ToolOutput(success=False)

        assert output.success is False
        assert output.message == ""
        assert output.data == {}
