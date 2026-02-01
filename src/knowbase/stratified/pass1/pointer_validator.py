"""
OSMOSE Pipeline V2 - Pointer Validator
=======================================
Ref: Plan Pointer-Based Extraction (2026-01-27)

Validation 3 niveaux des concepts pointés par le LLM:

1. LEXICAL: Score pondéré ≥ 1.5
   - token exact du concept label = +1.0
   - motif valeur dans unité = +1.0
   - synonyme léger (optionnel) = +0.5

2. TYPE MARKERS: Vérification cohérence type/contenu
   - PRESCRIPTIVE → doit avoir must/shall/required/mandatory
   - Sinon downgrade vers DEFINITIONAL

3. VALUE PATTERNS: Si kind spécifié, vérifier présence motif
   - version → \\d+(\\.\\d+)+
   - percentage → \\d+\\s*%
   - size → \\d+\\s*(GB|TB|MB|TiB|GiB)

IMPORTANT:
- La confidence LLM n'est JAMAIS utilisée pour la décision
- Seuls le span + validation = existence
- La confidence peut servir pour tri/priorisation/debug uniquement
"""

import re
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================================
# ENUMS & DATA CLASSES
# ============================================================================

class ValidationStatus(str, Enum):
    """Statut de validation d'un concept pointé."""
    VALID = "VALID"           # Concept validé, peut être promu
    DOWNGRADE = "DOWNGRADE"   # Type modifié (ex: PRESCRIPTIVE → DEFINITIONAL)
    ABSTAIN = "ABSTAIN"       # Concept rejeté, ne sera pas promu


class AbstainReason(str, Enum):
    """Raisons d'ABSTAIN pour un concept."""
    NO_LEXICAL_SUPPORT = "no_lexical_support"
    VALUE_PATTERN_MISMATCH = "value_pattern_mismatch"
    INVALID_UNIT_ID = "invalid_unit_id"
    EMPTY_UNIT = "empty_unit"


@dataclass
class ValidationResult:
    """Résultat de la validation d'un concept pointé."""
    status: ValidationStatus
    score: float = 0.0
    reason: Optional[AbstainReason] = None
    new_type: Optional[str] = None  # Si DOWNGRADE, le nouveau type
    details: str = ""

    @property
    def is_valid(self) -> bool:
        return self.status in (ValidationStatus.VALID, ValidationStatus.DOWNGRADE)


@dataclass
class PointerValidationStats:
    """Statistiques de validation batch."""
    total: int = 0
    valid: int = 0
    downgraded: int = 0
    abstained: int = 0

    # Répartition des raisons d'ABSTAIN
    abstain_no_lexical: int = 0
    abstain_value_mismatch: int = 0
    abstain_invalid_unit: int = 0
    abstain_empty_unit: int = 0

    @property
    def valid_rate(self) -> float:
        return self.valid / self.total if self.total > 0 else 0.0

    @property
    def abstain_rate(self) -> float:
        return self.abstained / self.total if self.total > 0 else 0.0


# ============================================================================
# POINTER VALIDATOR
# ============================================================================

