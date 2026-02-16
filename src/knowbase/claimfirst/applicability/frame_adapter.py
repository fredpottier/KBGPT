# src/knowbase/claimfirst/applicability/frame_adapter.py
"""
FrameAdapter — Rétrocompatibilité entre ApplicabilityFrame et le système existant.

Conversions:
- Frame → List[AxisObservation] (réutilise AxisOrderInferrer)
- Frame → List[ApplicabilityAxis] (via create_axes_from_observations)
- Frame → mise à jour DocumentContext.axis_values et .applicable_axes
"""

from __future__ import annotations

import logging
from typing import List, Optional

from knowbase.claimfirst.applicability.models import (
    ApplicabilityFrame,
    CandidateProfile,
    FrameField,
    FrameFieldConfidence,
    ValueCandidate,
)
from knowbase.claimfirst.axes.axis_detector import AxisObservation
from knowbase.claimfirst.axes.axis_order_inferrer import AxisOrderInferrer
from knowbase.claimfirst.models.applicability_axis import (
    ApplicabilityAxis,
    OrderingConfidence,
)
from knowbase.claimfirst.models.axis_value import EvidenceSpan
from knowbase.claimfirst.models.document_context import DocumentContext

logger = logging.getLogger(__name__)


# Mapping de confiance Frame → AxisObservation reliability
_CONFIDENCE_TO_RELIABILITY = {
    FrameFieldConfidence.HIGH: "explicit_text",
    FrameFieldConfidence.MEDIUM: "explicit_text",
    FrameFieldConfidence.LOW: "inferred",
    FrameFieldConfidence.ABSENT: "inferred",
}


class FrameAdapter:
    """
    Adapte un ApplicabilityFrame vers les structures legacy du pipeline.
    """

    def __init__(self) -> None:
        self.order_inferrer = AxisOrderInferrer()

    def frame_to_observations(
        self,
        frame: ApplicabilityFrame,
        profile: Optional[CandidateProfile] = None,
    ) -> List[AxisObservation]:
        """
        Convertit un ApplicabilityFrame en AxisObservation[] (format legacy).

        Args:
            frame: ApplicabilityFrame validé
            profile: CandidateProfile optionnel pour résolution canonique

        Returns:
            Liste d'AxisObservation compatibles avec le pipeline existant
        """
        candidates_by_id = {}
        if profile:
            candidates_by_id = {vc.candidate_id: vc for vc in profile.value_candidates}

        observations: List[AxisObservation] = []

        for field in frame.fields:
            # Créer un EvidenceSpan depuis les unit_ids
            evidence_spans = []
            for uid in field.evidence_unit_ids[:3]:
                evidence_spans.append(EvidenceSpan(
                    passage_id=None,
                    snippet_ref=f"unit:{uid}",
                ))

            reliability = _CONFIDENCE_TO_RELIABILITY.get(
                field.confidence, "explicit_text"
            )

            # Résoudre la valeur canonique via candidat
            extracted_value = field.value_normalized
            for cid in field.candidate_ids:
                vc = candidates_by_id.get(cid)
                if vc and vc.canonical_value:
                    extracted_value = vc.canonical_value
                    break

            obs = AxisObservation(
                axis_key=field.field_name,
                axis_display_name=field.display_label,
                values_extracted=[extracted_value],
                evidence_spans=evidence_spans,
                orderability_confidence=OrderingConfidence.UNKNOWN,
                reliability=reliability,
            )
            observations.append(obs)

        return observations

    def frame_to_axes(
        self,
        frame: ApplicabilityFrame,
        tenant_id: str,
        doc_id: str,
        profile: Optional[CandidateProfile] = None,
    ) -> List[ApplicabilityAxis]:
        """
        Convertit un ApplicabilityFrame en ApplicabilityAxis[].

        Utilise AxisOrderInferrer pour inférer l'ordonnabilité.

        Args:
            frame: ApplicabilityFrame validé
            tenant_id: Tenant ID
            doc_id: Document ID
            profile: CandidateProfile optionnel pour résolution canonique

        Returns:
            Liste d'ApplicabilityAxis
        """
        observations = self.frame_to_observations(frame, profile=profile)

        if not observations:
            return []

        axes: List[ApplicabilityAxis] = []

        for obs in observations:
            # Créer l'axe
            axis = ApplicabilityAxis.create_new(
                tenant_id=tenant_id,
                axis_key=obs.axis_key,
                axis_display_name=obs.axis_display_name,
                doc_id=doc_id,
            )

            # Ajouter les valeurs
            for v in obs.values_extracted:
                axis.add_value(v, doc_id)

            # Inférer l'ordre
            if len(axis.known_values) >= 2:
                order_result = self.order_inferrer.infer_order(
                    axis_key=axis.axis_key,
                    values=axis.known_values,
                )
                axis.is_orderable = order_result.is_orderable
                axis.order_type = order_result.order_type
                axis.ordering_confidence = order_result.confidence
                axis.value_order = order_result.inferred_order

            axes.append(axis)

        return axes

    def update_document_context(
        self,
        frame: ApplicabilityFrame,
        doc_context: DocumentContext,
        profile: Optional[CandidateProfile] = None,
    ) -> None:
        """
        Met à jour le DocumentContext avec les valeurs du frame.

        Args:
            frame: ApplicabilityFrame validé
            doc_context: DocumentContext à mettre à jour (modifié in-place)
            profile: CandidateProfile optionnel pour résolution canonique
        """
        candidates_by_id = {}
        if profile:
            candidates_by_id = {vc.candidate_id: vc for vc in profile.value_candidates}

        for field in frame.fields:
            reliability = _CONFIDENCE_TO_RELIABILITY.get(
                field.confidence, "explicit_text"
            )

            # Construire le snippet_ref depuis les unit_ids
            snippet_ref = "unknown"
            if field.evidence_unit_ids:
                snippet_ref = f"units:{','.join(field.evidence_unit_ids[:3])}"

            # Résoudre la forme canonique via le candidat choisi
            scalar = field.value_normalized
            display = None
            for cid in field.candidate_ids:
                vc = candidates_by_id.get(cid)
                if vc and vc.canonical_value:
                    scalar = vc.canonical_value
                    display = vc.raw_value
                    break

            doc_context.axis_values[field.field_name] = {
                "value_type": "scalar",
                "scalar_value": scalar,
                "display_value": display,
                "evidence_passage_id": None,
                "evidence_snippet_ref": snippet_ref,
                "reliability": reliability,
            }

            if field.field_name not in doc_context.applicable_axes:
                doc_context.applicable_axes.append(field.field_name)


__all__ = [
    "FrameAdapter",
]
