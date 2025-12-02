"""
Tests d'integration pour l'orchestrateur.
"""
import pytest
from pathlib import Path

from models import Task, TaskPriority, TaskComplexity
from core.orchestrator import AgentOrchestrator


@pytest.mark.integration
class TestOrchestratorIntegration:
    """Tests d'integration de l'orchestrateur complet."""

    @pytest.fixture
    def orchestrator(self, config_path):
        """Cree un orchestrateur pour les tests."""
        return AgentOrchestrator(config_path=config_path)

    @pytest.fixture
    def simple_task(self):
        """Cree une tache simple pour les tests."""
        return Task(
            task_id="integration_test_001",
            title="Simple Calculator",
            description="Implement a simple calculator with add and subtract functions",
            requirements=[
                "Function add(a, b) returns a + b",
                "Function subtract(a, b) returns a - b",
                "Write unit tests with pytest",
                "Code should be in calculator.py",
            ],
            priority=TaskPriority.MEDIUM,
            context={
                "project_type": "python",
                "test_framework": "pytest",
            }
        )

    def test_orchestrator_initialization(self, orchestrator):
        """Test initialisation de l'orchestrateur."""
        assert orchestrator is not None
        assert orchestrator.planning_agent is not None
        assert orchestrator.dev_agent is not None
        assert orchestrator.control_agent is not None
        assert orchestrator.graph is not None

    def test_tools_initialization(self, orchestrator):
        """Test initialisation des tools."""
        assert "filesystem" in orchestrator.tools
        assert "shell" in orchestrator.tools
        assert "git" in orchestrator.tools
        assert "testing" in orchestrator.tools
        assert "code_analysis" in orchestrator.tools
        assert "docker" in orchestrator.tools

    def test_planning_agent_has_correct_tools(self, orchestrator):
        """Test que le Planning Agent a les bons tools."""
        planning_tools = {tool.name for tool in orchestrator.planning_agent.tools}
        assert "filesystem" in planning_tools
        assert "git" in planning_tools
        assert "code_analysis" in planning_tools

    def test_dev_agent_has_all_tools(self, orchestrator):
        """Test que le Dev Agent a tous les tools."""
        dev_tools = {tool.name for tool in orchestrator.dev_agent.tools}
        assert len(dev_tools) >= 6  # Tous les tools

    def test_control_agent_has_correct_tools(self, orchestrator):
        """Test que le Control Agent a les bons tools."""
        control_tools = {tool.name for tool in orchestrator.control_agent.tools}
        assert "code_analysis" in control_tools
        assert "testing" in control_tools
        assert "git" in control_tools

    @pytest.mark.slow
    @pytest.mark.requires_llm
    def test_full_orchestration_simple_task(self, orchestrator, simple_task):
        """
        Test orchestration complete avec une tache simple.

        Note: Ce test necessite une cle API Claude valide et peut prendre
        plusieurs minutes. Il est marque comme 'slow' et 'requires_llm'.
        """
        result = orchestrator.run(task=simple_task)

        # Verifier la structure du resultat
        assert "status" in result
        assert "task_id" in result
        assert "plan_id" in result
        assert "dev_reports" in result
        assert "control_reports" in result
        assert "validation_passed" in result
        assert "iterations" in result

        # Verifier que l'orchestration a produit des rapports
        assert result["task_id"] == simple_task.task_id
        assert isinstance(result["dev_reports"], list)
        assert isinstance(result["control_reports"], list)
        assert isinstance(result["validation_passed"], bool)

        # Afficher le resultat pour debug
        print("\n" + "=" * 80)
        print("ORCHESTRATION RESULT")
        print("=" * 80)
        print(f"Status: {result['status']}")
        print(f"Plan ID: {result.get('plan_id')}")
        print(f"Dev Reports: {len(result['dev_reports'])}")
        print(f"Control Reports: {len(result['control_reports'])}")
        print(f"Validation: {result['validation_passed']}")
        print(f"Iterations: {result['iterations']}")
        print("=" * 80)

    def test_orchestrator_max_iterations(self, orchestrator):
        """Test que l'orchestrateur respecte la limite d'iterations."""
        # Creer une tache complexe qui pourrait boucler
        complex_task = Task(
            task_id="complex_test_001",
            title="Complex System",
            description="Implement a very complex system with multiple components",
            requirements=[
                "Component A with feature X",
                "Component B with feature Y",
                "Integration between A and B",
                "Complete test suite",
                "Documentation",
            ],
            priority=TaskPriority.HIGH,
            context={"complexity": "high"}
        )

        # L'orchestrateur doit s'arreter apres max_iterations
        # (meme si la validation n'est pas passee)
        result = orchestrator.run(task=complex_task)

        # Verifier que ca ne boucle pas indefiniment
        assert result["iterations"] <= 10  # Limite par defaut dans orchestrator


@pytest.mark.integration
class TestAgentCommunication:
    """Tests de communication entre agents."""

    @pytest.fixture
    def orchestrator(self, config_path):
        """Cree un orchestrateur pour les tests."""
        return AgentOrchestrator(config_path=config_path)

    def test_planning_to_dev_state_flow(self, orchestrator, simple_task):
        """Test du flux d'etat de Planning vers Dev."""
        from models import create_initial_state

        # Creer l'etat initial
        state = create_initial_state(simple_task)

        # Executer Planning
        state = orchestrator._planning_node(state)

        # Verifier que Planning a produit un plan
        assert state["plan"] is not None
        assert len(state["plan"].subtasks) > 0
        assert state["planning_iterations"] == 1

        # Verifier que le plan a des sous-taches
        subtasks = state["plan"].subtasks
        assert all(hasattr(st, "subtask_id") for st in subtasks)
        assert all(hasattr(st, "description") for st in subtasks)

    def test_dev_to_control_state_flow(self, orchestrator, simple_task):
        """Test du flux d'etat de Dev vers Control."""
        from models import create_initial_state, Plan, Subtask

        # Creer un plan simple pour le test
        plan = Plan(
            plan_id="test_plan_001",
            task_id=simple_task.task_id,
            task_description=simple_task.description,
            subtasks=[
                Subtask(
                    subtask_id="st_001",
                    title="Implement calculator",
                    description="Create calculator.py with add/subtract",
                    complexity=TaskComplexity.LOW,
                    estimated_duration_minutes=30,
                    files_impacted=["calculator.py"],
                )
            ],
            estimated_total_duration_minutes=30,
        )

        state = create_initial_state(simple_task)
        state["plan"] = plan
        state["current_subtask_id"] = "st_001"

        # Executer Dev
        state = orchestrator._dev_node(state)

        # Verifier que Dev a produit un rapport
        assert len(state["dev_reports"]) == 1
        dev_report = state["dev_reports"][0]
        assert dev_report.subtask_id == "st_001"

        # Executer Control
        state = orchestrator._control_node(state)

        # Verifier que Control a produit un rapport
        assert len(state["control_reports"]) == 1
        control_report = state["control_reports"][0]
        assert hasattr(control_report, "overall_score")
        assert hasattr(control_report, "decision")
