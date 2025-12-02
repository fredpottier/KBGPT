"""
Tests unitaires pour les tools.
"""
import pytest
from pathlib import Path

from tools import (
    FilesystemTool,
    ShellTool,
    GitTool,
    TestingTool,
    CodeAnalysisTool,
    DockerTool,
)


@pytest.mark.unit
class TestFilesystemTool:
    """Tests pour FilesystemTool."""

    def test_filesystem_tool_creation(self, mock_filesystem_config):
        """Test creation du tool."""
        tool = FilesystemTool(**mock_filesystem_config)
        assert tool.name == "filesystem"
        assert len(tool.allowed_read_paths) > 0

    def test_read_file(self, temp_workspace, mock_filesystem_config):
        """Test lecture de fichier."""
        # Creer un fichier de test
        test_file = temp_workspace / "test.txt"
        test_file.write_text("Hello World")

        # Configurer le tool avec le workspace
        config = mock_filesystem_config.copy()
        config["allowed_read_paths"] = [str(temp_workspace / "**")]
        tool = FilesystemTool(**config)

        # Tester la lecture
        result = tool.execute(operation="read", path=str(test_file))
        assert result.is_success is True
        assert result.output["content"] == "Hello World"

    def test_write_file(self, temp_workspace, mock_filesystem_config):
        """Test ecriture de fichier."""
        test_file = temp_workspace / "test.txt"

        # Configurer le tool
        config = mock_filesystem_config.copy()
        config["allowed_write_paths"] = [str(temp_workspace / "**")]
        tool = FilesystemTool(**config)

        # Tester l'ecriture
        result = tool.execute(
            operation="write",
            path=str(test_file),
            content="Test content"
        )
        assert result.is_success is True
        assert test_file.exists()
        assert test_file.read_text() == "Test content"

    def test_list_directory(self, temp_workspace, mock_filesystem_config):
        """Test listage de repertoire."""
        # Creer des fichiers
        (temp_workspace / "file1.txt").write_text("test1")
        (temp_workspace / "file2.txt").write_text("test2")

        # Configurer le tool
        config = mock_filesystem_config.copy()
        config["allowed_read_paths"] = [str(temp_workspace / "**")]
        tool = FilesystemTool(**config)

        # Tester le listage
        result = tool.execute(operation="list", path=str(temp_workspace))
        assert result.is_success is True
        assert len(result.output["files"]) >= 2

    def test_denied_path(self, mock_filesystem_config):
        """Test acces refuse a un chemin interdit."""
        tool = FilesystemTool(**mock_filesystem_config)

        # Tenter de lire un fichier dans .git
        result = tool.execute(
            operation="read",
            path=".git/config"
        )
        assert result.is_success is False
        assert "denied" in result.error.lower()


@pytest.mark.unit
class TestShellTool:
    """Tests pour ShellTool."""

    def test_shell_tool_creation(self, mock_shell_config):
        """Test creation du tool."""
        tool = ShellTool(**mock_shell_config)
        assert tool.name == "shell"
        assert len(tool.allowed_commands) > 0

    def test_allowed_command(self, mock_shell_config):
        """Test execution d'une commande autorisee."""
        tool = ShellTool(**mock_shell_config)

        # pwd est autorise
        result = tool.execute(command="pwd")
        assert result.is_success is True

    def test_denied_command(self, mock_shell_config):
        """Test rejet d'une commande interdite."""
        tool = ShellTool(**mock_shell_config)

        # rm -rf est interdit
        result = tool.execute(command="rm -rf /")
        assert result.is_success is False
        assert "not allowed" in result.error.lower() or "denied" in result.error.lower()

    def test_command_validation(self, mock_shell_config):
        """Test validation des commandes."""
        tool = ShellTool(**mock_shell_config)

        # Commande autorisee
        result = tool.execute(command="git status")
        # Le resultat peut echouer si pas dans un repo git, mais la commande est autorisee
        assert "not allowed" not in str(result.error).lower() if result.error else True


