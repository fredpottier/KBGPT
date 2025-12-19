from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    """
    Requête de recherche sémantique avec support Graph-Guided RAG (OSMOSE).
    """
    question: str = Field(..., description="Question de l'utilisateur")
    language: str | None = Field(None, description="Langue de la question (auto-détecté si non spécifié)")
    mime: str | None = Field(None, description="Filtre par type MIME")
    solution: str | None = Field(None, description="Filtre par solution SAP")

    # 🌊 OSMOSE Graph-Guided RAG options
    use_graph_context: bool = Field(
        default=True,
        description="Activer l'enrichissement Knowledge Graph (OSMOSE Graph-Guided RAG)"
    )
    graph_enrichment_level: Literal["none", "light", "standard", "deep"] = Field(
        default="standard",
        description="""
        Niveau d'enrichissement Knowledge Graph:
        - none: Pas d'enrichissement (RAG classique)
        - light: Concepts liés uniquement
        - standard: Concepts + relations transitives
        - deep: Tout (concepts, transitives, clusters, bridges)
        """
    )

    class Config:
        json_schema_extra = {
            "example": {
                "question": "Quels sont les effets du Remdesivir sur les patients COVID-19 ?",
                "use_graph_context": True,
                "graph_enrichment_level": "standard"
            }
        }


__all__ = ["SearchRequest"]
