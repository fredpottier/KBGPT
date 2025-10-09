"""
Architecture Analyzer avec Claude - Expert architecte senior.

Analyse architecturale profonde avec compréhension contextuelle.
"""
from pathlib import Path
from typing import Dict, Any

from .claude_analyzer import ClaudeAnalyzer


def run_architecture_analysis_with_claude(project_root: Path) -> Dict[str, Any]:
    """
    Analyse architecturale avec Claude comme architecte senior.

    Args:
        project_root: Racine du projet

    Returns:
        Résultats de l'analyse architecturale
    """
    print("🏗️ ANALYSE ARCHITECTURE (Claude Architecte)")
    print("=" * 80)

    results = {
        "total_issues": 0,
        "details": {
            "structure_analysis": {},
            "pattern_analysis": {},
            "architectural_issues": [],
            "recommendations": []
        }
    }

    try:
        analyzer = ClaudeAnalyzer(project_root)

        # Collecter les fichiers Python
        src_dir = project_root / "src" / "knowbase"
        python_files = list(src_dir.rglob("*.py"))
        python_files = [f for f in python_files if "__pycache__" not in str(f)]

        print(f"\n  📁 {len(python_files)} fichiers Python trouvés")

        # Analyse architecturale avec Claude
        print("\n  🤖 Analyse avec Claude Architecte Senior...")
        arch_results = analyzer.analyze_architecture(python_files)

        # Structure analysis
        structure = arch_results.get("structure_analysis", {})
        results["details"]["structure_analysis"] = structure

        print(f"    ✓ Forces identifiées: {len(structure.get('strengths', []))}")
        print(f"    ✓ Faiblesses identifiées: {len(structure.get('weaknesses', []))}")
        print(f"    ✓ Problèmes architecturaux: {len(structure.get('architectural_issues', []))}")

        # Pattern analysis
        patterns = arch_results.get("pattern_analysis", {})
        results["details"]["pattern_analysis"] = patterns

        print(f"    ✓ Patterns détectés: {len(patterns.get('patterns_detected', []))}")
        print(f"    ✓ Anti-patterns: {len(patterns.get('anti_patterns', []))}")

        # Consolidation
        results["details"]["architectural_issues"] = (
            structure.get("architectural_issues", []) +
            patterns.get("anti_patterns", [])
        )

        results["details"]["recommendations"] = arch_results.get("architectural_recommendations", [])

        # Calcul total issues
        results["total_issues"] = len(results["details"]["architectural_issues"])

        print(f"\n  ✅ Analyse terminée - {results['total_issues']} problèmes architecturaux")
        print(f"  💡 {len(results['details']['recommendations'])} recommandations")

    except Exception as e:
        print(f"\n  ❌ Erreur durant l'analyse: {e}")
        import traceback
        traceback.print_exc()
        results["error"] = str(e)

    return results
