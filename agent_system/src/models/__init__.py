"""
Data models pour le systeme d'agents.
"""
from .task import (
    Task,
    Subtask,
    TaskPriority,
    TaskStatus,
    TaskComplexity,
)
from .plan import (
    Plan,
    Risk,
    RiskLevel,
    ValidationPoint,
)
from .report import (
    DevReport,
    ControlReport,
    TestResult,
    TestExecutionReport,
    CoverageReport,
    CodeQualityReport,
    Issue,
    IssueSeverity,
    IssueCategory,
    ConformityAnalysis,
    ValidationDecision,
    ReportStatus,
    TestStatus,
)
from .agent_state import (
    AgentState,
    create_initial_state,
    update_state_with_plan,
    update_state_with_dev_report,
    update_state_with_control_report,
    add_error_to_state,
    add_warning_to_state,
)
from .tool_result import (
    ToolResult,
    ToolStatus,
    FilesystemOperationResult,
    ShellCommandResult,
    GitOperationResult,
    TestExecutionResult,
    CodeAnalysisResult,
    DockerOperationResult,
    create_success_result,
    create_error_result,
    create_timeout_result,
    create_permission_denied_result,
)
from .project import (
    ProjectPlan,
    ProjectTask,
    ProjectState,
    ProjectReport,
    ProjectStatus,
    ProjectTaskStatus,
)

__all__ = [
    # Task models
    "Task",
    "Subtask",
    "TaskPriority",
    "TaskStatus",
    "TaskComplexity",
    # Plan models
    "Plan",
    "Risk",
    "RiskLevel",
    "ValidationPoint",
    # Report models
    "DevReport",
    "ControlReport",
    "TestResult",
    "TestExecutionReport",
    "CoverageReport",
    "CodeQualityReport",
    "Issue",
    "IssueSeverity",
    "IssueCategory",
    "ConformityAnalysis",
    "ValidationDecision",
    "ReportStatus",
    "TestStatus",
    # Agent state
    "AgentState",
    "create_initial_state",
    "update_state_with_plan",
    "update_state_with_dev_report",
    "update_state_with_control_report",
    "add_error_to_state",
    "add_warning_to_state",
    # Tool results
    "ToolResult",
    "ToolStatus",
    "FilesystemOperationResult",
    "ShellCommandResult",
    "GitOperationResult",
    "TestExecutionResult",
    "CodeAnalysisResult",
    "DockerOperationResult",
    "create_success_result",
    "create_error_result",
    "create_timeout_result",
    "create_permission_denied_result",
    # Project models
    "ProjectPlan",
    "ProjectTask",
    "ProjectState",
    "ProjectReport",
    "ProjectStatus",
    "ProjectTaskStatus",
]
