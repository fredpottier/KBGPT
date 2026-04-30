"""
JobState pydantic — P4.1.

État per-doc persisté dans Redis pour résilience ingestion.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class JobStateEnum(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    POST_IMPORT = "post_import"
    DONE = "done"
    FAILED = "failed"
    PAUSED = "paused"


class JobCheckpoint(BaseModel):
    """Sauvegarde de progression mid-process pour reprise."""

    phase: str = Field(..., description="extract / claim_persist / post_import / done")
    progress: float = Field(0.0, ge=0.0, le=1.0)
    last_block: Optional[int] = None
    total_blocks: Optional[int] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    saved_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


class JobState(BaseModel):
    """État complet d'un job d'ingestion."""

    doc_id: str
    file_path: str
    state: JobStateEnum = JobStateEnum.PENDING
    started_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    last_checkpoint: Optional[JobCheckpoint] = None
    error: Optional[str] = None
    retries: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
