"""
Tool de base pour tous les tools du système.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from datetime import datetime
import time

from models.tool_result import (
    ToolResult,
    ToolStatus,
    create_success_result,
    create_error_result,
    create_timeout_result,
)


class BaseTool(ABC):
    """Classe abstraite pour tous les tools."""

    def __init__(self, name: str, description: str, timeout: int = 120) -> None:
        """
        Args:
            name: Nom du tool
            description: Description du tool
            timeout: Timeout en secondes
        """
        self.name = name
        self.description = description
        self.timeout = timeout

    @abstractmethod
    def _execute(self, **kwargs: Any) -> Any:
        """
        Exécute le tool (à implémenter par les sous-classes).

        Returns:
            Résultat de l'exécution
        """
        pass

    def execute(self, **kwargs: Any) -> ToolResult:
        """
        Exécute le tool avec gestion d'erreurs et timeout.

        Returns:
            ToolResult encapsulant le résultat
        """
        start_time = time.time()

        try:
            result = self._execute(**kwargs)
            duration = time.time() - start_time

            return create_success_result(
                tool_name=self.name,
                output=result,
                duration_seconds=duration,
                metadata={"timestamp": datetime.utcnow().isoformat()}
            )

        except TimeoutError as e:
            return create_timeout_result(
                tool_name=self.name,
                timeout_seconds=self.timeout,
                metadata={"error": str(e)}
            )

        except Exception as e:
            duration = time.time() - start_time
            return create_error_result(
                tool_name=self.name,
                error=e,
                duration_seconds=duration
            )

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}')"
