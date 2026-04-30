"""
Ingestion resilience — Sprint résilience P4.

Modules :
- job_state : pydantic JobState model
- job_manager : Redis-backed JobManager pour persister l'état per-doc

Conformément à doc/ongoing/P4_RESILIENCE_SPRINT_PLAN.md.
"""

from knowbase.ingestion.resilience.job_state import (
    JobState,
    JobStateEnum,
    JobCheckpoint,
)
from knowbase.ingestion.resilience.job_manager import JobManager

__all__ = ["JobState", "JobStateEnum", "JobCheckpoint", "JobManager"]
