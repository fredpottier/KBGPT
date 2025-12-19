"""Tests complets pour BaseAgent et modèles associés.

Tests unitaires couvrant:
- AgentRole enum
- AgentState modèle Pydantic
- ToolInput / ToolOutput modèles
- BaseAgent classe abstraite
- Validation d'état
- Appel de tools
"""

import pytest
import time
from typing import Dict, Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

from knowbase.agents.base import (
    AgentRole,
    AgentState,
    ToolInput,
    ToolOutput,
    BaseAgent,
)


class TestAgentRoleEnum:
    """Tests pour l'enum AgentRole."""

    def test_agent_roles_defined(self) -> None:
        """Test que tous les rôles d'agents sont définis."""
        assert AgentRole.SUPERVISOR.value == "supervisor"
        assert AgentRole.EXTRACTOR.value == "extractor_orchestrator"
        assert AgentRole.MINER.value == "pattern_miner"
        assert AgentRole.GATEKEEPER.value == "gatekeeper_delegate"
        assert AgentRole.BUDGET.value == "budget_manager"
        assert AgentRole.DISPATCHER.value == "llm_dispatcher"

    def test_agent_role_is_string_enum(self) -> None:
        """Test que AgentRole hérite de str."""
        assert isinstance(AgentRole.SUPERVISOR, str)
        assert AgentRole.SUPERVISOR == "supervisor"


class TestAgentState:
    """Tests pour le modèle AgentState."""

    def test_create_minimal_state(self) -> None:
        """Test création d'un état minimal."""
        state = AgentState(document_id="doc-123")

        assert state.document_id == "doc-123"
        assert state.tenant_id == "default"
        assert state.current_step == "init"
        assert state.steps_count == 0

    def test_create_full_state(self) -> None:
        """Test création d'un état complet."""
        state = AgentState(
            document_id="doc-123",
            tenant_id="tenant-abc",
            document_type="PPTX",
            full_text="Sample text content",
            document_name="presentation.pptx",
            chunk_ids=["chunk-1", "chunk-2"],
        )

        assert state.document_id == "doc-123"
        assert state.tenant_id == "tenant-abc"
        assert state.document_type == "PPTX"
        assert state.full_text == "Sample text content"
        assert len(state.chunk_ids) == 2

    def test_default_budget(self) -> None:
        """Test budget par défaut."""
        state = AgentState(document_id="doc-123")

        assert state.budget_remaining["SMALL"] == 120
        assert state.budget_remaining["BIG"] == 8
        assert state.budget_remaining["VISION"] == 2

    def test_default_llm_calls_count(self) -> None:
        """Test compteur d'appels LLM par défaut."""
        state = AgentState(document_id="doc-123")

        assert state.llm_calls_count["SMALL"] == 0
        assert state.llm_calls_count["BIG"] == 0
        assert state.llm_calls_count["VISION"] == 0

    def test_default_collections(self) -> None:
        """Test collections par défaut vides."""
        state = AgentState(document_id="doc-123")

        assert state.segments == []
        assert state.candidates == []
        assert state.promoted == []
        assert state.relations == []
        assert state.errors == []

    def test_timeout_default(self) -> None:
        """Test timeout par défaut."""
        state = AgentState(document_id="doc-123")

        assert state.timeout_seconds == 3600  # 1 heure
        assert state.max_steps == 50

    def test_started_at_auto_generated(self) -> None:
        """Test que started_at est auto-généré."""
        before = time.time()
        state = AgentState(document_id="doc-123")
        after = time.time()

        assert before <= state.started_at <= after

    def test_custom_data_dict(self) -> None:
        """Test custom_data accepte un dictionnaire."""
        state = AgentState(
            document_id="doc-123",
            custom_data={"key1": "value1", "slides_data": [{"slide": 1}]},
        )

        assert state.custom_data["key1"] == "value1"
        assert len(state.custom_data["slides_data"]) == 1

    def test_concept_to_chunk_ids_mapping(self) -> None:
        """Test mapping concept → chunk_ids."""
        state = AgentState(
            document_id="doc-123",
            concept_to_chunk_ids={
                "proto-123": ["chunk-456", "chunk-789"],
                "proto-124": ["chunk-101"],
            },
        )

        assert len(state.concept_to_chunk_ids["proto-123"]) == 2
        assert "chunk-456" in state.concept_to_chunk_ids["proto-123"]


