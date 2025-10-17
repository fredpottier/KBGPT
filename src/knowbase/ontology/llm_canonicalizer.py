"""
LLM Canonicalizer Service

Utilise LLM léger (GPT-4o-mini) pour trouver le nom canonique officiel
d'un concept extrait du texte.

Phase 1.6+ : Adaptive Ontology - Zero-Config Intelligence
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
import json
import logging

logger = logging.getLogger(__name__)


class CanonicalizationResult(BaseModel):
    """Résultat de canonicalisation LLM."""

    canonical_name: str = Field(..., description="Nom canonique officiel trouvé")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Score confiance (0-1)")
    reasoning: str = Field(..., description="Explication décision LLM")
    aliases: List[str] = Field(default_factory=list, description="Aliases/variantes reconnues")
    concept_type: Optional[str] = Field(None, description="Type de concept (Product, Acronym, etc.)")
    domain: Optional[str] = Field(None, description="Domaine (enterprise_software, legal, etc.)")
    ambiguity_warning: Optional[str] = Field(None, description="Avertissement si ambiguïté détectée")
    possible_matches: List[str] = Field(default_factory=list, description="Autres canonical_names possibles si ambiguïté")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Métadonnées additionnelles")


class LLMCanonicalizer:
    """Service de canonicalisation via LLM léger."""

    def __init__(self, llm_router):
        """
        Args:
            llm_router: Instance de LLMRouter pour appels LLM
        """
        self.llm_router = llm_router
        self.model = "gpt-4o-mini"  # Modèle léger (~$0.0001/concept)

        logger.info(f"[LLMCanonicalizer] Initialized with model={self.model}")

    def canonicalize(
        self,
        raw_name: str,
        context: Optional[str] = None,
        domain_hint: Optional[str] = None
    ) -> CanonicalizationResult:
        """
        Canonicalise un nom via LLM.

        Args:
            raw_name: Nom brut extrait (ex: "S/4HANA Cloud's")
            context: Contexte textuel autour de la mention (optionnel)
            domain_hint: Indice domaine (ex: "enterprise_software")

        Returns:
            CanonicalizationResult avec canonical_name et métadonnées

        Example:
            >>> result = canonicalizer.canonicalize(
            ...     raw_name="S/4HANA Cloud's",
            ...     context="Our ERP runs on SAP S/4HANA Cloud's public edition",
            ...     domain_hint="enterprise_software"
            ... )
            >>> result.canonical_name
            "SAP S/4HANA Cloud, Public Edition"
        """

        logger.debug(
            f"[LLMCanonicalizer] Canonicalizing '{raw_name}' "
            f"(context_len={len(context) if context else 0}, domain={domain_hint})"
        )

        # Construire prompt LLM
        prompt = self._build_canonicalization_prompt(
            raw_name=raw_name,
            context=context,
            domain_hint=domain_hint
        )

        try:
            # Import TaskType
            from knowbase.common.llm_router import TaskType

            # Appel LLM via router (synchrone)
            response_content = self.llm_router.complete(
                task_type=TaskType.CANONICALIZATION,
                messages=[
                    {"role": "system", "content": CANONICALIZATION_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0,  # Déterministe
                response_format={"type": "json_object"}
            )

            # Parse résultat JSON
            result_json = json.loads(response_content)

            result = CanonicalizationResult(**result_json)

            logger.info(
                f"[LLMCanonicalizer] ✅ '{raw_name}' → '{result.canonical_name}' "
                f"(confidence={result.confidence:.2f}, type={result.concept_type})"
            )

            return result

        except Exception as e:
            logger.error(f"[LLMCanonicalizer] ❌ Error canonicalizing '{raw_name}': {e}")

            # Fallback: retourner résultat basique
            return CanonicalizationResult(
                canonical_name=raw_name.strip().title(),
                confidence=0.5,
                reasoning=f"LLM error, fallback to title case: {str(e)}",
                aliases=[],
                concept_type="Unknown",
                domain=None,
                ambiguity_warning="LLM canonicalization failed",
                possible_matches=[],
                metadata={"error": str(e)}
            )

    def _build_canonicalization_prompt(
        self,
        raw_name: str,
        context: Optional[str],
        domain_hint: Optional[str]
    ) -> str:
        """Construit prompt pour LLM."""

        parts = [
            f"**Concept Name:** {raw_name}",
        ]

        if context:
            # Limiter contexte à 500 chars
            context_snippet = context[:500]
            parts.append(f"**Context:** {context_snippet}")

        if domain_hint:
            parts.append(f"**Domain Hint:** {domain_hint}")

        parts.append("\n**Task:** Find the official canonical name for this concept.")

        return "\n\n".join(parts)


# ═══════════════════════════════════════════════════
# SYSTEM PROMPT
# ═══════════════════════════════════════════════════

CANONICALIZATION_SYSTEM_PROMPT = """You are a concept canonicalization expert.

