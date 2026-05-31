"""Test du timeout par tâche Novita (#430 fiabilité synthèse)."""
from knowbase.common.llm_router import LLMRouter, TaskType


def test_synthesis_gets_long_timeout():
    # LONG_TEXT_SUMMARY (synthèse, génération longue) → 240s
    assert LLMRouter._novita_timeout_for_task(TaskType.LONG_TEXT_SUMMARY) == 240.0


def test_short_tasks_get_short_timeout():
    assert LLMRouter._novita_timeout_for_task(TaskType.FAST_CLASSIFICATION) == 120.0
    assert LLMRouter._novita_timeout_for_task(TaskType.RUNTIME_PARSE_EVALUATE) == 120.0


def test_unknown_task_defaults_short():
    assert LLMRouter._novita_timeout_for_task("whatever") == 120.0
