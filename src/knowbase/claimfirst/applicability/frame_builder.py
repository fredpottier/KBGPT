# src/knowbase/claimfirst/applicability/frame_builder.py
"""
Layer C: FrameBuilder — Construction du frame d'applicabilité (LLM evidence-locked).

Le LLM reçoit uniquement:
- Titre, primary_subject, taille du document
- Candidats: candidate_id, raw_value, value_type, frequency, in_title,
  in_header, cooccurs_subject, nearby_markers, unit_ids[:5]
- Markers par catégorie
- Domain Context (optionnel)

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
from typing import Any, Dict, List, Optional

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
    ) -> ApplicabilityFrame:
        """
        Construit le frame d'applicabilité.

        Args:
            profile: Profil de candidats (sortie Layer B)
            units: EvidenceUnits (sortie Layer A)
            domain_context_prompt: Contexte domaine optionnel

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

        if self.use_llm:
            try:
                frame = self._build_with_llm(profile, units, domain_context_prompt)
                if frame and frame.fields:
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

        return self._build_deterministic(profile, units)

    # =========================================================================
    # LLM-based construction
    # =========================================================================

    def _build_with_llm(
        self,
        profile: CandidateProfile,
        units: List[EvidenceUnit],
        domain_context_prompt: Optional[str] = None,
    ) -> ApplicabilityFrame:
        """Construction via LLM evidence-locked."""
        from knowbase.common.llm_router import get_llm_router, TaskType

        # Construire les sections du prompt
        candidates_section = self._format_candidates(profile)
        markers_section = self._format_markers(profile)
        domain_context_section = ""
        if domain_context_prompt:
            domain_context_section = f"## Domain Context\n{domain_context_prompt}"

        prompt = FRAME_BUILDER_PROMPT.format(
            title=profile.title or "Unknown",
            primary_subject=profile.primary_subject or "Unknown",
            total_chars=profile.total_chars,
            total_units=profile.total_units,
            candidates_section=candidates_section,
            markers_section=markers_section,
            domain_context_section=domain_context_section,
        )

        router = get_llm_router()
        response = router.complete(
            task_type=TaskType.METADATA_EXTRACTION,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=2000,
        )

        logger.debug(
            f"[OSMOSE:FrameBuilder] LLM raw response for {profile.doc_id} "
            f"(first 300 chars): {response[:300]}"
        )
        return self._parse_llm_response(response, profile)

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
        valid_candidate_ids = {vc.candidate_id for vc in profile.value_candidates}
        valid_raw_values = {vc.raw_value.lower() for vc in profile.value_candidates}

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

            # Vérifier que la valeur existe dans les candidats
            if value.lower() not in valid_raw_values:
                logger.debug(
                    f"[OSMOSE:FrameBuilder] LLM invented value '{value}' "
                    f"not in candidates — skipping"
                )
                continue

            confidence_str = field_data.get("confidence", "medium")
            try:
                confidence = FrameFieldConfidence(confidence_str)
            except ValueError:
                confidence = FrameFieldConfidence.MEDIUM

            fields.append(FrameField(
                field_name=field_data.get("field_name", "unknown"),
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
]
