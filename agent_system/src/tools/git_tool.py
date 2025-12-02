"""
Git Tool - Opérations Git (lecture seule).
"""
from typing import Any, Dict, List, Optional
from pathlib import Path
import yaml

try:
    from git import Repo, InvalidGitRepositoryError
    GIT_AVAILABLE = True
except ImportError:
    GIT_AVAILABLE = False

from .base_tool import BaseTool


class GitTool(BaseTool):
    """Tool pour opérations Git (lecture seule)."""

    def __init__(
        self,
        repo_path: str = "/app",
        allowed_operations: Optional[List[str]] = None
    ) -> None:
        """
        Args:
            repo_path: Chemin du repository Git
            allowed_operations: Opérations autorisées
        """
        super().__init__("git", "Git operations (read-only)")

        if not GIT_AVAILABLE:
            raise ImportError("GitPython not available. Install with: pip install GitPython")

        self.repo_path = Path(repo_path)
        self.allowed_operations = allowed_operations or [
            "status", "diff", "log", "show", "blame", "branch", "ls-files"
        ]

        # Initialiser le repo
        try:
            self.repo = Repo(self.repo_path)
        except InvalidGitRepositoryError as e:
            raise ValueError(f"Not a git repository: {repo_path}") from e

    def _execute(
        self,
        operation: str,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Exécute une opération Git.

        Args:
            operation: Type d'opération (status, diff, log, etc.)
            **kwargs: Arguments spécifiques à l'opération

        Returns:
            Résultat de l'opération
        """
        # Valider l'opération
        if operation not in self.allowed_operations:
            raise PermissionError(
                f"Git operation not allowed: {operation}. "
                f"Allowed: {self.allowed_operations}"
            )

        if operation == "status":
            return self._get_status()
        elif operation == "diff":
            return self._get_diff(**kwargs)
        elif operation == "log":
            return self._get_log(**kwargs)
        elif operation == "show":
            return self._get_show(**kwargs)
        elif operation == "blame":
            return self._get_blame(**kwargs)
        elif operation == "branch":
            return self._get_branches(**kwargs)
        elif operation == "ls-files":
            return self._get_files(**kwargs)
        else:
            raise ValueError(f"Unknown git operation: {operation}")

    def _get_status(self) -> Dict[str, Any]:
        """Récupère le statut Git."""
        return {
            "branch": self.repo.active_branch.name,
            "commit": self.repo.head.commit.hexsha[:8],
            "modified": [item.a_path for item in self.repo.index.diff(None)],
            "staged": [item.a_path for item in self.repo.index.diff("HEAD")],
            "untracked": self.repo.untracked_files,
            "is_dirty": self.repo.is_dirty(),
        }

    def _get_diff(
        self,
        ref: str = "HEAD",
        path: Optional[str] = None,
        unified: int = 3,
    ) -> Dict[str, Any]:
        """Récupère un diff Git."""
        if path:
            diff = self.repo.git.diff(ref, path, unified=unified)
        else:
            diff = self.repo.git.diff(ref, unified=unified)

        return {
            "ref": ref,
            "path": path,
            "diff": diff,
            "lines": len(diff.splitlines()),
        }

    def _get_log(
        self,
        max_count: int = 10,
        since: Optional[str] = None,
        path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Récupère l'historique Git."""
        kwargs = {"max_count": max_count}
        if since:
            kwargs["since"] = since

        if path:
            commits = list(self.repo.iter_commits(paths=path, **kwargs))
        else:
            commits = list(self.repo.iter_commits(**kwargs))

        commit_data = []
        for commit in commits:
            commit_data.append({
                "hash": commit.hexsha[:8],
                "author": str(commit.author),
                "date": commit.committed_datetime.isoformat(),
                "message": commit.message.strip(),
            })

        return {
            "commits": commit_data,
            "total": len(commit_data),
        }

    def _get_show(
        self,
        ref: str = "HEAD",
    ) -> Dict[str, Any]:
        """Affiche un commit."""
        commit = self.repo.commit(ref)

        return {
            "hash": commit.hexsha[:8],
            "author": str(commit.author),
            "date": commit.committed_datetime.isoformat(),
            "message": commit.message.strip(),
            "diff": commit.diff(commit.parents[0] if commit.parents else None),
            "stats": commit.stats.total,
        }

    def _get_blame(
        self,
        path: str,
    ) -> Dict[str, Any]:
        """Récupère le blame d'un fichier."""
        blame = self.repo.git.blame(path)

        return {
            "path": path,
            "blame": blame,
            "lines": len(blame.splitlines()),
        }

    def _get_branches(
        self,
        remote: bool = False,
    ) -> Dict[str, Any]:
        """Liste les branches."""
        if remote:
            branches = [ref.name for ref in self.repo.remote().refs]
        else:
            branches = [branch.name for branch in self.repo.branches]

        return {
            "current": self.repo.active_branch.name,
            "branches": branches,
            "total": len(branches),
        }

    def _get_files(
        self,
        pattern: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Liste les fichiers trackés."""
        files = self.repo.git.ls_files().splitlines()

        if pattern:
            import fnmatch
            files = [f for f in files if fnmatch.fnmatch(f, pattern)]

        return {
            "files": files,
            "total": len(files),
        }


def load_git_tool_from_config(config_path: str, repo_path: str = "/app") -> GitTool:
    """Charge GitTool depuis la configuration YAML."""
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    git_config = config.get("git", {})

    return GitTool(
        repo_path=repo_path,
        allowed_operations=git_config.get("allowed_operations", None),
    )
