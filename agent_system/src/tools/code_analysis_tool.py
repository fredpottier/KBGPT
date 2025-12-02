"""
Code Analysis Tool - Analyse de code (AST, complexité, linting).
"""
import subprocess
import ast
import json
from typing import Any, Dict, List, Optional
from pathlib import Path

from .base_tool import BaseTool


class CodeAnalysisTool(BaseTool):
    """Tool pour analyse de code Python."""

    def __init__(
        self,
        project_root: str = "/app",
        complexity_threshold: int = 10,
    ) -> None:
        """
        Args:
            project_root: Racine du projet
            complexity_threshold: Seuil de complexité cyclomatique
        """
        super().__init__("code_analysis", "Code analysis (AST, complexity, linting)")
        self.project_root = Path(project_root)
        self.complexity_threshold = complexity_threshold

    def _execute(
        self,
        analysis_type: str,
        file_path: Optional[str] = None,
        directory: Optional[str] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Exécute une analyse de code.

        Args:
            analysis_type: Type d'analyse (ast, complexity, ruff, mypy, black)
            file_path: Fichier à analyser
            directory: Dossier à analyser
            **kwargs: Arguments additionnels

        Returns:
            Résultat de l'analyse
        """
        target = file_path or directory
        if not target:
            raise ValueError("file_path or directory required")

        if analysis_type == "ast":
            return self._analyze_ast(target)
        elif analysis_type == "complexity":
            return self._analyze_complexity(target)
        elif analysis_type == "ruff":
            return self._run_ruff(target, **kwargs)
        elif analysis_type == "mypy":
            return self._run_mypy(target, **kwargs)
        elif analysis_type == "black":
            return self._run_black(target, **kwargs)
        else:
            raise ValueError(f"Unknown analysis type: {analysis_type}")

    def _analyze_ast(self, file_path: str) -> Dict[str, Any]:
        """Analyse AST d'un fichier Python."""
        path = self.project_root / file_path

        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        with open(path, "r") as f:
            source = f.read()

        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as e:
            return {
                "file": file_path,
                "syntax_error": str(e),
                "line": e.lineno,
            }

        # Analyser l'AST
        functions = []
        classes = []
        imports = []

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                functions.append({
                    "name": node.name,
                    "line": node.lineno,
                    "args": [arg.arg for arg in node.args.args],
                    "decorators": [d.id if isinstance(d, ast.Name) else str(d) for d in node.decorator_list],
                })
            elif isinstance(node, ast.ClassDef):
                classes.append({
                    "name": node.name,
                    "line": node.lineno,
                    "bases": [b.id if isinstance(b, ast.Name) else str(b) for b in node.bases],
                })
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports.append(alias.name)
                else:
                    imports.append(f"{node.module}.{node.names[0].name}" if node.names else node.module)

        return {
            "file": file_path,
            "functions": functions,
            "classes": classes,
            "imports": list(set(imports)),
            "total_functions": len(functions),
            "total_classes": len(classes),
            "total_imports": len(set(imports)),
        }

    def _analyze_complexity(self, target: str) -> Dict[str, Any]:
        """Analyse la complexité cyclomatique avec radon."""
        path = self.project_root / target

        try:
            # Exécuter radon cc
            result = subprocess.run(
                ["radon", "cc", str(path), "-a", "-s", "-j"],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(self.project_root),
            )

            if result.returncode != 0:
                return {
                    "error": result.stderr,
                    "exit_code": result.returncode,
                }

            # Parser le JSON
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError:
                # Fallback: parser le format texte
                return self._parse_radon_text(result.stdout)

            # Analyser les résultats
            high_complexity = []
            average_complexity = 0.0
            total_functions = 0

            for file_path, functions in data.items():
                for func in functions:
                    complexity = func.get("complexity", 0)
                    total_functions += 1
                    average_complexity += complexity

                    if complexity > self.complexity_threshold:
                        high_complexity.append({
                            "file": file_path,
                            "function": func.get("name"),
                            "line": func.get("lineno"),
                            "complexity": complexity,
                        })

            if total_functions > 0:
                average_complexity /= total_functions

            return {
                "target": target,
                "average_complexity": round(average_complexity, 2),
                "total_functions": total_functions,
                "high_complexity_functions": high_complexity,
                "threshold": self.complexity_threshold,
            }

        except FileNotFoundError:
            return {
                "error": "radon not installed. Install with: pip install radon"
            }

    def _parse_radon_text(self, output: str) -> Dict[str, Any]:
        """Parse la sortie texte de radon (fallback)."""
        # Parser basique du format texte
        lines = output.splitlines()
        high_complexity = []

        for line in lines:
            if " - " in line and "(" in line:
                # Format: "F 12:0 function_name - A (5)"
                parts = line.split()
                if len(parts) >= 4:
                    try:
                        complexity = int(parts[-1].strip("()"))
                        if complexity > self.complexity_threshold:
                            high_complexity.append({
                                "function": parts[2],
                                "complexity": complexity,
                            })
                    except ValueError:
                        continue

        return {
            "high_complexity_functions": high_complexity,
            "note": "Parsed from text output (radon JSON not available)",
        }

    def _run_ruff(self, target: str, fix: bool = False) -> Dict[str, Any]:
        """Exécute ruff (linter)."""
        path = self.project_root / target

        cmd = ["ruff", "check", str(path)]
        if fix:
            cmd.append("--fix")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(self.project_root),
            )

            # Parser les erreurs
            errors = []
            warnings = []

            for line in result.stdout.splitlines():
                if ": error:" in line.lower():
                    errors.append(line.strip())
                elif ": warning:" in line.lower():
                    warnings.append(line.strip())

            return {
                "target": target,
                "errors": errors,
                "warnings": warnings,
                "total_errors": len(errors),
                "total_warnings": len(warnings),
                "passed": result.returncode == 0,
                "output": result.stdout,
            }

        except FileNotFoundError:
            return {
                "error": "ruff not installed. Install with: pip install ruff"
            }

    def _run_mypy(self, target: str) -> Dict[str, Any]:
        """Exécute mypy (type checking)."""
        path = self.project_root / target

        try:
            result = subprocess.run(
                ["mypy", str(path)],
                capture_output=True,
                text=True,
                timeout=180,
                cwd=str(self.project_root),
            )

            # Parser les erreurs
            errors = []
            for line in result.stdout.splitlines():
                if ": error:" in line:
                    errors.append(line.strip())

            return {
                "target": target,
                "errors": errors,
                "total_errors": len(errors),
                "passed": result.returncode == 0,
                "output": result.stdout,
            }

        except FileNotFoundError:
            return {
                "error": "mypy not installed. Install with: pip install mypy"
            }

    def _run_black(self, target: str, check_only: bool = True) -> Dict[str, Any]:
        """Exécute black (formatter)."""
        path = self.project_root / target

        cmd = ["black", str(path)]
        if check_only:
            cmd.append("--check")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(self.project_root),
            )

            return {
                "target": target,
                "formatted": result.returncode == 0,
                "would_reformat": result.returncode != 0 and check_only,
                "output": result.stdout,
            }

        except FileNotFoundError:
            return {
                "error": "black not installed. Install with: pip install black"
            }

    def analyze_file_comprehensive(self, file_path: str) -> Dict[str, Any]:
        """
        Analyse complète d'un fichier (AST + complexité + linting + typing).

        Args:
            file_path: Fichier à analyser

        Returns:
            Résultats combinés de toutes les analyses
        """
        results = {}

        # AST
        ast_result = self.execute(analysis_type="ast", file_path=file_path)
        if ast_result.is_success:
            results["ast"] = ast_result.output

        # Complexité
        complexity_result = self.execute(analysis_type="complexity", file_path=file_path)
        if complexity_result.is_success:
            results["complexity"] = complexity_result.output

        # Ruff
        ruff_result = self.execute(analysis_type="ruff", file_path=file_path)
        if ruff_result.is_success:
            results["ruff"] = ruff_result.output

        # Mypy
        mypy_result = self.execute(analysis_type="mypy", file_path=file_path)
        if mypy_result.is_success:
            results["mypy"] = mypy_result.output

        # Black
        black_result = self.execute(analysis_type="black", file_path=file_path, check_only=True)
        if black_result.is_success:
            results["black"] = black_result.output

        return results
