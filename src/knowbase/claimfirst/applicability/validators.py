# src/knowbase/claimfirst/applicability/validators.py
"""
Layer D: FrameValidationPipeline — Pipeline séquentiel de validation.

Valide que le frame produit par le LLM (Layer C) est evidence-locked:
1. EvidenceIntegrityValidator — supprime unit_ids invalides
2. NoEvidenceValidator — rejette champs sans evidence
3. ValueConsistencyValidator — vérifie valeur existe dans units ou candidats
4. LexicalSanityValidator — vérifie markers contextuels cohérents
"""

from __future__ import annotations

import logging
from typing import Dict, List, Protocol, Set

from knowbase.claimfirst.applicability.models import (
    ApplicabilityFrame,
    CandidateProfile,
    EvidenceUnit,
    FrameField,
    FrameFieldConfidence,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Validator Protocol
# ============================================================================

class FrameValidator(Protocol):
    """Interface pour un validateur de frame."""

    def validate(
        self,
        frame: ApplicabilityFrame,
        units: List[EvidenceUnit],
        profile: CandidateProfile,
    ) -> ApplicabilityFrame:
        """Valide et corrige le frame, retourne la version corrigée."""
        ...


# ============================================================================
# Validator 1: Evidence Integrity
# ============================================================================

class EvidenceIntegrityValidator:
    """Supprime les unit_ids qui n'existent pas dans la liste d'EvidenceUnits."""

    def validate(
        self,
        frame: ApplicabilityFrame,
        units: List[EvidenceUnit],
        profile: CandidateProfile,
    ) -> ApplicabilityFrame:
        valid_ids: Set[str] = {u.unit_id for u in units}
        removed_count = 0

        for field in frame.fields:
            original = field.evidence_unit_ids[:]
            field.evidence_unit_ids = [
                uid for uid in field.evidence_unit_ids if uid in valid_ids
            ]
            diff = len(original) - len(field.evidence_unit_ids)
            if diff > 0:
                removed_count += diff
                frame.validation_notes.append(
                    f"EvidenceIntegrity: removed {diff} invalid unit_ids "
                    f"from field '{field.field_name}'"
                )

        if removed_count:
            logger.debug(
                f"[OSMOSE:Validator:Integrity] Removed {removed_count} invalid unit_ids"
            )

        return frame


# ============================================================================
# Validator 2: No Evidence
# ============================================================================

class NoEvidenceValidator:
    """Rejette les champs qui n'ont aucune evidence (unit_ids vide après intégrité)."""

    def validate(
        self,
        frame: ApplicabilityFrame,
        units: List[EvidenceUnit],
        profile: CandidateProfile,
    ) -> ApplicabilityFrame:
        kept: List[FrameField] = []
        rejected: List[str] = []

        for field in frame.fields:
            if field.evidence_unit_ids:
                kept.append(field)
            else:
                rejected.append(field.field_name)
                frame.validation_notes.append(
                    f"NoEvidence: rejected field '{field.field_name}' "
                    f"(value='{field.value_normalized}') — no valid evidence"
                )

        if rejected:
            logger.debug(
                f"[OSMOSE:Validator:NoEvidence] Rejected fields: {rejected}"
            )

        frame.fields = kept
        return frame


# ============================================================================
# Validator 3: Value Consistency
# ============================================================================

class ValueConsistencyValidator:
    """
    Vérifie que la valeur normalisée de chaque champ existe effectivement
    dans les EvidenceUnits référencées ou dans les ValueCandidates du profil.
    """

    def validate(
        self,
        frame: ApplicabilityFrame,
        units: List[EvidenceUnit],
        profile: CandidateProfile,
    ) -> ApplicabilityFrame:
        unit_map: Dict[str, EvidenceUnit] = {u.unit_id: u for u in units}
        candidate_values: Set[str] = {
            vc.raw_value.lower() for vc in profile.value_candidates
        }

        kept: List[FrameField] = []

        for field in frame.fields:
            value_lower = field.value_normalized.lower().strip()

            # Vérifier dans les candidats
            if value_lower in candidate_values:
                kept.append(field)
                continue

            # Vérifier dans le texte des units référencées
            found_in_unit = False
            for uid in field.evidence_unit_ids:
                unit = unit_map.get(uid)
                if unit and value_lower in unit.text.lower():
                    found_in_unit = True
                    break

            if found_in_unit:
                kept.append(field)
            else:
                # Dégrader la confiance au lieu de supprimer
                field.confidence = FrameFieldConfidence.LOW
                frame.validation_notes.append(
                    f"ValueConsistency: degraded confidence for '{field.field_name}' "
                    f"(value='{field.value_normalized}' not found verbatim in evidence)"
                )
                kept.append(field)

        frame.fields = kept
        return frame


# ============================================================================
# Validator 4: Lexical Sanity
# ============================================================================

class LexicalSanityValidator:
    """
    Vérifie la cohérence lexicale:
    - Un champ 'year' doit contenir une année valide (4 digits, 19xx/20xx)
    - Un champ 'version' ne doit pas contenir le nom du produit
    - La valeur ne doit pas être trop longue (>50 chars = probablement du texte, pas une valeur)
    """

    MAX_VALUE_LENGTH = 50

    def validate(
        self,
        frame: ApplicabilityFrame,
        units: List[EvidenceUnit],
        profile: CandidateProfile,
    ) -> ApplicabilityFrame:
        import re

        kept: List[FrameField] = []

        for field in frame.fields:
            value = field.value_normalized.strip()
            issues: List[str] = []

            # Valeur trop longue
            if len(value) > self.MAX_VALUE_LENGTH:
                issues.append(f"value too long ({len(value)} chars)")

            # Check year-format si le champ est explicitement un *_year ou "year"
            if field.field_name.endswith("_year") or field.field_name == "year":
                if not re.match(r"^(19|20)\d{2}$", value):
                    issues.append(f"'{value}' does not match year format YYYY")

            if field.field_name in ("release_id", "version"):
                # Ne doit pas contenir le nom du produit
                if profile.primary_subject:
                    subject_lower = profile.primary_subject.lower()
                    value_lower = value.lower()
                    if subject_lower in value_lower and len(value) > len(profile.primary_subject) + 10:
                        issues.append(
                            f"value contains product name '{profile.primary_subject}'"
                        )

            if issues:
                frame.validation_notes.append(
                    f"LexicalSanity: issues with '{field.field_name}'="
                    f"'{value}': {', '.join(issues)}"
                )
                # Ne pas rejeter, mais dégrader confiance
                field.confidence = FrameFieldConfidence.LOW

            kept.append(field)

        frame.fields = kept
        return frame


# ============================================================================
# Validator 5: Metric Context (anti-SLA / anti-percentage)
# ============================================================================

class MetricContextValidator:
    """
    Rejette les valeurs qui sont probablement des métriques SLA/performance,
    pas des versions ou releases.

    Règles:
    - version/release avec major >= 50 → rejeté (99.9, 99.7 = SLA percentages)
    - version/release dont l'evidence contient des keywords SLA → dégradé LOW
    """

    SLA_KEYWORDS = frozenset({
        "sla", "uptime", "availability", "service level",
        "guaranteed", "latency", "throughput", "response time",
        "success rate", "error rate", "%",
    })

    def validate(
        self,
        frame: ApplicabilityFrame,
        units: List[EvidenceUnit],
        profile: CandidateProfile,
    ) -> ApplicabilityFrame:
        unit_map: Dict[str, EvidenceUnit] = {u.unit_id: u for u in units}
        kept: List[FrameField] = []

        for field in frame.fields:
            if field.field_name not in ("release_id", "version"):
                kept.append(field)
                continue

            value = field.value_normalized.strip()

            # Check 1: valeur numérique avec major >= 50 → rejeté
            try:
                major = int(value.split(".")[0])
                if major >= 50:
                    frame.validation_notes.append(
                        f"MetricContext: rejected '{field.field_name}={value}' "
                        f"— major >= 50, likely SLA/metric percentage"
                    )
                    continue  # Ne pas garder
            except ValueError:
                pass  # Pas numérique pur (ex: "SP 12"), on continue

            # Check 2: keywords SLA dans les evidence units → dégrader LOW
            has_sla_context = False
            for uid in field.evidence_unit_ids:
                unit = unit_map.get(uid)
                if unit:
                    text_lower = unit.text.lower()
                    if any(kw in text_lower for kw in self.SLA_KEYWORDS):
                        has_sla_context = True
                        break

            if has_sla_context:
                field.confidence = FrameFieldConfidence.LOW
                frame.validation_notes.append(
                    f"MetricContext: degraded '{field.field_name}={value}' to LOW "
                    f"— SLA/metric context detected in evidence"
                )

            kept.append(field)

        frame.fields = kept
        return frame


# ============================================================================
# Pipeline
# ============================================================================

class FrameValidationPipeline:
    """
    Pipeline séquentiel de validation du frame.

    Applique les 4 validateurs dans l'ordre:
    1. EvidenceIntegrity → supprime unit_ids invalides
    2. NoEvidence → rejette champs sans evidence
    3. ValueConsistency → vérifie valeurs dans evidence
    4. LexicalSanity → vérifie cohérence lexicale
    """

    def __init__(self) -> None:
        self.validators: List[FrameValidator] = [
            EvidenceIntegrityValidator(),
            NoEvidenceValidator(),
            ValueConsistencyValidator(),
            LexicalSanityValidator(),
            MetricContextValidator(),
        ]

    def validate(
        self,
        frame: ApplicabilityFrame,
        units: List[EvidenceUnit],
        profile: CandidateProfile,
    ) -> ApplicabilityFrame:
        """
        Applique la pipeline de validation complète.

        Args:
            frame: Frame à valider (sortie Layer C)
            units: EvidenceUnits (sortie Layer A)
            profile: CandidateProfile (sortie Layer B)

        Returns:
            Frame validé et corrigé
        """
        for validator in self.validators:
            frame = validator.validate(frame, units, profile)

        original_count = len(frame.fields) + len(frame.validation_notes)
        logger.debug(
            f"[OSMOSE:FrameValidationPipeline] {frame.doc_id}: "
            f"{len(frame.fields)} fields kept, "
            f"{len(frame.validation_notes)} validation notes"
        )

        return frame


__all__ = [
    "FrameValidationPipeline",
    "EvidenceIntegrityValidator",
    "NoEvidenceValidator",
    "ValueConsistencyValidator",
    "LexicalSanityValidator",
    "MetricContextValidator",
]
