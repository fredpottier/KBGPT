"""
Router API pour gestion catalogues d'ontologies.
"""
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from knowbase.api.schemas.ontology import (
    EntityCatalogCreate,
    EntityCatalogUpdate,
    EntityCatalogResponse,
    CatalogStatistics,
    UncatalogedEntity,
    UncatalogedEntityApprove,
    CatalogBulkImport,
    CatalogBulkImportResult,
)
from knowbase.api.services.ontology_service import OntologyService
from knowbase.common.entity_types import EntityType
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "ontology_router.log")

router = APIRouter(prefix="/ontology", tags=["ontology"])


# === Catalogues ===

@router.get("/catalogs/{entity_type}/entities", response_model=List[EntityCatalogResponse])
async def list_catalog_entities(
    entity_type: EntityType,
    category: Optional[str] = Query(None, description="Filtrer par catégorie"),
    vendor: Optional[str] = Query(None, description="Filtrer par vendor")
):
    """
    Liste toutes les entités d'un catalogue.

    **entity_type**: SOLUTION, COMPONENT, TECHNOLOGY, ORGANIZATION, PERSON, CONCEPT
    """
    try:
        service = OntologyService()
        entities = service.list_entities(
            entity_type=entity_type,
            category=category,
            vendor=vendor
        )
        return entities

    except Exception as e:
        logger.error(f"Erreur list_catalog_entities: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/catalogs/{entity_type}/entities/{entity_id}", response_model=EntityCatalogResponse)
async def get_catalog_entity(
    entity_type: EntityType,
    entity_id: str
):
    """Récupère une entité catalogue par ID."""
    try:
        service = OntologyService()
        entity = service.get_entity(entity_type=entity_type, entity_id=entity_id)

        if not entity:
            raise HTTPException(
                status_code=404,
                detail=f"Entity '{entity_id}' not found in {entity_type.value} catalog"
            )

        return entity

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Erreur get_catalog_entity: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/catalogs/entities", response_model=EntityCatalogResponse, status_code=201)
async def create_catalog_entity(entity_data: EntityCatalogCreate):
    """Crée une nouvelle entité dans un catalogue."""
    try:
        service = OntologyService()
        entity = service.create_entity(entity_data)
        return entity

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Erreur create_catalog_entity: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/catalogs/{entity_type}/entities/{entity_id}", response_model=EntityCatalogResponse)
async def update_catalog_entity(
    entity_type: EntityType,
    entity_id: str,
    update_data: EntityCatalogUpdate
):
    """Met à jour une entité catalogue."""
    try:
        service = OntologyService()
        entity = service.update_entity(
            entity_type=entity_type,
            entity_id=entity_id,
            update_data=update_data
        )
        return entity

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Erreur update_catalog_entity: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/catalogs/{entity_type}/entities/{entity_id}", status_code=204)
async def delete_catalog_entity(
    entity_type: EntityType,
    entity_id: str
):
    """Supprime une entité catalogue."""
    try:
        service = OntologyService()
        service.delete_entity(entity_type=entity_type, entity_id=entity_id)
        return None

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Erreur delete_catalog_entity: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# === Statistiques ===

@router.get("/catalogs/{entity_type}/statistics", response_model=CatalogStatistics)
async def get_catalog_statistics(entity_type: EntityType):
    """Retourne statistiques d'un catalogue."""
    try:
        service = OntologyService()
        stats = service.get_statistics(entity_type=entity_type)
        return stats

    except Exception as e:
        logger.error(f"Erreur get_catalog_statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# === Entités Non Cataloguées ===

@router.get("/uncataloged", response_model=List[UncatalogedEntity])
async def list_uncataloged_entities(
    entity_type: Optional[EntityType] = Query(None, description="Filtrer par type")
):
    """
    Liste toutes les entités non cataloguées détectées.

    Parse le fichier uncataloged_entities.log et agrège les résultats.
    """
    try:
        service = OntologyService()
        uncataloged = service.parse_uncataloged_log()

        # Filtrer par type si spécifié
        if entity_type:
            uncataloged = [
                e for e in uncataloged
                if e.entity_type == entity_type
            ]

        return uncataloged

    except Exception as e:
        logger.error(f"Erreur list_uncataloged_entities: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/uncataloged/{entity_type}/approve", response_model=EntityCatalogResponse)
async def approve_uncataloged_entity(
    entity_type: EntityType,
    raw_name: str = Query(..., description="Nom brut de l'entité à approuver"),
    approve_data: UncatalogedEntityApprove = None
):
    """
    Approuve une entité non cataloguée (ajoute au catalogue).

    Le raw_name est automatiquement ajouté aux aliases.
    """
    try:
        service = OntologyService()
        entity = service.approve_uncataloged(
            entity_type=entity_type,
            raw_name=raw_name,
            approve_data=approve_data
        )
        return entity

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Erreur approve_uncataloged_entity: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/uncataloged/{entity_type}/reject", status_code=204)
async def reject_uncataloged_entity(
    entity_type: EntityType,
    raw_name: str = Query(..., description="Nom brut de l'entité à rejeter")
):
    """Rejette une entité non cataloguée (supprime du log)."""
    try:
        service = OntologyService()
        service.reject_uncataloged(entity_type=entity_type, raw_name=raw_name)
        return None

    except Exception as e:
        logger.error(f"Erreur reject_uncataloged_entity: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# === Import en masse ===

@router.post("/catalogs/bulk-import", response_model=CatalogBulkImportResult)
async def bulk_import_catalog(import_data: CatalogBulkImport):
    """
    Import en masse d'entités dans un catalogue.

    Utile pour migration ou ajout de plusieurs entités d'un coup.
    """
    try:
        service = OntologyService()
        result = service.bulk_import(
            entity_type=import_data.entity_type,
            entities=import_data.entities,
            overwrite_existing=import_data.overwrite_existing
        )
        return result

    except Exception as e:
        logger.error(f"Erreur bulk_import_catalog: {e}")
        raise HTTPException(status_code=500, detail=str(e))


__all__ = ["router"]
