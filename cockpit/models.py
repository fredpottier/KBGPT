"""
OSMOSIS Cockpit — Modèle d'état canonique.

Représente l'état complet du cockpit à un instant donné.
Chaque widget lit un sous-ensemble de CockpitState.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


@dataclass
class BurstStatus:
    active: bool = False
    status: str = "off"  # off|starting|booting|ready|processing|stopping|failed
    instance_ip: Optional[str] = None
    instance_id: Optional[str] = None
    instance_type: Optional[str] = None
    instance_state: Optional[str] = None  # état AWS brut (running|pending|stopping)
    uptime_s: Optional[int] = None
    vllm_healthy: bool = False
    tei_healthy: bool = False
    job_name: Optional[str] = None
    docs_done: Optional[int] = None
    docs_total: Optional[int] = None
    # Métriques de charge vLLM/TEI
    vllm_requests_running: int = 0
    vllm_requests_waiting: int = 0
    vllm_gpu_cache_pct: float = 0.0
    vllm_tokens_per_sec: float = 0.0   # Débit tokens/s (delta entre 2 collectes)
    tei_queue_size: int = 0


@dataclass
class StageStatus:
    name: str
    short_name: str  # 5-6 chars pour rendu SVG
    status: str = "pending"  # done|running|pending|failed|skipped
    duration_s: Optional[float] = None
    progress: Optional[float] = None  # 0.0-1.0
    detail: Optional[str] = None


@dataclass
class PipelineStatus:
    name: str  # claim-first|post-import|burst-extract
    run_id: str = ""
    started_at: Optional[str] = None
    elapsed_s: int = 0
    stages: list[StageStatus] = field(default_factory=list)
    current_stage_index: int = -1
    eta_remaining_s: Optional[int] = None
    eta_finish: Optional[str] = None
    eta_confidence: str = "unknown"  # high|medium|low|unknown


@dataclass
class ContainerStatus:
    name: str
    status: str = "unknown"  # up|down|starting|removing
    health: Optional[str] = None  # healthy|unhealthy|None
    uptime_s: Optional[int] = None
    cpu_percent: float = 0.0
    mem_percent: float = 0.0
    activity: str = "idle"  # idle|active|busy


@dataclass
class ContainerGroupStatus:
    name: str  # infra|app|monitoring
    containers: list[ContainerStatus] = field(default_factory=list)


@dataclass
class KnowledgeStatus:
    qdrant_ok: bool = False
    qdrant_chunks: int = 0
    qdrant_collections: int = 0
    neo4j_ok: bool = False
    neo4j_nodes: int = 0
    neo4j_claims: int = 0
    neo4j_entities: int = 0
    neo4j_facets: int = 0
    neo4j_relations: int = 0
    neo4j_contradictions: int = 0
    last_refresh: Optional[str] = None


@dataclass
class LLMSessionStatus:
    session_cost_usd: float = 0.0
    session_started_at: Optional[str] = None
    session_calls: int = 0
    session_breakdown: dict = field(default_factory=dict)  # {model: cost}
    cost_per_minute: float = 0.0


@dataclass
class LLMBalanceStatus:
    openai_balance: Optional[float] = None
    openai_status: str = "unknown"  # ok|low|critical|unknown
    anthropic_balance: Optional[float] = None
    anthropic_status: str = "unknown"
    low_threshold: float = 10.0
    critical_threshold: float = 3.0


@dataclass
class RagasReport:
    faithfulness: float = 0.0
    context_relevance: float = 0.0
    sample_count: int = 0
    label: str = "OSMOSIS"
    timestamp: str = ""
    diagnostic: str = ""
    worst_samples: list = field(default_factory=list)  # [{question, faithfulness}]


@dataclass
class T2T5Report:
    tension_mentioned: float = 0.0
    both_sides_surfaced: float = 0.0
    both_sources_cited: float = 0.0
    proactive_detection: float = 0.0
    chain_coverage: float = 0.0
    multi_doc_cited: float = 0.0
    t2_count: int = 0
    t5_count: int = 0
    total_evaluated: int = 0
    timestamp: str = ""


@dataclass
class SmartEvent:
    timestamp: str
    severity: str  # info|warning|critical
    category: str  # pipeline|container|knowledge|budget|burst
    message: str
    ttl_s: int = 3600


@dataclass
class CockpitState:
    timestamp: str = ""
    burst: BurstStatus = field(default_factory=BurstStatus)
    pipelines: list[PipelineStatus] = field(default_factory=list)
    container_groups: list[ContainerGroupStatus] = field(default_factory=list)
    knowledge: KnowledgeStatus = field(default_factory=KnowledgeStatus)
    llm_session: LLMSessionStatus = field(default_factory=LLMSessionStatus)
    llm_balances: LLMBalanceStatus = field(default_factory=LLMBalanceStatus)
    ragas: Optional[RagasReport] = None
    t2t5: Optional[T2T5Report] = None
    events: list[SmartEvent] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)
