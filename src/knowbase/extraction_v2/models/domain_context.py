"""
VisionDomainContext pour Extraction V2.

Adaptateur: DomainContextStore → VisionDomainContext.
Une seule source de vérité: le DomainContextStore existant.

Spécification: OSMOSIS_EXTRACTION_V2_DECISIONS.md - Décision 2

Règles:
- DomainContextStore reste la source unique
- Vision CONSOMME le contexte, ne le DÉFINIT pas
- Pas de YAML spécifique Vision
- Pas de logique métier en dur dans les prompts Vision
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class VisionDomainContext:
    """
    Contexte métier pour guider l'interprétation Vision.

    Ne crée JAMAIS d'information, réduit l'espace des interprétations.

    Le Domain Context est utilisé UNIQUEMENT pour:
    - Désambiguïser des termes déjà visibles dans l'image
    - Réduire l'ambiguïté d'interprétation

    Il NE DOIT PAS:
    - Introduire des concepts absents de l'image
    - Appliquer des best practices du domaine
    - Résoudre des ambiguïtés non supportées visuellement

    Attributs:
        name: Nom du domaine (ex: "SAP", "Pharmaceutical", "Retail")
        interpretation_rules: Règles d'interprétation spécifiques
        vocabulary: Dictionnaire acronymes → expansions
        key_concepts: Concepts clés à reconnaître prioritairement
        business_context: Description courte du contexte métier
        extraction_focus: Focus spécifique pour l'extraction
    """
    name: str  # e.g., "SAP", "Regulatory", "LifeScience"

    # Règles d'interprétation
    interpretation_rules: List[str] = field(default_factory=list)

    # Vocabulaire du domaine (acronymes → expansions)
    vocabulary: Dict[str, str] = field(default_factory=dict)

    # Concepts clés à reconnaître
    key_concepts: List[str] = field(default_factory=list)

    # Contexte métier court
    business_context: str = ""

    # Focus spécifique pour l'extraction
    extraction_focus: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Sérialise en dictionnaire."""
        return {
            "name": self.name,
            "interpretation_rules": self.interpretation_rules,
            "vocabulary": self.vocabulary,
            "key_concepts": self.key_concepts,
            "business_context": self.business_context,
            "extraction_focus": self.extraction_focus,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VisionDomainContext":
        """Désérialise depuis un dictionnaire."""
        return cls(
            name=data.get("name", "default"),
            interpretation_rules=data.get("interpretation_rules", []),
            vocabulary=data.get("vocabulary", {}),
            key_concepts=data.get("key_concepts", []),
            business_context=data.get("business_context", ""),
            extraction_focus=data.get("extraction_focus", ""),
        )

    def to_prompt_section(self) -> str:
        """
        Génère la section Domain Context pour le prompt Vision.

        Format conforme au VISION_PROMPT_CANONICAL.md.
        """
        lines = [
            f"**Domain:** {self.name}",
            "",
        ]

        if self.interpretation_rules:
            lines.append("**Interpretation Rules:**")
            for rule in self.interpretation_rules:
                lines.append(f"- {rule}")
            lines.append("")

        if self.vocabulary:
            lines.append("**Domain Vocabulary:**")
            for acronym, expansion in self.vocabulary.items():
                lines.append(f"- {acronym}: {expansion}")
            lines.append("")

        if self.key_concepts:
            lines.append("**Key Concepts:**")
            lines.append(", ".join(self.key_concepts))
            lines.append("")

        if self.business_context:
            lines.append("**Business Context:**")
            lines.append(self.business_context)
            lines.append("")

        if self.extraction_focus:
            lines.append("**Extraction Focus:**")
            lines.append(self.extraction_focus)

        return "\n".join(lines)

    @classmethod
    def default(cls) -> "VisionDomainContext":
        """
        Retourne un contexte par défaut (neutre).

        Utilisé quand aucun contexte spécifique n'est configuré.
        """
        return cls(
            name="generic",
            interpretation_rules=[
                "Interpret terms literally as shown in the image",
                "Do not assume domain-specific meanings",
                "Declare ambiguity when multiple interpretations are possible",
            ],
            vocabulary={},
            key_concepts=[],
            business_context="General business document",
            extraction_focus="Extract all visible structural elements and relationships",
        )

    def __repr__(self) -> str:
        return (
            f"VisionDomainContext(name={self.name!r}, "
            f"{len(self.interpretation_rules)} rules, "
            f"{len(self.vocabulary)} vocab, "
            f"{len(self.key_concepts)} concepts)"
        )


def get_vision_domain_context(tenant_id: str) -> VisionDomainContext:
    """
    Adaptateur: DomainContextStore → VisionDomainContext.

    Récupère le profil depuis le store existant et le convertit
    en VisionDomainContext pour usage dans le pipeline Vision.

    Args:
        tenant_id: Identifiant du tenant

    Returns:
        VisionDomainContext adapté depuis le DomainContextProfile,
        ou contexte par défaut si le profil n'existe pas.

    Spécification: OSMOSIS_EXTRACTION_V2_DECISIONS.md - Décision 2

    Example:
        >>> context = get_vision_domain_context("default")
        >>> prompt_section = context.to_prompt_section()
    """
    try:
        from knowbase.ontology.domain_context_store import get_domain_context_store

        store = get_domain_context_store()
        profile = store.get_profile(tenant_id)

        if profile is None:
            logger.debug(
                f"[VisionDomainContext] No profile for tenant '{tenant_id}', using default"
            )
            return VisionDomainContext.default()

        # Construction des règles d'interprétation
        interpretation_rules = []

        # Règle basée sur l'industrie
        if profile.industry:
            interpretation_rules.append(
                f"Interpret acronyms strictly in {profile.industry} context"
            )

        # Règles par défaut Vision
        interpretation_rules.extend([
            "Prefer explicit visual relations over inferred ones",
            "If ambiguous, declare ambiguity rather than guess",
            "Only extract what is visually explicit",
        ])

        # Focus d'extraction basé sur le domaine
        extraction_focus = ""
        if profile.key_concepts:
            concepts_str = ", ".join(profile.key_concepts[:10])  # Limite à 10
            extraction_focus = (
                f"Identify which concepts from [{concepts_str}] are associated "
                f"with elements in the diagram, ONLY if explicitly visible."
            )

        vision_context = VisionDomainContext(
            name=profile.industry or "default",
            interpretation_rules=interpretation_rules,
            vocabulary=profile.common_acronyms or {},
            key_concepts=profile.key_concepts[:20] if profile.key_concepts else [],
            business_context=profile.domain_summary or "",
            extraction_focus=extraction_focus,
        )

        logger.debug(
            f"[VisionDomainContext] ✅ Adapted from profile: "
            f"tenant='{tenant_id}', industry='{profile.industry}'"
        )

        return vision_context

    except ImportError as e:
        logger.warning(
            f"[VisionDomainContext] Cannot import DomainContextStore: {e}, using default"
        )
        return VisionDomainContext.default()

    except Exception as e:
        logger.error(
            f"[VisionDomainContext] Error adapting context for '{tenant_id}': {e}"
        )
        return VisionDomainContext.default()


# === Contextes prédéfinis pour tests et exemples ===

SAP_VISION_CONTEXT = VisionDomainContext(
    name="SAP",
    interpretation_rules=[
        "Interpret acronyms strictly in SAP context",
        "Disambiguate 'Cloud' variants (S/4HANA PCE, GROW, BTP)",
        "Prefer explicit visual relations over inferred ones",
        "If ambiguous, declare ambiguity",
    ],
    vocabulary={
        "ERP": "S/4HANA, RISE, GROW",
        "Platform": "BTP, CPI, SAC",
        "HCM": "SuccessFactors",
        "Spend": "Ariba, Concur, Fieldglass",
        "SAC": "SAP Analytics Cloud",
        "BTP": "Business Technology Platform",
        "CPI": "Cloud Platform Integration",
    },
    key_concepts=[
        "SAP S/4HANA",
        "SuccessFactors",
        "SAP Analytics Cloud",
        "Business Technology Platform",
        "Ariba",
        "Concur",
        "RISE with SAP",
        "GROW with SAP",
    ],
    business_context="SAP enterprise software ecosystem",
    extraction_focus=(
        "Identify which SAP solution is associated with each concept "
        "ONLY if explicitly visible in the image."
    ),
)


__all__ = [
    "VisionDomainContext",
    "get_vision_domain_context",
    "SAP_VISION_CONTEXT",
]
