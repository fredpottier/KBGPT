"""
Segment-Level Relation Extractor - Pass 2 Architecture

Extraction de relations au niveau SEGMENT (pas chunk) selon ADR 2024-12-30.
Remplace l'extraction chunk-aware de Pass 1 (Option A') par une approche
plus efficace en Pass 2.

Architecture:
1. SCORING: Sélectionner segments pertinents selon scoring formula
2. EXTRACT: Appel LLM par segment avec 12 predicats du set fermé
3. ANCHOR: Mapper relations extraites vers chunks via fuzzy match

Predicats du set fermé (12):
- defines, requires, enables, prevents, causes, applies_to
- part_of, depends_on, mitigates, conflicts_with, example_of, governed_by

ADR: doc/ongoing/ADR_HYBRID_ANCHOR_MODEL.md (Addendum 2024-12-30)

Author: OSMOSE Phase 2
Date: 2024-12-30
"""

import logging
import asyncio
import re
import json
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from knowbase.common.llm_router import get_llm_router, TaskType
from knowbase.relations.types import RelationType, RawAssertionFlags
from knowbase.semantic.anchor_resolver import fuzzy_match_in_text

logger = logging.getLogger(__name__)


# =============================================================================
# Constants: 12 Core Predicates (Set Fermé)
# =============================================================================

CORE_PREDICATES = [
    "defines",        # A defines B (définition)
    "requires",       # A requires B (dépendance dure)
    "enables",        # A enables B (facilite)
    "prevents",       # A prevents B (bloque)
    "causes",         # A causes B (causalité)
    "applies_to",     # A applies_to B (scope)
    "part_of",        # A part_of B (composition)
    "depends_on",     # A depends_on B (dépendance souple)
    "mitigates",      # A mitigates B (atténue)
    "conflicts_with", # A conflicts_with B (conflit)
    "example_of",     # A example_of B (instance)
    "governed_by",    # A governed_by B (régulation)
]

# Mapping predicat → RelationType (pour persistance)
PREDICATE_TO_RELATION_TYPE = {
    "defines": RelationType.DEFINES,
    "requires": RelationType.REQUIRES,
    "enables": RelationType.ENABLES,
    "prevents": RelationType.PREVENTS,
    "causes": RelationType.CAUSES,
    "applies_to": RelationType.APPLIES_TO,
    "part_of": RelationType.PART_OF,
    "depends_on": RelationType.REQUIRES,  # Alias
    "mitigates": RelationType.MITIGATES,
    "conflicts_with": RelationType.CONFLICTS_WITH,
    "example_of": RelationType.EXAMPLE_OF,
    "governed_by": RelationType.GOVERNED_BY,
}


# =============================================================================
# Scoring Configuration (ADR Addendum)
# =============================================================================

@dataclass
class SegmentScoringConfig:
    """Configuration pour le scoring des segments."""

    # Poids du scoring
    anchor_density_weight: float = 0.4
    concept_diversity_weight: float = 0.3
    section_weight: float = 0.3

    # Seuils
    min_anchor_density: float = 0.02  # 2% du texte
    min_concept_diversity: int = 3     # Au moins 3 concepts distincts
    min_score: float = 0.3             # Score minimum pour traitement

    # Sections exclues
    excluded_sections: List[str] = field(default_factory=lambda: [
        "intro", "introduction",
        "toc", "table_of_contents", "sommaire",
        "about", "about_us", "about_the_author",
        "appendix", "annexe",
        "references", "bibliography",
    ])

    # Section weights (bonus)
    section_bonus: Dict[str, float] = field(default_factory=lambda: {
        "methodology": 1.5,
        "results": 1.3,
        "analysis": 1.3,
        "discussion": 1.2,
        "findings": 1.3,
        "requirements": 1.4,
        "specifications": 1.4,
        "architecture": 1.5,
        "implementation": 1.3,
    })