class TestToolInput:
    """Tests pour le modèle ToolInput."""

    def test_tool_input_base_model(self) -> None:
        """Test que ToolInput est un BaseModel vide."""
        # ToolInput est une classe de base
        tool_input = ToolInput()
        assert tool_input is not None

    def test_tool_input_subclass(self) -> None:
        """Test création d'une sous-classe ToolInput."""

        class CustomToolInput(ToolInput):
            param1: str
            param2: int = 0

        custom = CustomToolInput(param1="test", param2=42)
        assert custom.param1 == "test"
        assert custom.param2 == 42


class TestToolOutput:
    """Tests pour le modèle ToolOutput."""

    def test_tool_output_success(self) -> None:
        """Test création d'un output réussi."""
        output = ToolOutput(
            success=True,
            message="Operation completed",
            data={"result": "value"},
        )

        assert output.success is True
        assert output.message == "Operation completed"
        assert output.data["result"] == "value"

    def test_tool_output_failure(self) -> None:
        """Test création d'un output échoué."""
        output = ToolOutput(
            success=False,
            message="Operation failed: timeout",
        )

        assert output.success is False
        assert "failed" in output.message
        assert output.data == {}

    def test_tool_output_defaults(self) -> None:
        """Test valeurs par défaut de ToolOutput."""
        output = ToolOutput(success=True)

        assert output.success is True
        assert output.message == ""
        assert output.data == {}


class ConcreteAgent(BaseAgent):
    """Agent concret pour les tests (BaseAgent est abstrait)."""

    def _register_tools(self) -> None:
        """Enregistre des tools de test."""
        self.tools["sync_tool"] = self._sync_tool
        self.tools["async_tool"] = self._async_tool
        self.tools["failing_tool"] = self._failing_tool

    def _sync_tool(self, tool_input: ToolInput) -> ToolOutput:
        """Tool synchrone de test."""
        return ToolOutput(success=True, message="Sync tool executed")

    async def _async_tool(self, tool_input: ToolInput) -> ToolOutput:
        """Tool asynchrone de test."""
        return ToolOutput(success=True, message="Async tool executed")

    def _failing_tool(self, tool_input: ToolInput) -> ToolOutput:
        """Tool qui échoue."""
        raise ValueError("Tool error")

    async def execute(
        self,
        state: AgentState,
        instruction: Optional[str] = None,
    ) -> AgentState:
        """Exécute la logique de l'agent."""
        state.steps_count += 1
        state.current_step = "executed"
        return state


class TestBaseAgent:
    """Tests pour la classe BaseAgent."""

    def test_agent_initialization(self) -> None:
        """Test initialisation d'un agent."""
        agent = ConcreteAgent(role=AgentRole.EXTRACTOR)

        assert agent.role == AgentRole.EXTRACTOR
        assert agent.config == {}
        assert len(agent.tools) == 3

    def test_agent_initialization_with_config(self) -> None:
        """Test initialisation d'un agent avec config."""
        config = {"param1": "value1", "param2": 42}
        agent = ConcreteAgent(role=AgentRole.SUPERVISOR, config=config)

        assert agent.config["param1"] == "value1"
        assert agent.config["param2"] == 42

    def test_get_tool_names(self) -> None:
        """Test récupération des noms de tools."""
        agent = ConcreteAgent(role=AgentRole.EXTRACTOR)
        tool_names = agent.get_tool_names()

        assert "sync_tool" in tool_names
        assert "async_tool" in tool_names
        assert "failing_tool" in tool_names


class TestBaseAgentValidation:
    """Tests pour la validation d'état."""

    def test_validate_state_valid(self) -> None:
        """Test validation d'un état valide."""
        agent = ConcreteAgent(role=AgentRole.EXTRACTOR)
        state = AgentState(document_id="doc-123")

        assert agent.validate_state(state) is True

    def test_validate_state_max_steps_exceeded(self) -> None:
        """Test validation avec max_steps dépassé."""
        agent = ConcreteAgent(role=AgentRole.EXTRACTOR)
        state = AgentState(
            document_id="doc-123",
            steps_count=51,
            max_steps=50,
        )

        assert agent.validate_state(state) is False

    def test_validate_state_timeout_exceeded(self) -> None:
        """Test validation avec timeout dépassé."""
        agent = ConcreteAgent(role=AgentRole.EXTRACTOR)
        state = AgentState(
            document_id="doc-123",
            started_at=time.time() - 3700,  # > 1 heure
            timeout_seconds=3600,
        )

        assert agent.validate_state(state) is False


