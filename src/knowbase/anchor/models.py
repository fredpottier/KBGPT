"""
Pydantic models pour Anchor Extraction V2-S2.

Modèle minimal et domain-agnostic — pas de champs spécifiques à un domaine
(version SAP, amendment number, regulatory year, etc.). Le scope est un dict
flexible pour absorber toute typologie d'anchor cross-domain.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AnchorType(str, Enum):
    """Type d'anchor extrait de la question.

    - POINT : la question vise un cadre temporel/scope ponctuel explicite
      ("dans la version 1809", "à la date 2024-01-15", "for ESC Guideline 2023")
    - RANGE : la question vise une plage d'anchors
      ("comment X a évolué entre 2018 et 2024", "depuis quand Y existe")
    - CURRENT_DEFAULT : la question n'a pas d'anchor explicite, le runtime
      doit déterminer le current via Current Resolver
      ("Quel est le mode de chiffrement de S/4HANA ?")
    """

    POINT = "point"
    RANGE = "range"
    CURRENT_DEFAULT = "current_default"


class AnchorScope(BaseModel):
    """Cadre d'applicabilité porté par l'anchor.

    Champs flexibles cross-domain :
    - version : identifiant de version, release, edition (ex: "1809", "v3.2", "Amendment 27")
    - date : date ISO si la question mentionne explicitement une date
    - range_start / range_end : bornes d'un range (peuvent être versions OU dates)
    - extraction_evidence : fragment verbatim de la question qui porte l'anchor
      (obligatoire pour POINT et RANGE — anti-hallucination, validator post-LLM)
    """

    version: Optional[str] = None
    date: Optional[str] = None
    range_start: Optional[str] = None
    range_end: Optional[str] = None
    extraction_evidence: Optional[str] = Field(
        default=None,
        description="Fragment verbatim de la question portant l'anchor. Substring de la question si non null.",
    )


class ResolvedAnchor(BaseModel):
    """Résultat de l'Anchor Extractor.

    Si anchor_type=CURRENT_DEFAULT, scope.extraction_evidence peut être null
    (pas d'anchor explicite cité par le user).
    """

    anchor_type: AnchorType
    scope: AnchorScope = Field(default_factory=AnchorScope)
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: Optional[str] = None
    extraction_method: str = "llm_evidence_locked_v2_s2"
    model_id: str = "Qwen/Qwen2.5-14B-Instruct-AWQ"


class AnchorExtractionDiagnostic(BaseModel):
    """Trace de validation pour audit/forensics."""

    raw_question: str
    resolved_anchor: ResolvedAnchor
    evidence_validated: bool
    evidence_validation_reason: Optional[str] = None
