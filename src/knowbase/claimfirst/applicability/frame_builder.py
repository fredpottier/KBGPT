# src/knowbase/claimfirst/applicability/frame_builder.py
"""
Layer C: FrameBuilder — Construction du frame d'applicabilité (LLM evidence-locked).

Le LLM reçoit uniquement:
- Titre, primary_subject, taille du document
- Candidats: candidate_id, raw_value, value_type, frequency, in_title,
  in_header, cooccurs_subject, nearby_markers, unit_ids[:5]
- Markers par catégorie
- Domain Context (optionnel)
- Pre-identified Values du SubjectResolver (priors avec contrat d'autorité)

Règles dans le prompt:
- Ne référencer QUE des IDs existants
- Ne pas inventer de valeurs
- Champs indéterminables → unknowns

Fallback déterministe si LLM indisponible.
TaskType: METADATA_EXTRACTION (1000 tokens réponse).
"""

from __future__ import annotations

import json
import logging
import re
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from knowbase.claimfirst.applicability.models import (
    ApplicabilityFrame,
    CandidateProfile,
    EvidenceUnit,
    FrameField,
    FrameFieldConfidence,
    ValueCandidate,
)

logger = logging.getLogger(__name__)

# ============================================================================
# RESOLVER PRIOR AUTHORITY CONTRACT
# ============================================================================

ROLE_TO_FIELD = {
    "revision": "release_id",
    "temporal": "doc_year",
    "geographic": "region",
    "applicability_scope": "edition",
    "status": "lifecycle_status",
}


class ResolverPriorStatus(str, Enum):
    """Statut d'identification du resolver pour le contrat d'autorité."""

    CONFIRMED = "confirmed"
    """Le resolver a trouvé une revision fiable (confidence >= 0.7)."""

    ABSENT = "absent"
    """Le resolver n'a trouvé aucune revision."""

    WEAK_GUESS = "weak_guess"
    """Pas de prior resolver mais preuve forte Layer B (named_version + in_title)."""


# ============================================================================
# PROMPT TEMPLATE
# ============================================================================

FRAME_BUILDER_PROMPT = """You are an evidence-locked metadata extractor. Your job is to build an applicability frame for a document based ONLY on pre-extracted candidates.

## Document Info
- Title: {title}
- Primary Subject: {primary_subject}
- Document Size: {total_chars} chars ({total_units} evidence units)

## Pre-extracted Value Candidates
{candidates_section}

## Detected Markers by Category
{markers_section}

{domain_context_section}

{resolver_prior_section}

## STRICT RULES
1. You may ONLY use candidate_ids and unit_ids that appear above
2. You may ONLY use raw_values from the candidates listed above
3. If a field cannot be determined from the candidates → add it to "unknowns"
4. NEVER invent values that don't appear in the candidates
5. A numeric_identifier (4-digit number like 2023, 1809) is AMBIGUOUS:
   it could be a release identifier, a calendar year, a regulation version,
   a model year, a clinical trial phase number, etc.
   Use document context + Domain Context identification semantics to decide.
   Examples:
     "ProductX 2023 Security Guide" → 2023 is likely release_id
     "Copyright 2023 Acme Corp" → 2023 is likely publication_year
     "Basel III Framework" → III is likely regulation_version
     "Clio III Owner Manual" → III is likely model_generation
6. If Domain Context provides identification semantics → follow those rules
7. Without Domain Context: adjacent to subject name = likely release_id or model identifier;
   in copyright/publication context = likely publication_year;
   standalone with temporal markers = likely calendar year
8. Do NOT include the subject/product name in version values
9. Prefer candidates that are: in_title > in_header > high_frequency > cooccurs_subject
10. Choose the most specific field_name for the value's role in THIS domain
    (release_id, publication_year, regulation_version, model_generation, trial_phase, etc.)
    NEVER use value_type names as field_name (numeric_identifier, named_version, etc.)
11. Do NOT create fields for IP addresses, port numbers, or non-version numeric patterns
12. Do NOT create fields for SLA percentages, performance metrics, or availability targets:
    "99.7%" near "SLA/uptime/availability" → NOT a version/release
    Values with major number >= 50 (like 99.9, 99.7, 95.0) are almost never versions
13. Bare decimal numbers (type=version, e.g. "3.0", "3.1") without an explicit version keyword
    are AMBIGUOUS. Prefer named_version candidates (e.g. "Version 3.0") over bare decimals.
    If only bare decimals exist, set confidence to "low" and explain why in reasoning

## Output JSON Format
{{
  "fields": [
    {{
      "field_name": "<domain-specific role: release_id, model_generation, regulation_version, trial_phase, publication_year, etc.>",
      "value_normalized": "<exact raw_value from a candidate>",
      "display_label": "<version|release|edition|generation|phase|etc.>",
      "evidence_unit_ids": ["EU:0:1", "EU:3:0"],
      "candidate_ids": ["VC:named_version:abc123"],
      "confidence": "high|medium|low",
      "reasoning": "<brief explanation>"
    }}
  ],
  "unknowns": ["edition", "region"]
}}

Respond with ONLY the JSON object, no markdown fences."""

