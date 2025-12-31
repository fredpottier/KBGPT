"""
Hybrid Anchor Model - Heuristic Classifier (Pass 1)

Classification heuristique rapide sans appel LLM pour Pass 1.
Basée sur patterns textuels, structure document, verbes normatifs.

Types assignés:
- structural: Articles, sections, clauses (regex patterns)
- regulatory: Langage normatif (shall, must, required)
- procedural: Processus, méthodes, procédures
- abstract: Concepts généraux sans pattern spécifique

ADR: doc/ongoing/ADR_HYBRID_ANCHOR_MODEL.md

Author: OSMOSE Phase 2
Date: 2024-12
"""

import re
import logging
from enum import Enum
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from knowbase.config.feature_flags import get_hybrid_anchor_config

logger = logging.getLogger(__name__)


class ConceptTypeHeuristic(str, Enum):
    """
    Types heuristiques assignés en Pass 1.

    Ces types sont provisoires et peuvent être affinés en Pass 2.
    """
    STRUCTURAL = "structural"    # Articles, sections, clauses
    REGULATORY = "regulatory"    # Obligations, interdictions, contraintes
    PROCEDURAL = "procedural"    # Processus, méthodes, procédures
    ABSTRACT = "abstract"        # Concepts généraux (défaut)


@dataclass
class HeuristicResult:
    """Résultat de classification heuristique."""

    concept_type: ConceptTypeHeuristic
    confidence: float
    matched_pattern: Optional[str] = None
    matched_tokens: List[str] = None

    def __post_init__(self):
        if self.matched_tokens is None:
            self.matched_tokens = []


# =============================================================================
# Patterns de Classification
# =============================================================================

# Patterns structurels (articles, sections, etc.)
STRUCTURAL_PATTERNS = [
    # EN patterns
    r"^article\s+\d+",
    r"^section\s+\d+(\.\d+)*",
    r"^chapter\s+\d+",
    r"^annex\s+[a-z0-9]+",
    r"^appendix\s+[a-z0-9]+",
    r"^clause\s+\d+(\.\d+)*",
    r"^part\s+\d+",
    r"^schedule\s+\d+",
    r"^\d+(\.\d+)+\s",  # Numbered sections like "4.2.1 ..."
    # FR patterns
    r"^article\s+\d+",
    r"^section\s+\d+(\.\d+)*",
    r"^chapitre\s+\d+",
    r"^annexe\s+[a-z0-9]+",
    r"^paragraphe\s+\d+",
    r"^alinéa\s+\d+",
    # General
    r"^table\s+\d+",
    r"^figure\s+\d+",
    r"^tableau\s+\d+",
]

# Verbes normatifs indiquant regulatory content
NORMATIVE_MODALS = {
    # EN obligatory
    "shall", "must", "required", "mandatory", "obligatory",
    "shall not", "must not", "prohibited", "forbidden",
    # EN conditional
    "should", "recommended", "may", "optional",
    # FR obligatory
    "doit", "doivent", "obligatoire", "requis", "exigé",
    "interdit", "ne doit pas", "ne doivent pas",
    # FR conditional
    "devrait", "recommandé", "peut", "peuvent", "facultatif",
}

# Patterns procéduraux
PROCEDURAL_PATTERNS = [
    r"\bprocess\b",
    r"\bprocedure\b",
    r"\bmethod\b",
    r"\bworkflow\b",
    r"\bstep\b",
    r"\bphase\b",
    r"\bstage\b",
    r"\bpipeline\b",
    # FR
    r"\bprocessus\b",
    r"\bprocédure\b",
    r"\bméthode\b",
    r"\bétape\b",
    r"\bflux\b",
]

# Patterns d'action (verbes à l'infinitif ou gérondif)
ACTION_PATTERNS = [
    r"^(to|how to)\s+\w+",  # "To implement...", "How to configure..."
    r"^(implement|configure|setup|install|deploy|create|build|develop)\b",
    r"^(implementing|configuring|setting up|installing|deploying|creating)\b",
    # FR
    r"^(implémenter|configurer|installer|déployer|créer|développer)\b",
]


