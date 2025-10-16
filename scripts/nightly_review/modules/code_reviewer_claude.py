"""
Code Reviewer avec analyse Claude - Version intelligente.

Combine l'analyse statique (ruff/mypy) avec l'intelligence de Claude.
"""
from pathlib import Path
from typing import Dict, Any
import subprocess
import json

from .claude_analyzer import ClaudeAnalyzer


def run_code_review_with_claude(project_root: Path) -> Dict[str, Any]:
    """
    Exécute une revue de code intelligente avec Claude.

    Args:
        project_root: Racine du projet

    Returns:
        Résultats de la revue (statique + Claude)
    """
    print("📋 CODE REVIEW (Statique + Claude)")
    print("=" * 80)

    results = {
        "total_issues": 0,
        "static_analysis": {},
        "claude_analysis": {},
        "details": {
            "ruff_issues": [],
            "mypy_issues": [],
            "claude_issues": [],
            "claude_suggestions": [],
            "refactoring_opportunities": []
        }
    }

    # Étape 1: Analyse statique rapide (ruff + mypy)
    print("\n  📊 Phase 1: Analyse statique (ruff + mypy)...")
    static_results = _run_static_analysis(project_root)
    results["static_analysis"] = static_results
    results["details"]["ruff_issues"] = static_results.get("ruff_issues", [])
    results["details"]["mypy_issues"] = static_results.get("mypy_issues", [])

    # Étape 2: Analyse intelligente avec Claude
    print("\n  🤖 Phase 2: Analyse intelligente avec Claude...")
    try:
        analyzer = ClaudeAnalyzer(project_root)

        # Collecter les fichiers Python
        src_dir = project_root / "src" / "knowbase"
        python_files = list(src_dir.rglob("*.py"))
        python_files = [f for f in python_files if "__pycache__" not in str(f)]

        # Analyse avec Claude
        claude_results = analyzer.analyze_code_review(python_files, max_files=15)

        results["claude_analysis"] = claude_results
        results["details"]["claude_issues"] = claude_results.get("issues", [])
        results["details"]["claude_suggestions"] = claude_results.get("suggestions", [])
        results["details"]["refactoring_opportunities"] = claude_results.get("refactoring_opportunities", [])

        print(f"    ✓ {len(claude_results.get('issues', []))} issues détectées par Claude")
        print(f"    ✓ {len(claude_results.get('suggestions', []))} suggestions d'amélioration")
        print(f"    ✓ {len(claude_results.get('refactoring_opportunities', []))} opportunités de refactoring")

    except Exception as e:
        print(f"    ⚠ Erreur analyse Claude: {e}")
        results["claude_analysis"] = {"error": str(e)}

    # Calculer le total
    results["total_issues"] = (
        len(results["details"]["ruff_issues"]) +
        len(results["details"]["mypy_issues"]) +
        len(results["details"]["claude_issues"])
    )

    print(f"\n  ✅ Analyse terminée - {results['total_issues']} problèmes détectés")

    return results


def _run_static_analysis(project_root: Path) -> Dict[str, Any]:
    """Exécute l'analyse statique (ruff + mypy)."""

    results = {
        "ruff_issues": [],
        "mypy_issues": []
    }

    # Ruff
    try:
        result = subprocess.run(
            ["docker-compose", "exec", "-T", "app", "ruff", "check", "src/", "--output-format=json"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=60
        )

        if result.stdout:
            ruff_data = json.loads(result.stdout)
            for issue in ruff_data:
                results["ruff_issues"].append({
                    "file": issue.get("filename", "unknown"),
                    "line": issue.get("location", {}).get("row", 0),
                    "code": issue.get("code", ""),
                    "message": issue.get("message", ""),
                    "severity": "medium"
                })

        print(f"    ✓ Ruff: {len(results['ruff_issues'])} problèmes")

    except Exception as e:
        print(f"    ⚠ Ruff non disponible: {e}")

    # Mypy
    try:
        result = subprocess.run(
            ["docker-compose", "exec", "-T", "app", "mypy", "src/knowbase", "--ignore-missing-imports"],
            cwd=project_root,
            capture_output=True,
            text=True,
            timeout=90
        )

        if result.stdout:
            for line in result.stdout.split('\n'):
                if ':' in line and 'error:' in line:
                    parts = line.split(':')
                    if len(parts) >= 3:
                        results["mypy_issues"].append({
                            "file": parts[0].strip(),
                            "line": parts[1].strip() if parts[1].strip().isdigit() else 0,
                            "message": ':'.join(parts[2:]).replace('error:', '').strip(),
                            "severity": "medium"
                        })

        print(f"    ✓ Mypy: {len(results['mypy_issues'])} problèmes")

    except Exception as e:
        print(f"    ⚠ Mypy non disponible: {e}")

    return results
