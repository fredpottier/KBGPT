"""
OSMOSE Scope Layer - Topic & Scope Description Extractor

Extracteurs simples pour dériver:
- document.topic depuis le titre/métadonnées
- section.scope_description depuis le chemin de section

ADR: doc/ongoing/ADR_SCOPE_VS_ASSERTION_SEPARATION.md

Author: Claude Code
Date: 2026-01-21
"""

import re
from typing import Optional, List
from dataclasses import dataclass


@dataclass
class ScopeExtractionResult:
    """Résultat d'extraction de scope."""
    topic: Optional[str] = None
    scope_description: Optional[str] = None
    scope_keywords: List[str] = None

    def __post_init__(self):
        if self.scope_keywords is None:
            self.scope_keywords = []


# Keywords qui indiquent un scope spécifique (pour boosting Anchored)
SCOPE_KEYWORDS = {
    "requirements": ["requirements", "prerequisites", "prérequis", "minimum", "sizing"],
    "security": ["security", "sécurité", "authentication", "authorization", "tls", "ssl", "encryption"],
    "configuration": ["configuration", "settings", "paramètres", "setup", "installation"],
    "architecture": ["architecture", "design", "overview", "introduction", "structure"],
    "migration": ["migration", "upgrade", "conversion", "transition"],
    "integration": ["integration", "intégration", "connectivity", "interface", "api"],
    "operations": ["operations", "administration", "maintenance", "monitoring"],
    "troubleshooting": ["troubleshooting", "issues", "problems", "errors", "debug"],
}


def extract_document_topic(
    document_name: Optional[str] = None,
    document_title: Optional[str] = None,
    document_path: Optional[str] = None
) -> Optional[str]:
    """
    Extrait le topic principal d'un document.

    Stratégie V1 (simple):
    1. Utilise le titre si disponible
    2. Sinon, utilise le nom du fichier
    3. Nettoie les suffixes techniques (.pdf, _v2, etc.)

    Args:
        document_name: Nom du document (ex: "S4HANA_Security_Guide.pdf")
        document_title: Titre extrait du document (ex: "SAP S/4HANA Security Guide")
        document_path: Chemin complet du fichier

    Returns:
        Topic extrait ou None
    """
    # Priorité au titre explicite
    if document_title:
        return _clean_topic(document_title)

    # Sinon, utilise le nom du document
    if document_name:
        return _clean_topic(document_name)

    # Dernier recours: extraire du chemin
    if document_path:
        # Extraire le nom de fichier
        filename = document_path.split("/")[-1].split("\\")[-1]
        return _clean_topic(filename)

    return None


def _clean_topic(raw_topic: str) -> str:
    """Nettoie un topic brut."""
    topic = raw_topic

    # Supprimer les extensions de fichier
    topic = re.sub(r'\.(pdf|pptx?|docx?|xlsx?|txt|md)$', '', topic, flags=re.IGNORECASE)

    # Supprimer les suffixes de version
    topic = re.sub(r'[_\-]v\d+(\.\d+)?$', '', topic, flags=re.IGNORECASE)
    topic = re.sub(r'[_\-]?full$', '', topic, flags=re.IGNORECASE)

    # Remplacer underscores par espaces
    topic = topic.replace('_', ' ')

    # Normaliser les espaces
    topic = ' '.join(topic.split())

    return topic.strip()


def extract_scope_description(
    section_path: str,
    section_title: Optional[str] = None
) -> ScopeExtractionResult:
    """
    Extrait la description de scope d'une section.

    Stratégie V1 (simple):
    1. Utilise le titre de section comme scope_description
    2. Extrait les keywords de scope pour le boosting

    Args:
        section_path: Chemin de section (ex: "1.2.3 Security Architecture")
        section_title: Titre de section (si différent du path)

    Returns:
        ScopeExtractionResult avec description et keywords
    """
    # Utilise le titre si fourni, sinon extrait du path
    if section_title:
        description = section_title
    else:
        # Extraire le titre du section_path (enlever les numéros)
        description = re.sub(r'^[\d\.\s]+', '', section_path).strip()

    # Extraire les keywords de scope
    keywords = _extract_scope_keywords(description)

    return ScopeExtractionResult(
        scope_description=description if description else None,
        scope_keywords=keywords
    )


def _extract_scope_keywords(text: str) -> List[str]:
    """Extrait les keywords de scope d'un texte."""
    text_lower = text.lower()
    keywords = []

    for category, category_keywords in SCOPE_KEYWORDS.items():
        for keyword in category_keywords:
            if keyword in text_lower:
                if category not in keywords:
                    keywords.append(category)
                break

    return keywords


def derive_scope_from_section_path(section_path: str) -> str:
    """
    Dérive une description de scope simple depuis le section_path.

    Utilisé quand on n'a que le section_path et pas d'analyse plus poussée.

    Args:
        section_path: Ex: "1.2.3 Security Architecture"

    Returns:
        Scope description: Ex: "Security Architecture"
    """
    # Enlever les numéros de section au début
    description = re.sub(r'^[\d\.\s]+', '', section_path).strip()
    return description if description else section_path


def extract_mentioned_concepts_from_text(
    text: str,
    known_concept_names: List[str]
) -> List[str]:
    """
    Extrait les concepts mentionnés dans un texte.

    Stratégie V1 (simple):
    - Recherche par matching exact (case-insensitive)
    - Retourne les concept_ids des concepts trouvés

    Args:
        text: Texte à analyser
        known_concept_names: Liste des noms de concepts connus

    Returns:
        Liste des noms de concepts trouvés dans le texte
    """
    text_lower = text.lower()
    found = []

    for concept_name in known_concept_names:
        # Matching case-insensitive
        if concept_name.lower() in text_lower:
            found.append(concept_name)

    return found