class TestBaseAgentCallTool:
    """Tests pour l'appel de tools."""

    @pytest.mark.asyncio
    async def test_call_sync_tool(self) -> None:
        """Test appel d'un tool synchrone."""
        agent = ConcreteAgent(role=AgentRole.EXTRACTOR)
        tool_input = ToolInput()

        result = await agent.call_tool("sync_tool", tool_input)

        assert result.success is True
        assert result.message == "Sync tool executed"

    @pytest.mark.asyncio
    async def test_call_async_tool(self) -> None:
        """Test appel d'un tool asynchrone."""
        agent = ConcreteAgent(role=AgentRole.EXTRACTOR)
        tool_input = ToolInput()

        result = await agent.call_tool("async_tool", tool_input)

        assert result.success is True
        assert result.message == "Async tool executed"

    @pytest.mark.asyncio
    async def test_call_nonexistent_tool(self) -> None:
        """Test appel d'un tool inexistant."""
        agent = ConcreteAgent(role=AgentRole.EXTRACTOR)
        tool_input = ToolInput()

        result = await agent.call_tool("nonexistent_tool", tool_input)

        assert result.success is False
        assert "not found" in result.message

    @pytest.mark.asyncio
    async def test_call_failing_tool(self) -> None:
        """Test appel d'un tool qui échoue."""
        agent = ConcreteAgent(role=AgentRole.EXTRACTOR)
        tool_input = ToolInput()

        result = await agent.call_tool("failing_tool", tool_input)

        assert result.success is False
        assert "failed" in result.message


class TestBaseAgentExecute:
    """Tests pour la méthode execute."""

    @pytest.mark.asyncio
    async def test_execute_updates_state(self) -> None:
        """Test que execute met à jour l'état."""
        agent = ConcreteAgent(role=AgentRole.EXTRACTOR)
        state = AgentState(document_id="doc-123")

        result_state = await agent.execute(state)

        assert result_state.steps_count == 1
        assert result_state.current_step == "executed"

    @pytest.mark.asyncio
    async def test_execute_with_instruction(self) -> None:
        """Test execute avec instruction."""
        agent = ConcreteAgent(role=AgentRole.EXTRACTOR)
        state = AgentState(document_id="doc-123")

        result_state = await agent.execute(state, instruction="Extract entities")

        assert result_state.steps_count == 1


class TestAgentStateUpdates:
    """Tests pour les mises à jour d'état."""

    def test_update_budget(self) -> None:
        """Test mise à jour du budget."""
        state = AgentState(document_id="doc-123")

        state.budget_remaining["SMALL"] -= 10
        state.llm_calls_count["SMALL"] += 10

        assert state.budget_remaining["SMALL"] == 110
        assert state.llm_calls_count["SMALL"] == 10

    def test_add_candidates(self) -> None:
        """Test ajout de candidats."""
        state = AgentState(document_id="doc-123")

        state.candidates.append({"name": "SAP S/4HANA", "type": "SOLUTION"})
        state.candidates.append({"name": "HANA", "type": "COMPONENT"})

        assert len(state.candidates) == 2
        assert state.candidates[0]["name"] == "SAP S/4HANA"

    def test_add_errors(self) -> None:
        """Test ajout d'erreurs."""
        state = AgentState(document_id="doc-123")

        state.errors.append("Error 1: timeout")
        state.errors.append("Error 2: invalid format")

        assert len(state.errors) == 2
        assert "timeout" in state.errors[0]

    def test_update_cost(self) -> None:
        """Test mise à jour du coût."""
        state = AgentState(document_id="doc-123")

        state.cost_incurred += 0.05
        state.cost_incurred += 0.03

        assert state.cost_incurred == pytest.approx(0.08, rel=1e-6)


class TestAgentStateSerialization:
    """Tests pour la sérialisation de l'état."""

    def test_state_to_dict(self) -> None:
        """Test conversion état vers dict."""
        state = AgentState(
            document_id="doc-123",
            tenant_id="tenant-abc",
            document_type="PDF",
        )

        state_dict = state.model_dump()

        assert state_dict["document_id"] == "doc-123"
        assert state_dict["tenant_id"] == "tenant-abc"
        assert state_dict["document_type"] == "PDF"

    def test_state_from_dict(self) -> None:
        """Test création état depuis dict."""
        state_dict = {
            "document_id": "doc-456",
            "tenant_id": "tenant-xyz",
            "current_step": "processing",
            "steps_count": 5,
        }

        state = AgentState(**state_dict)

        assert state.document_id == "doc-456"
        assert state.current_step == "processing"
        assert state.steps_count == 5
