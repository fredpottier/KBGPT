from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from knowbase.api.schemas.user import User, UserCreate, UserRole, UserUpdate
from knowbase.config.settings import get_settings


class UserService:
    """Service de gestion des utilisateurs avec persistance JSON."""

    def __init__(self):
        self.settings = get_settings()
        self.users_file = self.settings.data_dir / "users.json"
        self._ensure_users_file()

    def _ensure_users_file(self) -> None:
        """S'assure que le fichier utilisateurs existe avec des données par défaut."""
        if not self.users_file.exists():
            # Créer utilisateur par défaut
            default_users = [
                {
                    "id": "default-user",
                    "name": "Utilisateur par défaut",
                    "email": None,
                    "role": "user",
                    "is_default": True,
                    "created_at": datetime.now().isoformat(),
                    "last_active": datetime.now().isoformat(),
                }
            ]
            self._save_users(default_users)

    def _load_users(self) -> List[dict]:
        """Charge la liste des utilisateurs depuis le fichier JSON."""
        try:
            with open(self.users_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _save_users(self, users_data: List[dict]) -> None:
        """Sauvegarde la liste des utilisateurs dans le fichier JSON."""
        with open(self.users_file, "w", encoding="utf-8") as f:
            json.dump(users_data, f, ensure_ascii=False, indent=2)

    def list_users(self) -> List[User]:
        """Retourne la liste de tous les utilisateurs."""
        users_data = self._load_users()
        return [User(**user_data) for user_data in users_data]

    def get_user(self, user_id: str) -> Optional[User]:
        """Récupère un utilisateur par son ID."""
        users_data = self._load_users()
        for user_data in users_data:
            if user_data["id"] == user_id:
                return User(**user_data)
        return None

    def create_user(self, user_data: UserCreate) -> User:
        """Crée un nouveau utilisateur."""
        users_data = self._load_users()

        # Vérifier si le nom existe déjà
        if any(u["name"] == user_data.name for u in users_data):
            raise ValueError(f"Un utilisateur avec le nom '{user_data.name}' existe déjà")

        # Créer le nouvel utilisateur
        new_user = User(
            id=str(uuid.uuid4()),
            name=user_data.name,
            email=user_data.email,
            role=user_data.role,
            created_at=datetime.now(),
            last_active=datetime.now(),
        )

        # Ajouter à la liste et sauvegarder
        users_data.append(new_user.model_dump(mode="json"))
        self._save_users(users_data)

        return new_user

    def update_user(self, user_id: str, user_update: UserUpdate) -> Optional[User]:
        """Met à jour un utilisateur existant."""
        users_data = self._load_users()

        for i, user_data in enumerate(users_data):
            if user_data["id"] == user_id:
                # Mettre à jour les champs modifiés
                update_data = user_update.model_dump(exclude_unset=True)
                if update_data:
                    user_data.update(update_data)
                    user_data["last_active"] = datetime.now().isoformat()
                    users_data[i] = user_data
                    self._save_users(users_data)

                return User(**user_data)

        return None

    def delete_user(self, user_id: str) -> bool:
        """Supprime un utilisateur."""
        # Ne pas permettre la suppression de l'utilisateur par défaut
        if user_id == "default-user":
            raise ValueError("L'utilisateur par défaut ne peut pas être supprimé")

        users_data = self._load_users()
        original_count = len(users_data)

        users_data = [u for u in users_data if u["id"] != user_id]

        if len(users_data) < original_count:
            self._save_users(users_data)
            return True

        return False

    def update_last_active(self, user_id: str) -> None:
        """Met à jour la dernière activité d'un utilisateur."""
        users_data = self._load_users()

        for user_data in users_data:
            if user_data["id"] == user_id:
                user_data["last_active"] = datetime.now().isoformat()
                self._save_users(users_data)
                break

    def set_default_user(self, user_id: str) -> Optional[User]:
        """Définit un utilisateur comme utilisateur par défaut."""
        users_data = self._load_users()

        # Vérifier que l'utilisateur existe
        target_user = None
        for user_data in users_data:
            if user_data["id"] == user_id:
                target_user = user_data
                break

        if not target_user:
            return None

        # Retirer le statut par défaut de tous les autres utilisateurs
        for user_data in users_data:
            user_data["is_default"] = (user_data["id"] == user_id)

        self._save_users(users_data)
        return User(**target_user)

    def get_default_user(self) -> Optional[User]:
        """Récupère l'utilisateur par défaut."""
        users_data = self._load_users()

        for user_data in users_data:
            if user_data.get("is_default", False):
                return User(**user_data)

        # Fallback sur l'utilisateur "default-user" s'il n'y a pas d'utilisateur marqué par défaut
        for user_data in users_data:
            if user_data["id"] == "default-user":
                return User(**user_data)

        return None


# Instance globale du service
user_service = UserService()


__all__ = ["UserService", "user_service"]