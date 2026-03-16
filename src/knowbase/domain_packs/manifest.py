# src/knowbase/domain_packs/manifest.py
"""
PackManifest — Modèle Pydantic pour le manifest.json d'un Domain Pack.

Chaque pack est un artefact distribuable (.osmpack = zip) contenant
un manifest.json qui décrit son identité et son contrat.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Dict, List, Optional


class ContainerSpec(BaseModel):
    """Spécification du container sidecar du pack."""
    port: int = Field(..., description="Port interne du container")
    health_endpoint: str = Field(default="/health")
    extract_endpoint: str = Field(default="/extract")
    memory_limit: str = Field(default="512m")
    build_args: Dict[str, str] = Field(default_factory=dict)


class ProvidesSpec(BaseModel):
    """Ce que le pack fournit comme capacités NER."""
    entity_types: List[str] = Field(default_factory=list)
    ner_model: str = Field(default="")
    ner_model_size_mb: int = Field(default=0)


class PackManifest(BaseModel):
    """Manifest complet d'un Domain Pack (.osmpack)."""
    schema_version: int = Field(default=1)
    name: str
    display_name: str
    description: str
    version: str = Field(default="1.0.0")
    author: str = Field(default="")
    min_core_version: str = Field(default="2.0.0")

    container: ContainerSpec
    provides: ProvidesSpec = Field(default_factory=ProvidesSpec)


class PackState:
    """États possibles d'un pack."""
    NOT_INSTALLED = "not_installed"
    INSTALLED = "installed"      # Image buildée, container non démarré
    ACTIVE = "active"            # Container en cours d'exécution
    ERROR = "error"              # Container en erreur


__all__ = ["PackManifest", "ContainerSpec", "ProvidesSpec", "PackState"]
