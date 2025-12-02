"""
Docker Tool - Opérations Docker (lecture seule: ps, logs).
"""
import subprocess
from typing import Any, Dict, List, Optional
import yaml

from .base_tool import BaseTool


class DockerTool(BaseTool):
    """Tool pour opérations Docker (lecture seule)."""

    def __init__(
        self,
        allowed_operations: Optional[List[str]] = None,
        compose_file: str = "docker-compose.yml",
    ) -> None:
        """
        Args:
            allowed_operations: Opérations autorisées
            compose_file: Fichier docker-compose à utiliser
        """
        super().__init__("docker", "Docker operations (read-only)")
        self.allowed_operations = allowed_operations or ["ps", "logs", "inspect", "stats"]
        self.compose_file = compose_file

    def _execute(
        self,
        operation: str,
        service_name: Optional[str] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Exécute une opération Docker.

        Args:
            operation: Type d'opération (ps, logs, inspect, stats)
            service_name: Nom du service (optionnel)
            **kwargs: Arguments spécifiques

        Returns:
            Résultat de l'opération
        """
        # Valider l'opération
        if operation not in self.allowed_operations:
            raise PermissionError(
                f"Docker operation not allowed: {operation}. "
                f"Allowed: {self.allowed_operations}"
            )

        if operation == "ps":
            return self._docker_ps()
        elif operation == "logs":
            if not service_name:
                raise ValueError("service_name required for logs operation")
            return self._docker_logs(service_name, **kwargs)
        elif operation == "inspect":
            if not service_name:
                raise ValueError("service_name required for inspect operation")
            return self._docker_inspect(service_name)
        elif operation == "stats":
            return self._docker_stats(service_name, **kwargs)
        else:
            raise ValueError(f"Unknown docker operation: {operation}")

    def _docker_ps(self) -> Dict[str, Any]:
        """Liste les conteneurs en cours."""
        try:
            result = subprocess.run(
                ["docker", "compose", "-f", self.compose_file, "ps"],
                capture_output=True,
                text=True,
                timeout=30,
            )

            # Parser la sortie
            lines = result.stdout.splitlines()
            services = []

            for line in lines[1:]:  # Skip header
                if line.strip():
                    parts = line.split()
                    if len(parts) >= 3:
                        services.append({
                            "name": parts[0],
                            "status": " ".join(parts[1:-1]),
                            "ports": parts[-1] if "->" in parts[-1] else None,
                        })

            return {
                "services": services,
                "total": len(services),
                "output": result.stdout,
            }

        except FileNotFoundError:
            return {"error": "docker or docker-compose not available"}

    def _docker_logs(
        self,
        service_name: str,
        tail: int = 100,
        follow: bool = False,
        since: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Récupère les logs d'un service."""
        cmd = ["docker", "compose", "-f", self.compose_file, "logs"]

        if tail:
            cmd.extend(["--tail", str(tail)])

        if follow:
            cmd.append("--follow")

        if since:
            cmd.extend(["--since", since])

        cmd.append(service_name)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30 if not follow else None,
            )

            return {
                "service": service_name,
                "logs": result.stdout,
                "lines": len(result.stdout.splitlines()),
                "tail": tail,
            }

        except subprocess.TimeoutExpired:
            raise TimeoutError(f"Logs retrieval timed out for service: {service_name}")

    def _docker_inspect(self, service_name: str) -> Dict[str, Any]:
        """Inspecte un conteneur."""
        try:
            # Obtenir le container ID du service
            ps_result = subprocess.run(
                ["docker", "compose", "-f", self.compose_file, "ps", "-q", service_name],
                capture_output=True,
                text=True,
                timeout=10,
            )

            container_id = ps_result.stdout.strip()
            if not container_id:
                return {"error": f"Service not found: {service_name}"}

            # Inspecter le conteneur
            inspect_result = subprocess.run(
                ["docker", "inspect", container_id],
                capture_output=True,
                text=True,
                timeout=10,
            )

            import json
            inspect_data = json.loads(inspect_result.stdout)

            if inspect_data:
                container = inspect_data[0]
                return {
                    "service": service_name,
                    "container_id": container_id[:12],
                    "status": container.get("State", {}).get("Status"),
                    "image": container.get("Config", {}).get("Image"),
                    "ports": container.get("NetworkSettings", {}).get("Ports", {}),
                    "environment": container.get("Config", {}).get("Env", []),
                }

            return {"error": "No inspect data"}

        except json.JSONDecodeError:
            return {"error": "Failed to parse inspect output"}

    def _docker_stats(
        self,
        service_name: Optional[str] = None,
        no_stream: bool = True,
    ) -> Dict[str, Any]:
        """Récupère les statistiques des conteneurs."""
        cmd = ["docker", "stats"]

        if no_stream:
            cmd.append("--no-stream")

        if service_name:
            # Obtenir le container ID
            ps_result = subprocess.run(
                ["docker", "compose", "-f", self.compose_file, "ps", "-q", service_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            container_id = ps_result.stdout.strip()
            if container_id:
                cmd.append(container_id)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )

            return {
                "service": service_name,
                "stats": result.stdout,
                "output": result.stdout,
            }

        except subprocess.TimeoutExpired:
            raise TimeoutError("Stats retrieval timed out")


def load_docker_tool_from_config(config_path: str) -> DockerTool:
    """Charge DockerTool depuis la configuration YAML."""
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    docker_config = config.get("docker", {})

    return DockerTool(
        allowed_operations=docker_config.get("allowed_operations", None),
        compose_file="docker-compose.yml",
    )
