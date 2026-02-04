#!/usr/bin/env python3
"""
OSMOSE Deprecation Audit Script
===============================

Scanne le codebase pour identifier et rapporter tous les éléments dépréciés.

Usage:
------
    # Rapport texte (défaut)
    python scripts/audit_deprecated.py

    # Format JSON
    python scripts/audit_deprecated.py --format json

    # Filtrer par type
    python scripts/audit_deprecated.py --kind DEAD_CODE
    python scripts/audit_deprecated.py --kind PHASE_ABANDONED

    # Chemin personnalisé
    python scripts/audit_deprecated.py --path src/knowbase/agents

    # Verbose
    python scripts/audit_deprecated.py -v
"""

import argparse
import ast
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class DeprecationEntry:
    """Une entrée de code déprécié trouvée."""

    file_path: str
    line_number: int
    kind: str
    reason: str
    element_type: str  # 'module', 'function', 'class'
    element_name: str
    alternative: Optional[str] = None
    removal_version: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "file": self.file_path,
            "line": self.line_number,
            "kind": self.kind,
            "reason": self.reason,
            "type": self.element_type,
            "name": self.element_name,
            "alternative": self.alternative,
            "removal_version": self.removal_version,
        }


@dataclass
class AuditReport:
    """Rapport d'audit complet."""

    entries: list[DeprecationEntry] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    files_scanned: int = 0
    files_with_deprecations: int = 0

    def to_dict(self) -> dict:
        by_kind = defaultdict(list)
        for entry in self.entries:
            by_kind[entry.kind].append(entry.to_dict())

        return {
            "summary": {
                "total_deprecated": len(self.entries),
                "files_scanned": self.files_scanned,
                "files_with_deprecations": self.files_with_deprecations,
                "by_kind": {k: len(v) for k, v in by_kind.items()},
            },
            "entries": [e.to_dict() for e in self.entries],
            "errors": self.errors,
        }


