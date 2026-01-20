# ADR Relations Discursivement Déterminées - Règles d'attribution du DefensibilityTier
#
# Ce module implémente les règles d'attribution du tier selon l'ADR:
# - EXPLICIT → STRICT (par défaut)
# - MIXED → STRICT (au moins une preuve EXPLICIT)
# - DISCURSIVE → STRICT ou EXTENDED selon la matrice basis → tier
#
# Ref: doc/ongoing/ADR_DISCURSIVE_RELATIONS.md

from typing import List, Optional, Set
from .types import (
    AssertionKind,
    DiscursiveBasis,
    DiscursiveAbstainReason,
    DefensibilityTier,
    SemanticGrade,
    RelationType,
    ExtractionMethod,
)


# =============================================================================
# Whitelist RelationType pour DISCURSIVE (V1)
# =============================================================================

# RelationType autorisés pour DISCURSIVE (contrainte C4)
DISCURSIVE_ALLOWED_RELATION_TYPES: Set[RelationType] = {
    RelationType.ALTERNATIVE_TO,  # Toujours autorisé
    RelationType.APPLIES_TO,      # Toujours autorisé
    RelationType.REQUIRES,        # Seulement si obligation explicite (must/shall/required)
    RelationType.REPLACES,        # Seulement si temporalité explicite
    RelationType.DEPRECATES,      # Seulement si temporalité explicite
}

# RelationType interdits pour DISCURSIVE (causalité = raisonnement monde)
DISCURSIVE_FORBIDDEN_RELATION_TYPES: Set[RelationType] = {
    RelationType.CAUSES,      # Causalité = raisonnement monde
    RelationType.PREVENTS,    # Causalité = raisonnement monde
    RelationType.MITIGATES,   # Causalité = raisonnement monde
    RelationType.ENABLES,     # Implique capacité non-textuelle
    RelationType.DEFINES,     # Définitionnel = risque ontologique
}


# =============================================================================
# Bases déterministes fortes vs moins déterministes
# =============================================================================

# Bases déterministes fortes → peuvent être STRICT avec 1 span
# (reposent sur des opérateurs linguistiques structurants)
STRONG_DETERMINISTIC_BASES: Set[DiscursiveBasis] = {
    DiscursiveBasis.ALTERNATIVE,  # "or", "either...or", "X ou Y"
    DiscursiveBasis.DEFAULT,      # "by default", "par défaut"
    DiscursiveBasis.EXCEPTION,    # "unless", "except", "sauf si"
}

# Bases moins déterministes → nécessitent plus de friction (≥ 2 spans)
WEAK_DETERMINISTIC_BASES: Set[DiscursiveBasis] = {
    DiscursiveBasis.SCOPE,        # Maintien de portée entre spans
    DiscursiveBasis.COREF,        # Résolution référentielle
    DiscursiveBasis.ENUMERATION,  # Listes explicites
}

# Marqueurs textuels pour les bases fortes (pour validation)
STRONG_BASIS_MARKERS = {
    DiscursiveBasis.ALTERNATIVE: {"or", "either", "ou", "soit"},
    DiscursiveBasis.DEFAULT: {"by default", "default", "par défaut", "défaut"},
    DiscursiveBasis.EXCEPTION: {"unless", "except", "sauf", "à moins"},
}


# =============================================================================
# ExtractionMethod autorisés pour DISCURSIVE (contrainte C3bis)
# =============================================================================

# DISCURSIVE ne peut pas être produit par LLM seul
DISCURSIVE_ALLOWED_EXTRACTION_METHODS: Set[ExtractionMethod] = {
    ExtractionMethod.PATTERN,
    ExtractionMethod.HYBRID,
}


# =============================================================================
# Règles d'attribution du tier
# =============================================================================

class TierAttributionResult:
    """Résultat de l'attribution du tier avec justification."""

    def __init__(
        self,
        tier: DefensibilityTier,
        reason: str,
        abstain_reason: Optional[DiscursiveAbstainReason] = None
    ):
        self.tier = tier
        self.reason = reason
        self.abstain_reason = abstain_reason

    def __repr__(self) -> str:
        return f"TierAttributionResult(tier={self.tier}, reason='{self.reason}')"


def is_relation_type_allowed_for_discursive(relation_type: RelationType) -> bool:
    """
    Vérifie si un RelationType est autorisé pour DISCURSIVE.

    Contrainte C4 de l'ADR.
    """
    return relation_type in DISCURSIVE_ALLOWED_RELATION_TYPES


