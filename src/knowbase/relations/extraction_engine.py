# Phase 2 OSMOSE - Relation Extraction Engine
# Semaines 14-15 : Core extraction engine

import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

from knowbase.relations.types import (
    RelationType,
    TypedRelation,
    RelationMetadata,
    ExtractionMethod,
    RelationStrength,
    RelationStatus,
    RelationExtractionResult
)

logger = logging.getLogger(__name__)


class RelationExtractionEngine:
    """
    Moteur d'extraction de relations typées entre concepts.

    Architecture hybride :
    - Pattern-based extraction (regex + spaCy)
    - LLM-assisted classification (validation/enhancement)
    - Confidence scoring multi-critères

    Phase 2 OSMOSE - Semaines 14-15
    """

    def __init__(
        self,
        strategy: str = "llm_first",  # "llm_first", "hybrid", "pattern_only"
        llm_model: str = "gpt-4o-mini",
        min_confidence: float = 0.60,
        language: str = "EN"
    ):
        """
        Initialise le moteur d'extraction.

        Args:
            strategy: Stratégie extraction
                - "llm_first": LLM principal, patterns fallback (RECOMMANDÉ)
                - "hybrid": Patterns + LLM validation
                - "pattern_only": Patterns seuls (déconseillé)
            llm_model: Modèle LLM (default: gpt-4o-mini - bon rapport qualité/prix)
            min_confidence: Seuil minimum confidence pour accepter relation
            language: Langue principale documents (EN, FR, DE, ES)
        """
        self.strategy = strategy
        self.llm_model = llm_model
        self.min_confidence = min_confidence
        self.language = language

        # Composants extraction (lazy loading)
        self._pattern_matcher = None
        self._llm_extractor = None
        self._llm_router = None

        logger.info(
            f"[OSMOSE:RelationExtraction] Engine initialized "
            f"(strategy={strategy}, llm_model={llm_model}, "
            f"min_conf={min_confidence}, lang={language})"
        )

    def extract_relations(
        self,
        concepts: List[Dict[str, Any]],
        full_text: str,
        document_id: str,
        document_name: str,
        chunk_ids: Optional[List[str]] = None
    ) -> RelationExtractionResult:
        """
        Extraire relations typées entre concepts d'un document.

        Pipeline :
        1. Pattern-based extraction (regex + spaCy)
        2. LLM-assisted validation/classification
        3. Confidence scoring
        4. Filtering (min_confidence threshold)

        Args:
            concepts: Liste concepts canoniques du document
                [
                    {
                        "concept_id": "canonical-123",
                        "canonical_name": "SAP S/4HANA",
                        "surface_forms": ["S/4HANA", "S4HANA"],
                        "concept_type": "PRODUCT"
                    },
                    ...
                ]
            full_text: Texte complet du document
            document_id: ID document source
            document_name: Nom document source
            chunk_ids: IDs chunks Qdrant (optionnel, pour traçabilité)

        Returns:
            RelationExtractionResult avec relations extraites
        """
        start_time = datetime.utcnow()

        logger.info(
            f"[OSMOSE:RelationExtraction] Extracting relations from {document_name} "
            f"({len(concepts)} concepts, {len(full_text)} chars)"
        )

        # Étape 1: Extraction selon stratégie
        if self.strategy == "llm_first":
            # LLM-first: Extraction principale via LLM
            all_relations = self._extract_with_llm(
                concepts=concepts,
                full_text=full_text,
                document_id=document_id,
                document_name=document_name,
                chunk_ids=chunk_ids
            )
            logger.info(
                f"[OSMOSE:RelationExtraction] LLM extraction: "
                f"{len(all_relations)} relations"
            )

        elif self.strategy == "hybrid":
            # Hybrid: Patterns + LLM validation
            pattern_relations = self._extract_with_patterns(
                concepts=concepts,
                full_text=full_text,
                document_id=document_id,
                document_name=document_name,
                chunk_ids=chunk_ids
            )
            logger.info(
                f"[OSMOSE:RelationExtraction] Pattern-based: "
                f"{len(pattern_relations)} candidates"
            )

            # LLM valide les patterns
            all_relations = self._enhance_with_llm(
                candidate_relations=pattern_relations,
                full_text=full_text
            )
            logger.info(
                f"[OSMOSE:RelationExtraction] LLM-enhanced: "
                f"{len(all_relations)} relations"
            )

        else:  # pattern_only
            # Pattern-only (déconseillé)
            all_relations = self._extract_with_patterns(
                concepts=concepts,
                full_text=full_text,
                document_id=document_id,
                document_name=document_name,
                chunk_ids=chunk_ids
            )
            logger.warning(
                "[OSMOSE:RelationExtraction] Pattern-only mode (déconseillé) - "
                f"{len(all_relations)} relations"
            )

        # Étape 3: Filtering par confidence
        filtered_relations = [
            rel for rel in all_relations
            if rel.metadata.confidence >= self.min_confidence
        ]

        logger.info(
            f"[OSMOSE:RelationExtraction] Filtered (conf≥{self.min_confidence}): "
            f"{len(filtered_relations)}/{len(all_relations)} relations"
        )

        # Étape 4: Statistiques
        extraction_time = (datetime.utcnow() - start_time).total_seconds()

        relations_by_type = self._count_by_type(filtered_relations)
        extraction_method_stats = self._count_by_method(filtered_relations)

        result = RelationExtractionResult(
            document_id=document_id,
            relations=filtered_relations,
            extraction_time_seconds=extraction_time,
            total_relations_extracted=len(filtered_relations),
            relations_by_type=relations_by_type,
            extraction_method_stats=extraction_method_stats
        )

        logger.info(
            f"[OSMOSE:RelationExtraction] ✅ Extracted {len(filtered_relations)} "
            f"relations in {extraction_time:.2f}s"
        )

        return result

    def _extract_with_patterns(
        self,
        concepts: List[Dict[str, Any]],
        full_text: str,
        document_id: str,
        document_name: str,
        chunk_ids: Optional[List[str]] = None
    ) -> List[TypedRelation]:
        """
        Extraction pattern-based (regex + spaCy dependency parsing).

        Stratégies :
        - Regex patterns multilingues (EN, FR, DE, ES)
        - spaCy dependency parsing (Subject-Verb-Object triplets)
        - Co-occurrence scoring (concepts proches → candidates)

        Returns:
            Liste relations candidates (confidence initiale 0.5-0.8)
        """
        logger.debug("[OSMOSE:RelationExtraction] Pattern extraction (J4-J7)")

        return self.pattern_matcher.extract_relations(
            concepts=concepts,
            full_text=full_text,
            document_id=document_id,
            document_name=document_name,
            chunk_ids=chunk_ids
        )

    def _enhance_with_llm(
        self,
        candidate_relations: List[TypedRelation],
        full_text: str
    ) -> List[TypedRelation]:
        """
        Enhancement LLM-assisted des relations candidates.

        LLM Tasks :
        - Valider relation type (pattern peut se tromper)
        - Ajuster confidence score
        - Extraire metadata spécifique (breaking_changes, etc.)

        Returns:
            Relations avec confidence ajustée et metadata enrichie
        """
        # TODO J8-J10: Implémenter LLM classification
        logger.debug("[OSMOSE:RelationExtraction] LLM enhancement (TODO J8-J10)")
        return candidate_relations

    def _count_by_type(
        self,
        relations: List[TypedRelation]
    ) -> Dict[RelationType, int]:
        """Compter relations par type."""
        counts = {}
        for rel in relations:
            rel_type = rel.relation_type
            counts[rel_type] = counts.get(rel_type, 0) + 1
        return counts

    def _count_by_method(
        self,
        relations: List[TypedRelation]
    ) -> Dict[ExtractionMethod, int]:
        """Compter relations par méthode extraction."""
        counts = {}
        for rel in relations:
            method = rel.metadata.extraction_method
            counts[method] = counts.get(method, 0) + 1
        return counts

    # ==================================================================
    # Pattern Matching Components (J4-J7)
    # ==================================================================

    @property
    def pattern_matcher(self):
        """Lazy load PatternMatcher (J4-J7)."""
        if self._pattern_matcher is None:
            from knowbase.relations.pattern_matcher import PatternMatcher
            self._pattern_matcher = PatternMatcher(languages=["EN", "FR", "DE", "ES"])
            logger.info("[OSMOSE:RelationExtraction] PatternMatcher loaded")
        return self._pattern_matcher

    # ==================================================================
    # LLM Extraction Components (LLM-First)
    # ==================================================================

    @property
    def llm_extractor(self):
        """Lazy load LLMRelationExtractor (LLM-first)."""
        if self._llm_extractor is None:
            from knowbase.relations.llm_relation_extractor import LLMRelationExtractor
            from knowbase.common.llm_router import LLMRouter

            if self._llm_router is None:
                self._llm_router = LLMRouter()

            self._llm_extractor = LLMRelationExtractor(
                llm_router=self._llm_router,
                model=self.llm_model
            )
            logger.info("[OSMOSE:RelationExtraction] LLMRelationExtractor loaded")
        return self._llm_extractor

    def _extract_with_llm(
        self,
        concepts: List[Dict[str, Any]],
        full_text: str,
        document_id: str,
        document_name: str,
        chunk_ids: Optional[List[str]] = None
    ) -> List[TypedRelation]:
        """
        Extraction LLM-first (gpt-4o-mini).

        Pipeline:
        1. Co-occurrence pre-filtering (réduire coût)
        2. LLM analyse contexte et extrait relations
        3. Post-processing et validation

        Returns:
            Liste relations extraites
        """
        logger.debug("[OSMOSE:RelationExtraction] LLM extraction (gpt-4o-mini)")

        return self.llm_extractor.extract_relations(
            concepts=concepts,
            full_text=full_text,
            document_id=document_id,
            document_name=document_name,
            chunk_ids=chunk_ids
        )
