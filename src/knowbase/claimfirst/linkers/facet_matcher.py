# src/knowbase/claimfirst/linkers/facet_matcher.py
"""
FacetMatcher — Tier 3 du Facet Registry émergent.

Affectation déterministe Claim → Facet via 4 signaux pondérés :
1. Document inheritance (0.25) — claims héritent des facettes du doc parent
2. Keyword matching (0.35) — match des keywords de la facette dans le texte
3. Section context (0.25) — hérite des facettes de la section
4. ClaimKey pattern match (0.15) — réutilise ClaimKeyPatterns existant

Seuil : score >= 0.3 pour créer un lien. Multi-facet autorisé.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from knowbase.claimfirst.models.claim import Claim
from knowbase.claimfirst.models.facet import Facet
from knowbase.stratified.claimkey.patterns import ClaimKeyPatterns

logger = logging.getLogger(__name__)


# Coefficients initiaux heuristiques — à calibrer sur set de validation
DEFAULT_WEIGHTS = {
    "document_inheritance": 0.25,
    "keyword_matching": 0.35,
    "section_context": 0.25,
    "claimkey_pattern": 0.15,
}

DEFAULT_MIN_SCORE = 0.3


class FacetMatcher:
    """
    Matching déterministe Claim → Facet via 4 signaux pondérés.

    Reçoit les facettes validées depuis FacetRegistry (injection).
    """

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        min_score: float = DEFAULT_MIN_SCORE,
    ):
        self.weights = weights or dict(DEFAULT_WEIGHTS)
        self.min_score = min_score
        self.patterns = ClaimKeyPatterns()

        self.stats = {
            "claims_processed": 0,
            "links_created": 0,
            "signals_used": {
                "document_inheritance": 0,
                "keyword_matching": 0,
                "section_context": 0,
                "claimkey_pattern": 0,
            },
        }

    def match(
        self,
        claims: List[Claim],
        tenant_id: str,
        validated_facets: Optional[List[Facet]] = None,
        doc_facet_ids: Optional[List[str]] = None,
        section_facet_map: Optional[Dict[str, List[str]]] = None,
    ) -> Tuple[List[Facet], List[Tuple[str, str]]]:
        """
        Matche les claims avec les facettes (rétrocompatible).

        Args:
            claims: Claims à analyser
            tenant_id: Tenant ID
            validated_facets: Facettes validées depuis le FacetRegistry
            doc_facet_ids: IDs des facettes du document parent
            section_facet_map: section_id → facet_ids

        Returns:
            Tuple (facets, links) où links = (claim_id, facet_id)
        """
        if validated_facets is None:
            validated_facets = []

        facets_by_id: Dict[str, Facet] = {f.facet_id: f for f in validated_facets}
        facets_by_domain: Dict[str, Facet] = {f.domain: f for f in validated_facets}

        links: List[Tuple[str, str]] = []
        doc_facet_set = set(doc_facet_ids or [])

        # Mode post-import : pas de contexte document/section
        # → le keyword matching seul doit suffire
        is_post_import = not doc_facet_ids and not section_facet_map

        for claim in claims:
            self.stats["claims_processed"] += 1

            if is_post_import:
                claim_links = self._assign_keyword_only(
                    claim=claim,
                    validated_facets=validated_facets,
                )
            else:
                claim_links = self.assign_claim_to_facets(
                    claim=claim,
                    validated_facets=validated_facets,
                    facets_by_id=facets_by_id,
                    facets_by_domain=facets_by_domain,
                    doc_facet_ids=doc_facet_set,
                    section_facet_map=section_facet_map,
                )

            for facet_id, _score, _signals in claim_links:
                links.append((claim.claim_id, facet_id))
                self.stats["links_created"] += 1

        logger.info(
            f"[OSMOSE:FacetMatcher] {self.stats['links_created']} links for "
            f"{len(claims)} claims across {len(validated_facets)} facets"
            f"{' (post-import mode)' if is_post_import else ''}"
        )

        return validated_facets, links

    def _assign_keyword_only(
        self,
        claim: Claim,
        validated_facets: List[Facet],
        min_keywords: int = 2,
        min_ratio: float = 0.10,
    ) -> List[Tuple[str, float, str]]:
        """
        Mode post-import : matching par keywords uniquement.

        Plus permissif que le mode pipeline (pas de seuil 0.3 composite).
        Requiert au moins min_keywords matchés ET un ratio min.
        Multi-facet : une claim peut être liée à plusieurs facettes.

        Args:
            claim: Claim à matcher
            validated_facets: Facettes validées
            min_keywords: Nombre minimum de keywords matchés (défaut: 2)
            min_ratio: Ratio minimum matched/total keywords (défaut: 0.15)

        Returns:
            Liste de (facet_id, score, signals)
        """
        claim_text_lower = claim.text.lower() if claim.text else ""
        if not claim_text_lower:
            return []

        results = []
        for facet in validated_facets:
            if not facet.keywords:
                continue

            matched = 0
            for kw in facet.keywords:
                if kw.lower() in claim_text_lower:
                    matched += 1

            if matched < min_keywords:
                continue

            ratio = matched / len(facet.keywords)
            if ratio < min_ratio:
                continue

            score = ratio
            results.append((facet.facet_id, score, f"keyword({matched}/{len(facet.keywords)})"))
            self.stats["signals_used"]["keyword_matching"] += 1

        return results

    def assign_claim_to_facets(
        self,
        claim: Claim,
        validated_facets: List[Facet],
        facets_by_id: Dict[str, Facet],
        facets_by_domain: Dict[str, Facet],
        doc_facet_ids: set,
        section_facet_map: Optional[Dict[str, List[str]]] = None,
    ) -> List[Tuple[str, float, str]]:
        """
        Assigne une claim aux facettes pertinentes.

        Returns:
            Liste de (facet_id, score, assignment_signals)
        """
        results = []
        claim_text_lower = claim.text.lower() if claim.text else ""

        for facet in validated_facets:
            signals = []
            score = 0.0

            # Signal 1: Document inheritance
            if facet.facet_id in doc_facet_ids or facet.domain in doc_facet_ids:
                score += self.weights["document_inheritance"]
                signals.append("doc_inherit")

            # Signal 2: Keyword matching
            kw_score = self._keyword_match_score(claim_text_lower, facet)
            if kw_score > 0:
                score += self.weights["keyword_matching"] * kw_score
                signals.append("keyword")

            # Signal 3: Section context
            if section_facet_map and hasattr(claim, "section_id") and claim.section_id:
                section_facets = section_facet_map.get(claim.section_id, [])
                if facet.facet_id in section_facets or facet.domain in section_facets:
                    score += self.weights["section_context"]
                    signals.append("section")

            # Signal 4: ClaimKey pattern match
            ck_score = self._claimkey_pattern_score(claim, facet)
            if ck_score > 0:
                score += self.weights["claimkey_pattern"] * ck_score
                signals.append("claimkey")

            if score >= self.min_score and signals:
                signal_str = "+".join(signals)
                results.append((facet.facet_id, score, signal_str))

                # Stats
                for s in signals:
                    key = {
                        "doc_inherit": "document_inheritance",
                        "keyword": "keyword_matching",
                        "section": "section_context",
                        "claimkey": "claimkey_pattern",
                    }.get(s)
                    if key:
                        self.stats["signals_used"][key] += 1

        return results

    def assign_claims_to_facets(
        self,
        claims: List[Claim],
        validated_facets: List[Facet],
        doc_facet_ids: List[str],
        section_facet_map: Optional[Dict[str, List[str]]] = None,
    ) -> List[Tuple[str, str, float, str]]:
        """
        Assigne toutes les claims aux facettes.

        Returns:
            Liste de (claim_id, facet_id, score, assignment_signals)
        """
        facets_by_id = {f.facet_id: f for f in validated_facets}
        facets_by_domain = {f.domain: f for f in validated_facets}
        doc_facet_set = set(doc_facet_ids or [])

        results = []
        for claim in claims:
            self.stats["claims_processed"] += 1
            claim_links = self.assign_claim_to_facets(
                claim=claim,
                validated_facets=validated_facets,
                facets_by_id=facets_by_id,
                facets_by_domain=facets_by_domain,
                doc_facet_ids=doc_facet_set,
                section_facet_map=section_facet_map,
            )
            for facet_id, score, signals in claim_links:
                results.append((claim.claim_id, facet_id, score, signals))
                self.stats["links_created"] += 1

        return results

    def _keyword_match_score(self, claim_text_lower: str, facet: Facet) -> float:
        """Score de matching par keywords (0.0-1.0)."""
        if not facet.keywords:
            return 0.0

        matched = 0
        for kw in facet.keywords:
            if kw.lower() in claim_text_lower:
                matched += 1

        if matched == 0:
            return 0.0

        return min(1.0, matched / max(len(facet.keywords), 1))

    def _claimkey_pattern_score(self, claim: Claim, facet: Facet) -> float:
        """Score basé sur ClaimKeyPatterns (0.0 ou 1.0)."""
        context = {
            "product": "",
            "current_theme": "",
        }
        if claim.scope and claim.scope.version:
            context["version"] = claim.scope.version

        pattern_match = self.patterns.infer_claimkey(claim.text, context)
        if not pattern_match:
            return 0.0

        # Le domain du pattern matche le domain de la facette ?
        if facet.matches_domain(pattern_match.domain):
            return 1.0

        return 0.0

    def get_stats(self) -> dict:
        """Retourne les statistiques de matching."""
        return dict(self.stats)

    def reset_stats(self) -> None:
        """Réinitialise les statistiques."""
        self.stats = {
            "claims_processed": 0,
            "links_created": 0,
            "signals_used": {
                "document_inheritance": 0,
                "keyword_matching": 0,
                "section_context": 0,
                "claimkey_pattern": 0,
            },
        }


__all__ = [
    "FacetMatcher",
    "DEFAULT_WEIGHTS",
]