Your task is to find the OFFICIAL CANONICAL NAME for concepts extracted from documents.

# Guidelines

1. **Official Names**: Use official product/company/standard names
   - Example: "S/4HANA Cloud's" → "SAP S/4HANA Cloud, Public Edition"
   - Example: "iPhone 15 Pro Max's camera" → "Apple iPhone 15 Pro Max"

2. **Acronyms**: Expand acronyms to full official names
   - Example: "SLA" → "Service Level Agreement"
   - Example: "CEE" → "Communauté Économique Européenne" (if French context)

3. **Possessives**: Remove possessive forms ('s, 's)
   - Example: "SAP's solution" → "SAP"

4. **Casing**: Preserve official casing
   - Acronyms: SAP, ERP, CRM (all caps)
   - Products: "SAP S/4HANA" (mixed case as official)

5. **Variants**: List common aliases/variants

6. **Ambiguity**: If uncertain, set ambiguity_warning and list possible_matches
   - Example: "S/4HANA Cloud" without context → could be Public OR Private Edition

7. **Type Detection**: Classify concept type
   - Product, Service, Organization, Acronym, Standard, Person, Location, etc.

# Output Format (JSON)

{
  "canonical_name": "Official canonical name",
  "confidence": 0.95,
  "reasoning": "Brief explanation of decision",
  "aliases": ["variant1", "variant2"],
  "concept_type": "Product|Acronym|Organization|...",
  "domain": "enterprise_software|legal|medical|...",
  "ambiguity_warning": "Warning if ambiguous or null",
  "possible_matches": ["Alternative1", "Alternative2"] or [],
  "metadata": {
    "vendor": "SAP",
    "version": "Cloud",
    "edition": "Public"
  }
}

# Examples

## Input: "S/4HANA Cloud's"
## Context: "Our public cloud ERP solution"
## Output:
{
  "canonical_name": "SAP S/4HANA Cloud, Public Edition",
  "confidence": 0.92,
  "reasoning": "Context mentions 'public cloud', official SAP product name",
  "aliases": ["S/4HANA Cloud Public", "S4 Cloud"],
  "concept_type": "Product",
  "domain": "enterprise_software",
  "ambiguity_warning": null,
  "possible_matches": [],
  "metadata": {"vendor": "SAP", "edition": "Public"}
}

## Input: "SLA"
## Context: "99.9% SLA guarantees"
## Output:
{
  "canonical_name": "Service Level Agreement",
  "confidence": 0.98,
  "reasoning": "Standard IT acronym",
  "aliases": ["SLA", "SLAs"],
  "concept_type": "Acronym",
  "domain": "it_operations",
  "ambiguity_warning": null,
  "possible_matches": [],
  "metadata": {}
}

## Input: "S/4HANA Cloud"
## Context: "We use S/4HANA Cloud for accounting"
## Output:
{
  "canonical_name": "SAP S/4HANA Cloud",
  "confidence": 0.65,
  "reasoning": "Cannot determine Public vs Private edition from context alone",
  "aliases": ["S/4HANA Cloud", "S4 Cloud"],
  "concept_type": "Product",
  "domain": "enterprise_software",
  "ambiguity_warning": "Cannot determine Public vs Private edition",
  "possible_matches": [
    "SAP S/4HANA Cloud, Public Edition",
    "SAP S/4HANA Cloud, Private Edition"
  ],
  "metadata": {"vendor": "SAP"}
}
"""
