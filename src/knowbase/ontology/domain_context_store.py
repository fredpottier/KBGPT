"""
DomainContextStore - Persistence PostgreSQL

Stockage et récupération des profils contexte métier par tenant.

Migré depuis Neo4j vers PostgreSQL (décembre 2024) pour:
- Survie aux purges du Knowledge Graph Neo4j
- Cohérence avec autres métadonnées (users, sessions, entity_types)
- Backup/restore simplifié via pg_dump
"""

from typing import Optional
import json
import logging

from sqlalchemy.orm import Session as SQLAlchemySession

from knowbase.db.base import SessionLocal
from knowbase.db.models import DomainContext
from knowbase.ontology.domain_context import DomainContextProfile

logger = logging.getLogger(__name__)


class DomainContextStore:
    """
    Stockage et récupération profils contexte métier dans PostgreSQL.

    Schema PostgreSQL:
        Table: domain_contexts
        Columns: id, tenant_id (UNIQUE), domain_summary, industry, ...
        Indexes: tenant_id (unique), industry
    """

    def __init__(self, session_factory=None):
        """
        Initialise store.

        Args:
            session_factory: SQLAlchemy session factory (optionnel, utilise SessionLocal par défaut)
        """
        self.session_factory = session_factory or SessionLocal

    def _get_session(self) -> SQLAlchemySession:
        """Crée une nouvelle session DB."""
        return self.session_factory()

    def save_profile(self, profile: DomainContextProfile) -> None:
        """
        Sauvegarde (upsert) profil contexte.

        Créé nouveau profil ou met à jour existant (basé sur tenant_id).

        Args:
            profile: DomainContextProfile à sauvegarder

        Example:
            >>> store = DomainContextStore()
            >>> profile = DomainContextProfile(tenant_id="default", ...)
            >>> store.save_profile(profile)
        """
        session = self._get_session()
        try:
            # Chercher existant
            existing = session.query(DomainContext).filter(
                DomainContext.tenant_id == profile.tenant_id
            ).first()

            if existing:
                # Update
                existing.domain_summary = profile.domain_summary
                existing.industry = profile.industry
                existing.sub_domains = json.dumps(profile.sub_domains)
                existing.target_users = json.dumps(profile.target_users)
                existing.document_types = json.dumps(profile.document_types)
                existing.common_acronyms = json.dumps(profile.common_acronyms)
                existing.key_concepts = json.dumps(profile.key_concepts)
                existing.context_priority = profile.context_priority
                existing.llm_injection_prompt = profile.llm_injection_prompt
                existing.versioning_hints = profile.versioning_hints
                existing.identification_semantics = profile.identification_semantics
                existing.axis_reclassification_rules = profile.axis_reclassification_rules
                # updated_at is auto-updated by SQLAlchemy
            else:
                # Insert
                new_context = DomainContext(
                    tenant_id=profile.tenant_id,
                    domain_summary=profile.domain_summary,
                    industry=profile.industry,
                    sub_domains=json.dumps(profile.sub_domains),
                    target_users=json.dumps(profile.target_users),
                    document_types=json.dumps(profile.document_types),
                    common_acronyms=json.dumps(profile.common_acronyms),
                    key_concepts=json.dumps(profile.key_concepts),
                    context_priority=profile.context_priority,
                    llm_injection_prompt=profile.llm_injection_prompt,
                    versioning_hints=profile.versioning_hints,
                    identification_semantics=profile.identification_semantics,
                    axis_reclassification_rules=profile.axis_reclassification_rules,
                )
                session.add(new_context)

            session.commit()

            logger.info(
                f"[DomainContextStore] ✅ Profile saved (PostgreSQL): tenant='{profile.tenant_id}', "
                f"industry='{profile.industry}', priority='{profile.context_priority}'"
            )
        except Exception as e:
            session.rollback()
            logger.error(f"[DomainContextStore] ❌ Error saving profile: {e}")
            raise
        finally:
            session.close()

    def get_profile(self, tenant_id: str) -> Optional[DomainContextProfile]:
        """
        Récupère profil contexte pour un tenant.

        Args:
            tenant_id: ID tenant

        Returns:
            DomainContextProfile si trouvé, None sinon

        Example:
            >>> profile = store.get_profile("default")
            >>> if profile:
            ...     print(profile.common_acronyms)
        """
        session = self._get_session()
        try:
            record = session.query(DomainContext).filter(
                DomainContext.tenant_id == tenant_id
            ).first()

            if not record:
                logger.debug(
                    f"[DomainContextStore] No profile found for tenant '{tenant_id}'"
                )
                return None

            # Convertir en DomainContextProfile
            profile = DomainContextProfile(
                tenant_id=record.tenant_id,
                domain_summary=record.domain_summary,
                industry=record.industry,
                sub_domains=json.loads(record.sub_domains or "[]"),
                target_users=json.loads(record.target_users or "[]"),
                document_types=json.loads(record.document_types or "[]"),
                common_acronyms=json.loads(record.common_acronyms or "{}"),
                key_concepts=json.loads(record.key_concepts or "[]"),
                context_priority=record.context_priority or "medium",
                llm_injection_prompt=record.llm_injection_prompt,
                versioning_hints=getattr(record, 'versioning_hints', '') or "",
                identification_semantics=getattr(record, 'identification_semantics', '') or "",
                axis_reclassification_rules=getattr(record, 'axis_reclassification_rules', '') or "",
                created_at=record.created_at,
                updated_at=record.updated_at,
            )

            logger.debug(
                f"[DomainContextStore] ✅ Profile retrieved (PostgreSQL): tenant='{tenant_id}', "
                f"industry='{profile.industry}'"
            )

            return profile
        finally:
            session.close()

    def delete_profile(self, tenant_id: str) -> bool:
        """
        Supprime profil contexte pour un tenant.

        Args:
            tenant_id: ID tenant

        Returns:
            True si profil supprimé, False si non trouvé

        Example:
            >>> deleted = store.delete_profile("default")
            >>> if deleted:
            ...     print("Profile deleted")
        """
        session = self._get_session()
        try:
            result = session.query(DomainContext).filter(
                DomainContext.tenant_id == tenant_id
            ).delete()

            session.commit()

            if result > 0:
                logger.info(
                    f"[DomainContextStore] ✅ Profile deleted (PostgreSQL): tenant='{tenant_id}'"
                )
                return True
            else:
                logger.debug(
                    f"[DomainContextStore] No profile to delete for tenant '{tenant_id}'"
                )
                return False
        except Exception as e:
            session.rollback()
            logger.error(f"[DomainContextStore] ❌ Error deleting profile: {e}")
            raise
        finally:
            session.close()

    def list_all_profiles(self) -> list[DomainContextProfile]:
        """
        Liste tous les profils contexte.

        Returns:
            Liste de tous les DomainContextProfile

        Example:
            >>> profiles = store.list_all_profiles()
            >>> for p in profiles:
            ...     print(f"{p.tenant_id}: {p.industry}")
        """
        session = self._get_session()
        try:
            records = session.query(DomainContext).order_by(
                DomainContext.created_at.desc()
            ).all()

            profiles = []
            for record in records:
                profile = DomainContextProfile(
                    tenant_id=record.tenant_id,
                    domain_summary=record.domain_summary,
                    industry=record.industry,
                    sub_domains=json.loads(record.sub_domains or "[]"),
                    target_users=json.loads(record.target_users or "[]"),
                    document_types=json.loads(record.document_types or "[]"),
                    common_acronyms=json.loads(record.common_acronyms or "{}"),
                    key_concepts=json.loads(record.key_concepts or "[]"),
                    context_priority=record.context_priority or "medium",
                    llm_injection_prompt=record.llm_injection_prompt,
                    versioning_hints=getattr(record, 'versioning_hints', '') or "",
                    identification_semantics=getattr(record, 'identification_semantics', '') or "",
                    axis_reclassification_rules=getattr(record, 'axis_reclassification_rules', '') or "",
                    created_at=record.created_at,
                    updated_at=record.updated_at,
                )
                profiles.append(profile)

            logger.debug(
                f"[DomainContextStore] Retrieved {len(profiles)} profiles (PostgreSQL)"
            )

            return profiles
        finally:
            session.close()


# Instance singleton (usage simple)
_store_instance: Optional[DomainContextStore] = None


def get_domain_context_store() -> DomainContextStore:
    """
    Retourne instance singleton du store.

    Returns:
        DomainContextStore instance

    Example:
        >>> store = get_domain_context_store()
        >>> profile = store.get_profile("default")
    """
    global _store_instance

    if _store_instance is None:
        _store_instance = DomainContextStore()
        logger.info("[DomainContextStore] ✅ Initialized with PostgreSQL backend")

    return _store_instance


__all__ = ["DomainContextStore", "get_domain_context_store"]
