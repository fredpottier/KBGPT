# src/knowbase/claimfirst/linkers/entity_linker.py
"""
EntityLinker - Linking déterministe Claim → Entity.

INV-4: Entity sans rôle structurant (V1)
- Pas de `role` (primary/secondary) — reporté à V2
- La relation `ABOUT` existe mais sans attribut `role` pour commencer
- Toutes les mentions sont équivalentes en V1
- L'heuristique "premier tiers = primary" est trop fragile

Pas de LLM - matching textuel simple.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Tuple

from knowbase.claimfirst.models.claim import Claim
from knowbase.claimfirst.models.entity import Entity

logger = logging.getLogger(__name__)


class EntityLinker:
    """
    Linking déterministe Claim → Entity.

    V1: pas de role (primary/secondary) — toutes mentions équivalentes.

    Utilise le matching textuel:
    - normalized_name dans claim.text
    - aliases dans claim.text
    """

    def __init__(
        self,
        case_sensitive: bool = False,
        min_entity_length: int = 2,
    ):
        """
        Initialise le linker.

        Args:
            case_sensitive: Si True, matching case-sensitive
            min_entity_length: Longueur minimale d'entité pour matcher
        """
        self.case_sensitive = case_sensitive
        self.min_entity_length = min_entity_length

        self.stats = {
            "claims_processed": 0,
            "links_created": 0,
            "entities_matched": 0,
            "claims_with_entities": 0,
        }

    def link(
        self,
        claims: List[Claim],
        entities: List[Entity],
    ) -> List[Tuple[str, str]]:
        """
        Établit les liens Claim → Entity.

        Args:
            claims: Claims à lier
            entities: Entités disponibles

        Returns:
            Liste de tuples (claim_id, entity_id) pour relation ABOUT
            Note: Pas de {role} en V1 (INV-4)
        """
        links: List[Tuple[str, str]] = []

        # Index des entités par normalized_name
        entity_by_normalized: Dict[str, Entity] = {
            e.normalized_name: e for e in entities if e.normalized_name
        }

        # Index des alias → entity
        alias_to_entity: Dict[str, Entity] = {}
        for entity in entities:
            for alias in entity.aliases:
                normalized_alias = self._normalize(alias)
                if normalized_alias:
                    alias_to_entity[normalized_alias] = entity

        matched_entities: set = set()

        for claim in claims:
            self.stats["claims_processed"] += 1
            claim_entities = []

            # Normaliser le texte de la claim
            claim_text = self._normalize(claim.text) if not self.case_sensitive else claim.text

            # Chercher les entités dans le texte
            for normalized, entity in entity_by_normalized.items():
                if len(normalized) < self.min_entity_length:
                    continue

                # Match sur normalized_name
                if self._matches(normalized, claim_text):
                    claim_entities.append(entity)
                    matched_entities.add(entity.entity_id)
                    continue

                # Match sur le nom original (préserve casse pour acronymes)
                original_name = entity.name.lower() if not self.case_sensitive else entity.name
                if self._matches(original_name, claim_text):
                    claim_entities.append(entity)
                    matched_entities.add(entity.entity_id)

            # Chercher via alias
            for alias_normalized, entity in alias_to_entity.items():
                if entity.entity_id in matched_entities:
                    continue  # Déjà matché
                if len(alias_normalized) < self.min_entity_length:
                    continue

                if self._matches(alias_normalized, claim_text):
                    claim_entities.append(entity)
                    matched_entities.add(entity.entity_id)

            # Créer les liens
            for entity in claim_entities:
                links.append((claim.claim_id, entity.entity_id))
                self.stats["links_created"] += 1

            if claim_entities:
                self.stats["claims_with_entities"] += 1

        self.stats["entities_matched"] = len(matched_entities)

        logger.info(
            f"[OSMOSE:EntityLinker] Created {len(links)} links "
            f"({self.stats['entities_matched']} unique entities, "
            f"{self.stats['claims_with_entities']}/{len(claims)} claims with entities)"
        )

        return links

    def _normalize(self, text: str) -> str:
        """Normalise le texte pour matching."""
        if not text:
            return ""
        return text.lower().strip()

    def _matches(self, entity_text: str, claim_text: str) -> bool:
        """
        Vérifie si une entité est mentionnée dans le texte de la claim.

        Utilise une recherche de sous-chaîne avec boundary checking
        pour éviter les faux positifs (ex: "API" dans "CAPITAL").
        """
        if not entity_text or not claim_text:
            return False

        # Recherche simple de sous-chaîne
        pos = claim_text.find(entity_text)
        if pos == -1:
            return False

        # Vérifier les boundaries (éviter partial matches)
        # Un match est valide si entouré de non-alphanumériques
        start_ok = pos == 0 or not claim_text[pos - 1].isalnum()
        end_pos = pos + len(entity_text)
        end_ok = end_pos >= len(claim_text) or not claim_text[end_pos].isalnum()

        return start_ok and end_ok

    def link_with_confidence(
        self,
        claims: List[Claim],
        entities: List[Entity],
    ) -> List[Tuple[str, str, float]]:
        """
        Établit les liens avec un score de confiance.

        Scores basés sur:
        - Match exact: 1.0
        - Match normalisé: 0.9
        - Match alias: 0.8

        Args:
            claims: Claims à lier
            entities: Entités disponibles

        Returns:
            Liste de tuples (claim_id, entity_id, confidence)
        """
        links: List[Tuple[str, str, float]] = []

        for claim in claims:
            claim_text = self._normalize(claim.text)
            claim_text_original = claim.text

            for entity in entities:
                confidence = 0.0

                # Match exact (nom original, case-sensitive)
                if entity.name in claim_text_original:
                    confidence = 1.0
                # Match normalisé
                elif self._matches(entity.normalized_name, claim_text):
                    confidence = 0.9
                # Match alias
                else:
                    for alias in entity.aliases:
                        if self._matches(self._normalize(alias), claim_text):
                            confidence = 0.8
                            break

                if confidence > 0:
                    links.append((claim.claim_id, entity.entity_id, confidence))

        return links

    def get_stats(self) -> dict:
        """Retourne les statistiques de linking."""
        return dict(self.stats)

    def reset_stats(self) -> None:
        """Réinitialise les statistiques."""
        self.stats = {
            "claims_processed": 0,
            "links_created": 0,
            "entities_matched": 0,
            "claims_with_entities": 0,
        }


__all__ = [
    "EntityLinker",
]
