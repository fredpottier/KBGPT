"""
Control Agent - Valide la conformité, qualité, tests, sécurité.
"""
from datetime import datetime
from typing import Any, Dict, List

from .base_agent import BaseAgent
from models import (
    AgentState,
    ControlReport,
    ValidationDecision,
    ConformityAnalysis,
    Issue,
    IssueSeverity,
    IssueCategory,
)
from tools import CodeAnalysisTool, TestingTool


class ControlAgent(BaseAgent):
    """Agent spécialisé dans la validation et le contrôle qualité."""

    def __init__(
        self,
        prompts_config_path: str = "agent_system/config/prompts/control.yaml",
        conformity_threshold: float = 0.85,
        **kwargs: Any
    ) -> None:
        super().__init__(
            name="control_agent",
            prompts_config_path=prompts_config_path,
            **kwargs
        )
        self.conformity_threshold = conformity_threshold

    def execute(self, state: AgentState) -> AgentState:
        """
        Exécute le Control Agent: valide le travail du Dev Agent.

        Args:
            state: État actuel

        Returns:
            État mis à jour avec ControlReport
        """
        # 1. Analyser la conformité aux specs
        conformity_score, conformity_analysis = self._check_conformity(state)

        # 2. Analyser la qualité du code
        quality_score, quality_issues = self._check_code_quality(state)

        # 3. Valider les tests
        test_score = self._validate_tests(state)

        # 4. Scanner la sécurité
        security_score, security_vulns = self._scan_security(state)

        # 5. Évaluer la performance (placeholder)
        performance_score = 0.90

        # 6. Calculer le score global
        overall_score = (
            conformity_score * 0.30 +
            quality_score * 0.25 +
            test_score * 0.25 +
            security_score * 0.10 +
            performance_score * 0.10
        )

        # 7. Déterminer la décision
        decision = self._make_decision(overall_score, quality_issues, security_vulns)

        # 8. Générer le rapport
        report = self._generate_control_report(
            state,
            conformity_score,
            conformity_analysis,
            quality_score,
            quality_issues,
            test_score,
            security_score,
            security_vulns,
            performance_score,
            overall_score,
            decision,
        )

        # 9. Mettre à jour l'état
        state["control_reports"].append(report)
        state["validation_passed"] = (decision == ValidationDecision.APPROVED)

        return state

    def _check_conformity(self, state: AgentState) -> tuple[float, ConformityAnalysis]:
        """Vérifie la conformité aux spécifications."""
        task = state["task"]
        plan = state["plan"]
        dev_reports = state["dev_reports"]

        system_prompt = self.get_prompt("system_prompt")
        if not system_prompt:
            system_prompt = "Tu es un Control Agent expert en validation."

        conformity_prompt = self.format_prompt(
            "conformity_check_prompt",
            original_spec=task.description,
            plan=plan.model_dump_json(),
            implementation=str(dev_reports),
            dev_report=dev_reports[-1].model_dump_json() if dev_reports else "{}",
        )

        response = self.invoke_llm(system_prompt, conformity_prompt)

        # Parser la réponse (simulation)
        conformity_score = 0.90
        conformity_analysis = ConformityAnalysis(
            conformity_score=conformity_score,
        )

        return conformity_score, conformity_analysis

    def _check_code_quality(self, state: AgentState) -> tuple[float, List[Issue]]:
        """Vérifie la qualité du code."""
        issues: List[Issue] = []
        quality_score = 0.85

        # TODO: Analyser avec CodeAnalysisTool

        return quality_score, issues

    def _validate_tests(self, state: AgentState) -> float:
        """Valide les tests et la couverture."""
        dev_reports = state["dev_reports"]
        if not dev_reports:
            return 0.0

        last_report = dev_reports[-1]
        coverage = last_report.test_coverage.total_coverage

        # Score basé sur la couverture
        if coverage >= 0.80:
            return 1.0
        elif coverage >= 0.70:
            return 0.85
        elif coverage >= 0.60:
            return 0.70
        else:
            return 0.50

    def _scan_security(self, state: AgentState) -> tuple[float, List[Issue]]:
        """Scan de sécurité."""
        vulns: List[Issue] = []
        security_score = 1.0

        # TODO: Implémenter scan sécurité réel

        return security_score, vulns

    def _make_decision(
        self,
        overall_score: float,
        quality_issues: List[Issue],
        security_vulns: List[Issue],
    ) -> ValidationDecision:
        """Détermine la décision de validation."""
        # Rejeter si vulnérabilités critiques
        critical_issues = [
            i for i in (quality_issues + security_vulns)
            if i.severity == IssueSeverity.CRITICAL
        ]

        if critical_issues:
            return ValidationDecision.REJECTED

        # Décision basée sur le score
        if overall_score >= self.conformity_threshold:
            return ValidationDecision.APPROVED
        elif overall_score >= 0.70:
            return ValidationDecision.APPROVED_WITH_COMMENTS
        else:
            return ValidationDecision.REJECTED

    def _generate_control_report(
        self,
        state: AgentState,
        conformity_score: float,
        conformity_analysis: ConformityAnalysis,
        quality_score: float,
        quality_issues: List[Issue],
        test_score: float,
        security_score: float,
        security_vulns: List[Issue],
        performance_score: float,
        overall_score: float,
        decision: ValidationDecision,
    ) -> ControlReport:
        """Génère le rapport de validation."""
        dev_reports = state["dev_reports"]
        dev_report_id = dev_reports[-1].report_id if dev_reports else "unknown"

        report_id = f"control_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

        report = ControlReport(
            report_id=report_id,
            task_id=state["task"].task_id,
            dev_report_id=dev_report_id,
            conformity_score=conformity_score,
            quality_score=quality_score,
            test_score=test_score,
            security_score=security_score,
            performance_score=performance_score,
            overall_score=overall_score,
            conformity_analysis=conformity_analysis,
            code_quality_issues=quality_issues,
            security_vulnerabilities=security_vulns,
            decision=decision,
        )

        return report
