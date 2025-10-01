"""
Router API pour la canonicalisation d'entités
Endpoints pour bootstrap, suggestions, merge, et gouvernance entités
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Header
from fastapi.responses import JSONResponse

from knowbase.canonicalization.bootstrap import KGBootstrapService
from knowbase.canonicalization.service import CanonicalizationService
from knowbase.canonicalization.schemas import (
    BootstrapConfig,
    BootstrapResult,
    BootstrapProgress,
    MergeEntitiesRequest,
    MergeEntitiesResponse,
    CreateNewCanonicalRequest,
    CreateNewCanonicalResponse
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/canonicalization",
    tags=["canonicalization"],
    responses={404: {"description": "Not found"}},
)


# Singleton services (réutilisés entre requêtes)
_bootstrap_service: Optional[KGBootstrapService] = None
_canonicalization_service: Optional[CanonicalizationService] = None


def get_bootstrap_service() -> KGBootstrapService:
    """Dependency injection pour le service bootstrap"""
    global _bootstrap_service
    if _bootstrap_service is None:
        _bootstrap_service = KGBootstrapService()
    return _bootstrap_service


def get_canonicalization_service() -> CanonicalizationService:
    """Dependency injection pour le service canonicalization"""
    global _canonicalization_service
    if _canonicalization_service is None:
        _canonicalization_service = CanonicalizationService()
    return _canonicalization_service


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


@router.post("/merge", response_model=MergeEntitiesResponse)
async def merge_entities(
    request: MergeEntitiesRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    service: CanonicalizationService = Depends(get_canonicalization_service)
) -> MergeEntitiesResponse:
    """
    Merge entités candidates vers entité canonique existante

    **Idempotence garantie**: Header `Idempotency-Key` obligatoire.
    Replay avec même clé → résultat identique (bit-à-bit).

    **Logique**:
    - Valide canonical_entity existe
    - Valide candidates existent
    - Merge candidates → canonical (attributes, occurrences, confidence)
    - Marque candidates comme MERGED
    - Retourne résultat déterministe avec hash

    **Headers requis**:
    - `Idempotency-Key`: UUID unique identifiant opération (rejouable 24h)

    **Paramètres**:
    - `canonical_entity_id`: UUID entité canonique cible
    - `candidate_ids`: Liste UUIDs candidates à merger (min 1)
    - `user_id`: Utilisateur effectuant merge (optionnel)

    **Exemple requête**:
    ```bash
    curl -X POST /api/canonicalization/merge \\
      -H "Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000" \\
      -H "Content-Type: application/json" \\
      -d '{
        "canonical_entity_id": "abc123...",
        "candidate_ids": ["def456...", "ghi789..."],
        "user_id": "user_123"
      }'
    ```

    **Exemple réponse**:
    ```json
    {
      "canonical_entity_id": "abc123...",
      "merged_candidates": ["def456...", "ghi789..."],
      "merge_count": 2,
      "operation": "merge",
      "idempotency_key": "550e8400-e29b-41d4-a716-446655440000",
      "user_id": "user_123",
      "version_metadata": {...},
      "executed_at": "2025-10-01T00:00:00Z",
      "status": "completed",
      "result_hash": "a3f2bc8e..."
    }
    ```

    **Note**: Replay avec même `Idempotency-Key` retourne résultat mis en cache (TTL 24h).
    """
    try:
        logger.info(
            f"Merge demandé: canonical={request.canonical_entity_id[:8]}... "
            f"candidates={len(request.candidate_ids)} [key={idempotency_key[:12]}...]"
        )

        result = await service.merge_entities(
            canonical_entity_id=request.canonical_entity_id,
            candidate_ids=request.candidate_ids,
            idempotency_key=idempotency_key,
            user_id=request.user_id
        )

        logger.info(
            f"Merge terminé: canonical={request.canonical_entity_id[:8]}... "
            f"merged={len(request.candidate_ids)} hash={result['result_hash'][:12]}..."
        )

        return MergeEntitiesResponse(**result)

    except ValueError as e:
        logger.error(f"Erreur validation merge: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Erreur merge: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erreur interne merge")


@router.post("/create-new", response_model=CreateNewCanonicalResponse)
async def create_new_canonical(
    request: CreateNewCanonicalRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    service: CanonicalizationService = Depends(get_canonicalization_service)
) -> CreateNewCanonicalResponse:
    """
    Créer nouvelle entité canonique depuis candidates

    **Idempotence garantie**: Header `Idempotency-Key` obligatoire.
    Replay avec même clé → résultat identique (même UUID généré).

    **Logique**:
    - Valide candidates existent
    - Crée nouvelle entité canonique dans KG (UUID déterministe)
    - Lie candidates à nouvelle canonique
    - Marque candidates comme CANONICAL_CREATED
    - Retourne résultat déterministe avec hash

    **Headers requis**:
    - `Idempotency-Key`: UUID unique identifiant opération (rejouable 24h)

    **Paramètres**:
    - `candidate_ids`: Liste UUIDs candidates sources (min 1)
    - `canonical_name`: Nom entité canonique à créer
    - `entity_type`: Type entité (solution, product, concept, etc.)
    - `description`: Description optionnelle
    - `user_id`: Utilisateur effectuant création (optionnel)

    **Exemple requête**:
    ```bash
    curl -X POST /api/canonicalization/create-new \\
      -H "Idempotency-Key: 550e8400-e29b-41d4-a716-446655440001" \\
      -H "Content-Type: application/json" \\
      -d '{
        "candidate_ids": ["def456...", "ghi789..."],
        "canonical_name": "SAP S/4HANA Cloud",
        "entity_type": "solution",
        "description": "Cloud ERP solution",
        "user_id": "user_123"
      }'
    ```

    **Exemple réponse**:
    ```json
    {
      "canonical_entity_id": "xyz789...",
      "canonical_name": "SAP S/4HANA Cloud",
      "entity_type": "solution",
      "description": "Cloud ERP solution",
      "source_candidates": ["def456...", "ghi789..."],
      "candidate_count": 2,
      "operation": "create_new",
      "idempotency_key": "550e8400-e29b-41d4-a716-446655440001",
      "user_id": "user_123",
      "version_metadata": {...},
      "executed_at": "2025-10-01T00:00:00Z",
      "status": "created",
      "result_hash": "b4e3cd9f..."
    }
    ```

    **Note**: Replay avec même `Idempotency-Key` génère même UUID entité (déterministe).
    """
    try:
        logger.info(
            f"Create new canonical demandé: name='{request.canonical_name}' "
            f"candidates={len(request.candidate_ids)} [key={idempotency_key[:12]}...]"
        )

        result = await service.create_new_canonical(
            candidate_ids=request.candidate_ids,
            canonical_name=request.canonical_name,
            entity_type=request.entity_type,
            description=request.description,
            idempotency_key=idempotency_key,
            user_id=request.user_id
        )

        logger.info(
            f"Create new canonical terminé: id={result['canonical_entity_id'][:8]}... "
            f"name='{request.canonical_name}' hash={result['result_hash'][:12]}..."
        )

        return CreateNewCanonicalResponse(**result)

    except ValueError as e:
        logger.error(f"Erreur validation create-new: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Erreur create-new: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erreur interne create-new")
