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

import json
import logging
from typing import Dict, List, Optional, Protocol, Set

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
                # Year fields avec format invalide → REJETER (pas juste dégrader)
                # "H1, 2025" ou "2023-10-11" dans un champ doc_year est inutilisable
                is_year_field = field.field_name.endswith("_year") or field.field_name == "year"
                has_year_format_issue = any("does not match year format" in i for i in issues)
                if is_year_field and has_year_format_issue:
                    frame.validation_notes.append(
                        f"LexicalSanity: REJECTED '{field.field_name}'="
                        f"'{value}' — invalid year format"
                    )
                    continue  # Ne pas ajouter à kept
                # Autres issues → dégrader confiance
                field.confidence = FrameFieldConfidence.LOW

            kept.append(field)

        frame.fields = kept
        return frame


# ============================================================================
# Validator 5: Metric Context (anti-SLA / anti-percentage)
# ============================================================================

class MetricContextValidator:
    """
    Détecte les valeurs dans un contexte SLA/performance et dégrade leur confiance.

    Règle:
    - version/release dont l'evidence contient des keywords SLA → dégradé LOW

    Note: l'ancien check "major >= 50" a été supprimé — le contrat d'autorité
    (ResolverPriorStatus) le rend redondant et il causait des faux positifs
    sur les identifiants numériques légitimes (2021, 1809, etc.).
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

            # Note: l'ancien Check "major >= 50" a été supprimé.
            # Le contrat d'autorité (ResolverPriorStatus) rend ce check redondant
            # et il causait des faux positifs sur les identifiants numériques
            # légitimes (2021, 1809, etc.)

            # Check: keywords SLA dans les evidence units → dégrader LOW
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
# Validator 6: Plausibility (core invariants)
# ============================================================================

class PlausibilityValidator:
    """
    Filtres de plausibilité core (invariants de format uniquement).

    Les bornes numériques (min_year, max_year) sont dans la policy
    DomainContext (PolicyValidator). Ici on ne garde que les
    invariants de format universels.
    """

    def validate(
        self,
        frame: ApplicabilityFrame,
        units: List[EvidenceUnit],
        profile: CandidateProfile,
    ) -> ApplicabilityFrame:
        import re

        iso_date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")

        kept = []
        for field in frame.fields:
            value = field.value_normalized.strip()
            reject = False

            # Invariant universel : lifecycle_status ≠ date ISO brute
            if field.field_name == "lifecycle_status" and iso_date_re.match(value):
                frame.validation_notes.append(
                    f"Plausibility: REJECTED '{field.field_name}'='{value}' "
                    f"— ISO date is not a status keyword"
                )
                reject = True

            if not reject:
                kept.append(field)

        frame.fields = kept
        return frame


# ============================================================================
# Validator 7: Policy (DomainContext-driven)
# ============================================================================

class PolicyValidator:
    """
    Applique les règles de policy du DomainContext aux champs du frame.

    Comportement expected_axes :
    - strict_expected=false (défaut) : axes hors expected reçoivent une note
      mais ne sont PAS rejetés (soft boost pour le scoring futur)
    - strict_expected=true : axes hors expected sont rejetés (hard filter)
    - excluded_axes : TOUJOURS hard reject (indépendant de strict_expected)
    """

    def __init__(self, tenant_id: str = "default"):
        self.tenant_id = tenant_id
        self._policy: Optional[dict] = None

    def _load_policy(self) -> dict:
        if self._policy is not None:
            return self._policy
        try:
            from knowbase.ontology.domain_context_store import get_domain_context_store
            profile = get_domain_context_store().get_profile(self.tenant_id)
            if profile and profile.axis_policy:
                self._policy = json.loads(profile.axis_policy)
            else:
                self._policy = {}
        except Exception:
            self._policy = {}
        return self._policy

    def validate(
        self,
        frame: ApplicabilityFrame,
        units: List[EvidenceUnit],
        profile: CandidateProfile,
    ) -> ApplicabilityFrame:
        policy = self._load_policy()
        if not policy:
            return frame

        expected = set(policy.get("expected_axes", []))
        excluded = set(policy.get("excluded_axes", []))
        strict_expected = policy.get("strict_expected", False)
        year_range = policy.get("year_range", {})
        overrides = policy.get("plausibility_overrides", {})

        kept = []
        for field in frame.fields:
            # 1. excluded_axes → TOUJOURS hard reject
            if field.field_name in excluded:
                frame.validation_notes.append(
                    f"Policy: REJECTED '{field.field_name}' — in excluded_axes"
                )
                continue

            # 2. expected_axes → soft (note) ou hard (reject) selon strict_expected
            if expected and field.field_name not in expected:
                if strict_expected:
                    frame.validation_notes.append(
                        f"Policy: REJECTED '{field.field_name}' — not in expected_axes (strict mode)"
                    )
                    continue
                else:
                    frame.validation_notes.append(
                        f"Policy: NOTE '{field.field_name}' not in expected_axes (soft mode, kept)"
                    )

            # 3. Year range plausibility (policy-driven)
            if year_range:
                import re as re_mod
                import datetime
                value_str = field.value_normalized.strip()
                apply_year_check = False

                if field.field_name == "year" or field.field_name.endswith("_year"):
                    apply_year_check = True
                elif field.field_name.endswith("_date"):
                    if re_mod.match(r"^\d{4}(-\d{2})?(-\d{2})?$", value_str):
                        apply_year_check = True

                if apply_year_check:
                    try:
                        year_val = int(value_str[:4])
                        min_year = year_range.get("min", 1970)
                        max_relative = year_range.get("max_relative", 2)
                        max_year = datetime.datetime.now().year + max_relative
                        if year_val < min_year or year_val > max_year:
                            frame.validation_notes.append(
                                f"Policy: REJECTED '{field.field_name}'='{value_str}' "
                                f"— year {year_val} outside [{min_year}, {max_year}]"
                            )
                            continue
                    except (ValueError, IndexError):
                        pass

            # 4. Plausibility overrides (reject/accept patterns par axe)
            axis_rules = overrides.get(field.field_name, {})
            if axis_rules:
                import re as re_mod
                value = field.value_normalized.strip()
                reject = False

                for pattern in axis_rules.get("reject_patterns", []):
                    if re_mod.match(pattern, value):
                        frame.validation_notes.append(
                            f"Policy: REJECTED '{field.field_name}'='{value}' "
                            f"— matches reject_pattern '{pattern}'"
                        )
                        reject = True
                        break

                accept_patterns = axis_rules.get("accept_patterns", [])
                if not reject and accept_patterns:
                    if not any(re_mod.match(p, value) for p in accept_patterns):
                        frame.validation_notes.append(
                            f"Policy: REJECTED '{field.field_name}'='{value}' "
                            f"— matches no accept_pattern"
                        )
                        reject = True

                if reject:
                    continue

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

    def __init__(self, tenant_id: str = "default") -> None:
        self.validators: List[FrameValidator] = [
            EvidenceIntegrityValidator(),
            NoEvidenceValidator(),
            ValueConsistencyValidator(),
            LexicalSanityValidator(),
            PlausibilityValidator(),
            MetricContextValidator(),
            PolicyValidator(tenant_id=tenant_id),
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
    "PlausibilityValidator",
    "MetricContextValidator",
    "PolicyValidator",
]
