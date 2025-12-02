"""
Tests unitaires pour les modeles de donnees.
"""
import pytest
from datetime import datetime

from models import (
    Task, TaskPriority, TaskStatus, TaskComplexity,
    Plan, Subtask, Risk, RiskLevel, ValidationPoint,
    DevReport, ControlReport, TestExecutionReport,
    CoverageReport, CodeQualityReport, ReportStatus,
    ValidationDecision, ConformityAnalysis,
    Issue, IssueSeverity, IssueCategory,
    AgentState, create_initial_state, ToolResult,
)


@pytest.mark.unit
class TestTaskModel:
    """Tests pour le modele Task."""

    def test_task_creation(self):
        """Test creation d'une tache."""
        task = Task(
            task_id="test_001",
            title="Test Task",
            description="A test task",
            requirements=["REQ-001", "REQ-002"],
            priority=TaskPriority.HIGH,
        )

        assert task.task_id == "test_001"
        assert task.title == "Test Task"
        assert task.status == TaskStatus.PENDING
        assert task.priority == TaskPriority.HIGH
        assert len(task.requirements) == 2

    def test_task_to_dict(self):
        """Test serialisation en dict."""
        task = Task(
            task_id="test_001",
            title="Test",
            description="Test task",
        )

        task_dict = task.model_dump()
        assert "task_id" in task_dict
        assert task_dict["title"] == "Test"

    def test_task_validation(self):
        """Test validation des champs."""
        with pytest.raises(ValueError):
            Task(
                task_id="",  # ID vide invalide
                title="Test",
                description="Test",
            )


@pytest.mark.unit
class TestPlanModel:
    """Tests pour le modele Plan."""

    def test_plan_creation(self):
        """Test creation d'un plan."""
        subtasks = [
            Subtask(
                subtask_id="st_001",
                title="Subtask 1",
                description="First subtask",
                complexity=TaskComplexity.LOW,
                estimated_duration_minutes=30,
            ),
            Subtask(
                subtask_id="st_002",
                title="Subtask 2",
                description="Second subtask",
                complexity=TaskComplexity.MEDIUM,
                estimated_duration_minutes=60,
                dependencies=["st_001"],
            ),
        ]

        plan = Plan(
            plan_id="plan_001",
            task_id="task_001",
            task_description="Test task",
            subtasks=subtasks,
            estimated_total_duration_minutes=90,
        )

        assert plan.plan_id == "plan_001"
        assert len(plan.subtasks) == 2
        assert plan.estimated_total_duration_minutes == 90

    def test_get_subtask_by_id(self):
        """Test recuperation de sous-tache par ID."""
        subtasks = [
            Subtask(
                subtask_id="st_001",
                title="Subtask 1",
                description="First",
                complexity=TaskComplexity.LOW,
            ),
        ]

        plan = Plan(
            plan_id="plan_001",
            task_id="task_001",
            task_description="Test",
            subtasks=subtasks,
        )

        found = plan.get_subtask_by_id("st_001")
        assert found is not None
        assert found.subtask_id == "st_001"

        not_found = plan.get_subtask_by_id("st_999")
        assert not_found is None

    def test_get_ready_subtasks(self):
        """Test recuperation des sous-taches pretes."""
        subtasks = [
            Subtask(
                subtask_id="st_001",
                title="Subtask 1",
                description="First",
                complexity=TaskComplexity.LOW,
                status=TaskStatus.PENDING,
            ),
            Subtask(
                subtask_id="st_002",
                title="Subtask 2",
                description="Second",
                complexity=TaskComplexity.LOW,
                status=TaskStatus.PENDING,
                dependencies=["st_001"],
            ),
        ]

        plan = Plan(
            plan_id="plan_001",
            task_id="task_001",
            task_description="Test",
            subtasks=subtasks,
        )

        ready = plan.get_ready_subtasks()
        assert len(ready) == 1
        assert ready[0].subtask_id == "st_001"

        # Marquer la premiere comme terminee
        plan.subtasks[0].status = TaskStatus.COMPLETED
        ready = plan.get_ready_subtasks()
        assert len(ready) == 1
        assert ready[0].subtask_id == "st_002"

    def test_get_progress_percentage(self):
        """Test calcul du pourcentage de progression."""
        subtasks = [
            Subtask(
                subtask_id="st_001",
                title="Subtask 1",
                description="First",
                complexity=TaskComplexity.LOW,
                status=TaskStatus.COMPLETED,
            ),
            Subtask(
                subtask_id="st_002",
                title="Subtask 2",
                description="Second",
                complexity=TaskComplexity.LOW,
                status=TaskStatus.IN_PROGRESS,
            ),
            Subtask(
                subtask_id="st_003",
                title="Subtask 3",
                description="Third",
                complexity=TaskComplexity.LOW,
                status=TaskStatus.PENDING,
            ),
        ]

        plan = Plan(
            plan_id="plan_001",
            task_id="task_001",
            task_description="Test",
            subtasks=subtasks,
        )

        progress = plan.get_progress_percentage()
        assert progress == pytest.approx(33.33, rel=0.1)