class DeprecationVisitor(ast.NodeVisitor):
    """Visiteur AST pour détecter les appels de dépréciation."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.entries: list[DeprecationEntry] = []
        self.current_class: Optional[str] = None
        self.current_function: Optional[str] = None

    def _extract_deprecation_args(
        self, call: ast.Call
    ) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """Extrait kind, reason, alternative, removal_version d'un appel."""
        kind = None
        reason = None
        alternative = None
        removal_version = None

        for keyword in call.keywords:
            if keyword.arg == "kind" and isinstance(keyword.value, ast.Attribute):
                kind = keyword.value.attr
            elif keyword.arg == "reason" and isinstance(keyword.value, ast.Constant):
                reason = keyword.value.value
            elif keyword.arg == "alternative" and isinstance(
                keyword.value, ast.Constant
            ):
                alternative = keyword.value.value
            elif keyword.arg == "removal_version" and isinstance(
                keyword.value, ast.Constant
            ):
                removal_version = keyword.value.value

        # Aussi chercher dans les args positionnels
        if len(call.args) >= 1 and isinstance(call.args[0], ast.Attribute):
            kind = call.args[0].attr
        if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
            reason = call.args[1].value

        return kind, reason, alternative, removal_version

    def visit_Expr(self, node: ast.Expr) -> None:
        """Détecte les appels à deprecated_module()."""
        if isinstance(node.value, ast.Call):
            call = node.value
            func_name = None

            if isinstance(call.func, ast.Name):
                func_name = call.func.id
            elif isinstance(call.func, ast.Attribute):
                func_name = call.func.attr

            if func_name == "deprecated_module":
                kind, reason, alternative, removal_version = (
                    self._extract_deprecation_args(call)
                )

                # Extraire le nom du module depuis le chemin
                module_name = (
                    Path(self.file_path)
                    .stem.replace("\\", ".")
                    .replace("/", ".")
                )

                self.entries.append(
                    DeprecationEntry(
                        file_path=self.file_path,
                        line_number=node.lineno,
                        kind=kind or "UNKNOWN",
                        reason=reason or "No reason provided",
                        element_type="module",
                        element_name=module_name,
                        alternative=alternative,
                        removal_version=removal_version,
                    )
                )

        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Détecte les décorateurs @deprecated sur les fonctions."""
        self._check_decorators(node, "function")
        old_function = self.current_function
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = old_function

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Détecte les décorateurs @deprecated sur les fonctions async."""
        self._check_decorators(node, "function")
        old_function = self.current_function
        self.current_function = node.name
        self.generic_visit(node)
        self.current_function = old_function

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Détecte les décorateurs @deprecated_class sur les classes."""
        self._check_decorators(node, "class")
        old_class = self.current_class
        self.current_class = node.name
        self.generic_visit(node)
        self.current_class = old_class

    def _check_decorators(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, elem_type: str
    ) -> None:
        """Vérifie si un noeud a un décorateur @deprecated."""
        for decorator in node.decorator_list:
            func_name = None

            if isinstance(decorator, ast.Call):
                if isinstance(decorator.func, ast.Name):
                    func_name = decorator.func.id
                elif isinstance(decorator.func, ast.Attribute):
                    func_name = decorator.func.attr

                if func_name in ("deprecated", "deprecated_class"):
                    kind, reason, alternative, removal_version = (
                        self._extract_deprecation_args(decorator)
                    )

                    # Construire le nom qualifié
                    name_parts = []
                    if self.current_class:
                        name_parts.append(self.current_class)
                    name_parts.append(node.name)
                    qualname = ".".join(name_parts)

                    self.entries.append(
                        DeprecationEntry(
                            file_path=self.file_path,
                            line_number=node.lineno,
                            kind=kind or "UNKNOWN",
                            reason=reason or "No reason provided",
                            element_type=elem_type,
                            element_name=qualname,
                            alternative=alternative,
                            removal_version=removal_version,
                        )
                    )

            elif isinstance(decorator, ast.Name):
                if decorator.id in ("deprecated", "deprecated_class"):
                    # Décorateur sans arguments
                    name_parts = []
                    if self.current_class:
                        name_parts.append(self.current_class)
                    name_parts.append(node.name)
                    qualname = ".".join(name_parts)

                    self.entries.append(
                        DeprecationEntry(
                            file_path=self.file_path,
                            line_number=node.lineno,
                            kind="UNKNOWN",
                            reason="No reason provided",
                            element_type=elem_type,
                            element_name=qualname,
                            alternative=None,
                            removal_version=None,
                        )
                    )


def scan_file(file_path: Path, verbose: bool = False) -> tuple[list[DeprecationEntry], Optional[str]]:
    """Scanne un fichier Python pour les dépréciations."""
    try:
        content = file_path.read_text(encoding="utf-8-sig")  # Gérer BOM automatiquement
        tree = ast.parse(content, filename=str(file_path))

        visitor = DeprecationVisitor(str(file_path))
        visitor.visit(tree)

        if verbose and visitor.entries:
            print(f"  Found {len(visitor.entries)} deprecation(s) in {file_path}")

        return visitor.entries, None

    except SyntaxError as e:
        return [], f"Syntax error in {file_path}: {e}"
    except Exception as e:
        return [], f"Error scanning {file_path}: {e}"


def scan_directory(
    base_path: Path,
    kind_filter: Optional[str] = None,
    verbose: bool = False,
) -> AuditReport:
    """Scanne un répertoire récursivement."""
    report = AuditReport()

    python_files = list(base_path.rglob("*.py"))

    # Exclure certains répertoires
    excluded_patterns = [
        "__pycache__",
        ".venv",
        "venv",
        ".git",
        "node_modules",
        ".pytest_cache",
    ]

    python_files = [
        f
        for f in python_files
        if not any(excl in str(f) for excl in excluded_patterns)
    ]

    report.files_scanned = len(python_files)

    if verbose:
        print(f"Scanning {len(python_files)} Python files...")

    files_with_deps = set()

    for file_path in python_files:
        entries, error = scan_file(file_path, verbose)

        if error:
            report.errors.append(error)

        for entry in entries:
            if kind_filter is None or entry.kind == kind_filter:
                report.entries.append(entry)
                files_with_deps.add(str(file_path))

    report.files_with_deprecations = len(files_with_deps)

    # Trier par kind puis par fichier
    report.entries.sort(key=lambda e: (e.kind, e.file_path, e.line_number))

    return report


def format_text_report(report: AuditReport) -> str:
    """Formate le rapport en texte lisible."""
    lines = []
    lines.append("=" * 70)
    lines.append("OSMOSE DEPRECATION AUDIT REPORT")
    lines.append("=" * 70)
    lines.append("")

    # Summary
    lines.append("SUMMARY")
    lines.append("-" * 40)
    lines.append(f"Files scanned:          {report.files_scanned}")
    lines.append(f"Files with deprecations: {report.files_with_deprecations}")
    lines.append(f"Total deprecated items:  {len(report.entries)}")
    lines.append("")

    # By kind
    by_kind = defaultdict(list)
    for entry in report.entries:
        by_kind[entry.kind].append(entry)

    lines.append("BY KIND")
    lines.append("-" * 40)
    for kind in sorted(by_kind.keys()):
        lines.append(f"  {kind}: {len(by_kind[kind])}")
    lines.append("")

    # Details
    for kind in sorted(by_kind.keys()):
        entries = by_kind[kind]
        lines.append("")
        lines.append(f"[{kind}] ({len(entries)} items)")
        lines.append("=" * 70)

        for entry in entries:
            lines.append("")
            lines.append(f"  {entry.element_type.upper()}: {entry.element_name}")
            lines.append(f"  File: {entry.file_path}:{entry.line_number}")
            lines.append(f"  Reason: {entry.reason}")
            if entry.alternative:
                lines.append(f"  Alternative: {entry.alternative}")
            if entry.removal_version:
                lines.append(f"  Removal: {entry.removal_version}")

    # Errors
    if report.errors:
        lines.append("")
        lines.append("ERRORS")
        lines.append("-" * 40)
        for error in report.errors:
            lines.append(f"  ! {error}")

    lines.append("")
    lines.append("=" * 70)

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Audit deprecated code in OSMOSE codebase"
    )
    parser.add_argument(
        "--path",
        type=str,
        default="src/knowbase",
        help="Path to scan (default: src/knowbase)",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--kind",
        type=str,
        choices=["DEAD_CODE", "LEGACY_COMPAT", "EXPERIMENTAL", "PHASE_ABANDONED"],
        help="Filter by deprecation kind",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output",
    )

    args = parser.parse_args()

    # Déterminer le chemin de base
    base_path = Path(args.path)
    if not base_path.exists():
        # Essayer depuis la racine du projet
        script_dir = Path(__file__).parent.parent
        base_path = script_dir / args.path
        if not base_path.exists():
            print(f"Error: Path not found: {args.path}", file=sys.stderr)
            sys.exit(1)

    if args.verbose:
        print(f"Scanning: {base_path.absolute()}")

    report = scan_directory(base_path, kind_filter=args.kind, verbose=args.verbose)

    if args.format == "json":
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_text_report(report))

    # Exit code basé sur les résultats
    if report.errors:
        sys.exit(2)  # Erreurs de parsing
    elif report.entries:
        sys.exit(0)  # Dépréciations trouvées (pas une erreur)
    else:
        sys.exit(0)  # Aucune dépréciation


if __name__ == "__main__":
    main()
