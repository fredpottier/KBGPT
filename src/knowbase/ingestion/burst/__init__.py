"""
OSMOSE Burst Ingestion Mode

Architecture pour ingestion massive sur EC2 Spot éphémère :
- BurstOrchestrator : orchestration complète du cycle de vie
- Provider Switch : basculement dynamique LLM/Embeddings vers EC2
- Resilient Client : gestion retries et interruptions Spot
- Types : BurstState, BurstStatus, BurstConfig

Flow Mode Burst (v2.0) :
1. Admin active Burst → BurstOrchestrator.prepare_batch()
2. Infrastructure → BurstOrchestrator.start_infrastructure()
3. Provider Switch → LLMRouter et EmbeddingManager basculent vers EC2
4. Pipeline local → appels API vers EC2 Spot via providers
5. Fin batch → cleanup automatique, retour mode normal

Author: OSMOSE Burst Ingestion
Date: 2025-12
"""

# Types et Enums
from .types import (
    BurstStatus,
    BurstState,
    BurstConfig,
    BurstEvent,
    DocumentStatus,
    EventSeverity,
)

# Orchestrateur principal
from .orchestrator import (
    BurstOrchestrator,
    BurstOrchestrationError,
    get_burst_orchestrator,
    reset_burst_orchestrator,
)

# Provider Switch
from .provider_switch import (
    activate_burst_providers,
    deactivate_burst_providers,
    get_burst_providers_status,
    check_burst_providers_health,
)

# Resilient Client
from .resilient_client import (
    ResilientBurstClient,
    BurstProviderUnavailable,
    SpotInterruptionDetected,
    RetryConfig,
    create_resilient_vllm_client,
    create_resilient_embeddings_client,
)

# Artifact Export/Import (pour mode hybride si nécessaire)
from .artifact_exporter import (
    ArtifactExporter,
    ExportedArtifact,
    export_ingestion_artifacts,
)
from .artifact_importer import (
    ArtifactImporter,
    import_artifacts_to_qdrant,
    import_artifacts_to_neo4j,
)

__all__ = [
    # Types
    "BurstStatus",
    "BurstState",
    "BurstConfig",
    "BurstEvent",
    "DocumentStatus",
    "EventSeverity",
    # Orchestrator
    "BurstOrchestrator",
    "BurstOrchestrationError",
    "get_burst_orchestrator",
    "reset_burst_orchestrator",
    # Provider Switch
    "activate_burst_providers",
    "deactivate_burst_providers",
    "get_burst_providers_status",
    "check_burst_providers_health",
    # Resilient Client
    "ResilientBurstClient",
    "BurstProviderUnavailable",
    "SpotInterruptionDetected",
    "RetryConfig",
    "create_resilient_vllm_client",
    "create_resilient_embeddings_client",
    # Artifacts
    "ArtifactExporter",
    "ExportedArtifact",
    "export_ingestion_artifacts",
    "ArtifactImporter",
    "import_artifacts_to_qdrant",
    "import_artifacts_to_neo4j",
]
