"""
DomainContextStore - Persistence Neo4j

Stockage et récupération des profils contexte métier par tenant.
"""

from typing import Optional
import logging

from neo4j import GraphDatabase
from knowbase.ontology.domain_context import DomainContextProfile

logger = logging.getLogger(__name__)


class DomainContextStore:
    """
    Stockage et récupération profils contexte métier dans Neo4j.

    Schema Neo4j:
        Node: :DomainContextProfile
        Properties: tenant_id (UNIQUE), domain_summary, industry, ...
        Constraints: tenant_id UNIQUE
        Indexes: industry
    """

    def __init__(self, neo4j_driver: GraphDatabase.driver):
        """
        Initialise store.

        Args:
            neo4j_driver: Neo4j driver instance
        """
        self.driver = neo4j_driver
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """
        Crée constraints et indexes Neo4j si nécessaire.

        Schema:
        - Constraint: tenant_id UNIQUE
        - Index: industry
        """
        with self.driver.session() as session:
            # Constraint UNIQUE sur tenant_id
            try:
                session.run("""
                    CREATE CONSTRAINT domain_context_tenant_unique
                    IF NOT EXISTS
                    FOR (dcp:DomainContextProfile)
                    REQUIRE dcp.tenant_id IS UNIQUE
                """)
                logger.debug(
                    "[DomainContextStore] ✅ Constraint tenant_id UNIQUE created/verified"
                )
            except Exception as e:
                logger.warning(
                    f"[DomainContextStore] Constraint creation skipped: {e}"
                )

            # Index sur industry
            try:
                session.run("""
                    CREATE INDEX domain_context_industry
                    IF NOT EXISTS
                    FOR (dcp:DomainContextProfile)
                    ON (dcp.industry)
                """)
                logger.debug(
                    "[DomainContextStore] ✅ Index industry created/verified"
                )
            except Exception as e:
                logger.warning(
                    f"[DomainContextStore] Index creation skipped: {e}"
                )

    def save_profile(self, profile: DomainContextProfile) -> None:
        """
        Sauvegarde (upsert) profil contexte.

        Créé nouveau profil ou met à jour existant (basé sur tenant_id).

        Args:
            profile: DomainContextProfile à sauvegarder

        Example:
            >>> store = DomainContextStore(driver)
            >>> profile = DomainContextProfile(tenant_id="sap_sales", ...)
            >>> store.save_profile(profile)
        """
        with self.driver.session() as session:
            props = profile.to_neo4j_properties()

            session.run("""
                MERGE (dcp:DomainContextProfile {tenant_id: $tenant_id})
                SET dcp += $props
            """, {
                "tenant_id": profile.tenant_id,
                "props": props
            })

            logger.info(
                f"[DomainContextStore] ✅ Profile saved: tenant='{profile.tenant_id}', "
                f"industry='{profile.industry}', priority='{profile.context_priority}'"
            )

    def get_profile(self, tenant_id: str) -> Optional[DomainContextProfile]:
        """
        Récupère profil contexte pour un tenant.

        Args:
            tenant_id: ID tenant

        Returns:
            DomainContextProfile si trouvé, None sinon

        Example:
            >>> profile = store.get_profile("sap_sales")
            >>> if profile:
            ...     print(profile.common_acronyms)
        """
        with self.driver.session() as session:
            result = session.run("""
                MATCH (dcp:DomainContextProfile {tenant_id: $tenant_id})
                RETURN dcp
            """, {"tenant_id": tenant_id})

            record = result.single()

            if not record:
                logger.debug(
                    f"[DomainContextStore] No profile found for tenant '{tenant_id}'"
                )
                return None

            props = dict(record["dcp"])
            profile = DomainContextProfile.from_neo4j_properties(props)

            logger.debug(
                f"[DomainContextStore] ✅ Profile retrieved: tenant='{tenant_id}', "
                f"industry='{profile.industry}'"
            )

            return profile

    def delete_profile(self, tenant_id: str) -> bool:
        """
        Supprime profil contexte pour un tenant.

        Args:
            tenant_id: ID tenant

        Returns:
            True si profil supprimé, False si non trouvé

        Example:
            >>> deleted = store.delete_profile("sap_sales")
            >>> if deleted:
            ...     print("Profile deleted")
        """
        with self.driver.session() as session:
            result = session.run("""
                MATCH (dcp:DomainContextProfile {tenant_id: $tenant_id})
                DELETE dcp
                RETURN count(dcp) AS deleted_count
            """, {"tenant_id": tenant_id})

            record = result.single()
            deleted_count = record["deleted_count"] if record else 0

            if deleted_count > 0:
                logger.info(
                    f"[DomainContextStore] ✅ Profile deleted: tenant='{tenant_id}'"
                )
                return True
            else:
                logger.debug(
                    f"[DomainContextStore] No profile to delete for tenant '{tenant_id}'"
                )
                return False

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
        with self.driver.session() as session:
            result = session.run("""
                MATCH (dcp:DomainContextProfile)
                RETURN dcp
                ORDER BY dcp.created_at DESC
            """)

            profiles = []
            for record in result:
                props = dict(record["dcp"])
                profile = DomainContextProfile.from_neo4j_properties(props)
                profiles.append(profile)

            logger.debug(
                f"[DomainContextStore] Retrieved {len(profiles)} profiles"
            )

            return profiles


# Instance singleton (usage simple)
_store_instance: Optional[DomainContextStore] = None


def get_domain_context_store(
    neo4j_driver: Optional[GraphDatabase.driver] = None
) -> DomainContextStore:
    """
    Retourne instance singleton du store.

    Args:
        neo4j_driver: Neo4j driver (optionnel si déjà initialisé)

    Returns:
        DomainContextStore instance

    Example:
        >>> store = get_domain_context_store()
        >>> profile = store.get_profile("sap_sales")
    """
    global _store_instance

    if _store_instance is None:
        if neo4j_driver is None:
            # Récupérer driver depuis client Neo4j existant avec config depuis env
            from knowbase.common.clients.neo4j_client import get_neo4j_client
            from knowbase.config.settings import get_settings

            settings = get_settings()
            client = get_neo4j_client(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password,
                database="neo4j"
            )
            neo4j_driver = client.driver

        _store_instance = DomainContextStore(neo4j_driver)

    return _store_instance


__all__ = ["DomainContextStore", "get_domain_context_store"]
