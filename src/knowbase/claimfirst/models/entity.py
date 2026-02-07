# src/knowbase/claimfirst/models/entity.py
"""
Modèle Entity - Ancre de navigation (pas structurante).

INV-4: Entity sans rôle structurant (V1)
- Pas de `role` (primary/secondary) — reporté à V2
- La relation `ABOUT` existe mais sans attribut `role` pour commencer
- Toutes les mentions sont équivalentes en V1
- L'heuristique "premier tiers = primary" est trop fragile

INV-5: EntityExtractor enrichi (pas juste NER)
- Termes capitalisés répétés
- Titres de sections / headings
- Acronymes (pattern [A-Z]{2,})
- Patterns syntaxiques: "X is ...", "X allows ...", "X must ..."
- Stoplist métier pour exclure termes trop génériques

Règle: Entity ne porte AUCUNE vérité. Pas de rôle structurant.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class EntityType(str, Enum):
    """Types d'entités extraites."""

    PRODUCT = "product"
    """Produit logiciel ou service (ex: "SAP BTP", "S/4HANA")."""

    SERVICE = "service"
    """Service ou composant (ex: "Cloud Connector", "Identity Service")."""

    FEATURE = "feature"
    """Fonctionnalité (ex: "Single Sign-On", "Data Encryption")."""

    ACTOR = "actor"
    """Acteur ou rôle (ex: "Customer", "Administrator", "SAP")."""

    CONCEPT = "concept"
    """Concept technique ou métier (ex: "TLS", "GDPR", "Compliance")."""

    LEGAL_TERM = "legal_term"
    """Terme juridique ou contractuel (ex: "SLA", "DPA", "Liability")."""

    STANDARD = "standard"
    """Standard ou certification (ex: "ISO 27001", "SOC 2", "HIPAA")."""

    OTHER = "other"
    """Autre type non catégorisé."""


class Entity(BaseModel):
    """
    Entity - Ancre de navigation pour les Claims.

    Une Entity est un terme ou concept mentionné dans les claims,
    servant d'ancre de navigation. Elle ne porte AUCUNE vérité
    (pas de rôle structurant en V1).

    Attributes:
        entity_id: Identifiant unique
        tenant_id: Tenant multi-locataire
        name: Nom original de l'entité
        entity_type: Type de l'entité
        aliases: Alias connus (variantes orthographiques)
        normalized_name: Nom normalisé (lowercase, stripped)
    """

    entity_id: str = Field(
        ...,
        description="Identifiant unique de l'entité"
    )

    tenant_id: str = Field(
        ...,
        description="Identifiant du tenant"
    )

    name: str = Field(
        ...,
        min_length=1,
        description="Nom original de l'entité"
    )

    entity_type: EntityType = Field(
        default=EntityType.OTHER,
        description="Type de l'entité"
    )

    aliases: List[str] = Field(
        default_factory=list,
        description="Alias connus (variantes orthographiques)"
    )

    normalized_name: str = Field(
        default="",
        description="Nom normalisé (lowercase, stripped)"
    )

    # Métadonnées optionnelles
    source_doc_ids: List[str] = Field(
        default_factory=list,
        description="Documents où l'entité a été extraite"
    )

    mention_count: int = Field(
        default=1,
        ge=1,
        description="Nombre de mentions dans les claims"
    )

    def model_post_init(self, __context) -> None:
        """Calcule le nom normalisé après initialisation si non fourni."""
        if not self.normalized_name and self.name:
            # Utiliser object.__setattr__ pour contourner Pydantic frozen
            object.__setattr__(self, "normalized_name", self.normalize(self.name))

    @staticmethod
    def normalize(name: str) -> str:
        """
        Normalise un nom d'entité.

        - Lowercase
        - Strip whitespace
        - Remove special chars (keep alphanumeric and spaces)
        - Collapse multiple spaces
        """
        if not name:
            return ""
        # Lowercase et strip
        normalized = name.lower().strip()
        # Garder alphanumeric, espaces et tirets
        normalized = re.sub(r"[^\w\s\-]", "", normalized)
        # Collapse multiple spaces
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized

    def matches(self, text: str) -> bool:
        """
        Vérifie si l'entité est mentionnée dans un texte.

        Compare le normalized_name et les aliases contre le texte normalisé.
        """
        text_normalized = self.normalize(text)

        # Check normalized name
        if self.normalized_name and self.normalized_name in text_normalized:
            return True

        # Check aliases
        for alias in self.aliases:
            alias_normalized = self.normalize(alias)
            if alias_normalized and alias_normalized in text_normalized:
                return True

        return False

    def to_neo4j_properties(self) -> dict:
        """Convertit en propriétés pour Neo4j."""
        return {
            "entity_id": self.entity_id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "entity_type": self.entity_type.value,
            "aliases": self.aliases if self.aliases else None,
            "normalized_name": self.normalized_name,
            "source_doc_ids": self.source_doc_ids if self.source_doc_ids else None,
            "mention_count": self.mention_count,
        }

    @classmethod
    def from_neo4j_record(cls, record: dict) -> "Entity":
        """Construit une Entity depuis un record Neo4j."""
        return cls(
            entity_id=record["entity_id"],
            tenant_id=record["tenant_id"],
            name=record["name"],
            entity_type=EntityType(record.get("entity_type", "other")),
            aliases=record.get("aliases") or [],
            normalized_name=record.get("normalized_name", ""),
            source_doc_ids=record.get("source_doc_ids") or [],
            mention_count=record.get("mention_count", 1),
        )


