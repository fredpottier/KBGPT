from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

from .paths import (
    CONFIG_DIR,
    DATA_DIR,
    DOCS_DONE_DIR,
    DOCS_IN_DIR,
    LOGS_DIR,
    MODELS_DIR,
    ONTOLOGIES_DIR,
    PRESENTATIONS_DIR,
    PROJECT_ROOT,
    SLIDES_DIR,
    STATUS_DIR,
    THUMBNAILS_DIR,
    ensure_directories,
)


class Settings(BaseSettings):
    """Configuration centralisee du projet Knowbase."""

    debug_mode: bool = Field(default=False, alias="DEBUG_MODE")

    # === Modèles IA spécialisés ===
    # Modèle par défaut (rétrocompatibilité)
    gpt_model: str = Field(default="gpt-4o", alias="GPT_MODEL")

    # Modèles OpenAI spécialisés
    model_vision: str = Field(default="gpt-4o", alias="MODEL_VISION")
    model_metadata: str = Field(default="gpt-4o", alias="MODEL_METADATA")
    model_fast: str = Field(default="gpt-4o-mini", alias="MODEL_FAST")

    # Modèles Anthropic
    model_long_text: str = Field(default="claude-sonnet-4-20250514", alias="MODEL_LONG_TEXT")
    model_enrichment: str = Field(default="claude-3-haiku-20240307", alias="MODEL_ENRICHMENT")

    # Configuration clients
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    anthropic_api_key: Optional[str] = Field(default=None, alias="ANTHROPIC_API_KEY")

    # Configuration Neo4j
    neo4j_uri: str = Field(default="bolt://graphiti-neo4j:7687", alias="NEO4J_URI")
    neo4j_user: str = Field(default="neo4j", alias="NEO4J_USER")
    neo4j_password: str = Field(default="graphiti_neo4j_pass", alias="NEO4J_PASSWORD")

    embeddings_model: str = Field(
        default="intfloat/multilingual-e5-large", alias="EMB_MODEL_NAME"
    )
    qdrant_url: str = Field(default="http://qdrant:6333", alias="QDRANT_URL")
    qdrant_api_key: Optional[str] = Field(default=None, alias="QDRANT_API_KEY")
    qdrant_collection: str = Field(default="knowbase", alias="QDRANT_COLLECTION")
    qdrant_qa_collection: str = Field(default="rfp_qa", alias="QDRANT_QA_COLLECTION")
    hf_home: Path = Field(default=MODELS_DIR, alias="HF_HOME")

    # Configuration Redis (pour RQ jobs async)
    redis_host: str = Field(default="redis", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")

    config_dir: Path = Field(default=CONFIG_DIR)
    data_dir: Path = Field(default=DATA_DIR, alias="DATA_DIR")
    docs_in_dir: Path = Field(default=DOCS_IN_DIR)
    docs_done_dir: Path = Field(default=DOCS_DONE_DIR)
    logs_dir: Path = Field(default=LOGS_DIR)
    models_dir: Path = Field(default=MODELS_DIR)
    status_dir: Path = Field(default=STATUS_DIR)
    presentations_dir: Path = Field(default=PRESENTATIONS_DIR)
    slides_dir: Path = Field(default=SLIDES_DIR)
    thumbnails_dir: Path = Field(default=THUMBNAILS_DIR)
    ontologies_dir: Path = Field(default=ONTOLOGIES_DIR)  # Phase 3

    # === OSMOSE Configuration ===
    # Timeout central pour traitement documents (1 seule variable à configurer)
    max_document_processing_time: int = Field(
        default=3600,
        alias="MAX_DOCUMENT_PROCESSING_TIME",
        description="Durée maximale de traitement d'un document (secondes). "
        "Recommandation: 3600s (1h) pour documents < 300 slides, "
        "5400s (1h30) pour 300-500 slides, 7200s (2h) pour > 500 slides."
    )

    # Legacy: osmose_timeout_seconds - peut être fourni explicitement ou calculé auto
    osmose_timeout_seconds: int = Field(default=3600, alias="OSMOSE_TIMEOUT_SECONDS")

    @model_validator(mode='before')
    @classmethod
    def compute_derived_timeouts(cls, data: Any) -> Any:
        """
        Calcule automatiquement les timeouts dérivés depuis MAX_DOCUMENT_PROCESSING_TIME.
        Si OSMOSE_TIMEOUT_SECONDS n'est pas fourni explicitement, utilise MAX_DOCUMENT_PROCESSING_TIME.
        """
        if isinstance(data, dict):
            # Récupérer max_document_processing_time (via alias ou nom direct)
            max_time = data.get("MAX_DOCUMENT_PROCESSING_TIME") or data.get("max_document_processing_time") or 3600

            # Si OSMOSE_TIMEOUT_SECONDS n'est pas fourni, le calculer
            if "OSMOSE_TIMEOUT_SECONDS" not in data and "osmose_timeout_seconds" not in data:
                data["osmose_timeout_seconds"] = max_time

        return data

    @property
    def ingestion_job_timeout(self) -> int:
        """
        Timeout RQ job (avec buffer 50% au-dessus du timeout document).
        Si INGESTION_JOB_TIMEOUT est fourni explicitement, l'utilise.
        Sinon, calcule automatiquement: MAX_DOCUMENT_PROCESSING_TIME * 1.5
        """
        env_value = os.getenv("INGESTION_JOB_TIMEOUT")
        if env_value:
            return int(env_value)
        return int(self.max_document_processing_time * 1.5)

    # === Extraction Cache System (V2.2) ===
    enable_extraction_cache: bool = Field(default=True, alias="ENABLE_EXTRACTION_CACHE")
    extraction_cache_dir: Path = Field(default=DATA_DIR / "extraction_cache", alias="EXTRACTION_CACHE_DIR")
    cache_expiry_days: int = Field(default=30, alias="CACHE_EXPIRY_DAYS")
    allow_cache_upload: bool = Field(default=True, alias="ALLOW_CACHE_UPLOAD")

    class Config:
        env_file = PROJECT_ROOT / ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

    def configure_runtime(self) -> None:
        """Cree les repertoires utiles et configure les variables derivees."""
        ensure_directories(
            [
                self.data_dir,
                self.docs_in_dir,
                self.docs_done_dir,
                self.logs_dir,
                self.models_dir,
                self.status_dir,
                self.presentations_dir,
                self.slides_dir,
                self.thumbnails_dir,
                self.extraction_cache_dir,  # V2.2: Cache extraction
            ]
        )
        os.environ.setdefault("HF_HOME", str(self.hf_home))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()  # type: ignore[arg-type]
    settings.configure_runtime()
    return settings