def is_extraction_method_allowed_for_discursive(method: ExtractionMethod) -> bool:
    """
    Vérifie si une ExtractionMethod est autorisée pour DISCURSIVE.

    Contrainte C3bis de l'ADR: DISCURSIVE + LLM seul est interdit.
    """
    return method in DISCURSIVE_ALLOWED_EXTRACTION_METHODS


def has_strong_deterministic_basis(bases: List[DiscursiveBasis]) -> bool:
    """
    Vérifie si au moins une base déterministe forte est présente.

    Bases fortes: ALTERNATIVE, DEFAULT, EXCEPTION
    """
    return any(basis in STRONG_DETERMINISTIC_BASES for basis in bases)


def compute_tier_for_discursive(
    bases: List[DiscursiveBasis],
    relation_type: RelationType,
    extraction_method: ExtractionMethod,
    span_count: int = 1,
    has_marker_in_text: bool = True,
) -> TierAttributionResult:
    """
    Calcule le DefensibilityTier pour une assertion DISCURSIVE.

    Règles (ADR):
    1. ExtractionMethod ∈ {PATTERN, HYBRID} (pas LLM seul)
    2. RelationType ∈ whitelist_discursive_v1
    3. discursive_basis contient au moins une base déterministe forte
    4. EvidenceBundle satisfait le minimum adapté à la base

    Args:
        bases: Liste des DiscursiveBasis de l'assertion
        relation_type: Type de relation
        extraction_method: Méthode d'extraction utilisée
        span_count: Nombre de spans dans l'EvidenceBundle
        has_marker_in_text: True si le marqueur textuel est présent (or, unless, etc.)

    Returns:
        TierAttributionResult avec tier et justification
    """
    # Contrainte C3bis: ExtractionMethod
    if not is_extraction_method_allowed_for_discursive(extraction_method):
        return TierAttributionResult(
            tier=DefensibilityTier.EXTENDED,
            reason=f"ExtractionMethod={extraction_method} non autorisé pour DISCURSIVE (C3bis)",
            abstain_reason=DiscursiveAbstainReason.TYPE2_RISK
        )

    # Contrainte C4: Whitelist RelationType
    if not is_relation_type_allowed_for_discursive(relation_type):
        return TierAttributionResult(
            tier=DefensibilityTier.EXTENDED,
            reason=f"RelationType={relation_type} non autorisé pour DISCURSIVE (C4)",
            abstain_reason=DiscursiveAbstainReason.WHITELIST_VIOLATION
        )

    # Pas de basis déclarée
    if not bases:
        return TierAttributionResult(
            tier=DefensibilityTier.EXTENDED,
            reason="Aucune DiscursiveBasis déclarée",
            abstain_reason=DiscursiveAbstainReason.WEAK_BUNDLE
        )

    # Vérifier si au moins une base forte est présente
    has_strong_basis = has_strong_deterministic_basis(bases)

    if has_strong_basis:
        # Bases fortes: ALTERNATIVE, DEFAULT, EXCEPTION
        # → STRICT si marqueur présent dans le texte
        if has_marker_in_text:
            return TierAttributionResult(
                tier=DefensibilityTier.STRICT,
                reason=f"Base(s) forte(s) {[b for b in bases if b in STRONG_DETERMINISTIC_BASES]} avec marqueur textuel"
            )
        else:
            return TierAttributionResult(
                tier=DefensibilityTier.EXTENDED,
                reason="Base forte mais marqueur textuel absent",
                abstain_reason=DiscursiveAbstainReason.WEAK_BUNDLE
            )
    else:
        # Bases faibles: SCOPE, COREF, ENUMERATION
        # → STRICT seulement si ≥ 2 spans
        if span_count >= 2:
            return TierAttributionResult(
                tier=DefensibilityTier.STRICT,
                reason=f"Base(s) faible(s) {bases} avec {span_count} spans (≥ 2)"
            )
        else:
            return TierAttributionResult(
                tier=DefensibilityTier.EXTENDED,
                reason=f"Base(s) faible(s) {bases} avec seulement {span_count} span (< 2 requis)",
                abstain_reason=DiscursiveAbstainReason.WEAK_BUNDLE
            )


