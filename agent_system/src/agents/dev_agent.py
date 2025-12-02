"""
Dev Agent - Implémente le code, écrit les tests, génère les patches.
"""
from datetime import datetime
from typing import Any, Dict, List
import json

from .base_agent import BaseAgent
from models import (
    AgentState,
    DevReport,
    ReportStatus,
    TestExecutionReport,
    CoverageReport,
    CodeQualityReport,
)
from tools import (
    FilesystemTool,
    ShellTool,
    GitTool,
    TestingTool,
    CodeAnalysisTool,
)


class DevAgent(BaseAgent):
    """Agent spécialisé dans le développement et les tests."""

    def __init__(
        self,
        prompts_config_path: str = "agent_system/config/prompts/dev.yaml",
        **kwargs: Any
    ) -> None:
        super().__init__(
            name="dev_agent",
            prompts_config_path=prompts_config_path,
            **kwargs
        )

    def execute(self, state: AgentState) -> AgentState:
        """
        Exécute le Dev Agent: implémente une sous-tâche.

        Args:
            state: État actuel

        Returns:
            État mis à jour avec DevReport
        """
        plan = state["plan"]
        subtask_id = state["current_subtask_id"]

        if not plan or not subtask_id:
            raise ValueError("Plan and current_subtask_id required")

        subtask = plan.get_subtask_by_id(subtask_id)
        if not subtask:
            raise ValueError(f"Subtask not found: {subtask_id}")

        # 1. Implémenter le code
        implementation_result = self._implement_code(subtask, state)

        # 2. Générer et exécuter les tests
        test_result = self._generate_and_run_tests(subtask, implementation_result)

        # 3. Vérifier la qualité du code
        quality_result = self._check_code_quality(implementation_result["files_modified"])

        # 4. Générer le rapport
        report = self._generate_dev_report(
            subtask,
            implementation_result,
            test_result,
            quality_result,
        )

        # 5. Mettre à jour l'état
        state["dev_reports"].append(report)

        return state

    def _implement_code(self, subtask: Any, state: AgentState) -> Dict[str, Any]:
        """Implémente le code pour la sous-tâche."""
        system_prompt = self.get_prompt("system_prompt")
        if not system_prompt:
            system_prompt = "Tu es un Dev Agent expert en développement Python."

        # Lire les fichiers existants si spécifiés
        existing_code = {}
        for file_path in subtask.files_impacted:
            fs_tool = self._get_tool(FilesystemTool)
            if fs_tool:
                result = fs_tool.execute(operation="read", path=file_path)
                if result.is_success:
                    existing_code[file_path] = result.output.get("content", "")

        implementation_prompt = self.format_prompt(
            "implementation_prompt",
            subtask_description=subtask.description,
            files_impacted=str(subtask.files_impacted),
            plan_context=state["plan"].model_dump_json(),
            existing_code=json.dumps(existing_code, indent=2),
        )

        # Invoquer le LLM
        response = self.invoke_llm(system_prompt, implementation_prompt)

        # Écrire le code généré (simulation - en production parser la réponse)
        files_modified = []
        # TODO: Parser la réponse et écrire les fichiers via FilesystemTool

        return {
            "files_modified": files_modified,
            "lines_added": 0,
            "lines_deleted": 0,
            "code_generated": response,
        }

    def _generate_and_run_tests(self, subtask: Any, implementation: Dict[str, Any]) -> Dict[str, Any]:
        """Génère et exécute les tests."""
        # Générer les tests
        test_code = self._generate_tests(subtask, implementation)

        # Exécuter les tests
        testing_tool = self._get_tool(TestingTool)
        if testing_tool:
            result = testing_tool.execute(
                test_path="tests/",
                coverage=True,
                verbose=True,
            )

            if result.is_success:
                return result.output

        return {
            "test_report": TestExecutionReport().model_dump(),
            "coverage_report": CoverageReport().model_dump(),
        }

    def _generate_tests(self, subtask: Any, implementation: Dict[str, Any]) -> str:
        """Génère le code des tests."""
        system_prompt = self.get_prompt("system_prompt")
        if not system_prompt:
            system_prompt = "Tu es un Dev Agent expert."

        test_prompt = self.format_prompt(
            "test_generation_prompt",
            code_to_test=implementation.get("code_generated", ""),
            module_path="src/knowbase/",
        )

        response = self.invoke_llm(system_prompt, test_prompt)
        return response

    def _check_code_quality(self, files: List[str]) -> Dict[str, Any]:
        """Vérifie la qualité du code."""
        analysis_tool = self._get_tool(CodeAnalysisTool)
        if not analysis_tool:
            return {}

        results = {}
        for file_path in files:
            result = analysis_tool.execute(
                analysis_type="ruff",
                file_path=file_path,
            )
            if result.is_success:
                results[file_path] = result.output

        return results

    def _generate_dev_report(
        self,
        subtask: Any,
        implementation: Dict[str, Any],
        test_result: Dict[str, Any],
        quality_result: Dict[str, Any],
    ) -> DevReport:
        """Génère le rapport final du Dev Agent."""
        report_id = f"dev_report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

        test_report_data = test_result.get("test_report", {})
        coverage_data = test_result.get("coverage_report", {})

        report = DevReport(
            report_id=report_id,
            task_id=subtask.subtask_id.replace("subtask_", "task_"),
            subtask_id=subtask.subtask_id,
            files_modified=implementation.get("files_modified", []),
            lines_added=implementation.get("lines_added", 0),
            lines_deleted=implementation.get("lines_deleted", 0),
            tests_executed=TestExecutionReport(**test_report_data) if test_report_data else TestExecutionReport(),
            test_coverage=CoverageReport(**coverage_data) if coverage_data else CoverageReport(),
            code_quality=CodeQualityReport(),
            status=ReportStatus.SUCCESS,
        )

        return report

    def _get_tool(self, tool_class: type) -> Any:
        """Récupère un tool par sa classe."""
        for tool in self.tools:
            if isinstance(tool, tool_class):
                return tool
        return None
