"""
Data models pour les résultats des tools.
"""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ToolStatus(str, Enum):
    """Statut d'exécution d'un tool."""
    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"
    PERMISSION_DENIED = "permission_denied"


class ToolResult(BaseModel):
    """Résultat d'exécution d'un tool."""

    tool_name: str = Field(..., description="Nom du tool exécuté")
    status: ToolStatus = Field(..., description="Statut d'exécution")
    output: Any = Field(default=None, description="Sortie du tool")
    error_message: Optional[str] = Field(
        default=None,
        description="Message d'erreur si échec"
    )
    traceback: Optional[str] = Field(
        default=None,
        description="Traceback si erreur"
    )
    duration_seconds: float = Field(
        default=0.0,
        ge=0,
        description="Durée d'exécution"
    )
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Date/heure d'exécution"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Métadonnées additionnelles"
    )

    @property
    def is_success(self) -> bool:
        """Vérifie si l'exécution est un succès."""
        return self.status == ToolStatus.SUCCESS

    @property
    def is_error(self) -> bool:
        """Vérifie si l'exécution est une erreur."""
        return self.status in (ToolStatus.ERROR, ToolStatus.TIMEOUT, ToolStatus.PERMISSION_DENIED)


class FilesystemOperationResult(ToolResult):
    """Résultat d'une opération filesystem."""

    operation: str = Field(..., description="Type d'opération (read, write, list, etc.)")
    path: str = Field(..., description="Chemin du fichier/dossier")
    files_affected: List[str] = Field(
        default_factory=list,
        description="Liste des fichiers affectés"
    )


class ShellCommandResult(ToolResult):
    """Résultat d'une commande shell."""

    command: str = Field(..., description="Commande exécutée")
    exit_code: int = Field(default=0, description="Code de sortie")
    stdout: str = Field(default="", description="Sortie standard")
    stderr: str = Field(default="", description="Sortie d'erreur")
    timeout: Optional[int] = Field(default=None, description="Timeout en secondes")


class GitOperationResult(ToolResult):
    """Résultat d'une opération Git."""

    operation: str = Field(..., description="Type d'opération (status, diff, log, etc.)")
    repository_path: str = Field(default="/app", description="Chemin du repository")
    branch: Optional[str] = Field(default=None, description="Branche actuelle")
    commit_hash: Optional[str] = Field(default=None, description="Hash du commit actuel")


class TestExecutionResult(ToolResult):
    """Résultat d'exécution de tests."""

    test_command: str = Field(..., description="Commande de test exécutée")
    total_tests: int = Field(default=0, ge=0, description="Nombre total de tests")
    passed: int = Field(default=0, ge=0, description="Tests réussis")
    failed: int = Field(default=0, ge=0, description="Tests échoués")
    skipped: int = Field(default=0, ge=0, description="Tests skippés")
    coverage: Optional[float] = Field(
        default=None,
        ge=0,
        le=1,
        description="Couverture de code (0-1)"
    )
    test_output: str = Field(default="", description="Sortie des tests")


class CodeAnalysisResult(ToolResult):
    """Résultat d'analyse de code."""

    analysis_type: str = Field(
        ...,
        description="Type d'analyse (ast, complexity, linting, etc.)"
    )
    file_path: str = Field(..., description="Chemin du fichier analysé")
    findings: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Résultats de l'analyse"
    )
    metrics: Dict[str, Any] = Field(
        default_factory=dict,
        description="Métriques calculées"
    )


class DockerOperationResult(ToolResult):
    """Résultat d'une opération Docker."""

    operation: str = Field(..., description="Type d'opération (ps, logs, etc.)")
    service_name: Optional[str] = Field(
        default=None,
        description="Nom du service concerné"
    )
    container_id: Optional[str] = Field(
        default=None,
        description="ID du conteneur"
    )


def create_success_result(
    tool_name: str,
    output: Any,
    duration_seconds: float = 0.0,
    metadata: Optional[Dict[str, Any]] = None
) -> ToolResult:
    """Crée un résultat de succès."""
    return ToolResult(
        tool_name=tool_name,
        status=ToolStatus.SUCCESS,
        output=output,
        duration_seconds=duration_seconds,
        metadata=metadata or {},
    )


def create_error_result(
    tool_name: str,
    error: Exception,
    duration_seconds: float = 0.0,
    metadata: Optional[Dict[str, Any]] = None
) -> ToolResult:
    """Crée un résultat d'erreur."""
    import traceback as tb

    return ToolResult(
        tool_name=tool_name,
        status=ToolStatus.ERROR,
        error_message=str(error),
        traceback=tb.format_exc(),
        duration_seconds=duration_seconds,
        metadata=metadata or {},
    )


def create_timeout_result(
    tool_name: str,
    timeout_seconds: int,
    metadata: Optional[Dict[str, Any]] = None
) -> ToolResult:
    """Crée un résultat de timeout."""
    return ToolResult(
        tool_name=tool_name,
        status=ToolStatus.TIMEOUT,
        error_message=f"Tool execution exceeded timeout of {timeout_seconds}s",
        metadata=metadata or {},
    )


def create_permission_denied_result(
    tool_name: str,
    reason: str,
    metadata: Optional[Dict[str, Any]] = None
) -> ToolResult:
    """Crée un résultat de permission refusée."""
    return ToolResult(
        tool_name=tool_name,
        status=ToolStatus.PERMISSION_DENIED,
        error_message=f"Permission denied: {reason}",
        metadata=metadata or {},
    )
