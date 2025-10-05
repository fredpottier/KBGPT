"""
Migrations Neo4j - Gestion Schema

Système simple de migrations pour Neo4j:
- Versioning schéma
- Création constraints
- Création indexes
- Rollback (si possible)
"""

import logging
from typing import List, Dict, Any

from .client import Neo4jCustomClient
from . import schemas

logger = logging.getLogger(__name__)


class MigrationError(Exception):
    """Erreur migration Neo4j"""
    pass


class Neo4jMigrations:
    """
    Gestionnaire migrations Neo4j.

    Usage:
        migrations = Neo4jMigrations(client)
        migrations.apply_all()
    """

    def __init__(self, client: Neo4jCustomClient):
        self.client = client

    def get_current_version(self) -> int:
        """
        Retourne version schéma actuelle.

        Returns:
            Version schéma (0 si pas de version)
        """
        query = """
        MATCH (v:SchemaVersion)
        RETURN v.version as version
        ORDER BY v.version DESC
        LIMIT 1
        """

        try:
            results = self.client.execute_query(query)
            if results:
                return results[0]["version"]
            return 0

        except Exception as e:
            logger.warning(f"No schema version found: {e}")
            return 0

    def set_version(self, version: int) -> None:
        """
        Enregistre version schéma.

        Args:
            version: Numéro version
        """
        query = """
        CREATE (v:SchemaVersion {
          version: $version,
          applied_at: datetime()
        })
        RETURN v
        """

        try:
            self.client.execute_write_query(query, {"version": version})
            logger.info(f"✅ Schema version set to {version}")

        except Exception as e:
            logger.error(f"Failed to set schema version: {e}")
            raise MigrationError(f"Failed to set version: {e}") from e

    def apply_constraints(self) -> None:
        """Applique tous les constraints."""
        logger.info("📝 Applying constraints...")

        for i, constraint_query in enumerate(schemas.CONSTRAINTS, 1):
            try:
                self.client.execute_write_query(constraint_query)
                logger.info(f"  ✅ Constraint {i}/{len(schemas.CONSTRAINTS)} applied")

            except Exception as e:
                # Les constraints peuvent déjà exister (idempotent)
                if "already exists" in str(e).lower() or "equivalent" in str(e).lower():
                    logger.debug(f"  ⚠️ Constraint {i} already exists (OK)")
                else:
                    logger.error(f"  ❌ Failed to apply constraint {i}: {e}")
                    raise MigrationError(f"Constraint {i} failed: {e}") from e

        logger.info(f"✅ All constraints applied ({len(schemas.CONSTRAINTS)} total)")

    def apply_indexes(self) -> None:
        """Applique tous les indexes."""
        logger.info("📝 Applying indexes...")

        for i, index_query in enumerate(schemas.INDEXES, 1):
            try:
                self.client.execute_write_query(index_query)
                logger.info(f"  ✅ Index {i}/{len(schemas.INDEXES)} applied")

            except Exception as e:
                # Les indexes peuvent déjà exister (idempotent)
                if "already exists" in str(e).lower() or "equivalent" in str(e).lower():
                    logger.debug(f"  ⚠️ Index {i} already exists (OK)")
                else:
                    logger.error(f"  ❌ Failed to apply index {i}: {e}")
                    raise MigrationError(f"Index {i} failed: {e}") from e

        logger.info(f"✅ All indexes applied ({len(schemas.INDEXES)} total)")

    def apply_all(self) -> Dict[str, Any]:
        """
        Applique toutes les migrations.

        Returns:
            Dict avec résultats migration
        """
        logger.info("🚀 Starting Neo4j migrations...")

        current_version = self.get_current_version()
        logger.info(f"Current schema version: {current_version}")

        target_version = 1  # Version 1 = Schéma Facts initial

        if current_version >= target_version:
            logger.info(f"Schema already up to date (v{current_version})")
            return {
                "status": "up_to_date",
                "current_version": current_version,
                "target_version": target_version,
            }

        try:
            # Appliquer constraints
            self.apply_constraints()

            # Appliquer indexes
            self.apply_indexes()

            # Mettre à jour version
            self.set_version(target_version)

            logger.info(f"✅ Migrations completed successfully (v{current_version} → v{target_version})")

            return {
                "status": "success",
                "previous_version": current_version,
                "current_version": target_version,
                "constraints_applied": len(schemas.CONSTRAINTS),
                "indexes_applied": len(schemas.INDEXES),
            }

        except Exception as e:
            logger.error(f"❌ Migration failed: {e}")
            return {
                "status": "failed",
                "error": str(e),
                "current_version": current_version,
            }

    def list_constraints(self) -> List[Dict[str, Any]]:
        """
        Liste tous les constraints Neo4j.

        Returns:
            Liste constraints
        """
        query = "SHOW CONSTRAINTS"

        try:
            results = self.client.execute_query(query)
            logger.info(f"Found {len(results)} constraints")
            return results

        except Exception as e:
            logger.error(f"Failed to list constraints: {e}")
            return []

    def list_indexes(self) -> List[Dict[str, Any]]:
        """
        Liste tous les indexes Neo4j.

        Returns:
            Liste indexes
        """
        query = "SHOW INDEXES"

        try:
            results = self.client.execute_query(query)
            logger.info(f"Found {len(results)} indexes")
            return results

        except Exception as e:
            logger.error(f"Failed to list indexes: {e}")
            return []

    def drop_all_constraints(self) -> None:
        """
        ⚠️ DANGER: Supprime tous les constraints.

        À utiliser uniquement pour tests ou rollback.
        """
        logger.warning("⚠️ Dropping all constraints...")

        constraints = self.list_constraints()

        for constraint in constraints:
            constraint_name = constraint.get("name")
            if constraint_name:
                try:
                    query = f"DROP CONSTRAINT {constraint_name} IF EXISTS"
                    self.client.execute_write_query(query)
                    logger.info(f"  ✅ Dropped constraint: {constraint_name}")

                except Exception as e:
                    logger.error(f"  ❌ Failed to drop constraint {constraint_name}: {e}")

        logger.warning("⚠️ All constraints dropped")

    def drop_all_indexes(self) -> None:
        """
        ⚠️ DANGER: Supprime tous les indexes.

        À utiliser uniquement pour tests ou rollback.
        """
        logger.warning("⚠️ Dropping all indexes...")

        indexes = self.list_indexes()

        for index in indexes:
            index_name = index.get("name")
            # Ne pas supprimer indexes système
            if index_name and not index_name.startswith("__"):
                try:
                    query = f"DROP INDEX {index_name} IF EXISTS"
                    self.client.execute_write_query(query)
                    logger.info(f"  ✅ Dropped index: {index_name}")

                except Exception as e:
                    logger.error(f"  ❌ Failed to drop index {index_name}: {e}")

        logger.warning("⚠️ All indexes dropped")


def apply_migrations(client: Neo4jCustomClient) -> Dict[str, Any]:
    """
    Helper function pour appliquer migrations.

    Args:
        client: Neo4jCustomClient

    Returns:
        Dict résultats migration
    """
    migrations = Neo4jMigrations(client)
    return migrations.apply_all()
