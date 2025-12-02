"""
Claude Code CLI Wrapper avec tracing LangSmith.

Ce wrapper permet d'utiliser Claude Code CLI (avec OAuth/abonnement Pro)
tout en tracant les appels vers LangSmith pour le monitoring.
"""
import subprocess
import json
import os
import time
from typing import Optional, Dict, Any, List
from datetime import datetime
from pathlib import Path

# LangSmith SDK pour tracing manuel
try:
    from langsmith import Client as LangSmithClient
    from langsmith.run_trees import RunTree
    LANGSMITH_AVAILABLE = True
except ImportError:
    LANGSMITH_AVAILABLE = False
    LangSmithClient = None
    RunTree = None


class ClaudeCodeWrapper:
    """
    Wrapper pour Claude Code CLI avec tracing LangSmith.

    Utilise l'authentification OAuth de Claude Code (via ~/.claude/)
    et trace tous les appels vers LangSmith.
    """

    def __init__(
        self,
        project_name: str = "knowwhere-agents",
        langsmith_api_key: Optional[str] = None,
        enable_tracing: bool = True,
        working_directory: str = "/app",
    ):
        """
        Args:
            project_name: Nom du projet LangSmith
            langsmith_api_key: API key LangSmith (ou via env LANGSMITH_API_KEY)
            enable_tracing: Activer le tracing LangSmith
            working_directory: Repertoire de travail pour Claude Code
        """
        self.project_name = project_name
        self.working_directory = working_directory
        self.enable_tracing = enable_tracing and LANGSMITH_AVAILABLE

        # Initialiser LangSmith client si disponible
        self.langsmith_client = None
        if self.enable_tracing:
            api_key = langsmith_api_key or os.environ.get("LANGSMITH_API_KEY")
            if api_key:
                try:
                    self.langsmith_client = LangSmithClient(api_key=api_key)
                    print(f"[ClaudeCodeWrapper] LangSmith tracing actif pour projet: {project_name}")
                except Exception as e:
                    print(f"[ClaudeCodeWrapper] Erreur init LangSmith: {e}")
                    self.langsmith_client = None

        # Verifier que Claude Code CLI est disponible
        self._verify_claude_cli()

    def _verify_claude_cli(self) -> bool:
        """Verifie que Claude Code CLI est installe et accessible."""
        try:
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True,
                timeout=10,
            )
            if result.returncode == 0:
                version = result.stdout.decode().strip()
                print(f"[ClaudeCodeWrapper] Claude CLI disponible: {version}")
                return True
            else:
                print("[ClaudeCodeWrapper] ERREUR: Claude CLI non fonctionnel")
                return False
        except FileNotFoundError:
            print("[ClaudeCodeWrapper] ERREUR: Claude CLI non trouve (installer avec: npm install -g @anthropic-ai/claude-code)")
            return False
        except Exception as e:
            print(f"[ClaudeCodeWrapper] ERREUR verification CLI: {e}")
            return False

    def execute_task(
        self,
        task_description: str,
        task_id: str,
        context: Optional[str] = None,
        allowed_tools: Optional[List[str]] = None,
        timeout_seconds: int = 300,
        parent_run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute une tache via Claude Code CLI.

        Args:
            task_description: Description detaillee de la tache
            task_id: ID unique de la tache (pour tracing)
            context: Contexte additionnel (fichiers, code, etc.)
            allowed_tools: Liste des tools autorises (Read, Write, Edit, Bash, etc.)
            timeout_seconds: Timeout en secondes
            parent_run_id: ID du run parent pour hierarchie LangSmith

        Returns:
            Dict avec status, output, files_modified, duration, etc.
        """
        start_time = time.time()

        # Construire le prompt complet
        full_prompt = self._build_prompt(task_description, context, allowed_tools)

        # Creer le run LangSmith
        run_tree = None
        if self.langsmith_client:
            run_tree = self._create_langsmith_run(
                task_id=task_id,
                prompt=full_prompt,
                parent_run_id=parent_run_id,
            )

        try:
            # Executer Claude Code CLI
            result = self._execute_claude_cli(full_prompt, timeout_seconds)

            duration = time.time() - start_time

            # Parser la reponse
            output = {
                "status": "success" if result["returncode"] == 0 else "failed",
                "task_id": task_id,
                "output": result["stdout"],
                "error": result["stderr"] if result["returncode"] != 0 else None,
                "returncode": result["returncode"],
                "duration_seconds": duration,
                "timestamp": datetime.now().isoformat(),
            }

            # Mettre a jour LangSmith
            if run_tree:
                self._complete_langsmith_run(
                    run_tree,
                    output=output,
                    error=result["stderr"] if result["returncode"] != 0 else None,
                )

            return output

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            output = {
                "status": "timeout",
                "task_id": task_id,
                "output": None,
                "error": f"Task timed out after {timeout_seconds}s",
                "duration_seconds": duration,
                "timestamp": datetime.now().isoformat(),
            }

            if run_tree:
                self._complete_langsmith_run(run_tree, output=output, error="Timeout")

            return output

        except Exception as e:
            duration = time.time() - start_time
            output = {
                "status": "error",
                "task_id": task_id,
                "output": None,
                "error": str(e),
                "duration_seconds": duration,
                "timestamp": datetime.now().isoformat(),
            }

            if run_tree:
                self._complete_langsmith_run(run_tree, output=output, error=str(e))

            return output

    def _build_prompt(
        self,
        task_description: str,
        context: Optional[str],
        allowed_tools: Optional[List[str]],
    ) -> str:
        """Construit le prompt complet pour Claude Code."""
        parts = []

        # Task principale
        parts.append(f"## Task\n\n{task_description}")

        # Contexte si fourni
        if context:
            parts.append(f"\n\n## Context\n\n{context}")

        # Instructions sur les tools
        if allowed_tools:
            tools_str = ", ".join(allowed_tools)
            parts.append(f"\n\n## Allowed Tools\n\nYou may use: {tools_str}")

        # Instructions de sortie
        parts.append("""

## Output Format

Please complete the task and provide a summary of:
1. What was done
2. Files created/modified
3. Any issues encountered
""")

        return "\n".join(parts)

    def _execute_claude_cli(
        self,
        prompt: str,
        timeout_seconds: int,
    ) -> Dict[str, Any]:
        """Execute Claude Code CLI avec le prompt."""
        # Claude Code CLI accepte le prompt via stdin avec --print
        # ou via argument direct

        cmd = [
            "claude",
            "--print",  # Mode non-interactif, affiche juste la reponse
            "--dangerously-skip-permissions",  # Skip les confirmations (full auto)
        ]

        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            timeout=timeout_seconds,
            cwd=self.working_directory,
            text=True,
        )

        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }

    def _create_langsmith_run(
        self,
        task_id: str,
        prompt: str,
        parent_run_id: Optional[str],
    ) -> Optional[RunTree]:
        """Cree un run LangSmith pour tracer l'execution."""
        if not self.langsmith_client or not LANGSMITH_AVAILABLE:
            return None

        try:
            run_tree = RunTree(
                name=f"claude_code_task_{task_id}",
                run_type="chain",
                inputs={"prompt": prompt, "task_id": task_id},
                project_name=self.project_name,
                parent_run_id=parent_run_id,
            )
            return run_tree
        except Exception as e:
            print(f"[ClaudeCodeWrapper] Erreur creation run LangSmith: {e}")
            return None

    def _complete_langsmith_run(
        self,
        run_tree: RunTree,
        output: Dict[str, Any],
        error: Optional[str] = None,
    ) -> None:
        """Complete le run LangSmith avec les resultats."""
        if not run_tree:
            return

        try:
            run_tree.end(
                outputs=output,
                error=error,
            )
            run_tree.post()
        except Exception as e:
            print(f"[ClaudeCodeWrapper] Erreur completion run LangSmith: {e}")


class ClaudeCodeProjectExecutor:
    """
    Executeur de projets complets via Claude Code CLI.

    Lit un plan de projet et execute chaque tache sequentiellement
    via Claude Code, avec tracing LangSmith.
    """

    def __init__(
        self,
        wrapper: Optional[ClaudeCodeWrapper] = None,
        project_name: str = "knowwhere-agents",
    ):
        self.wrapper = wrapper or ClaudeCodeWrapper(project_name=project_name)
        self.project_name = project_name

    def execute_project_plan(
        self,
        plan_path: str,
        output_dir: str,
    ) -> Dict[str, Any]:
        """
        Execute un plan de projet complet.

        Args:
            plan_path: Chemin vers le fichier project_plan.yaml
            output_dir: Repertoire pour les outputs

        Returns:
            Rapport d'execution
        """
        import yaml

        # Charger le plan
        with open(plan_path, "r", encoding="utf-8") as f:
            plan = yaml.safe_load(f)

        project_id = plan.get("project_id", "unknown")
        tasks = plan.get("tasks", [])

        print(f"\n{'='*60}")
        print(f"Execution projet: {plan.get('title', project_id)}")
        print(f"Nombre de taches: {len(tasks)}")
        print(f"{'='*60}\n")

        results = []
        failed = False

        for idx, task in enumerate(tasks):
            if failed:
                results.append({
                    "task_id": task["task_id"],
                    "status": "skipped",
                    "reason": "Previous task failed",
                })
                continue

            print(f"\n[{idx+1}/{len(tasks)}] Execution: {task['title']}")
            print(f"    ID: {task['task_id']}")
            print(f"    Priorite: {task.get('priority', 'medium')}")

            # Construire la description complete
            description = self._build_task_description(task, plan)

            # Executer
            result = self.wrapper.execute_task(
                task_description=description,
                task_id=task["task_id"],
                timeout_seconds=600,  # 10 minutes par tache
            )

            results.append(result)

            if result["status"] != "success":
                print(f"    ECHEC: {result.get('error', 'Unknown error')}")
                failed = True
            else:
                print(f"    OK ({result['duration_seconds']:.1f}s)")

        # Generer rapport
        report = {
            "project_id": project_id,
            "title": plan.get("title"),
            "total_tasks": len(tasks),
            "completed": sum(1 for r in results if r["status"] == "success"),
            "failed": sum(1 for r in results if r["status"] == "failed"),
            "skipped": sum(1 for r in results if r["status"] == "skipped"),
            "results": results,
            "timestamp": datetime.now().isoformat(),
        }

        # Sauvegarder rapport
        report_path = Path(output_dir) / "execution_report.yaml"
        with open(report_path, "w", encoding="utf-8") as f:
            yaml.dump(report, f, default_flow_style=False, allow_unicode=True)

        print(f"\n{'='*60}")
        print(f"Execution terminee: {report['completed']}/{report['total_tasks']} taches")
        print(f"Rapport: {report_path}")
        print(f"{'='*60}\n")

        return report

    def _build_task_description(
        self,
        task: Dict[str, Any],
        plan: Dict[str, Any],
    ) -> str:
        """Construit la description complete d'une tache."""
        parts = [
            f"# Task: {task['title']}",
            f"\n## Description\n{task['description']}",
        ]

        # Requirements
        requirements = task.get("requirements", [])
        global_reqs = plan.get("global_requirements", [])
        all_reqs = requirements + global_reqs

        if all_reqs:
            parts.append("\n## Requirements")
            for req in all_reqs:
                parts.append(f"- {req}")

        # Dependencies info
        deps = task.get("dependencies", [])
        if deps:
            parts.append(f"\n## Dependencies (completed)\n- {', '.join(deps)}")

        return "\n".join(parts)
