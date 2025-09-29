from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from knowbase.api.schemas.user import User, UserCreate, UserListResponse, UserUpdate
from knowbase.api.services.user import user_service

router = APIRouter(tags=["users"])


@router.get("/users", response_model=UserListResponse)
def list_users():
    """Récupère la liste de tous les utilisateurs."""
    try:
        users = user_service.list_users()
        return UserListResponse(users=users, total=len(users))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération des utilisateurs: {str(e)}"
        )


@router.get("/users/default", response_model=User)
def get_default_user():
    """Récupère l'utilisateur par défaut."""
    try:
        default_user = user_service.get_default_user()
        if not default_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Aucun utilisateur par défaut défini"
            )
        return default_user
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération de l'utilisateur par défaut: {str(e)}"
        )


@router.get("/users/{user_id}", response_model=User)
def get_user(user_id: str):
    """Récupère un utilisateur par son ID."""
    try:
        user = user_service.get_user(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Utilisateur avec l'ID '{user_id}' introuvable"
            )
        return user
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la récupération de l'utilisateur: {str(e)}"
        )


@router.post("/users", response_model=User, status_code=status.HTTP_201_CREATED)
def create_user(user_data: UserCreate):
    """Crée un nouveau utilisateur."""
    try:
        user = user_service.create_user(user_data)
        return user
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la création de l'utilisateur: {str(e)}"
        )


@router.put("/users/{user_id}", response_model=User)
def update_user(user_id: str, user_update: UserUpdate):
    """Met à jour un utilisateur existant."""
    try:
        updated_user = user_service.update_user(user_id, user_update)
        if not updated_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Utilisateur avec l'ID '{user_id}' introuvable"
            )
        return updated_user
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la mise à jour de l'utilisateur: {str(e)}"
        )


@router.delete("/users/{user_id}")
def delete_user(user_id: str):
    """Supprime un utilisateur."""
    try:
        success = user_service.delete_user(user_id)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Utilisateur avec l'ID '{user_id}' introuvable"
            )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"message": f"Utilisateur '{user_id}' supprimé avec succès"}
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la suppression de l'utilisateur: {str(e)}"
        )


@router.post("/users/{user_id}/activity")
def update_user_activity(user_id: str):
    """Met à jour la dernière activité d'un utilisateur."""
    try:
        user = user_service.get_user(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Utilisateur avec l'ID '{user_id}' introuvable"
            )

        user_service.update_last_active(user_id)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"message": "Activité utilisateur mise à jour"}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la mise à jour de l'activité: {str(e)}"
        )


@router.post("/users/{user_id}/set-default", response_model=User)
def set_default_user(user_id: str):
    """Définit un utilisateur comme utilisateur par défaut."""
    try:
        updated_user = user_service.set_default_user(user_id)
        if not updated_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Utilisateur avec l'ID '{user_id}' introuvable"
            )
        return updated_user
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erreur lors de la définition de l'utilisateur par défaut: {str(e)}"
        )


__all__ = ["router"]