# ============================================================================
# JSON Schema for structured output (vLLM / burst mode)
# ============================================================================

FRAME_BUILDER_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field_name": {"type": "string"},
                    "value_normalized": {"type": "string"},
                    "display_label": {"type": "string"},
                    "evidence_unit_ids": {"type": "array", "items": {"type": "string"}},
                    "candidate_ids": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "reasoning": {"type": "string"},
                },
                "required": ["field_name", "value_normalized", "display_label",
                             "evidence_unit_ids", "candidate_ids", "confidence", "reasoning"],
                "additionalProperties": False,
            },
        },
        "unknowns": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["fields", "unknowns"],
    "additionalProperties": False,
}


class FrameBuilder:
    """
    Construit le frame d'applicabilité via LLM (evidence-locked)
    ou fallback déterministe.
    """

    def __init__(
        self,
        llm_client: Any = None,
        use_llm: bool = True,
    ):
        """
        Args:
            llm_client: Client LLM (optionnel)
            use_llm: Si False, utilise uniquement le fallback déterministe
        """
        self.llm_client = llm_client
        self.use_llm = use_llm and llm_client is not None
        if use_llm and llm_client is None:
            logger.warning(
                "[OSMOSE:FrameBuilder] use_llm=True but llm_client is None — "
                "version detection will use deterministic fallback only "
                "(reduced accuracy for release_id identification)"
            )

    def build(
        self,
        profile: CandidateProfile,
        units: List[EvidenceUnit],
        domain_context_prompt: Optional[str] = None,
        resolver_axis_values: Optional[List] = None,
    ) -> ApplicabilityFrame:
        """
        Construit le frame d'applicabilité.

        Args:
            profile: Profil de candidats (sortie Layer B)
            units: EvidenceUnits (sortie Layer A)
            domain_context_prompt: Contexte domaine optionnel
            resolver_axis_values: AxisValueOutput du SubjectResolver (priors)

        Returns:
            ApplicabilityFrame (non validé, pré-Layer D)
        """
        if not profile.value_candidates:
            return ApplicabilityFrame(
                doc_id=profile.doc_id,
                fields=[],
                unknowns=["release_id", "edition"],
                method="no_candidates",
            )

        # 1. Convertir les priors du resolver en FrameFields
        prior_fields, prior_status = self._resolve_priors(resolver_axis_values)

        # 2. Enrichir les evidence_unit_ids via token matching dans les units
        if prior_fields:
            self._link_priors_to_evidence(prior_fields, units, profile)
            # 2b. Dédupliquer : si plusieurs priors pour le même field_name,
            # garder celui qui a le plus d'evidence (ex: "2021" x208 > "9.0" x2)
            prior_fields = self._deduplicate_priors(prior_fields)

        if prior_fields:
            logger.debug(
                f"[OSMOSE:FrameBuilder] Resolver priors: status={prior_status.value}, "
                f"fields={[(f.field_name, f.value_normalized) for f in prior_fields]}"
            )

        # 3. Appeler LLM / fallback
        if self.use_llm:
            try:
                frame = self._build_with_llm(
                    profile, units, domain_context_prompt,
                    prior_fields, prior_status,
                )
                if frame and frame.fields:
                    # 4. Fusionner priors avec réponse LLM (contrat d'autorité)
                    frame = self._merge_with_priors(frame, prior_fields, prior_status, profile)
                    return frame
                logger.warning(
                    f"[OSMOSE:FrameBuilder] LLM returned empty frame for {profile.doc_id}, "
                    f"falling back to deterministic"
                )
            except Exception as e:
                logger.warning(
                    f"[OSMOSE:FrameBuilder] LLM failed for {profile.doc_id}: {e}, "
                    f"falling back to deterministic"
                )

        frame = self._build_deterministic(profile, units)
        # Appliquer aussi le contrat d'autorité au fallback déterministe
        frame = self._merge_with_priors(frame, prior_fields, prior_status, profile)
        return frame

    # =========================================================================
    # Resolver priors
    # =========================================================================

    def _resolve_priors(
        self,
        axis_values: Optional[List],
    ) -> Tuple[List[FrameField], ResolverPriorStatus]:
        """Convertit les axis_values du SubjectResolver en FrameFields priors."""
        if not axis_values:
            return [], ResolverPriorStatus.ABSENT

        fields = []
        has_revision = False
        for av in axis_values:
            role = av.discriminating_role.value
            field_name = ROLE_TO_FIELD.get(role)
            if not field_name:
                continue
            if av.confidence < 0.7:
                continue

            if role == "revision":
                has_revision = True

            fields.append(FrameField(
                field_name=field_name,
                value_normalized=av.value_raw,
                display_label=role,
                evidence_unit_ids=[],
                candidate_ids=[],
                confidence=FrameFieldConfidence.HIGH,
                reasoning=(
                    f"SubjectResolver prior ({role}, conf={av.confidence:.2f}): "
                    f"{av.rationale}"
                ),
            ))

        status = ResolverPriorStatus.CONFIRMED if has_revision else ResolverPriorStatus.ABSENT
        return fields, status

    def _link_priors_to_evidence(
        self,
        prior_fields: List[FrameField],
        units: List[EvidenceUnit],
        profile: CandidateProfile,
    ) -> None:
        """Enrichit les evidence_unit_ids des priors par token matching."""
        for field in prior_fields:
            value_tokens = set(re.split(r'\W+', field.value_normalized.lower()))
            value_tokens.discard('')
            if not value_tokens:
                continue

            # Linker aux EvidenceUnits
            for unit in units:
                unit_tokens = set(re.split(r'\W+', unit.text.lower()))
                if value_tokens.issubset(unit_tokens):
                    field.evidence_unit_ids.append(unit.unit_id)
                    if len(field.evidence_unit_ids) >= 5:
                        break

            # Linker aux candidats Layer B
            for vc in profile.value_candidates:
                vc_tokens = set(re.split(r'\W+', vc.raw_value.lower()))
                if (value_tokens == vc_tokens
                        or field.value_normalized.lower() == vc.raw_value.lower()):
                    field.candidate_ids.append(vc.candidate_id)

    def _deduplicate_priors(
        self,
        prior_fields: List[FrameField],
    ) -> List[FrameField]:
        """
        Déduplique les priors quand plusieurs axis_values mappent vers le même field_name.

        Ex: resolver retourne "2021" (revision) et "9.0" (revision) → les deux deviennent
        release_id. On garde celui qui a le plus d'evidence (evidence_unit_ids + candidate_ids).
        """
        from collections import defaultdict
        groups: dict = defaultdict(list)
        for f in prior_fields:
            groups[f.field_name].append(f)

        result = []
        for field_name, candidates in groups.items():
            if len(candidates) == 1:
                result.append(candidates[0])
                continue

            # Départager par: evidence_count + candidate_count, puis confiance
            def _score(f: FrameField) -> tuple:
                return (len(f.evidence_unit_ids), len(f.candidate_ids))

            candidates.sort(key=_score, reverse=True)
            winner = candidates[0]
            losers = candidates[1:]
            loser_vals = [f.value_normalized for f in losers]
            logger.debug(
                f"[OSMOSE:FrameBuilder] Prior dedup '{field_name}': "
                f"kept '{winner.value_normalized}' "
                f"(evidence={len(winner.evidence_unit_ids)}, candidates={len(winner.candidate_ids)}), "
                f"discarded {loser_vals}"
            )
            result.append(winner)

        return result

    # =========================================================================
    # LLM-based construction
    # =========================================================================

    def _build_with_llm(
        self,
        profile: CandidateProfile,
        units: List[EvidenceUnit],
        domain_context_prompt: Optional[str] = None,
        prior_fields: Optional[List[FrameField]] = None,
        prior_status: ResolverPriorStatus = ResolverPriorStatus.ABSENT,
    ) -> ApplicabilityFrame:
        """Construction via LLM evidence-locked."""
        from knowbase.common.llm_router import get_llm_router, TaskType

        # Construire les sections du prompt
        candidates_section = self._format_candidates(profile)
        markers_section = self._format_markers(profile)
        domain_context_section = ""
        if domain_context_prompt:
            domain_context_section = f"## Domain Context\n{domain_context_prompt}"

        resolver_prior_section = self._format_resolver_prior_section(
            prior_fields, prior_status,
        )

        prompt = FRAME_BUILDER_PROMPT.format(
            title=profile.title or "Unknown",
            primary_subject=profile.primary_subject or "Unknown",
            total_chars=profile.total_chars,
            total_units=profile.total_units,
            candidates_section=candidates_section,
            markers_section=markers_section,
            domain_context_section=domain_context_section,
            resolver_prior_section=resolver_prior_section,
        )

        router = get_llm_router()
        response = router.complete(
            task_type=TaskType.METADATA_EXTRACTION,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=2000,
            json_schema=FRAME_BUILDER_SCHEMA,
        )

        logger.debug(
            f"[OSMOSE:FrameBuilder] LLM raw response for {profile.doc_id} "
            f"(first 300 chars): {response[:300]}"
        )
        return self._parse_llm_response(response, profile)

    def _format_resolver_prior_section(
        self,
        prior_fields: Optional[List[FrameField]],
        prior_status: ResolverPriorStatus,
    ) -> str:
        """Formate la section Pre-identified Values pour le prompt LLM."""
        if prior_status == ResolverPriorStatus.CONFIRMED and prior_fields:
            lines = ["## Pre-identified Values (from document structure analysis)",
                      "The following values were identified by analyzing document title, headers, and structure:"]
            for f in prior_fields:
                lines.append(
                    f"- {f.field_name}=\"{f.value_normalized}\" "
                    f"(role={f.display_label}, confidence={f.confidence.value})"
                )
            lines.append("")
            lines.append("RULES for pre-identified values:")
            lines.append("- CONFIRM these values unless candidates clearly contradict them with strong evidence")
            lines.append("- To OVERRIDE, you MUST cite evidence_unit_ids that support the override")
            lines.append("- Do NOT invent new release_id/version fields — if pre-identified says release_id=X, use it")
            return "\n".join(lines)

        # ABSENT: pas de version identifiée
        return (
            "## Pre-identified Values\n"
            "No version/release was identified in the document structure.\n"
            "This document likely has NO specific version/release.\n"
            "Do NOT create release_id or version fields from bare decimal candidates.\n"
            "Only create release_id if a named_version candidate (e.g. \"Release X\", \"Version X\") exists\n"
            "with in_title=True OR frequency >= 3."
        )

    def _format_candidates(self, profile: CandidateProfile, max_candidates: int = 50) -> str:
        """Formate les candidats pour le prompt LLM (top N par score)."""
        if not profile.value_candidates:
            return "None found."

        # Trier par pertinence et limiter pour éviter la troncation du prompt
        def _relevance(vc: ValueCandidate) -> tuple:
            return (vc.in_title, vc.in_header_zone, vc.cooccurs_with_subject, vc.frequency)

        sorted_candidates = sorted(profile.value_candidates, key=_relevance, reverse=True)
        selected = sorted_candidates[:max_candidates]

        if len(profile.value_candidates) > max_candidates:
            logger.debug(
                f"[OSMOSE:FrameBuilder] {profile.doc_id}: trimmed candidates "
                f"from {len(profile.value_candidates)} to {max_candidates} for LLM prompt"
            )

        lines = []
        for vc in selected:
            markers_str = ", ".join(vc.nearby_markers[:3]) if vc.nearby_markers else "none"
            unit_ids_str = ", ".join(vc.unit_ids[:5])
            lines.append(
                f"- candidate_id={vc.candidate_id} | "
                f"type={vc.value_type} | "
                f"raw_value=\"{vc.raw_value}\" | "
                f"frequency={vc.frequency} | "
                f"in_title={vc.in_title} | "
                f"in_header={vc.in_header_zone} | "
                f"cooccurs_subject={vc.cooccurs_with_subject} | "
                f"nearby_markers=[{markers_str}] | "
                f"unit_ids=[{unit_ids_str}]"
            )

        return "\n".join(lines)

    def _format_markers(self, profile: CandidateProfile) -> str:
        """Formate les markers par catégorie pour le prompt LLM."""
        if not profile.markers_by_category:
            return "None found."

        lines = []
        for cat, count in sorted(profile.markers_by_category.items()):
            lines.append(f"- {cat}: {count} occurrences")
        return "\n".join(lines)

    def _parse_llm_response(
        self,
        response: str,
        profile: CandidateProfile,
    ) -> ApplicabilityFrame:
        """Parse la réponse JSON du LLM en ApplicabilityFrame."""
        # Nettoyer la réponse
        response = response.strip()
        if response.startswith("```"):
            # Retirer les fences markdown
            lines = response.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            response = "\n".join(lines)

        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            logger.warning(
                f"[OSMOSE:FrameBuilder] Failed to parse LLM JSON for {profile.doc_id}. "
                f"Raw response (first 500 chars): {response[:500]}"
            )
            return ApplicabilityFrame(
                doc_id=profile.doc_id,
                fields=[],
                unknowns=["release_id"],
                method="llm_parse_error",
            )

        # Construire les champs
        fields: List[FrameField] = []
        valid_raw_values = {vc.raw_value.lower() for vc in profile.value_candidates}

        # Index candidats par ID et par valeur (raw + canonical)
        candidates_by_id: Dict[str, ValueCandidate] = {
            vc.candidate_id: vc for vc in profile.value_candidates
        }
        canonical_to_candidates: Dict[str, List[str]] = {}
        for vc in profile.value_candidates:
            if vc.canonical_value:
                key = vc.canonical_value.lower()
                canonical_to_candidates.setdefault(key, []).append(vc.candidate_id)

        # field_names interdits (value_types bruts utilisés par erreur comme field_name)
        INVALID_FIELD_NAMES = {"numeric_identifier", "named_version", "unknown"}

        for field_data in data.get("fields", []):
            field_name = field_data.get("field_name", "unknown")
            value = field_data.get("value_normalized", "")

            # Rejeter les field_names qui sont en fait des value_types
            if field_name in INVALID_FIELD_NAMES:
                logger.debug(
                    f"[OSMOSE:FrameBuilder] LLM used value_type '{field_name}' as field_name "
                    f"— skipping (value='{value}')"
                )
                continue

            value_lower = value.lower()
            confidence_str = field_data.get("confidence", "medium")

            # 1. Vérification primaire via candidate_ids (plus fiable que string matching)
            llm_candidate_ids = field_data.get("candidate_ids", [])
            valid_cids = [cid for cid in llm_candidate_ids if cid in candidates_by_id]

            if valid_cids:
                # Le LLM a bien identifié des candidats → rattachement confirmé
                chosen_vc = candidates_by_id[valid_cids[0]]
                if chosen_vc.canonical_value:
                    value = chosen_vc.canonical_value
                logger.debug(
                    f"[OSMOSE:FrameBuilder] Value '{value}' anchored via candidate_ids {valid_cids}"
                )
            elif value_lower in valid_raw_values:
                # Fallback : match exact sur raw_value
                pass
            elif value_lower in canonical_to_candidates:
                # Fallback : match sur forme canonique
                matched_cids = canonical_to_candidates[value_lower]
                logger.debug(
                    f"[OSMOSE:FrameBuilder] LLM canonical '{value}' matched candidates {matched_cids}"
                )
            else:
                # Véritablement inventé → rejeter
                logger.debug(
                    f"[OSMOSE:FrameBuilder] LLM invented value '{value}' "
                    f"not in candidates — skipping"
                )
                continue

            # ABSTAIN : confidence=low + pas de candidate_ids valides → skip
            if confidence_str == "low" and not valid_cids:
                logger.debug(
                    f"[OSMOSE:FrameBuilder] ABSTAIN '{field_name}'='{value}' "
                    f"— low confidence without candidate anchoring"
                )
                continue

            try:
                confidence = FrameFieldConfidence(confidence_str)
            except ValueError:
                confidence = FrameFieldConfidence.MEDIUM

            fields.append(FrameField(
                field_name=field_name,
                value_normalized=value,
                display_label=field_data.get("display_label"),
                evidence_unit_ids=field_data.get("evidence_unit_ids", []),
                candidate_ids=field_data.get("candidate_ids", []),
                confidence=confidence,
                reasoning=field_data.get("reasoning"),
            ))

        # Confidence gate: "year" sans marqueur temporel → LOW
        TEMPORAL_MARKERS = {"copyright", "published", "publication", "fiscal",
                            "calendar", "effective", "dated", "issued",
                            "as of", "valid", "revision", "amendment"}
        for field in fields:
            if "year" in field.field_name.lower():
                texts_to_check = [(field.reasoning or "").lower()]
                for cid in field.candidate_ids:
                    for vc in profile.value_candidates:
                        if vc.candidate_id == cid:
                            texts_to_check.extend(
                                s.lower() for s in vc.context_snippets
                            )
                            break
                combined = " ".join(texts_to_check)
                if not any(m in combined for m in TEMPORAL_MARKERS):
                    field.confidence = FrameFieldConfidence.LOW
                    logger.debug(
                        f"[OSMOSE:FrameBuilder] ConfidenceGate: '{field.field_name}' "
                        f"degraded to LOW — no temporal marker in reasoning or context"
                    )

        unknowns = data.get("unknowns", [])

        return ApplicabilityFrame(
            doc_id=profile.doc_id,
            fields=fields,
            unknowns=unknowns,
            method="llm_evidence_locked",
        )

    # =========================================================================
    # Authority contract: merge priors with LLM/deterministic output
    # =========================================================================

    def _merge_with_priors(
        self,
        frame: ApplicabilityFrame,
        prior_fields: List[FrameField],
        prior_status: ResolverPriorStatus,
        profile: Optional[CandidateProfile] = None,
    ) -> ApplicabilityFrame:
        """
        Fusionne les priors du resolver avec le frame produit (LLM ou déterministe).

        Contrat d'autorité:
        - CONFIRMED + LLM confirme → garder HIGH
        - CONFIRMED + LLM override avec evidence → accepter MEDIUM
        - CONFIRMED + LLM override sans evidence → rejeté, garder prior
        - ABSENT → supprimer release_id sauf WEAK_GUESS légitime
        - ABSENT + tout rejeté → fallback titre numeric_identifier
        """
        if not prior_fields:
            # Mode ABSENT : supprimer tout release_id que le LLM aurait inventé
            if prior_status == ResolverPriorStatus.ABSENT:
                kept = []
                had_release_rejected = False
                for f in frame.fields:
                    if f.field_name in ("release_id", "version"):
                        if self._is_weak_guess_legitimate(f, profile):
                            f.reasoning = f"WEAK_GUESS (no resolver prior): {f.reasoning}"
                            kept.append(f)
                        else:
                            had_release_rejected = True
                            frame.validation_notes.append(
                                f"AuthorityContract: rejected '{f.field_name}={f.value_normalized}' "
                                f"— no resolver prior, insufficient evidence"
                            )
                    else:
                        kept.append(f)

                # Fallback : si tous les release_id rejetés, tenter
                # un numeric_identifier du titre comme release_id
                has_release = any(
                    f.field_name in ("release_id", "version") for f in kept
                )
                if had_release_rejected and not has_release and profile:
                    fallback = self._fallback_title_numeric(profile)
                    if fallback:
                        kept.append(fallback)
                        frame.validation_notes.append(
                            f"AuthorityContract: fallback to title numeric_identifier "
                            f"'{fallback.value_normalized}'"
                        )

                frame.fields = kept
            return frame

        # Mode CONFIRMED : fusionner
        prior_by_name = {f.field_name: f for f in prior_fields}
        merged = []
        used_priors: set = set()

        for f in frame.fields:
            if f.field_name in prior_by_name:
                prior = prior_by_name[f.field_name]
                used_priors.add(f.field_name)
                if f.value_normalized.lower() == prior.value_normalized.lower():
                    # LLM confirme → garder le prior avec HIGH
                    merged.append(prior)
                elif f.evidence_unit_ids:
                    # LLM override avec evidence → accepter MEDIUM + log
                    f.confidence = FrameFieldConfidence.MEDIUM
                    f.reasoning = (
                        f"resolver_disagreed (prior='{prior.value_normalized}'): "
                        f"{f.reasoning}"
                    )
                    frame.validation_notes.append(
                        f"AuthorityContract: resolver_disagreed on '{f.field_name}' "
                        f"prior='{prior.value_normalized}' vs llm='{f.value_normalized}'"
                    )
                    merged.append(f)
                else:
                    # LLM override SANS evidence → rejeté, garder prior
                    frame.validation_notes.append(
                        f"AuthorityContract: rejected override '{f.field_name}="
                        f"{f.value_normalized}' — no evidence, keeping prior "
                        f"'{prior.value_normalized}'"
                    )
                    merged.append(prior)
            else:
                merged.append(f)

        # Ajouter les priors non traités par le LLM
        for name, prior in prior_by_name.items():
            if name not in used_priors:
                merged.append(prior)

        frame.fields = merged
        return frame

    def _is_weak_guess_legitimate(
        self,
        field: FrameField,
        profile: Optional[CandidateProfile] = None,
    ) -> bool:
        """
        WEAK_GUESS accepté si :
        1. named_version signal (in_title ou named_version dans reasoning), OU
        2. candidat backing avec in_title=True (vérifié via le profil)

        ET confiance != LOW.
        """
        r = (field.reasoning or "").lower()
        has_named_signal = "in_title=true" in r or "named_version" in r

        # Vérifier aussi les candidats du profil pour le signal in_title
        if not has_named_signal and profile and field.candidate_ids:
            for vc in profile.value_candidates:
                if vc.candidate_id in field.candidate_ids and vc.in_title:
                    has_named_signal = True
                    break

        not_low = field.confidence != FrameFieldConfidence.LOW
        return has_named_signal and not_low

    def _fallback_title_numeric(
        self,
        profile: CandidateProfile,
    ) -> Optional[FrameField]:
        """
        Fallback quand tous les release_id sont rejetés par l'Authority Contract.

        Cherche un numeric_identifier (year) dans le titre + co-occurrent
        avec le sujet. Ex: "S4HANA 2023 Upgrade Guide" → release_id=2023.
        """
        candidates = profile.get_candidates_by_type("numeric_identifier")
        title_candidates = [
            c for c in candidates
            if c.in_title and c.cooccurs_with_subject
        ]
        if not title_candidates:
            return None

        best = max(title_candidates, key=lambda c: c.frequency)
        logger.info(
            f"[OSMOSE:FrameBuilder] AuthorityContract fallback: "
            f"title numeric_identifier '{best.raw_value}' "
            f"(freq={best.frequency}, in_title=True)"
        )
        return FrameField(
            field_name="release_id",
            value_normalized=best.raw_value,
            display_label="numeric_identifier",
            evidence_unit_ids=best.unit_ids[:5],
            candidate_ids=[best.candidate_id],
            confidence=FrameFieldConfidence.MEDIUM,
            reasoning=(
                f"AuthorityContract fallback: numeric_identifier in title "
                f"(freq={best.frequency}, cooccurs_with_subject=True)"
            ),
        )

    # =========================================================================
    # Deterministic fallback
    # =========================================================================

    def _build_deterministic(
        self,
        profile: CandidateProfile,
        units: List[EvidenceUnit],
    ) -> ApplicabilityFrame:
        """
        Fallback déterministe si LLM indisponible.

        Seuls les signaux NON ambigus sont utilisés :
        1. named_version (ex: "Release 4", "Version 2023", "Phase III") → release_id
        2. numeric_identifier dans titre + co-occurrent sujet → release_id (confiance basse)
        3. Tout le reste → unknowns (version nue "2.0" est TROP ambiguë sans LLM)
        """
        fields: List[FrameField] = []
        unknowns: List[str] = []

        # named_version UNIQUEMENT (pas "version" nu : "2.0" est trop ambigu)
        release_field = self._pick_best_candidate(
            profile, ["named_version"], "release_id"
        )

        # Si pas de named_version, tenter numeric_identifier avec signal fort
        numeric_candidates = profile.get_candidates_by_type("numeric_identifier")
        if not release_field and numeric_candidates:
            # numeric_identifier dans le titre ET co-occurrent avec le sujet
            # = signal suffisant pour release_id (ex: "ProductX 2023 Guide")
            title_subject = [
                nc for nc in numeric_candidates
                if nc.in_title and nc.cooccurs_with_subject
            ]
            if title_subject:
                best_ni = max(title_subject, key=lambda c: c.frequency)
                release_field = FrameField(
                    field_name="release_id",
                    value_normalized=best_ni.raw_value,
                    display_label="numeric_identifier",
                    evidence_unit_ids=best_ni.unit_ids[:5],
                    candidate_ids=[best_ni.candidate_id],
                    confidence=FrameFieldConfidence.LOW,
                    reasoning="deterministic: numeric_identifier in title + cooccurs with subject (no LLM)",
                )
            else:
                unknowns.append("numeric_identifier_ambiguous")
        elif numeric_candidates:
            unknowns.append("numeric_identifier_ambiguous")

        # "version" type (ex: "2.0", "3.1.4") est toujours ambigu sans LLM
        version_candidates = profile.get_candidates_by_type("version")
        if version_candidates and not release_field:
            unknowns.append("version_ambiguous")

        if release_field:
            fields.append(release_field)
        else:
            unknowns.append("release_id")

        # Edition, effective_date → unknowns par défaut en mode déterministe
        unknowns.extend(["edition", "effective_date"])

        return ApplicabilityFrame(
            doc_id=profile.doc_id,
            fields=fields,
            unknowns=unknowns,
            method="deterministic_fallback",
        )

    def _pick_best_candidate(
        self,
        profile: CandidateProfile,
        value_types: List[str],
        field_name: str,
    ) -> Optional[FrameField]:
        """
        Choisit le meilleur candidat par heuristiques.

        Priorité: in_title > in_header > high frequency > cooccurs_subject
        """
        candidates: List[ValueCandidate] = []
        for vt in value_types:
            candidates.extend(profile.get_candidates_by_type(vt))

        if not candidates:
            return None

        # Trier par priorité
        def score(vc: ValueCandidate) -> tuple:
            return (
                vc.in_title,           # Priorité 1
                vc.in_header_zone,     # Priorité 2
                vc.cooccurs_with_subject,  # Priorité 3
                vc.frequency,          # Priorité 4
            )

        candidates.sort(key=score, reverse=True)
        best = candidates[0]

        confidence = FrameFieldConfidence.MEDIUM
        if best.in_title:
            confidence = FrameFieldConfidence.HIGH
        elif best.in_header_zone and best.frequency >= 2:
            confidence = FrameFieldConfidence.HIGH
        elif not best.in_title and not best.in_header_zone:
            confidence = FrameFieldConfidence.LOW

        return FrameField(
            field_name=field_name,
            value_normalized=best.raw_value,
            display_label=best.value_type if best.value_type != "numeric_identifier" else None,
            evidence_unit_ids=best.unit_ids[:5],
            candidate_ids=[best.candidate_id],
            confidence=confidence,
            reasoning=f"deterministic: best {best.value_type} "
            f"(title={best.in_title}, header={best.in_header_zone}, "
            f"freq={best.frequency})",
        )


__all__ = [
    "FrameBuilder",
    "ResolverPriorStatus",
    "ROLE_TO_FIELD",
]