@dataclass
class ScoredSegment:
    """Segment avec son score de pertinence."""

    segment_id: str
    text: str
    section_id: Optional[str] = None
    char_offset: int = 0

    # Métriques de scoring
    anchor_density: float = 0.0
    concept_diversity: int = 0
    section_weight: float = 1.0

    # Score final
    score: float = 0.0

    # Concepts présents dans le segment
    concept_ids: List[str] = field(default_factory=list)
    concept_labels: List[str] = field(default_factory=list)


@dataclass
class ExtractedRelation:
    """Relation extraite d'un segment."""

    subject_label: str
    object_label: str
    predicate: str
    evidence: str
    confidence: float = 0.7

    # Résolution vers concepts
    subject_concept_id: Optional[str] = None
    object_concept_id: Optional[str] = None

    # Ancrage vers chunk
    chunk_id: Optional[str] = None
    evidence_span: Optional[Tuple[int, int]] = None


@dataclass
class SegmentExtractionResult:
    """Résultat d'extraction pour un segment."""

    segment_id: str
    relations: List[ExtractedRelation] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Pass2ExtractionResult:
    """Résultat complet de l'extraction Pass 2."""

    document_id: str
    total_segments: int = 0
    segments_processed: int = 0
    segments_skipped: int = 0

    relations: List[ExtractedRelation] = field(default_factory=list)

    # Stats détaillées
    stats: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Segment Relation Extractor
# =============================================================================

