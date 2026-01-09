"""
DocContextExtractor - Extraction de contexte documentaire.

Orchestre l'extraction de contexte en trois etapes:
1. Candidate Mining: extraction deterministe de marqueurs
2. Structural Analysis: enrichissement avec features structurelles (PR6)
3. LLM Validation: validation par LLM avec prompt production-grade (PR7)

Le resultat est un DocContextFrame stocke sur le document.

Spec: doc/ongoing/ADR_ASSERTION_AWARE_KG.md - Section 3.1
Spec: doc/ongoing/ADR_DOCUMENT_STRUCTURAL_AWARENESS.md
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
import json
import logging
import re

from knowbase.extraction_v2.context.models import (
    DocScope,
    DocContextFrame,
    DocScopeAnalysis,
    MarkerEvidence,
    ScopeSignals,
    DocumentContext,
)
from knowbase.extraction_v2.context.candidate_mining import (
    CandidateMiner,
    MiningResult,
    MarkerCandidate,
    enrich_candidates_with_structural_analysis,
    DocumentContextDecider,
    MarkerMention,
    decide_marker,
)
from knowbase.extraction_v2.context.structural import (
    ZoneSegmenter,
    TemplateDetector,
    LinguisticCueDetector,
    StructuralAnalysis,
    StructuralConfidence,
    get_zone_segmenter,
    get_template_detector,
    get_linguistic_cue_detector,
)
from knowbase.extraction_v2.context import prompts

logger = logging.getLogger(__name__)


class DocContextExtractor:
    """
    Extracteur de contexte documentaire.

    Utilise une strategie en trois etapes:
    1. Candidate Mining (deterministe) - extraction via regex/patterns
    2. Structural Analysis (PR6) - enrichissement avec features structurelles
    3. LLM Validation (PR7) - validation par LLM avec prompt production-grade

    Le LLM agit comme ARBITRE (pas extracteur) - il classe les candidats
    en CONTEXT_SETTING vs TEMPLATE_NOISE en utilisant les signaux structurels.

    Usage:
        >>> extractor = DocContextExtractor()
        >>> frame = await extractor.extract(
        ...     document_id="doc_123",
        ...     filename="S4HANA_1809_BUSINESS_SCOPE.pdf",
        ...     pages_text=["Page 1 text...", "Page 2 text..."],
        ... )
        >>> print(frame.doc_scope)  # DocScope.VARIANT_SPECIFIC
        >>> print(frame.strong_markers)  # ["1809"]
    """

    def __init__(
        self,
        use_llm: bool = True,
        llm_temperature: float = 0.0,
        llm_max_tokens: int = 1024,
        min_candidates_for_llm: int = 0,
        use_structural_analysis: bool = True,
        use_document_context_filtering: bool = True,
    ):
        """
        Initialise l'extracteur.

        Args:
            use_llm: Utiliser le LLM pour validation (True en production)
            llm_temperature: Temperature pour le LLM
            llm_max_tokens: Max tokens pour la reponse LLM
            min_candidates_for_llm: Nombre minimum de candidats pour appeler le LLM
                                    (si 0, toujours appeler meme sans candidats)
            use_structural_analysis: Utiliser l'analyse structurelle (PR6)
            use_document_context_filtering: Utiliser DocumentContext + decide_marker()
                                            pour filtrer les faux positifs (ADR)
        """
        self.use_llm = use_llm
        self.llm_temperature = llm_temperature
        self.llm_max_tokens = llm_max_tokens
        self.min_candidates_for_llm = min_candidates_for_llm
        self.use_structural_analysis = use_structural_analysis
        self.use_document_context_filtering = use_document_context_filtering

        # Initialiser le miner
        self._miner = CandidateMiner()

        # Structural analysis components (lazy init)
        self._zone_segmenter = None
        self._template_detector = None
        self._linguistic_detector = None

        # LLM Router (lazy init)
        self._llm_router = None

    def _get_zone_segmenter(self) -> ZoneSegmenter:
        """Lazy init du ZoneSegmenter."""
        if self._zone_segmenter is None:
            self._zone_segmenter = get_zone_segmenter()
        return self._zone_segmenter

    def _get_template_detector(self) -> TemplateDetector:
        """Lazy init du TemplateDetector."""
        if self._template_detector is None:
            self._template_detector = get_template_detector()
        return self._template_detector

    def _get_linguistic_detector(self) -> LinguisticCueDetector:
        """Lazy init du LinguisticCueDetector."""
        if self._linguistic_detector is None:
            self._linguistic_detector = get_linguistic_cue_detector()
        return self._linguistic_detector

    def _get_llm_router(self):
        """Lazy init du LLM Router."""
        if self._llm_router is None:
            from knowbase.common.llm_router import get_llm_router
            self._llm_router = get_llm_router()
        return self._llm_router

    def _perform_structural_analysis(
        self,
        pages_text: List[str],
    ) -> StructuralAnalysis:
        """
        Effectue l'analyse structurelle du document.

        Pipeline:
        1. Zone Segmentation - segmente chaque page en TOP/MAIN/BOTTOM
        2. Template Detection - identifie les fragments repetes (boilerplate)

        Args:
            pages_text: Liste des textes par page

        Returns:
            StructuralAnalysis avec zones, templates, et statistiques
        """
        # Etape 1: Segmentation en zones
        segmenter = self._get_zone_segmenter()
        pages_zones = segmenter.segment_document(pages_text)

        # Etape 2: Detection des templates
        detector = self._get_template_detector()
        analysis = detector.analyze(pages_zones)

        return analysis

    def _filter_candidates_with_context(
        self,
        candidates: List[MarkerCandidate],
        document_context: DocumentContext,
        document_id: str = "unknown",
    ) -> tuple:
        """
        Filtre les candidats via decide_marker() avec le DocumentContext.

        Applique les regles ADR Document Context Markers:
        - structure_hint.has_numbered_sections → rejette WORD+SMALL_NUMBER en position heading
        - entity_hints → booste confiance si prefix correspond a une entite dominante
        - Safe-by-default: en cas de doute, rejeter

        Args:
            candidates: Liste de MarkerCandidate a filtrer
            document_context: Contraintes document-level
            document_id: ID du document pour EvidenceRef

        Returns:
            Tuple (filtered_candidates, rejection_log)
        """
        filtered = []
        rejection_log = []

        for candidate in candidates:
            # Convertir MarkerCandidate en MarkerMention via factory method
            mention = MarkerMention.from_marker_candidate(candidate, document_id)

            # Appliquer decide_marker()
            decision = decide_marker(mention, document_context)

            if decision.decision in ("ACCEPT_STRONG", "ACCEPT_WEAK"):
                filtered.append(candidate)
                logger.debug(
                    f"[DocContextExtractor] ACCEPT {candidate.value}: "
                    f"{decision.decision} (score={decision.score:.2f}, reasons={decision.reasons})"
                )
            else:
                rejection_log.append({
                    "value": candidate.value,
                    "decision": decision.decision,
                    "reasons": decision.reasons,
                })
                logger.debug(
                    f"[DocContextExtractor] REJECT {candidate.value}: "
                    f"{decision.decision} (reasons={decision.reasons})"
                )

        return filtered, rejection_log

    async def extract(
        self,
        document_id: str,
        filename: str,
        pages_text: List[str],
        metadata: Optional[Dict[str, Any]] = None,
        document_context: Optional[DocumentContext] = None,
    ) -> DocContextFrame:
        """
        Extrait le contexte documentaire.

        Pipeline en 4 etapes (ADR Document Context Markers):
        1. Candidate Mining - extraction deterministe de marqueurs
        2. Structural Analysis - enrichissement avec zone/template/linguistic features
        3. DocumentContext Filtering - filtrage via decide_marker() (ADR)
        4. LLM Validation - arbitrage final par LLM

        Args:
            document_id: Identifiant unique du document
            filename: Nom du fichier
            pages_text: Liste des textes par page (index 0 = premiere page)
            metadata: Metadonnees additionnelles (headers, footers, etc.)
            document_context: DocumentContext pre-genere (optionnel, sera genere si absent)

        Returns:
            DocContextFrame avec les marqueurs et la classification
        """
        logger.info(f"[DocContextExtractor] Extracting context for: {filename}")

        # === ETAPE 1: Candidate Mining ===
        mining_result = self._miner.mine_document(
            filename=filename,
            pages_text=pages_text,
            metadata=metadata,
        )

        # Calculer les signaux de base
        total_pages = len(pages_text)
        signals_dict = self._miner.compute_signals(mining_result, total_pages)

        logger.info(
            f"[DocContextExtractor] Mining found {len(mining_result.candidates)} candidates, "
            f"signals={signals_dict}"
        )

        # === ETAPE 2: Structural Analysis (PR6) ===
        structural_analysis = None
        if self.use_structural_analysis and len(pages_text) > 0:
            try:
                structural_analysis = self._perform_structural_analysis(pages_text)

                # Enrichir les candidats avec les features structurelles
                enriched_candidates = enrich_candidates_with_structural_analysis(
                    candidates=mining_result.candidates,
                    structural_analysis=structural_analysis,
                    linguistic_detector=self._get_linguistic_detector(),
                )

                # Remplacer les candidats par les versions enrichies
                mining_result.candidates = enriched_candidates

                logger.info(
                    f"[DocContextExtractor] Structural analysis: "
                    f"confidence={structural_analysis.structural_confidence.value}, "
                    f"templates={len(structural_analysis.template_fragments)}, "
                    f"coverage={structural_analysis.template_coverage:.1%}"
                )
            except Exception as e:
                logger.warning(
                    f"[DocContextExtractor] Structural analysis failed: {e}, "
                    f"continuing without enrichment"
                )

        # === ETAPE 3: DocumentContext Filtering (ADR Document Context Markers) ===
        # Filtre les faux positifs comme "PUBLIC 3" via structure_hint et entity_hints
        if self.use_document_context_filtering and document_context is not None:
            try:
                filtered_candidates, rejection_log = self._filter_candidates_with_context(
                    candidates=mining_result.candidates,
                    document_context=document_context,
                    document_id=document_id,
                )

                rejected_count = len(mining_result.candidates) - len(filtered_candidates)
                if rejected_count > 0:
                    logger.info(
                        f"[DocContextExtractor] DocumentContext filtering: "
                        f"rejected {rejected_count}/{len(mining_result.candidates)} candidates, "
                        f"reasons: {rejection_log[:3]}"  # Log premiers rejets
                    )

                # Remplacer les candidats par ceux filtrés
                mining_result.candidates = filtered_candidates

            except Exception as e:
                logger.warning(
                    f"[DocContextExtractor] DocumentContext filtering failed: {e}, "
                    f"continuing without filtering"
                )

        # === ETAPE 4: LLM Validation (PR7) ===
        if self.use_llm:
            # Appeler le LLM si on a des candidats OU si on veut quand meme classifier
            should_call_llm = (
                len(mining_result.candidates) >= self.min_candidates_for_llm
            )

            if should_call_llm:
                try:
                    analysis = await self._validate_with_llm(
                        candidates=mining_result.candidates,
                        pages_text=pages_text,
                        filename=filename,
                        signals=signals_dict,
                        structural_analysis=structural_analysis,
                    )

                    frame = analysis.to_context_frame(document_id)

                    logger.info(
                        f"[DocContextExtractor] LLM classified as {frame.doc_scope.value}, "
                        f"strong={frame.strong_markers}, weak={frame.weak_markers}"
                    )

                    return frame

                except Exception as e:
                    logger.warning(
                        f"[DocContextExtractor] LLM validation failed: {e}, "
                        f"falling back to heuristic"
                    )
                    # Fallback to heuristic
                    return self._heuristic_classification(
                        document_id=document_id,
                        mining_result=mining_result,
                        signals_dict=signals_dict,
                    )
            else:
                # Pas assez de candidats, classification heuristique
                return self._heuristic_classification(
                    document_id=document_id,
                    mining_result=mining_result,
                    signals_dict=signals_dict,
                )
        else:
            # Mode sans LLM (tests, fallback)
            return self._heuristic_classification(
                document_id=document_id,
                mining_result=mining_result,
                signals_dict=signals_dict,
            )

    async def _validate_with_llm(
        self,
        candidates: List[MarkerCandidate],
        pages_text: List[str],
        filename: str,
        signals: Dict[str, float],
        structural_analysis: Optional[StructuralAnalysis] = None,
    ) -> DocScopeAnalysis:
        """
        Valide les candidats avec le LLM.

        Le LLM agit comme ARBITRE: il classe chaque candidat en:
        - CONTEXT_SETTING: marqueur definissant le scope du document
        - TEMPLATE_NOISE: marqueur present dans boilerplate/legal
        - AMBIGUOUS: pas assez de signaux pour decider

        Args:
            candidates: Liste de MarkerCandidate (enrichis avec features structurelles)
            pages_text: Texte des pages
            filename: Nom du fichier
            signals: Signaux pre-calcules
            structural_analysis: Analyse structurelle du document (optionnel)

        Returns:
            DocScopeAnalysis validee par le LLM
        """
        from knowbase.common.llm_router import TaskType

        # Preparer les candidats au format JSON avec features structurelles
        # Utiliser to_dict_enriched() pour inclure zone_distribution, template_likelihood, etc.
        candidates_dicts = [c.to_dict_enriched() for c in candidates]

        # Preparer le texte (premieres pages seulement)
        document_text = "\n\n---\n\n".join(pages_text[:5])

        # Ajouter les informations structurelles au contexte
        structural_context = None
        if structural_analysis is not None:
            structural_context = {
                "structural_confidence": structural_analysis.structural_confidence.value,
                "total_pages": structural_analysis.total_pages,
                "template_coverage": round(structural_analysis.template_coverage, 2),
                "template_count": len(structural_analysis.template_fragments),
            }

        # Construire les messages avec le nouveau prompt production-grade
        messages = prompts.get_messages(
            candidates=candidates_dicts,
            document_text=document_text,
            filename=filename,
            signals=signals,
            structural_context=structural_context,
        )

        # Appeler le LLM
        router = self._get_llm_router()
        response = await router.acomplete(
            task_type=TaskType.KNOWLEDGE_EXTRACTION,
            messages=messages,
            temperature=self.llm_temperature,
            max_tokens=self.llm_max_tokens,
        )

        # Parser la reponse JSON
        analysis = self._parse_llm_response(response)

        return analysis

    def _parse_llm_response(self, response: str) -> DocScopeAnalysis:
        """
        Parse la reponse JSON du LLM.

        Args:
            response: Reponse brute du LLM

        Returns:
            DocScopeAnalysis

        Raises:
            ValueError: Si le JSON est invalide
        """
        # Nettoyer la reponse (enlever markdown si present)
        response = response.strip()
        if response.startswith("```"):
            # Enlever les backticks markdown
            lines = response.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            response = "\n".join(lines)

        try:
            data = json.loads(response)
        except json.JSONDecodeError as e:
            # Essayer d'extraire le JSON de la reponse
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                try:
                    data = json.loads(json_match.group())
                except json.JSONDecodeError:
                    raise ValueError(f"Failed to parse LLM response as JSON: {e}")
            else:
                raise ValueError(f"No valid JSON found in LLM response: {e}")

        # Construire l'analyse
        strong_markers = [
            MarkerEvidence(
                value=m.get("value", ""),
                evidence=m.get("evidence", ""),
                source=m.get("source", "unknown"),
            )
            for m in data.get("strong_markers", [])
        ]

        weak_markers = [
            MarkerEvidence(
                value=m.get("value", ""),
                evidence=m.get("evidence", ""),
                source=m.get("source", "unknown"),
            )
            for m in data.get("weak_markers", [])
        ]

        # Parser le scope
        scope_str = data.get("doc_scope", "GENERAL").upper()
        try:
            doc_scope = DocScope(scope_str)
        except ValueError:
            doc_scope = DocScope.GENERAL

        # Parser les signaux
        signals_data = data.get("signals", {})
        signals = ScopeSignals(
            marker_position_score=signals_data.get("marker_position_score", 0.0),
            marker_repeat_score=signals_data.get("marker_repeat_score", 0.0),
            scope_language_score=signals_data.get("scope_language_score", 0.0),
            marker_diversity_score=signals_data.get("marker_diversity_score", 0.0),
            conflict_score=signals_data.get("conflict_score", 0.0),
        )

        return DocScopeAnalysis(
            strong_markers=strong_markers,
            weak_markers=weak_markers,
            doc_scope=doc_scope,
            scope_confidence=data.get("scope_confidence", 0.5),
            signals=signals,
            evidence=data.get("evidence", []),
            notes=data.get("notes", ""),
        )

    def _heuristic_classification(
        self,
        document_id: str,
        mining_result: MiningResult,
        signals_dict: Dict[str, float],
    ) -> DocContextFrame:
        """
        Classification heuristique sans LLM.

        Utilisee en fallback ou en mode test.

        Args:
            document_id: ID du document
            mining_result: Resultat du mining
            signals_dict: Signaux calcules

        Returns:
            DocContextFrame
        """
        signals = ScopeSignals(**signals_dict)

        # Logique de classification
        if mining_result.conflict_hits >= 3:
            # Beaucoup de conflits = MIXED
            doc_scope = DocScope.MIXED
            scope_confidence = min(0.7, 0.4 + mining_result.conflict_hits * 0.1)
        elif len(mining_result.candidates) == 0:
            # Pas de candidats = GENERAL
            doc_scope = DocScope.GENERAL
            scope_confidence = 0.6
        elif len(mining_result.get_unique_values()) >= 4:
            # Beaucoup de marqueurs differents = potentiellement MIXED
            doc_scope = DocScope.MIXED
            scope_confidence = 0.5
        else:
            # Sinon, verifier si on a des marqueurs forts
            cover_candidates = mining_result.get_by_source("cover")
            filename_candidates = mining_result.get_by_source("filename")

            if cover_candidates or filename_candidates:
                doc_scope = DocScope.VARIANT_SPECIFIC
                scope_confidence = 0.7 if cover_candidates else 0.5
            else:
                doc_scope = DocScope.GENERAL
                scope_confidence = 0.4

        # Separer les marqueurs forts et faibles
        strong_markers = []
        weak_markers = []
        strong_evidence = []
        weak_evidence = []

        for c in mining_result.candidates:
            if c.source in ("cover", "header", "revision"):
                strong_markers.append(c.value)
                strong_evidence.append(c.evidence[:100] if c.evidence else "")
            else:
                weak_markers.append(c.value)
                weak_evidence.append(c.evidence[:100] if c.evidence else "")

        # Limiter a 3 marqueurs
        strong_markers = strong_markers[:3]
        weak_markers = weak_markers[:3]
        strong_evidence = strong_evidence[:3]
        weak_evidence = weak_evidence[:3]

        frame = DocContextFrame(
            document_id=document_id,
            strong_markers=strong_markers,
            weak_markers=weak_markers,
            strong_evidence=strong_evidence,
            weak_evidence=weak_evidence,
            doc_scope=doc_scope,
            scope_confidence=scope_confidence,
            scope_signals=signals,
            notes="Heuristic classification (no LLM)",
        )

        logger.info(
            f"[DocContextExtractor] Heuristic: {frame.doc_scope.value}, "
            f"conf={frame.scope_confidence:.2f}, markers={frame.strong_markers + frame.weak_markers}"
        )

        return frame

    def extract_sync(
        self,
        document_id: str,
        filename: str,
        pages_text: List[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DocContextFrame:
        """
        Version synchrone de extract() pour usage sans async.

        Utilise uniquement la classification heuristique (pas de LLM).
        """
        mining_result = self._miner.mine_document(
            filename=filename,
            pages_text=pages_text,
            metadata=metadata,
        )

        signals_dict = self._miner.compute_signals(mining_result, len(pages_text))

        return self._heuristic_classification(
            document_id=document_id,
            mining_result=mining_result,
            signals_dict=signals_dict,
        )


# Singleton pour reutilisation
_extractor_instance: Optional[DocContextExtractor] = None


def get_doc_context_extractor() -> DocContextExtractor:
    """Retourne l'instance singleton de l'extracteur."""
    global _extractor_instance
    if _extractor_instance is None:
        _extractor_instance = DocContextExtractor()
    return _extractor_instance


__all__ = [
    "DocContextExtractor",
    "get_doc_context_extractor",
]
