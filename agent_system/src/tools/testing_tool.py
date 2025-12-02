"""
Testing Tool - Exécution de tests pytest avec analyse des résultats.
"""
import subprocess
import re
import json
from typing import Any, Dict, List, Optional
from pathlib import Path

from .base_tool import BaseTool
from models.tool_result import TestExecutionResult, ToolStatus
from models.report import TestResult, TestStatus, TestExecutionReport, CoverageReport


class TestingTool(BaseTool):
    """Tool pour exécution de tests pytest."""

    def __init__(
        self,
        project_root: str = "/app",
        default_timeout: int = 300,
        coverage_threshold: float = 0.80,
    ) -> None:
        """
        Args:
            project_root: Racine du projet
            default_timeout: Timeout par défaut en secondes
            coverage_threshold: Seuil de couverture minimum
        """
        super().__init__("testing", "Pytest execution and analysis", default_timeout)
        self.project_root = Path(project_root)
        self.coverage_threshold = coverage_threshold

    def _execute(
        self,
        test_path: Optional[str] = None,
        test_pattern: Optional[str] = None,
        coverage: bool = True,
        verbose: bool = True,
        markers: Optional[List[str]] = None,
        timeout: Optional[int] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Exécute des tests pytest.

        Args:
            test_path: Chemin vers les tests (fichier ou dossier)
            test_pattern: Pattern de tests à exécuter (-k option)
            coverage: Activer la couverture de code
            verbose: Mode verbose
            markers: Liste de markers pytest (-m option)
            timeout: Timeout en secondes
            **kwargs: Arguments additionnels

        Returns:
            Résultat de l'exécution des tests
        """
        # Construire la commande pytest
        cmd_parts = ["pytest"]

        if test_path:
            cmd_parts.append(test_path)

        if verbose:
            cmd_parts.append("-v")

        if test_pattern:
            cmd_parts.extend(["-k", test_pattern])

        if markers:
            for marker in markers:
                cmd_parts.extend(["-m", marker])

        if coverage:
            # Ajouter couverture
            module = kwargs.get("coverage_module", "src")
            cmd_parts.extend([
                f"--cov={module}",
                "--cov-report=term-missing",
                "--cov-report=json",
            ])

        # Options additionnelles
        cmd_parts.append("--tb=short")
        cmd_parts.append("--color=no")

        # Exécuter pytest
        command = " ".join(cmd_parts)
        exec_timeout = timeout or self.timeout

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=exec_timeout,
                cwd=str(self.project_root),
            )

            # Parser les résultats
            test_report = self._parse_pytest_output(result.stdout, result.stderr)
            coverage_report = None

            if coverage:
                coverage_report = self._parse_coverage_report()

            return {
                "command": command,
                "exit_code": result.exitcode,
                "test_report": test_report.model_dump() if test_report else None,
                "coverage_report": coverage_report.model_dump() if coverage_report else None,
                "passed": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }

        except subprocess.TimeoutExpired as e:
            raise TimeoutError(
                f"Tests timed out after {exec_timeout}s: {command}"
            ) from e

    def _parse_pytest_output(self, stdout: str, stderr: str) -> TestExecutionReport:
        """Parse la sortie de pytest."""
        # Extraire le résumé
        summary_match = re.search(
            r"=+ ([\d]+) passed(?:, ([\d]+) failed)?(?:, ([\d]+) skipped)?(?:, ([\d]+) error)? in",
            stdout
        )

        passed = 0
        failed = 0
        skipped = 0
        error = 0
        duration = 0.0

        if summary_match:
            passed = int(summary_match.group(1) or 0)
            failed = int(summary_match.group(2) or 0)
            skipped = int(summary_match.group(3) or 0)
            error = int(summary_match.group(4) or 0)

        # Extraire la durée
        duration_match = re.search(r"in ([\d.]+)s", stdout)
        if duration_match:
            duration = float(duration_match.group(1))

        # Parser les tests individuels
        test_results = self._parse_individual_tests(stdout)

        return TestExecutionReport(
            total_tests=passed + failed + skipped + error,
            passed=passed,
            failed=failed,
            skipped=skipped,
            error=error,
            duration_seconds=duration,
            test_results=test_results,
        )

    def _parse_individual_tests(self, output: str) -> List[TestResult]:
        """Parse les résultats de tests individuels."""
        results = []

        # Pattern pour les tests
        test_pattern = r"([\w/]+\.py)::([\w]+)::([\w]+) (PASSED|FAILED|SKIPPED|ERROR)"

        for match in re.finditer(test_pattern, output):
            file_path = match.group(1)
            class_name = match.group(2)
            test_name = match.group(3)
            status = match.group(4)

            # Mapper le statut
            status_map = {
                "PASSED": TestStatus.PASSED,
                "FAILED": TestStatus.FAILED,
                "SKIPPED": TestStatus.SKIPPED,
                "ERROR": TestStatus.ERROR,
            }

            results.append(TestResult(
                test_name=f"{file_path}::{class_name}::{test_name}",
                status=status_map.get(status, TestStatus.ERROR),
            ))

        return results

    def _parse_coverage_report(self) -> Optional[CoverageReport]:
        """Parse le rapport de couverture JSON."""
        coverage_file = self.project_root / "coverage.json"

        if not coverage_file.exists():
            return None

        try:
            with open(coverage_file, "r") as f:
                cov_data = json.load(f)

            totals = cov_data.get("totals", {})
            files_data = cov_data.get("files", {})

            # Calculer couverture globale
            total_coverage = totals.get("percent_covered", 0.0) / 100.0

            # Extraire lignes manquantes par fichier
            missing_lines = {}
            files_coverage = {}

            for file_path, file_data in files_data.items():
                missing = file_data.get("missing_lines", [])
                if missing:
                    missing_lines[file_path] = missing

                file_cov = file_data.get("summary", {}).get("percent_covered", 0.0) / 100.0
                files_coverage[file_path] = file_cov

            return CoverageReport(
                total_coverage=total_coverage,
                lines_covered=totals.get("covered_lines", 0),
                lines_total=totals.get("num_statements", 0),
                missing_lines=missing_lines,
                files_coverage=files_coverage,
            )

        except Exception as e:
            # Si erreur de parsing, retourner None
            return None

    def run_specific_test(
        self,
        test_file: str,
        test_name: str,
        verbose: bool = True,
    ) -> Dict[str, Any]:
        """
        Exécute un test spécifique.

        Args:
            test_file: Fichier de test
            test_name: Nom du test
            verbose: Mode verbose

        Returns:
            Résultat du test
        """
        return self.execute(
            test_path=f"{test_file}::{test_name}",
            verbose=verbose,
            coverage=False,
        )

    def check_coverage_threshold(
        self,
        module: str,
        threshold: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Vérifie si la couverture atteint le seuil.

        Args:
            module: Module à tester
            threshold: Seuil de couverture (optionnel)

        Returns:
            Résultat de la vérification
        """
        result = self.execute(
            coverage=True,
            coverage_module=module,
        )

        if not result.is_success:
            return {
                "meets_threshold": False,
                "reason": "Tests failed",
            }

        coverage_report = result.output.get("coverage_report")
        if not coverage_report:
            return {
                "meets_threshold": False,
                "reason": "No coverage report",
            }

        total_coverage = coverage_report.get("total_coverage", 0.0)
        required_threshold = threshold or self.coverage_threshold

        return {
            "meets_threshold": total_coverage >= required_threshold,
            "actual_coverage": total_coverage,
            "required_threshold": required_threshold,
            "gap": required_threshold - total_coverage if total_coverage < required_threshold else 0,
        }
