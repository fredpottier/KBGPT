"""
Endpoints FastAPI pour la gestion des tenants multi-tenant
"""
from typing import List, Optional
from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends, Query, status
from pydantic import BaseModel

from ..schemas.tenant import (
    Tenant,
    TenantCreate,
    TenantUpdate,
    TenantListResponse,
    TenantStatus,
    UserTenantMembership,
    TenantHierarchy,
    TenantPermission
)
from ..services.tenant import get_tenant_service, TenantService
from ..dependencies import get_settings

router = APIRouter(prefix="/tenants", tags=["tenants"])


def get_tenant_service_dependency() -> TenantService:
    """Dependency pour obtenir le service de tenants"""
    settings = get_settings()
    data_dir = Path(settings.data_dir) / "tenants"
    return get_tenant_service(data_dir)


# Schémas spécifiques pour les endpoints

class TenantCreateRequest(BaseModel):
    """Requête de création de tenant"""
    tenant: TenantCreate
    created_by: str


class AddUserToTenantRequest(BaseModel):
    """Requête d'ajout d'utilisateur à un tenant"""
    user_id: str
    role: str = "member"
    permissions: Optional[List[str]] = None
    is_default: bool = False


class TenantStatsUpdate(BaseModel):
    """Mise à jour des statistiques d'un tenant"""
    users_count: Optional[int] = None
    episodes_count: Optional[int] = None
    facts_count: Optional[int] = None
    relations_count: Optional[int] = None
    documents_count: Optional[int] = None
    storage_size_mb: Optional[float] = None


# Endpoints

@router.post("/", response_model=Tenant, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    request: TenantCreateRequest,
    tenant_service: TenantService = Depends(get_tenant_service_dependency)
) -> Tenant:
    """
    Crée un nouveau tenant
    """
    try:
        # Vérifier que le nom n'existe pas déjà
        existing = tenant_service.get_tenant_by_name(request.tenant.name)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Un tenant avec le nom '{request.tenant.name}' existe déjà"
            )

        tenant = tenant_service.create_tenant(request.tenant, request.created_by)
        return tenant

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur création tenant: {str(e)}"
        )


@router.get("/", response_model=TenantListResponse)
async def list_tenants(
    page: int = Query(default=1, ge=1, description="Numéro de page"),
    page_size: int = Query(default=20, ge=1, le=100, description="Taille de page"),
    status_filter: Optional[TenantStatus] = Query(default=None, description="Filtre par statut"),
    parent_id: Optional[str] = Query(default=None, description="Filtre par tenant parent"),
    tenant_service: TenantService = Depends(get_tenant_service_dependency)
) -> TenantListResponse:
    """
    Liste les tenants avec pagination et filtres
    """
    try:
        tenants = tenant_service.list_tenants(
            page=page,
            page_size=page_size,
            status_filter=status_filter,
            parent_id_filter=parent_id
        )

        # Compter le total (approximatif pour éviter de recharger)
        all_tenants = tenant_service.list_tenants(page=1, page_size=1000)
        total = len(all_tenants)

        return TenantListResponse(
            tenants=tenants,
            total=total,
            page=page,
            page_size=page_size
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur listage tenants: {str(e)}"
        )


@router.get("/{tenant_id}", response_model=Tenant)
async def get_tenant(
    tenant_id: str,
    tenant_service: TenantService = Depends(get_tenant_service_dependency)
) -> Tenant:
    """
    Récupère un tenant par son ID
    """
    tenant = tenant_service.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} non trouvé"
        )

    return tenant


@router.put("/{tenant_id}", response_model=Tenant)
async def update_tenant(
    tenant_id: str,
    updates: TenantUpdate,
    tenant_service: TenantService = Depends(get_tenant_service_dependency)
) -> Tenant:
    """
    Met à jour un tenant
    """
    tenant = tenant_service.update_tenant(tenant_id, updates)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} non trouvé"
        )

    return tenant


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tenant(
    tenant_id: str,
    tenant_service: TenantService = Depends(get_tenant_service_dependency)
):
    """
    Supprime un tenant (archive)
    """
    success = tenant_service.delete_tenant(tenant_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} non trouvé"
        )


@router.post("/{tenant_id}/users", response_model=UserTenantMembership, status_code=status.HTTP_201_CREATED)
async def add_user_to_tenant(
    tenant_id: str,
    request: AddUserToTenantRequest,
    tenant_service: TenantService = Depends(get_tenant_service_dependency)
) -> UserTenantMembership:
    """
    Ajoute un utilisateur à un tenant
    """
    # Vérifier que le tenant existe
    tenant = tenant_service.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} non trouvé"
        )

    try:
        membership = tenant_service.add_user_to_tenant(
            user_id=request.user_id,
            tenant_id=tenant_id,
            role=request.role,
            permissions=request.permissions,
            is_default=request.is_default
        )
        return membership

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur ajout utilisateur: {str(e)}"
        )


