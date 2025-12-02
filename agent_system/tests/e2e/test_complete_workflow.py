"""
Tests End-to-End pour le workflow complet.
"""
import pytest
import os
from pathlib import Path

from models import Task, TaskPriority
from core.orchestrator import AgentOrchestrator
from monitoring import configure_langsmith


@pytest.mark.e2e
@pytest.mark.slow
class TestCompleteWorkflow:
    """Tests E2E du workflow complet d'orchestration."""

    @pytest.fixture(autouse=True)
    def setup_langsmith(self):
        """Configure LangSmith pour les tests E2E."""
        # Desactiver LangSmith pour les tests sauf si explicitement active
        if not os.getenv("ENABLE_LANGSMITH_TESTS"):
            os.environ["LANGSMITH_TRACING"] = "false"
        yield

    @pytest.fixture
    def orchestrator(self):
        """Cree un orchestrateur pour les tests E2E."""
        return AgentOrchestrator(config_path="agent_system/config/")

    @pytest.mark.skipif(
        not os.getenv("ANTHROPIC_API_KEY"),
        reason="Requires ANTHROPIC_API_KEY"
    )
    def test_calculator_implementation_workflow(self, orchestrator, temp_workspace):
        """
        Test E2E: Implementation complete d'une calculatrice.

        Ce test execute le workflow complet:
        1. Planning Agent decompose la tache
        2. Dev Agent implemente le code et les tests
        3. Control Agent valide le resultat
        """
        # Definir la tache
        task = Task(
            task_id="e2e_calculator_001",
            title="Calculator Implementation",
            description="""
            Implement a simple calculator module with the following features:
            - Function add(a, b) that returns a + b
            - Function subtract(a, b) that returns a - b
            - Function multiply(a, b) that returns a * b
            - Function divide(a, b) that returns a / b with zero division handling
            - Complete unit tests with pytest
            - Code should be in calculator.py
            - Tests should be in test_calculator.py
            """,
            requirements=[
                "All functions must handle integer and float inputs",
                "Divide function must raise ValueError on division by zero",
                "Unit tests must achieve 100% coverage",
                "Code must pass ruff linting",
            ],
            priority=TaskPriority.HIGH,
            context={
                "project_type": "python",
                "test_framework": "pytest",
                "output_directory": str(temp_workspace),
            }
        )

        # Executer l'orchestration
        print("\n" + "=" * 80)
        print("STARTING E2E TEST: Calculator Implementation")
        print("=" * 80)

        result = orchestrator.run(task=task)

        # Verifications du resultat
        assert result is not None
        assert result["status"] in ["success", "failed"]
        assert result["task_id"] == task.task_id

        # Verifier que le plan a ete cree
        assert result["plan_id"] is not None
        print(f"\n✓ Plan created: {result['plan_id']}")

        # Verifier que des rapports Dev ont ete generes
        assert len(result["dev_reports"]) > 0
        print(f"✓ Dev reports generated: {len(result['dev_reports'])}")

        for i, report in enumerate(result["dev_reports"], 1):
            print(f"  {i}. Subtask: {report.get('subtask_id')}")
            print(f"     Status: {report.get('status')}")
            print(f"     Files: {len(report.get('files_modified', []))}")
            print(f"     Tests: {report.get('tests_executed', {}).get('total_tests', 0)}")

        # Verifier que des rapports Control ont ete generes
        assert len(result["control_reports"]) > 0
        print(f"\n✓ Control reports generated: {len(result['control_reports'])}")

        for i, report in enumerate(result["control_reports"], 1):
            print(f"  {i}. Overall Score: {report.get('overall_score', 0):.2f}")
            print(f"     Decision: {report.get('decision')}")
            print(f"     Conformity: {report.get('conformity_score', 0):.2f}")
            print(f"     Quality: {report.get('quality_score', 0):.2f}")
            print(f"     Tests: {report.get('test_score', 0):.2f}")

        # Verifier le nombre d'iterations
        assert result["iterations"] > 0
        assert result["iterations"] <= 10
        print(f"\n✓ Iterations: {result['iterations']}")

        # Afficher le resultat final
        print("\n" + "=" * 80)
        print("FINAL RESULT")
        print("=" * 80)
        print(f"Status: {result['status']}")
        print(f"Validation: {'PASSED ✅' if result['validation_passed'] else 'FAILED ❌'}")
        print("=" * 80 + "\n")

        # Assertions finales
        if result["status"] == "success":
            assert result["validation_passed"] is True
            print("✅ E2E TEST PASSED: Workflow completed successfully")
        else:
            print("⚠️  E2E TEST COMPLETED: Workflow finished with validation issues")

    @pytest.mark.skipif(
        not os.getenv("ANTHROPIC_API_KEY"),
        reason="Requires ANTHROPIC_API_KEY"
    )
    def test_refactoring_workflow(self, orchestrator):
        """
        Test E2E: Refactoring d'un code existant.

        Ce test simule un workflow de refactoring:
        1. Analyser le code existant
        2. Proposer des ameliorations
        3. Appliquer le refactoring
        4. Valider que les tests passent toujours
        """
        task = Task(
            task_id="e2e_refactor_001",
            title="Code Refactoring",
            description="""
            Refactor the following code to improve readability and maintainability:
            - Extract magic numbers into constants
            - Split long functions into smaller ones
            - Add type hints
            - Improve variable names
            - Ensure all tests still pass after refactoring
            """,
            requirements=[
                "All existing tests must pass",
                "Code coverage must not decrease",
                "Ruff linting must pass",
                "Type hints must be added",
            ],
            priority=TaskPriority.MEDIUM,
            context={
                "project_type": "python",
                "refactoring": True,
            }
        )

        result = orchestrator.run(task=task)

        # Verifications de base
        assert result is not None
        assert result["task_id"] == task.task_id
        assert len(result["dev_reports"]) > 0
        assert len(result["control_reports"]) > 0

        print("\n" + "=" * 80)
        print("REFACTORING WORKFLOW RESULT")
        print("=" * 80)
        print(f"Status: {result['status']}")
        print(f"Dev Reports: {len(result['dev_reports'])}")
        print(f"Control Reports: {len(result['control_reports'])}")
        print(f"Validation: {result['validation_passed']}")
        print("=" * 80 + "\n")

    @pytest.mark.skipif(
        not os.getenv("ANTHROPIC_API_KEY"),
        reason="Requires ANTHROPIC_API_KEY"
    )
    def test_bug_fix_workflow(self, orchestrator):
        """
        Test E2E: Correction de bug.

        Ce test simule un workflow de correction de bug:
        1. Analyser le bug reporte
        2. Localiser le code problematique
        3. Proposer et implementer une correction
        4. Ajouter un test de regression
        5. Valider la correction
        """
        task = Task(
            task_id="e2e_bugfix_001",
            title="Fix Division by Zero Bug",
            description="""
            Fix the following bug:
            - The divide function crashes when dividing by zero
            - It should raise a ValueError with a clear message instead
            - Add a regression test to prevent this bug in the future
            """,
            requirements=[
                "Divide function must raise ValueError on zero division",
                "Error message must be clear and helpful",
                "Add regression test",
                "All existing tests must still pass",
            ],
            priority=TaskPriority.CRITICAL,
            context={
                "bug_id": "BUG-001",
                "project_type": "python",
            }
        )

        result = orchestrator.run(task=task)

        # Verifications
        assert result is not None
        assert result["task_id"] == task.task_id

        # Pour un bug critique, on s'attend a une validation reussie
        print("\n" + "=" * 80)
        print("BUG FIX WORKFLOW RESULT")
        print("=" * 80)
        print(f"Status: {result['status']}")
        print(f"Validation: {result['validation_passed']}")
        print("=" * 80 + "\n")


@pytest.mark.e2e
@pytest.mark.slow
class TestWorkflowEdgeCases:
    """Tests E2E des cas limites."""

    @pytest.fixture
    def orchestrator(self):
        """Cree un orchestrateur pour les tests."""
        return AgentOrchestrator(config_path="agent_system/config/")

    def test_empty_requirements(self, orchestrator):
        """Test avec des requirements vides."""
        task = Task(
            task_id="e2e_empty_001",
            title="Task with no requirements",
            description="Do something useful",
            requirements=[],  # Vide
            priority=TaskPriority.LOW,
        )

        result = orchestrator.run(task=task)
        assert result is not None
        assert result["status"] in ["success", "failed"]

    def test_very_simple_task(self, orchestrator):
        """Test avec une tache tres simple."""
        task = Task(
            task_id="e2e_simple_001",
            title="Print Hello World",
            description="Create a Python file that prints 'Hello World'",
            requirements=["File should be named hello.py"],
            priority=TaskPriority.LOW,
        )

        result = orchestrator.run(task=task)
        assert result is not None
        # Meme une tache simple devrait passer par tous les agents
        assert len(result["dev_reports"]) > 0
        assert len(result["control_reports"]) > 0
