"""
Module Claude Analyzer - Analyse intelligente avec Claude.

Utilise l'API Anthropic pour des analyses contextuelles profondes
avec différents personas d'experts.
"""

import os
import json
from pathlib import Path
from typing import Dict, Any, List
from anthropic import Anthropic


class ClaudeAnalyzer:
    """Analyseur intelligent utilisant Claude comme expert."""

    def __init__(self, project_root: Path):
        """
        Initialise l'analyseur Claude.

        Args:
            project_root: Racine du projet
        """
        self.project_root = project_root
        self.src_dir = project_root / "src" / "knowbase"

        # Initialiser le client Anthropic
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY non définie dans l'environnement")

        self.client = Anthropic(api_key=api_key)
        self.model = "claude-sonnet-4-20250514"  # Modèle le plus récent

        # Context du projet
        self.project_context = self._build_project_context()

    def _build_project_context(self) -> str:
        """Construit le contexte du projet pour Claude."""
        return """
        Projet: SAP Knowledge Base (SAP KB)

        Description Générale:
        - Système RAG avancé (Retrieval-Augmented Generation) pour base de connaissances SAP
        - Architecture hybride : Vector Search (Qdrant) + Knowledge Graph (Neo4j)
        - Ingestion intelligente de documents avec extraction d'entités, relations et faits
        - Recherche sémantique multi-modale + génération de réponses contextuelles
        - Support multi-provider LLM (OpenAI, Anthropic, Mistral)

        Stack Technique:
        - Backend: Python 3.11, FastAPI, Pydantic, SQLAlchemy
        - Embeddings: OpenAI text-embedding-3-small
        - Vector DB: Qdrant (stockage chunks avec embeddings)
        - Knowledge Graph: Neo4j (entités, relations, faits)
        - Cache: Redis (queue ingestion, cache recherches)
        - Registry: SQLite (types d'entités dynamiques)
        - LLM: Claude Sonnet 4, GPT-4, Mistral
        - Frontend: Next.js 14, TypeScript, React
        - Infrastructure: Docker Compose (7 services)

        Architecture en Couches:
        - API Layer (routers, schemas)
        - Service Layer (business logic, orchestration)
        - Data Layer (Qdrant, Neo4j, Redis, SQLite)
        - Common Layer (clients, config, utils)

        ARCHITECTURE KNOWLEDGE GRAPH (Partie Critique):

        1. Entity System (Entités):
           - Extraction automatique d'entités depuis les documents
           - Types d'entités dynamiques (registry SQLite + Neo4j)
           - Normalisation des entités (noms canoniques, synonymes)
           - Catégories: SOLUTION, TECHNOLOGY, FEATURE, CONCEPT, PRODUCT, etc.
           - Chaque entité a: name, canonical_name, entity_type, metadata

        2. Entity Types Registry:
           - Système de types d'entités auto-apprenant
           - Registry SQLite: définitions, contraintes, règles de validation
           - Synchronisation bidirectionnelle SQLite ↔ Neo4j
           - Évolution dynamique: ajout de nouveaux types à la volée
           - Contraintes: properties requises, format, cardinalité

        3. Relations entre Entités:
           - Relations typées et orientées: (Entity)-[RELATION]->(Entity)
           - Types de relations: IMPLEMENTS, USES, REPLACES, INTEGRATES_WITH, etc.
           - Relations extraites depuis le contexte des documents
           - Pondération des relations (strength, confidence)

        4. Facts (Faits):
           - Triplets RDF-like: (Entity, Predicate, Object)
           - Faits extraits depuis le texte avec vérification LLM
           - Stockage Neo4j avec metadata (source, confidence, date)
           - Exemples: "SAP S/4HANA" -[RUNS_ON]-> "SAP HANA Database"

        5. Relation Documents ↔ Entities:
           - Chaque chunk vectorisé est lié aux entités qu'il mentionne
           - Mapping Qdrant (chunk ID) ↔ Neo4j (entity nodes)
           - Permet recherche hybride: similarité vectorielle + graph traversal

        6. Pipeline d'Ingestion (3 phases parallèles):
           Phase 1: Chunking + Embeddings → Qdrant
           Phase 2: Entity Extraction + Normalization → Neo4j
           Phase 3: Relation Extraction + Fact Extraction → Neo4j

        7. Recherche Hybride:
           - Recherche vectorielle Qdrant (similarité sémantique)
           - Enrichissement via Neo4j (entités liées, relations, contexte étendu)
           - Expansion de requête via le graph (entités similaires, relations)
           - Génération de réponse LLM avec contexte enrichi (chunks + graph)

        8. Dynamic Type Learning:
           - Détection automatique de nouveaux types d'entités
           - Proposition à l'utilisateur via UI
           - Validation et ajout au registry
           - Reclassification rétroactive si nécessaire

        Points d'Architecture Importants:
        - Séparation claire Vector DB (Qdrant) vs Graph DB (Neo4j)
        - Synchronisation asynchrone via Redis queues
        - Transaction management pour cohérence SQLite ↔ Neo4j
        - Caching intelligent des résultats de graph traversal
        - API REST + WebSocket pour updates temps réel

        Patterns Attendus:
        - Repository pattern pour accès données (Qdrant, Neo4j)
        - Service layer pour orchestration vector + graph
        - Factory pattern pour création entités/relations
        - Observer pattern pour synchronisation registry
        - Strategy pattern pour différents types d'extraction
        """

    def analyze_code_review(
        self, files: List[Path], max_files: int = 20
    ) -> Dict[str, Any]:
        """
        Analyse de code review avec Claude comme expert.

        Args:
            files: Liste de fichiers Python à analyser
            max_files: Nombre max de fichiers à analyser en détail

        Returns:
            Résultats de l'analyse
        """
        print("  🤖 Analyse Code Review avec Claude...")

        # Sélectionner les fichiers les plus importants
        important_files = self._select_important_files(files, max_files)

        results = {
            "total_files_analyzed": len(important_files),
            "issues": [],
            "suggestions": [],
            "refactoring_opportunities": [],
        }

        for py_file in important_files:
            try:
                with open(py_file, "r", encoding="utf-8-sig") as f:
                    code_content = f.read()

                # Limiter la taille du code (max 10k caractères par fichier)
                if len(code_content) > 10000:
                    code_content = code_content[:10000] + "\n\n... [tronqué]"

                file_analysis = self._analyze_file_with_claude(
                    py_file, code_content, persona="code_reviewer"
                )

                if file_analysis:
                    results["issues"].extend(file_analysis.get("issues", []))
                    results["suggestions"].extend(file_analysis.get("suggestions", []))
                    results["refactoring_opportunities"].extend(
                        file_analysis.get("refactoring_opportunities", [])
                    )

                print(f"    ✓ Analysé: {py_file.name}")

            except Exception as e:
                print(f"    ⚠ Erreur analyse {py_file.name}: {e}")

        return results

    def analyze_architecture(self, files: List[Path]) -> Dict[str, Any]:
        """
        Analyse architecturale avec Claude comme architecte senior.

        Args:
            files: Liste de fichiers Python à analyser

        Returns:
            Résultats de l'analyse architecturale
        """
        print("  🏗️ Analyse Architecture avec Claude Architecte...")

        # Analyser la structure globale
        structure_analysis = self._analyze_project_structure(files)

        # Analyser les patterns et anti-patterns
        pattern_analysis = self._analyze_patterns(files[:15])  # Top 15 fichiers

        return {
            "structure_analysis": structure_analysis,
            "pattern_analysis": pattern_analysis,
            "architectural_recommendations": structure_analysis.get(
                "recommendations", []
            ),
        }

    def analyze_tests(
        self, src_files: List[Path], test_files: List[Path]
    ) -> Dict[str, Any]:
        """
        Analyse des tests avec Claude comme expert QA.

        Args:
            src_files: Fichiers source
            test_files: Fichiers de tests

        Returns:
            Résultats de l'analyse des tests
        """
        print("  🧪 Analyse Tests avec Claude QA Expert...")

        results = {
            "test_quality_issues": [],
            "missing_test_suggestions": [],
            "test_improvement_recommendations": [],
        }

        # Analyser la qualité des tests existants
        for test_file in test_files[:10]:  # Limiter à 10 fichiers de tests
            try:
                with open(test_file, "r", encoding="utf-8-sig") as f:
                    test_content = f.read()

                if len(test_content) > 8000:
                    test_content = test_content[:8000] + "\n... [tronqué]"

                test_analysis = self._analyze_test_file_with_claude(
                    test_file, test_content
                )

                if test_analysis:
                    results["test_quality_issues"].extend(
                        test_analysis.get("quality_issues", [])
                    )
                    results["test_improvement_recommendations"].extend(
                        test_analysis.get("improvements", [])
                    )

                print(f"    ✓ Test analysé: {test_file.name}")

            except Exception as e:
                print(f"    ⚠ Erreur analyse test {test_file.name}: {e}")

        # Suggérer des tests manquants
        missing_tests = self._suggest_missing_tests(src_files[:10], test_files)
        results["missing_test_suggestions"] = missing_tests

        return results

    def _analyze_file_with_claude(
        self, file_path: Path, code_content: str, persona: str = "code_reviewer"
    ) -> Dict[str, Any]:
        """Analyse un fichier avec Claude selon un persona."""

        relative_path = file_path.relative_to(self.project_root)

        prompts = {
            "code_reviewer": f"""Tu es un expert en code review senior spécialisé en Python et FastAPI.

Contexte du projet:
{self.project_context}

Fichier à analyser: {relative_path}

```python
{code_content}
```

Analyse ce fichier et identifie:
1. **Issues critiques** : Bugs potentiels, problèmes de sécurité, erreurs logiques
2. **Suggestions d'amélioration** : Lisibilité, maintenabilité, performance
3. **Opportunités de refactoring** : Code dupliqué, fonctions trop longues, responsabilités mal définies

Réponds UNIQUEMENT en JSON strict (pas de markdown) avec cette structure:
{{
  "issues": [
    {{
      "severity": "critical|high|medium|low",
      "type": "bug|security|logic|performance",
      "line": <numéro de ligne si identifiable>,
      "description": "Description claire du problème",
      "recommendation": "Solution concrète avec exemple de code si pertinent"
    }}
  ],
  "suggestions": [
    {{
      "category": "readability|maintainability|performance",
      "line": <numéro de ligne>,
      "description": "Suggestion d'amélioration",
      "example": "Exemple de code amélioré"
    }}
  ],
  "refactoring_opportunities": [
    {{
      "type": "extract_function|split_class|introduce_pattern",
      "description": "Opportunité de refactoring",
      "benefit": "Bénéfice attendu"
    }}
  ]
}}"""
        }

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[
                    {
                        "role": "user",
                        "content": prompts.get(persona, prompts["code_reviewer"]),
                    }
                ],
            )

            # Extraire le contenu JSON
            content = response.content[0].text.strip()

            # Nettoyer les balises markdown si présentes
            if content.startswith("```json"):
                content = content.replace("```json", "").replace("```", "").strip()
            elif content.startswith("```"):
                content = content.replace("```", "").strip()

            result = json.loads(content)

            # Ajouter le fichier à chaque élément
            for issue in result.get("issues", []):
                issue["file"] = str(relative_path)
            for suggestion in result.get("suggestions", []):
                suggestion["file"] = str(relative_path)
            for refactor in result.get("refactoring_opportunities", []):
                refactor["file"] = str(relative_path)

            return result

        except json.JSONDecodeError as e:
            print(f"    ⚠ Erreur parsing JSON: {e}")
            print(f"    Réponse Claude: {content[:200]}...")
            return None
        except Exception as e:
            print(f"    ⚠ Erreur API Claude: {e}")
            return None

    def _analyze_project_structure(self, files: List[Path]) -> Dict[str, Any]:
        """Analyse la structure globale du projet."""

        # Construire un aperçu de la structure
        structure_overview = self._build_structure_overview(files)

        prompt = f"""Tu es un architecte logiciel senior expert en Python, FastAPI et architecture RAG.

Contexte du projet:
{self.project_context}

Structure du projet:
{structure_overview}

Analyse cette architecture et réponds en JSON strict:
{{
  "strengths": ["Point fort 1", "Point fort 2"],
  "weaknesses": ["Faiblesse 1", "Faiblesse 2"],
  "architectural_issues": [
    {{
      "severity": "critical|high|medium",
      "type": "coupling|cohesion|layering|scalability",
      "description": "Description du problème",
      "impact": "Impact sur le système"
    }}
  ],
  "recommendations": [
    {{
      "priority": "critical|high|medium|low",
      "category": "architecture|design|performance",
      "title": "Titre de la recommandation",
      "description": "Description détaillée",
      "action": "Action concrète à prendre",
      "expected_benefit": "Bénéfice attendu"
    }}
  ]
}}"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=3072,
                messages=[{"role": "user", "content": prompt}],
            )

            content = response.content[0].text.strip()
            if content.startswith("```json"):
                content = content.replace("```json", "").replace("```", "").strip()
            elif content.startswith("```"):
                content = content.replace("```", "").strip()

            return json.loads(content)

        except Exception as e:
            print(f"    ⚠ Erreur analyse structure: {e}")
            return {
                "strengths": [],
                "weaknesses": [],
                "architectural_issues": [],
                "recommendations": [],
            }

    def _analyze_patterns(self, files: List[Path]) -> Dict[str, Any]:
        """Analyse les patterns et anti-patterns."""

        # Collecter des extraits de code représentatifs
        code_samples = []
        for py_file in files[:10]:
            try:
                with open(py_file, "r", encoding="utf-8-sig") as f:
                    content = f.read()
                    if len(content) > 2000:
                        content = content[:2000]
                    code_samples.append(
                        f"### {py_file.name}\n```python\n{content}\n```"
                    )
            except:
                pass

        combined_samples = "\n\n".join(code_samples)

        prompt = f"""Tu es un expert en design patterns et clean code.

