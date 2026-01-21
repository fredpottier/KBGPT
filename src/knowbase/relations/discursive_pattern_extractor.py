"""
ADR Relations Discursivement Déterminées - Discursive Pattern Extractor

Extracteur de relations discursives basé sur patterns textuels.
Implémente le contrat E1-E6 de l'ADR.

Bases fortes V1:
- ALTERNATIVE: "or", "either...or", "ou", "soit...soit"
- DEFAULT: "by default", "par défaut"
- EXCEPTION: "unless", "except", "sauf si"

Règles du contrat:
- E1: Local Textual Trigger (marqueur obligatoire)
- E2: Local Co-presence (concepts dans même contexte)
- E3: No Global Pairing (pas de pairing arbitraire)
- E4: Pattern-First, LLM-Second
- E5: Candidate ≠ Assertion
- E6: No Concept Creation (concepts existants uniquement)

Ref: doc/ongoing/ADR_DISCURSIVE_RELATIONS.md

Author: Claude Code
Date: 2025-01-20
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from enum import Enum

from knowbase.relations.types import (
    RelationType,
    ExtractionMethod,
    AssertionKind,
    DiscursiveBasis,
    DiscursiveAbstainReason,
)
from knowbase.relations.tier_attribution import (
    is_relation_type_allowed_for_discursive,
    DISCURSIVE_ALLOWED_RELATION_TYPES,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Types pour les candidats discursifs
# =============================================================================

@dataclass
class DiscursiveCandidate:
    """
    Candidat de relation discursive (pré-validation).

    Note: Un candidat n'a aucun statut sémantique (règle E5).
    Il doit être validé avant de devenir une RawAssertion.
    """
    # Concepts identifiés
    subject_concept_id: str
    object_concept_id: str
    subject_surface_form: str
    object_surface_form: str

    # Relation
    relation_type: RelationType
    predicate_raw: str

    # Discursive metadata
    discursive_basis: DiscursiveBasis
    marker_text: str  # Le marqueur détecté ("or", "by default", etc.)

    # Evidence
    evidence_text: str  # Le span contenant le marqueur
    evidence_start: int  # Position dans le texte source
    evidence_end: int

    # Confidence du pattern (avant validation)
    pattern_confidence: float = 0.8

    # Validation status
    is_valid: bool = False
    rejection_reason: Optional[DiscursiveAbstainReason] = None


@dataclass
class DiscursiveExtractionResult:
    """Résultat de l'extraction discursive."""
    candidates: List[DiscursiveCandidate] = field(default_factory=list)
    valid_candidates: List[DiscursiveCandidate] = field(default_factory=list)
    rejected_candidates: List[DiscursiveCandidate] = field(default_factory=list)

    # Stats
    patterns_found: int = 0
    concepts_matched: int = 0
    validation_passed: int = 0
    validation_failed: int = 0


# =============================================================================
# Patterns de détection par DiscursiveBasis
# =============================================================================

# Motif générique pour capturer les noms de produits (SAP HANA, SAP S/4HANA, Oracle Database, etc.)
# Utilise une approche plus permissive pour les noms avec /, chiffres, etc.
PRODUCT_NAME_PATTERN = r"([A-Z][A-Za-z0-9]*(?:[\s\-/][A-Za-z0-9]+)*)"

# Pattern ALTERNATIVE: "X or Y", "either X or Y", "X ou Y", "soit X soit Y"
ALTERNATIVE_PATTERNS = [
    # English - "X or Y"
    rf"(?:either\s+)?{PRODUCT_NAME_PATTERN}\s+(?:or)\s+{PRODUCT_NAME_PATTERN}",
    # French - "X ou Y"
    rf"(?:soit\s+)?{PRODUCT_NAME_PATTERN}\s+(?:ou)\s+{PRODUCT_NAME_PATTERN}",
]

