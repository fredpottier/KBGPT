"""
Test Analyzer avec Claude - Expert QA senior.

Analyse de tests avec intelligence contextuelle.
"""
from pathlib import Path
from typing import Dict, Any
import subprocess
import json

from .claude_analyzer import ClaudeAnalyzer


def run_test_analysis_with_claude(project_root: Path) -> Dict[str, Any]:
    """
    Analyse des tests avec Claude expert QA.

    Args:
        project_root: Racine du projet

    Returns:
        Résultats de l'analyse des tests
    """
    print("🧪 ANALYSE TESTS (Exécution + Claude QA)")
    print("=" * 80)

    results = {
        "total_tests": 0,
        "passed": 0,
        "failed": 0,
        "coverage_percent": 0.0,
        "details": {
            "test_execution": {},
            "claude_quality_analysis": {},
            "missing_tests": [],
            "test_improvements": []
        }
    }

    # Phase 1: Exécution des tests et coverage
    print("\n  📊 Phase 1: Exécution des tests et coverage...")
    execution_results = _run_tests_with_coverage(project_root)
    results["details"]["test_execution"] = execution_results

    results["total_tests"] = execution_results.get("total", 0)
    results["passed"] = execution_results.get("passed", 0)
    results["failed"] = execution_results.get("failed", 0)
    results["coverage_percent"] = execution_results.get("coverage_percent", 0.0)

    print(f"    ✓ {results['passed']}/{results['total_tests']} tests réussis")
    print(f"    ✓ Couverture: {results['coverage_percent']:.1f}%")

    # Phase 2: Analyse qualité avec Claude
    print("\n  🤖 Phase 2: Analyse qualité avec Claude QA Expert...")
    try:
        analyzer = ClaudeAnalyzer(project_root)

        # Collecter fichiers source et tests
        src_dir = project_root / "src" / "knowbase"
        tests_dir = project_root / "tests"

        src_files = list(src_dir.rglob("*.py"))
        src_files = [f for f in src_files if "__pycache__" not in str(f)]

        test_files = list(tests_dir.rglob("test_*.py")) if tests_dir.exists() else []

        # Analyse avec Claude
        claude_results = analyzer.analyze_tests(src_files, test_files)

        results["details"]["claude_quality_analysis"] = claude_results
        results["details"]["missing_tests"] = claude_results.get("missing_test_suggestions", [])
        results["details"]["test_improvements"] = claude_results.get("test_improvement_recommendations", [])

        print(f"    ✓ {len(claude_results.get('test_quality_issues', []))} problèmes de qualité détectés")
        print(f"    ✓ {len(claude_results.get('missing_test_suggestions', []))} suggestions de tests manquants")
        print(f"    ✓ {len(claude_results.get('test_improvement_recommendations', []))} recommandations d'amélioration")

    except Exception as e:
        print(f"    ⚠ Erreur analyse Claude: {e}")
        results["details"]["claude_quality_analysis"] = {"error": str(e)}

    print(f"\n  ✅ Analyse terminée")

    return results


def _run_tests_with_coverage(project_root: Path) -> Dict[str, Any]:
    """Exécute les tests avec coverage."""

    results = {
        "total": 0,
        "passed": 0,
        "failed": 0,
        "coverage_percent": 0.0
    }

    try:
        # Exécuter les tests avec coverage
        result = subprocess.run(
            [
                "docker-compose", "exec", "-T", "app",
                "pytest",
                "--cov=src/knowbase",
                "--cov-report=json",
                "--cov-report=term",
                "-v"
            ],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=300
        )

        # Parser le résultat
        output = result.stdout + result.stderr

        # Extraire les stats de tests
        for line in output.split('\n'):
            if 'passed' in line.lower():
                parts = line.split()
                for i, part in enumerate(parts):
                    if 'passed' in part.lower() and i > 0:
                        try:
                            results["passed"] = int(parts[i - 1])
                        except:
                            pass
            if 'failed' in line.lower():
                parts = line.split()
                for i, part in enumerate(parts):
                    if 'failed' in part.lower() and i > 0:
                        try:
                            results["failed"] = int(parts[i - 1])
                        except:
                            pass

        results["total"] = results["passed"] + results["failed"]

        # Lire le coverage JSON si disponible
        coverage_file = project_root / "coverage.json"
        if coverage_file.exists():
            with open(coverage_file, 'r') as f:
                coverage_data = json.load(f)
                results["coverage_percent"] = coverage_data.get("totals", {}).get("percent_covered", 0.0)

    except subprocess.TimeoutExpired:
        print("    ⚠ Timeout exécution tests (>5min)")
    except Exception as e:
        print(f"    ⚠ Erreur exécution tests: {e}")

    return results
