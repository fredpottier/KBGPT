"""
🌊 OSMOSE Semantic Intelligence - Configuration

Gestion de la configuration pour le module semantic
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field
import yaml
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


class ProfilerConfig(BaseModel):
    """Configuration du Semantic Document Profiler"""
    enabled: bool = True
    complexity_thresholds: Dict[str, float] = {
        "simple": 0.3,
        "medium": 0.6,
        "complex": 0.9
    }
    domain_classification: Dict = {
        "enabled": True,
        "models": ["finance", "pharma", "consulting", "general"]
    }


class NarrativeDetectionConfig(BaseModel):
    """Configuration du Narrative Thread Detector"""
    enabled: bool = True
    min_confidence: float = 0.7
    causal_connectors: List[str] = [
        "because", "therefore", "as a result",
        "due to", "consequently", "leads to"
    ]
    temporal_markers: List[str] = [
        "revised", "updated", "replaced",
        "deprecated", "superseded", "evolved"
    ]
    reference_patterns: List[str] = [
        "refers to", "see section", "as mentioned in",
        "according to", "based on"
    ]


class SegmentationConfig(BaseModel):
    """Configuration du Intelligent Segmentation Engine"""
    enabled: bool = True
    min_cluster_size: int = 2
    max_cluster_size: int = 10
    similarity_threshold: float = 0.75
    preserve_narrative_context: bool = True


class BudgetAllocationConfig(BaseModel):
    """Configuration du budget token/coût"""
    default_per_doc: float = 2.0  # USD
    complexity_multipliers: Dict[str, float] = {
        "simple": 0.5,
        "medium": 1.0,
        "complex": 2.0
    }
    narrative_bonus: float = 0.3  # +30% si narrative threads détectés


class Neo4jProtoConfig(BaseModel):
    """Configuration Neo4j Proto-KG"""
    database: str = "neo4j"
    labels: Dict[str, str] = {
        "candidate_entity": "CandidateEntity",
        "candidate_relation": "CandidateRelation"
    }
    statuses: List[str] = [
        "PENDING_REVIEW",
        "AUTO_PROMOTED",
        "HUMAN_PROMOTED",
        "REJECTED"
    ]


class QdrantProtoConfig(BaseModel):
    """Configuration Qdrant Proto Collection"""
    collection_name: str = "knowwhere_proto"
    vector_size: int = 1536  # OpenAI text-embedding-3-small
    distance: str = "Cosine"


class SemanticConfig(BaseModel):
    """Configuration complète du module semantic"""
    project: Dict = {
        "name": "KnowWhere",
        "codename": "OSMOSE",
        "version": "1.0.0-alpha"
    }

    semantic_intelligence: Dict = {
        "enabled": True,
        "mode": "SEMANTIC"  # SEMANTIC | LEGACY
    }

    profiler: ProfilerConfig = Field(default_factory=ProfilerConfig)
    narrative_detection: NarrativeDetectionConfig = Field(default_factory=NarrativeDetectionConfig)
    segmentation: SegmentationConfig = Field(default_factory=SegmentationConfig)
    budget_allocation: BudgetAllocationConfig = Field(default_factory=BudgetAllocationConfig)
    neo4j_proto: Neo4jProtoConfig = Field(default_factory=Neo4jProtoConfig)
    qdrant_proto: QdrantProtoConfig = Field(default_factory=QdrantProtoConfig)


def load_semantic_config(config_path: Optional[Path] = None) -> SemanticConfig:
    """
    Charge la configuration depuis un fichier YAML.

    Args:
        config_path: Chemin vers le fichier de configuration
                     Par défaut: config/osmose_semantic_intelligence.yaml

    Returns:
        SemanticConfig: Configuration chargée

    Raises:
        FileNotFoundError: Si le fichier n'existe pas
        ValueError: Si le fichier est invalide
    """
    if config_path is None:
        config_path = Path("config/osmose_semantic_intelligence.yaml")

    if not config_path.exists():
        logger.warning(
            f"[OSMOSE] Fichier de configuration non trouvé: {config_path}. "
            "Utilisation configuration par défaut."
        )
        return SemanticConfig()

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f)

        config = SemanticConfig(**yaml_data)
        logger.info(f"[OSMOSE] ✅ Configuration chargée depuis {config_path}")
        return config

    except Exception as e:
        logger.error(f"[OSMOSE] ❌ Erreur chargement configuration: {e}")
        logger.warning("[OSMOSE] Utilisation configuration par défaut")
        return SemanticConfig()


# Instance globale (singleton pattern)
_semantic_config: Optional[SemanticConfig] = None


def get_semantic_config(reload: bool = False) -> SemanticConfig:
    """
    Récupère l'instance singleton de la configuration.

    Args:
        reload: Si True, recharge la configuration depuis le fichier

    Returns:
        SemanticConfig: Configuration globale
    """
    global _semantic_config

    if _semantic_config is None or reload:
        _semantic_config = load_semantic_config()

    return _semantic_config
