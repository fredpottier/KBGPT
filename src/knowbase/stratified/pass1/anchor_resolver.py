"""
OSMOSE Pipeline V2 - Phase 1.3b Anchor Resolver (CRITIQUE)
===========================================================
Ref: doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md

Convertit les ancrages chunk_id → docitem_id:
- Trouve le DocItem correspondant à chaque chunk
- Calcule le span relatif au DocItem
- Gère les cas d'échec (NO_DOCITEM_ANCHOR, CROSS_DOCITEM)

INVARIANT V2-001: Chaque Information DOIT avoir ANCHORED_IN → DocItem
INVARIANT V2-002: ANCHORED_IN ne doit JAMAIS viser autre chose que DocItem
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from difflib import SequenceMatcher

from knowbase.stratified.models import (
    Anchor,
    DocItem,
    AssertionLogReason,
)
from knowbase.stratified.pass1.assertion_extractor import RawAssertion, ConceptLink

logger = logging.getLogger(__name__)


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class AnchorResolutionResult:
    """Résultat de la résolution d'ancrage pour une assertion."""
    assertion_id: str
    success: bool
    anchor: Optional[Anchor] = None
    failure_reason: Optional[AssertionLogReason] = None
    details: str = ""


@dataclass
class ChunkToDocItemMapping:
    """Mapping entre un chunk et ses DocItems correspondants."""
    chunk_id: str
    docitem_ids: List[str] = field(default_factory=list)
    # Mapping position chunk → position DocItem
    char_offsets: Dict[str, int] = field(default_factory=dict)


@dataclass
class AnchorResolverStats:
    """Statistiques de résolution d'ancrage."""
    total: int = 0
    resolved: int = 0
    no_docitem: int = 0
    cross_docitem: int = 0
    ambiguous_span: int = 0


# ============================================================================
# ANCHOR RESOLVER
# ============================================================================

