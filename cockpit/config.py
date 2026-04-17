"""
OSMOSIS Cockpit — Configuration.
"""

from __future__ import annotations

import os
from pathlib import Path

# Réseau
COCKPIT_HOST = os.getenv("COCKPIT_HOST", "0.0.0.0")
COCKPIT_PORT = int(os.getenv("COCKPIT_PORT", "9090"))

# Intervalles de collecte (secondes)
COLLECT_INTERVAL = float(os.getenv("COCKPIT_COLLECT_INTERVAL", "5"))
DOCKER_COLLECT_INTERVAL = float(os.getenv("COCKPIT_DOCKER_INTERVAL", "10"))
KNOWLEDGE_COLLECT_INTERVAL = float(os.getenv("COCKPIT_KNOWLEDGE_INTERVAL", "15"))
BURST_COLLECT_INTERVAL = float(os.getenv("COCKPIT_BURST_INTERVAL", "15"))
LLM_COLLECT_INTERVAL = float(os.getenv("COCKPIT_LLM_INTERVAL", "10"))

# Redis
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Qdrant
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "knowbase_chunks_v2")

# Neo4j
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "graphiti_neo4j_pass")

# OSMOSIS API (pour tokens stats)
OSMOSIS_API_URL = os.getenv("OSMOSIS_API_URL", "http://localhost:8000")

# AWS
AWS_REGION = os.getenv("AWS_DEFAULT_REGION", "eu-central-1")
AWS_BURST_REGIONS = [r.strip() for r in os.getenv(
    "AWS_BURST_REGIONS", "eu-central-1,eu-west-3"
).split(",")]
AWS_EC2_TAG_KEY = "Project"
AWS_EC2_TAG_VALUE = "KnowWhere"
AWS_SCAN_CACHE_TTL = 15  # secondes

# LLM budget seuils
LLM_LOW_THRESHOLD = float(os.getenv("COCKPIT_LLM_LOW", "10.0"))
LLM_CRITICAL_THRESHOLD = float(os.getenv("COCKPIT_LLM_CRITICAL", "3.0"))

# ETA
ETA_DB_PATH = Path(os.getenv("COCKPIT_ETA_DB", str(Path(__file__).parent / "db" / "history.db")))

# Smart events
EVENT_MAX_AGE_S = 3600  # TTL par défaut
EVENT_STALL_THRESHOLD_S = 300  # 5min sans progression = stall
EVENT_SLOW_RATIO = 2.5  # > 2.5x la médiane = lent
EVENT_BURST_IDLE_S = 3600  # 1h burst idle = alerte

# Pipeline definitions
PIPELINE_DEFS_PATH = Path(os.getenv(
    "COCKPIT_PIPELINE_DEFS",
    str(Path(__file__).parent / "pipeline_defs.yaml"),
))

# Docker
DOCKER_GROUPS = {
    "infra": ["qdrant", "redis", "neo4j", "postgres"],
    "app": ["app", "ingestion-worker", "folder-watcher", "frontend"],
    "monitoring": ["loki", "promtail", "grafana"],
}

# Domain Pack containers : détectés dynamiquement par préfixe de nom
DOMAIN_PACK_PREFIX = "osmose-pack-"

# RAGAS Diagnostic
RAGAS_COLLECT_INTERVAL = float(os.getenv("COCKPIT_RAGAS_INTERVAL", "60"))
RAGAS_RESULTS_DIR = os.getenv(
    "COCKPIT_RAGAS_RESULTS_DIR",
    str(Path(__file__).parent.parent / "data" / "benchmark" / "results"),
)

# Static files
STATIC_DIR = Path(__file__).parent / "static"