@router.get("/{tenant_id}/users", response_model=List[UserTenantMembership])
async def get_tenant_users(
    tenant_id: str,
    tenant_service: TenantService = Depends(get_tenant_service_dependency)
) -> List[UserTenantMembership]:
    """
    Récupère tous les utilisateurs d'un tenant
    """
    # Vérifier que le tenant existe
    tenant = tenant_service.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} non trouvé"
        )

    return tenant_service.get_tenant_users(tenant_id)


@router.get("/{tenant_id}/hierarchy", response_model=TenantHierarchy)
async def get_tenant_hierarchy(
    tenant_id: str,
    tenant_service: TenantService = Depends(get_tenant_service_dependency)
) -> TenantHierarchy:
    """
    Récupère la hiérarchie d'un tenant avec ses enfants
    """
    hierarchy = tenant_service.get_tenant_hierarchy(tenant_id)
    if not hierarchy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} non trouvé"
        )

    return hierarchy


@router.put("/{tenant_id}/stats", status_code=status.HTTP_204_NO_CONTENT)
async def update_tenant_stats(
    tenant_id: str,
    stats: TenantStatsUpdate,
    tenant_service: TenantService = Depends(get_tenant_service_dependency)
):
    """
    Met à jour les statistiques d'un tenant
    """
    # Filtrer les valeurs non-None
    stats_dict = {k: v for k, v in stats.model_dump().items() if v is not None}

    success = tenant_service.update_tenant_stats(tenant_id, **stats_dict)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tenant {tenant_id} non trouvé"
        )


# Endpoints pour les utilisateurs

@router.get("/user/{user_id}/tenants", response_model=List[UserTenantMembership])
async def get_user_tenants(
    user_id: str,
    tenant_service: TenantService = Depends(get_tenant_service_dependency)
) -> List[UserTenantMembership]:
    """
    Récupère tous les tenants d'un utilisateur
    """
    return tenant_service.get_user_tenants(user_id)


@router.get("/user/{user_id}/default-tenant")
async def get_user_default_tenant(
    user_id: str,
    tenant_service: TenantService = Depends(get_tenant_service_dependency)
) -> dict:
    """
    Récupère le tenant par défaut d'un utilisateur
    """
    default_tenant_id = tenant_service.get_default_tenant_for_user(user_id)

    if not default_tenant_id:
        return {"default_tenant_id": None, "message": "Aucun tenant par défaut"}

    tenant = tenant_service.get_tenant(default_tenant_id)
    return {
        "default_tenant_id": default_tenant_id,
        "tenant": tenant
    }


@router.post("/user/{user_id}/check-permission")
async def check_user_permission(
    user_id: str,
    tenant_id: str = Query(..., description="ID du tenant"),
    permission: TenantPermission = Query(..., description="Permission à vérifier"),
    tenant_service: TenantService = Depends(get_tenant_service_dependency)
) -> dict:
    """
    Vérifie si un utilisateur a une permission dans un tenant
    """
    has_permission = tenant_service.user_has_permission(user_id, tenant_id, permission)

    return {
        "user_id": user_id,
        "tenant_id": tenant_id,
        "permission": permission.value,
        "has_permission": has_permission
    }


# Endpoint utilitaire pour initialiser des tenants par défaut

@router.post("/initialize-defaults", status_code=status.HTTP_201_CREATED)
async def initialize_default_tenants(
    created_by: str = Query(..., description="ID de l'utilisateur créateur"),
    tenant_service: TenantService = Depends(get_tenant_service_dependency)
) -> dict:
    """
    Initialise des tenants par défaut pour démarrer
    """
    try:
        created_tenants = []

        # Tenant enterprise par défaut
        if not tenant_service.get_tenant_by_name("sap_kb_enterprise"):
            enterprise_tenant = tenant_service.create_tenant(
                TenantCreate(
                    name="sap_kb_enterprise",
                    display_name="SAP Knowledge Base Enterprise",
                    description="Tenant enterprise principal pour SAP KB",
                    tenant_type="enterprise",
                    metadata={"is_default": True, "auto_created": True}
                ),
                created_by=created_by
            )
            created_tenants.append(enterprise_tenant.id)

        # Tenant projet par défaut
        if not tenant_service.get_tenant_by_name("sap_kb_default"):
            default_tenant = tenant_service.create_tenant(
                TenantCreate(
                    name="sap_kb_default",
                    display_name="SAP KB - Projet par défaut",
                    description="Tenant par défaut pour nouveaux utilisateurs",
                    tenant_type="project",
                    parent_tenant_id=created_tenants[0] if created_tenants else None,
                    metadata={"is_default": True, "auto_created": True}
                ),
                created_by=created_by
            )
            created_tenants.append(default_tenant.id)

        return {
            "message": f"{len(created_tenants)} tenants par défaut créés",
            "created_tenant_ids": created_tenants
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur initialisation tenants: {str(e)}"
        )