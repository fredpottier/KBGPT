"""
Configuration pytest et fixtures communes pour les tests.
"""
import os
import pytest
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Any, Generator

# Configuration pour les tests
os.environ["LANGSMITH_TRACING"] = "false"


@pytest.fixture
def temp_workspace() -> Generator[Path, None, None]:
    """
    Cree un workspace temporaire pour les tests.

    Yields:
        Path vers le workspace temporaire
    """
    temp_dir = Path(tempfile.mkdtemp(prefix="agent_test_"))
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def sample_task() -> Dict[str, Any]:
    """
    Cree une tache de test simple.

    Returns:
        Donnees de tache de test
    """
    return {
        "task_id": "test_task_001",
        "title": "Test Task",
        "description": "Implement a simple calculator function",
        "requirements": [
            "Function should support addition and subtraction",
            "Function should handle edge cases",
            "Tests should be written",
        ],
        "priority": "medium",
    }


@pytest.fixture
def sample_plan() -> Dict[str, Any]:
    """
    Cree un plan de test simple.

    Returns:
        Donnees de plan de test
    """
    return {
        "plan_id": "test_plan_001",
        "task_id": "test_task_001",
        "task_description": "Implement calculator",
        "subtasks": [
            {
                "subtask_id": "subtask_001",
                "title": "Create calculator module",
                "description": "Create the basic calculator module structure",
                "complexity": "low",
                "estimated_duration_minutes": 30,
                "dependencies": [],
                "validation_criteria": "Module created and importable",
                "files_impacted": ["calculator.py"],
            },
            {
                "subtask_id": "subtask_002",
                "title": "Implement operations",
                "description": "Implement add and subtract operations",
                "complexity": "medium",
                "estimated_duration_minutes": 60,
                "dependencies": ["subtask_001"],
                "validation_criteria": "Operations work correctly",
                "files_impacted": ["calculator.py"],
            },
            {
                "subtask_id": "subtask_003",
                "title": "Write tests",
                "description": "Write unit tests for calculator",
                "complexity": "low",
                "estimated_duration_minutes": 45,
                "dependencies": ["subtask_002"],
                "validation_criteria": "All tests pass",
                "files_impacted": ["test_calculator.py"],
            },
        ],
        "estimated_total_duration_minutes": 135,
    }


@pytest.fixture
def config_path() -> str:
    """
    Retourne le chemin vers la configuration de test.

    Returns:
        Chemin vers la config
    """
    return "agent_system/config/"


@pytest.fixture
def mock_llm_response() -> str:
    """
    Reponse LLM mockee pour les tests.

    Returns:
        Reponse mockee
    """
    return """
```yaml
plan_id: test_plan_001
task_id: test_task_001
subtasks:
  - subtask_id: subtask_001
    title: Analyze requirements
    description: Understand the task requirements
    complexity: low
    estimated_duration_minutes: 30
    dependencies: []
    validation_criteria: Requirements documented
    files_impacted: []
  - subtask_id: subtask_002
    title: Implement solution
    description: Implement the required functionality
    complexity: medium
    estimated_duration_minutes: 120
    dependencies: [subtask_001]
    validation_criteria: Tests pass
    files_impacted: []
estimated_total_duration_minutes: 150
```
"""


@pytest.fixture
def mock_filesystem_config() -> Dict[str, Any]:
    """
    Configuration mockee pour FilesystemTool.

    Returns:
        Configuration filesystem
    """
    return {
        "allowed_read_paths": [
            "agent_system/**",
            "src/**",
            "tests/**",
        ],
        "allowed_write_paths": [
            "agent_system/data/**",
            "agent_system/plans/**",
            "agent_system/reports/**",
        ],
        "denied_paths": [
            "**/node_modules/**",
            "**/.git/**",
            "**/venv/**",
            "**/__pycache__/**",
        ],
        "allowed_extensions": [
            ".py", ".yaml", ".yml", ".json", ".txt", ".md",
        ],
        "max_file_size_mb": 10,
    }


@pytest.fixture
def mock_shell_config() -> Dict[str, Any]:
    """
    Configuration mockee pour ShellTool.

    Returns:
        Configuration shell
    """
    return {
        "allowed_commands": [
            r"^pytest\s+.*",
            r"^python\s+-m\s+pytest\s+.*",
            r"^git\s+status$",
            r"^git\s+diff\s+.*",
            r"^ls\s+.*",
            r"^pwd$",
        ],
        "denied_commands": [
            r".*rm\s+-rf\s+/.*",
            r".*shutdown.*",
            r".*reboot.*",
        ],
        "timeout_seconds": 300,
        "max_output_lines": 1000,
    }


@pytest.fixture(autouse=True)
def reset_env_vars():
    """
    Reset les variables d'environnement entre les tests.
    """
    original_env = os.environ.copy()
    yield
    os.environ.clear()
    os.environ.update(original_env)


# Markers personnalises
def pytest_configure(config):
    """Configure les markers personnalises."""
    config.addinivalue_line("markers", "unit: Tests unitaires")
    config.addinivalue_line("markers", "integration: Tests d'integration")
    config.addinivalue_line("markers", "e2e: Tests end-to-end")
    config.addinivalue_line("markers", "slow: Tests lents")
    config.addinivalue_line("markers", "requires_llm: Tests necessitant un LLM reel")
