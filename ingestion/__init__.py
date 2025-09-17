"""Common constants for ingestion queue handling."""

import os

INGESTION_QUEUE = os.getenv('INGESTION_QUEUE', 'ingestion')
DEFAULT_JOB_TIMEOUT = int(os.getenv('INGESTION_JOB_TIMEOUT', '7200'))
