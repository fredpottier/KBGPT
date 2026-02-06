# src/knowbase/claimfirst/extractors/entity_extractor.py
"""
EntityExtractor - Extraction d'entités enrichie (pas juste NER).

INV-4: Entity sans rôle structurant (V1)
- Pas de `role` (primary/secondary) — reporté à V2
- La relation `ABOUT` existe mais sans attribut `role` pour commencer
- Toutes les mentions sont équivalentes en V1
- L'heuristique "premier tiers = primary" est trop fragile

INV-5: EntityExtractor enrichi (pas juste NER)
Sources d'extraction (déterministes, pas LLM):
1. Termes capitalisés répétés dans le claim
2. Titres de sections / headings du passage source
3. Acronymes (pattern [A-Z]{2,})
4. Patterns syntaxiques: "X is ...", "X allows ...", "X must ..."
5. Stoplist métier: exclure "System", "Information", "Data", "Service"

Règle: Entity ne porte AUCUNE vérité. Pas de rôle structurant.
"""

from __future__ import annotations

import re
import logging
import uuid
from collections import Counter
from typing import Dict, List, Optional, Set, Tuple

from knowbase.claimfirst.models.claim import Claim
from knowbase.claimfirst.models.entity import (
    Entity,
    EntityType,
    ENTITY_STOPLIST,
    is_valid_entity_name,
)
from knowbase.claimfirst.models.passage import Passage

logger = logging.getLogger(__name__)


# Patterns syntaxiques pour extraction de sujets
SUBJECT_PATTERNS = [
    # "X is ..." patterns
    (r"^([A-Z][A-Za-z0-9\s\-/]+?)\s+is\s+", EntityType.CONCEPT),
    (r"^([A-Z][A-Za-z0-9\s\-/]+?)\s+are\s+", EntityType.CONCEPT),

    # "X allows ..." patterns
    (r"^([A-Z][A-Za-z0-9\s\-/]+?)\s+allows?\s+", EntityType.PRODUCT),
    (r"^([A-Z][A-Za-z0-9\s\-/]+?)\s+enables?\s+", EntityType.PRODUCT),
    (r"^([A-Z][A-Za-z0-9\s\-/]+?)\s+provides?\s+", EntityType.PRODUCT),
    (r"^([A-Z][A-Za-z0-9\s\-/]+?)\s+supports?\s+", EntityType.PRODUCT),

    # "X must/shall ..." patterns (prescriptive)
    (r"^([A-Z][A-Za-z0-9\s\-/]+?)\s+must\s+", EntityType.ACTOR),
    (r"^([A-Z][A-Za-z0-9\s\-/]+?)\s+shall\s+", EntityType.ACTOR),
    (r"^([A-Z][A-Za-z0-9\s\-/]+?)\s+should\s+", EntityType.ACTOR),
    (r"^([A-Z][A-Za-z0-9\s\-/]+?)\s+may\s+", EntityType.ACTOR),

    # "X requires ..." patterns
    (r"^([A-Z][A-Za-z0-9\s\-/]+?)\s+requires?\s+", EntityType.PRODUCT),

    # NOTE: Aucun pattern domain-specific (INV-25 agnosticisme)
    # La canonicalisation LLM (EntityCanonicalizer) gère les variantes
]

# Pattern pour acronymes
ACRONYM_PATTERN = re.compile(r"\b([A-Z]{2,}(?:/[A-Z]+)?)\b")

# Pattern pour termes capitalisés
CAPITALIZED_TERM_PATTERN = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")

# Pattern pour termes techniques (CamelCase)
CAMELCASE_PATTERN = re.compile(r"\b([A-Z][a-z]+[A-Z][A-Za-z0-9]+)\b")


