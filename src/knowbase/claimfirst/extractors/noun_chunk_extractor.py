# src/knowbase/claimfirst/extractors/noun_chunk_extractor.py
"""
NounChunkExtractor — Extraction d'entités text-anchored via spaCy noun chunks.

Résout le problème des corpus non-techniques (réglementaire, finance, RH, etc.)
où les entités sont des concepts en minuscules que le regex ne capte pas.

Chaque entité extraite est un SPAN EXACT du texte source — pas d'interprétation
LLM, pas de normalisation sémantique. L'invariant "pas d'assertion sans preuve
localisable" est strictement respecté.

Pipeline :
1. spaCy noun_chunks (parsing syntaxique)
2. Nettoyage déterministe (retrait déterminants, filtrage longueur)
3. Filtrage IDF (exclusion termes trop génériques ou trop rares)
4. Déduplication par normalized_name
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Déterminants et pronoms à retirer en début de noun chunk
_DETERMINERS = {
    # EN
    "the", "a", "an", "this", "that", "these", "those",
    "its", "their", "our", "your", "his", "her", "my",
    "some", "any", "each", "every", "all", "no",
    # FR
    "le", "la", "les", "l'", "un", "une", "des",
    "ce", "cet", "cette", "ces", "son", "sa", "ses",
    "mon", "ma", "mes", "ton", "ta", "tes",
    "leur", "leurs", "notre", "nos", "votre", "vos",
    "du", "de", "d'", "au", "aux",
}

# Pronoms à rejeter entièrement
_PRONOUNS = {
    "it", "they", "we", "he", "she", "you", "i",
    "them", "us", "him", "her", "me",
    "this", "that", "which", "who", "what",
    "il", "elle", "ils", "elles", "on", "nous", "vous", "je", "tu",
}

# Mots trop vagues comme entité standalone (1 mot)
_VAGUE_STANDALONE = {
    # EN — termes trop génériques pour être des entités utiles
    "case", "way", "part", "use", "order", "time", "place",
    "fact", "purpose", "basis", "view", "end", "regard",
    "account", "means", "need", "result", "respect", "act",
    "risks", "risk", "decisions", "decision", "development",
    "approaches", "approach", "users", "user", "information",
    "system", "systems", "process", "processes", "level",
    "measures", "measure", "requirements", "requirement",
    "provisions", "provision", "rules", "rule", "conditions",
    "principles", "principle", "standards", "standard",
    "rights", "right", "obligations", "obligation",
    "practices", "practice", "activities", "activity",
    "services", "service", "actions", "action",
    "data", "persons", "person", "bodies", "body",
    "authorities", "authority", "parties", "party",
    "areas", "area", "types", "type", "forms", "form",
    "cases", "purposes", "situations", "situation",
    "context", "scope", "impact", "nature", "extent",
    "manner", "terms", "aspects", "matters", "issues",
    "features", "functions", "elements", "factors",
    "procedures", "mechanisms", "frameworks", "models",
    "categories", "groups", "sets", "lists",
    "governance", "compliance", "transparency", "regulation",
    # FR — équivalents
    "cas", "fait", "lieu", "fin", "base", "vue", "moyen",
    "risques", "risque", "données", "système", "systèmes",
    "mesures", "mesure", "niveau", "droit", "droits",
    "règles", "règle", "obligations", "obligation",
    "personnes", "personne", "autorités", "autorité",
}

# Longueur min/max
MIN_CHUNK_CHARS = 3
MAX_CHUNK_CHARS = 60
MIN_CHUNK_WORDS = 1
MAX_CHUNK_WORDS = 6


def _clean_chunk(text: str) -> Optional[str]:
    """Nettoie un noun chunk : retrait déterminants, normalisation."""
    words = text.strip().split()
    if not words:
        return None

    # Rejeter si c'est un pronom seul
    if len(words) == 1 and words[0].lower() in _PRONOUNS:
        return None

    # Retirer les déterminants en début
    while words and words[0].lower() in _DETERMINERS:
        words = words[1:]

    if not words:
        return None

    result = " ".join(words).strip()

    # Retirer ponctuation en début/fin
    result = result.strip(".,;:!?()[]{}\"'")

    if not result or len(result) < MIN_CHUNK_CHARS:
        return None

    return result


def _normalize(name: str) -> str:
    """Normalise un nom d'entité (lowercase, strip, collapse spaces)."""
    return re.sub(r"\s+", " ", name.lower().strip())


