"""
Service EntityTypeRegistry - Gestion types d'entités découverts dynamiquement.

Phase 2 - Entity Types Management
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from knowbase.db.models import EntityTypeRegistry
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "entity_type_registry_service.log")


class EntityTypeRegistryService:
    """Service gestion registry types d'entités."""

    def __init__(self, db: Session):
        """
        Initialise le service.

        Args:
            db: Session SQLAlchemy
        """
        self.db = db

    def get_or_create_type(
        self,
        type_name: str,
        tenant_id: str = "default",
        discovered_by: str = "llm"
    ) -> EntityTypeRegistry:
        """
        Récupère un type existant ou le crée s'il n'existe pas.

        Si le type existe déjà, le retourne tel quel.
        Si nouveau, le crée avec status=pending (sauf si discovered_by=system → approved).

        Args:
            type_name: Nom type (UPPERCASE, ex: INFRASTRUCTURE)
            tenant_id: Tenant ID
            discovered_by: Source découverte (llm | admin | system)

        Returns:
            EntityTypeRegistry instance
        """
        # Normaliser type_name
        type_name = type_name.strip().upper()

        # Chercher type existant
        existing_type = self.db.query(EntityTypeRegistry).filter(
            EntityTypeRegistry.type_name == type_name,
            EntityTypeRegistry.tenant_id == tenant_id
        ).first()

        if existing_type:
            logger.debug(
                f"✅ Type existant trouvé: {type_name} (status={existing_type.status})"
            )
            return existing_type

        # Créer nouveau type
        # Types système (bootstrap) sont auto-approuvés
        initial_status = "approved" if discovered_by == "system" else "pending"

        new_type = EntityTypeRegistry(
            type_name=type_name,
            status=initial_status,
            first_seen=datetime.now(timezone.utc),
            discovered_by=discovered_by,
            tenant_id=tenant_id,
            entity_count=0,
            pending_entity_count=0
        )

        self.db.add(new_type)
        self.db.commit()
        self.db.refresh(new_type)

        logger.info(
            f"📝 Nouveau type créé: {type_name} (status={initial_status}, "
            f"discovered_by={discovered_by})"
        )

        return new_type

    def update_entity_counts(
        self,
        type_name: str,
        tenant_id: str,
        total_count: int,
        pending_count: int
    ) -> Optional[EntityTypeRegistry]:
        """
        Met à jour les compteurs d'entités pour un type.

        Args:
            type_name: Nom type
            tenant_id: Tenant ID
            total_count: Nombre total entités
            pending_count: Nombre entités pending

        Returns:
            EntityTypeRegistry mis à jour ou None si type non trouvé
        """
        entity_type = self.db.query(EntityTypeRegistry).filter(
            EntityTypeRegistry.type_name == type_name,
            EntityTypeRegistry.tenant_id == tenant_id
        ).first()

        if not entity_type:
            logger.warning(f"⚠️ Type {type_name} non trouvé pour update counts")
            return None

        entity_type.entity_count = total_count
        entity_type.pending_entity_count = pending_count
        entity_type.updated_at = datetime.now(timezone.utc)

        self.db.commit()
        self.db.refresh(entity_type)

        logger.debug(
            f"📊 Counts mis à jour: {type_name} → total={total_count}, "
            f"pending={pending_count}"
        )

        return entity_type

    def list_types(
        self,
        tenant_id: str = "default",
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[EntityTypeRegistry]:
        """
        Liste tous les types avec filtres optionnels.

        Args:
            tenant_id: Tenant ID
            status: Filtrer par status (pending | approved | rejected)
            limit: Limite résultats
            offset: Offset pagination

        Returns:
            Liste EntityTypeRegistry
        """
        query = self.db.query(EntityTypeRegistry).filter(
            EntityTypeRegistry.tenant_id == tenant_id
        )

        if status:
            query = query.filter(EntityTypeRegistry.status == status)

        query = query.order_by(EntityTypeRegistry.entity_count.desc())
        query = query.limit(limit).offset(offset)

        types = query.all()

        logger.debug(
            f"📋 Listés {len(types)} types (status={status or 'all'}, "
            f"tenant={tenant_id})"
        )

        return types

    def count_types(
        self,
        tenant_id: str = "default",
        status: Optional[str] = None
    ) -> int:
        """
        Compte les types avec filtres optionnels.

        Args:
            tenant_id: Tenant ID
            status: Filtrer par status

        Returns:
            Nombre types
        """
        query = self.db.query(func.count(EntityTypeRegistry.id)).filter(
            EntityTypeRegistry.tenant_id == tenant_id
        )

        if status:
            query = query.filter(EntityTypeRegistry.status == status)

        count = query.scalar()
        return count or 0

    def get_type_by_name(
        self,
        type_name: str,
        tenant_id: str = "default"
    ) -> Optional[EntityTypeRegistry]:
        """
        Récupère un type par son nom.

        Args:
            type_name: Nom type
            tenant_id: Tenant ID

        Returns:
            EntityTypeRegistry ou None si non trouvé
        """
        type_name = type_name.strip().upper()

        entity_type = self.db.query(EntityTypeRegistry).filter(
            EntityTypeRegistry.type_name == type_name,
            EntityTypeRegistry.tenant_id == tenant_id
        ).first()

        return entity_type

    def approve_type(
        self,
        type_name: str,
        admin_email: str,
        tenant_id: str = "default"
    ) -> Optional[EntityTypeRegistry]:
        """
        Approuve un type pending.

        Args:
            type_name: Nom type
            admin_email: Email admin
            tenant_id: Tenant ID

        Returns:
            EntityTypeRegistry approuvé ou None si non trouvé
        """
        entity_type = self.get_type_by_name(type_name, tenant_id)

        if not entity_type:
            logger.warning(f"⚠️ Type {type_name} non trouvé pour approbation")
            return None

        entity_type.approve(admin_email)
        self.db.commit()
        self.db.refresh(entity_type)

        logger.info(
            f"✅ Type approuvé: {type_name} par {admin_email}"
        )

        return entity_type

    def reject_type(
        self,
        type_name: str,
        admin_email: str,
        reason: Optional[str] = None,
        tenant_id: str = "default"
    ) -> Optional[EntityTypeRegistry]:
        """
        Rejette un type.

        Args:
            type_name: Nom type
            admin_email: Email admin
            reason: Raison rejet (optionnel)
            tenant_id: Tenant ID

        Returns:
            EntityTypeRegistry rejeté ou None si non trouvé
        """
        entity_type = self.get_type_by_name(type_name, tenant_id)

        if not entity_type:
            logger.warning(f"⚠️ Type {type_name} non trouvé pour rejet")
            return None

        entity_type.reject(admin_email, reason)
        self.db.commit()
        self.db.refresh(entity_type)

        logger.info(
            f"❌ Type rejeté: {type_name} par {admin_email} (raison: {reason or 'non spécifiée'})"
        )

        return entity_type

    def delete_type(
        self,
        type_name: str,
        tenant_id: str = "default"
    ) -> bool:
        """
        Supprime un type du registry.

        ⚠️ ATTENTION : Ne supprime PAS les entités Neo4j associées.
        Utiliser cascade_delete_type pour suppression complète.

        Args:
            type_name: Nom type
            tenant_id: Tenant ID

        Returns:
            True si supprimé, False sinon
        """
        entity_type = self.get_type_by_name(type_name, tenant_id)

        if not entity_type:
            logger.warning(f"⚠️ Type {type_name} non trouvé pour suppression")
            return False

        self.db.delete(entity_type)
        self.db.commit()

        logger.info(f"🗑️ Type supprimé du registry: {type_name}")

        return True


__all__ = ["EntityTypeRegistryService"]