class EntityExtractor:
    """
    Extracteur d'entités sans LLM.

    Sources multiples, stoplist métier, tolérant au bruit.
    Pas de rôle structurant en V1 (INV-4).
    """

    def __init__(
        self,
        min_mentions: int = 1,
        max_entities_per_claim: int = 5,
        max_entity_length: int = 60,
        max_entity_words: int = 6,
        custom_stoplist: Optional[Set[str]] = None,
    ):
        """
        Initialise l'extracteur.

        Args:
            min_mentions: Nombre minimal de mentions pour garder une entité
            max_entities_per_claim: Nombre max d'entités par claim
            max_entity_length: Longueur max d'un nom d'entité (caractères)
            max_entity_words: Nombre max de mots dans un nom d'entité
            custom_stoplist: Stoplist personnalisée (en plus de la défaut)
        """
        self.min_mentions = min_mentions
        self.max_entities_per_claim = max_entities_per_claim
        self.max_entity_length = max_entity_length
        self.max_entity_words = max_entity_words

        # Stoplist combinée
        self.stoplist = ENTITY_STOPLIST.copy()
        if custom_stoplist:
            self.stoplist = self.stoplist | {s.lower() for s in custom_stoplist}

        # Stats
        self.stats = {
            "candidates_found": 0,
            "entities_created": 0,
            "filtered_by_stoplist": 0,
            "filtered_by_length": 0,
            "filtered_by_too_long": 0,
            "filtered_by_too_many_words": 0,
        }

    def extract_from_claims(
        self,
        claims: List[Claim],
        passages: List[Passage],
        tenant_id: str,
    ) -> Tuple[List[Entity], Dict[str, List[str]]]:
        """
        Extrait les entités depuis les claims et passages.

        Args:
            claims: Claims à analyser
            passages: Passages pour contexte (titres de section)
            tenant_id: Tenant ID

        Returns:
            Tuple (entities, claim_entity_map) où claim_entity_map est
            un dict claim_id → [entity_ids]
        """
        # Index des passages par ID
        passage_map = {p.passage_id: p for p in passages}

        # Collecter tous les candidats avec leur source
        all_candidates: Counter = Counter()
        claim_candidates: Dict[str, List[Tuple[str, EntityType]]] = {}

        for claim in claims:
            candidates = self._extract_candidates_from_claim(claim, passage_map)
            claim_candidates[claim.claim_id] = candidates

            for name, _ in candidates:
                all_candidates[name] += 1
                self.stats["candidates_found"] += 1

        # Filtrer et créer les entités
        entities: Dict[str, Entity] = {}  # normalized_name → Entity
        claim_entity_map: Dict[str, List[str]] = {}

        for claim_id, candidates in claim_candidates.items():
            entity_ids = []

            for name, entity_type in candidates:
                normalized = Entity.normalize(name)

                # Filtrer stoplist
                if normalized in self.stoplist:
                    self.stats["filtered_by_stoplist"] += 1
                    continue

                # Filtrer trop court
                if len(normalized) < 2:
                    self.stats["filtered_by_length"] += 1
                    continue

                # Filtrer mentions rares (si configuré)
                if self.min_mentions > 1 and all_candidates[name] < self.min_mentions:
                    continue

                # Créer ou réutiliser l'entité
                if normalized not in entities:
                    entity = Entity(
                        entity_id=f"entity_{uuid.uuid4().hex[:12]}",
                        tenant_id=tenant_id,
                        name=name,
                        entity_type=entity_type,
                        normalized_name=normalized,
                        aliases=[],
                        source_doc_ids=[],
                        mention_count=1,
                    )
                    entities[normalized] = entity
                    self.stats["entities_created"] += 1
                else:
                    # Mettre à jour le compteur
                    entities[normalized].mention_count += 1

                entity_ids.append(entities[normalized].entity_id)

                # Limiter le nombre d'entités par claim
                if len(entity_ids) >= self.max_entities_per_claim:
                    break

            claim_entity_map[claim_id] = list(set(entity_ids))  # Dedup

        logger.info(
            f"[OSMOSE:EntityExtractor] Extracted {len(entities)} unique entities "
            f"from {len(claims)} claims "
            f"(filtered: {self.stats['filtered_by_stoplist']} stoplist, "
            f"{self.stats['filtered_by_length']} length)"
        )

        return list(entities.values()), claim_entity_map

    def _extract_candidates_from_claim(
        self,
        claim: Claim,
        passage_map: Dict[str, Passage],
    ) -> List[Tuple[str, EntityType]]:
        """
        Extrait les candidats entités d'une claim.

        Sources:
        1. Termes capitalisés répétés
        2. Titres de sections
        3. Acronymes
        4. Patterns syntaxiques
        """
        candidates: List[Tuple[str, EntityType]] = []
        text = claim.text

        # Source 1: Patterns syntaxiques (priorité haute)
        for pattern, entity_type in SUBJECT_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                if self._is_valid_candidate(name):
                    candidates.append((name, entity_type))

        # Source 2: Acronymes
        for match in ACRONYM_PATTERN.finditer(text):
            acronym = match.group(1)
            if len(acronym) >= 2 and self._is_valid_candidate(acronym):
                candidates.append((acronym, EntityType.CONCEPT))

        # Source 3: Termes capitalisés (multi-mots)
        for match in CAPITALIZED_TERM_PATTERN.finditer(text):
            term = match.group(1)
            if self._is_valid_candidate(term):
                candidates.append((term, EntityType.CONCEPT))

        # Source 4: CamelCase
        for match in CAMELCASE_PATTERN.finditer(text):
            term = match.group(1)
            if self._is_valid_candidate(term):
                candidates.append((term, EntityType.PRODUCT))

        # Source 5: Titre de section du passage source
        passage = passage_map.get(claim.passage_id)
        if passage and passage.section_title:
            title = passage.section_title.strip()
            if self._is_valid_candidate(title):
                candidates.append((title, EntityType.CONCEPT))

        # Dedup en préservant l'ordre
        seen = set()
        unique_candidates = []
        for name, etype in candidates:
            normalized = Entity.normalize(name)
            if normalized not in seen:
                seen.add(normalized)
                unique_candidates.append((name, etype))

        return unique_candidates

    def _is_valid_candidate(self, name: str) -> bool:
        """
        Vérifie si un candidat est valide.

        Critères:
        - Pas dans la stoplist
        - Longueur minimale (2 caractères normalisés)
        - Longueur maximale (évite les phrases)
        - Nombre de mots limité (évite les descriptions)
        - Pas que des chiffres
        - Ne commence pas par un article/pronom (signe de phrase)
        """
        if not name:
            return False

        normalized = Entity.normalize(name)

        # Stoplist
        if normalized in self.stoplist:
            return False

        # Longueur minimale
        if len(normalized) < 2:
            return False

        # Longueur maximale (évite les phrases)
        if len(name) > self.max_entity_length:
            self.stats["filtered_by_too_long"] += 1
            return False

        # Nombre de mots limité (évite les descriptions)
        word_count = len(name.split())
        if word_count > self.max_entity_words:
            self.stats["filtered_by_too_many_words"] += 1
            return False

        # Pas que des chiffres
        if normalized.replace("-", "").replace(" ", "").isdigit():
            return False

        # Ne commence pas par un article/pronom/verbe (signe de phrase incomplète)
        phrase_starters = {
            "the", "a", "an", "this", "that", "these", "those",
            "it", "they", "we", "you", "he", "she",
            "built-in", "recommendations", "future", "combined",
        }
        first_word = name.split()[0].lower() if name.split() else ""
        if first_word in phrase_starters:
            return False

        return True

    def infer_entity_type(self, name: str, context: str = "") -> EntityType:
        """
        Infère le type d'entité depuis le nom et le contexte.

        Heuristiques simples sans LLM.
        """
        name_lower = name.lower()
        context_lower = context.lower()

        # SAP products
        if "sap" in name_lower or name.startswith("S/"):
            return EntityType.PRODUCT

        # Standards / Certifications
        if any(std in name_lower for std in ["iso", "soc", "hipaa", "gdpr", "pci"]):
            return EntityType.STANDARD

        # Acteurs
        if any(actor in name_lower for actor in ["customer", "administrator", "user", "vendor"]):
            return EntityType.ACTOR

        # Services (suffixes courants)
        if any(suffix in name_lower for suffix in ["service", "connector", "adapter", "api"]):
            return EntityType.SERVICE

        # Features
        if any(feat in context_lower for feat in ["feature", "capability", "function"]):
            return EntityType.FEATURE

        # Legal terms
        if any(legal in name_lower for legal in ["agreement", "contract", "liability", "warranty"]):
            return EntityType.LEGAL_TERM

        # Default
        return EntityType.CONCEPT

    def get_stats(self) -> dict:
        """Retourne les statistiques d'extraction."""
        return dict(self.stats)

    def reset_stats(self) -> None:
        """Réinitialise les statistiques."""
        self.stats = {
            "candidates_found": 0,
            "entities_created": 0,
            "filtered_by_stoplist": 0,
            "filtered_by_length": 0,
            "filtered_by_too_long": 0,
            "filtered_by_too_many_words": 0,
        }


__all__ = [
    "EntityExtractor",
    "SUBJECT_PATTERNS",
    "ACRONYM_PATTERN",
    "CAPITALIZED_TERM_PATTERN",
]
