# src/knowbase/domain_packs/base.py
"""
Classes abstraites pour les Domain Packs OSMOSE.

Un Domain Pack est un bundle de configuration et d'extracteurs spécialisés
qu'un administrateur active pour un tenant.

INV-PACK : Le pack augmente le recall. Le core garde le monopole de la décision.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, List, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from knowbase.claimfirst.models.claim import Claim
    from knowbase.claimfirst.models.entity import Entity, EntityType
    from knowbase.ontology.domain_context import DomainContextProfile

logger = logging.getLogger(__name__)


class DomainEntityExtractor(ABC):
    """
    Extracteur d'entités spécialisé domaine.

    Opère en post-processing sur les claims non couvertes
    par l'extracteur générique.
    """

    @abstractmethod
    def load_model(self) -> None:
        """Charge le modèle NER (lazy, une seule fois)."""

    @abstractmethod
    def extract(
        self,
        claims: "List[Claim]",
        existing_entities: "List[Entity]",
        domain_context: "DomainContextProfile",
    ) -> "Tuple[List[Entity], Dict[str, List[str]]]":
        """
        Extrait des entités domaine via NER.

        Args:
            claims: Claims à analyser (typiquement les isolées)
            existing_entities: Entités déjà extraites (pour éviter doublons)
            domain_context: Profil domaine du tenant

        Returns:
            (nouvelles_entités, {claim_id: [entity_ids]})
        """

    @property
    @abstractmethod
    def entity_type_mapping(self) -> "Dict[str, EntityType]":
        """Mapping types NER → EntityType OSMOSE.

        Exemple biomédical :
            'CHEMICAL' → EntityType.CONCEPT
            'DISEASE'  → EntityType.CONCEPT
        """


class DomainPack(ABC):
    """
    Package métier activable pour un tenant.

    Un DomainPack peut proposer plus de matière,
    mais il ne doit jamais changer les lois de la gravité d'OSMOSE.

    Les données de configuration (acronymes, concepts, stoplist) sont
    chargées depuis un fichier JSON co-localisé avec le pack, modifiable
    sans toucher au code Python.
    """

    def __init__(self):
        self._defaults_cache: dict | None = None

    @property
    @abstractmethod
    def name(self) -> str:
        """Identifiant unique du pack (ex: 'biomedical')."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Nom affiché dans l'UI."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Description pour l'admin."""

    @property
    def version(self) -> str:
        """Version du pack."""
        return "1.0.0"

    @property
    def priority(self) -> int:
        """Priorité d'exécution (plus élevé = exécuté en premier).

        Valeurs indicatives :
            100 = pack domaine principal (biomedical, enterprise_sap)
             50 = pack transverse (regulatory, compliance)
              0 = pack générique / fallback
        """
        return 50

    def _load_defaults_json(self) -> dict:
        """Charge le fichier context_defaults.json co-localisé avec le pack.

        Le fichier est cherché dans le même répertoire que le module Python
        du pack concret. Résultat mis en cache.

        Returns:
            Contenu du JSON, ou dict vide si fichier absent.
        """
        if self._defaults_cache is not None:
            return self._defaults_cache

        # Trouver le répertoire du module concret (pas de base.py)
        module = type(self).__module__
        try:
            import importlib
            mod = importlib.import_module(module)
            if mod.__file__:
                pack_dir = Path(mod.__file__).parent
            else:
                self._defaults_cache = {}
                return {}
        except Exception:
            self._defaults_cache = {}
            return {}

        json_path = pack_dir / "context_defaults.json"
        if not json_path.exists():
            logger.debug(
                f"[DomainPack:{self.name}] No context_defaults.json found at {json_path}"
            )
            self._defaults_cache = {}
            return {}

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                self._defaults_cache = json.load(f)
            logger.info(
                f"[DomainPack:{self.name}] Loaded context_defaults.json "
                f"({len(self._defaults_cache)} keys)"
            )
        except Exception as e:
            logger.error(
                f"[DomainPack:{self.name}] Error loading context_defaults.json: {e}"
            )
            self._defaults_cache = {}

        return self._defaults_cache

    def get_entity_extractors(self) -> List[DomainEntityExtractor]:
        """Extracteurs d'entités complémentaires."""
        return []

    def get_domain_context_defaults(self) -> dict:
        """Valeurs par défaut pour DomainContextProfile.

        Charge depuis context_defaults.json co-localisé avec le pack.
        Clés attendues: domain_summary, industry, common_acronyms, key_concepts.
        """
        defaults = self._load_defaults_json()
        return {
            k: v for k, v in defaults.items()
            if k in ("domain_summary", "industry", "common_acronyms", "key_concepts")
        }

    def get_entity_stoplist(self) -> List[str]:
        """Termes à exclure spécifiques au domaine.

        Charge depuis la clé 'entity_stoplist' du context_defaults.json.
        """
        defaults = self._load_defaults_json()
        return defaults.get("entity_stoplist", [])

    def get_product_gazetteer(self) -> List[str]:
        """Liste de canonicals d'entités du domaine (produits, concepts stables).

        Cette liste est utilisee par le SubjectResolver pour contraindre le
        choix du ComparableSubject a des canonicals connus du domaine, evitant
        la derive et les doublons (ex: "S/4HANA" vs "SAP S/4HANA" vs "S/4HANA
        Cloud Private Edition" tous traites comme des entites differentes).

        IMPORTANT : la liste doit etre ordonnee du MOINS specifique au PLUS
        specifique quand il y a une hierarchie implicite. Exemple pour SAP :
            - "SAP S/4HANA" (parent)
            - "SAP S/4HANA Cloud" (enfant)
            - "SAP S/4HANA Cloud Private Edition" (petit-enfant)
            - "SAP S/4HANA Cloud Public Edition" (petit-enfant)
        Le SubjectResolver prefererera le PLUS COURT match quand plusieurs
        canonicals correspondent.

        Un pack qui n'a pas de gazetteer explicite retourne une liste vide —
        le resolver revient alors a son comportement LLM libre (comportement
        historique, avant cette feature).

        Charge depuis la cle 'product_gazetteer' du context_defaults.json.
        """
        defaults = self._load_defaults_json()
        gazetteer = defaults.get("product_gazetteer", [])
        if not isinstance(gazetteer, list):
            logger.warning(
                f"[DomainPack:{self.name}] product_gazetteer is not a list, ignoring"
            )
            return []
        return [str(item).strip() for item in gazetteer if item]

    def get_canonical_aliases(self) -> dict:
        """Table d'alias -> canonical pour la resolution d'entites.

        Permet de mapper des variantes communes (acronymes, orthographes
        alternatives) vers leur forme canonique preferee. Utilise conjointement
        avec le product_gazetteer par le SubjectResolver.

        Exemple pour SAP :
            {"S/4": "SAP S/4HANA", "S4HC": "SAP S/4HANA Cloud", "PCE":
             "SAP S/4HANA Cloud Private Edition"}

        Retourne un dict vide si le pack n'en fournit pas.

        Charge depuis la cle 'canonical_aliases' du context_defaults.json.
        """
        defaults = self._load_defaults_json()
        aliases = defaults.get("canonical_aliases", {})
        if not isinstance(aliases, dict):
            logger.warning(
                f"[DomainPack:{self.name}] canonical_aliases is not a dict, ignoring"
            )
            return {}
        return {str(k): str(v) for k, v in aliases.items() if k and v}


__all__ = ["DomainPack", "DomainEntityExtractor"]
