"""
Router Admin API - Phase 1 Critère 1.5

Endpoints administration pour opérations de maintenance (migration, diagnostics, etc.)
"""

from fastapi import APIRouter, HTTPException
from typing import Optional
from pydantic import BaseModel, Field

from knowbase.migration.qdrant_graphiti_migration import (
    migrate_tenant,
    analyze_migration_needs,
    MigrationStats
)

router = APIRouter(prefix="/admin", tags=["admin"])


# Schémas requête/réponse
class MigrationRequest(BaseModel):
    """Requête migration Qdrant → Graphiti"""
    tenant_id: str = Field(..., description="ID tenant à migrer")
    collection_name: str = Field("knowbase", description="Collection Qdrant")
    dry_run: bool = Field(True, description="Simulation sans modification (défaut: True)")
    extract_entities: bool = Field(False, description="Extraire entities via LLM (coûteux)")
    limit: Optional[int] = Field(None, description="Limite nombre chunks (None = tous)")


class MigrationResponse(BaseModel):
    """Réponse migration"""
    status: str = Field(..., description="success ou error")
    stats: dict = Field(..., description="Statistiques migration")
    message: str = Field(..., description="Message résumé")


class AnalysisRequest(BaseModel):
    """Requête analyse migration"""
    tenant_id: str = Field(..., description="ID tenant à analyser")
    collection_name: str = Field("knowbase", description="Collection Qdrant")


@router.post("/migrate/qdrant-to-graphiti", response_model=MigrationResponse)
async def migrate_qdrant_to_graphiti(request: MigrationRequest):
    """
    Migrer chunks Qdrant existants → episodes Graphiti (Phase 1 Critère 1.5)

    Cette opération migre les chunks Qdrant sans knowledge graph vers Graphiti.

    **Workflow**:
    1. Récupère chunks sans KG depuis Qdrant
    2. Groupe par source (filename, import_id)
    3. Crée episodes Graphiti (avec entities/relations si extract_entities=True)
    4. Update metadata chunks Qdrant (episode_id, has_knowledge_graph)

    **Modes**:
    - dry_run=True (défaut): Simulation sans modification
    - dry_run=False: Migration réelle (ATTENTION: modifie les données!)

    **Extraction entities**:
    - extract_entities=False (défaut): Pas d'extraction LLM (rapide, pas de coût)
    - extract_entities=True: Extraction entities via LLM (lent, coûteux)

    Args:
        request: MigrationRequest avec tenant_id, options

    Returns:
        MigrationResponse avec statistiques détaillées

    Example:
        ```python
        POST /admin/migrate/qdrant-to-graphiti
        {
            "tenant_id": "acme_corp",
            "dry_run": true,
            "extract_entities": false
        }
        ```

    Raises:
        HTTPException 400: Paramètres invalides
        HTTPException 500: Erreur migration
    """
    try:
        # Validation tenant_id
        if not request.tenant_id or len(request.tenant_id) > 100:
            raise HTTPException(
                status_code=400,
                detail="tenant_id invalide (max 100 chars)"
            )

        # Exécution migration
        stats = await migrate_tenant(
            tenant_id=request.tenant_id,
            collection_name=request.collection_name,
            dry_run=request.dry_run,
            extract_entities=request.extract_entities,
            limit=request.limit
        )

        # Construction réponse
        if stats.errors > 0:
            message = f"Migration terminée avec {stats.errors} erreur(s) - {stats.chunks_migrated}/{stats.chunks_to_migrate} chunks migrés"
            status = "partial_success"
        else:
            message = f"Migration réussie - {stats.chunks_migrated} chunks migrés, {stats.episodes_created} episodes créés"
            status = "success"

        if stats.dry_run:
            message = f"[DRY-RUN] {message}"

        return MigrationResponse(
            status=status,
            stats=stats.to_dict(),
            message=message
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur migration: {str(e)}"
        )


@router.post("/migrate/analyze", response_model=dict)
async def analyze_migration(request: AnalysisRequest):
    """
    Analyser besoins migration sans modifier données

    Retourne statistiques sur chunks à migrer, sources, etc.

    Args:
        request: AnalysisRequest avec tenant_id

    Returns:
        Dict avec analyse détaillée:
        - chunks_total: Total chunks Qdrant
        - chunks_with_kg: Chunks déjà avec knowledge graph
        - chunks_without_kg: Chunks à migrer
        - sources_count: Nombre sources identifiées
        - top_sources: Top 10 sources par nombre de chunks
        - migration_recommended: Boolean recommandation

    Example:
        ```python
        POST /admin/migrate/analyze
        {
            "tenant_id": "acme_corp"
        }
        ```

    Raises:
        HTTPException 400: Paramètres invalides
        HTTPException 500: Erreur analyse
    """
    try:
        # Validation
        if not request.tenant_id:
            raise HTTPException(status_code=400, detail="tenant_id requis")

        # Analyse
        analysis = await analyze_migration_needs(
            tenant_id=request.tenant_id,
            collection_name=request.collection_name
        )

        return analysis

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur analyse: {str(e)}"
        )


__all__ = ["router"]
