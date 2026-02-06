# src/knowbase/claimfirst/applicability/__init__.py
"""
Module ApplicabilityFrame (Evidence-Locked).

Architecture à 4 couches pour l'extraction d'applicabilité sans hallucination:

  Layer A: EvidenceUnitSegmenter → EvidenceUnit[] (sentence-level, IDs stables)
  Layer B: CandidateMiner → CandidateProfile (markers + values + stats, 0 LLM)
  Layer C: FrameBuilder → ApplicabilityFrame (LLM evidence-locked)
  Layer D: FrameValidationPipeline → ApplicabilityFrame validé
  FrameAdapter → AxisObservation[] + DocumentContext (rétrocompat)
"""

from knowbase.claimfirst.applicability.models import (
    ApplicabilityFrame,
    CandidateProfile,
    EvidenceUnit,
    FrameField,
    FrameFieldConfidence,
    MarkerCategory,
    MarkerHit,
    ValueCandidate,
)
from knowbase.claimfirst.applicability.evidence_unit_segmenter import (
    EvidenceUnitSegmenter,
)
from knowbase.claimfirst.applicability.candidate_miner import CandidateMiner
from knowbase.claimfirst.applicability.frame_builder import FrameBuilder
from knowbase.claimfirst.applicability.validators import FrameValidationPipeline
from knowbase.claimfirst.applicability.frame_adapter import FrameAdapter

__all__ = [
    # Models
    "ApplicabilityFrame",
    "CandidateProfile",
    "EvidenceUnit",
    "FrameField",
    "FrameFieldConfidence",
    "MarkerCategory",
    "MarkerHit",
    "ValueCandidate",
    # Layers
    "EvidenceUnitSegmenter",
    "CandidateMiner",
    "FrameBuilder",
    "FrameValidationPipeline",
    "FrameAdapter",
]