Contexte: {self.project_context}

Voici des extraits de code du projet:

{combined_samples}

Identifie les patterns et anti-patterns. Réponds en JSON strict:
{{
  "patterns_detected": [
    {{
      "pattern": "Factory|Singleton|Strategy|Repository|etc",
      "location": "Nom de fichier",
      "quality": "well-implemented|needs-improvement|misused",
      "notes": "Commentaires"
    }}
  ],
  "anti_patterns": [
    {{
      "type": "God Object|Spaghetti Code|Magic Numbers|etc",
      "location": "Fichier",
      "severity": "critical|high|medium|low",
      "description": "Description",
      "fix": "Comment corriger"
    }}
  ]
}}"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )

            content = response.content[0].text.strip()
            if content.startswith("```json"):
                content = content.replace("```json", "").replace("```", "").strip()
            elif content.startswith("```"):
                content = content.replace("```", "").strip()

            return json.loads(content)

        except Exception as e:
            print(f"    ⚠ Erreur analyse patterns: {e}")
            return {"patterns_detected": [], "anti_patterns": []}

    def _analyze_test_file_with_claude(
        self, test_file: Path, test_content: str
    ) -> Dict[str, Any]:
        """Analyse un fichier de test avec Claude."""

        relative_path = test_file.relative_to(self.project_root)

        prompt = f"""Tu es un expert QA et testing senior.

Contexte: {self.project_context}

Fichier de test: {relative_path}

```python
{test_content}
```

Analyse ce fichier de test et réponds en JSON strict:
{{
  "quality_issues": [
    {{
      "severity": "high|medium|low",
      "type": "coverage|assertion|setup|isolation",
      "description": "Problème identifié",
      "recommendation": "Comment améliorer"
    }}
  ],
  "improvements": [
    {{
      "category": "readability|maintainability|coverage",
      "description": "Amélioration suggérée",
      "example": "Exemple de code"
    }}
  ]
}}"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            )

            content = response.content[0].text.strip()
            if content.startswith("```json"):
                content = content.replace("```json", "").replace("```", "").strip()
            elif content.startswith("```"):
                content = content.replace("```", "").strip()

            result = json.loads(content)

            # Ajouter le fichier
            for issue in result.get("quality_issues", []):
                issue["file"] = str(relative_path)
            for improvement in result.get("improvements", []):
                improvement["file"] = str(relative_path)

            return result

        except Exception as e:
            print(f"    ⚠ Erreur analyse test: {e}")
            return {"quality_issues": [], "improvements": []}

    def _suggest_missing_tests(
        self, src_files: List[Path], test_files: List[Path]
    ) -> List[Dict[str, Any]]:
        """Suggère des tests manquants."""

        # Lister les fichiers sources sans tests correspondants
        tested_modules = {t.stem.replace("test_", "") for t in test_files}
        untested_files = [
            f
            for f in src_files
            if f.stem not in tested_modules and f.stem != "__init__"
        ]

        suggestions = []

        for src_file in untested_files[:5]:  # Limiter à 5 suggestions
            try:
                with open(src_file, "r", encoding="utf-8-sig") as f:
                    content = f.read()
                    if len(content) > 3000:
                        content = content[:3000]

                relative_path = src_file.relative_to(self.project_root)

                prompt = f"""Tu es un expert en testing Python.

