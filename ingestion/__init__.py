"""Common constants for ingestion queue handling."""

import os

INGESTION_QUEUE = os.getenv('INGESTION_QUEUE', 'ingestion')
DEFAULT_JOB_TIMEOUT = int(os.getenv('INGESTION_JOB_TIMEOUT', '7200'))

# Ensure submodules used by RQ are importable via ``ingestion.jobs``
from . import jobs  # noqa: F401

__all__ = [
    'INGESTION_QUEUE',
    'DEFAULT_JOB_TIMEOUT',
    'jobs',
]
