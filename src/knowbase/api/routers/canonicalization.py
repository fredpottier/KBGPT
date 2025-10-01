"""
Router API pour la canonicalisation d'entités
Endpoints pour bootstrap, suggestions, merge, et gouvernance entités
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import JSONResponse

from knowbase.canonicalization.bootstrap import KGBootstrapService
from knowbase.canonicalization.schemas import (
    BootstrapConfig,
    BootstrapResult,
    BootstrapProgress
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/canonicalization",
    tags=["canonicalization"],
    responses={404: {"description": "Not found"}},
)


# Singleton service (réutilisé entre requêtes)
_bootstrap_service: Optional[KGBootstrapService] = None


def get_bootstrap_service() -> KGBootstrapService:
    """Dependency injection pour le service bootstrap"""
    global _bootstrap_service
    if _bootstrap_service is None:
        _bootstrap_service = KGBootstrapService()
    return _bootstrap_service


@router.post("/bootstrap", response_model=BootstrapResult)
async def bootstrap_entities(
    config: BootstrapConfig,
    background_tasks: BackgroundTasks,
    service: KGBootstrapService = Depends(get_bootstrap_service)
) -> BootstrapResult:
    """
    Bootstrap automatique du Knowledge Graph

    Promeut automatiquement les entités candidates fréquentes en entités seed.

    **Logique** :
    - Récupère toutes les candidates avec status=CANDIDATE
    - Filtre selon min_occurrences (défaut: 10) et min_confidence (défaut: 0.8)
    - Promeut les entités qualifiées en status=SEED
    - Crée les entités canoniques dans le KG

    **Paramètres** :
    - `min_occurrences`: Minimum d'occurrences (défaut: 10)
    - `min_confidence`: Confidence minimale (défaut: 0.8)
    - `group_id`: Groupe à bootstrap (None = tous)
    - `entity_types`: Types d'entités à inclure (None = tous)
    - `dry_run`: Mode simulation sans modification (défaut: false)

    **Exemples** :
    ```json
    {
      "min_occurrences": 10,
      "min_confidence": 0.8,
      "group_id": "corporate",
      "entity_types": ["product", "solution"],
      "dry_run": false
    }
    ```

    **Note Phase 3** :
    Actuellement, aucune candidate n'existe car l'extraction automatique
    (Phase 3) n'est pas encore implémentée. Le bootstrap retournera 0 entité promue.
    Une fois Phase 3 implémentée, les candidates seront extraites automatiquement
    depuis les documents et le bootstrap fonctionnera normalement.
    """
    try:
        logger.info(
            f"Bootstrap demandé: min_occ={config.min_occurrences}, "
            f"min_conf={config.min_confidence}, dry_run={config.dry_run}"
        )

        # Exécuter le bootstrap
        result = await service.auto_bootstrap_from_candidates(config)

        logger.info(
            f"Bootstrap terminé: {result.promoted_seeds} seeds promues "
            f"en {result.duration_seconds:.2f}s"
        )

        return result

    except ValueError as e:
        logger.error(f"Configuration bootstrap invalide: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        logger.error(f"Erreur durant bootstrap: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Erreur inattendue bootstrap: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erreur interne bootstrap")


@router.get("/bootstrap/progress", response_model=Optional[BootstrapProgress])
async def get_bootstrap_progress(
    service: KGBootstrapService = Depends(get_bootstrap_service)
) -> Optional[BootstrapProgress]:
    """
    Récupère la progression du bootstrap en cours

    Returns:
        Progression actuelle avec statut, entités traitées/promues, etc.
        Retourne null si aucun bootstrap en cours.

    **Exemple réponse** :
    ```json
    {
      "status": "running",
      "processed": 45,
      "total": 120,
      "promoted": 12,
      "current_entity": "SAP S/4HANA Cloud",
      "started_at": "2025-10-01T10:30:00Z",
      "estimated_completion": "2025-10-01T10:35:00Z"
    }
    ```
    """
    progress = service.get_progress()

    if progress is None:
        return None

    return progress


@router.post("/bootstrap/estimate")
async def estimate_bootstrap(
    config: BootstrapConfig,
    service: KGBootstrapService = Depends(get_bootstrap_service)
) -> JSONResponse:
    """
    Estime le nombre d'entités qui seraient promues (sans modifier)

    Exécute un bootstrap en mode dry_run pour estimer le résultat.

    **Paramètres** :
    Mêmes que `/bootstrap` (dry_run sera forcé à true)

    **Exemple réponse** :
    ```json
    {
      "qualified_candidates": 23,
      "by_entity_type": {
        "product": 12,
        "solution": 8,
        "concept": 3
      },
      "estimated_duration_seconds": 2.5
    }
    ```
    """
    try:
        estimation = await service.estimate_bootstrap(config)
        return JSONResponse(content=estimation)

    except Exception as e:
        logger.error(f"Erreur estimation bootstrap: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erreur estimation bootstrap")
