"""
Module Test Analyzer - Analyse couverture de tests.

Fonctionnalités:
- Exécution des tests avec couverture
- Détection de fonctions sans tests
- Analyse de la qualité des tests
- Suggestions de tests manquants
"""
import subprocess
import json
from pathlib import Path
from typing import Dict, List, Any
import ast


class TestAnalyzer:
    """Analyseur de tests et couverture."""

    def __init__(self, project_root: Path):
        """
        Initialise l'analyseur de tests.

        Args:
            project_root: Racine du projet
        """
        self.project_root = project_root
        self.src_dir = project_root / "src" / "knowbase"
        self.tests_dir = project_root / "tests"
        self.results = {
            "coverage": {},
            "missing_tests": [],
            "test_quality": [],
            "execution_results": {}
        }

    def analyze(self) -> Dict[str, Any]:
        """
        Exécute l'analyse complète des tests.

        Returns:
            Résultats de l'analyse
        """
        print("🧪 Test Analyzer - Démarrage analyse...")

        # 1. Exécuter les tests avec couverture
        self._run_tests_with_coverage()

        # 2. Identifier les fonctions sans tests
        self._detect_missing_tests()

        # 3. Analyser la qualité des tests existants
        self._analyze_test_quality()

        return {
            "total_tests": self.results["execution_results"].get("total", 0),
            "passed": self.results["execution_results"].get("passed", 0),
            "failed": self.results["execution_results"].get("failed", 0),
            "coverage_percent": self.results["coverage"].get("total_percent", 0),
            "missing_tests_count": len(self.results["missing_tests"]),
            "details": self.results,
            "summary": self._generate_summary()
        }

    def _run_tests_with_coverage(self):
        """Exécute les tests avec couverture."""
        print("  🏃 Exécution tests avec couverture...")

        try:
            # Exécuter pytest avec coverage
            result = subprocess.run(
                [
                    "docker-compose", "exec", "-T", "app",
                    "pytest",
                    "--cov=src/knowbase",
                    "--cov-report=json",
                    "--cov-report=term",
                    "-v"
                ],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=300  # 5 minutes max
            )

            # Parser la sortie pytest
            self._parse_pytest_output(result.stdout)

            # Lire le rapport de couverture JSON
            coverage_file = self.project_root / "coverage.json"
            if coverage_file.exists():
                with open(coverage_file, 'r') as f:
                    coverage_data = json.load(f)
                    self.results["coverage"] = {
                        "total_percent": coverage_data.get("totals", {}).get("percent_covered", 0),
                        "files": self._extract_coverage_details(coverage_data)
                    }

            print(f"    ✓ Tests exécutés - Couverture: {self.results['coverage'].get('total_percent', 0):.1f}%")

        except subprocess.TimeoutExpired:
            print("    ⚠ Timeout tests (> 5 min)")
            self.results["execution_results"]["error"] = "Timeout"
        except Exception as e:
            print(f"    ⚠ Erreur exécution tests: {e}")
            self.results["execution_results"]["error"] = str(e)

    def _parse_pytest_output(self, output: str):
        """
        Parse la sortie de pytest.

        Args:
            output: Sortie stdout de pytest
        """
        lines = output.split('\n')
        total = 0
        passed = 0
        failed = 0

        for line in lines:
            if 'passed' in line.lower():
                # Format: "X passed in Y.Ys"
                parts = line.split()
                for i, part in enumerate(parts):
                    if part == 'passed' and i > 0:
                        try:
                            passed = int(parts[i - 1])
                        except (ValueError, IndexError):
                            pass
                    elif part == 'failed' and i > 0:
                        try:
                            failed = int(parts[i - 1])
                        except (ValueError, IndexError):
                            pass

        total = passed + failed

        self.results["execution_results"] = {
            "total": total,
            "passed": passed,
            "failed": failed,
            "success_rate": (passed / total * 100) if total > 0 else 0
        }

    def _extract_coverage_details(self, coverage_data: Dict) -> List[Dict]:
        """
        Extrait les détails de couverture par fichier.

        Args:
            coverage_data: Données de couverture pytest

        Returns:
            Liste des fichiers avec leur couverture
        """
        files_coverage = []

        for file_path, file_data in coverage_data.get("files", {}).items():
            if "src/knowbase" in file_path:
                summary = file_data.get("summary", {})
                percent = summary.get("percent_covered", 0)

                # Identifier les fichiers avec faible couverture
                if percent < 70:
                    files_coverage.append({
                        "file": file_path,
                        "coverage": percent,
                        "missing_lines": file_data.get("missing_lines", []),
                        "severity": "critical" if percent < 50 else "warning"
                    })

        # Trier par couverture croissante
        files_coverage.sort(key=lambda x: x["coverage"])

        return files_coverage

    def _detect_missing_tests(self):
        """Détecte les fonctions/classes sans tests."""
        print("  🔍 Détection fonctions sans tests...")

        # Collecter toutes les fonctions publiques
        functions_in_src = self._collect_functions(self.src_dir)

        # Collecter toutes les fonctions testées
        tested_functions = set()
        if self.tests_dir.exists():
            for test_file in self.tests_dir.rglob("test_*.py"):
                try:
                    with open(test_file, 'r', encoding='utf-8-sig') as f:
                        content = f.read()
                        # Extraire les noms de fonctions mentionnées dans les tests
                        for func_name in functions_in_src:
                            if func_name in content:
                                tested_functions.add(func_name)
                except Exception as e:
                    print(f"    ⚠ Erreur lecture {test_file.name}: {e}")

        # Identifier les fonctions sans tests
        for func_info in functions_in_src.values():
            if func_info["name"] not in tested_functions:
                self.results["missing_tests"].append({
                    "function": func_info["name"],
                    "file": func_info["file"],
                    "line": func_info["line"],
                    "type": func_info["type"]
                })

        print(f"    ✓ {len(self.results['missing_tests'])} fonctions sans tests détectées")

    def _collect_functions(self, directory: Path) -> Dict[str, Dict]:
        """
        Collecte toutes les fonctions publiques d'un répertoire.

        Args:
            directory: Répertoire à analyser

        Returns:
            Dict {fonction_name: info}
        """
        functions = {}

        for py_file in directory.rglob("*.py"):
            if py_file.name.startswith("__"):
                continue

            try:
                with open(py_file, 'r', encoding='utf-8-sig') as f:
                    tree = ast.parse(f.read(), filename=str(py_file))

                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        # Ignorer les fonctions privées
                        if not node.name.startswith('_'):
                            functions[node.name] = {
                                "name": node.name,
                                "file": str(py_file.relative_to(self.project_root)),
                                "line": node.lineno,
                                "type": "function"
                            }
                    elif isinstance(node, ast.ClassDef):
                        # Collecter les méthodes publiques
                        for item in node.body:
                            if isinstance(item, ast.FunctionDef) and not item.name.startswith('_'):
                                full_name = f"{node.name}.{item.name}"
                                functions[full_name] = {
                                    "name": full_name,
                                    "file": str(py_file.relative_to(self.project_root)),
                                    "line": item.lineno,
                                    "type": "method"
                                }

            except Exception as e:
                print(f"    ⚠ Erreur parsing {py_file.name}: {e}")

        return functions

    def _analyze_test_quality(self):
        """Analyse la qualité des tests existants."""
        print("  📊 Analyse qualité tests...")

        if not self.tests_dir.exists():
            print("    ⚠ Dossier tests/ non trouvé")
            return

        test_files = list(self.tests_dir.rglob("test_*.py"))

        for test_file in test_files:
            try:
                with open(test_file, 'r', encoding='utf-8-sig') as f:
                    tree = ast.parse(f.read(), filename=str(test_file))

                # Compter les assertions
                assertions_count = 0
                test_functions_count = 0

                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef) and node.name.startswith('test_'):
                        test_functions_count += 1

                    if isinstance(node, ast.Assert):
                        assertions_count += 1

                # Analyser la qualité
                avg_assertions = assertions_count / test_functions_count if test_functions_count > 0 else 0

                if test_functions_count > 0 and avg_assertions < 1:
                    self.results["test_quality"].append({
                        "file": str(test_file.relative_to(self.project_root)),
                        "test_count": test_functions_count,
                        "assertions_count": assertions_count,
                        "avg_assertions": avg_assertions,
                        "issue": "Peu d'assertions par test"
                    })

            except Exception as e:
                print(f"    ⚠ Erreur analyse {test_file.name}: {e}")

        print(f"    ✓ {len(test_files)} fichiers de tests analysés")

    def _generate_summary(self) -> Dict[str, Any]:
        """Génère un résumé de l'analyse."""
        return {
            "total_tests": self.results["execution_results"].get("total", 0),
            "success_rate": self.results["execution_results"].get("success_rate", 0),
            "coverage": self.results["coverage"].get("total_percent", 0),
            "missing_tests": len(self.results["missing_tests"]),
            "low_coverage_files": len(self.results["coverage"].get("files", []))
        }


def run_test_analysis(project_root: Path) -> Dict[str, Any]:
    """
    Lance l'analyse des tests.

    Args:
        project_root: Racine du projet

    Returns:
        Résultats de l'analyse
    """
    analyzer = TestAnalyzer(project_root)
    return analyzer.analyze()