class AnchorResolverV2:
    """
    Résolveur d'ancrages pour Pipeline V2.

    MISSION CRITIQUE: Convertir chunk_id → docitem_id

    Les assertions sont extraites depuis des chunks (pour compatibilité Qdrant),
    mais doivent être ancrées sur des DocItems (surface de preuve atomique).

    Stratégies de résolution:
    1. Mapping direct: Si le chunk correspond exactement à un DocItem
    2. Matching texte: Chercher le texte de l'assertion dans les DocItems
    3. Fuzzy matching: En cas d'échec, utiliser SequenceMatcher
    """

    # Seuil de similarité pour le fuzzy matching
    FUZZY_THRESHOLD = 0.85

    def __init__(
        self,
        chunk_to_docitem_map: Optional[Dict[str, List[str]]] = None,
        docitems: Optional[Dict[str, DocItem]] = None,
        chunks: Optional[Dict[str, str]] = None
    ):
        """
        Args:
            chunk_to_docitem_map: Mapping chunk_id → [docitem_ids]
            docitems: Dict docitem_id → DocItem
            chunks: Dict chunk_id → texte du chunk
        """
        self.chunk_to_docitem_map = chunk_to_docitem_map or {}
        self.docitems = docitems or {}
        self.chunks = chunks or {}
        self.stats = AnchorResolverStats()

    def set_context(
        self,
        chunk_to_docitem_map: Dict[str, List[str]],
        docitems: Dict[str, DocItem],
        chunks: Dict[str, str]
    ):
        """Configure le contexte de résolution."""
        self.chunk_to_docitem_map = chunk_to_docitem_map
        self.docitems = docitems
        self.chunks = chunks
        self.stats = AnchorResolverStats()

    def resolve_all(
        self,
        assertions: List[RawAssertion],
        links: List[ConceptLink]
    ) -> Tuple[List[Tuple[RawAssertion, Anchor, str]], List[Tuple[RawAssertion, AssertionLogReason, str]]]:
        """
        Résout les ancrages pour toutes les assertions liées.

        Args:
            assertions: Liste des assertions à ancrer
            links: Liens assertion → concept (pour savoir quelles assertions ancrer)

        Returns:
            Tuple[resolved, failed]
            - resolved: [(assertion, anchor, concept_id), ...]
            - failed: [(assertion, reason, details), ...]
        """
        # Créer un set des assertion_ids liés à des concepts
        linked_assertion_ids = {link.assertion_id for link in links}
        link_map = {link.assertion_id: link.concept_id for link in links}

        resolved = []
        failed = []

        for assertion in assertions:
            if assertion.assertion_id not in linked_assertion_ids:
                # Assertion non liée → abstained (no_concept_match)
                failed.append((
                    assertion,
                    AssertionLogReason.NO_CONCEPT_MATCH,
                    "Assertion non liée à aucun concept"
                ))
                self.stats.total += 1
                continue

            self.stats.total += 1
            result = self.resolve_single(assertion)

            if result.success and result.anchor:
                concept_id = link_map.get(assertion.assertion_id, "")
                resolved.append((assertion, result.anchor, concept_id))
                self.stats.resolved += 1
            else:
                failed.append((assertion, result.failure_reason, result.details))
                self._update_failure_stats(result.failure_reason)

        logger.info(
            f"[OSMOSE:Pass1:1.3b] Anchor Resolution: "
            f"{self.stats.resolved}/{self.stats.total} résolus, "
            f"{self.stats.no_docitem} no_docitem, "
            f"{self.stats.cross_docitem} cross_docitem"
        )

        return resolved, failed

    def resolve_single(self, assertion: RawAssertion) -> AnchorResolutionResult:
        """
        Résout l'ancrage pour une assertion unique.

        Stratégies:
        1. Mapping direct chunk → DocItem
        2. Recherche texte dans les DocItems du chunk
        3. Fuzzy matching si texte non trouvé exactement
        """
        chunk_id = assertion.chunk_id

        # Stratégie 1: Mapping direct
        docitem_ids = self.chunk_to_docitem_map.get(chunk_id, [])

        if not docitem_ids:
            # Pas de mapping → chercher dans tous les DocItems
            return self._resolve_by_text_search(assertion)

        if len(docitem_ids) == 1:
            # Mapping unique → résolution directe
            return self._resolve_in_single_docitem(assertion, docitem_ids[0])

        # Plusieurs DocItems → chercher lequel contient l'assertion
        return self._resolve_in_multiple_docitems(assertion, docitem_ids)

    def _resolve_in_single_docitem(
        self,
        assertion: RawAssertion,
        docitem_id: str
    ) -> AnchorResolutionResult:
        """Résout l'ancrage dans un DocItem unique."""
        docitem = self.docitems.get(docitem_id)
        if not docitem:
            return AnchorResolutionResult(
                assertion_id=assertion.assertion_id,
                success=False,
                failure_reason=AssertionLogReason.NO_DOCITEM_ANCHOR,
                details=f"DocItem {docitem_id} non trouvé"
            )

        # Chercher le texte de l'assertion dans le DocItem
        span_result = self._find_span_in_docitem(assertion.text, docitem)

        if span_result:
            span_start, span_end = span_result
            return AnchorResolutionResult(
                assertion_id=assertion.assertion_id,
                success=True,
                anchor=Anchor(
                    docitem_id=docitem_id,
                    span_start=span_start,
                    span_end=span_end
                )
            )

        # Fallback: utiliser les positions du chunk si le texte matche approximativement
        chunk_text = self.chunks.get(assertion.chunk_id, "")
        if chunk_text and self._texts_overlap(assertion.text, docitem.text):
            # Les textes se chevauchent → utiliser les positions relatives
            return AnchorResolutionResult(
                assertion_id=assertion.assertion_id,
                success=True,
                anchor=Anchor(
                    docitem_id=docitem_id,
                    span_start=0,
                    span_end=min(len(assertion.text), len(docitem.text))
                )
            )

        return AnchorResolutionResult(
            assertion_id=assertion.assertion_id,
            success=False,
            failure_reason=AssertionLogReason.AMBIGUOUS_SPAN,
            details=f"Texte non trouvé dans DocItem {docitem_id}"
        )

    def _resolve_in_multiple_docitems(
        self,
        assertion: RawAssertion,
        docitem_ids: List[str]
    ) -> AnchorResolutionResult:
        """Résout l'ancrage quand plusieurs DocItems correspondent au chunk."""
        best_match = None
        best_score = 0

        for docitem_id in docitem_ids:
            docitem = self.docitems.get(docitem_id)
            if not docitem:
                continue

            span_result = self._find_span_in_docitem(assertion.text, docitem)
            if span_result:
                span_start, span_end = span_result
                # Match exact trouvé
                return AnchorResolutionResult(
                    assertion_id=assertion.assertion_id,
                    success=True,
                    anchor=Anchor(
                        docitem_id=docitem_id,
                        span_start=span_start,
                        span_end=span_end
                    )
                )

            # Calcul du score de similarité
            score = SequenceMatcher(None, assertion.text, docitem.text).ratio()
            if score > best_score:
                best_score = score
                best_match = docitem_id

        if best_score >= self.FUZZY_THRESHOLD and best_match:
            # Fuzzy match acceptable
            docitem = self.docitems[best_match]
            return AnchorResolutionResult(
                assertion_id=assertion.assertion_id,
                success=True,
                anchor=Anchor(
                    docitem_id=best_match,
                    span_start=0,
                    span_end=min(len(assertion.text), len(docitem.text))
                )
            )

        # L'assertion chevauche plusieurs DocItems
        if len(docitem_ids) > 1 and best_score > 0.3:
            return AnchorResolutionResult(
                assertion_id=assertion.assertion_id,
                success=False,
                failure_reason=AssertionLogReason.CROSS_DOCITEM,
                details=f"Assertion chevauche {len(docitem_ids)} DocItems"
            )

        return AnchorResolutionResult(
            assertion_id=assertion.assertion_id,
            success=False,
            failure_reason=AssertionLogReason.NO_DOCITEM_ANCHOR,
            details="Aucun DocItem correspondant trouvé"
        )

    def _resolve_by_text_search(self, assertion: RawAssertion) -> AnchorResolutionResult:
        """Recherche le texte de l'assertion dans tous les DocItems."""
        best_match = None
        best_span = None
        best_score = 0

        for docitem_id, docitem in self.docitems.items():
            span_result = self._find_span_in_docitem(assertion.text, docitem)
            if span_result:
                # Match exact trouvé
                return AnchorResolutionResult(
                    assertion_id=assertion.assertion_id,
                    success=True,
                    anchor=Anchor(
                        docitem_id=docitem_id,
                        span_start=span_result[0],
                        span_end=span_result[1]
                    )
                )

            # Fuzzy matching
            score = SequenceMatcher(None, assertion.text, docitem.text).ratio()
            if score > best_score:
                best_score = score
                best_match = docitem_id

        if best_score >= self.FUZZY_THRESHOLD and best_match:
            docitem = self.docitems[best_match]
            return AnchorResolutionResult(
                assertion_id=assertion.assertion_id,
                success=True,
                anchor=Anchor(
                    docitem_id=best_match,
                    span_start=0,
                    span_end=min(len(assertion.text), len(docitem.text))
                )
            )

        return AnchorResolutionResult(
            assertion_id=assertion.assertion_id,
            success=False,
            failure_reason=AssertionLogReason.NO_DOCITEM_ANCHOR,
            details=f"Texte non trouvé (meilleur score: {best_score:.2f})"
        )

    def _find_span_in_docitem(
        self,
        assertion_text: str,
        docitem: DocItem
    ) -> Optional[Tuple[int, int]]:
        """Trouve la position exacte du texte dans le DocItem."""
        docitem_text = docitem.text

        # Recherche exacte
        pos = docitem_text.find(assertion_text)
        if pos >= 0:
            return (pos, pos + len(assertion_text))

        # Recherche avec normalisation des espaces
        normalized_assertion = ' '.join(assertion_text.split())
        normalized_docitem = ' '.join(docitem_text.split())

        pos = normalized_docitem.find(normalized_assertion)
        if pos >= 0:
            # Recalculer la position dans le texte original
            return self._map_normalized_position(
                normalized_docitem, docitem_text, pos, len(normalized_assertion)
            )

        return None

    def _map_normalized_position(
        self,
        normalized: str,
        original: str,
        norm_start: int,
        norm_length: int
    ) -> Tuple[int, int]:
        """
        Mappe une position du texte normalisé vers le texte original.
        Approximation: retourne les bornes les plus proches.
        """
        # Heuristique simple: ratio de position
        ratio_start = norm_start / len(normalized) if normalized else 0
        ratio_end = (norm_start + norm_length) / len(normalized) if normalized else 0

        orig_start = int(ratio_start * len(original))
        orig_end = int(ratio_end * len(original))

        return (max(0, orig_start), min(len(original), orig_end))

    def _texts_overlap(self, text1: str, text2: str, threshold: float = 0.5) -> bool:
        """Vérifie si deux textes se chevauchent significativement."""
        return SequenceMatcher(None, text1, text2).ratio() >= threshold

    def _update_failure_stats(self, reason: Optional[AssertionLogReason]):
        """Met à jour les statistiques d'échec."""
        if reason == AssertionLogReason.NO_DOCITEM_ANCHOR:
            self.stats.no_docitem += 1
        elif reason == AssertionLogReason.CROSS_DOCITEM:
            self.stats.cross_docitem += 1
        elif reason == AssertionLogReason.AMBIGUOUS_SPAN:
            self.stats.ambiguous_span += 1


# ============================================================================
# UTILITAIRE: CONSTRUCTION DU MAPPING
# ============================================================================

def build_chunk_to_docitem_mapping(
    chunks: Dict[str, str],
    docitems: Dict[str, DocItem]
) -> Dict[str, List[str]]:
    """
    Construit le mapping chunk_id → [docitem_ids].

    Stratégie:
    1. Si chunk_id contient un docitem_id (convention) → mapping direct
    2. Sinon, matching par texte
    """
    mapping = {}

    for chunk_id, chunk_text in chunks.items():
        # Convention: chunk_id peut contenir docitem_id (ex: "chunk_docitem_123_0")
        docitem_ids_found = []

        for docitem_id, docitem in docitems.items():
            if docitem_id in chunk_id:
                docitem_ids_found.append(docitem_id)
            elif chunk_text and docitem.text:
                # Matching par overlap de texte
                if chunk_text in docitem.text or docitem.text in chunk_text:
                    docitem_ids_found.append(docitem_id)
                elif SequenceMatcher(None, chunk_text, docitem.text).ratio() > 0.8:
                    docitem_ids_found.append(docitem_id)

        mapping[chunk_id] = docitem_ids_found

    return mapping
