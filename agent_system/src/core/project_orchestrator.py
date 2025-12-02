"""
Project Orchestrator - Gestion complete de projets multi-taches.
"""
from pathlib import Path
from typing import Optional
from datetime import datetime
import subprocess
import time

from models import (
    Task,
    TaskPriority,
    ProjectPlan,
    ProjectTask,
    ProjectState,
    ProjectReport,
    ProjectStatus,
    ProjectTaskStatus,
)
from agents import DocumentParserAgent
from .orchestrator import AgentOrchestrator


class ProjectOrchestrator:
    """Orchestrateur pour l'execution complete de projets."""

    def __init__(
        self,
        workspace_root: str = "/app",
        config_path: Optional[str] = None,
    ):
        """
        Initialise le ProjectOrchestrator.

        Args:
            workspace_root: Repertoire de travail
            config_path: Chemin vers la configuration (optionnel)
        """
        self.workspace_root = Path(workspace_root)
        self.config_path = config_path or "agent_system/config/"

        # Agents
        self.document_parser = DocumentParserAgent()
        self.task_orchestrator = AgentOrchestrator(config_path=self.config_path)

    def execute_project(
        self,
        document_path: str,
        project_id: str,
        output_dir: Optional[str] = None,
        resume_from_checkpoint: bool = False,
        base_branch: str = "main",
    ) -> ProjectReport:
        """
        Execute un projet complet depuis un document.

        Args:
            document_path: Chemin vers le document projet (markdown)
            project_id: ID unique du projet
            output_dir: Repertoire de sortie (optionnel)
            resume_from_checkpoint: Reprendre depuis un checkpoint existant
            base_branch: Branche git de base

        Returns:
            ProjectReport avec les resultats
        """
        if output_dir is None:
            output_dir = f"agent_system/data/projects/{project_id}"

        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        checkpoint_path = output_path / "checkpoint.yaml"

        # Charger ou creer l'etat du projet
        if resume_from_checkpoint and checkpoint_path.exists():
            print(f"\n📂 Reprise depuis checkpoint: {checkpoint_path}")
            project_state = ProjectState.load_checkpoint(checkpoint_path)
            project_state.log_event("resume", f"Resumed from checkpoint")
        else:
            print(f"\n📋 Parsing document: {document_path}")
            project_plan = self._parse_document(document_path, project_id, base_branch)

            # Sauvegarder le plan
            plan_path = output_path / "project_plan.yaml"
            project_plan.save(plan_path)
            print(f"✅ Plan sauvegarde: {plan_path}")

            # Afficher le resume
            summary = self.document_parser.extract_task_summary(project_plan)
            summary_path = output_path / "project_summary.md"
            summary_path.write_text(summary, encoding="utf-8")
            print(f"✅ Resume genere: {summary_path}")

            # Creer l'etat initial
            project_state = ProjectState(
                project_plan=project_plan,
                current_task_index=0,
                execution_started_at=datetime.now(),
            )
            project_state.log_event("start", f"Project execution started")

        # Creer la branche Git
        if not self._git_branch_exists(project_state.project_plan.git_branch):
            self._create_git_branch(
                project_state.project_plan.git_branch,
                project_state.project_plan.base_branch,
            )
            project_state.log_event(
                "git",
                f"Created branch: {project_state.project_plan.git_branch}"
            )

        # Executer les taches
        try:
            self._execute_tasks(project_state, checkpoint_path)
            project_state.project_plan.status = ProjectStatus.COMPLETED
            project_state.log_event("complete", "All tasks completed successfully")
        except Exception as e:
            project_state.project_plan.status = ProjectStatus.FAILED
            project_state.log_event("error", f"Project execution failed: {str(e)}")

            # Rollback Git
            print(f"\n❌ Echec du projet: {str(e)}")
            print(f"🔄 Rollback de la branche Git...")
            self._rollback_git_branch(
                project_state.project_plan.git_branch,
                project_state.project_plan.base_branch,
            )
            project_state.project_plan.status = ProjectStatus.ROLLED_BACK
            project_state.log_event("rollback", "Git branch rolled back")

        # Marquer comme termine
        project_state.execution_completed_at = datetime.now()

        # Generer le rapport final
        report = self._generate_project_report(project_state)

        # Sauvegarder le rapport
        report_path = output_path / "project_report.yaml"
        report.save(report_path)
        print(f"\n📊 Rapport final: {report_path}")

        # Rapport markdown
        md_report = report.generate_markdown_report()
        md_report_path = output_path / "project_report.md"
        md_report_path.write_text(md_report, encoding="utf-8")
        print(f"📄 Rapport markdown: {md_report_path}")

        return report

    def _parse_document(
        self,
        document_path: str,
        project_id: str,
        base_branch: str,
    ) -> ProjectPlan:
        """Parse le document projet."""
        return self.document_parser.parse_project_document(
            document_path=document_path,
            project_id=project_id,
            base_branch=base_branch,
        )

    def _execute_tasks(
        self,
        project_state: ProjectState,
        checkpoint_path: Path,
    ) -> None:
        """
        Execute toutes les taches du projet dans l'ordre.

        Args:
            project_state: Etat du projet
            checkpoint_path: Chemin pour sauvegarder les checkpoints
        """
        execution_order = project_state.project_plan.get_execution_order()
        total_tasks = len(execution_order)

        print(f"\n🚀 Execution de {total_tasks} taches...")
        print(f"━" * 80)

        for idx in range(project_state.current_task_index, total_tasks):
            task = execution_order[idx]
            project_state.current_task_index = idx

            print(f"\n📌 Tache {idx + 1}/{total_tasks}: {task.title}")
            print(f"   ID: {task.task_id}")
            print(f"   Priorite: {task.priority}")

            task.status = ProjectTaskStatus.IN_PROGRESS
            task.started_at = datetime.now()

            # Sauvegarder checkpoint AVANT execution
            project_state.save_checkpoint(checkpoint_path)

            try:
                # Executer la tache avec le TaskOrchestrator
                self._execute_single_task(task, project_state)

                task.status = ProjectTaskStatus.COMPLETED
                task.completed_at = datetime.now()
                duration = (task.completed_at - task.started_at).total_seconds()

                print(f"   ✅ Complete en {duration:.1f}s")
                project_state.log_event(
                    "task_complete",
                    f"Task {task.task_id} completed",
                    task_id=task.task_id,
                    duration=duration,
                )

            except Exception as e:
                task.status = ProjectTaskStatus.FAILED
                task.error_message = str(e)
                task.completed_at = datetime.now()

                print(f"   ❌ Echec: {str(e)}")
                project_state.log_event(
                    "task_failed",
                    f"Task {task.task_id} failed: {str(e)}",
                    task_id=task.task_id,
                    error=str(e),
                )

                # Sauvegarder checkpoint avec echec
                project_state.save_checkpoint(checkpoint_path)

                # Echec = abandon du projet
                raise Exception(f"Task {task.task_id} failed: {str(e)}")

            # Sauvegarder checkpoint apres succes
            project_state.save_checkpoint(checkpoint_path)

        print(f"\n━" * 80)
        print(f"✅ Toutes les taches completees avec succes!")

    def _execute_single_task(
        self,
        project_task: ProjectTask,
        project_state: ProjectState,
    ) -> None:
        """
        Execute une seule tache avec le TaskOrchestrator.

        Args:
            project_task: Tache a executer
            project_state: Etat du projet
        """
        # Creer une Task pour le TaskOrchestrator
        task = Task(
            task_id=project_task.task_id,
            title=project_task.title,
            description=project_task.description,
            requirements=project_task.requirements + project_state.project_plan.global_requirements,
            priority=self._map_priority(project_task.priority),
        )

        # Executer avec TaskOrchestrator
        result = self.task_orchestrator.run(task=task)

        # Stocker les resultats
        project_task.plan_id = result.get("plan_id")
        project_task.validation_passed = result.get("validation_passed", False)

        if not project_task.validation_passed:
            raise Exception(f"Validation failed for task {project_task.task_id}")

    def _map_priority(self, priority_str: str) -> TaskPriority:
        """Convertit string priority en TaskPriority."""
        mapping = {
            "low": TaskPriority.LOW,
            "medium": TaskPriority.MEDIUM,
            "high": TaskPriority.HIGH,
            "critical": TaskPriority.CRITICAL,
        }
        return mapping.get(priority_str, TaskPriority.MEDIUM)

    def _create_git_branch(self, branch_name: str, base_branch: str) -> None:
        """Cree une nouvelle branche Git depuis la branche courante."""
        print(f"🌿 Creation branche Git: {branch_name}")
        # Git operations must run from git repo root (/app)
        git_repo_root = "/app"
        try:
            # Obtenir la branche courante
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=git_repo_root,
                check=True,
                capture_output=True,
            )
            current_branch = result.stdout.decode().strip()
            print(f"   Branche courante: {current_branch}")

            # Creer nouvelle branche depuis la branche courante
            # (evite les problemes de checkout avec volumes Docker)
            result = subprocess.run(
                ["git", "checkout", "-b", branch_name],
                cwd=git_repo_root,
                capture_output=True,
            )
            # Ignorer l'erreur Git LFS si le checkout a reussi
            stderr_msg = result.stderr.decode() if result.stderr else ""
            if result.returncode != 0 and "Switched to a new branch" not in stderr_msg:
                raise Exception(f"Failed to create git branch: {stderr_msg}")
            print(f"✅ Branche creee: {branch_name} (depuis {current_branch})")
        except subprocess.CalledProcessError as e:
            raise Exception(f"Failed to create git branch: {e.stderr.decode() if e.stderr else str(e)}")

    def _git_branch_exists(self, branch_name: str) -> bool:
        """Verifie si une branche Git existe."""
        git_repo_root = "/app"
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--verify", branch_name],
                cwd=git_repo_root,
                capture_output=True,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _rollback_git_branch(self, branch_name: str, base_branch: str) -> None:
        """Rollback: supprime la branche projet et retourne sur base."""
        git_repo_root = "/app"
        try:
            # Retourner sur base_branch
            subprocess.run(
                ["git", "checkout", base_branch],
                cwd=git_repo_root,
                check=True,
                capture_output=True,
            )

            # Supprimer la branche projet
            subprocess.run(
                ["git", "branch", "-D", branch_name],
                cwd=git_repo_root,
                check=True,
                capture_output=True,
            )
            print(f"✅ Branche {branch_name} supprimee")
        except subprocess.CalledProcessError as e:
            print(f"⚠️  Avertissement rollback: {e.stderr.decode()}")

    def _generate_project_report(self, project_state: ProjectState) -> ProjectReport:
        """Genere le rapport final du projet."""
        plan = project_state.project_plan

        # Compter les taches par statut
        completed = sum(1 for t in plan.tasks if t.status == ProjectTaskStatus.COMPLETED)
        failed = sum(1 for t in plan.tasks if t.status == ProjectTaskStatus.FAILED)
        skipped = sum(1 for t in plan.tasks if t.status == ProjectTaskStatus.SKIPPED)

        # Calculer duree
        duration = 0.0
        if project_state.execution_started_at and project_state.execution_completed_at:
            duration = (
                project_state.execution_completed_at - project_state.execution_started_at
            ).total_seconds()

        # Creer le rapport
        report = ProjectReport(
            project_id=plan.project_id,
            project_title=plan.title,
            status=plan.status,
            total_tasks=len(plan.tasks),
            completed_tasks=completed,
            failed_tasks=failed,
            skipped_tasks=skipped,
            git_branch=plan.git_branch,
            git_commits=[],  # TODO: extraire les commits de la branche
            started_at=project_state.execution_started_at,
            completed_at=project_state.execution_completed_at,
            duration_seconds=duration,
            execution_log=project_state.execution_log,
        )

        # Ajouter les summaries des taches
        for task in plan.tasks:
            report.task_summaries.append({
                "task_id": task.task_id,
                "title": task.title,
                "status": task.status.value,
                "validation_passed": task.validation_passed,
                "error_message": task.error_message,
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            })

        return report
