# src/knowbase/domain_packs/registry.py
"""
PackRegistry — Découverte et gestion des Domain Packs.

Découverte hybride :
- Packs intégrés (src/knowbase/domain_packs/<name>/ avec manifest.json)
- Packs installés (data/packs/<name>/ via upload .osmpack)

État d'activation stocké dans le champ active_packs (JSON array)
de la table domain_contexts en PostgreSQL.
"""

from __future__ import annotations

import json
import logging
from typing import Dict, List, Optional

from knowbase.domain_packs.base import DomainPack

logger = logging.getLogger(__name__)


class PackRegistry:
    """
    Registre central des Domain Packs.

    Gère la découverte, l'enregistrement et l'activation des packs.
    """

    def __init__(self):
        self._packs: Dict[str, DomainPack] = {}
        self._builtin_names: set = set()

    def register(self, pack: DomainPack, builtin: bool = False) -> None:
        """Enregistre un pack dans le registre."""
        if pack.name in self._packs:
            logger.warning(
                f"[PackRegistry] Pack '{pack.name}' already registered, replacing"
            )
        self._packs[pack.name] = pack
        if builtin:
            self._builtin_names.add(pack.name)
        logger.info(
            f"[PackRegistry] Registered pack '{pack.name}' v{pack.version} "
            f"(priority={pack.priority}, builtin={builtin})"
        )

    def is_builtin(self, pack_name: str) -> bool:
        """Retourne True si le pack est intégré au code source."""
        return pack_name in self._builtin_names

    def get_pack(self, name: str) -> Optional[DomainPack]:
        """Récupère un pack par son nom."""
        return self._packs.get(name)

    def list_packs(self) -> List[DomainPack]:
        """Liste tous les packs enregistrés, triés par priorité décroissante."""
        return sorted(
            self._packs.values(),
            key=lambda p: p.priority,
            reverse=True,
        )

    def get_active_packs(self, tenant_id: str) -> List[DomainPack]:
        """
        Récupère les packs actifs pour un tenant, triés par priorité.

        Lit le champ active_packs depuis PostgreSQL via DomainContextStore.
        """
        active_names = self._get_active_pack_names(tenant_id)
        active = []
        for name in active_names:
            pack = self._packs.get(name)
            if pack:
                active.append(pack)
            else:
                logger.warning(
                    f"[PackRegistry] Active pack '{name}' not found in registry "
                    f"(tenant={tenant_id})"
                )
        return sorted(active, key=lambda p: p.priority, reverse=True)

    def activate(self, pack_name: str, tenant_id: str) -> bool:
        """Active un pack pour un tenant (DB + container Docker)."""
        if pack_name not in self._packs:
            logger.error(f"[PackRegistry] Cannot activate unknown pack '{pack_name}'")
            return False

        # Démarrer le container sidecar
        try:
            from knowbase.domain_packs.pack_manager import get_pack_manager
            manager = get_pack_manager()
            state = manager.get_state(pack_name)

            if state == "not_installed":
                # Tenter l'install du builtin
                manifest = manager.install_builtin(pack_name)
                if not manifest:
                    logger.warning(
                        f"[PackRegistry] Pack '{pack_name}' not installed, "
                        f"activation sans container (mode dégradé)"
                    )

            if state != "active":
                success = manager.activate(pack_name)
                if not success:
                    logger.warning(
                        f"[PackRegistry] Container start failed for '{pack_name}', "
                        f"activation en mode dégradé"
                    )
        except Exception as e:
            logger.warning(f"[PackRegistry] Container management error: {e}")

        # Persister l'activation en DB
        active_names = self._get_active_pack_names(tenant_id)
        if pack_name not in active_names:
            active_names.append(pack_name)
            self._save_active_pack_names(tenant_id, active_names)

        logger.info(f"[PackRegistry] Activated pack '{pack_name}' for {tenant_id}")
        return True

    def deactivate(self, pack_name: str, tenant_id: str) -> bool:
        """Désactive un pack pour un tenant (DB + stop container)."""
        # Arrêter le container sidecar
        try:
            from knowbase.domain_packs.pack_manager import get_pack_manager
            manager = get_pack_manager()
            manager.deactivate(pack_name)
        except Exception as e:
            logger.warning(f"[PackRegistry] Container stop error: {e}")

        # Persister la désactivation en DB
        active_names = self._get_active_pack_names(tenant_id)
        if pack_name in active_names:
            active_names.remove(pack_name)
            self._save_active_pack_names(tenant_id, active_names)

        logger.info(f"[PackRegistry] Deactivated pack '{pack_name}' for {tenant_id}")
        return True

    def is_active(self, pack_name: str, tenant_id: str) -> bool:
        """Vérifie si un pack est actif pour un tenant."""
        return pack_name in self._get_active_pack_names(tenant_id)

    def _get_active_pack_names(self, tenant_id: str) -> List[str]:
        """Lit les noms des packs actifs depuis PostgreSQL."""
        try:
            from knowbase.db.base import SessionLocal
            from knowbase.db.models import DomainContext

            session = SessionLocal()
            try:
                record = session.query(DomainContext).filter(
                    DomainContext.tenant_id == tenant_id
                ).first()
                if record and record.active_packs:
                    return json.loads(record.active_packs)
                return []
            finally:
                session.close()
        except Exception as e:
            logger.error(f"[PackRegistry] Error reading active packs: {e}")
            return []

    def _save_active_pack_names(self, tenant_id: str, names: List[str]) -> None:
        """Sauvegarde les noms des packs actifs dans PostgreSQL."""
        try:
            from knowbase.db.base import SessionLocal
            from knowbase.db.models import DomainContext

            session = SessionLocal()
            try:
                record = session.query(DomainContext).filter(
                    DomainContext.tenant_id == tenant_id
                ).first()
                if record:
                    record.active_packs = json.dumps(names)
                    session.commit()
                else:
                    logger.warning(
                        f"[PackRegistry] No DomainContext for tenant '{tenant_id}', "
                        f"cannot save active packs"
                    )
            except Exception as e:
                session.rollback()
                raise
            finally:
                session.close()
        except Exception as e:
            logger.error(f"[PackRegistry] Error saving active packs: {e}")


