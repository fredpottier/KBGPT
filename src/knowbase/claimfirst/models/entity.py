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
from typing import List, Optional, Tuple

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


# Pattern domain-agnostic pour séparer un suffixe version d'un nom d'entity
# Exemples : "S/4HANA 2023" → ("S/4HANA", "2023"), "React 18.2" → ("React", "18.2")
VERSION_TAIL_PATTERN = re.compile(
    r'^(.+?)\s+'              # nom de base (non-greedy)
    r'(v?\d+(?:\.\d+)*'       # version numérique: "2023", "v3.2", "18.2.1"
    r'|[IVX]+(?:\.[IVX]+)*'   # version romaine: "III", "IV.2"
    r')$',
    re.IGNORECASE
)


def strip_version_qualifier(name: str) -> Tuple[str, Optional[str]]:
    """
    Sépare un nom d'entity de son éventuel suffixe version.

    Domain-agnostic : fonctionne pour tout produit/standard/concept.

    Exemples:
        "S/4HANA 2023" → ("S/4HANA", "2023")
        "Windows 11"   → ("Windows", "11")
        "React 18.2"   → ("React", "18.2")
        "Clio III"     → ("Clio", "III")
        "SAP BTP"      → ("SAP BTP", None)  # pas de version
        "v2"           → ("v2", None)  # base trop courte

    Returns:
        Tuple (base_name, version_qualifier) — version est None si absent
    """
    stripped = name.strip()
    m = VERSION_TAIL_PATTERN.match(stripped)
    if m:
        base = m.group(1).strip()
        version = m.group(2).strip()
        # Garder seulement si le nom de base est significatif (>=2 chars)
        if len(base) >= 2:
            return base, version
    return stripped, None


# Stoplist métier (termes trop génériques)
ENTITY_STOPLIST = frozenset({
    # Termes génériques anglais (singuliers)
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
    # Pluriels courants (manquants, détectés par audit qualité v1.6.1)
    "systems", "services", "processes", "documents", "applications",
    "users", "customers", "administrators", "items", "elements",
    "components", "modules", "functions", "objects", "features",
    "files", "operations", "methods", "parameters", "options",
    "settings", "configurations", "values", "messages", "entries",
    "tasks", "activities", "actions", "solutions", "platforms",
    # Termes suffisamment génériques pour être du bruit dans tout domaine
    "integration", "monitoring", "report", "reports",
    # Mots anglais courants qui se déguisent en acronymes 2-5 lettres
    # (passent le filtre acronyme ^[A-Z]{2,5}$ mais ne sont pas des acronymes)
    "as", "new", "up", "non", "map", "fix", "key", "end",
    "add", "top", "per", "via", "due", "own", "old",

    # Termes déictiques et articles (NE JAMAIS être des entités)
    "this", "that", "these", "those",
    "it", "its", "itself",
    "a", "an", "the",
    "some", "any", "all", "each", "every",
    "one", "other", "another",

    # Prépositions anglaises (mots-outils, jamais des entities)
    "to", "of", "in", "on", "at", "by", "for", "with", "from",
    "into", "onto", "upon", "about", "between", "through",
    "over", "under", "after", "before", "during", "without",
    # Conjonctions et négations
    "and", "or", "but", "not", "no", "nor", "yet", "so",
    "if", "then", "else", "because", "since", "while", "although",
    # Adverbes courants
    "also", "than", "very", "only", "just",
    "here", "there", "now", "already", "still",
    # Verbes trop courts / génériques (formes simples, pas des noms propres)
    "use", "used", "uses", "using",
    "set", "get", "run", "put", "let",
    "made", "make", "take", "give", "keep",
    "need", "needs", "needed",
    # Pronoms et déterminants manquants
    "he", "she", "we", "they", "you", "me", "him", "us", "them",
    "his", "her", "our", "your", "their", "my",
    "which", "where", "when", "how", "what", "who", "whom",

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

# Mots-outils purs (prépositions, conjonctions, pronoms, articles) qui ne doivent
# JAMAIS commencer un nom d'entity multi-mots. Séparé de ENTITY_STOPLIST qui contient
# aussi des termes domaine génériques ("system", "activity") valides comme premier mot.
_FUNCTION_WORDS = frozenset({
    # Prépositions
    "to", "of", "in", "on", "at", "by", "for", "with", "from",
    "into", "onto", "upon", "about", "between", "through",
    "over", "under", "after", "before", "during", "without",
    # Conjonctions / négations
    "and", "or", "but", "not", "no", "nor", "yet", "so",
    "if", "then", "else", "because", "since", "while", "although",
    # Adverbes
    "also", "than", "very", "only", "just",
    "here", "there", "now", "already", "still",
    # Pronoms
    "he", "she", "we", "they", "you", "me", "him", "us", "them",
    "his", "her", "our", "your", "their", "my",
    "which", "where", "when", "how", "what", "who", "whom",
    # Déictiques / articles
    "this", "that", "these", "those", "it", "its",
    "a", "an", "the", "some", "any", "each", "every",
    # Adj. non-informatifs en début de nom
    "different", "certain", "other", "various", "several",
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

    # Vérifier stoplist EN PREMIER (même les acronymes comme "IS", "OF", "TO")
    if normalized in ENTITY_STOPLIST:
        return False

    # Contient des indicateurs de fragment de phrase
    words = set(normalized.lower().split())
    if words & PHRASE_FRAGMENT_INDICATORS:
        return False

    # Pas que des chiffres / codes numériques
    if re.sub(r"[\s\-_./]", "", normalized).isdigit():
        return False

    # Acronyme majuscule (2-5 lettres) = valide si pas dans la stoplist
    # Ex: EU, AD, BW, TLS, GDPR
    if re.match(r"^[A-Z]{2,5}$", name_stripped):
        return True

    # Trop court pour un non-acronyme
    if len(normalized) < 3:
        return False

    # Trop long (probablement une phrase)
    if len(normalized) > 80:
        return False

    # Multi-mots : le premier mot ne doit pas être un mot-outil de la langue
    # (prépositions, conjonctions, pronoms — PAS les termes domaine comme "system", "activity")
    words = normalized.split()
    if len(words) > 1:
        first_word = words[0]
        if first_word in _FUNCTION_WORDS or first_word in PHRASE_FRAGMENT_INDICATORS:
            return False

    # Trop de mots (>8 = probablement une phrase)
    if len(words) > 8:
        return False

    return True


__all__ = [
    "Entity",
    "EntityType",
    "ENTITY_STOPLIST",
    "PHRASE_FRAGMENT_INDICATORS",
    "VERSION_TAIL_PATTERN",
    "is_valid_entity_name",
    "strip_version_qualifier",
]