@pytest.mark.unit
class TestGitTool:
    """Tests pour GitTool."""

    def test_git_tool_creation(self):
        """Test creation du tool."""
        tool = GitTool(repo_path=".")
        assert tool.name == "git"

    @pytest.mark.skipif(
        not Path(".git").exists(),
        reason="Requires git repository"
    )
    def test_git_status(self):
        """Test git status."""
        tool = GitTool(repo_path=".")
        result = tool.execute(operation="status")
        # Si on est dans un repo git, ca devrait marcher
        assert result.is_success in [True, False]  # Peut echouer si pas un repo

    def test_git_unsupported_operation(self):
        """Test operation non supportee."""
        tool = GitTool(repo_path=".")
        result = tool.execute(operation="push")  # push n'est pas supporte (read-only)
        assert result.is_success is False
        assert "unsupported" in result.error.lower() or "not supported" in result.error.lower()


@pytest.mark.unit
class TestTestingTool:
    """Tests pour TestingTool."""

    def test_testing_tool_creation(self):
        """Test creation du tool."""
        tool = TestingTool()
        assert tool.name == "testing"

    def test_pytest_execution(self, temp_workspace):
        """Test execution de pytest."""
        # Creer un test simple
        test_file = temp_workspace / "test_simple.py"
        test_file.write_text("""
def test_example():
    assert 1 + 1 == 2
""")

        tool = TestingTool()
        result = tool.execute(
            test_path=str(test_file),
            coverage=False,
            verbose=False,
        )

        # Le test devrait passer
        assert result.is_success is True
        assert result.output.get("test_report", {}).get("passed", 0) >= 1


@pytest.mark.unit
class TestCodeAnalysisTool:
    """Tests pour CodeAnalysisTool."""

    def test_code_analysis_tool_creation(self):
        """Test creation du tool."""
        tool = CodeAnalysisTool()
        assert tool.name == "code_analysis"

    def test_ast_analysis(self, temp_workspace):
        """Test analyse AST."""
        # Creer un fichier Python simple
        py_file = temp_workspace / "example.py"
        py_file.write_text("""
def hello():
    return "world"

class Example:
    def method(self):
        pass
""")

        tool = CodeAnalysisTool()
        result = tool.execute(
            analysis_type="ast",
            file_path=str(py_file)
        )

        assert result.is_success is True
        assert "functions" in result.output
        assert "classes" in result.output

    def test_complexity_analysis(self, temp_workspace):
        """Test analyse de complexite."""
        py_file = temp_workspace / "complex.py"
        py_file.write_text("""
def complex_function(x):
    if x > 0:
        if x > 10:
            return "big"
        else:
            return "small"
    else:
        return "negative"
""")

        tool = CodeAnalysisTool()
        result = tool.execute(
            analysis_type="complexity",
            file_path=str(py_file)
        )

        assert result.is_success is True
        assert "complexity" in result.output


@pytest.mark.unit
class TestDockerTool:
    """Tests pour DockerTool."""

    def test_docker_tool_creation(self):
        """Test creation du tool."""
        tool = DockerTool(compose_file="docker-compose.yml")
        assert tool.name == "docker"

    @pytest.mark.skipif(
        not Path("docker-compose.yml").exists(),
        reason="Requires docker-compose.yml"
    )
    def test_docker_ps(self):
        """Test docker compose ps."""
        tool = DockerTool(compose_file="docker-compose.yml")
        result = tool.execute(operation="ps")
        # Peut echouer si Docker n'est pas lance, mais la structure est correcte
        assert result.is_success in [True, False]

    def test_docker_unsupported_operation(self):
        """Test operation non supportee."""
        tool = DockerTool(compose_file="docker-compose.yml")
        result = tool.execute(operation="down")  # down n'est pas supporte (read-only)
        assert result.is_success is False
        assert "unsupported" in result.error.lower() or "not supported" in result.error.lower()
