"""
Data models pour les rapports d'agents (Dev, Control).
"""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class ReportStatus(str, Enum):
    """Statut d'un rapport."""
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class TestStatus(str, Enum):
    """Statut d'un test."""
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


class IssueSeverity(str, Enum):
    """Sévérité d'un issue."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class IssueCategory(str, Enum):
    """Catégorie d'un issue."""
    QUALITY = "quality"
    ARCHITECTURE = "architecture"
    SECURITY = "security"
    PERFORMANCE = "performance"
    TESTS = "tests"
    CONFORMITY = "conformity"


class TestResult(BaseModel):
    """Résultat d'un test individuel."""

    test_name: str = Field(..., description="Nom du test")
    status: TestStatus = Field(..., description="Statut du test")
    duration_seconds: float = Field(default=0.0, ge=0, description="Durée d'exécution")
    error_message: Optional[str] = Field(default=None, description="Message d'erreur si échec")
    traceback: Optional[str] = Field(default=None, description="Traceback si erreur")


class TestExecutionReport(BaseModel):
    """Rapport d'exécution des tests."""

    total_tests: int = Field(default=0, ge=0, description="Nombre total de tests")
    passed: int = Field(default=0, ge=0, description="Nombre de tests réussis")
    failed: int = Field(default=0, ge=0, description="Nombre de tests échoués")
    skipped: int = Field(default=0, ge=0, description="Nombre de tests skippés")
    error: int = Field(default=0, ge=0, description="Nombre de tests en erreur")
    duration_seconds: float = Field(default=0.0, ge=0, description="Durée totale")
    test_results: List[TestResult] = Field(
        default_factory=list,
        description="Résultats détaillés des tests"
    )


class CoverageReport(BaseModel):
    """Rapport de couverture de code."""

    total_coverage: float = Field(default=0.0, ge=0, le=1, description="Couverture totale (0-1)")
    lines_covered: int = Field(default=0, ge=0, description="Nombre de lignes couvertes")
    lines_total: int = Field(default=0, ge=0, description="Nombre total de lignes")
    missing_lines: Dict[str, List[int]] = Field(
        default_factory=dict,
        description="Lignes manquantes par fichier"
    )
    files_coverage: Dict[str, float] = Field(
        default_factory=dict,
        description="Couverture par fichier"
    )


class CodeQualityReport(BaseModel):
    """Rapport de qualité de code."""

    ruff_errors: int = Field(default=0, ge=0, description="Nombre d'erreurs ruff")
    ruff_warnings: int = Field(default=0, ge=0, description="Nombre de warnings ruff")
    mypy_errors: int = Field(default=0, ge=0, description="Nombre d'erreurs mypy")
    black_formatted: bool = Field(default=True, description="Code formaté avec black")
    average_complexity: float = Field(default=0.0, ge=0, description="Complexité moyenne")
    high_complexity_functions: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Fonctions avec complexité élevée"
    )


class DevReport(BaseModel):
    """Rapport du Dev Agent."""

    report_id: str = Field(..., description="Identifiant unique du rapport")
    task_id: str = Field(..., description="ID de la tâche associée")
    subtask_id: str = Field(..., description="ID de la sous-tâche traitée")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Date/heure du rapport"
    )
    agent_version: str = Field(default="0.1.0", description="Version de l'agent")

    # Modifications de code
    files_modified: List[str] = Field(
        default_factory=list,
        description="Liste des fichiers modifiés"
    )
    files_created: List[str] = Field(
        default_factory=list,
        description="Liste des fichiers créés"
    )
    files_deleted: List[str] = Field(
        default_factory=list,
        description="Liste des fichiers supprimés"
    )
    lines_added: int = Field(default=0, ge=0, description="Nombre de lignes ajoutées")
    lines_deleted: int = Field(default=0, ge=0, description="Nombre de lignes supprimées")

    # Tests
    tests_executed: TestExecutionReport = Field(
        default_factory=TestExecutionReport,
        description="Rapport d'exécution des tests"
    )
    test_coverage: CoverageReport = Field(
        default_factory=CoverageReport,
        description="Rapport de couverture"
    )

    # Qualité du code
    code_quality: CodeQualityReport = Field(
        default_factory=CodeQualityReport,
        description="Rapport de qualité du code"
    )

    # Patches
    patches: List[str] = Field(
        default_factory=list,
        description="Chemins vers les fichiers patch générés"
    )

    # Statut et résultat
    status: ReportStatus = Field(..., description="Statut du rapport")
    issues: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Issues identifiées durant le développement"
    )
    recommendations: List[str] = Field(
        default_factory=list,
        description="Recommandations pour amélioration"
    )

    # Métadonnées
    duration_seconds: float = Field(default=0.0, ge=0, description="Durée totale d'exécution")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Métadonnées additionnelles"
    )

    @field_validator('report_id')
    @classmethod
    def validate_report_id(cls, v: str) -> str:
        """Valide le format de l'ID de rapport."""
        if not v.startswith('dev_report_'):
            raise ValueError("report_id must start with 'dev_report_'")
        return v

    def to_dict(self) -> Dict[str, Any]:
        """Convertit le modèle en dictionnaire."""
        return self.model_dump()


