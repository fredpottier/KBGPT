"""
Module Code Reviewer - Analyse qualité du code.

Fonctionnalités:
- Détection de code mort (dead code)
- Analyse de structure et organisation
- Vérification des bonnes pratiques
- Détection de code dupliqué
- Complexité cyclomatique
"""
import ast
import os
from pathlib import Path
from typing import Dict, List, Any
from collections import defaultdict
import subprocess


class CodeReviewer:
    """Analyseur de qualité de code."""

    def __init__(self, project_root: Path):
        """
        Initialise le code reviewer.

        Args:
            project_root: Racine du projet
        """
        self.project_root = project_root
        self.src_dir = project_root / "src" / "knowbase"
        self.results = {
            "dead_code": [],
            "quality_issues": [],
            "structure_issues": [],
            "duplicates": [],
            "complexity": [],
            "imports_unused": []
        }

    def analyze(self) -> Dict[str, Any]:
        """
        Exécute l'analyse complète.

        Returns:
            Résultats de l'analyse
        """
        print("🔍 Code Reviewer - Démarrage analyse...")

        # 1. Analyse avec ruff
        self._analyze_with_ruff()

        # 2. Analyse avec mypy
        self._analyze_with_mypy()

        # 3. Détection de code mort
        self._detect_dead_code()

        # 4. Analyse de complexité
        self._analyze_complexity()

        # 5. Détection d'imports inutilisés
        self._detect_unused_imports()

        return {
            "total_issues": self._count_total_issues(),
            "details": self.results,
            "summary": self._generate_summary()
        }

    def _analyze_with_ruff(self):
        """Analyse avec ruff (linting)."""
        print("  📋 Analyse ruff...")
        try:
            result = subprocess.run(
                ["docker-compose", "exec", "-T", "app", "ruff", "check", "src/", "--output-format=json"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.stdout:
                import json
                try:
                    issues = json.loads(result.stdout)
                    for issue in issues:
                        self.results["quality_issues"].append({
                            "file": issue.get("filename", "unknown"),
                            "line": issue.get("location", {}).get("row", 0),
                            "code": issue.get("code", ""),
                            "message": issue.get("message", ""),
                            "severity": "error" if issue.get("code", "").startswith("E") else "warning"
                        })
                except json.JSONDecodeError:
                    pass

            print(f"    ✓ {len(self.results['quality_issues'])} problèmes détectés")

        except subprocess.TimeoutExpired:
            print("    ⚠ Timeout ruff")
        except Exception as e:
            print(f"    ⚠ Erreur ruff: {e}")

    def _analyze_with_mypy(self):
        """Analyse avec mypy (typage)."""
        print("  📋 Analyse mypy...")
        try:
            result = subprocess.run(
                ["docker-compose", "exec", "-T", "app", "mypy", "src/", "--ignore-missing-imports"],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=120
            )

            if result.stdout:
                for line in result.stdout.split('\n'):
                    if ':' in line and ('error:' in line or 'warning:' in line):
                        parts = line.split(':')
                        if len(parts) >= 4:
                            self.results["quality_issues"].append({
                                "file": parts[0].strip(),
                                "line": parts[1].strip(),
                                "type": "typing",
                                "message": ':'.join(parts[3:]).strip(),
                                "severity": "error" if 'error:' in line else "warning"
                            })

            print(f"    ✓ Analyse mypy terminée")

        except subprocess.TimeoutExpired:
            print("    ⚠ Timeout mypy")
        except Exception as e:
            print(f"    ⚠ Erreur mypy: {e}")

    def _detect_dead_code(self):
        """Détecte le code mort (fonctions/classes non utilisées)."""
        print("  💀 Détection code mort...")

        # Analyser tous les fichiers Python
        python_files = list(self.src_dir.rglob("*.py"))

        # Dict: nom -> {file, line, type}
        definitions = {}
        usages = set()

        for py_file in python_files:
            try:
                with open(py_file, 'r', encoding='utf-8-sig') as f:
                    tree = ast.parse(f.read(), filename=str(py_file))

                # Collecter définitions
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        if not node.name.startswith('_'):  # Ignorer privées
                            definitions[node.name] = {
                                "file": str(py_file.relative_to(self.project_root)),
                                "line": node.lineno,
                                "type": "function"
                            }
                    elif isinstance(node, ast.ClassDef):
                        definitions[node.name] = {
                            "file": str(py_file.relative_to(self.project_root)),
                            "line": node.lineno,
                            "type": "class"
                        }

                # Collecter usages
                for node in ast.walk(tree):
                    if isinstance(node, ast.Name):
                        usages.add(node.id)
                    elif isinstance(node, ast.Attribute):
                        usages.add(node.attr)

            except Exception as e:
                print(f"    ⚠ Erreur parsing {py_file.name}: {e}")

        # Identifier le code mort
        for name, info in definitions.items():
            if name not in usages:
                self.results["dead_code"].append({
                    "name": name,
                    "file": info["file"],
                    "line": info["line"],
                    "type": info["type"]
                })

        print(f"    ✓ {len(self.results['dead_code'])} éléments potentiellement non utilisés")

    def _analyze_complexity(self):
        """Analyse la complexité cyclomatique."""
        print("  🧮 Analyse complexité...")

        python_files = list(self.src_dir.rglob("*.py"))

        for py_file in python_files:
            try:
                with open(py_file, 'r', encoding='utf-8-sig') as f:
                    tree = ast.parse(f.read(), filename=str(py_file))

                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        complexity = self._calculate_complexity(node)
                        if complexity > 10:  # Seuil complexité élevée
                            self.results["complexity"].append({
                                "function": node.name,
                                "file": str(py_file.relative_to(self.project_root)),
                                "line": node.lineno,
                                "complexity": complexity,
                                "severity": "high" if complexity > 20 else "medium"
                            })

            except Exception as e:
                print(f"    ⚠ Erreur analyse complexité {py_file.name}: {e}")

        print(f"    ✓ {len(self.results['complexity'])} fonctions complexes détectées")

    def _calculate_complexity(self, node: ast.FunctionDef) -> int:
        """
        Calcule la complexité cyclomatique d'une fonction.

        Args:
            node: Node AST de la fonction

        Returns:
            Score de complexité
        """
        complexity = 1  # Base

        for child in ast.walk(node):
            # Branches
            if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                complexity += 1
            # Opérateurs logiques
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1

        return complexity

    def _detect_unused_imports(self):
        """Détecte les imports non utilisés."""
        print("  📦 Détection imports inutilisés...")

        python_files = list(self.src_dir.rglob("*.py"))

        for py_file in python_files:
            try:
                with open(py_file, 'r', encoding='utf-8-sig') as f:
                    content = f.read()
                    tree = ast.parse(content, filename=str(py_file))

                # Imports
                imports = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            imports.add(alias.asname or alias.name)
                    elif isinstance(node, ast.ImportFrom):
                        for alias in node.names:
                            imports.add(alias.asname or alias.name)

                # Usages
                usages = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Name):
                        usages.add(node.id)

                # Détection inutilisés
                unused = imports - usages
                if unused:
                    self.results["imports_unused"].append({
                        "file": str(py_file.relative_to(self.project_root)),
                        "unused": list(unused)
                    })

            except Exception as e:
                print(f"    ⚠ Erreur détection imports {py_file.name}: {e}")

        print(f"    ✓ {len(self.results['imports_unused'])} fichiers avec imports inutilisés")

    def _count_total_issues(self) -> int:
        """Compte le nombre total de problèmes."""
        return (
            len(self.results["dead_code"]) +
            len(self.results["quality_issues"]) +
            len(self.results["complexity"]) +
            len(self.results["imports_unused"])
        )

    def _generate_summary(self) -> Dict[str, Any]:
        """Génère un résumé de l'analyse."""
        return {
            "dead_code_count": len(self.results["dead_code"]),
            "quality_issues_count": len(self.results["quality_issues"]),
            "complex_functions_count": len(self.results["complexity"]),
            "files_with_unused_imports": len(self.results["imports_unused"]),
            "total_python_files": len(list(self.src_dir.rglob("*.py")))
        }


def run_code_review(project_root: Path) -> Dict[str, Any]:
    """
    Lance l'analyse de code.

    Args:
        project_root: Racine du projet

    Returns:
        Résultats de l'analyse
    """
    reviewer = CodeReviewer(project_root)
    return reviewer.analyze()
