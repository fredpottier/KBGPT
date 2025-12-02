"""
Shell Tool - Exécution sécurisée de commandes shell avec whitelist.
"""
import subprocess
import re
from typing import Any, Dict, List, Optional
import yaml

from .base_tool import BaseTool
from models.tool_result import ShellCommandResult, ToolStatus


class ShellTool(BaseTool):
    """Tool pour exécution sécurisée de commandes shell."""

    def __init__(
        self,
        allowed_patterns: List[Dict[str, Any]],
        denied_patterns: List[str],
        default_timeout: int = 120,
        max_output_lines: int = 1000,
    ) -> None:
        """
        Args:
            allowed_patterns: Liste de patterns de commandes autorisées
            denied_patterns: Liste de patterns de commandes interdites
            default_timeout: Timeout par défaut en secondes
            max_output_lines: Nombre max de lignes de sortie
        """
        super().__init__("shell", "Shell command execution (whitelisted)", default_timeout)
        self.allowed_patterns = allowed_patterns
        self.denied_patterns = denied_patterns
        self.default_timeout = default_timeout
        self.max_output_lines = max_output_lines

    def _execute(
        self,
        command: str,
        timeout: Optional[int] = None,
        cwd: Optional[str] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Exécute une commande shell.

        Args:
            command: Commande à exécuter
            timeout: Timeout en secondes (optionnel)
            cwd: Working directory (optionnel)
            **kwargs: Arguments additionnels

        Returns:
            Résultat de la commande
        """
        # Valider la commande
        self._validate_command(command)

        # Déterminer le timeout
        exec_timeout = timeout or self.default_timeout

        try:
            # Exécuter la commande
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=exec_timeout,
                cwd=cwd,
            )

            # Limiter la sortie
            stdout = self._truncate_output(result.stdout)
            stderr = self._truncate_output(result.stderr)

            return {
                "command": command,
                "exit_code": result.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "success": result.returncode == 0,
                "timeout": exec_timeout,
            }

        except subprocess.TimeoutExpired as e:
            raise TimeoutError(
                f"Command timed out after {exec_timeout}s: {command}"
            ) from e

    def _validate_command(self, command: str) -> None:
        """
        Valide qu'une commande est autorisée.

        Args:
            command: Commande à valider

        Raises:
            PermissionError: Si la commande n'est pas autorisée
        """
        # Vérifier les patterns interdits en premier
        for denied_pattern in self.denied_patterns:
            if re.search(denied_pattern, command):
                raise PermissionError(
                    f"Command denied by pattern '{denied_pattern}': {command}"
                )

        # Vérifier les patterns autorisés
        for allowed in self.allowed_patterns:
            pattern = allowed.get("pattern", "")
            if re.match(pattern, command):
                # Vérifier le timeout spécifique si défini
                specific_timeout = allowed.get("timeout")
                if specific_timeout and specific_timeout < self.timeout:
                    self.timeout = specific_timeout
                return

        # Aucun pattern autorisé ne correspond
        raise PermissionError(
            f"Command not in whitelist: {command}\n"
            f"Allowed patterns: {[p.get('pattern') for p in self.allowed_patterns]}"
        )

    def _truncate_output(self, output: str) -> str:
        """Tronque la sortie si trop longue."""
        lines = output.splitlines()
        if len(lines) > self.max_output_lines:
            truncated_lines = lines[:self.max_output_lines]
            truncated_lines.append(
                f"\n... (truncated, {len(lines) - self.max_output_lines} lines omitted)"
            )
            return "\n".join(truncated_lines)
        return output

    def is_command_allowed(self, command: str) -> bool:
        """
        Vérifie si une commande est autorisée (sans l'exécuter).

        Args:
            command: Commande à vérifier

        Returns:
            True si autorisée, False sinon
        """
        try:
            self._validate_command(command)
            return True
        except PermissionError:
            return False


def load_shell_tool_from_config(config_path: str) -> ShellTool:
    """Charge ShellTool depuis la configuration YAML."""
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    shell_config = config.get("shell_commands", {})

    return ShellTool(
        allowed_patterns=shell_config.get("allowed", []),
        denied_patterns=[
            p.get("pattern") for p in shell_config.get("denied", [])
        ],
        default_timeout=120,
        max_output_lines=1000,
    )
