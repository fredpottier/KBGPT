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

    # 🧠 Memory Layer - Session Context (Phase 2.5)
    session_id: str | None = Field(
        None,
        description="ID de session pour contexte conversationnel (Memory Layer Phase 2.5)"
    )

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

    # 🔍 OSMOSE Graph-First Search (Topics/COVERS routing)
    use_graph_first: bool = Field(
        default=True,
        description="""
        Activer le runtime Graph-First (ADR Phase C).
        Utilise les Topics et relations COVERS pour router vers les documents pertinents.
        Modes: REASONED (paths sémantiques), ANCHORED (Topics/COVERS), TEXT_ONLY (fallback)
        """
    )

    # 🔗 OSMOSE KG Traversal (multi-hop CHAINS_TO)
    use_kg_traversal: bool = Field(
        default=True,
        description="Activer la traversée multi-hop CHAINS_TO dans le Knowledge Graph pour le raisonnement transitif cross-document"
    )

    # 🎯 OSMOSE Assertion-Centric
    use_instrumented: bool = Field(
        default=False,
        description="Activer les reponses instrumentees (Assertion-Centric UX)"
    )

    # 🔄 OSMOSE Version/Release filtering (Phase B)
    release_id: str | None = Field(
        None,
        description="Filtre par release/version (ex: '2023')"
    )
    use_latest: bool = Field(
        default=True,
        description="Préférer la version la plus récente si aucune release spécifiée"
    )

    # 🎯 V3 Response Mode Override (admin/benchmark)
    response_mode: str | None = Field(
        None,
        description="Override du mode de reponse (DIRECT, AUGMENTED, TENSION, STRUCTURED_FACT). Auto-detect si non specifie."
    )

    # 📊 Benchmark mode : skip les appels LLM coûteux non nécessaires pour l'évaluation
    skip_tension_summary: bool = Field(
        default=False,
        description="Skip la génération de résumés de tensions (économise les crédits LLM pendant les benchmarks)"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "question": "Quels sont les effets du Remdesivir sur les patients COVID-19 ?",
                "session_id": "optional-session-uuid",
                "use_graph_context": True,
                "graph_enrichment_level": "standard"
            }
        }


class RelatedArticle(BaseModel):
    """Article Atlas lié à la réponse search."""
    slug: str
    title: str
    importance_tier: int
    matched_entity: str
    is_recommended: bool = False


class InsightHint(BaseModel):
    """Insight proactif pour guider l'utilisateur."""
    type: str = Field(..., description="contradiction | low_coverage | related_concept | structuring_concept")
    message: str
    priority: int = Field(..., description="1=highest")
    action_label: str | None = None
    action_href: str | None = None


__all__ = ["SearchRequest", "RelatedArticle", "InsightHint"]
