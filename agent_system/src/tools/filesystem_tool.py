"""
Filesystem Tool - Opérations filesystem sécurisées dans un sandbox.
"""
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml

from pathvalidate import is_valid_filepath, validate_filepath

from .base_tool import BaseTool
from models.tool_result import FilesystemOperationResult, ToolStatus


class FilesystemTool(BaseTool):
    """Tool pour opérations filesystem sécurisées."""

    def __init__(
        self,
        workspace_root: str,
        allowed_read_paths: List[str],
        allowed_write_paths: List[str],
        denied_paths: List[str],
        max_file_size_mb: int = 10,
        allowed_extensions: Optional[List[str]] = None,
    ) -> None:
        """
        Args:
            workspace_root: Racine du workspace
            allowed_read_paths: Chemins autorisés en lecture
            allowed_write_paths: Chemins autorisés en écriture
            denied_paths: Chemins strictement interdits
            max_file_size_mb: Taille max fichier en MB
            allowed_extensions: Extensions autorisées pour l'écriture
        """
        super().__init__("filesystem", "Filesystem operations (sandboxed)")
        self.workspace_root = Path(workspace_root).resolve()
        self.allowed_read_paths = [Path(p).resolve() for p in allowed_read_paths]
        self.allowed_write_paths = [Path(p).resolve() for p in allowed_write_paths]
        self.denied_paths = denied_paths
        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024
        self.allowed_extensions = allowed_extensions or [
            ".py", ".yaml", ".yml", ".json", ".md", ".txt", ".sh"
        ]

    def _execute(
        self,
        operation: str,
        path: str,
        content: Optional[str] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Exécute une opération filesystem.

        Args:
            operation: Type d'opération (read, write, list, exists, delete, mkdir)
            path: Chemin du fichier/dossier
            content: Contenu pour l'écriture
            **kwargs: Arguments additionnels

        Returns:
            Résultat de l'opération
        """
        resolved_path = self._resolve_and_validate_path(path, operation)

        if operation == "read":
            return self._read_file(resolved_path)
        elif operation == "write":
            if content is None:
                raise ValueError("Content required for write operation")
            return self._write_file(resolved_path, content)
        elif operation == "list":
            return self._list_directory(resolved_path, **kwargs)
        elif operation == "exists":
            return {"exists": resolved_path.exists(), "path": str(resolved_path)}
        elif operation == "delete":
            return self._delete(resolved_path)
        elif operation == "mkdir":
            return self._mkdir(resolved_path)
        elif operation == "copy":
            dest = kwargs.get("destination")
            if not dest:
                raise ValueError("Destination required for copy operation")
            return self._copy(resolved_path, dest)
        elif operation == "move":
            dest = kwargs.get("destination")
            if not dest:
                raise ValueError("Destination required for move operation")
            return self._move(resolved_path, dest)
        else:
            raise ValueError(f"Unknown operation: {operation}")

    def _resolve_and_validate_path(self, path: str, operation: str) -> Path:
        """Résout et valide un chemin."""
        # Résoudre le chemin
        if not os.path.isabs(path):
            resolved = (self.workspace_root / path).resolve()
        else:
            resolved = Path(path).resolve()

        # Vérifier chemins interdits
        for denied_pattern in self.denied_paths:
            if denied_pattern.startswith("**/"):
                # Pattern glob
                if resolved.match(denied_pattern):
                    raise PermissionError(f"Access denied to path matching {denied_pattern}")
            elif str(resolved).startswith(denied_pattern):
                raise PermissionError(f"Access denied to path: {resolved}")

        # Vérifier permissions lecture/écriture
        if operation in ("write", "delete", "mkdir", "move"):
            # Opérations d'écriture
            if not any(
                str(resolved).startswith(str(allowed))
                for allowed in self.allowed_write_paths
            ):
                raise PermissionError(
                    f"Write access denied to path: {resolved}. "
                    f"Allowed write paths: {self.allowed_write_paths}"
                )

            # Vérifier extension pour écriture de fichiers
            if operation == "write" and resolved.suffix not in self.allowed_extensions:
                raise PermissionError(
                    f"File extension {resolved.suffix} not allowed. "
                    f"Allowed: {self.allowed_extensions}"
                )

        elif operation in ("read", "list", "exists"):
            # Opérations de lecture
            if not any(
                str(resolved).startswith(str(allowed))
                for allowed in self.allowed_read_paths
            ):
                raise PermissionError(
                    f"Read access denied to path: {resolved}. "
                    f"Allowed read paths: {self.allowed_read_paths}"
                )

        return resolved

    def _read_file(self, path: Path) -> Dict[str, Any]:
        """Lit un fichier."""
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        if not path.is_file():
            raise ValueError(f"Path is not a file: {path}")

        # Vérifier taille
        size = path.stat().st_size
        if size > self.max_file_size_bytes:
            raise ValueError(
                f"File too large: {size / 1024 / 1024:.2f}MB "
                f"(max: {self.max_file_size_bytes / 1024 / 1024}MB)"
            )

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        return {
            "path": str(path),
            "content": content,
            "size_bytes": size,
            "encoding": "utf-8",
        }

    def _write_file(self, path: Path, content: str) -> Dict[str, Any]:
        """Écrit un fichier."""
        # Vérifier taille du contenu
        content_size = len(content.encode("utf-8"))
        if content_size > self.max_file_size_bytes:
            raise ValueError(
                f"Content too large: {content_size / 1024 / 1024:.2f}MB "
                f"(max: {self.max_file_size_bytes / 1024 / 1024}MB)"
            )

        # Créer les dossiers parents si nécessaire
        path.parent.mkdir(parents=True, exist_ok=True)

        # Écrire le fichier
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        return {
            "path": str(path),
            "size_bytes": content_size,
            "created": not path.exists(),
        }

    def _list_directory(
        self,
        path: Path,
        recursive: bool = False,
        pattern: Optional[str] = None
    ) -> Dict[str, Any]:
        """Liste le contenu d'un dossier."""
        if not path.exists():
            raise FileNotFoundError(f"Directory not found: {path}")

        if not path.is_dir():
            raise ValueError(f"Path is not a directory: {path}")

        files = []
        directories = []

        if recursive:
            # Listing récursif
            for item in path.rglob(pattern or "*"):
                if item.is_file():
                    files.append(str(item.relative_to(path)))
                elif item.is_dir():
                    directories.append(str(item.relative_to(path)))
        else:
            # Listing non-récursif
            for item in path.iterdir():
                if pattern and not item.match(pattern):
                    continue
                if item.is_file():
                    files.append(item.name)
                elif item.is_dir():
                    directories.append(item.name)

        return {
            "path": str(path),
            "files": sorted(files),
            "directories": sorted(directories),
            "total_files": len(files),
            "total_directories": len(directories),
        }

    def _delete(self, path: Path) -> Dict[str, Any]:
        """Supprime un fichier ou dossier."""
        if not path.exists():
            raise FileNotFoundError(f"Path not found: {path}")

        if path.is_file():
            path.unlink()
            return {"path": str(path), "type": "file", "deleted": True}
        elif path.is_dir():
            shutil.rmtree(path)
            return {"path": str(path), "type": "directory", "deleted": True}

    def _mkdir(self, path: Path) -> Dict[str, Any]:
        """Crée un dossier."""
        path.mkdir(parents=True, exist_ok=True)
        return {"path": str(path), "created": True}

    def _copy(self, source: Path, destination: str) -> Dict[str, Any]:
        """Copie un fichier ou dossier."""
        dest_path = self._resolve_and_validate_path(destination, "write")

        if source.is_file():
            shutil.copy2(source, dest_path)
        elif source.is_dir():
            shutil.copytree(source, dest_path)
        else:
            raise ValueError(f"Invalid source path: {source}")

        return {
            "source": str(source),
            "destination": str(dest_path),
            "copied": True,
        }

    def _move(self, source: Path, destination: str) -> Dict[str, Any]:
        """Déplace un fichier ou dossier."""
        dest_path = self._resolve_and_validate_path(destination, "write")

        shutil.move(str(source), str(dest_path))

        return {
            "source": str(source),
            "destination": str(dest_path),
            "moved": True,
        }


def load_filesystem_tool_from_config(config_path: str) -> FilesystemTool:
    """Charge FilesystemTool depuis la configuration YAML."""
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    fs_config = config.get("filesystem", {})

    return FilesystemTool(
        workspace_root=fs_config.get("workspace_root", "/app/agent_system/data/workspace"),
        allowed_read_paths=fs_config.get("allowed_read_paths", []),
        allowed_write_paths=fs_config.get("allowed_write_paths", []),
        denied_paths=fs_config.get("denied_paths", []),
        max_file_size_mb=fs_config.get("max_file_size_mb", 10),
        allowed_extensions=fs_config.get("allowed_write_extensions"),
    )