class Issue(BaseModel):
    """Modèle d'un issue identifié."""

    issue_id: str = Field(..., description="Identifiant de l'issue")
    severity: IssueSeverity = Field(..., description="Sévérité de l'issue")
    category: IssueCategory = Field(..., description="Catégorie de l'issue")
    description: str = Field(..., description="Description de l'issue")
    location: str = Field(..., description="Localisation (file:line)")
    suggestion: Optional[str] = Field(
        default=None,
        description="Suggestion de correction"
    )


class ValidationDecision(str, Enum):
    """Décision de validation."""
    APPROVED = "approved"
    APPROVED_WITH_COMMENTS = "approved_with_comments"
    REJECTED = "rejected"


class ConformityAnalysis(BaseModel):
    """Analyse de conformité aux spécifications."""

    requirements_implemented: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Requirements implémentées"
    )
    conformity_score: float = Field(
        default=0.0,
        ge=0,
        le=1,
        description="Score de conformité (0-1)"
    )
    missing_features: List[str] = Field(
        default_factory=list,
        description="Fonctionnalités manquantes"
    )
    deviations: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Écarts par rapport aux specs"
    )


class ControlReport(BaseModel):
    """Rapport du Control Agent."""

    report_id: str = Field(..., description="Identifiant unique du rapport")
    task_id: str = Field(..., description="ID de la tâche associée")
    dev_report_id: str = Field(..., description="ID du rapport Dev associé")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Date/heure du rapport"
    )
    agent_version: str = Field(default="0.1.0", description="Version de l'agent")

    # Scores de validation
    conformity_score: float = Field(default=0.0, ge=0, le=1, description="Score conformité")
    quality_score: float = Field(default=0.0, ge=0, le=1, description="Score qualité")
    test_score: float = Field(default=0.0, ge=0, le=1, description="Score tests")
    security_score: float = Field(default=0.0, ge=0, le=1, description="Score sécurité")
    performance_score: float = Field(default=0.0, ge=0, le=1, description="Score performance")
    overall_score: float = Field(default=0.0, ge=0, le=1, description="Score global")

    # Analyses détaillées
    conformity_analysis: ConformityAnalysis = Field(
        default_factory=ConformityAnalysis,
        description="Analyse de conformité"
    )
    code_quality_issues: List[Issue] = Field(
        default_factory=list,
        description="Issues de qualité de code"
    )
    security_vulnerabilities: List[Issue] = Field(
        default_factory=list,
        description="Vulnérabilités de sécurité"
    )

    # Décision et recommandations
    decision: ValidationDecision = Field(..., description="Décision de validation")
    critical_issues: List[Issue] = Field(
        default_factory=list,
        description="Issues critiques bloquantes"
    )
    recommendations: List[str] = Field(
        default_factory=list,
        description="Recommandations d'amélioration"
    )
    required_actions: List[str] = Field(
        default_factory=list,
        description="Actions requises avant approval"
    )

    # Métadonnées
    duration_seconds: float = Field(default=0.0, ge=0, description="Durée de validation")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Métadonnées additionnelles"
    )

    @field_validator('report_id')
    @classmethod
    def validate_report_id(cls, v: str) -> str:
        """Valide le format de l'ID de rapport."""
        if not v.startswith('control_report_'):
            raise ValueError("report_id must start with 'control_report_'")
        return v

    def to_dict(self) -> Dict[str, Any]:
        """Convertit le modèle en dictionnaire."""
        return self.model_dump()

    def to_markdown(self) -> str:
        """Génère un rapport Markdown."""
        md_lines = [
            f"# Rapport de Validation - Task {self.task_id}",
            "",
            f"**Date:** {self.timestamp.isoformat()}",
            f"**Validateur:** Control Agent v{self.agent_version}",
            f"**Décision:** {self.decision.value.upper()}",
            "",
            f"## Score Global: {self.overall_score:.2f} / 1.00",
            "",
            "### Détail des Scores",
            "",
            "| Critère | Score | Poids | Contribution |",
            "|---------|-------|-------|--------------|",
            f"| Conformité aux specs | {self.conformity_score:.2f} | 30% | {self.conformity_score * 0.30:.2f} |",
            f"| Qualité du code | {self.quality_score:.2f} | 25% | {self.quality_score * 0.25:.2f} |",
            f"| Tests | {self.test_score:.2f} | 25% | {self.test_score * 0.25:.2f} |",
            f"| Sécurité | {self.security_score:.2f} | 10% | {self.security_score * 0.10:.2f} |",
            f"| Performance | {self.performance_score:.2f} | 10% | {self.performance_score * 0.10:.2f} |",
            "",
        ]

        if self.critical_issues:
            md_lines.extend([
                "### Issues Critiques (Bloquantes)",
                "",
            ])
            for issue in self.critical_issues:
                md_lines.append(f"- **{issue.location}**: {issue.description}")
            md_lines.append("")

        if self.recommendations:
            md_lines.extend([
                "### Recommandations",
                "",
            ])
            for i, rec in enumerate(self.recommendations, 1):
                md_lines.append(f"{i}. {rec}")
            md_lines.append("")

        if self.required_actions:
            md_lines.extend([
                "### Actions Requises",
                "",
            ])
            for action in self.required_actions:
                md_lines.append(f"- [ ] {action}")
            md_lines.append("")

        md_lines.extend([
            "---",
            f"**Signature:** Control Agent v{self.agent_version}",
        ])

        return "\n".join(md_lines)