# Stoplist métier (termes trop génériques)
ENTITY_STOPLIST = frozenset({
    # Termes génériques anglais
    "system", "information", "data", "service", "process",
    "document", "section", "table", "figure", "example",
    "user", "customer", "administrator", "admin",
    "application", "software", "platform", "solution",
    "request", "response", "error", "warning", "message",
    "value", "parameter", "option", "setting", "configuration",
    "feature", "function", "method", "operation",
    "file", "folder", "directory", "path",
    "time", "date", "version", "number", "id", "identifier",
    "type", "kind", "category", "class", "group",
    "note", "tip", "important", "warning", "caution",
    "object", "item", "element", "component", "module",
    "content", "detail", "details", "summary", "overview",
    "result", "results", "output", "input", "entry",
    "case", "scenario", "instance", "example", "sample",
    "step", "steps", "action", "task", "activity",

    # Termes déictiques et articles (NE JAMAIS être des entités)
    "this", "that", "these", "those",
    "it", "its", "itself",
    "a", "an", "the",
    "some", "any", "all", "each", "every",
    "one", "other", "another",

    # Termes génériques français
    "système", "information", "donnée", "service", "processus",
    "document", "section", "tableau", "figure", "exemple",
    "utilisateur", "client", "administrateur",
    "application", "logiciel", "plateforme", "solution",
    "requête", "réponse", "erreur", "avertissement",
    "valeur", "paramètre", "option", "configuration",
    "fonctionnalité", "fonction", "méthode", "opération",
    "fichier", "dossier", "répertoire", "chemin",
    "temps", "date", "version", "numéro", "identifiant",
    "objet", "élément", "composant", "module",
    "contenu", "détail", "détails", "résumé", "aperçu",
    "résultat", "résultats", "sortie", "entrée",
    "cas", "scénario", "instance", "exemple", "échantillon",
    "étape", "étapes", "action", "tâche", "activité",
    # Termes déictiques français
    "ce", "cette", "ces", "cet",
    "un", "une", "le", "la", "les",
    "quelque", "quelques", "tout", "tous", "toute", "toutes",
    "chaque", "autre", "autres",
})

# Patterns indiquant un fragment de phrase (pas une entité)
PHRASE_FRAGMENT_INDICATORS = frozenset({
    # Verbes modaux anglais
    "will", "would", "shall", "should", "can", "could", "may", "might", "must",
    # Verbes auxiliaires
    "is", "are", "was", "were", "be", "been", "being",
    "has", "have", "had", "having",
    "do", "does", "did", "doing",
    # Verbes modaux français
    "doit", "devrait", "peut", "pourrait", "sera", "serait",
})


def is_valid_entity_name(name: str) -> bool:
    """
    Vérifie si un nom d'entité est valide.

    Rejette:
    - Termes dans la stoplist
    - Noms trop courts (<2 caractères), sauf acronymes majuscules
    - Noms trop longs (>80 caractères = probablement une phrase)
    - Noms commençant par des déictiques
    - Noms contenant des indicateurs de fragments de phrase

    Args:
        name: Nom à vérifier

    Returns:
        True si le nom est valide pour être une entité
    """
    if not name:
        return False

    name_stripped = name.strip()
    normalized = Entity.normalize(name)

    # Acronyme majuscule (2-5 lettres) = toujours valide
    # Ex: EU, AD, BW, TLS, GDPR
    if re.match(r"^[A-Z]{2,5}$", name_stripped):
        return True

    # Trop court pour un non-acronyme
    if len(normalized) < 3:
        return False

    # Trop long (probablement une phrase)
    if len(normalized) > 80:
        return False

    # Dans la stoplist
    if normalized in ENTITY_STOPLIST:
        return False

    # Commence par un terme déictique ou article
    first_word = normalized.split()[0] if normalized.split() else ""
    if first_word in {"this", "that", "these", "those", "the", "a", "an",
                      "ce", "cette", "ces", "cet", "le", "la", "les", "un", "une"}:
        return False

    # Contient des indicateurs de fragment de phrase
    words = set(normalized.lower().split())
    if words & PHRASE_FRAGMENT_INDICATORS:
        return False

    # Trop de mots (>8 = probablement une phrase)
    if len(normalized.split()) > 8:
        return False

    return True


__all__ = [
    "Entity",
    "EntityType",
    "ENTITY_STOPLIST",
    "PHRASE_FRAGMENT_INDICATORS",
    "is_valid_entity_name",
]
