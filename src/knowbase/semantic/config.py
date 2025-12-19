"""
🌊 OSMOSE Semantic Intelligence V2.1 - Configuration

Gestion de la configuration pour le module semantic
Phase 1 V2.1: Concept-First, Language-Agnostic
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field
import yaml
from pathlib import Path
import logging
import os

logger = logging.getLogger(__name__)


# ===================================
# CONFIGURATIONS V2.1
# ===================================

class SegmentationConfig(BaseModel):
    """Configuration Topic Segmentation"""
    enabled: bool = True
    window_size: int = 3000
    overlap: float = 0.25
    cohesion_threshold: float = 0.65
    clustering_method: str = "HDBSCAN"
    clustering_fallback: str = "Agglomerative"
    min_cluster_size: int = 2
    max_windows_per_topic: int = 10


class ExtractionConfig(BaseModel):
    """Configuration Multilingual Concept Extraction"""
    enabled: bool = True
    methods: List[str] = ["NER", "CLUSTERING", "LLM"]
    min_concepts_per_topic: int = 5  # Augmenté de 2 à 5 pour forcer LLM sur textes denses
    max_concepts_per_topic: int = 15
    concept_types: List[str] = ["ENTITY", "PRACTICE", "STANDARD", "TOOL", "ROLE"]
    confidence_threshold: float = 0.7
    llm: Dict = {
        "model": "gpt-4o-mini",
        "temperature": 0.3,
        "max_tokens": 1500,
        "retry_attempts": 3
    }


class IndexingConfig(BaseModel):
    """Configuration Semantic Indexing & Canonicalization"""
    enabled: bool = True
    similarity_threshold: float = 0.85
    canonical_name_priority: str = "en"
    fallback_language: str = "original"
    hierarchy_construction: str = "LLM"
    hierarchy_max_depth: int = 3
    deduplication: bool = True
    deduplication_threshold: float = 0.90


class LinkingConfig(BaseModel):
    """Configuration Cross-Document Concept Linking"""
    enabled: bool = True
    document_roles: List[str] = ["DEFINES", "IMPLEMENTS", "AUDITS", "PROVES", "REFERENCES"]
    similarity_threshold: float = 0.75
    max_connections_per_doc: int = 20


class NERConfig(BaseModel):
    """Configuration NER Multilingue (spaCy)"""
    enabled: bool = True
    # Modèles medium (md) pour documents techniques SAP/RFP
    # Précision NER 85-90% (vs 75-80% pour sm)
    models: Dict[str, str] = {
        "en": "en_core_web_md",
        "fr": "fr_core_news_md",
        "xx": "xx_ent_wiki_sm"
    }
    entity_types: List[str] = ["ORG", "PRODUCT", "TECH", "LAW", "MISC"]
    batch_size: int = 16
    n_process: int = 1


class EmbeddingsConfig(BaseModel):
    """Configuration Embeddings Multilingues"""
    model: str = "intfloat/multilingual-e5-large"
    dimension: int = 1024
    device: str = "cpu"
    batch_size: int = 32
    normalize: bool = True
    cache_enabled: bool = True
    cache_size: int = 1000
    cache_ttl: int = 3600


class LanguageDetectionConfig(BaseModel):
    """Configuration Détection Langue (fasttext)"""
    enabled: bool = True
    model_path: str = "models/lid.176.bin"
    confidence_threshold: float = 0.8
    fallback_language: str = "en"
    supported_languages: List[str] = ["en", "fr", "de", "es", "it", "pt", "nl"]


class Neo4jProtoConfig(BaseModel):
    """Configuration Neo4j Proto-KG V2.1"""
    uri: str = Field(default_factory=lambda: os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    user: str = Field(default_factory=lambda: os.getenv("NEO4J_USER", "neo4j"))
    password: str = Field(default_factory=lambda: os.getenv("NEO4J_PASSWORD", "password"))
    database: str = "neo4j"
    labels: Dict[str, str] = {
        "document": "Document",
        "topic": "Topic",
        "concept": "Concept",
        "canonical_concept": "CanonicalConcept"
    }
    relationships: Dict[str, str] = {
        "has_topic": "HAS_TOPIC",
        "extracts_concept": "EXTRACTS_CONCEPT",
        "unified_as": "UNIFIED_AS",
        "parent_of": "PARENT_OF",
        "child_of": "CHILD_OF",
        "relates_to": "RELATES_TO",
        "mentions_in": "MENTIONS_IN"
    }
    indexes: List[str] = ["concept_name", "canonical_name", "concept_type", "language"]


class QdrantProtoConfig(BaseModel):
    """Configuration Qdrant Proto (Concepts) V2.1"""
    host: str = Field(default_factory=lambda: os.getenv("QDRANT_HOST", "localhost"))
    port: int = Field(default_factory=lambda: int(os.getenv("QDRANT_PORT", "6333")))
    collection_name: str = "concepts_proto"
    vector_size: int = 1024  # multilingual-e5-large
    distance: str = "Cosine"
    on_disk_payload: bool = True
    hnsw_config: Dict = {
        "m": 16,
        "ef_construct": 100
    }
    optimization: Dict = {
        "indexing_threshold": 10000
    }


class ProfilingConfig(BaseModel):
    """Configuration Profiling (conservé pour budget allocation)"""
    enabled: bool = True
    complexity_zones: bool = True
    complexity_levels: Dict[str, float] = {
        "simple": 0.33,
        "medium": 0.66,
        "complex": 1.0
    }
    domain_classification: bool = True
    supported_domains: List[str] = ["finance", "pharma", "consulting", "technology", "legal", "general"]


class PerformanceConfig(BaseModel):
    """Configuration Performance & Monitoring"""
    topic_segmentation_timeout: int = 60
    concept_extraction_timeout: int = 120
    indexing_timeout: int = 90
    linking_timeout: int = 60
    target_processing_time: int = 30
    target_cost_per_doc: float = 0.40
    track_metrics: bool = True
    metrics_retention_days: int = 30


class LoggingConfig(BaseModel):
    """Configuration Logging"""
    level: str = "INFO"
    format: str = "[OSMOSE] %(asctime)s - %(name)s - %(levelname)s - %(message)s"
    semantic_logger: str = "knowbase.semantic"
    log_extraction_details: bool = True
    log_canonicalization: bool = True
    log_performance: bool = True


class SemanticConfig(BaseModel):
    """Configuration complète du module semantic V2.1"""
    semantic: Dict = {
        "segmentation": {},
        "extraction": {},
        "indexing": {},
        "linking": {}
    }

    # Composants V2.1
    segmentation: SegmentationConfig = Field(default_factory=SegmentationConfig)
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    indexing: IndexingConfig = Field(default_factory=IndexingConfig)
    linking: LinkingConfig = Field(default_factory=LinkingConfig)

    # Infrastructure
    ner: NERConfig = Field(default_factory=NERConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    language_detection: LanguageDetectionConfig = Field(default_factory=LanguageDetectionConfig)

    # Storage
    neo4j_proto: Neo4jProtoConfig = Field(default_factory=Neo4jProtoConfig)
    qdrant_proto: QdrantProtoConfig = Field(default_factory=QdrantProtoConfig)

    # Monitoring
    profiling: ProfilingConfig = Field(default_factory=ProfilingConfig)
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


def load_semantic_config(config_path: Optional[Path] = None) -> SemanticConfig:
    """
    Charge la configuration depuis un fichier YAML V2.1.

    Args:
        config_path: Chemin vers le fichier de configuration
                     Par défaut: config/semantic_intelligence_v2.yaml

    Returns:
        SemanticConfig: Configuration chargée

    Raises:
        FileNotFoundError: Si le fichier n'existe pas
        ValueError: Si le fichier est invalide
    """
    if config_path is None:
        config_path = Path("config/semantic_intelligence_v2.yaml")

    if not config_path.exists():
        logger.warning(
            f"[OSMOSE] Fichier de configuration non trouvé: {config_path}. "
            "Utilisation configuration par défaut."
        )
        return SemanticConfig()

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f)

        # Adapter la structure du YAML pour Pydantic
        config_dict = {}

        if "semantic" in yaml_data:
            if "segmentation" in yaml_data["semantic"]:
                config_dict["segmentation"] = SegmentationConfig(**yaml_data["semantic"]["segmentation"])
            if "extraction" in yaml_data["semantic"]:
                config_dict["extraction"] = ExtractionConfig(**yaml_data["semantic"]["extraction"])
            if "indexing" in yaml_data["semantic"]:
                config_dict["indexing"] = IndexingConfig(**yaml_data["semantic"]["indexing"])
            if "linking" in yaml_data["semantic"]:
                config_dict["linking"] = LinkingConfig(**yaml_data["semantic"]["linking"])

        if "ner" in yaml_data:
            config_dict["ner"] = NERConfig(**yaml_data["ner"])
        if "embeddings" in yaml_data:
            config_dict["embeddings"] = EmbeddingsConfig(**yaml_data["embeddings"])
        if "language_detection" in yaml_data:
            config_dict["language_detection"] = LanguageDetectionConfig(**yaml_data["language_detection"])

        if "neo4j_proto" in yaml_data:
            config_dict["neo4j_proto"] = Neo4jProtoConfig(**yaml_data["neo4j_proto"])
        if "qdrant_proto" in yaml_data:
            config_dict["qdrant_proto"] = QdrantProtoConfig(**yaml_data["qdrant_proto"])

        if "profiling" in yaml_data:
            config_dict["profiling"] = ProfilingConfig(**yaml_data["profiling"])
        if "performance" in yaml_data:
            config_dict["performance"] = PerformanceConfig(**yaml_data["performance"])
        if "logging" in yaml_data:
            config_dict["logging"] = LoggingConfig(**yaml_data["logging"])

        config = SemanticConfig(**config_dict)
        logger.info(f"[OSMOSE] ✅ Configuration V2.1 chargée depuis {config_path}")
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
