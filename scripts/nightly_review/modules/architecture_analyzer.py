"""
Module Architecture Analyzer - Analyse architecture et patterns.

Fonctionnalités:
- Détection d'anti-patterns
- Analyse de dépendances circulaires
- Vérification principes SOLID
- Détection de God Objects
- Recommandations d'optimisation
- Analyse de la structure en couches
"""
import ast
from pathlib import Path
from typing import Dict, List, Any, Set, Tuple
from collections import defaultdict, deque
import re


class ArchitectureAnalyzer:
    """Analyseur d'architecture et patterns."""

    def __init__(self, project_root: Path):
        """
        Initialise l'analyseur d'architecture.

        Args:
            project_root: Racine du projet
        """
        self.project_root = project_root
        self.src_dir = project_root / "src" / "knowbase"
        self.results = {
            "anti_patterns": [],
            "circular_dependencies": [],
            "god_objects": [],
            "solid_violations": [],
            "performance_issues": [],
            "layer_violations": [],
            "recommendations": []
        }

        # Définition des couches architecturales
        self.layers = {
            "api": ["routers", "main.py"],
            "services": ["services"],
            "db": ["db", "models"],
            "common": ["common", "config"]
        }

    def analyze(self) -> Dict[str, Any]:
        """
        Exécute l'analyse complète d'architecture.

        Returns:
            Résultats de l'analyse
        """
        print("🏗️ Architecture Analyzer - Démarrage analyse...")

        # 1. Analyser les dépendances entre modules
        self._analyze_dependencies()

        # 2. Détecter les God Objects
        self._detect_god_objects()

        # 3. Vérifier la séparation des couches
        self._verify_layer_separation()

        # 4. Détecter les anti-patterns
        self._detect_anti_patterns()

        # 5. Analyser les opportunités de performance
        self._analyze_performance_opportunities()

        # 6. Générer des recommandations
        self._generate_recommendations()

        return {
            "total_issues": self._count_total_issues(),
            "details": self.results,
            "summary": self._generate_summary()
        }

    def _analyze_dependencies(self):
        """Analyse les dépendances entre modules et détecte les cycles."""
        print("  🔗 Analyse des dépendances...")

        # Construire le graphe de dépendances
        dependencies = defaultdict(set)

        python_files = list(self.src_dir.rglob("*.py"))

        for py_file in python_files:
            module_name = self._get_module_name(py_file)

            try:
                with open(py_file, 'r', encoding='utf-8-sig') as f:
                    tree = ast.parse(f.read(), filename=str(py_file))

                # Extraire les imports
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        if node.module and node.module.startswith('knowbase'):
                            imported_module = node.module.split('.')[1] if '.' in node.module else node.module
                            dependencies[module_name].add(imported_module)

            except Exception as e:
                print(f"    ⚠ Erreur analyse {py_file.name}: {e}")

        # Détecter les cycles
        cycles = self._detect_cycles(dependencies)

        for cycle in cycles:
            self.results["circular_dependencies"].append({
                "cycle": " → ".join(cycle),
                "modules": cycle,
                "severity": "high" if len(cycle) > 3 else "medium"
            })

        print(f"    ✓ {len(cycles)} cycles de dépendances détectés")

    def _detect_cycles(self, graph: Dict[str, Set[str]]) -> List[List[str]]:
        """
        Détecte les cycles dans un graphe de dépendances.

        Args:
            graph: Graphe de dépendances

        Returns:
            Liste des cycles détectés
        """
        cycles = []
        visited = set()
        rec_stack = set()

        def dfs(node: str, path: List[str]):
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in graph.get(node, set()):
                if neighbor not in visited:
                    dfs(neighbor, path.copy())
                elif neighbor in rec_stack:
                    # Cycle détecté
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    if cycle not in cycles:
                        cycles.append(cycle)

            rec_stack.remove(node)

        for node in graph:
            if node not in visited:
                dfs(node, [])

        return cycles

    def _detect_god_objects(self):
        """Détecte les God Objects (classes trop grosses)."""
        print("  👑 Détection God Objects...")

        python_files = list(self.src_dir.rglob("*.py"))

        for py_file in python_files:
            try:
                with open(py_file, 'r', encoding='utf-8-sig') as f:
                    content = f.read()
                    tree = ast.parse(content, filename=str(py_file))

                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        # Compter les méthodes
                        methods = [n for n in node.body if isinstance(n, ast.FunctionDef)]
                        num_methods = len(methods)

                        # Compter les lignes de la classe
                        class_lines = len([line for line in content.split('\n')[node.lineno-1:] if line.strip()])

                        # Détecter God Object
                        if num_methods > 20 or class_lines > 500:
                            severity = "critical" if num_methods > 30 else "high"

                            self.results["god_objects"].append({
                                "class_name": node.name,
                                "file": str(py_file.relative_to(self.project_root)),
                                "line": node.lineno,
                                "num_methods": num_methods,
                                "estimated_lines": class_lines,
                                "severity": severity,
                                "recommendation": f"Diviser {node.name} en plusieurs classes responsabilités distinctes"
                            })

            except Exception as e:
                print(f"    ⚠ Erreur analyse {py_file.name}: {e}")

        print(f"    ✓ {len(self.results['god_objects'])} God Objects détectés")

    def _verify_layer_separation(self):
        """Vérifie la séparation des couches architecturales."""
        print("  🏛️ Vérification séparation des couches...")

        violations = []
        python_files = list(self.src_dir.rglob("*.py"))

        for py_file in python_files:
            current_layer = self._identify_layer(py_file)

            if not current_layer:
                continue

            try:
                with open(py_file, 'r', encoding='utf-8-sig') as f:
                    tree = ast.parse(f.read(), filename=str(py_file))

                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        if node.module and node.module.startswith('knowbase'):
                            imported_layer = self._get_layer_from_import(node.module)

                            # Vérifier les violations
                            if self._is_layer_violation(current_layer, imported_layer):
                                violations.append({
                                    "file": str(py_file.relative_to(self.project_root)),
                                    "current_layer": current_layer,
                                    "imports_from": imported_layer,
                                    "violation": f"Layer '{current_layer}' ne devrait pas importer de '{imported_layer}'",
                                    "severity": "medium"
                                })

            except Exception as e:
                print(f"    ⚠ Erreur analyse {py_file.name}: {e}")

        self.results["layer_violations"] = violations
        print(f"    ✓ {len(violations)} violations de couches détectées")

    def _detect_anti_patterns(self):
        """Détecte les anti-patterns courants."""
        print("  🚫 Détection anti-patterns...")

        python_files = list(self.src_dir.rglob("*.py"))

        for py_file in python_files:
            try:
                with open(py_file, 'r', encoding='utf-8-sig') as f:
                    content = f.read()
                    tree = ast.parse(content, filename=str(py_file))

                # 1. Singleton Pattern (souvent anti-pattern en Python)
                self._detect_singleton(py_file, tree, content)

                # 2. Catch-all Exception handlers
                self._detect_bare_except(py_file, tree)

                # 3. String concatenation in loops
                self._detect_string_concat_in_loops(py_file, tree)

                # 4. Mutable default arguments
                self._detect_mutable_defaults(py_file, tree)

            except Exception as e:
                print(f"    ⚠ Erreur analyse {py_file.name}: {e}")

        print(f"    ✓ {len(self.results['anti_patterns'])} anti-patterns détectés")

    def _detect_singleton(self, py_file: Path, tree: ast.AST, content: str):
        """Détecte le pattern Singleton."""
        if '__new__' in content and 'instance' in content.lower():
            self.results["anti_patterns"].append({
                "type": "Singleton Pattern",
                "file": str(py_file.relative_to(self.project_root)),
                "severity": "medium",
                "description": "Singleton détecté - considérer dependency injection à la place",
                "recommendation": "Utiliser FastAPI Depends() pour injection de dépendances"
            })

    def _detect_bare_except(self, py_file: Path, tree: ast.AST):
        """Détecte les bare except (catch-all)."""
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:  # bare except
                    self.results["anti_patterns"].append({
                        "type": "Bare Except",
                        "file": str(py_file.relative_to(self.project_root)),
                        "line": node.lineno,
                        "severity": "low",
                        "description": "Catch-all exception - masque les erreurs potentielles",
                        "recommendation": "Spécifier les exceptions à capturer (except ValueError, TypeError:)"
                    })

    def _detect_string_concat_in_loops(self, py_file: Path, tree: ast.AST):
        """Détecte la concaténation de strings dans les boucles."""
        for node in ast.walk(tree):
            if isinstance(node, (ast.For, ast.While)):
                # Chercher des += sur strings dans le corps de la boucle
                for child in ast.walk(node):
                    if isinstance(child, ast.AugAssign) and isinstance(child.op, ast.Add):
                        self.results["anti_patterns"].append({
                            "type": "String Concatenation in Loop",
                            "file": str(py_file.relative_to(self.project_root)),
                            "line": node.lineno,
                            "severity": "low",
                            "description": "Concaténation de strings dans une boucle - inefficace",
                            "recommendation": "Utiliser list.append() puis ''.join()"
                        })
                        break

    def _detect_mutable_defaults(self, py_file: Path, tree: ast.AST):
        """Détecte les arguments par défaut mutables."""
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                for default in node.args.defaults:
                    if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                        self.results["anti_patterns"].append({
                            "type": "Mutable Default Argument",
                            "file": str(py_file.relative_to(self.project_root)),
                            "line": node.lineno,
                            "function": node.name,
                            "severity": "medium",
                            "description": "Argument par défaut mutable - comportement inattendu",
                            "recommendation": "Utiliser None comme défaut et créer l'objet dans la fonction"
                        })

    def _analyze_performance_opportunities(self):
        """Analyse les opportunités d'optimisation de performance."""
        print("  ⚡ Analyse opportunités de performance...")

        python_files = list(self.src_dir.rglob("*.py"))

        for py_file in python_files:
            try:
                with open(py_file, 'r', encoding='utf-8-sig') as f:
                    content = f.read()
                    tree = ast.parse(content, filename=str(py_file))

                # 1. Détection de requêtes potentielles N+1
                self._detect_n_plus_one(py_file, tree, content)

                # 2. Imports synchrones lourds
                self._detect_heavy_imports(py_file, tree)

                # 3. Opportunités de caching
                self._detect_caching_opportunities(py_file, tree, content)

            except Exception as e:
                print(f"    ⚠ Erreur analyse {py_file.name}: {e}")

        print(f"    ✓ {len(self.results['performance_issues'])} opportunités détectées")

    def _detect_n_plus_one(self, py_file: Path, tree: ast.AST, content: str):
        """Détecte les potentielles requêtes N+1."""
        # Pattern: boucle for avec appel à une fonction qui semble faire une requête DB
        for node in ast.walk(tree):
            if isinstance(node, ast.For):
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        func_name = ""
                        if isinstance(child.func, ast.Name):
                            func_name = child.func.id
                        elif isinstance(child.func, ast.Attribute):
                            func_name = child.func.attr

                        # Mots-clés suspects
                        if any(keyword in func_name.lower() for keyword in ['get', 'find', 'fetch', 'query', 'select']):
                            self.results["performance_issues"].append({
                                "type": "Potential N+1 Query",
                                "file": str(py_file.relative_to(self.project_root)),
                                "line": node.lineno,
                                "severity": "high",
                                "description": f"Possible N+1: appel à '{func_name}' dans une boucle",
                                "recommendation": "Utiliser batch queries ou prefetch/eager loading"
                            })
                            break

    def _detect_heavy_imports(self, py_file: Path, tree: ast.AST):
        """Détecte les imports lourds qui devraient être lazy."""
        heavy_libraries = ['pandas', 'numpy', 'torch', 'tensorflow', 'matplotlib']

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if any(lib in alias.name for lib in heavy_libraries):
                            # Vérifier si c'est un import top-level
                            if node.col_offset == 0:
                                self.results["performance_issues"].append({
                                    "type": "Heavy Top-Level Import",
                                    "file": str(py_file.relative_to(self.project_root)),
                                    "line": node.lineno,
                                    "library": alias.name,
                                    "severity": "low",
                                    "description": f"Import lourd '{alias.name}' au top-level",
                                    "recommendation": "Considérer lazy import (dans la fonction qui l'utilise)"
                                })

    def _detect_caching_opportunities(self, py_file: Path, tree: ast.AST, content: str):
        """Détecte les opportunités de caching."""
        # Chercher des fonctions sans @lru_cache qui semblent pures
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # Vérifier si déjà @lru_cache ou @cache
                has_cache_decorator = any(
                    isinstance(d, ast.Name) and d.id in ['lru_cache', 'cache']
                    for d in node.decorator_list
                )

                if not has_cache_decorator:
                    # Fonction pure potentielle (pas de self, pas d'effets de bord évidents)
                    is_method = len(node.args.args) > 0 and node.args.args[0].arg == 'self'

                    if not is_method and self._looks_like_pure_function(node):
                        self.results["performance_issues"].append({
                            "type": "Caching Opportunity",
                            "file": str(py_file.relative_to(self.project_root)),
                            "line": node.lineno,
                            "function": node.name,
                            "severity": "low",
                            "description": f"Fonction '{node.name}' pourrait bénéficier de @lru_cache",
                            "recommendation": "Ajouter @functools.lru_cache() si la fonction est pure"
                        })

    def _looks_like_pure_function(self, node: ast.FunctionDef) -> bool:
        """Détermine si une fonction semble pure (candidate pour caching)."""
        # Heuristique simple: pas d'appels à print, open, write, etc.
        impure_keywords = ['print', 'open', 'write', 'save', 'delete', 'update', 'insert']

        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name):
                    if any(keyword in child.func.id.lower() for keyword in impure_keywords):
                        return False
                elif isinstance(child.func, ast.Attribute):
                    if any(keyword in child.func.attr.lower() for keyword in impure_keywords):
                        return False

        return True

    def _generate_recommendations(self):
        """Génère des recommandations d'amélioration."""
        print("  💡 Génération recommandations...")

        recommendations = []

        # Recommandation basée sur God Objects
        if len(self.results["god_objects"]) > 0:
            recommendations.append({
                "category": "Architecture",
                "priority": "high",
                "title": "Refactoring de God Objects",
                "description": f"{len(self.results['god_objects'])} classes trop volumineuses détectées",
                "action": "Appliquer le principe Single Responsibility (SRP)",
                "impact": "Améliore maintenabilité et testabilité"
            })

        # Recommandation basée sur cycles
        if len(self.results["circular_dependencies"]) > 0:
            recommendations.append({
                "category": "Architecture",
                "priority": "critical",
                "title": "Résolution de dépendances circulaires",
                "description": f"{len(self.results['circular_dependencies'])} cycles détectés",
                "action": "Introduire des interfaces ou inverser les dépendances",
                "impact": "Essentiel pour éviter les imports circulaires et améliorer la modularité"
            })

        # Recommandation basée sur violations de couches
        if len(self.results["layer_violations"]) > 3:
            recommendations.append({
                "category": "Architecture",
                "priority": "high",
                "title": "Renforcer la séparation des couches",
                "description": f"{len(self.results['layer_violations'])} violations détectées",
                "action": "Respecter l'architecture en couches (API → Services → DB)",
                "impact": "Améliore la testabilité et facilite les changements futurs"
            })

        # Recommandation basée sur performance
        n_plus_one_count = len([p for p in self.results["performance_issues"] if p["type"] == "Potential N+1 Query"])
        if n_plus_one_count > 0:
            recommendations.append({
                "category": "Performance",
                "priority": "high",
                "title": "Optimiser les requêtes de base de données",
                "description": f"{n_plus_one_count} requêtes N+1 potentielles",
                "action": "Utiliser batch loading ou eager loading",
                "impact": "Peut réduire le temps de réponse de 10x à 100x"
            })

        self.results["recommendations"] = recommendations
        print(f"    ✓ {len(recommendations)} recommandations générées")

    def _get_module_name(self, file_path: Path) -> str:
        """Extrait le nom du module depuis un chemin de fichier."""
        rel_path = file_path.relative_to(self.src_dir)
        parts = rel_path.parts

        if len(parts) > 0:
            return parts[0]
        return "unknown"

    def _identify_layer(self, file_path: Path) -> str:
        """Identifie la couche architecturale d'un fichier."""
        rel_path = str(file_path.relative_to(self.src_dir))

        for layer, patterns in self.layers.items():
            if any(pattern in rel_path for pattern in patterns):
                return layer

        return "unknown"

    def _get_layer_from_import(self, import_path: str) -> str:
        """Extrait la couche depuis un chemin d'import."""
        parts = import_path.split('.')

        if len(parts) > 1:
            module = parts[1]
            for layer, patterns in self.layers.items():
                if module in patterns:
                    return layer

        return "unknown"

    def _is_layer_violation(self, current: str, imported: str) -> bool:
        """Détermine si un import viole la séparation des couches."""
        # Règles:
        # - DB ne devrait importer de personne (sauf common)
        # - Services peut importer DB et common
        # - API peut importer Services, DB (via services), common

        if current == "db" and imported not in ["common", "unknown"]:
            return True

        if current == "services" and imported == "api":
            return True

        return False

    def _count_total_issues(self) -> int:
        """Compte le nombre total de problèmes."""
        return (
            len(self.results["anti_patterns"]) +
            len(self.results["circular_dependencies"]) +
            len(self.results["god_objects"]) +
            len(self.results["layer_violations"]) +
            len(self.results["performance_issues"])
        )

    def _generate_summary(self) -> Dict[str, Any]:
        """Génère un résumé de l'analyse."""
        return {
            "god_objects": len(self.results["god_objects"]),
            "circular_dependencies": len(self.results["circular_dependencies"]),
            "anti_patterns": len(self.results["anti_patterns"]),
            "layer_violations": len(self.results["layer_violations"]),
            "performance_opportunities": len(self.results["performance_issues"]),
            "high_priority_recommendations": len([r for r in self.results["recommendations"] if r["priority"] in ["critical", "high"]])
        }


def run_architecture_analysis(project_root: Path) -> Dict[str, Any]:
    """
    Lance l'analyse d'architecture.

    Args:
        project_root: Racine du projet

    Returns:
        Résultats de l'analyse
    """
    analyzer = ArchitectureAnalyzer(project_root)
    return analyzer.analyze()
