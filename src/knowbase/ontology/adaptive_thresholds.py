"""
Seuils adaptatifs pour canonicalisation (P1.1).

Ajuste les seuils de confidence selon le contexte:
- Domaine technique (SAP, Cloud, IA)
- Langue (français, anglais, multilingue)
- Source (documentation officielle, forum, interne)
- Type d'entité (produit, concept, organisation)

Permet de gérer la variabilité de qualité des extractions LLM.
"""
from typing import Optional, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field
import logging

logger = logging.getLogger(__name__)


class DomainContext(str, Enum):
    """Domaines techniques couverts."""
    SAP_ECOSYSTEM = "sap_ecosystem"  # S/4HANA, SuccessFactors, etc.
    CLOUD_COMPUTING = "cloud_computing"  # AWS, Azure, GCP
    ARTIFICIAL_INTELLIGENCE = "artificial_intelligence"  # ML, NLP, Computer Vision
    ENTERPRISE_SOFTWARE = "enterprise_software"  # ERP, CRM, SCM
    CYBERSECURITY = "cybersecurity"  # Security, compliance
    GENERAL = "general"  # Domaine général


class LanguageContext(str, Enum):
    """Contextes linguistiques."""
    FRENCH = "french"  # Français
    ENGLISH = "english"  # Anglais
    MULTILINGUAL = "multilingual"  # Document multilingue
    TECHNICAL_JARGON = "technical_jargon"  # Jargon technique dense


class SourceContext(str, Enum):
    """Sources de documents."""
    OFFICIAL_DOCUMENTATION = "official_documentation"  # Docs officielles vendeur
    INTERNAL_DOCUMENTATION = "internal_documentation"  # Docs internes entreprise
    FORUM_COMMUNITY = "forum_community"  # Forums, communautés
    PRESENTATION_SLIDES = "presentation_slides"  # PPT, slides
    EMAILS_CHAT = "emails_chat"  # Emails, chat, messaging
    UNKNOWN = "unknown"  # Source inconnue


class EntityTypeContext(str, Enum):
    """Types d'entités."""
    PRODUCT = "PRODUCT"  # Produit logiciel
    CONCEPT = "CONCEPT"  # Concept technique
    ORGANIZATION = "ORGANIZATION"  # Organisation, entreprise
    PERSON = "PERSON"  # Personne
    TECHNOLOGY = "TECHNOLOGY"  # Technologie, framework
    UNKNOWN = "UNKNOWN"  # Type inconnu


class ThresholdProfile(BaseModel):
    """
    Profil de seuils adaptatifs pour un contexte donné.

    Chaque profil définit des seuils de confidence pour:
    - Fuzzy matching (similarité textuelle)
    - Auto-validation (sandbox)
    - Promotion (gate check)
    """
    name: str = Field(..., description="Nom du profil")

    # Seuils de matching
    fuzzy_match_threshold: float = Field(0.85, description="Seuil similarité fuzzy (0-1)")
    exact_match_required: bool = Field(False, description="Si exact match obligatoire")

    # Seuils auto-validation (P0.1 Sandbox)
    auto_validation_threshold: float = Field(0.95, description="Seuil auto-validation sandbox")
    require_human_validation_below: float = Field(0.80, description="En dessous, nécessite validation humaine")

    # Seuils promotion (Gatekeeper)
    promotion_threshold: float = Field(0.70, description="Seuil promotion Proto→Canonical")

    # Metadata
    description: str = Field("", description="Description du profil")
    applies_to: Dict[str, Any] = Field(default_factory=dict, description="Contextes d'application")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "SAP_OFFICIAL_DOCS",
                "fuzzy_match_threshold": 0.90,
                "exact_match_required": False,
                "auto_validation_threshold": 0.95,
                "require_human_validation_below": 0.85,
                "promotion_threshold": 0.75,
                "description": "Profil pour documentation SAP officielle (haute qualité)",
                "applies_to": {
                    "domain": "sap_ecosystem",
                    "source": "official_documentation",
                    "language": "english"
                }
            }
        }


# ============================================================================
# Profils Prédéfinis
# ============================================================================

