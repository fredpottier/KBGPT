"""
Document Parser Agent - Parse les documents projet et extrait les taches.
"""
from pathlib import Path
from typing import List, Dict, Any
import json
import re

from .base_agent import BaseAgent
from models import ProjectPlan, ProjectTask, ProjectStatus, ProjectTaskStatus


class DocumentParserAgent(BaseAgent):
    """Agent specialise dans le parsing de documents projet."""

    def __init__(
        self,
        prompts_config_path: str = "agent_system/config/prompts/document_parser.yaml",
        agents_config_path: str = "agent_system/config/agents_settings.yaml",
    ):
        super().__init__(
            agent_name="DocumentParserAgent",
            prompts_config_path=prompts_config_path,
            agents_config_path=agents_config_path,
        )

    def parse_project_document(
        self,
        document_path: str,
        project_id: str,
        base_branch: str = "main",
    ) -> ProjectPlan:
        """
        Parse un document projet markdown et extrait les taches.

        Args:
            document_path: Chemin vers le document markdown
            project_id: ID unique du projet
            base_branch: Branche git de base

        Returns:
            ProjectPlan avec toutes les taches extraites
        """
        # Lire le document
        doc_path = Path(document_path)
        if not doc_path.exists():
            raise FileNotFoundError(f"Document not found: {document_path}")

        with open(doc_path, "r", encoding="utf-8") as f:
            document_content = f.read()

        # Utiliser Claude pour parser le document
        parsing_result = self._parse_with_llm(document_content)

        # Creer le ProjectPlan
        project_plan = ProjectPlan(
            project_id=project_id,
            title=parsing_result["title"],
            description=parsing_result["description"],
            document_path=document_path,
            git_branch=f"project/{project_id}",
            base_branch=base_branch,
            global_requirements=parsing_result.get("global_requirements", []),
            status=ProjectStatus.PARSED,
        )

        # Ajouter les taches
        for task_data in parsing_result["tasks"]:
            task = ProjectTask(
                task_id=task_data["task_id"],
                title=task_data["title"],
                description=task_data["description"],
                requirements=task_data.get("requirements", []),
                dependencies=task_data.get("dependencies", []),
                priority=task_data.get("priority", "medium"),
                status=ProjectTaskStatus.PENDING,
            )
            project_plan.tasks.append(task)

        return project_plan

    def _parse_with_llm(self, document_content: str) -> Dict[str, Any]:
        """
        Utilise Claude pour parser le document et extraire les taches.

        Args:
            document_content: Contenu du document markdown

        Returns:
            Dictionnaire avec title, description, tasks, global_requirements
        """
        system_prompt = self.prompts.get("parsing_prompt", "")
        user_prompt = self.prompts.get("user_prompt_template", "").format(
            document_content=document_content
        )

        messages = [
            {"role": "user", "content": user_prompt}
        ]

        # Appeler Claude
        response = self.llm.invoke(
            messages,
            system=system_prompt,
        )

        # Parser la reponse JSON
        response_text = response.content.strip()

        # Extraire le JSON (peut etre entoure de ```json ... ```)
        json_match = re.search(r"```json\s*(.*?)\s*```", response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = response_text

        try:
            parsing_result = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse LLM response as JSON: {e}\n\nResponse:\n{response_text}")

        # Valider la structure
        self._validate_parsing_result(parsing_result)

        return parsing_result

    def _validate_parsing_result(self, result: Dict[str, Any]) -> None:
        """
        Valide la structure du resultat de parsing.

        Args:
            result: Resultat a valider

        Raises:
            ValueError: Si la structure est invalide
        """
        required_keys = ["title", "description", "tasks"]
        for key in required_keys:
            if key not in result:
                raise ValueError(f"Missing required key in parsing result: {key}")

        if not isinstance(result["tasks"], list):
            raise ValueError("'tasks' must be a list")

        for idx, task in enumerate(result["tasks"]):
            required_task_keys = ["task_id", "title", "description"]
            for key in required_task_keys:
                if key not in task:
                    raise ValueError(f"Task {idx} missing required key: {key}")

            # Valider task_id format
            if not re.match(r"^task_\d+$", task["task_id"]):
                raise ValueError(f"Invalid task_id format: {task['task_id']} (expected: task_N)")

            # Valider dependencies (doivent etre des task_ids valides)
            if "dependencies" in task:
                if not isinstance(task["dependencies"], list):
                    raise ValueError(f"Task {task['task_id']} dependencies must be a list")

                all_task_ids = [t["task_id"] for t in result["tasks"]]
                for dep_id in task["dependencies"]:
                    if dep_id not in all_task_ids:
                        raise ValueError(
                            f"Task {task['task_id']} has invalid dependency: {dep_id}"
                        )

            # Valider priority
            if "priority" in task:
                valid_priorities = ["low", "medium", "high", "critical"]
                if task["priority"] not in valid_priorities:
                    raise ValueError(
                        f"Task {task['task_id']} has invalid priority: {task['priority']}"
                    )

    def extract_task_summary(self, project_plan: ProjectPlan) -> str:
        """
        Genere un resume lisible du projet parse.

        Args:
            project_plan: Plan du projet

        Returns:
            Resume en markdown
        """
        lines = [
            f"# Project: {project_plan.title}",
            f"",
            f"**Project ID**: {project_plan.project_id}",
            f"**Git Branch**: {project_plan.git_branch}",
            f"**Total Tasks**: {len(project_plan.tasks)}",
            f"",
            f"## Description",
            f"",
            project_plan.description,
            f"",
        ]

        if project_plan.global_requirements:
            lines.append(f"## Global Requirements")
            lines.append(f"")
            for req in project_plan.global_requirements:
                lines.append(f"- {req}")
            lines.append(f"")

        lines.append(f"## Tasks")
        lines.append(f"")

        execution_order = project_plan.get_execution_order()
        for idx, task in enumerate(execution_order, 1):
            lines.append(f"### {idx}. {task.title} (`{task.task_id}`)")
            lines.append(f"")
            lines.append(f"**Priority**: {task.priority}")
            if task.dependencies:
                deps_str = ", ".join([f"`{dep}`" for dep in task.dependencies])
                lines.append(f"**Dependencies**: {deps_str}")
            lines.append(f"")
            lines.append(task.description)
            lines.append(f"")
            if task.requirements:
                lines.append(f"**Requirements**:")
                for req in task.requirements:
                    lines.append(f"- {req}")
                lines.append(f"")

        return "\n".join(lines)