# Pattern DEFAULT: "X by default", "par défaut X", "defaults to X"
DEFAULT_PATTERNS = [
    # English - "X uses Y by default"
    rf"{PRODUCT_NAME_PATTERN}\s+(?:uses?|utilizes?|employs?)\s+{PRODUCT_NAME_PATTERN}\s+(?:by\s+default)",
    # English - "X defaults to Y"
    rf"{PRODUCT_NAME_PATTERN}\s+defaults?\s+to\s+{PRODUCT_NAME_PATTERN}",
    # English - "by default, X uses Y"
    rf"(?:by\s+default)[,\s]+{PRODUCT_NAME_PATTERN}\s+(?:uses?|is|are)\s+{PRODUCT_NAME_PATTERN}",
    # French - "X utilise Y par défaut"
    rf"{PRODUCT_NAME_PATTERN}\s+(?:utilise|emploie)\s+{PRODUCT_NAME_PATTERN}\s+(?:par\s+défaut)",
    # French - "par défaut, X utilise Y"
    rf"(?:par\s+défaut)[,\s]+{PRODUCT_NAME_PATTERN}\s+(?:utilise|est)\s+{PRODUCT_NAME_PATTERN}",
]

# Pattern EXCEPTION: "X unless Y", "X except Y", "X sauf si Y"
EXCEPTION_PATTERNS = [
    # English - "X requires Y, unless"
    rf"{PRODUCT_NAME_PATTERN}\s+(?:requires?|needs?|must\s+have)\s+{PRODUCT_NAME_PATTERN}[,\s]+(?:unless|except(?:\s+if)?|excluding)",
    # English - "all X require Y, unless" / "X installations require Y, unless"
    rf"(?:all\s+|new\s+)?{PRODUCT_NAME_PATTERN}(?:\s+(?:installations?|deployments?|systems?))?\s+(?:require|need)\s+{PRODUCT_NAME_PATTERN}[,\s]+(?:unless|except)",
    # French - "X nécessite Y sauf si"
    rf"{PRODUCT_NAME_PATTERN}\s+(?:nécessite|requiert|exige)\s+{PRODUCT_NAME_PATTERN}[,\s]+(?:sauf\s+si|à\s+moins\s+que|excepté)",
]

# Marqueurs pour validation
ALTERNATIVE_MARKERS = {"or", "ou", "either", "soit"}
DEFAULT_MARKERS = {"by default", "default", "par défaut", "défaut", "defaults to"}
EXCEPTION_MARKERS = {"unless", "except", "sauf", "à moins", "excluding", "excepté"}

# =============================================================================
# Filtres anti-bruit (ChatGPT recommendation)
# =============================================================================

# Stoplist de concepts génériques à ignorer (trop vagues pour des relations)
CONCEPT_STOPLIST: Set[str] = {
    # Éléments de document
    "document", "disclaimer", "note", "warning", "figure", "table",
    "appendix", "overview", "introduction", "summary", "reference",
    "glossary", "index", "chapter", "section", "paragraph",
    # Métadonnées
    "public", "private", "internal", "confidential",
    "example", "example code", "sample", "demo",
    # Légal / boilerplate
    "intellectual property rights", "copyright", "trademark",
    "experimental features", "beta and other experimental features",
    # Génériques
    "activities", "data", "information", "content", "details",
    "upgrade guide", "conversion guide", "installation guide",
    "operations guide", "admin guide",
}

# =============================================================================
# Marqueurs de substituabilité (pour ALTERNATIVE_TO vs CHOICE_BETWEEN)
# =============================================================================

# Marqueurs explicites de substituabilité → ALTERNATIVE_TO
# Sans ces marqueurs, "X or Y" → CHOICE_BETWEEN (choice-set, pas substituabilité)
SUBSTITUTABILITY_MARKERS: Set[str] = {
    # Anglais
    "alternative to", "instead of", "in place of", "in lieu of",
    "replaces", "replace", "replacing", "replaced by",
    "substitute for", "substitutes", "substituting",
    "equivalent to", "can be used in place of",
    "interchangeable with", "swap", "switch to",
    # Français
    "alternative à", "au lieu de", "à la place de",
    "remplace", "remplacer", "remplacé par",
    "substitut de", "équivalent à", "interchangeable avec",
}


# =============================================================================
# Extracteur principal
# =============================================================================