THRESHOLD_PROFILES = {
    # Haute confiance: Docs officielles SAP/Cloud
    "SAP_OFFICIAL_DOCS": ThresholdProfile(
        name="SAP_OFFICIAL_DOCS",
        fuzzy_match_threshold=0.90,
        exact_match_required=False,
        auto_validation_threshold=0.95,
        require_human_validation_below=0.85,
        promotion_threshold=0.75,
        description="Documentation SAP officielle (haute qualité, nomenclature standardisée)",
        applies_to={
            "domain": DomainContext.SAP_ECOSYSTEM,
            "source": SourceContext.OFFICIAL_DOCUMENTATION
        }
    ),

    # Confiance moyenne: Docs internes entreprise
    "INTERNAL_DOCS": ThresholdProfile(
        name="INTERNAL_DOCS",
        fuzzy_match_threshold=0.85,
        exact_match_required=False,
        auto_validation_threshold=0.95,
        require_human_validation_below=0.75,
        promotion_threshold=0.70,
        description="Documentation interne (qualité variable, acronymes locaux)",
        applies_to={
            "source": SourceContext.INTERNAL_DOCUMENTATION
        }
    ),

    # Confiance basse: Forums, présentations
    "COMMUNITY_CONTENT": ThresholdProfile(
        name="COMMUNITY_CONTENT",
        fuzzy_match_threshold=0.80,
        exact_match_required=False,
        auto_validation_threshold=0.97,  # Plus strict car qualité variable
        require_human_validation_below=0.70,
        promotion_threshold=0.65,
        description="Contenu communautaire (forums, slides, emails) - qualité variable",
        applies_to={
            "source": [SourceContext.FORUM_COMMUNITY, SourceContext.PRESENTATION_SLIDES, SourceContext.EMAILS_CHAT]
        }
    ),

    # Très haute confiance: Produits SAP catalogués
    "SAP_PRODUCTS_CATALOG": ThresholdProfile(
        name="SAP_PRODUCTS_CATALOG",
        fuzzy_match_threshold=0.92,
        exact_match_required=False,
        auto_validation_threshold=0.98,  # Très strict
        require_human_validation_below=0.90,
        promotion_threshold=0.80,
        description="Produits SAP catalogués (S/4HANA, SuccessFactors, etc.) - très haute confiance requise",
        applies_to={
            "domain": DomainContext.SAP_ECOSYSTEM,
            "entity_type": EntityTypeContext.PRODUCT
        }
    ),

    # Confiance ajustée: Multilangue ou jargon technique
    "MULTILINGUAL_TECHNICAL": ThresholdProfile(
        name="MULTILINGUAL_TECHNICAL",
        fuzzy_match_threshold=0.82,
        exact_match_required=False,
        auto_validation_threshold=0.95,
        require_human_validation_below=0.75,
        promotion_threshold=0.68,
        description="Documents multilingues ou jargon technique dense (plus de tolérance)",
        applies_to={
            "language": [LanguageContext.MULTILINGUAL, LanguageContext.TECHNICAL_JARGON]
        }
    ),

    # Profil par défaut (fallback)
    "DEFAULT": ThresholdProfile(
        name="DEFAULT",
        fuzzy_match_threshold=0.85,
        exact_match_required=False,
        auto_validation_threshold=0.95,
        require_human_validation_below=0.80,
        promotion_threshold=0.70,
        description="Profil par défaut (balanced)",
        applies_to={}
    )
}


# ============================================================================
# Sélecteur de Profil Adaptatif
# ============================================================================

