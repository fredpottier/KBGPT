"""
Service de gestion des tenants multi-tenant
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

from ..schemas.tenant import (
    Tenant,
    TenantCreate,
    TenantUpdate,
    TenantStats,
    TenantStatus,
    UserTenantMembership,
    TenantHierarchy,
    TenantPermission,
    GraphitiTenantInfo
)
from ..schemas.user import User


class TenantService:
    """
    Service de gestion des tenants avec persistance locale
    """

    def __init__(self, data_dir: Path):
        """
        Initialise le service de tenants

        Args:
            data_dir: Répertoire de données pour la persistance
        """
        self.data_dir = data_dir
        self.tenants_file = data_dir / "tenants.json"
        self.memberships_file = data_dir / "tenant_memberships.json"

        # Assurer que les fichiers existent
        self._ensure_data_files()

        # Cache en mémoire
        self._tenants: Dict[str, Tenant] = {}
        self._memberships: Dict[str, List[UserTenantMembership]] = {}
        self._load_data()

    def _ensure_data_files(self) -> None:
        """Assure que les fichiers de données existent"""
        self.data_dir.mkdir(exist_ok=True)

        if not self.tenants_file.exists():
            self.tenants_file.write_text("[]", encoding="utf-8")

        if not self.memberships_file.exists():
            self.memberships_file.write_text("[]", encoding="utf-8")

    def _load_data(self) -> None:
        """Charge les données depuis les fichiers"""
        try:
            # Charger les tenants
            with open(self.tenants_file, 'r', encoding='utf-8') as f:
                tenants_data = json.load(f)

            self._tenants = {}
            for tenant_dict in tenants_data:
                tenant = Tenant(**tenant_dict)
                self._tenants[tenant.id] = tenant

            # Charger les adhésions
            with open(self.memberships_file, 'r', encoding='utf-8') as f:
                memberships_data = json.load(f)

            self._memberships = {}
            for membership_dict in memberships_data:
                membership = UserTenantMembership(**membership_dict)
                user_id = membership.user_id

                if user_id not in self._memberships:
                    self._memberships[user_id] = []

                self._memberships[user_id].append(membership)

        except Exception as e:
            print(f"Erreur chargement données tenants: {e}")
            self._tenants = {}
            self._memberships = {}

    def _save_data(self) -> None:
        """Sauvegarde les données dans les fichiers"""
        try:
            # Sauvegarder les tenants
            tenants_data = []
            for tenant in self._tenants.values():
                tenant_dict = tenant.model_dump()
                # Convertir les dates en chaînes
                if isinstance(tenant_dict.get('created_at'), datetime):
                    tenant_dict['created_at'] = tenant_dict['created_at'].isoformat()
                if isinstance(tenant_dict.get('updated_at'), datetime):
                    tenant_dict['updated_at'] = tenant_dict['updated_at'].isoformat()
                if tenant_dict.get('stats', {}).get('last_activity'):
                    if isinstance(tenant_dict['stats']['last_activity'], datetime):
                        tenant_dict['stats']['last_activity'] = tenant_dict['stats']['last_activity'].isoformat()

                tenants_data.append(tenant_dict)

            with open(self.tenants_file, 'w', encoding='utf-8') as f:
                json.dump(tenants_data, f, indent=2, ensure_ascii=False)

            # Sauvegarder les adhésions
            memberships_data = []
            for user_memberships in self._memberships.values():
                for membership in user_memberships:
                    membership_dict = membership.model_dump()
                    if isinstance(membership_dict.get('joined_at'), datetime):
                        membership_dict['joined_at'] = membership_dict['joined_at'].isoformat()
                    memberships_data.append(membership_dict)

            with open(self.memberships_file, 'w', encoding='utf-8') as f:
                json.dump(memberships_data, f, indent=2, ensure_ascii=False)

        except Exception as e:
            print(f"Erreur sauvegarde données tenants: {e}")

    def create_tenant(self, tenant_data: TenantCreate, created_by: str) -> Tenant:
        """
        Crée un nouveau tenant

        Args:
            tenant_data: Données du tenant à créer
            created_by: ID de l'utilisateur créateur

        Returns:
            Tenant créé
        """
        tenant_id = str(uuid.uuid4())
        now = datetime.now()

        # Créer le tenant avec stats vides
        tenant = Tenant(
            id=tenant_id,
            name=tenant_data.name,
            display_name=tenant_data.display_name or tenant_data.name,
            description=tenant_data.description,
            tenant_type=tenant_data.tenant_type,
            parent_tenant_id=tenant_data.parent_tenant_id,
            graphiti_settings=tenant_data.graphiti_settings,
            metadata=tenant_data.metadata,
            status=TenantStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            stats=TenantStats()
        )

        # Stocker
        self._tenants[tenant_id] = tenant
        self._save_data()

        return tenant

    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        """Récupère un tenant par son ID"""
        return self._tenants.get(tenant_id)

    def get_tenant_by_name(self, name: str) -> Optional[Tenant]:
        """Récupère un tenant par son nom"""
        for tenant in self._tenants.values():
            if tenant.name == name:
                return tenant
        return None

    def list_tenants(self,
                     page: int = 1,
                     page_size: int = 20,
                     status_filter: Optional[TenantStatus] = None,
                     parent_id_filter: Optional[str] = None) -> List[Tenant]:
        """
        Liste les tenants avec pagination et filtres

        Args:
            page: Numéro de page
            page_size: Taille de page
            status_filter: Filtre par statut
            parent_id_filter: Filtre par tenant parent

        Returns:
            Liste des tenants
        """
        tenants = list(self._tenants.values())

        # Appliquer filtres
        if status_filter:
            tenants = [t for t in tenants if t.status == status_filter]

        if parent_id_filter:
            tenants = [t for t in tenants if t.parent_tenant_id == parent_id_filter]

        # Trier par date de création
        tenants.sort(key=lambda t: t.created_at, reverse=True)

        # Pagination
        start = (page - 1) * page_size
        end = start + page_size
        return tenants[start:end]

    def update_tenant(self, tenant_id: str, updates: TenantUpdate) -> Optional[Tenant]:
        """
        Met à jour un tenant

        Args:
            tenant_id: ID du tenant
            updates: Données à mettre à jour

        Returns:
            Tenant mis à jour ou None si inexistant
        """
        if tenant_id not in self._tenants:
            return None

        tenant = self._tenants[tenant_id]

        # Appliquer les mises à jour
        update_data = updates.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            if hasattr(tenant, field):
                setattr(tenant, field, value)

        tenant.updated_at = datetime.now()

        # Sauvegarder
        self._save_data()

        return tenant

    def delete_tenant(self, tenant_id: str) -> bool:
        """
        Supprime un tenant (marque comme archivé)

        Args:
            tenant_id: ID du tenant à supprimer

        Returns:
            True si supprimé avec succès
        """
        if tenant_id not in self._tenants:
            return False

        # Marquer comme archivé au lieu de supprimer
        self._tenants[tenant_id].status = TenantStatus.ARCHIVED
        self._tenants[tenant_id].updated_at = datetime.now()

        self._save_data()
        return True

    def add_user_to_tenant(self,
                          user_id: str,
                          tenant_id: str,
                          role: str = "member",
                          permissions: Optional[List[str]] = None,
                          is_default: bool = False) -> UserTenantMembership:
        """
        Ajoute un utilisateur à un tenant

        Args:
            user_id: ID de l'utilisateur
            tenant_id: ID du tenant
            role: Rôle de l'utilisateur
            permissions: Permissions spécifiques
            is_default: Tenant par défaut pour cet utilisateur

        Returns:
            Adhésion créée
        """
        if user_id not in self._memberships:
            self._memberships[user_id] = []

        # Vérifier si déjà membre
        for membership in self._memberships[user_id]:
            if membership.tenant_id == tenant_id:
                return membership

        # Créer nouvelle adhésion
        membership = UserTenantMembership(
            user_id=user_id,
            tenant_id=tenant_id,
            role=role,
            permissions=permissions or [],
            joined_at=datetime.now(),
            is_default=is_default
        )

        self._memberships[user_id].append(membership)
        self._save_data()

        return membership

    def get_user_tenants(self, user_id: str) -> List[UserTenantMembership]:
        """Récupère tous les tenants d'un utilisateur"""
        return self._memberships.get(user_id, [])

    def get_tenant_users(self, tenant_id: str) -> List[UserTenantMembership]:
        """Récupère tous les utilisateurs d'un tenant"""
        users = []
        for user_memberships in self._memberships.values():
            for membership in user_memberships:
                if membership.tenant_id == tenant_id:
                    users.append(membership)
        return users

    def user_has_permission(self, user_id: str, tenant_id: str, permission: TenantPermission) -> bool:
        """
        Vérifie si un utilisateur a une permission dans un tenant

        Args:
            user_id: ID de l'utilisateur
            tenant_id: ID du tenant
            permission: Permission à vérifier

        Returns:
            True si l'utilisateur a la permission
        """
        user_memberships = self._memberships.get(user_id, [])

        for membership in user_memberships:
            if membership.tenant_id == tenant_id:
                # Admin a toutes les permissions
                if membership.role == "admin" or TenantPermission.ADMIN.value in membership.permissions:
                    return True

                # Vérifier permission spécifique
                if permission.value in membership.permissions:
                    return True

        return False

    def get_tenant_hierarchy(self, tenant_id: str) -> Optional[TenantHierarchy]:
        """
        Récupère la hiérarchie d'un tenant avec ses enfants

        Args:
            tenant_id: ID du tenant racine

        Returns:
            Hiérarchie du tenant
        """
        tenant = self.get_tenant(tenant_id)
        if not tenant:
            return None

        def build_hierarchy(current_tenant: Tenant, path: List[str], depth: int) -> TenantHierarchy:
            # Trouver les enfants
            children = []
            for child_tenant in self._tenants.values():
                if child_tenant.parent_tenant_id == current_tenant.id:
                    child_hierarchy = build_hierarchy(
                        child_tenant,
                        path + [current_tenant.id],
                        depth + 1
                    )
                    children.append(child_hierarchy)

            return TenantHierarchy(
                tenant=current_tenant,
                children=children,
                path=path,
                depth=depth
            )

        return build_hierarchy(tenant, [], 0)

    def update_tenant_stats(self, tenant_id: str, **stats) -> bool:
        """
        Met à jour les statistiques d'un tenant

        Args:
            tenant_id: ID du tenant
            **stats: Statistiques à mettre à jour

        Returns:
            True si mis à jour avec succès
        """
        if tenant_id not in self._tenants:
            return False

        tenant = self._tenants[tenant_id]

        # Mettre à jour les stats
        for key, value in stats.items():
            if hasattr(tenant.stats, key):
                setattr(tenant.stats, key, value)

        tenant.stats.last_activity = datetime.now()
        tenant.updated_at = datetime.now()

        self._save_data()
        return True

    def get_default_tenant_for_user(self, user_id: str) -> Optional[str]:
        """
        Récupère le tenant par défaut d'un utilisateur

        Args:
            user_id: ID de l'utilisateur

        Returns:
            ID du tenant par défaut ou None
        """
        user_memberships = self._memberships.get(user_id, [])

        for membership in user_memberships:
            if membership.is_default:
                return membership.tenant_id

        # Si pas de défaut explicite, retourner le premier
        if user_memberships:
            return user_memberships[0].tenant_id

        return None


# Instance globale du service
_tenant_service: Optional[TenantService] = None


def get_tenant_service(data_dir: Optional[Path] = None) -> TenantService:
    """Factory pour obtenir le service de tenants"""
    global _tenant_service

    if _tenant_service is None:
        if data_dir is None:
            data_dir = Path("/data/tenants")  # Répertoire par défaut

        _tenant_service = TenantService(data_dir)

    return _tenant_service