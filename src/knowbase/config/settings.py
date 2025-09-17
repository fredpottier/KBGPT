from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import BaseSettings, Field

from .paths import (
    DOCS_DONE_DIR,
    DOCS_IN_DIR,
    LOGS_DIR,
    MODELS_DIR,
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
    gpt_model: str = Field(default="gpt-4o", alias="GPT_MODEL")
    embeddings_model: str = Field(
        default="intfloat/multilingual-e5-base", alias="EMB_MODEL_NAME"
    )
    qdrant_url: str = Field(default="http://qdrant:6333", alias="QDRANT_URL")
    qdrant_api_key: Optional[str] = Field(default=None, alias="QDRANT_API_KEY")
    qdrant_collection: str = Field(default="sap_kb", alias="QDRANT_COLLECTION")
    hf_home: Path = Field(default=MODELS_DIR, alias="HF_HOME")
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")

    docs_in_dir: Path = Field(default=DOCS_IN_DIR)
    docs_done_dir: Path = Field(default=DOCS_DONE_DIR)
    logs_dir: Path = Field(default=LOGS_DIR)
    models_dir: Path = Field(default=MODELS_DIR)
    status_dir: Path = Field(default=STATUS_DIR)
    presentations_dir: Path = Field(default=PRESENTATIONS_DIR)
    slides_dir: Path = Field(default=SLIDES_DIR)
    thumbnails_dir: Path = Field(default=THUMBNAILS_DIR)

    class Config:
        env_file = PROJECT_ROOT / ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

    def configure_runtime(self) -> None:
        """Cree les repertoires utiles et configure les variables derivees."""
        ensure_directories(
            [
                self.docs_in_dir,
                self.docs_done_dir,
                self.logs_dir,
                self.models_dir,
                self.status_dir,
                self.presentations_dir,
                self.slides_dir,
                self.thumbnails_dir,
            ]
        )
        os.environ.setdefault("HF_HOME", str(self.hf_home))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()  # type: ignore[arg-type]
    settings.configure_runtime()
    return settings