def compute_defensibility_tier(
    semantic_grade: SemanticGrade,
    assertion_kind: Optional[AssertionKind] = None,
    discursive_bases: Optional[List[DiscursiveBasis]] = None,
    relation_type: Optional[RelationType] = None,
    extraction_method: Optional[ExtractionMethod] = None,
    span_count: int = 1,
    has_marker_in_text: bool = True,
) -> TierAttributionResult:
    """
    Calcule le DefensibilityTier pour une SemanticRelation.

    Règles récapitulatives (ADR):
    | SemanticGrade | DefensibilityTier | Rationale |
    |---------------|-------------------|-----------|
    | EXPLICIT      | STRICT            | Preuve directe, toujours défendable |
    | MIXED         | STRICT            | Au moins une preuve EXPLICIT ancre la relation |
    | DISCURSIVE    | STRICT ou EXTENDED | Dépend de la matrice basis → tier |

    Args:
        semantic_grade: Grade sémantique de la relation
        assertion_kind: Kind de l'assertion (pour DISCURSIVE uniquement)
        discursive_bases: Bases discursives (pour DISCURSIVE uniquement)
        relation_type: Type de relation (pour validation whitelist)
        extraction_method: Méthode d'extraction (pour validation C3bis)
        span_count: Nombre de spans dans l'EvidenceBundle
        has_marker_in_text: True si marqueur textuel présent

    Returns:
        TierAttributionResult avec tier et justification
    """
    # EXPLICIT → STRICT (toujours)
    if semantic_grade == SemanticGrade.EXPLICIT:
        return TierAttributionResult(
            tier=DefensibilityTier.STRICT,
            reason="SemanticGrade=EXPLICIT → preuve directe, toujours défendable"
        )

    # MIXED → STRICT (au moins une preuve EXPLICIT ancre la relation)
    if semantic_grade == SemanticGrade.MIXED:
        return TierAttributionResult(
            tier=DefensibilityTier.STRICT,
            reason="SemanticGrade=MIXED → au moins une preuve EXPLICIT ancre la relation"
        )

    # DISCURSIVE → appliquer la matrice basis → tier
    if semantic_grade == SemanticGrade.DISCURSIVE:
        # Valeurs par défaut si non fournies
        if discursive_bases is None:
            discursive_bases = []
        if relation_type is None:
            relation_type = RelationType.ASSOCIATED_WITH
        if extraction_method is None:
            extraction_method = ExtractionMethod.HYBRID

        return compute_tier_for_discursive(
            bases=discursive_bases,
            relation_type=relation_type,
            extraction_method=extraction_method,
            span_count=span_count,
            has_marker_in_text=has_marker_in_text,
        )

    # Cas par défaut (ne devrait pas arriver)
    return TierAttributionResult(
        tier=DefensibilityTier.EXTENDED,
        reason=f"SemanticGrade inconnu: {semantic_grade}"
    )


# =============================================================================
# Validation helpers
# =============================================================================

def validate_discursive_assertion(
    relation_type: RelationType,
    extraction_method: ExtractionMethod,
    discursive_bases: List[DiscursiveBasis],
) -> Optional[DiscursiveAbstainReason]:
    """
    Valide qu'une assertion DISCURSIVE respecte les contraintes de l'ADR.

    Returns:
        None si valide, sinon la raison d'abstention
    """
    # C3bis: ExtractionMethod
    if not is_extraction_method_allowed_for_discursive(extraction_method):
        return DiscursiveAbstainReason.TYPE2_RISK

    # C4: Whitelist RelationType
    if not is_relation_type_allowed_for_discursive(relation_type):
        return DiscursiveAbstainReason.WHITELIST_VIOLATION

    # Basis requise
    if not discursive_bases:
        return DiscursiveAbstainReason.WEAK_BUNDLE

    return None


def should_abstain(
    assertion_kind: AssertionKind,
    relation_type: RelationType,
    extraction_method: ExtractionMethod,
    discursive_bases: Optional[List[DiscursiveBasis]] = None,
) -> Optional[DiscursiveAbstainReason]:
    """
    Détermine si une assertion doit être rejetée (ABSTAIN).

    Args:
        assertion_kind: EXPLICIT ou DISCURSIVE
        relation_type: Type de relation
        extraction_method: Méthode d'extraction
        discursive_bases: Bases discursives (pour DISCURSIVE)

    Returns:
        None si l'assertion est acceptable, sinon la raison d'abstention
    """
    # EXPLICIT: pas de validation spéciale
    if assertion_kind == AssertionKind.EXPLICIT:
        return None

    # DISCURSIVE: valider les contraintes
    if assertion_kind == AssertionKind.DISCURSIVE:
        return validate_discursive_assertion(
            relation_type=relation_type,
            extraction_method=extraction_method,
            discursive_bases=discursive_bases or [],
        )

    return None