class HeuristicClassifier:
    """
    Classificateur heuristique pour Pass 1 du Hybrid Anchor Model.

    Assigne un type préliminaire basé sur:
    1. Patterns structurels (regex)
    2. Verbes normatifs (modal detection)
    3. Patterns procéduraux
    4. Patterns d'action

    Pas d'appel LLM = rapide et déterministe.
    """

    def __init__(self, tenant_id: str = "default"):
        """
        Initialise le classificateur.

        Args:
            tenant_id: ID tenant pour configuration
        """
        self.tenant_id = tenant_id

        # Compiler patterns pour performance
        self._structural_patterns = [
            re.compile(p, re.IGNORECASE) for p in STRUCTURAL_PATTERNS
        ]
        self._procedural_patterns = [
            re.compile(p, re.IGNORECASE) for p in PROCEDURAL_PATTERNS
        ]
        self._action_patterns = [
            re.compile(p, re.IGNORECASE) for p in ACTION_PATTERNS
        ]

        # Charger configuration
        classification_config = get_hybrid_anchor_config(
            "classification_config", tenant_id
        ) or {}
        self._custom_patterns = classification_config.get("custom_patterns", {})

        logger.info(
            f"[OSMOSE:HeuristicClassifier] Initialized "
            f"(structural={len(STRUCTURAL_PATTERNS)} patterns, "
            f"procedural={len(PROCEDURAL_PATTERNS)} patterns)"
        )

    def classify(
        self,
        label: str,
        context: str = "",
        quote: str = ""
    ) -> HeuristicResult:
        """
        Classifie un concept de manière heuristique.

        Args:
            label: Label du concept
            context: Contexte optionnel (définition, description)
            quote: Quote de l'anchor (texte source)

        Returns:
            HeuristicResult avec type et confiance
        """
        # Combiner textes pour analyse
        full_text = f"{label} {context} {quote}".lower()
        label_lower = label.lower().strip()

        # 1. Check structural patterns (haute priorité)
        structural_result = self._check_structural(label_lower)
        if structural_result:
            return structural_result

        # 2. Check regulatory (modaux normatifs)
        regulatory_result = self._check_regulatory(full_text, quote.lower())
        if regulatory_result:
            return regulatory_result

        # 3. Check procedural patterns
        procedural_result = self._check_procedural(full_text, label_lower)
        if procedural_result:
            return procedural_result

        # 4. Default: abstract
        return HeuristicResult(
            concept_type=ConceptTypeHeuristic.ABSTRACT,
            confidence=0.5,
            matched_pattern=None,
            matched_tokens=[]
        )

    def _check_structural(self, label: str) -> Optional[HeuristicResult]:
        """Check structural patterns on label."""
        for pattern in self._structural_patterns:
            if pattern.match(label):
                return HeuristicResult(
                    concept_type=ConceptTypeHeuristic.STRUCTURAL,
                    confidence=0.95,
                    matched_pattern=pattern.pattern,
                    matched_tokens=[]
                )
        return None

    def _check_regulatory(
        self,
        full_text: str,
        quote: str
    ) -> Optional[HeuristicResult]:
        """
        Check for normative modals indicating regulatory content.

        Priorité à la quote car c'est le texte source.
        """
        matched_tokens = []

        # Chercher modaux dans la quote (haute confiance)
        for modal in NORMATIVE_MODALS:
            if f" {modal} " in f" {quote} " or quote.startswith(f"{modal} "):
                matched_tokens.append(modal)

        if matched_tokens:
            return HeuristicResult(
                concept_type=ConceptTypeHeuristic.REGULATORY,
                confidence=0.90,
                matched_pattern="normative_modal",
                matched_tokens=matched_tokens
            )

        # Chercher dans le texte complet (confiance moyenne)
        for modal in NORMATIVE_MODALS:
            if f" {modal} " in f" {full_text} ":
                matched_tokens.append(modal)

        if len(matched_tokens) >= 1:
            return HeuristicResult(
                concept_type=ConceptTypeHeuristic.REGULATORY,
                confidence=0.70,
                matched_pattern="normative_modal_context",
                matched_tokens=matched_tokens[:3]  # Top 3
            )

        return None

    def _check_procedural(
        self,
        full_text: str,
        label: str
    ) -> Optional[HeuristicResult]:
        """Check procedural patterns."""
        matched_patterns = []

        # Check label first
        for pattern in self._procedural_patterns:
            if pattern.search(label):
                matched_patterns.append(pattern.pattern)

        if matched_patterns:
            return HeuristicResult(
                concept_type=ConceptTypeHeuristic.PROCEDURAL,
                confidence=0.85,
                matched_pattern=matched_patterns[0],
                matched_tokens=[]
            )

        # Check action patterns
        for pattern in self._action_patterns:
            if pattern.match(label):
                return HeuristicResult(
                    concept_type=ConceptTypeHeuristic.PROCEDURAL,
                    confidence=0.80,
                    matched_pattern=pattern.pattern,
                    matched_tokens=[]
                )

        # Check full text (lower confidence)
        for pattern in self._procedural_patterns:
            if pattern.search(full_text):
                matched_patterns.append(pattern.pattern)

        if len(matched_patterns) >= 2:
            return HeuristicResult(
                concept_type=ConceptTypeHeuristic.PROCEDURAL,
                confidence=0.65,
                matched_pattern="multiple_procedural_context",
                matched_tokens=[]
            )

        return None

    def classify_batch(
        self,
        concepts: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Classifie un batch de concepts.

        Args:
            concepts: Liste de dicts avec 'label', 'context', 'quote'

        Returns:
            Liste de concepts enrichis avec 'type_heuristic', 'type_confidence'
        """
        results = []

        for concept in concepts:
            result = self.classify(
                label=concept.get("label", ""),
                context=concept.get("context", "") or concept.get("definition", ""),
                quote=concept.get("quote", "")
            )

            enriched = {
                **concept,
                "type_heuristic": result.concept_type.value,
                "type_confidence": result.confidence,
                "type_matched_pattern": result.matched_pattern,
            }
            results.append(enriched)

        # Stats
        type_counts = {}
        for r in results:
            t = r["type_heuristic"]
            type_counts[t] = type_counts.get(t, 0) + 1

        logger.info(
            f"[OSMOSE:HeuristicClassifier] Batch classified: {len(results)} concepts, "
            f"types: {type_counts}"
        )

        return results


# =============================================================================
# Factory & Convenience Functions
# =============================================================================

_classifier_instance: Optional[HeuristicClassifier] = None


def get_heuristic_classifier(tenant_id: str = "default") -> HeuristicClassifier:
    """
    Récupère l'instance singleton du classificateur.

    Args:
        tenant_id: ID tenant

    Returns:
        HeuristicClassifier instance
    """
    global _classifier_instance

    if _classifier_instance is None:
        _classifier_instance = HeuristicClassifier(tenant_id=tenant_id)

    return _classifier_instance


def classify_heuristic(
    label: str,
    context: str = "",
    quote: str = "",
    tenant_id: str = "default"
) -> HeuristicResult:
    """
    Fonction de convenance pour classification heuristique.

    Args:
        label: Label du concept
        context: Contexte optionnel
        quote: Quote de l'anchor
        tenant_id: ID tenant

    Returns:
        HeuristicResult
    """
    classifier = get_heuristic_classifier(tenant_id)
    return classifier.classify(label, context, quote)