@pytest.mark.unit
class TestReportModels:
    """Tests pour les modeles de rapports."""

    def test_dev_report_creation(self):
        """Test creation d'un DevReport."""
        report = DevReport(
            report_id="dev_001",
            task_id="task_001",
            subtask_id="st_001",
            files_modified=["test.py"],
            lines_added=50,
            lines_deleted=10,
            tests_executed=TestExecutionReport(
                total_tests=10,
                passed=10,
                failed=0,
                skipped=0,
            ),
            test_coverage=CoverageReport(
                total_coverage=0.85,
                line_coverage=0.85,
                branch_coverage=0.80,
            ),
            code_quality=CodeQualityReport(),
            status=ReportStatus.SUCCESS,
        )

        assert report.report_id == "dev_001"
        assert report.status == ReportStatus.SUCCESS
        assert report.tests_executed.total_tests == 10

    def test_control_report_creation(self):
        """Test creation d'un ControlReport."""
        report = ControlReport(
            report_id="ctrl_001",
            task_id="task_001",
            dev_report_id="dev_001",
            conformity_score=0.90,
            quality_score=0.85,
            test_score=0.95,
            security_score=1.0,
            performance_score=0.90,
            overall_score=0.91,
            conformity_analysis=ConformityAnalysis(conformity_score=0.90),
            decision=ValidationDecision.APPROVED,
        )

        assert report.report_id == "ctrl_001"
        assert report.decision == ValidationDecision.APPROVED
        assert report.overall_score == pytest.approx(0.91, rel=0.01)

    def test_control_report_to_markdown(self):
        """Test export markdown du ControlReport."""
        report = ControlReport(
            report_id="ctrl_001",
            task_id="task_001",
            dev_report_id="dev_001",
            conformity_score=0.90,
            quality_score=0.85,
            test_score=0.95,
            security_score=1.0,
            performance_score=0.90,
            overall_score=0.91,
            conformity_analysis=ConformityAnalysis(conformity_score=0.90),
            decision=ValidationDecision.APPROVED,
        )

        markdown = report.to_markdown()
        assert "# Control Report" in markdown
        assert "ctrl_001" in markdown
        assert "APPROVED" in markdown


@pytest.mark.unit
class TestAgentState:
    """Tests pour AgentState."""

    def test_create_initial_state(self, sample_task):
        """Test creation de l'etat initial."""
        task = Task(**sample_task)
        state = create_initial_state(task)

        assert state["task"] == task
        assert state["plan"] is None
        assert len(state["dev_reports"]) == 0
        assert len(state["control_reports"]) == 0
        assert state["validation_passed"] is False
        assert state["iteration_count"] == 0


@pytest.mark.unit
class TestToolResult:
    """Tests pour ToolResult."""

    def test_tool_result_success(self):
        """Test creation d'un resultat succes."""
        result = ToolResult(
            tool_name="test_tool",
            is_success=True,
            output={"result": "success"},
            error=None,
        )

        assert result.is_success is True
        assert result.output["result"] == "success"
        assert result.error is None

    def test_tool_result_failure(self):
        """Test creation d'un resultat echec."""
        result = ToolResult(
            tool_name="test_tool",
            is_success=False,
            output={},
            error="Test error",
        )

        assert result.is_success is False
        assert result.error == "Test error"