Contexte: {self.project_context}

Fichier source sans tests: {relative_path}

```python
{content}
```

Suggère les tests manquants les plus importants. Réponds en JSON strict:
{{
  "missing_tests": [
    {{
      "function": "Nom de la fonction à tester",
      "priority": "critical|high|medium",
      "test_scenarios": ["Scénario 1", "Scénario 2"],
      "rationale": "Pourquoi ce test est important"
    }}
  ]
}}"""

                response = self.client.messages.create(
                    model=self.model,
                    max_tokens=1536,
                    messages=[{"role": "user", "content": prompt}],
                )

                content_response = response.content[0].text.strip()
                if content_response.startswith("```json"):
                    content_response = (
                        content_response.replace("```json", "")
                        .replace("```", "")
                        .strip()
                    )
                elif content_response.startswith("```"):
                    content_response = content_response.replace("```", "").strip()

                result = json.loads(content_response)

                for test in result.get("missing_tests", []):
                    test["file"] = str(relative_path)
                    suggestions.append(test)

            except Exception as e:
                print(f"    ⚠ Erreur suggestion tests {src_file.name}: {e}")

        return suggestions

    def _select_important_files(self, files: List[Path], max_files: int) -> List[Path]:
        """Sélectionne les fichiers les plus importants à analyser."""

        # Priorité aux fichiers dans certains répertoires
        priority_dirs = ["api", "routers", "services", "ingestion", "pipelines"]

        important = []
        others = []

        for f in files:
            if any(pdir in str(f) for pdir in priority_dirs):
                important.append(f)
            else:
                others.append(f)

        # Trier par taille (plus gros = plus important)
        important.sort(key=lambda f: f.stat().st_size, reverse=True)
        others.sort(key=lambda f: f.stat().st_size, reverse=True)

        return (important + others)[:max_files]

    def _build_structure_overview(self, files: List[Path]) -> str:
        """Construit un aperçu de la structure du projet."""

        from collections import defaultdict

        structure = defaultdict(list)

        for f in files:
            try:
                relative = f.relative_to(self.src_dir)
                parts = relative.parts

                if len(parts) > 1:
                    category = parts[0]
                    structure[category].append(parts[-1])
            except:
                pass

        overview = []
        for category, files_list in sorted(structure.items()):
            overview.append(f"- {category}/ ({len(files_list)} fichiers)")
            for fname in sorted(files_list)[:5]:  # Top 5 par catégorie
                overview.append(f"  - {fname}")
            if len(files_list) > 5:
                overview.append(f"  - ... et {len(files_list) - 5} autres")

        return "\n".join(overview)
