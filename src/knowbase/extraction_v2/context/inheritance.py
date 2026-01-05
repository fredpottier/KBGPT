"""
Matrice d'heritage DocContext -> AnchorContext.

Implemente les regles de propagation du contexte documentaire
vers les assertions (anchors) selon l'ADR Section 3.4.

Regles principales:
- DocScope=VARIANT_SPECIFIC + strong_markers -> inherit avec INHERITED_STRONG
- DocScope=VARIANT_SPECIFIC + weak_markers -> inherit avec INHERITED_WEAK
- DocScope=MIXED -> PAS d'heritage (trop risque)
- DocScope=GENERAL -> scope=GENERAL (pas de markers herites)
- Override local detecte -> toujours prioritaire

Spec: doc/ongoing/ADR_ASSERTION_AWARE_KG.md - Section 3.4
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Tuple
import logging

from knowbase.extraction_v2.context.models import (
    DocScope,
    DocContextFrame,
)
from knowbase.extraction_v2.context.anchor_models import (
    Polarity,
    AssertionScope,
    QualifierSource,
    LocalMarker,
    AnchorContext,
)

logger = logging.getLogger(__name__)


@dataclass
class InheritanceRule:
    """
    Regle d'heritage documentaire.

    Definit comment le contexte document se propage a l'anchor.
    """
    doc_scope: DocScope
    has_strong_markers: bool
    has_weak_markers: bool
    result_scope: AssertionScope
    result_source: QualifierSource
    inherit_markers: bool
    confidence_factor: float  # Facteur multiplicatif sur la confiance
    description: str


# === MATRICE D'HERITAGE ===
# Definie selon ADR Section 3.4

INHERITANCE_RULES: List[InheritanceRule] = [
    # VARIANT_SPECIFIC avec strong markers -> heritage fort
    InheritanceRule(
        doc_scope=DocScope.VARIANT_SPECIFIC,
        has_strong_markers=True,
        has_weak_markers=False,
        result_scope=AssertionScope.CONSTRAINED,
        result_source=QualifierSource.INHERITED_STRONG,
        inherit_markers=True,
        confidence_factor=0.95,
        description="VARIANT_SPECIFIC + strong -> CONSTRAINED (inherited_strong)",
    ),
    # VARIANT_SPECIFIC avec strong + weak markers -> heritage fort (strong prioritaire)
    InheritanceRule(
        doc_scope=DocScope.VARIANT_SPECIFIC,
        has_strong_markers=True,
        has_weak_markers=True,
        result_scope=AssertionScope.CONSTRAINED,
        result_source=QualifierSource.INHERITED_STRONG,
        inherit_markers=True,
        confidence_factor=0.90,
        description="VARIANT_SPECIFIC + strong + weak -> CONSTRAINED (inherited_strong)",
    ),
    # VARIANT_SPECIFIC avec uniquement weak markers -> heritage faible
    InheritanceRule(
        doc_scope=DocScope.VARIANT_SPECIFIC,
        has_strong_markers=False,
        has_weak_markers=True,
        result_scope=AssertionScope.CONSTRAINED,
        result_source=QualifierSource.INHERITED_WEAK,
        inherit_markers=True,
        confidence_factor=0.85,
        description="VARIANT_SPECIFIC + weak only -> CONSTRAINED (inherited_weak)",
    ),
    # VARIANT_SPECIFIC sans markers -> scope UNKNOWN (cas anormal)
    InheritanceRule(
        doc_scope=DocScope.VARIANT_SPECIFIC,
        has_strong_markers=False,
        has_weak_markers=False,
        result_scope=AssertionScope.UNKNOWN,
        result_source=QualifierSource.NONE,
        inherit_markers=False,
        confidence_factor=0.7,
        description="VARIANT_SPECIFIC sans markers -> UNKNOWN",
    ),
    # MIXED -> PAS d'heritage (trop de risque d'erreur)
    InheritanceRule(
        doc_scope=DocScope.MIXED,
        has_strong_markers=True,
        has_weak_markers=False,
        result_scope=AssertionScope.UNKNOWN,
        result_source=QualifierSource.NONE,
        inherit_markers=False,
        confidence_factor=0.5,
        description="MIXED -> UNKNOWN (pas d'heritage)",
    ),
    InheritanceRule(
        doc_scope=DocScope.MIXED,
        has_strong_markers=False,
        has_weak_markers=True,
        result_scope=AssertionScope.UNKNOWN,
        result_source=QualifierSource.NONE,
        inherit_markers=False,
        confidence_factor=0.5,
        description="MIXED -> UNKNOWN (pas d'heritage)",
    ),
    InheritanceRule(
        doc_scope=DocScope.MIXED,
        has_strong_markers=True,
        has_weak_markers=True,
        result_scope=AssertionScope.UNKNOWN,
        result_source=QualifierSource.NONE,
        inherit_markers=False,
        confidence_factor=0.5,
        description="MIXED -> UNKNOWN (pas d'heritage)",
    ),
    InheritanceRule(
        doc_scope=DocScope.MIXED,
        has_strong_markers=False,
        has_weak_markers=False,
        result_scope=AssertionScope.UNKNOWN,
        result_source=QualifierSource.NONE,
        inherit_markers=False,
        confidence_factor=0.5,
        description="MIXED -> UNKNOWN (pas d'heritage)",
    ),
    # GENERAL -> scope GENERAL (aucun marker a heriter)
    InheritanceRule(
        doc_scope=DocScope.GENERAL,
        has_strong_markers=False,
        has_weak_markers=False,
        result_scope=AssertionScope.GENERAL,
        result_source=QualifierSource.NONE,
        inherit_markers=False,
        confidence_factor=0.8,
        description="GENERAL -> scope GENERAL",
    ),
]


def _find_rule(
    doc_scope: DocScope,
    has_strong: bool,
    has_weak: bool,
) -> Optional[InheritanceRule]:
    """
    Trouve la regle d'heritage applicable.

    Args:
        doc_scope: Scope du document
        has_strong: True si le document a des strong markers
        has_weak: True si le document a des weak markers

    Returns:
        InheritanceRule ou None
    """
    for rule in INHERITANCE_RULES:
        if (
            rule.doc_scope == doc_scope
            and rule.has_strong_markers == has_strong
            and rule.has_weak_markers == has_weak
        ):
            return rule
    return None


class InheritanceEngine:
    """
    Moteur d'heritage DocContext -> AnchorContext.

    Applique la matrice d'heritage pour determiner le scope
    et les markers herites d'un anchor.

    Usage:
        >>> engine = InheritanceEngine()
        >>> scope, source, markers, confidence = engine.apply_inheritance(
        ...     doc_context=doc_frame,
        ...     local_markers=[],
        ...     is_override=False,
        ... )
    """

    def __init__(self):
        """Initialise le moteur."""
        self._rules = INHERITANCE_RULES

    def apply_inheritance(
        self,
        doc_context: Optional[DocContextFrame],
        local_markers: List[LocalMarker],
        is_override: bool,
    ) -> Tuple[AssertionScope, QualifierSource, List[str], float]:
        """
        Applique la matrice d'heritage.

        Args:
            doc_context: Contexte documentaire (peut etre None)
            local_markers: Marqueurs detectes localement dans le passage
            is_override: True si un pattern d'override a ete detecte

        Returns:
            Tuple (scope, qualifier_source, inherited_markers, confidence_factor)
        """
        # === Cas 1: Override local -> pas d'heritage ===
        if is_override:
            logger.debug("[InheritanceEngine] Override detecte -> pas d'heritage")
            return (
                AssertionScope.CONSTRAINED if local_markers else AssertionScope.UNKNOWN,
                QualifierSource.EXPLICIT if local_markers else QualifierSource.NONE,
                [],  # Pas de markers herites
                1.0,
            )

        # === Cas 2: Markers locaux explicites -> pas d'heritage ===
        if local_markers:
            logger.debug(
                f"[InheritanceEngine] Markers locaux explicites: "
                f"{[m.value for m in local_markers]} -> pas d'heritage"
            )
            return (
                AssertionScope.CONSTRAINED,
                QualifierSource.EXPLICIT,
                [],  # Pas de markers herites
                1.0,
            )

        # === Cas 3: Pas de doc_context -> UNKNOWN ===
        if doc_context is None:
            logger.debug("[InheritanceEngine] Pas de doc_context -> UNKNOWN")
            return (
                AssertionScope.UNKNOWN,
                QualifierSource.NONE,
                [],
                0.5,
            )

        # === Cas 4: Appliquer la matrice ===
        has_strong = len(doc_context.strong_markers) > 0
        has_weak = len(doc_context.weak_markers) > 0

        rule = _find_rule(doc_context.doc_scope, has_strong, has_weak)

        if rule is None:
            # Cas non prevu -> fallback sur UNKNOWN
            logger.warning(
                f"[InheritanceEngine] Pas de regle pour "
                f"doc_scope={doc_context.doc_scope.value}, "
                f"strong={has_strong}, weak={has_weak}"
            )
            return (
                AssertionScope.UNKNOWN,
                QualifierSource.NONE,
                [],
                0.5,
            )

        # Determiner les markers a heriter
        inherited_markers = []
        if rule.inherit_markers:
            # Priorite aux strong markers
            if doc_context.strong_markers:
                inherited_markers = doc_context.strong_markers[:2]  # Max 2
            elif doc_context.weak_markers:
                inherited_markers = doc_context.weak_markers[:2]  # Max 2

        logger.debug(
            f"[InheritanceEngine] Regle appliquee: {rule.description}, "
            f"inherited_markers={inherited_markers}"
        )

        return (
            rule.result_scope,
            rule.result_source,
            inherited_markers,
            rule.confidence_factor,
        )

    def compute_final_context(
        self,
        polarity: Polarity,
        polarity_confidence: float,
        doc_context: Optional[DocContextFrame],
        local_markers: List[LocalMarker],
        is_override: bool,
    ) -> AnchorContext:
        """
        Calcule le contexte final d'un anchor.

        Combine les resultats heuristiques avec l'heritage documentaire.

        Args:
            polarity: Polarite detectee par heuristiques
            polarity_confidence: Confiance dans la polarite
            doc_context: Contexte documentaire
            local_markers: Marqueurs locaux
            is_override: True si override detecte

        Returns:
            AnchorContext complet
        """
        # Appliquer l'heritage
        scope, qualifier_source, inherited_markers, conf_factor = self.apply_inheritance(
            doc_context=doc_context,
            local_markers=local_markers,
            is_override=is_override,
        )

        # Calculer la confiance finale
        final_confidence = polarity_confidence * conf_factor

        # Construire les markers finaux
        final_markers = local_markers.copy()

        # Ajouter les markers herites si pas de markers locaux
        if inherited_markers and not local_markers:
            for value in inherited_markers:
                final_markers.append(LocalMarker(
                    value=value,
                    evidence="(inherited from document)",
                    confidence=conf_factor,
                ))

        return AnchorContext(
            polarity=polarity,
            scope=scope,
            local_markers=final_markers,
            is_override=is_override,
            confidence=final_confidence,
            qualifier_source=qualifier_source,
            evidence=[],
        )

    def get_rule_description(
        self,
        doc_context: Optional[DocContextFrame],
    ) -> str:
        """
        Retourne la description de la regle applicable.

        Utile pour le debugging et les logs.
        """
        if doc_context is None:
            return "No doc_context -> UNKNOWN"

        has_strong = len(doc_context.strong_markers) > 0
        has_weak = len(doc_context.weak_markers) > 0

        rule = _find_rule(doc_context.doc_scope, has_strong, has_weak)

        if rule:
            return rule.description
        return f"No rule for {doc_context.doc_scope.value}"


# Singleton
_engine_instance: Optional[InheritanceEngine] = None


def get_inheritance_engine() -> InheritanceEngine:
    """Retourne l'instance singleton du moteur d'heritage."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = InheritanceEngine()
    return _engine_instance


__all__ = [
    "InheritanceRule",
    "InheritanceEngine",
    "get_inheritance_engine",
    "INHERITANCE_RULES",
]