class DiscursivePatternExtractor:
    """
    Extracteur de relations discursives basé sur patterns.

    Implémente le contrat E1-E6 de l'ADR:
    - E1: Génère uniquement à partir de marqueurs discursifs explicites
    - E2: Concepts doivent être co-présents localement
    - E3: Pas de pairing global à travers le document
    - E4: Pattern-first (pas de LLM pour proposer)
    - E5: Candidats sans statut sémantique jusqu'à validation
    - E6: Opère sur inventaire de concepts existants uniquement
    """

    def __init__(
        self,
        context_window: int = 500,
        min_pattern_confidence: float = 0.7,
    ):
        """
        Initialize extractor.

        Args:
            context_window: Taille max du contexte autour du marqueur (règle E2)
            min_pattern_confidence: Confidence minimum pour les patterns
        """
        self.context_window = context_window
        self.min_pattern_confidence = min_pattern_confidence

        # Compile patterns
        self._alternative_patterns = [re.compile(p, re.IGNORECASE) for p in ALTERNATIVE_PATTERNS]
        self._default_patterns = [re.compile(p, re.IGNORECASE) for p in DEFAULT_PATTERNS]
        self._exception_patterns = [re.compile(p, re.IGNORECASE) for p in EXCEPTION_PATTERNS]

        self._stats = {
            "documents_processed": 0,
            "patterns_detected": 0,
            "candidates_generated": 0,
            "candidates_validated": 0,
            "candidates_rejected": 0,
        }

    def extract(
        self,
        text: str,
        concepts: List[Dict[str, Any]],
        document_id: str,
        chunk_id: Optional[str] = None,
    ) -> DiscursiveExtractionResult:
        """
        Extrait les relations discursives d'un texte.

        Args:
            text: Texte source à analyser
            concepts: Liste des concepts connus (règle E6)
                      Format: [{"concept_id": str, "canonical_name": str, "surface_forms": List[str]}]
            document_id: ID du document source
            chunk_id: ID du chunk (optionnel)

        Returns:
            DiscursiveExtractionResult avec candidats validés et rejetés
        """
        result = DiscursiveExtractionResult()
        self._stats["documents_processed"] += 1

        # Construire l'index des concepts pour matching rapide (règle E6)
        concept_index = self._build_concept_index(concepts)

        # Extraire par type de pattern (règle E1: marqueur obligatoire)

        # 1. ALTERNATIVE patterns
        alternative_candidates = self._extract_alternative_patterns(
            text, concept_index, document_id, chunk_id
        )
        result.candidates.extend(alternative_candidates)

        # 2. DEFAULT patterns
        default_candidates = self._extract_default_patterns(
            text, concept_index, document_id, chunk_id
        )
        result.candidates.extend(default_candidates)

        # 3. EXCEPTION patterns
        exception_candidates = self._extract_exception_patterns(
            text, concept_index, document_id, chunk_id
        )
        result.candidates.extend(exception_candidates)

        result.patterns_found = len(result.candidates)
        self._stats["patterns_detected"] += result.patterns_found

        # Valider les candidats
        validated_candidates = []
        for candidate in result.candidates:
            self._validate_candidate(candidate)

            if candidate.is_valid:
                validated_candidates.append(candidate)
                self._stats["candidates_validated"] += 1
            else:
                result.rejected_candidates.append(candidate)
                result.validation_failed += 1
                self._stats["candidates_rejected"] += 1

        # Filtrer les concepts de la stoplist (anti-bruit)
        filtered_candidates = []
        stoplist_rejected = 0
        for candidate in validated_candidates:
            if self._is_stoplist_concept(candidate.subject_surface_form) or \
               self._is_stoplist_concept(candidate.object_surface_form):
                candidate.is_valid = False
                candidate.rejection_reason = DiscursiveAbstainReason.WEAK_BUNDLE
                result.rejected_candidates.append(candidate)
                stoplist_rejected += 1
            else:
                filtered_candidates.append(candidate)

        # Dédupliquer les relations symétriques (ALTERNATIVE: A↔B = une seule entrée)
        deduplicated_candidates = self._deduplicate_symmetric(filtered_candidates)
        dedup_removed = len(filtered_candidates) - len(deduplicated_candidates)

        result.valid_candidates = deduplicated_candidates
        result.validation_passed = len(deduplicated_candidates)

        self._stats["candidates_generated"] += len(result.valid_candidates)
        self._stats["stoplist_rejected"] = self._stats.get("stoplist_rejected", 0) + stoplist_rejected
        self._stats["dedup_removed"] = self._stats.get("dedup_removed", 0) + dedup_removed

        logger.info(
            f"[DiscursivePatternExtractor] Document {document_id}: "
            f"patterns={result.patterns_found}, valid={result.validation_passed}, "
            f"rejected={result.validation_failed}, stoplist={stoplist_rejected}, dedup={dedup_removed}"
        )

        return result

    def _is_stoplist_concept(self, surface_form: str) -> bool:
        """Vérifie si un concept est dans la stoplist (trop générique)."""
        return surface_form.lower().strip() in CONCEPT_STOPLIST

    def _deduplicate_symmetric(
        self,
        candidates: List[DiscursiveCandidate]
    ) -> List[DiscursiveCandidate]:
        """
        Déduplique les relations symétriques (ALTERNATIVE).

        Pour A↔B, on garde une seule entrée avec la clé canonique:
        key = (min(A,B), max(A,B), basis)
        """
        seen_keys: Set[Tuple[str, str, str]] = set()
        deduplicated: List[DiscursiveCandidate] = []

        for candidate in candidates:
            # Pour les relations symétriques, créer une clé canonique
            if candidate.discursive_basis == DiscursiveBasis.ALTERNATIVE:
                # Clé canonique: (min_id, max_id, basis)
                id1 = candidate.subject_concept_id
                id2 = candidate.object_concept_id
                key = (min(id1, id2), max(id1, id2), candidate.discursive_basis.name)
            else:
                # Pour les autres (DEFAULT, EXCEPTION), garder l'ordre
                key = (candidate.subject_concept_id, candidate.object_concept_id,
                       candidate.discursive_basis.name)

            if key not in seen_keys:
                seen_keys.add(key)
                deduplicated.append(candidate)

        return deduplicated

    def _build_concept_index(
        self,
        concepts: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Construit un index des concepts pour matching rapide.

        Returns:
            Dict mapping surface_form.lower() -> concept info
        """
        index: Dict[str, Dict[str, Any]] = {}

        for concept in concepts:
            concept_id = concept.get("concept_id", "")
            canonical_name = concept.get("canonical_name", "")
            surface_forms = concept.get("surface_forms", [])

            # Index canonical name
            if canonical_name:
                key = canonical_name.lower().strip()
                index[key] = {
                    "concept_id": concept_id,
                    "canonical_name": canonical_name,
                    "matched_form": canonical_name,
                }

            # Index surface forms
            for form in surface_forms:
                if form:
                    key = form.lower().strip()
                    if key not in index:  # Don't overwrite canonical
                        index[key] = {
                            "concept_id": concept_id,
                            "canonical_name": canonical_name,
                            "matched_form": form,
                        }

        return index

    def _find_concept(
        self,
        text: str,
        concept_index: Dict[str, Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Trouve un concept dans le texte.

        Args:
            text: Texte à chercher (ex: "SAP HANA")
            concept_index: Index des concepts

        Returns:
            Concept info if found, None otherwise
        """
        # Normaliser
        text_lower = text.lower().strip()

        # 1. Recherche exacte (prioritaire)
        if text_lower in concept_index:
            return concept_index[text_lower]

        # 2. Recherche: le texte contient un concept connu
        # Prioriser les matches les plus longs (plus spécifiques)
        best_match = None
        best_match_len = 0

        for concept_key, concept_info in concept_index.items():
            # Le texte capturé contient le nom du concept
            if concept_key in text_lower:
                # Vérifier que c'est un mot complet (pas une sous-chaîne)
                # Ex: "hana" dans "sap s/4hana" ne doit pas matcher si "s/4hana" existe
                import re
                pattern = r'\b' + re.escape(concept_key) + r'\b'
                if re.search(pattern, text_lower):
                    if len(concept_key) > best_match_len:
                        best_match = concept_info
                        best_match_len = len(concept_key)

        return best_match

    def _find_concepts_in_window(
        self,
        text: str,
        start: int,
        end: int,
        concept_index: Dict[str, Dict[str, Any]],
        exclude_marker_pos: Optional[Tuple[int, int]] = None,
    ) -> List[Tuple[Dict[str, Any], int, int]]:
        """
        Trouve tous les concepts connus dans une fenêtre de texte.

        Args:
            text: Texte complet
            start: Position de début de la fenêtre
            end: Position de fin de la fenêtre
            concept_index: Index des concepts
            exclude_marker_pos: Position du marqueur à exclure (start, end)

        Returns:
            Liste de (concept_info, position_start, position_end)
        """
        window = text[start:end].lower()
        found = []

        # Trier les concepts par longueur décroissante (plus spécifiques d'abord)
        sorted_concepts = sorted(
            concept_index.items(),
            key=lambda x: len(x[0]),
            reverse=True
        )

        # Positions déjà couvertes pour éviter les doublons
        covered_positions: Set[int] = set()

        for concept_key, concept_info in sorted_concepts:
            if len(concept_key) < 4:  # Ignorer les concepts trop courts
                continue

            # Chercher toutes les occurrences
            idx = 0
            while True:
                pos = window.find(concept_key, idx)
                if pos == -1:
                    break

                # Position absolue dans le texte
                abs_pos = start + pos
                abs_end = abs_pos + len(concept_key)

                # Vérifier que cette position n'est pas déjà couverte
                if not any(p in covered_positions for p in range(abs_pos, abs_end)):
                    # Vérifier que ce n'est pas le marqueur lui-même
                    if exclude_marker_pos:
                        marker_start, marker_end = exclude_marker_pos
                        if not (abs_pos >= marker_start and abs_end <= marker_end):
                            found.append((concept_info, abs_pos, abs_end))
                            covered_positions.update(range(abs_pos, abs_end))
                    else:
                        found.append((concept_info, abs_pos, abs_end))
                        covered_positions.update(range(abs_pos, abs_end))

                idx = pos + 1

        return found

    def _extract_alternative_patterns(
        self,
        text: str,
        concept_index: Dict[str, Dict[str, Any]],
        document_id: str,
        chunk_id: Optional[str],
    ) -> List[DiscursiveCandidate]:
        """
        Extrait les patterns ALTERNATIVE avec approche concept-aware.

        Stratégie:
        1. Trouve les marqueurs "or"/"ou" dans le texte
        2. Cherche les concepts connus avant et après le marqueur
        3. Crée des candidats si deux concepts distincts sont trouvés
        """
        candidates = []

        # Approche concept-aware: chercher les marqueurs puis les concepts
        alternative_markers = [
            (r'\s+or\s+', 'or'),
            (r'\s+ou\s+', 'ou'),
        ]

        for marker_pattern, marker_name in alternative_markers:
            for match in re.finditer(marker_pattern, text, re.IGNORECASE):
                marker_start = match.start()
                marker_end = match.end()

                # Définir la fenêtre de recherche (100 chars avant/après le marqueur)
                window_before_start = max(0, marker_start - 100)
                window_after_end = min(len(text), marker_end + 100)

                # Chercher les concepts avant le marqueur
                concepts_before = self._find_concepts_in_window(
                    text, window_before_start, marker_start,
                    concept_index, exclude_marker_pos=(marker_start, marker_end)
                )

                # Chercher les concepts après le marqueur
                concepts_after = self._find_concepts_in_window(
                    text, marker_end, window_after_end,
                    concept_index, exclude_marker_pos=(marker_start, marker_end)
                )

                # Créer des candidats pour chaque paire (avant, après)
                for concept1, pos1_start, pos1_end in concepts_before:
                    for concept2, pos2_start, pos2_end in concepts_after:
                        # Vérifier que ce sont des concepts différents
                        if concept1["concept_id"] == concept2["concept_id"]:
                            continue

                        # Evidence: du début du premier concept à la fin du second
                        evidence_start = max(0, pos1_start - 20)
                        evidence_end = min(len(text), pos2_end + 20)
                        evidence_text = text[evidence_start:evidence_end]

                        # Déterminer le type de relation:
                        # - ALTERNATIVE_TO si marqueur de substituabilité explicite
                        # - CHOICE_BETWEEN sinon (choice-set linguistique, pas substituabilité)
                        relation_type, predicate = self._determine_alternative_relation_type(evidence_text)

                        # Ne créer qu'UN candidat (relation symétrique, dédup gérée ailleurs)
                        candidates.append(DiscursiveCandidate(
                            subject_concept_id=concept1["concept_id"],
                            object_concept_id=concept2["concept_id"],
                            subject_surface_form=concept1["matched_form"],
                            object_surface_form=concept2["matched_form"],
                            relation_type=relation_type,
                            predicate_raw=predicate,
                            discursive_basis=DiscursiveBasis.ALTERNATIVE,
                            marker_text=marker_name,
                            evidence_text=evidence_text,
                            evidence_start=evidence_start,
                            evidence_end=evidence_end,
                            pattern_confidence=0.80,
                        ))

        return candidates

    def _determine_alternative_relation_type(
        self,
        evidence_text: str
    ) -> Tuple[RelationType, str]:
        """
        Détermine si "X or Y" exprime une substituabilité ou un simple choice-set.

        - Si marqueur de substituabilité explicite → ALTERNATIVE_TO
        - Sinon → CHOICE_BETWEEN (choice-set linguistique)

        Returns:
            (RelationType, predicate_raw)
        """
        evidence_lower = evidence_text.lower()

        # Vérifier la présence d'un marqueur de substituabilité
        for marker in SUBSTITUTABILITY_MARKERS:
            if marker in evidence_lower:
                return (RelationType.ALTERNATIVE_TO, "alternative to")

        # Par défaut: choice-set linguistique, pas substituabilité
        return (RelationType.CHOICE_BETWEEN, "choice between")

    def _extract_default_patterns(
        self,
        text: str,
        concept_index: Dict[str, Dict[str, Any]],
        document_id: str,
        chunk_id: Optional[str],
    ) -> List[DiscursiveCandidate]:
        """Extrait les patterns DEFAULT."""
        candidates = []

        for pattern in self._default_patterns:
            for match in pattern.finditer(text):
                term1 = match.group(1).strip()
                term2 = match.group(2).strip()

                # Règle E6: vérifier concepts connus
                concept1 = self._find_concept(term1, concept_index)
                concept2 = self._find_concept(term2, concept_index)

                if not concept1 or not concept2:
                    continue

                # Evidence
                evidence_start = max(0, match.start() - 30)
                evidence_end = min(len(text), match.end() + 30)
                evidence_text = text[evidence_start:evidence_end]

                # Créer candidat: Subject USES Object (by default)
                candidates.append(DiscursiveCandidate(
                    subject_concept_id=concept1["concept_id"],
                    object_concept_id=concept2["concept_id"],
                    subject_surface_form=concept1["matched_form"],
                    object_surface_form=concept2["matched_form"],
                    relation_type=RelationType.USES,
                    predicate_raw="uses by default",
                    discursive_basis=DiscursiveBasis.DEFAULT,
                    marker_text="by default",
                    evidence_text=evidence_text,
                    evidence_start=evidence_start,
                    evidence_end=evidence_end,
                    pattern_confidence=0.80,
                ))

        return candidates

    def _extract_exception_patterns(
        self,
        text: str,
        concept_index: Dict[str, Dict[str, Any]],
        document_id: str,
        chunk_id: Optional[str],
    ) -> List[DiscursiveCandidate]:
        """Extrait les patterns EXCEPTION."""
        candidates = []

        for pattern in self._exception_patterns:
            for match in pattern.finditer(text):
                term1 = match.group(1).strip()
                term2 = match.group(2).strip()

                # Règle E6: vérifier concepts connus
                concept1 = self._find_concept(term1, concept_index)
                concept2 = self._find_concept(term2, concept_index)

                if not concept1 or not concept2:
                    continue

                # Evidence (inclure le contexte de l'exception)
                evidence_start = max(0, match.start() - 20)
                evidence_end = min(len(text), match.end() + 100)  # Plus large pour capturer l'exception
                evidence_text = text[evidence_start:evidence_end]

                # Détecter le marqueur
                match_lower = match.group(0).lower()
                if "unless" in match_lower:
                    marker = "unless"
                elif "except" in match_lower:
                    marker = "except"
                elif "sauf" in match_lower:
                    marker = "sauf si"
                else:
                    marker = "exception"

                # Créer candidat: Subject REQUIRES Object (with exception noted)
                candidates.append(DiscursiveCandidate(
                    subject_concept_id=concept1["concept_id"],
                    object_concept_id=concept2["concept_id"],
                    subject_surface_form=concept1["matched_form"],
                    object_surface_form=concept2["matched_form"],
                    relation_type=RelationType.REQUIRES,
                    predicate_raw="requires (with exception)",
                    discursive_basis=DiscursiveBasis.EXCEPTION,
                    marker_text=marker,
                    evidence_text=evidence_text,
                    evidence_start=evidence_start,
                    evidence_end=evidence_end,
                    pattern_confidence=0.75,  # Slightly lower due to exception complexity
                ))

        return candidates

    def _validate_candidate(self, candidate: DiscursiveCandidate) -> None:
        """
        Valide un candidat selon les contraintes ADR.

        Modifie candidate.is_valid et candidate.rejection_reason.
        """
        # Contrainte C4: Whitelist RelationType
        if not is_relation_type_allowed_for_discursive(candidate.relation_type):
            candidate.is_valid = False
            candidate.rejection_reason = DiscursiveAbstainReason.WHITELIST_VIOLATION
            return

        # Vérifier que le marqueur est présent dans l'evidence
        marker_found = False
        evidence_lower = candidate.evidence_text.lower()

        if candidate.discursive_basis == DiscursiveBasis.ALTERNATIVE:
            marker_found = any(m in evidence_lower for m in ALTERNATIVE_MARKERS)
        elif candidate.discursive_basis == DiscursiveBasis.DEFAULT:
            marker_found = any(m in evidence_lower for m in DEFAULT_MARKERS)
        elif candidate.discursive_basis == DiscursiveBasis.EXCEPTION:
            marker_found = any(m in evidence_lower for m in EXCEPTION_MARKERS)

        if not marker_found:
            candidate.is_valid = False
            candidate.rejection_reason = DiscursiveAbstainReason.WEAK_BUNDLE
            return

        # Vérifier confidence minimum
        if candidate.pattern_confidence < self.min_pattern_confidence:
            candidate.is_valid = False
            candidate.rejection_reason = DiscursiveAbstainReason.WEAK_BUNDLE
            return

        # Vérifier que subject != object
        if candidate.subject_concept_id == candidate.object_concept_id:
            candidate.is_valid = False
            candidate.rejection_reason = DiscursiveAbstainReason.AMBIGUOUS_PREDICATE
            return

        # Toutes les validations passent
        candidate.is_valid = True
        candidate.rejection_reason = None

    def get_stats(self) -> Dict[str, int]:
        """Retourne les statistiques d'extraction."""
        return self._stats.copy()

    def reset_stats(self) -> None:
        """Reset les statistiques."""
        self._stats = {
            "documents_processed": 0,
            "patterns_detected": 0,
            "candidates_generated": 0,
            "candidates_validated": 0,
            "candidates_rejected": 0,
        }


# =============================================================================
# Factory function
# =============================================================================

_extractor_instance: Optional[DiscursivePatternExtractor] = None


def get_discursive_pattern_extractor(**kwargs) -> DiscursivePatternExtractor:
    """Get or create DiscursivePatternExtractor instance."""
    global _extractor_instance
    if _extractor_instance is None:
        _extractor_instance = DiscursivePatternExtractor(**kwargs)
    return _extractor_instance