class SegmentRelationExtractor:
    """
    Extracteur de relations au niveau segment (Pass 2).

    Pipeline:
    1. Score segments selon anchor_density, concept_diversity, section_type
    2. Filtre segments avec score >= min_score
    3. Extrait relations via LLM avec 12 predicats
    4. Résout subject/object vers concept_ids
    5. Ancre evidence vers chunks
    """

    def __init__(
        self,
        tenant_id: str = "default",
        scoring_config: Optional[SegmentScoringConfig] = None,
        max_concurrent: int = 5
    ):
        """
        Initialise l'extracteur.

        Args:
            tenant_id: ID tenant
            scoring_config: Configuration scoring (utilise défaut si None)
            max_concurrent: Max appels LLM en parallèle
        """
        self.tenant_id = tenant_id
        self.config = scoring_config or SegmentScoringConfig()
        self.max_concurrent = max_concurrent
        self.llm_router = get_llm_router()

        logger.info(
            f"[OSMOSE:Pass2:SegmentExtractor] Initialized "
            f"(min_score={self.config.min_score}, max_concurrent={max_concurrent})"
        )

    def score_segments(
        self,
        segments: List[Dict[str, Any]],
        concept_anchors: Dict[str, List[str]]  # concept_id → [segment_ids]
    ) -> List[ScoredSegment]:
        """
        Score les segments selon la formule ADR.

        Formula:
        score = (anchor_density × 0.4) + (concept_diversity × 0.3) + section_weight × 0.3

        Args:
            segments: Liste de segments avec text, segment_id, section_id
            concept_anchors: Mapping concept_id → segment_ids où il est ancré

        Returns:
            Liste de ScoredSegment triée par score décroissant
        """
        scored = []

        # Inverser le mapping: segment_id → [concept_ids]
        segment_concepts: Dict[str, List[str]] = {}
        for concept_id, seg_ids in concept_anchors.items():
            for seg_id in seg_ids:
                if seg_id not in segment_concepts:
                    segment_concepts[seg_id] = []
                segment_concepts[seg_id].append(concept_id)

        for seg in segments:
            seg_id = seg.get("segment_id", "")
            text = seg.get("text", "")
            section_id = seg.get("section_id", "")

            # Vérifier exclusion section
            section_lower = (section_id or "").lower()
            if any(excl in section_lower for excl in self.config.excluded_sections):
                logger.debug(f"[OSMOSE:Pass2:Scoring] Excluded section: {section_id}")
                continue

            # Calculer métriques
            text_len = len(text)
            if text_len == 0:
                continue

            # Anchor density: proportion du texte couverte par les anchors
            # Approximation: nombre de concepts × longueur moyenne label / text_len
            concepts_in_seg = segment_concepts.get(seg_id, [])
            # Estimation: ~20 chars par label en moyenne
            anchor_chars = len(concepts_in_seg) * 20
            anchor_density = min(anchor_chars / text_len, 1.0)

            # Concept diversity
            concept_diversity = len(set(concepts_in_seg))

            # Section weight
            section_weight = 1.0
            for key, bonus in self.config.section_bonus.items():
                if key in section_lower:
                    section_weight = bonus
                    break

            # Vérifier seuils minimaux
            if anchor_density < self.config.min_anchor_density:
                continue
            if concept_diversity < self.config.min_concept_diversity:
                continue

            # Calculer score final
            score = (
                anchor_density * self.config.anchor_density_weight +
                (concept_diversity / 10) * self.config.concept_diversity_weight +  # Normalize to ~1
                section_weight * self.config.section_weight
            )

            scored_seg = ScoredSegment(
                segment_id=seg_id,
                text=text,
                section_id=section_id,
                char_offset=seg.get("char_offset", 0),
                anchor_density=anchor_density,
                concept_diversity=concept_diversity,
                section_weight=section_weight,
                score=score,
                concept_ids=concepts_in_seg,
                concept_labels=[]  # Rempli plus tard si nécessaire
            )

            if score >= self.config.min_score:
                scored.append(scored_seg)

        # Trier par score décroissant
        scored.sort(key=lambda s: s.score, reverse=True)

        logger.info(
            f"[OSMOSE:Pass2:Scoring] Scored {len(scored)} segments "
            f"(excluded {len(segments) - len(scored)} below threshold)"
        )

        return scored

    async def extract_from_document(
        self,
        document_id: str,
        segments: List[Dict[str, Any]],
        concept_anchors: Dict[str, List[str]],
        concept_catalogue: List[Dict[str, Any]],
        max_segments: int = 25
    ) -> Pass2ExtractionResult:
        """
        Extrait les relations de tous les segments pertinents d'un document.

        Args:
            document_id: ID du document
            segments: Liste des segments du document
            concept_anchors: Mapping concept_id → segment_ids
            concept_catalogue: Catalogue des concepts (id, label, type)
            max_segments: Max segments à traiter (top-N par score)

        Returns:
            Pass2ExtractionResult avec toutes les relations
        """
        result = Pass2ExtractionResult(
            document_id=document_id,
            total_segments=len(segments)
        )

        # 1. Score les segments
        scored_segments = self.score_segments(segments, concept_anchors)

        # 2. Limiter aux top-N
        segments_to_process = scored_segments[:max_segments]
        result.segments_skipped = len(scored_segments) - len(segments_to_process)

        if not segments_to_process:
            logger.info(
                f"[OSMOSE:Pass2:SegmentExtractor] No segments to process for {document_id}"
            )
            return result

        logger.info(
            f"[OSMOSE:Pass2:SegmentExtractor] Processing {len(segments_to_process)} segments "
            f"(skipped {result.segments_skipped} lower-scored)"
        )

        # 3. Construire index concept_label → concept_id pour résolution
        label_to_id: Dict[str, str] = {}
        for c in concept_catalogue:
            label = c.get("label", "").lower()
            cid = c.get("id") or c.get("canonical_id")
            if label and cid:
                label_to_id[label] = cid

        # 4. Extraire en parallèle
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def extract_segment(scored_seg: ScoredSegment) -> SegmentExtractionResult:
            async with semaphore:
                return await self._extract_from_segment(
                    scored_seg=scored_seg,
                    concept_catalogue=concept_catalogue,
                    label_to_id=label_to_id
                )

        tasks = [extract_segment(seg) for seg in segments_to_process]
        segment_results = await asyncio.gather(*tasks, return_exceptions=True)

        # 5. Agréger les résultats
        for seg_result in segment_results:
            if isinstance(seg_result, Exception):
                logger.error(f"[OSMOSE:Pass2:SegmentExtractor] Segment error: {seg_result}")
                continue

            result.relations.extend(seg_result.relations)
            result.segments_processed += 1

        result.stats = {
            "total_relations": len(result.relations),
            "segments_scored": len(scored_segments),
            "segments_processed": result.segments_processed,
            "segments_skipped": result.segments_skipped,
        }

        logger.info(
            f"[OSMOSE:Pass2:SegmentExtractor] ✅ Extraction complete: "
            f"{len(result.relations)} relations from {result.segments_processed} segments"
        )

        return result

    async def _extract_from_segment(
        self,
        scored_seg: ScoredSegment,
        concept_catalogue: List[Dict[str, Any]],
        label_to_id: Dict[str, str]
    ) -> SegmentExtractionResult:
        """
        Extrait les relations d'un segment via LLM.

        Args:
            scored_seg: Segment scoré
            concept_catalogue: Catalogue complet pour résolution
            label_to_id: Mapping label → concept_id

        Returns:
            SegmentExtractionResult
        """
        result = SegmentExtractionResult(segment_id=scored_seg.segment_id)

        # Construire le catalogue filtré (concepts présents dans le segment)
        segment_concepts = [
            c for c in concept_catalogue
            if c.get("id") in scored_seg.concept_ids or
               c.get("canonical_id") in scored_seg.concept_ids
        ]

        if len(segment_concepts) < 2:
            # Pas assez de concepts pour des relations
            return result

        # Construire le prompt
        prompt = self._build_extraction_prompt(
            text=scored_seg.text,
            concepts=segment_concepts
        )

        try:
            response = await self.llm_router.acomplete(
                task_type=TaskType.KNOWLEDGE_EXTRACTION,
                messages=[
                    {"role": "system", "content": SEGMENT_EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
                max_tokens=2000
            )

            # Parser la réponse
            relations_raw = self._parse_extraction_response(response)

            # Résoudre et créer les relations
            for rel_data in relations_raw:
                relation = self._resolve_relation(
                    rel_data=rel_data,
                    label_to_id=label_to_id,
                    segment_text=scored_seg.text
                )
                if relation:
                    result.relations.append(relation)

            result.stats = {
                "concepts_in_segment": len(segment_concepts),
                "relations_extracted": len(relations_raw),
                "relations_resolved": len(result.relations),
            }

        except Exception as e:
            logger.error(
                f"[OSMOSE:Pass2:SegmentExtractor] Failed for segment {scored_seg.segment_id}: {e}"
            )
            result.stats["error"] = str(e)

        return result

    def _build_extraction_prompt(
        self,
        text: str,
        concepts: List[Dict[str, Any]]
    ) -> str:
        """Construit le prompt d'extraction."""

        # Formater le catalogue de concepts
        concept_lines = []
        for c in concepts[:50]:  # Limiter à 50 concepts
            cid = c.get("id") or c.get("canonical_id")
            label = c.get("label") or c.get("canonical_name")
            ctype = c.get("type_fine") or c.get("type_heuristic") or "abstract"
            concept_lines.append(f"- [{cid}] {label} ({ctype})")

        concepts_str = "\n".join(concept_lines)

        return f"""## SEGMENT TEXT
{text[:4000]}

## CONCEPTS IN SEGMENT
{concepts_str}

## TASK
Extract semantic relations between the concepts listed above.
Use ONLY predicates from: {', '.join(CORE_PREDICATES)}

For each relation:
1. Identify subject and object concepts from the list
2. Choose the most appropriate predicate
3. Extract the evidence quote from the text
4. Estimate confidence (0.6-1.0)

Return JSON with "relations" array."""

    def _parse_extraction_response(self, response: str) -> List[Dict[str, Any]]:
        """Parse la réponse LLM."""
        try:
            # Chercher JSON
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if not json_match:
                return []

            data = json.loads(json_match.group(0))
            relations = data.get("relations", [])

            # Valider structure minimale
            valid = []
            for rel in relations:
                if all(k in rel for k in ["subject", "object", "predicate"]):
                    # Normaliser predicate
                    pred = rel["predicate"].lower().strip().replace(" ", "_")
                    if pred in CORE_PREDICATES or pred.replace("_", "") in [p.replace("_", "") for p in CORE_PREDICATES]:
                        valid.append({
                            "subject": rel["subject"],
                            "object": rel["object"],
                            "predicate": pred,
                            "evidence": rel.get("evidence", ""),
                            "confidence": float(rel.get("confidence", 0.7))
                        })

            return valid

        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"[OSMOSE:Pass2:SegmentExtractor] JSON parse error: {e}")
            return []

    def _resolve_relation(
        self,
        rel_data: Dict[str, Any],
        label_to_id: Dict[str, str],
        segment_text: str
    ) -> Optional[ExtractedRelation]:
        """Résout une relation vers des concept_ids."""

        subject = rel_data.get("subject", "")
        obj = rel_data.get("object", "")

        # Résoudre subject
        subject_id = None
        subject_lower = subject.lower()
        if subject_lower in label_to_id:
            subject_id = label_to_id[subject_lower]
        else:
            # Fuzzy match
            for label, cid in label_to_id.items():
                if label in subject_lower or subject_lower in label:
                    subject_id = cid
                    break

        # Résoudre object
        object_id = None
        object_lower = obj.lower()
        if object_lower in label_to_id:
            object_id = label_to_id[object_lower]
        else:
            for label, cid in label_to_id.items():
                if label in object_lower or object_lower in label:
                    object_id = cid
                    break

        # Les deux doivent être résolus
        if not subject_id or not object_id:
            logger.debug(
                f"[OSMOSE:Pass2:SegmentExtractor] Unresolved: {subject} → {obj}"
            )
            return None

        # Localiser l'evidence dans le texte
        evidence = rel_data.get("evidence", "")
        evidence_span = None
        if evidence:
            match_result = fuzzy_match_in_text(evidence, segment_text)
            if match_result:
                evidence_span = (match_result["start"], match_result["end"])

        return ExtractedRelation(
            subject_label=subject,
            object_label=obj,
            predicate=rel_data.get("predicate", ""),
            evidence=evidence,
            confidence=rel_data.get("confidence", 0.7),
            subject_concept_id=subject_id,
            object_concept_id=object_id,
            evidence_span=evidence_span
        )


# =============================================================================
# System Prompt
# =============================================================================

SEGMENT_EXTRACTION_SYSTEM_PROMPT = """You are OSMOSE Relation Extractor (Pass 2).

Your task is to extract semantic relations between concepts within a document segment.

## Available Predicates (CLOSED SET - USE ONLY THESE)
- defines: A defines B (definitional relationship)
- requires: A requires B (hard dependency)
- enables: A enables B (facilitation)
- prevents: A prevents B (blocking)
- causes: A causes B (causality)
- applies_to: A applies_to B (scope/applicability)
- part_of: A part_of B (composition)
- depends_on: A depends_on B (soft dependency)
- mitigates: A mitigates B (risk reduction)
- conflicts_with: A conflicts_with B (incompatibility)
- example_of: A example_of B (instance)
- governed_by: A governed_by B (regulation)

## Output Format
```json
{
  "relations": [
    {
      "subject": "Concept A Label",
      "object": "Concept B Label",
      "predicate": "requires",
      "evidence": "exact quote from text supporting this relation",
      "confidence": 0.85
    }
  ]
}
```

## Rules
1. Use ONLY concepts from the provided list
2. Use ONLY predicates from the closed set above
3. Extract exact evidence quotes from the text
4. Confidence must be between 0.6 and 1.0
5. Only include relations clearly supported by the text
6. Prefer more specific predicates (requires > depends_on)
7. No self-relations (subject must differ from object)"""


# =============================================================================
# Factory Pattern
# =============================================================================

_extractor_instance: Optional[SegmentRelationExtractor] = None


def get_segment_relation_extractor(
    tenant_id: str = "default"
) -> SegmentRelationExtractor:
    """
    Récupère l'instance singleton de l'extracteur.

    Args:
        tenant_id: ID tenant

    Returns:
        SegmentRelationExtractor instance
    """
    global _extractor_instance

    if _extractor_instance is None:
        _extractor_instance = SegmentRelationExtractor(tenant_id=tenant_id)

    return _extractor_instance
