"""
OSMOSE - NormativePatternExtractor

Extracteur pattern-first pour les règles normatives.
Détecte les marqueurs modaux (must, shall, required, etc.) et extrait les contraintes.

ADR: doc/ongoing/ADR_NORMATIVE_RULES_SPEC_FACTS.md

Invariants:
- INV-NORM-01: Preuve locale obligatoire (evidence_span)
- INV-NORM-02: Marqueur modal explicite requis
- INV-NORM-04: Pas de sujet inventé
- INV-AGN-01: Domain-agnostic (pas de prédicats métier)

Author: Claude Code
Date: 2026-01-21
"""

import re
import logging
from typing import List, Optional, Tuple, Dict, Any
from dataclasses import dataclass
from datetime import datetime
from ulid import ULID

from .types import (
    NormativeRule,
    NormativeModality,
    ConstraintType,
    ExtractionMethod,
    ScopeAnchor,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Modal Markers - Patterns linguistiques (EN + FR)
# =============================================================================

# Marqueurs MUST (obligation forte)
MUST_MARKERS_EN = [
    r"\bmust\b",
    r"\bshall\b",
    r"\bare\s+to\s+be\b",
    r"\bis\s+to\s+be\b",
    r"\bis\s+required\b",
    r"\bare\s+required\b",
    r"\brequired\b",
    r"\bmandatory\b",
    r"\bobligatory\b",
]

MUST_MARKERS_FR = [
    r"\bdoit\b",
    r"\bdoivent\b",
    r"\bobligatoire\b",
    r"\brequ(?:is|ise|ises)\b",
    r"\bimp[ée]ratif\b",
]

# Marqueurs MUST_NOT (interdiction)
MUST_NOT_MARKERS_EN = [
    r"\bmust\s+not\b",
    r"\bshall\s+not\b",
    r"\bshould\s+not\s+be\s+used\b",
    r"\bprohibited\b",
    r"\bforbidden\b",
    r"\bnot\s+allowed\b",
    r"\bno\s+\w+\s+allowed\b",
]

MUST_NOT_MARKERS_FR = [
    r"\bne\s+doit\s+pas\b",
    r"\bne\s+doivent\s+pas\b",
    r"\binterdit\b",
    r"\bproscrit\b",
]

# Marqueurs SHOULD (recommandation)
SHOULD_MARKERS_EN = [
    r"\bshould\b(?!\s+not)",
    r"\brecommended\b",
    r"\badvisable\b",
    r"\bit\s+is\s+recommended\b",
]

SHOULD_MARKERS_FR = [
    r"\bdevrait\b",
    r"\bdevraient\b",
    r"\brecommandé\b",
    r"\bconseillé\b",
]

# Marqueurs MAY (permission/optionnel)
MAY_MARKERS_EN = [
    r"\bmay\b",
    r"\bcan\b(?=.*\boptional)",  # "can" seulement si accompagné de "optional"
    r"\boptional\b",
    r"\boptionally\b",
]

MAY_MARKERS_FR = [
    r"\bpeut\b",
    r"\bpeuvent\b",
    r"\boptionnel\b",
    r"\bfacultatif\b",
]

# Marqueurs conditionnels (pour R2 - détection condition)
CONDITIONAL_MARKERS = [
    r"\bif\b",
    r"\bwhen\b",
    r"\bunless\b",
    r"\bexcept\b",
    r"\bin\s+case\s+of\b",
    r"\bsi\b",
    r"\bquand\b",
    r"\bsauf\b",
    r"\bà\s+moins\s+que\b",
]

# Marqueurs de version/range (pour constraint_type=MIN)
VERSION_RANGE_MARKERS = [
    r"(?:or\s+)?(?:higher|later|above|newer)",
    r"(?:or\s+)?(?:lower|earlier|below|older)",
    r"at\s+least",
    r"at\s+most",
    r"minimum\s+(?:of\s+)?",
    r"maximum\s+(?:of\s+)?",
    r"no\s+(?:less|more)\s+than",
    r"\+$",  # TLS 1.2+
    r">=",
    r"<=",
]


@dataclass
class ModalMatch:
    """Résultat d'un match de marqueur modal."""
    modality: NormativeModality
    marker_text: str
    start_pos: int
    end_pos: int
    language: str  # "EN" ou "FR"


@dataclass
class ExtractionCandidate:
    """Candidat d'extraction avant validation finale."""
    sentence: str
    modal_match: ModalMatch
    subject_text: Optional[str]
    constraint_value: Optional[str]
    constraint_type: ConstraintType
    constraint_unit: Optional[str]
    condition_span: Optional[str]
    confidence: float


class NormativePatternExtractor:
    """
    Extracteur pattern-first pour les règles normatives.

    Utilise des patterns regex pour détecter les marqueurs modaux
    puis extrait le sujet et la contrainte.

    Usage:
        extractor = NormativePatternExtractor()
        rules = extractor.extract_from_text(text, doc_id, chunk_id)
    """

    VERSION = "v1.0.0"

    def __init__(self, min_confidence: float = 0.7):
        """
        Initialise l'extracteur.

        Args:
            min_confidence: Seuil minimum de confidence pour accepter une extraction
        """
        self.min_confidence = min_confidence
        self._compile_patterns()

    def _compile_patterns(self):
        """Compile les patterns regex pour la performance."""
        # Compile tous les patterns par modalité
        self.patterns: Dict[NormativeModality, List[Tuple[re.Pattern, str]]] = {
            NormativeModality.MUST_NOT: [
                (re.compile(p, re.IGNORECASE), "EN") for p in MUST_NOT_MARKERS_EN
            ] + [
                (re.compile(p, re.IGNORECASE), "FR") for p in MUST_NOT_MARKERS_FR
            ],
            NormativeModality.MUST: [
                (re.compile(p, re.IGNORECASE), "EN") for p in MUST_MARKERS_EN
            ] + [
                (re.compile(p, re.IGNORECASE), "FR") for p in MUST_MARKERS_FR
            ],
            NormativeModality.SHOULD: [
                (re.compile(p, re.IGNORECASE), "EN") for p in SHOULD_MARKERS_EN
            ] + [
                (re.compile(p, re.IGNORECASE), "FR") for p in SHOULD_MARKERS_FR
            ],
            NormativeModality.MAY: [
                (re.compile(p, re.IGNORECASE), "EN") for p in MAY_MARKERS_EN
            ] + [
                (re.compile(p, re.IGNORECASE), "FR") for p in MAY_MARKERS_FR
            ],
        }

        # Patterns conditionnels
        self.conditional_patterns = [
            re.compile(p, re.IGNORECASE) for p in CONDITIONAL_MARKERS
        ]

        # Patterns version/range
        self.version_range_patterns = [
            re.compile(p, re.IGNORECASE) for p in VERSION_RANGE_MARKERS
        ]

    def extract_from_text(
        self,
        text: str,
        source_doc_id: str,
        source_chunk_id: str,
        source_segment_id: Optional[str] = None,
        evidence_section: Optional[str] = None,
        tenant_id: str = "default",
    ) -> List[NormativeRule]:
        """
        Extrait les règles normatives d'un texte.

        Args:
            text: Texte à analyser
            source_doc_id: ID du document source
            source_chunk_id: ID du chunk source
            source_segment_id: ID du segment (optionnel)
            evidence_section: Titre de section (scope setter)
            tenant_id: ID tenant

        Returns:
            Liste de NormativeRule extraites
        """
        rules: List[NormativeRule] = []

        # Diviser en phrases
        sentences = self._split_sentences(text)

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) < 10:  # Trop court
                continue

            # Chercher un marqueur modal
            modal_match = self._find_modal_marker(sentence)
            if not modal_match:
                continue

            # Extraire le candidat
            candidate = self._extract_candidate(sentence, modal_match)
            if not candidate:
                continue

            # Vérifier la confidence
            if candidate.confidence < self.min_confidence:
                logger.debug(
                    f"[NormativeExtractor] Rejeté (confidence {candidate.confidence:.2f}): "
                    f"{sentence[:50]}..."
                )
                continue

            # Créer la règle
            rule = self._create_rule(
                candidate=candidate,
                source_doc_id=source_doc_id,
                source_chunk_id=source_chunk_id,
                source_segment_id=source_segment_id,
                evidence_section=evidence_section,
                tenant_id=tenant_id,
            )
            rules.append(rule)

            logger.debug(
                f"[NormativeExtractor] Extrait: {rule.modality} "
                f"'{rule.subject_text}' {rule.constraint_type}={rule.constraint_value}"
            )

        return rules

    def _split_sentences(self, text: str) -> List[str]:
        """Divise un texte en phrases."""
        # Pattern simple pour découpage en phrases
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in sentences if s.strip()]

    def _find_modal_marker(self, sentence: str) -> Optional[ModalMatch]:
        """
        Trouve le premier marqueur modal dans une phrase.

        Note: MUST_NOT est vérifié avant MUST pour éviter les faux positifs.
        """
        # Ordre de vérification important: MUST_NOT avant MUST
        modality_order = [
            NormativeModality.MUST_NOT,
            NormativeModality.MUST,
            NormativeModality.SHOULD,
            NormativeModality.MAY,
        ]

        for modality in modality_order:
            for pattern, language in self.patterns.get(modality, []):
                match = pattern.search(sentence)
                if match:
                    return ModalMatch(
                        modality=modality,
                        marker_text=match.group(),
                        start_pos=match.start(),
                        end_pos=match.end(),
                        language=language,
                    )

        return None

    def _extract_candidate(
        self, sentence: str, modal_match: ModalMatch
    ) -> Optional[ExtractionCandidate]:
        """
        Extrait un candidat à partir d'une phrase avec marqueur modal.

        Parse:
        - subject_text: ce qui précède le marqueur
        - constraint: ce qui suit le marqueur
        """
        # Extraire le sujet (avant le marqueur)
        subject_text = self._extract_subject(sentence, modal_match)

        # Extraire la contrainte (après le marqueur)
        constraint_value, constraint_type, constraint_unit = self._extract_constraint(
            sentence, modal_match
        )

        # Détecter les conditions
        condition_span = self._detect_condition(sentence)

        # Calculer la confidence
        confidence = self._calculate_confidence(
            subject_text=subject_text,
            constraint_value=constraint_value,
            modal_match=modal_match,
            has_condition=condition_span is not None,
        )

        # Vérifier que l'extraction a du sens
        if not subject_text and not constraint_value:
            return None

        return ExtractionCandidate(
            sentence=sentence,
            modal_match=modal_match,
            subject_text=subject_text,
            constraint_value=constraint_value,
            constraint_type=constraint_type,
            constraint_unit=constraint_unit,
            condition_span=condition_span,
            confidence=confidence,
        )

    def _extract_subject(self, sentence: str, modal_match: ModalMatch) -> Optional[str]:
        """
        Extrait le sujet de la règle (ce qui précède le marqueur modal).

        Ex: "All HTTP connections must use TLS" → "All HTTP connections"
        """
        # Texte avant le marqueur
        before_marker = sentence[:modal_match.start_pos].strip()

        if not before_marker:
            return None

        # Nettoyer le sujet
        # Supprimer les articles initiaux pour certains cas
        subject = before_marker

        # Si le sujet est trop long, prendre seulement les derniers mots significatifs
        words = subject.split()
        if len(words) > 8:
            # Garder les 6 derniers mots
            subject = " ".join(words[-6:])

        return subject.strip() if subject.strip() else None

    def _extract_constraint(
        self, sentence: str, modal_match: ModalMatch
    ) -> Tuple[Optional[str], ConstraintType, Optional[str]]:
        """
        Extrait la contrainte (valeur, type, unité) après le marqueur modal.

        Ex: "must use TLS 1.2 or higher" → ("TLS 1.2", MIN, None)
        Ex: "must be at least 256GB" → ("256", MIN, "GB")
        """
        # Texte après le marqueur
        after_marker = sentence[modal_match.end_pos:].strip()

        if not after_marker:
            return None, ConstraintType.EQUALS, None

        # Détecter le type de contrainte
        constraint_type = self._detect_constraint_type(after_marker)

        # Extraire la valeur et l'unité
        value, unit = self._extract_value_and_unit(after_marker)

        return value, constraint_type, unit

    def _detect_constraint_type(self, text: str) -> ConstraintType:
        """Détecte le type de contrainte depuis le texte."""
        text_lower = text.lower()

        # Patterns pour MIN
        if any(p.search(text_lower) for p in self.version_range_patterns[:5]):
            return ConstraintType.MIN

        # Patterns pour MAX
        if any(p.search(text_lower) for p in self.version_range_patterns[5:10]):
            return ConstraintType.MAX

        # Pattern pour RANGE
        if re.search(r'\bbetween\b.*\band\b', text_lower):
            return ConstraintType.RANGE

        # Pattern pour ENUM (liste avec "or")
        if re.search(r'\bor\b', text_lower) and not re.search(r'or\s+(higher|lower)', text_lower):
            return ConstraintType.ENUM

        # Par défaut: EQUALS
        return ConstraintType.EQUALS

    def _extract_value_and_unit(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Extrait la valeur et l'unité d'une contrainte.

        Ex: "256GB" → ("256", "GB")
        Ex: "TLS 1.2+" → ("TLS 1.2", None)
        Ex: "8 characters" → ("8", "characters")
        """
        # Nettoyer le texte
        text = text.strip()

        # Pattern pour valeur numérique + unité
        numeric_match = re.search(
            r'(\d+(?:\.\d+)?)\s*([A-Za-z]+)?',
            text
        )

        if numeric_match:
            value = numeric_match.group(1)
            unit = numeric_match.group(2)
            return value, unit

        # Pattern pour version (TLS 1.2, v2.0, etc.)
        version_match = re.search(
            r'((?:TLS|SSL|v)?[\d.]+\+?)',
            text,
            re.IGNORECASE
        )

        if version_match:
            return version_match.group(1).rstrip('+'), None

        # Pattern pour mots-clés valeurs (enabled, disabled, etc.)
        keyword_match = re.search(
            r'\b(enabled|disabled|true|false|on|off)\b',
            text,
            re.IGNORECASE
        )

        if keyword_match:
            return keyword_match.group(1).lower(), None

        # Prendre le premier groupe de mots après le verbe
        words = text.split()
        if len(words) >= 2:
            # Ignorer les verbes communs
            verbs = {"be", "use", "have", "configure", "set", "enable"}
            start_idx = 0
            for i, w in enumerate(words):
                if w.lower() not in verbs:
                    start_idx = i
                    break
            value_words = words[start_idx:start_idx + 3]
            return " ".join(value_words), None

        return text[:50] if text else None, None

    def _detect_condition(self, sentence: str) -> Optional[str]:
        """
        Détecte et extrait une condition dans la phrase.

        Ex: "TLS required when connecting externally" → "when connecting externally"
        """
        for pattern in self.conditional_patterns:
            match = pattern.search(sentence)
            if match:
                # Extraire la condition (du marqueur jusqu'à la fin ou la virgule)
                start = match.start()
                # Chercher la fin de la condition
                end_match = re.search(r'[,;.]', sentence[start:])
                if end_match:
                    end = start + end_match.start()
                else:
                    end = len(sentence)

                condition = sentence[start:end].strip()
                if len(condition) > 5:  # Condition significative
                    return condition

        return None

    def _calculate_confidence(
        self,
        subject_text: Optional[str],
        constraint_value: Optional[str],
        modal_match: ModalMatch,
        has_condition: bool,
    ) -> float:
        """
        Calcule un score de confidence pour l'extraction.

        Facteurs:
        - Présence de sujet et contrainte
        - Force du marqueur modal
        - Présence de condition (pénalité si non capturée)
        """
        confidence = 0.5  # Base

        # Bonus si sujet présent
        if subject_text and len(subject_text) > 3:
            confidence += 0.2

        # Bonus si contrainte présente
        if constraint_value:
            confidence += 0.2

        # Bonus pour marqueurs forts
        strong_markers = {NormativeModality.MUST, NormativeModality.MUST_NOT}
        if modal_match.modality in strong_markers:
            confidence += 0.1

        # Pénalité si condition détectée (incertitude sur le scope)
        if has_condition:
            confidence -= 0.1

        return min(1.0, max(0.0, confidence))

    def _create_rule(
        self,
        candidate: ExtractionCandidate,
        source_doc_id: str,
        source_chunk_id: str,
        source_segment_id: Optional[str],
        evidence_section: Optional[str],
        tenant_id: str,
    ) -> NormativeRule:
        """Crée une NormativeRule à partir d'un candidat validé."""
        rule_id = str(ULID())

        # Créer le scope anchor
        scope_anchor = ScopeAnchor(
            doc_id=source_doc_id,
            section_id=None,  # À enrichir par le caller si disponible
            scope_setter_ids=[],
            scope_tags=[],
        )

        return NormativeRule(
            rule_id=rule_id,
            tenant_id=tenant_id,
            subject_text=candidate.subject_text or "unspecified",
            subject_concept_id=None,  # À enrichir par le linker
            modality=candidate.modal_match.modality,
            constraint_type=candidate.constraint_type,
            constraint_value=candidate.constraint_value or "",
            constraint_unit=candidate.constraint_unit,
            constraint_condition_span=candidate.condition_span,
            evidence_span=candidate.sentence,
            evidence_section=evidence_section,
            scope_anchors=[scope_anchor],
            source_doc_id=source_doc_id,
            source_chunk_id=source_chunk_id,
            source_segment_id=source_segment_id,
            extraction_method=ExtractionMethod.PATTERN,
            confidence=candidate.confidence,
            extractor_version=self.VERSION,
            created_at=datetime.utcnow(),
        )


# =============================================================================
# Fonctions utilitaires
# =============================================================================

def extract_normative_rules(
    text: str,
    doc_id: str,
    chunk_id: str,
    **kwargs
) -> List[NormativeRule]:
    """
    Fonction convenience pour l'extraction de règles normatives.

    Usage:
        rules = extract_normative_rules(text, doc_id, chunk_id)
    """
    extractor = NormativePatternExtractor()
    return extractor.extract_from_text(text, doc_id, chunk_id, **kwargs)