class NounChunkExtractor:
    """
    Extrait des entités text-anchored depuis les noun chunks spaCy.

    Usage :
        extractor = NounChunkExtractor()
        entities, links = extractor.extract_from_claims(claims, tenant_id)
    """

    def __init__(
        self,
        min_idf: float = 0.0,
        max_idf: float = 100.0,
        use_idf_filter: bool = True,
        custom_stoplist: Optional[Set[str]] = None,
        domain_terms: Optional[Set[str]] = None,
    ):
        self._nlp_en = None
        self._nlp_fr = None
        self.min_idf = min_idf
        self.max_idf = max_idf
        self.use_idf_filter = use_idf_filter
        self.custom_stoplist = custom_stoplist or set()
        self.domain_terms = {t.lower() for t in (domain_terms or set())}
        self.stats = Counter()

    def _get_nlp(self, lang: str):
        """Charge le modèle spaCy (lazy init)."""
        if lang == "fr":
            if self._nlp_fr is None:
                import spacy
                self._nlp_fr = spacy.load("fr_core_news_md", disable=["ner", "textcat"])
                logger.info("[NounChunkExtractor] Loaded fr_core_news_md")
            return self._nlp_fr
        else:
            if self._nlp_en is None:
                import spacy
                self._nlp_en = spacy.load("en_core_web_md", disable=["ner", "textcat"])
                logger.info("[NounChunkExtractor] Loaded en_core_web_md")
            return self._nlp_en

    def _detect_lang(self, text: str) -> str:
        """Détection de langue simplifiée."""
        fr_indicators = {"le ", "la ", "les ", "des ", "du ", "un ", "une ", "est ", "sont ", "dans "}
        text_lower = text[:200].lower()
        fr_score = sum(1 for ind in fr_indicators if ind in text_lower)
        return "fr" if fr_score >= 2 else "en"

    def _is_valid_chunk(self, cleaned: str, idf_checker=None) -> bool:
        """Vérifie si un noun chunk nettoyé est une entité valide."""
        norm = _normalize(cleaned)

        # Longueur
        if len(cleaned) > MAX_CHUNK_CHARS:
            self.stats["filtered_too_long"] += 1
            return False

        words = cleaned.split()
        if len(words) > MAX_CHUNK_WORDS:
            self.stats["filtered_too_many_words"] += 1
            return False

        # Mot unique : gardé SEULEMENT s'il est dans domain_terms du pack actif
        if len(words) == 1:
            if self.domain_terms and norm in self.domain_terms:
                self.stats["mono_word_domain_term"] += 1
                # Accepté — c'est un terme métier connu du domain pack
            else:
                self.stats["filtered_mono_word"] += 1
                return False

        # Stoplist custom
        if norm in self.custom_stoplist:
            self.stats["filtered_stoplist"] += 1
            return False

        # Que des chiffres
        if norm.replace("-", "").replace(" ", "").replace(".", "").isdigit():
            self.stats["filtered_numeric"] += 1
            return False

        # Contient des chiffres (ex: "180 days", "42 agencies", "60 percent")
        if re.search(r"\d", cleaned):
            self.stats["filtered_has_number"] += 1
            return False

        # Commence par un déictique (ex: "such data", "other circumstances")
        if words[0].lower() in {
            "such", "other", "certain", "another", "further",
            "same", "own", "every", "any", "no",
        }:
            self.stats["filtered_deictic"] += 1
            return False

        # IDF filter
        if self.use_idf_filter and idf_checker:
            if idf_checker(norm):
                self.stats["filtered_idf_generic"] += 1
                return False

        return True

    def extract_from_text(
        self,
        text: str,
        idf_checker=None,
    ) -> List[Tuple[str, int, int]]:
        """
        Extrait les noun chunks valides d'un texte.

        Returns:
            Liste de (cleaned_text, start_char, end_char)
        """
        lang = self._detect_lang(text)
        nlp = self._get_nlp(lang)
        doc = nlp(text)

        results = []
        seen_norms = set()

        for chunk in doc.noun_chunks:
            self.stats["chunks_total"] += 1

            cleaned = _clean_chunk(chunk.text)
            if not cleaned:
                self.stats["filtered_cleaning"] += 1
                continue

            norm = _normalize(cleaned)
            if norm in seen_norms:
                self.stats["filtered_dedup"] += 1
                continue

            if not self._is_valid_chunk(cleaned, idf_checker):
                continue

            seen_norms.add(norm)
            results.append((cleaned, chunk.start_char, chunk.end_char))
            self.stats["chunks_accepted"] += 1

        return results

    def extract_from_claims(
        self,
        claims,
        tenant_id: str,
        existing_entity_index: Optional[Dict[str, str]] = None,
        idf_checker=None,
    ) -> Tuple[list, List[Tuple[str, str]]]:
        """
        Extrait des entités noun-chunk depuis une liste de claims.

        Args:
            claims: Liste de Claim objects (avec .claim_id et .text)
            tenant_id: Tenant ID
            existing_entity_index: Dict normalized_name → entity_id pour réutiliser les entités existantes
            idf_checker: Callable(normalized_name) → bool (True = trop générique, filtrer)

        Returns:
            (new_entities, links) où links = [(claim_id, entity_id), ...]
        """
        import uuid
        from knowbase.claimfirst.models.entity import Entity, EntityType

        existing_index = existing_entity_index or {}
        new_entities: Dict[str, Entity] = {}  # norm → Entity
        links: List[Tuple[str, str]] = []

        for claim in claims:
            chunks = self.extract_from_text(claim.text, idf_checker)

            for cleaned, start, end in chunks:
                norm = _normalize(cleaned)

                # Chercher dans les entités existantes
                entity_id = existing_index.get(norm)

                # Chercher dans les nouvelles entités déjà créées
                if not entity_id and norm in new_entities:
                    entity_id = new_entities[norm].entity_id

                # Créer une nouvelle entité
                if not entity_id:
                    entity = Entity(
                        entity_id=f"entity_{uuid.uuid4().hex[:12]}",
                        tenant_id=tenant_id,
                        name=cleaned,
                        entity_type=EntityType.CONCEPT,
                        normalized_name=norm,
                        aliases=[],
                        source_doc_ids=[],
                        mention_count=1,
                    )
                    new_entities[norm] = entity
                    entity_id = entity.entity_id
                    self.stats["entities_created"] += 1
                else:
                    self.stats["entities_reused"] += 1

                links.append((claim.claim_id, entity_id))

        logger.info(
            f"[NounChunkExtractor] {self.stats['chunks_total']} chunks, "
            f"{self.stats['chunks_accepted']} accepted, "
            f"{self.stats['entities_created']} new entities, "
            f"{self.stats['entities_reused']} reused, "
            f"{len(links)} links"
        )

        return list(new_entities.values()), links
