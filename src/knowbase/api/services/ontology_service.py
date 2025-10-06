"""
Service pour gestion catalogues d'ontologies.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import yaml
import re
from collections import defaultdict

from knowbase.api.schemas.ontology import (
    EntityCatalogEntry,
    EntityCatalogCreate,
    EntityCatalogUpdate,
    EntityCatalogResponse,
    CatalogStatistics,
    UncatalogedEntity,
    UncatalogedEntityApprove,
    CatalogBulkImportResult,
)
from knowbase.common.entity_types import EntityType
from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "ontology_service.log")


class OntologyService:
    """Service CRUD pour catalogues d'ontologies."""

    # Map legacy: anciens noms de fichiers → nouveau format
    LEGACY_FILENAME_MAP = {
        "TECHNOLOGY": "technologies.yaml",
        "SOLUTION": "solutions.yaml",
        "COMPONENT": "components.yaml",
        "ORGANIZATION": "organizations.yaml",
        "PERSON": "persons.yaml",
        "CONCEPT": "concepts.yaml",
    }

    # Map legacy: anciennes clés racines YAML → nouveau format
    LEGACY_ROOT_KEY_MAP = {
        "TECHNOLOGY": "TECHNOLOGIES",
        "SOLUTION": "SOLUTIONS",
        "COMPONENT": "COMPONENTS",
        "ORGANIZATION": "ORGANIZATIONS",
        "PERSON": "PERSONS",
        "CONCEPT": "CONCEPTS",
    }

    def __init__(self):
        self.ontology_dir = Path(settings.config_dir) / "ontologies"
        self.ontology_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"📂 OntologyService init - ontology_dir: {self.ontology_dir}")

    def _get_catalog_path(self, entity_type: EntityType) -> Path:
        """
        Retourne chemin fichier catalogue pour un type.
        Supporte les anciens noms legacy et le nouveau format {type}_list.yaml
        """
        # Nouveau format: technology_list.yaml, solution_list.yaml, etc.
        new_format_path = self.ontology_dir / f"{entity_type.value.lower()}_list.yaml"

        # Si le nouveau format existe, l'utiliser
        if new_format_path.exists():
            return new_format_path

        # Sinon, chercher le legacy filename
        legacy_filename = self.LEGACY_FILENAME_MAP.get(entity_type.value)
        if legacy_filename:
            legacy_path = self.ontology_dir / legacy_filename
            if legacy_path.exists():
                logger.warning(
                    f"⚠️  Using legacy filename {legacy_filename}. "
                    f"Consider migrating to {entity_type.value.lower()}_list.yaml"
                )
                return legacy_path

        # Par défaut, retourner le nouveau format (même s'il n'existe pas encore)
        return new_format_path

    def _load_catalog(self, entity_type: EntityType) -> Dict:
        """Charge catalogue YAML pour un type."""
        catalog_path = self._get_catalog_path(entity_type)

        logger.info(f"🔍 Loading catalog: {catalog_path} (exists={catalog_path.exists()})")

        if not catalog_path.exists():
            logger.warning(f"Catalogue inexistant: {catalog_path}")
            return {}

        with open(catalog_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        # Nouveau format: clé racine = type en majuscules (ex: TECHNOLOGY)
        # Legacy format: clé racine = pluriel en majuscules (ex: TECHNOLOGIES)
        root_key = entity_type.value

        if root_key not in data:
            # Essayer d'abord avec le mapping legacy connu
            legacy_root_key = self.LEGACY_ROOT_KEY_MAP.get(entity_type.value)
            if legacy_root_key and legacy_root_key in data:
                root_key = legacy_root_key
                logger.info(f"⚠️  Using legacy root key {legacy_root_key}. Consider migrating to {entity_type.value}")
            else:
                # Sinon essayer le simple pluriel +S
                simple_plural = f"{entity_type.value}S"
                if simple_plural in data:
                    root_key = simple_plural
                    logger.info(f"⚠️  Using legacy root key {simple_plural}. Consider migrating to {entity_type.value}")

        catalog_data = data.get(root_key, {})
        logger.info(f"✅ Loaded {len(catalog_data)} entities from {entity_type.value} (root_key={root_key})")
        return catalog_data

    def _save_catalog(self, entity_type: EntityType, catalog: Dict) -> None:
        """Sauvegarde catalogue YAML (nouveau format uniquement)."""
        catalog_path = self._get_catalog_path(entity_type)

        # Toujours sauvegarder avec le nouveau format: clé = type singulier
        root_key = entity_type.value
        data = {root_key: catalog}

        with open(catalog_path, "w", encoding="utf-8") as f:
            yaml.dump(
                data,
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False
            )

        logger.info(f"✅ Catalogue sauvegardé: {catalog_path}")

    # === CRUD Entités ===

    def list_entities(
        self,
        entity_type: EntityType,
        category: Optional[str] = None,
        vendor: Optional[str] = None
    ) -> List[EntityCatalogResponse]:
        """Liste toutes les entités d'un catalogue."""
        catalog = self._load_catalog(entity_type)

        entities = []
        for entity_id, entity_data in catalog.items():
            # Filtres optionnels
            if category and entity_data.get("category") != category:
                continue
            if vendor and entity_data.get("vendor") != vendor:
                continue

            entities.append(
                EntityCatalogResponse(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    canonical_name=entity_data["canonical_name"],
                    aliases=entity_data.get("aliases", []),
                    category=entity_data.get("category"),
                    vendor=entity_data.get("vendor"),
                    usage_count=0  # TODO: calculer depuis Neo4j
                )
            )

        return entities

    def get_entity(
        self,
        entity_type: EntityType,
        entity_id: str
    ) -> Optional[EntityCatalogResponse]:
        """Récupère une entité catalogue."""
        catalog = self._load_catalog(entity_type)

        entity_data = catalog.get(entity_id)
        if not entity_data:
            return None

        return EntityCatalogResponse(
            entity_type=entity_type,
            entity_id=entity_id,
            canonical_name=entity_data["canonical_name"],
            aliases=entity_data.get("aliases", []),
            category=entity_data.get("category"),
            vendor=entity_data.get("vendor"),
            usage_count=0  # TODO: calculer depuis Neo4j
        )

    def create_entity(
        self,
        entity_data: EntityCatalogCreate
    ) -> EntityCatalogResponse:
        """Crée une nouvelle entité catalogue."""
        catalog = self._load_catalog(entity_data.entity_type)

        # Vérifier si entity_id existe déjà
        if entity_data.entity_id in catalog:
            raise ValueError(
                f"Entity ID '{entity_data.entity_id}' existe déjà dans "
                f"catalogue {entity_data.entity_type.value}"
            )

        # Créer entrée
        catalog[entity_data.entity_id] = {
            "canonical_name": entity_data.canonical_name,
            "aliases": entity_data.aliases,
        }

        if entity_data.category:
            catalog[entity_data.entity_id]["category"] = entity_data.category

        if entity_data.vendor:
            catalog[entity_data.entity_id]["vendor"] = entity_data.vendor

        # Sauvegarder
        self._save_catalog(entity_data.entity_type, catalog)

        logger.info(
            f"✅ Entité créée: {entity_data.entity_id} "
            f"(type={entity_data.entity_type.value})"
        )

        return EntityCatalogResponse(
            entity_type=entity_data.entity_type,
            entity_id=entity_data.entity_id,
            canonical_name=entity_data.canonical_name,
            aliases=entity_data.aliases,
            category=entity_data.category,
            vendor=entity_data.vendor,
            usage_count=0
        )

    def update_entity(
        self,
        entity_type: EntityType,
        entity_id: str,
        update_data: EntityCatalogUpdate
    ) -> EntityCatalogResponse:
        """Met à jour une entité catalogue."""
        catalog = self._load_catalog(entity_type)

        if entity_id not in catalog:
            raise ValueError(
                f"Entity ID '{entity_id}' introuvable dans "
                f"catalogue {entity_type.value}"
            )

        # Appliquer modifications
        entity = catalog[entity_id]

        if update_data.canonical_name is not None:
            entity["canonical_name"] = update_data.canonical_name

        if update_data.aliases is not None:
            entity["aliases"] = update_data.aliases

        if update_data.category is not None:
            entity["category"] = update_data.category

        if update_data.vendor is not None:
            entity["vendor"] = update_data.vendor

        # Sauvegarder
        self._save_catalog(entity_type, catalog)

        logger.info(f"✅ Entité mise à jour: {entity_id} (type={entity_type.value})")

        return EntityCatalogResponse(
            entity_type=entity_type,
            entity_id=entity_id,
            canonical_name=entity["canonical_name"],
            aliases=entity.get("aliases", []),
            category=entity.get("category"),
            vendor=entity.get("vendor"),
            usage_count=0
        )

    def delete_entity(
        self,
        entity_type: EntityType,
        entity_id: str
    ) -> None:
        """Supprime une entité catalogue."""
        catalog = self._load_catalog(entity_type)

        if entity_id not in catalog:
            raise ValueError(
                f"Entity ID '{entity_id}' introuvable dans "
                f"catalogue {entity_type.value}"
            )

        del catalog[entity_id]

        # Sauvegarder
        self._save_catalog(entity_type, catalog)

        logger.info(f"✅ Entité supprimée: {entity_id} (type={entity_type.value})")

    # === Statistiques ===

    def get_statistics(
        self,
        entity_type: EntityType
    ) -> CatalogStatistics:
        """Retourne statistiques catalogue."""
        catalog = self._load_catalog(entity_type)

        total_entities = len(catalog)
        total_aliases = sum(
            len(entity.get("aliases", []))
            for entity in catalog.values()
        )

        # Répartition par catégorie
        categories = defaultdict(int)
        for entity in catalog.values():
            category = entity.get("category", "Uncategorized")
            categories[category] += 1

        # Répartition par vendor
        vendors = defaultdict(int)
        for entity in catalog.values():
            vendor = entity.get("vendor", "Unknown")
            if vendor:
                vendors[vendor] += 1

        return CatalogStatistics(
            entity_type=entity_type,
            total_entities=total_entities,
            total_aliases=total_aliases,
            categories=dict(categories),
            vendors=dict(vendors)
        )

    # === Entités Non Cataloguées ===

    def parse_uncataloged_log(self) -> List[UncatalogedEntity]:
        """Parse le fichier uncataloged_entities.log."""
        log_path = self.ontology_dir / "uncataloged_entities.log"

        if not log_path.exists():
            return []

        # Agréger par (entity_type, raw_name)
        aggregated = defaultdict(lambda: {
            "occurrences": 0,
            "first_seen": None,
            "last_seen": None,
            "tenants": set()
        })

        with open(log_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                # Format: 2025-10-05 14:23:11 | COMPONENT | "Custom LB" | tenant=acme
                match = re.match(
                    r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| (\w+) \| "([^"]+)" \| tenant=(\w+)',
                    line
                )

                if match:
                    timestamp, entity_type_str, raw_name, tenant = match.groups()

                    key = (entity_type_str, raw_name)
                    entry = aggregated[key]

                    entry["occurrences"] += 1
                    entry["tenants"].add(tenant)

                    if not entry["first_seen"]:
                        entry["first_seen"] = timestamp

                    entry["last_seen"] = timestamp

        # Convertir en liste UncatalogedEntity
        uncataloged = []
        for (entity_type_str, raw_name), data in aggregated.items():
            try:
                entity_type = EntityType(entity_type_str)
            except ValueError:
                continue

            # Générer suggestion entity_id
            suggested_id = self._suggest_entity_id(raw_name)

            uncataloged.append(
                UncatalogedEntity(
                    raw_name=raw_name,
                    entity_type=entity_type,
                    occurrences=data["occurrences"],
                    first_seen=data["first_seen"],
                    last_seen=data["last_seen"],
                    tenants=list(data["tenants"]),
                    suggested_entity_id=suggested_id
                )
            )

        # Trier par occurrences décroissant
        uncataloged.sort(key=lambda x: x.occurrences, reverse=True)

        return uncataloged

    def _suggest_entity_id(self, raw_name: str) -> str:
        """Suggère un entity_id basé sur raw_name."""
        # Nettoyer et convertir en SNAKE_CASE_MAJUSCULES
        cleaned = re.sub(r'[^\w\s-]', '', raw_name)
        cleaned = re.sub(r'[-\s]+', '_', cleaned)
        cleaned = cleaned.strip('_').upper()
        return cleaned

    def approve_uncataloged(
        self,
        entity_type: EntityType,
        raw_name: str,
        approve_data: UncatalogedEntityApprove
    ) -> EntityCatalogResponse:
        """Approuve une entité non cataloguée (ajoute au catalogue)."""
        # Créer entité avec raw_name ajouté aux aliases
        aliases = approve_data.aliases.copy()
        if raw_name not in aliases:
            aliases.insert(0, raw_name)

        entity_create = EntityCatalogCreate(
            entity_type=entity_type,
            entity_id=approve_data.entity_id,
            canonical_name=approve_data.canonical_name,
            aliases=aliases,
            category=approve_data.category,
            vendor=approve_data.vendor
        )

        # Créer dans catalogue
        result = self.create_entity(entity_create)

        # TODO: Supprimer ligne du log ou marquer comme approved

        logger.info(
            f"✅ Entité non cataloguée approuvée: '{raw_name}' → {approve_data.entity_id}"
        )

        return result

    def reject_uncataloged(
        self,
        entity_type: EntityType,
        raw_name: str
    ) -> None:
        """Rejette une entité non cataloguée (supprime du log)."""
        # TODO: Implémenter suppression/marquage dans log
        logger.info(
            f"❌ Entité non cataloguée rejetée: '{raw_name}' (type={entity_type.value})"
        )

    # === Import en masse ===

    def bulk_import(
        self,
        entity_type: EntityType,
        entities: List[EntityCatalogCreate],
        overwrite_existing: bool = False
    ) -> CatalogBulkImportResult:
        """Import en masse d'entités."""
        catalog = self._load_catalog(entity_type)

        created = 0
        updated = 0
        skipped = 0
        errors = []

        for entity_data in entities:
            try:
                if entity_data.entity_id in catalog:
                    if overwrite_existing:
                        # Mettre à jour
                        catalog[entity_data.entity_id] = {
                            "canonical_name": entity_data.canonical_name,
                            "aliases": entity_data.aliases,
                        }
                        if entity_data.category:
                            catalog[entity_data.entity_id]["category"] = entity_data.category
                        if entity_data.vendor:
                            catalog[entity_data.entity_id]["vendor"] = entity_data.vendor
                        updated += 1
                    else:
                        skipped += 1
                else:
                    # Créer nouveau
                    catalog[entity_data.entity_id] = {
                        "canonical_name": entity_data.canonical_name,
                        "aliases": entity_data.aliases,
                    }
                    if entity_data.category:
                        catalog[entity_data.entity_id]["category"] = entity_data.category
                    if entity_data.vendor:
                        catalog[entity_data.entity_id]["vendor"] = entity_data.vendor
                    created += 1

            except Exception as e:
                errors.append(f"Erreur {entity_data.entity_id}: {str(e)}")

        # Sauvegarder
        self._save_catalog(entity_type, catalog)

        logger.info(
            f"✅ Import en masse: {created} créées, {updated} mises à jour, "
            f"{skipped} ignorées, {len(errors)} erreurs"
        )

        return CatalogBulkImportResult(
            entity_type=entity_type,
            total_processed=len(entities),
            created=created,
            updated=updated,
            skipped=skipped,
            errors=errors
        )


__all__ = ["OntologyService"]