class PointerValidator:
    """
    Valide les concepts pointés avec 3 niveaux de vérification.

    La validation est DÉTERMINISTE et ne dépend PAS de la confidence LLM.

    Usage:
        validator = PointerValidator()
        result = validator.validate(concept_label, concept_type, unit_text, value_kind)

        if result.status == ValidationStatus.VALID:
            # Promouvoir le concept
        elif result.status == ValidationStatus.DOWNGRADE:
            # Promouvoir avec type modifié
        else:  # ABSTAIN
            # Rejeter le concept
    """

    # =========================================================================
    # CONFIGURATION
    # =========================================================================

    # Seuil lexical minimal
    LEXICAL_THRESHOLD = 1.5

    # Marqueurs prescriptifs (EN + FR) - FIX 2026-01-28: Ajout formes verbales manquantes
    PRESCRIPTIVE_MARKERS = [
        # Anglais - Modaux stricts
        "must", "shall", "mandatory", "obligatory",
        # Anglais - Formes de "require" (toutes conjugaisons)
        "require", "requires", "required", "requiring",
        "need to", "needs to", "have to", "has to",
        "is required", "are required",
        # Anglais - Impératifs et restrictions
        "ensure", "ensures", "always", "never", "only",
        "prohibited", "forbidden", "not allowed", "not permitted",
        # Anglais - Formes passives
        "is mandatory", "is obligatory", "is prohibited",
        # Français - Formes de "requérir/exiger"
        "doit", "doivent", "obligatoire", "nécessaire", "impératif",
        "requis", "requiert", "requièrent", "exige", "exigent", "exigé",
        "imposé", "impose", "imposent", "interdit", "toujours", "jamais",
    ]

    # Patterns de valeur par kind - FIX 2026-01-27: Patterns plus flexibles
    VALUE_PATTERNS: Dict[str, str] = {
        "version": r"\d+(\.\d+)+",
        "percentage": r"\d+\s*%",
        "size": r"\d+\s*(GB|TB|MB|TiB|GiB|KB|KiB)",
        "number": r"\d+",
        "boolean": r"\b(true|false|yes|no|enabled|disabled|on|off)\b",
        # FIX: Accepter "30-day", "30 day", "30day", "30 days"
        "duration": r"\d+[-\s]*(ms|s|sec|second|min|minute|hour|h|day|d|week|month|year)s?",
    }

    # Tokens courts à ignorer dans le scoring lexical
    MIN_TOKEN_LENGTH = 3

    # Nombre max de tokens à scorer
    MAX_TOKENS_TO_SCORE = 2

    def __init__(
        self,
        lexical_threshold: float = 1.5,
        strict_type_markers: bool = True,
    ):
        """
        Args:
            lexical_threshold: Seuil minimum pour score lexical (défaut: 1.5)
            strict_type_markers: Si True, PRESCRIPTIVE sans marqueur → DOWNGRADE
        """
        self.lexical_threshold = lexical_threshold
        self.strict_type_markers = strict_type_markers

        # Compiler les patterns
        self._compiled_patterns = {
            kind: re.compile(pattern, re.IGNORECASE)
            for kind, pattern in self.VALUE_PATTERNS.items()
        }

    def validate(
        self,
        concept_label: str,
        concept_type: str,
        unit_text: str,
        value_kind: Optional[str] = None,
    ) -> ValidationResult:
        """
        Valide un concept pointé avec 3 niveaux de vérification.

        Args:
            concept_label: Label du concept (ex: "TLS minimum version")
            concept_type: Type du concept (PRESCRIPTIVE, DEFINITIONAL, etc.)
            unit_text: Texte verbatim de l'unité pointée
            value_kind: Kind de valeur attendue (IGNORÉ depuis FIX 2026-01-27)
                        La détection value_kind est maintenant automatique

        Returns:
            ValidationResult avec statut, score et détails
        """
        # Validation de base
        if not unit_text or not unit_text.strip():
            return ValidationResult(
                status=ValidationStatus.ABSTAIN,
                reason=AbstainReason.EMPTY_UNIT,
                details="Unit text is empty",
            )

        # =====================================================================
        # NIVEAU 1: Support Lexical (scoring pondéré)
        # FIX 2026-01-27: Ne plus utiliser value_kind du LLM, détecter auto
        # =====================================================================
        # Détecter automatiquement si l'unité contient une valeur
        detected_value_kind = self._detect_value_kind(unit_text)
        score = self._compute_lexical_score(concept_label, unit_text, detected_value_kind)

        if score < self.lexical_threshold:
            return ValidationResult(
                status=ValidationStatus.ABSTAIN,
                score=score,
                reason=AbstainReason.NO_LEXICAL_SUPPORT,
                details=f"Lexical score {score:.2f} < threshold {self.lexical_threshold}",
            )

        # =====================================================================
        # NIVEAU 2: Type Markers
        # =====================================================================
        new_type = None
        if self.strict_type_markers and concept_type.upper() == "PRESCRIPTIVE":
            if not self._has_prescriptive_marker(unit_text):
                new_type = "DEFINITIONAL"
                logger.debug(
                    f"[OSMOSE:PointerValidator] Downgrade PRESCRIPTIVE → DEFINITIONAL: "
                    f"'{concept_label}' (no markers in '{unit_text[:50]}...')"
                )

        # =====================================================================
        # NIVEAU 3: Value Patterns - SUPPRIMÉ (FIX 2026-01-27)
        # Le LLM assignait incorrectement value_kind dans 55% des cas
        # La détection est maintenant automatique et utilisée pour le scoring
        # =====================================================================
        # Note: On ne rejette plus sur value_mismatch car:
        # 1. Le LLM n'est plus censé fournir value_kind
        # 2. La détection auto est utilisée uniquement pour le score bonus

        # =====================================================================
        # RÉSULTAT
        # =====================================================================
        if new_type:
            return ValidationResult(
                status=ValidationStatus.DOWNGRADE,
                score=score,
                new_type=new_type,
                details=f"Type downgraded due to missing markers",
            )

        return ValidationResult(
            status=ValidationStatus.VALID,
            score=score,
            details=f"Validated with lexical score {score:.2f}",
        )

    def _detect_value_kind(self, text: str) -> Optional[str]:
        """
        Détecte automatiquement le type de valeur dans le texte.

        FIX 2026-01-27: Remplace la confiance au LLM pour value_kind.
        """
        # Ordre de priorité: du plus spécifique au moins spécifique
        for kind in ["version", "percentage", "size", "duration", "boolean"]:
            if self._check_value_pattern(kind, text):
                return kind
        return None

    def validate_batch(
        self,
        concepts: List[Dict],
        unit_index: Dict[str, "UnitIndexResult"],
    ) -> tuple[List[Dict], List[tuple[Dict, ValidationResult]], PointerValidationStats]:
        """
        Valide un batch de concepts pointés.

        Args:
            concepts: Liste de dicts avec keys: label, type, docitem_id, unit_id, value_kind
            unit_index: Index docitem_id → UnitIndexResult

        Returns:
            (valid_concepts, abstained_with_result, stats)
        """
        from knowbase.stratified.pass1.assertion_unit_indexer import lookup_unit_text

        valid = []
        abstained = []
        stats = PointerValidationStats(total=len(concepts))

        for concept in concepts:
            label = concept.get("label", "")
            concept_type = concept.get("type", "FACTUAL")
            docitem_id = concept.get("docitem_id", "")
            unit_id = concept.get("unit_id", "")
            # FIX 2026-01-27: Ignorer value_kind du LLM (55% d'erreurs)
            # value_kind = concept.get("value_kind")  # SUPPRIMÉ

            # Retrouver le texte de l'unité
            unit_text = lookup_unit_text(unit_index, docitem_id, unit_id)

            if unit_text is None:
                result = ValidationResult(
                    status=ValidationStatus.ABSTAIN,
                    reason=AbstainReason.INVALID_UNIT_ID,
                    details=f"Unit {unit_id} not found in docitem {docitem_id}",
                )
                abstained.append((concept, result))
                stats.abstained += 1
                stats.abstain_invalid_unit += 1
                continue

            # Valider - sans value_kind (détection auto)
            result = self.validate(label, concept_type, unit_text, value_kind=None)

            if result.status == ValidationStatus.VALID:
                # Ajouter le texte verbatim au concept
                concept["exact_quote"] = unit_text
                # FIX: Détecter et stocker le value_kind automatiquement
                detected_kind = self._detect_value_kind(unit_text)
                if detected_kind:
                    concept["value_kind"] = detected_kind
                valid.append(concept)
                stats.valid += 1

            elif result.status == ValidationStatus.DOWNGRADE:
                # Modifier le type et garder
                concept["type"] = result.new_type
                concept["exact_quote"] = unit_text
                concept["_downgraded_from"] = concept_type
                # FIX: Détecter value_kind aussi pour les downgraded
                detected_kind = self._detect_value_kind(unit_text)
                if detected_kind:
                    concept["value_kind"] = detected_kind
                valid.append(concept)
                stats.downgraded += 1

            else:  # ABSTAIN
                abstained.append((concept, result))
                stats.abstained += 1
                if result.reason == AbstainReason.NO_LEXICAL_SUPPORT:
                    stats.abstain_no_lexical += 1
                # FIX: value_mismatch ne devrait plus arriver
                elif result.reason == AbstainReason.VALUE_PATTERN_MISMATCH:
                    stats.abstain_value_mismatch += 1
                elif result.reason == AbstainReason.EMPTY_UNIT:
                    stats.abstain_empty_unit += 1

        # Log statistiques
        logger.info(
            f"[OSMOSE:PointerValidator] Batch: {stats.total} concepts → "
            f"{stats.valid} VALID, {stats.downgraded} DOWNGRADE, "
            f"{stats.abstained} ABSTAIN ({stats.abstain_rate:.1%})"
        )

        if stats.abstained > 0:
            logger.debug(
                f"[OSMOSE:PointerValidator] ABSTAIN distribution: "
                f"no_lexical={stats.abstain_no_lexical}, "
                f"value_mismatch={stats.abstain_value_mismatch}, "
                f"invalid_unit={stats.abstain_invalid_unit}, "
                f"empty_unit={stats.abstain_empty_unit}"
            )

        return valid, abstained, stats

    # =========================================================================
    # NIVEAU 1: SCORING LEXICAL
    # =========================================================================

    def _compute_lexical_score(
        self,
        label: str,
        text: str,
        value_kind: Optional[str] = None,
    ) -> float:
        """
        Calcule le score lexical pondéré.

        Score:
        - Token exact du label (mot entier) = +1.0
        - Motif valeur dans unité = +1.0

        Raffinements:
        - Ignorer tokens < 3 chars ("at", "of", "in")
        - Matcher en mots entiers (regex \\btoken\\b)
        - Max 2 tokens scorés pour éviter inflation
        """
        score = 0.0
        text_lower = text.lower()
        tokens_scored = 0

        # Score sur les tokens du label
        for token in label.lower().split():
            # Ignorer tokens courts (stopwords, articles)
            if len(token) < self.MIN_TOKEN_LENGTH:
                continue

            # Max tokens à scorer
            if tokens_scored >= self.MAX_TOKENS_TO_SCORE:
                break

            # Match mot entier uniquement (pas substring)
            pattern = rf'\b{re.escape(token)}\b'
            if re.search(pattern, text_lower):
                score += 1.0
                tokens_scored += 1

        # Score sur la présence d'un motif valeur
        if value_kind:
            # Si kind spécifié, vérifier ce pattern
            if self._check_value_pattern(value_kind, text):
                score += 1.0
        else:
            # Sinon, vérifier si un motif valeur générique est présent
            if self._has_any_value_pattern(text):
                score += 1.0

        return score

    def _has_any_value_pattern(self, text: str) -> bool:
        """Vérifie si un motif valeur quelconque est présent."""
        # Pattern générique: nombres avec unités ou versions
        generic_pattern = r'\d+(\.\d+)*\s*(%|GB|TB|MB|GiB|TiB|ms|s|min|h)?'
        return bool(re.search(generic_pattern, text))

    # =========================================================================
    # NIVEAU 2: TYPE MARKERS
    # =========================================================================

    def _has_prescriptive_marker(self, text: str) -> bool:
        """Vérifie la présence d'un marqueur prescriptif."""
        text_lower = text.lower()
        return any(marker in text_lower for marker in self.PRESCRIPTIVE_MARKERS)

    # =========================================================================
    # NIVEAU 3: VALUE PATTERNS
    # =========================================================================

    def _check_value_pattern(self, value_kind: str, text: str) -> bool:
        """Vérifie la présence du pattern de valeur spécifié."""
        pattern = self._compiled_patterns.get(value_kind.lower())
        if not pattern:
            # Kind inconnu, vérifier pattern générique
            return self._has_any_value_pattern(text)

        return bool(pattern.search(text))


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def validate_pointer_concept(
    concept_label: str,
    concept_type: str,
    unit_text: str,
    value_kind: Optional[str] = None,
) -> ValidationResult:
    """
    Fonction helper pour valider un concept pointé.

    Args:
        concept_label: Label du concept
        concept_type: Type (PRESCRIPTIVE, DEFINITIONAL, etc.)
        unit_text: Texte de l'unité pointée
        value_kind: Kind de valeur attendue (optionnel)

    Returns:
        ValidationResult
    """
    validator = PointerValidator()
    return validator.validate(concept_label, concept_type, unit_text, value_kind)


def reconstruct_exact_quote(
    unit_index: Dict[str, "UnitIndexResult"],
    docitem_id: str,
    unit_id: str,
) -> Optional[str]:
    """
    Reconstruit le texte verbatim depuis l'index.

    C'est LA garantie anti-reformulation: le texte vient TOUJOURS
    de l'index, jamais du LLM.

    Args:
        unit_index: Index global docitem_id → UnitIndexResult
        docitem_id: ID du DocItem
        unit_id: ID local de l'unité (U1, U2, etc.)

    Returns:
        Texte verbatim ou None si non trouvé
    """
    from knowbase.stratified.pass1.assertion_unit_indexer import lookup_unit_text
    return lookup_unit_text(unit_index, docitem_id, unit_id)