# Singleton
_registry_instance: Optional[PackRegistry] = None


def get_pack_registry() -> PackRegistry:
    """Retourne l'instance singleton du registre."""
    global _registry_instance

    if _registry_instance is None:
        _registry_instance = PackRegistry()
        _discover_packs(_registry_instance)

    return _registry_instance


def _discover_packs(registry: PackRegistry) -> None:
    """Découverte automatique des packs (intégrés + installés)."""
    # 1. Packs intégrés (dans le code source)
    try:
        from knowbase.domain_packs.biomedical import BiomedicalPack
        registry.register(BiomedicalPack(), builtin=True)
    except ImportError:
        logger.debug("[PackRegistry] Biomedical pack not available")
    except Exception as e:
        logger.warning(f"[PackRegistry] Error loading biomedical pack: {e}")

    try:
        from knowbase.domain_packs.enterprise_sap import EnterpriseSapPack
        registry.register(EnterpriseSapPack(), builtin=True)
    except ImportError:
        logger.debug("[PackRegistry] Enterprise SAP pack not available")
    except Exception as e:
        logger.warning(f"[PackRegistry] Error loading enterprise_sap pack: {e}")

    # 2. Packs installés via upload (dans data/packs/)
    try:
        from knowbase.domain_packs.pack_manager import get_pack_manager
        manager = get_pack_manager()
        for manifest in manager.list_installed():
            if manifest.name not in registry._packs:
                # Créer un DomainPack dynamique depuis le manifest
                pack = _manifest_to_pack(manifest)
                if pack:
                    registry.register(pack)
    except Exception as e:
        logger.debug(f"[PackRegistry] Error scanning installed packs: {e}")


def _manifest_to_pack(manifest) -> Optional[DomainPack]:
    """Crée un DomainPack dynamique depuis un PackManifest."""
    from knowbase.domain_packs.manifest import PackManifest

    class DynamicPack(DomainPack):
        def __init__(self, m: PackManifest):
            super().__init__()
            self._manifest = m

        @property
        def name(self) -> str:
            return self._manifest.name

        @property
        def display_name(self) -> str:
            return self._manifest.display_name

        @property
        def description(self) -> str:
            return self._manifest.description

        @property
        def version(self) -> str:
            return self._manifest.version

        @property
        def priority(self) -> int:
            return 50

    return DynamicPack(manifest)


__all__ = ["PackRegistry", "get_pack_registry"]
