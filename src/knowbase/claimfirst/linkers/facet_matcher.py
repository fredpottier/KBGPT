# src/knowbase/claimfirst/linkers/facet_matcher.py
"""
FacetMatcher - Matching déterministe Claim → Facet.

Réutilise ClaimKeyPatterns de stratified/claimkey/patterns.py.

Facet = navigation, inféré par patterns déterministes (pas LLM).
"""

from __future__ import annotations

import logging
import uuid
from typing import Dict, List, Optional, Tuple

from knowbase.claimfirst.models.claim import Claim
from knowbase.claimfirst.models.facet import (
    Facet,
    FacetKind,
    get_predefined_facets,
)
from knowbase.stratified.claimkey.patterns import ClaimKeyPatterns, PatternMatch

logger = logging.getLogger(__name__)


class FacetMatcher:
    """
    Matching déterministe Claim → Facet.

    Utilise ClaimKeyPatterns pour inférer les facettes depuis le texte des claims.
    PAS de LLM - patterns déterministes uniquement.
    """

    def __init__(
        self,
        include_predefined: bool = True,
        min_confidence: float = 0.5,
    ):
        """
        Initialise le matcher.

        Args:
            include_predefined: Si True, inclut les facettes prédéfinies
            min_confidence: Score minimal pour accepter un match
        """
        self.patterns = ClaimKeyPatterns()
        self.include_predefined = include_predefined
        self.min_confidence = min_confidence

        self.stats = {
            "claims_processed": 0,
            "patterns_matched": 0,
            "facets_created": 0,
            "links_created": 0,
        }

    def match(
        self,
        claims: List[Claim],
        tenant_id: str,
    ) -> Tuple[List[Facet], List[Tuple[str, str]]]:
        """
        Matche les claims avec les facettes.

        Args:
            claims: Claims à analyser
            tenant_id: Tenant ID

        Returns:
            Tuple (facets, links) où links est une liste de (claim_id, facet_id)
        """
        facets: Dict[str, Facet] = {}
        links: List[Tuple[str, str]] = []

        # Charger les facettes prédéfinies si demandé
        if self.include_predefined:
            for facet in get_predefined_facets(tenant_id):
                facets[facet.facet_id] = facet

        for claim in claims:
            self.stats["claims_processed"] += 1

            # Appliquer les patterns sur le texte de la claim
            pattern_match = self._match_patterns(claim)

            if pattern_match:
                self.stats["patterns_matched"] += 1

                # Créer ou récupérer la facette
                facet = self._get_or_create_facet(
                    pattern_match=pattern_match,
                    facets=facets,
                    tenant_id=tenant_id,
                )

                # Créer le lien
                links.append((claim.claim_id, facet.facet_id))
                self.stats["links_created"] += 1

            # Aussi matcher contre les facettes prédéfinies par keywords
            predefined_matches = self._match_predefined_facets(claim, facets)
            for facet in predefined_matches:
                if (claim.claim_id, facet.facet_id) not in links:
                    links.append((claim.claim_id, facet.facet_id))
                    self.stats["links_created"] += 1

        logger.info(
            f"[OSMOSE:FacetMatcher] Matched {self.stats['patterns_matched']} patterns, "
            f"created {self.stats['facets_created']} facets, "
            f"{len(links)} links for {len(claims)} claims"
        )

        return list(facets.values()), links

    def _match_patterns(self, claim: Claim) -> Optional[PatternMatch]:
        """
        Applique les patterns ClaimKey sur une claim.

        Args:
            claim: Claim à analyser

        Returns:
            PatternMatch si un pattern matche, None sinon
        """
        # Construire le contexte pour les patterns
        context = {
            "product": "",  # À enrichir depuis les entités
            "current_theme": "",
        }

        # Extraire le contexte depuis la claim si possible
        if claim.scope and claim.scope.version:
            context["version"] = claim.scope.version

        return self.patterns.infer_claimkey(claim.text, context)

    def _get_or_create_facet(
        self,
        pattern_match: PatternMatch,
        facets: Dict[str, Facet],
        tenant_id: str,
    ) -> Facet:
        """
        Récupère ou crée une facette depuis un PatternMatch.

        Args:
            pattern_match: Résultat du pattern matching
            facets: Index des facettes existantes
            tenant_id: Tenant ID

        Returns:
            Facet correspondante
        """
        # Construire l'ID depuis le domain
        facet_id = f"facet_{pattern_match.domain.replace('.', '_')}"

        if facet_id in facets:
            return facets[facet_id]

        # Mapper value_kind vers FacetKind
        kind = self._map_value_kind_to_facet_kind(pattern_match.value_kind)

        # Créer la nouvelle facette
        facet = Facet(
            facet_id=facet_id,
            tenant_id=tenant_id,
            facet_name=pattern_match.domain.replace(".", " / ").title(),
            facet_kind=kind,
            domain=pattern_match.domain,
            canonical_question=pattern_match.canonical_question,
        )

        facets[facet_id] = facet
        self.stats["facets_created"] += 1

        return facet

    def _map_value_kind_to_facet_kind(self, value_kind: str) -> FacetKind:
        """
        Mappe un value_kind de ClaimKey vers FacetKind.

        Args:
            value_kind: Type de valeur ("percent", "version", "boolean", etc.)

        Returns:
            FacetKind correspondant
        """
        mapping = {
            "percent": FacetKind.CAPABILITY,
            "version": FacetKind.LIMITATION,
            "boolean": FacetKind.CAPABILITY,
            "number": FacetKind.LIMITATION,
            "enum": FacetKind.OBLIGATION,
            "string": FacetKind.DOMAIN,
        }
        return mapping.get(value_kind, FacetKind.DOMAIN)

    def _match_predefined_facets(
        self,
        claim: Claim,
        facets: Dict[str, Facet],
    ) -> List[Facet]:
        """
        Matche une claim contre les facettes prédéfinies par keywords.

        Args:
            claim: Claim à analyser
            facets: Facettes disponibles

        Returns:
            Liste des facettes matchées
        """
        matched: List[Facet] = []
        claim_text_lower = claim.text.lower()

        # Keywords par domaine
        domain_keywords = {
            "security": ["security", "secure", "encryption", "encrypted", "tls", "ssl", "authentication", "access control"],
            "security.encryption": ["encryption", "encrypted", "tls", "ssl", "aes", "rsa", "cipher"],
            "security.authentication": ["authentication", "authenticate", "sso", "saml", "oauth", "mfa", "2fa"],
            "compliance": ["compliance", "compliant", "gdpr", "hipaa", "sox", "iso", "certification"],
            "compliance.gdpr": ["gdpr", "data protection", "privacy", "personal data", "data subject"],
            "operations": ["operation", "backup", "restore", "monitoring", "patch", "update"],
            "operations.backup": ["backup", "restore", "recovery", "snapshot"],
            "sla": ["sla", "availability", "uptime", "downtime", "rto", "rpo"],
            "sla.availability": ["availability", "uptime", "99.9%", "99.5%"],
        }

        for domain, keywords in domain_keywords.items():
            for keyword in keywords:
                if keyword in claim_text_lower:
                    # Trouver la facette correspondante
                    facet_id = f"facet_{domain.replace('.', '_')}_domain"
                    # Essayer aussi sans le suffixe
                    if facet_id not in facets:
                        facet_id = f"facet_{domain.replace('.', '_')}"

                    facet = facets.get(facet_id)
                    if facet and facet not in matched:
                        matched.append(facet)
                    break  # Un keyword suffit par domaine

        return matched

    def get_stats(self) -> dict:
        """Retourne les statistiques de matching."""
        return dict(self.stats)

    def reset_stats(self) -> None:
        """Réinitialise les statistiques."""
        self.stats = {
            "claims_processed": 0,
            "patterns_matched": 0,
            "facets_created": 0,
            "links_created": 0,
        }


__all__ = [
    "FacetMatcher",
]