class AdaptiveThresholdSelector:
    """
    Sélecteur intelligent de profil de seuils selon le contexte.

    Analyse le contexte (domaine, langue, source, type entité) et retourne
    le profil de seuils le plus approprié.
    """

    def __init__(self):
        """Initialise le sélecteur avec les profils prédéfinis."""
        self.profiles = THRESHOLD_PROFILES

    def select_profile(
        self,
        domain: Optional[DomainContext] = None,
        language: Optional[LanguageContext] = None,
        source: Optional[SourceContext] = None,
        entity_type: Optional[EntityTypeContext] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ThresholdProfile:
        """
        Sélectionne le profil de seuils le plus adapté au contexte.

        Algorithme de sélection (par ordre de priorité):
        1. Produits SAP catalogués → SAP_PRODUCTS_CATALOG
        2. Documentation officielle SAP → SAP_OFFICIAL_DOCS
        3. Contenu communautaire → COMMUNITY_CONTENT
        4. Multilingue/jargon → MULTILINGUAL_TECHNICAL
        5. Documentation interne → INTERNAL_DOCS
        6. Fallback → DEFAULT

        Args:
            domain: Contexte domaine technique
            language: Contexte linguistique
            source: Source du document
            entity_type: Type d'entité à canonicaliser
            metadata: Métadonnées additionnelles

        Returns:
            ThresholdProfile sélectionné
        """
        metadata = metadata or {}

        # Priorité 1: Produits SAP catalogués (très strict)
        if domain == DomainContext.SAP_ECOSYSTEM and entity_type == EntityTypeContext.PRODUCT:
            logger.debug(
                "[AdaptiveThresholds] Selected profile: SAP_PRODUCTS_CATALOG "
                "(domain=SAP + entity_type=PRODUCT)"
            )
            return self.profiles["SAP_PRODUCTS_CATALOG"]

        # Priorité 2: Documentation officielle SAP (haute confiance)
        if domain == DomainContext.SAP_ECOSYSTEM and source == SourceContext.OFFICIAL_DOCUMENTATION:
            logger.debug(
                "[AdaptiveThresholds] Selected profile: SAP_OFFICIAL_DOCS "
                "(domain=SAP + source=OFFICIAL_DOCS)"
            )
            return self.profiles["SAP_OFFICIAL_DOCS"]

        # Priorité 3: Contenu communautaire (confiance basse)
        if source in [SourceContext.FORUM_COMMUNITY, SourceContext.PRESENTATION_SLIDES, SourceContext.EMAILS_CHAT]:
            logger.debug(
                f"[AdaptiveThresholds] Selected profile: COMMUNITY_CONTENT (source={source})"
            )
            return self.profiles["COMMUNITY_CONTENT"]

        # Priorité 4: Multilingue ou jargon technique (tolérance accrue)
        if language in [LanguageContext.MULTILINGUAL, LanguageContext.TECHNICAL_JARGON]:
            logger.debug(
                f"[AdaptiveThresholds] Selected profile: MULTILINGUAL_TECHNICAL (language={language})"
            )
            return self.profiles["MULTILINGUAL_TECHNICAL"]

        # Priorité 5: Documentation interne (confiance moyenne)
        if source == SourceContext.INTERNAL_DOCUMENTATION:
            logger.debug(
                "[AdaptiveThresholds] Selected profile: INTERNAL_DOCS (source=INTERNAL_DOCS)"
            )
            return self.profiles["INTERNAL_DOCS"]

        # Fallback: Profil par défaut
        logger.debug(
            "[AdaptiveThresholds] Selected profile: DEFAULT (no specific context matched)"
        )
        return self.profiles["DEFAULT"]

    def get_threshold(
        self,
        threshold_type: str,
        domain: Optional[DomainContext] = None,
        language: Optional[LanguageContext] = None,
        source: Optional[SourceContext] = None,
        entity_type: Optional[EntityTypeContext] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> float:
        """
        Récupère un seuil spécifique pour un contexte donné.

        Args:
            threshold_type: Type de seuil (fuzzy_match, auto_validation, promotion)
            domain: Contexte domaine
            language: Contexte langue
            source: Contexte source
            entity_type: Type entité
            metadata: Métadonnées

        Returns:
            Valeur du seuil (0-1)
        """
        profile = self.select_profile(
            domain=domain,
            language=language,
            source=source,
            entity_type=entity_type,
            metadata=metadata
        )

        threshold_value = getattr(profile, f"{threshold_type}_threshold", None)

        if threshold_value is None:
            logger.warning(
                f"[AdaptiveThresholds] Unknown threshold type '{threshold_type}', "
                f"using default 0.85"
            )
            return 0.85

        logger.debug(
            f"[AdaptiveThresholds] Threshold '{threshold_type}' = {threshold_value:.2f} "
            f"(profile={profile.name})"
        )

        return threshold_value


# ============================================================================
# Singleton Instance
# ============================================================================

_selector_instance: Optional[AdaptiveThresholdSelector] = None


def get_adaptive_threshold_selector() -> AdaptiveThresholdSelector:
    """
    Retourne instance singleton du sélecteur de seuils adaptatifs.

    Returns:
        AdaptiveThresholdSelector instance
    """
    global _selector_instance

    if _selector_instance is None:
        _selector_instance = AdaptiveThresholdSelector()

    return _selector_instance


__all__ = [
    "DomainContext",
    "LanguageContext",
    "SourceContext",
    "EntityTypeContext",
    "ThresholdProfile",
    "THRESHOLD_PROFILES",
    "AdaptiveThresholdSelector",
    "get_adaptive_threshold_selector"
]
