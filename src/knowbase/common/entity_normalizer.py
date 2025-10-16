"""
Service de normalisation des noms d'entités Knowledge Graph.
Remplace et généralise la normalisation SAP-spécifique.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple
import yaml

from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "entity_normalizer.log")


class EntityNormalizer:
    """
    Service de normalisation des noms d'entités pour tous les types.

    Stratégie de performance :
    - Chargement lazy par type (pas tout en mémoire)
    - Cache en mémoire après premier accès
    - Index inverse aliases → canonical pour recherche O(1)
    """

    def __init__(self):
        self.ontology_dir = Path(settings.config_dir) / "ontologies"
        self._catalogs: Dict[str, Dict] = {}  # entity_type (str) → catalog
        self._alias_index: Dict[str, Dict[str, str]] = {}  # entity_type (str) → aliases
        self._loaded_types: set[str] = set()  # Types déjà chargés

        # Créer répertoire ontologies si absent
        self.ontology_dir.mkdir(parents=True, exist_ok=True)

    def normalize_entity_name(
        self,
        raw_name: str,
        entity_type: str
    ) -> Tuple[Optional[str], str, bool]:
        """
        Normalise un nom d'entité brut vers sa forme canonique.

        Args:
            raw_name: Nom brut extrait par LLM
            entity_type: Type d'entité (string UPPERCASE, ex: "SOLUTION", "INFRASTRUCTURE")

        Returns:
            Tuple[entity_id, canonical_name, is_cataloged]
            - entity_id: Identifiant catalogue (ex: "LOAD_BALANCER") ou None si non catalogué
            - canonical_name: Nom normalisé (ex: "Load Balancer") ou raw_name si non trouvé
            - is_cataloged: True si trouvé dans ontologie YAML, False sinon

        Si pas de correspondance catalogue → retourne (None, raw_name.strip(), False)
        """
        # Lazy load du catalogue si nécessaire
        if entity_type not in self._loaded_types:
            self._load_catalog(entity_type)

        # Normalisation basique
        normalized_search = raw_name.strip().lower()

        # Recherche dans l'index d'aliases
        alias_index = self._alias_index.get(entity_type, {})

        if normalized_search in alias_index:
            entity_id = alias_index[normalized_search]
            catalog = self._catalogs[entity_type]
            canonical_name = catalog[entity_id]["canonical_name"]
            logger.debug(
                f"✅ Normalisé: '{raw_name}' → '{canonical_name}' "
                f"(type={entity_type}, id={entity_id})"
            )
            return entity_id, canonical_name, True  # Catalogué

        # Pas de correspondance → retourner brut (nettoyé)
        logger.debug(
            f"⚠️  Entité non cataloguée: '{raw_name}' (type={entity_type})"
        )
        return None, raw_name.strip(), False  # Non catalogué

    def _load_catalog(self, entity_type: str) -> None:
        """
        Charge le catalogue d'ontologie pour un type donné.
        Construit l'index inverse aliases → entity_id.

        Args:
            entity_type: Type string UPPERCASE (ex: "SOLUTION", "INFRASTRUCTURE")
        """
        catalog_file = self.ontology_dir / f"{entity_type.lower()}s.yaml"

        if not catalog_file.exists():
            logger.warning(
                f"📂 Catalogue ontologie manquant: {catalog_file} "
                f"(type={entity_type})"
            )
            self._catalogs[entity_type] = {}
            self._alias_index[entity_type] = {}
            self._loaded_types.add(entity_type)
            return

        with open(catalog_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # Structure attendue: {ENTITY_ID: {canonical_name, aliases, ...}}
        root_key = f"{entity_type}S"  # SOLUTIONS, COMPONENTS, etc.
        catalog = data.get(root_key, {})

        # Construire index inverse
        alias_index = {}
        for entity_id, entity_data in catalog.items():
            canonical = entity_data["canonical_name"]
            aliases = entity_data.get("aliases", [])

            # Indexer canonical name (lowercase)
            alias_index[canonical.lower()] = entity_id

            # Indexer tous les aliases (lowercase)
            for alias in aliases:
                alias_index[alias.lower()] = entity_id

        self._catalogs[entity_type] = catalog
        self._alias_index[entity_type] = alias_index
        self._loaded_types.add(entity_type)

        logger.info(
            f"📖 Catalogue chargé: {entity_type} "
            f"({len(catalog)} entités, {len(alias_index)} aliases)"
        )

    def get_entity_metadata(
        self,
        entity_id: str,
        entity_type: str
    ) -> Optional[Dict]:
        """
        Récupère métadonnées complètes d'une entité cataloguée.

        Args:
            entity_id: ID entité dans catalogue
            entity_type: Type string UPPERCASE

        Returns:
            Dict avec canonical_name, aliases, category, vendor, etc.
            Ou None si entité non cataloguée.
        """
        if entity_type not in self._loaded_types:
            self._load_catalog(entity_type)

        catalog = self._catalogs.get(entity_type, {})
        return catalog.get(entity_id)

    def log_uncataloged_entity(
        self,
        raw_name: str,
        entity_type: str,
        tenant_id: str = "default"
    ) -> None:
        """
        Log une entité non cataloguée pour review admin ultérieure.

        Args:
            raw_name: Nom brut de l'entité
            entity_type: Type d'entité (string UPPERCASE)
            tenant_id: Tenant concerné
        """
        uncataloged_log = self.ontology_dir / "uncataloged_entities.log"

        with open(uncataloged_log, "a", encoding="utf-8") as f:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            f.write(
                f'{timestamp} | {entity_type} | "{raw_name}" | tenant={tenant_id}\n'
            )


# Instance globale singleton
_normalizer: Optional[EntityNormalizer] = None


def get_entity_normalizer() -> EntityNormalizer:
    """Retourne instance singleton du normalizer."""
    global _normalizer
    if _normalizer is None:
        _normalizer = EntityNormalizer()
    return _normalizer


__all__ = ["EntityNormalizer", "get_entity_normalizer"]
