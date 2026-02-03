# src/knowbase/claimfirst/extractors/context_extractor.py
"""
ContextExtractor - Extrait le contexte d'applicabilité d'un document.

INV-8: Applicability over Truth (Scope Épistémique)

Sources d'extraction:
1. Titre du document
2. Métadonnées (si disponibles)
3. Première page / préface
4. Headers récurrents

INV-10: Discriminants Découverts, pas Hardcodés

Les attributs discriminants (version, region, motorisation, dosage...)
sont découverts depuis le corpus, pas imposés a priori.

CORRECTIF 2: Bootstrap patterns vs Discovery
- BOOTSTRAP_QUALIFIERS = mini-set pour accélérer sur corpus classiques
- ⚠️ Ce ne sont PAS des patterns "universels", juste un kickstart
- Discovery pipeline propose de NOUVELLES clés au fur et à mesure
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from knowbase.claimfirst.models.document_context import (
    DocumentContext,
    extract_bootstrap_qualifiers,
)
from knowbase.claimfirst.models.passage import Passage

logger = logging.getLogger(__name__)


# Patterns pour détecter le titre du document
TITLE_PATTERNS = [
    re.compile(r"^(.+?)\s*[-–—]\s*(?:Operations|Security|Administration)\s+Guide", re.IGNORECASE),
    re.compile(r"^(.+?)\s+(?:Documentation|Manual|Guide|Reference)", re.IGNORECASE),
    re.compile(r"^(?:Guide|Manual|Documentation)\s+(?:for|of)\s+(.+)", re.IGNORECASE),
]

# Patterns pour extraire les sujets du texte
SUBJECT_EXTRACTION_PATTERNS = [
    re.compile(r"This document describes\s+(.+?)(?:\.|,|$)", re.IGNORECASE),
    re.compile(r"This guide covers\s+(.+?)(?:\.|,|$)", re.IGNORECASE),
    re.compile(r"(?:Introduction to|Overview of|About)\s+(.+?)(?:\.|,|$)", re.IGNORECASE),
    re.compile(r"^(.+?)\s+is\s+(?:a|an|the)\s+", re.IGNORECASE),
]

# Patterns pour détecter le type de document
DOCUMENT_TYPE_PATTERNS = {
    "Operations Guide": re.compile(r"operations?\s+guide", re.IGNORECASE),
    "Security Guide": re.compile(r"security\s+guide", re.IGNORECASE),
    "Administration Guide": re.compile(r"administration?\s+guide", re.IGNORECASE),
    "Technical Documentation": re.compile(r"technical\s+(?:documentation|manual)", re.IGNORECASE),
    "User Guide": re.compile(r"user(?:'s)?\s+guide", re.IGNORECASE),
    "Reference Manual": re.compile(r"reference\s+manual", re.IGNORECASE),
    "Release Notes": re.compile(r"release\s+notes", re.IGNORECASE),
    "White Paper": re.compile(r"white\s*paper", re.IGNORECASE),
    "Legal Document": re.compile(r"(?:terms|privacy|agreement|contract)", re.IGNORECASE),
}


class ContextExtractor:
    """
    Extrait le contexte d'applicabilité d'un document.

    Sources:
    1. Titre du document
    2. Métadonnées (si disponibles)
    3. Première page / préface
    4. Headers récurrents

    INV-10: Les qualificateurs sont découverts du corpus, pas hardcodés.
    """

    def __init__(
        self,
        llm_client: Any = None,
        use_llm_subjects: bool = True,
    ):
        """
        Initialise l'extracteur de contexte.

        Args:
            llm_client: Client LLM pour extraction avancée (optionnel)
            use_llm_subjects: Si True, utilise LLM pour extraire les sujets
        """
        self.llm_client = llm_client
        self.use_llm_subjects = use_llm_subjects and llm_client is not None

        # Stats
        self._stats = {
            "documents_processed": 0,
            "subjects_extracted": 0,
            "qualifiers_found": 0,
            "llm_calls": 0,
        }

    def extract(
        self,
        doc_id: str,
        tenant_id: str,
        passages: List[Passage],
        doc_title: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DocumentContext:
        """
        Extrait le DocumentContext depuis les Passages.

        Args:
            doc_id: ID du document
            tenant_id: Tenant ID
            passages: Liste des Passages du document
            doc_title: Titre du document (si connu)
            metadata: Métadonnées additionnelles

        Returns:
            DocumentContext configuré
        """
        self._stats["documents_processed"] += 1

        # Récupérer le texte des premiers passages (préface/intro)
        first_passages_text = self._get_first_passages_text(passages, max_chars=5000)

        # 1. Extraire les sujets candidats
        raw_subjects = self._extract_subject_candidates(
            passages=passages,
            doc_title=doc_title,
            first_text=first_passages_text,
            metadata=metadata,
        )
        self._stats["subjects_extracted"] += len(raw_subjects)

        # 2. Extraire les qualificateurs (INV-10: découverts, pas hardcodés)
        qualifiers, qualifier_candidates = self._extract_qualifiers(
            passages=passages,
            first_text=first_passages_text,
            metadata=metadata,
        )
        self._stats["qualifiers_found"] += len(qualifiers)

        # 3. Inférer le type de document
        document_type = self._infer_document_type(
            doc_title=doc_title,
            first_text=first_passages_text,
        )

        # 4. Extraire la portée temporelle
        temporal_scope = self._extract_temporal_scope(
            first_text=first_passages_text,
            metadata=metadata,
        )

        context = DocumentContext(
            doc_id=doc_id,
            tenant_id=tenant_id,
            raw_subjects=raw_subjects,
            qualifiers=qualifiers,
            qualifier_candidates=qualifier_candidates,
            document_type=document_type,
            temporal_scope=temporal_scope,
            extraction_method="llm" if self.use_llm_subjects else "pattern",
        )

        logger.info(
            f"[ContextExtractor] Extracted context for {doc_id}: "
            f"{len(raw_subjects)} subjects, {len(qualifiers)} qualifiers, "
            f"type='{document_type or 'unknown'}'"
        )

        return context

    def _get_first_passages_text(
        self,
        passages: List[Passage],
        max_chars: int = 5000,
    ) -> str:
        """
        Récupère le texte des premiers passages.

        Args:
            passages: Liste des passages
            max_chars: Nombre max de caractères

        Returns:
            Texte concaténé
        """
        text_parts = []
        total_chars = 0

        # Trier par reading_order_index
        sorted_passages = sorted(passages, key=lambda p: p.reading_order_index)

        for passage in sorted_passages:
            if total_chars >= max_chars:
                break
            text_parts.append(passage.text)
            total_chars += len(passage.text)

        return "\n".join(text_parts)[:max_chars]

    def _extract_subject_candidates(
        self,
        passages: List[Passage],
        doc_title: Optional[str],
        first_text: str,
        metadata: Optional[Dict[str, Any]],
    ) -> List[str]:
        """
        Extrait les sujets candidats.

        Heuristiques:
        - Titre du document (si détecté)
        - Métadonnées (si disponibles)
        - Termes en majuscules répétés dans les premiers passages
        - Patterns "This document describes X", "Guide for X"
        - LLM si activé

        Args:
            passages: Passages du document
            doc_title: Titre (optionnel)
            first_text: Texte des premiers passages
            metadata: Métadonnées

        Returns:
            Liste des sujets candidats
        """
        candidates = []

        # 1. Titre du document
        if doc_title:
            subject = self._extract_subject_from_title(doc_title)
            if subject:
                candidates.append(subject)

        # 2. Métadonnées
        if metadata:
            meta_subjects = self._extract_subjects_from_metadata(metadata)
            candidates.extend(meta_subjects)

        # 3. Patterns dans le texte
        pattern_subjects = self._extract_subjects_from_patterns(first_text)
        candidates.extend(pattern_subjects)

        # 4. Termes capitalisés répétés
        capitalized_subjects = self._extract_capitalized_subjects(first_text)
        candidates.extend(capitalized_subjects[:3])  # Limiter à 3

        # 5. LLM si activé
        if self.use_llm_subjects and self.llm_client:
            llm_subjects = self._extract_subjects_with_llm(first_text)
            candidates.extend(llm_subjects)
            self._stats["llm_calls"] += 1

        # Déduplication et normalisation
        seen = set()
        unique_candidates = []
        for candidate in candidates:
            normalized = candidate.strip()
            if normalized and normalized.lower() not in seen:
                seen.add(normalized.lower())
                unique_candidates.append(normalized)

        return unique_candidates[:5]  # Limiter à 5 sujets max

    def _extract_subject_from_title(self, title: str) -> Optional[str]:
        """Extrait le sujet depuis le titre."""
        for pattern in TITLE_PATTERNS:
            match = pattern.search(title)
            if match:
                return match.group(1).strip()

        # Sinon retourner le titre nettoyé
        # Enlever les suffixes courants
        cleaned = re.sub(
            r"\s*[-–—]\s*(?:Operations|Security|Administration|User)\s+Guide.*$",
            "",
            title,
            flags=re.IGNORECASE
        )
        return cleaned.strip() if cleaned else None

    def _extract_subjects_from_metadata(self, metadata: Dict[str, Any]) -> List[str]:
        """Extrait les sujets depuis les métadonnées."""
        subjects = []

        # Clés communes de métadonnées
        subject_keys = ["subject", "product", "service", "topic", "keywords"]
        for key in subject_keys:
            if key in metadata:
                value = metadata[key]
                if isinstance(value, str):
                    subjects.append(value)
                elif isinstance(value, list):
                    subjects.extend(str(v) for v in value if v)

        return subjects

    def _extract_subjects_from_patterns(self, text: str) -> List[str]:
        """Extrait les sujets via patterns regex."""
        subjects = []

        for pattern in SUBJECT_EXTRACTION_PATTERNS:
            match = pattern.search(text)
            if match:
                subject = match.group(1).strip()
                # Nettoyer les fin de phrases
                subject = re.sub(r"[,.].*$", "", subject)
                if len(subject) > 5:  # Ignorer les trop courts
                    subjects.append(subject)

        return subjects

    def _extract_capitalized_subjects(self, text: str) -> List[str]:
        """
        Extrait les termes capitalisés répétés comme sujets potentiels.

        Heuristique: Un nom de produit/service est souvent capitalisé
        et apparaît plusieurs fois.
        """
        # Pattern pour termes capitalisés (2+ mots)
        pattern = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")
        matches = pattern.findall(text)

        # Compter les occurrences
        from collections import Counter
        counts = Counter(matches)

        # Garder ceux qui apparaissent 2+ fois
        candidates = [term for term, count in counts.items() if count >= 2]

        return candidates

    def _extract_subjects_with_llm(self, text: str) -> List[str]:
        """
        Extrait les sujets via LLM.

        Prompt focalisé sur extraction de sujets explicites.
        """
        prompt = """Identify the PRIMARY SUBJECT(S) of this document excerpt.

A subject is:
- A product, service, or solution name (e.g., "SAP S/4HANA", "Azure DevOps")
- A regulation, standard, or framework name (e.g., "GDPR", "ISO 27001")
- A technical topic or domain (e.g., "Cloud Security", "Data Migration")

Return ONLY subjects that are EXPLICITLY mentioned in the text.
Do NOT infer, generalize, or make up subjects.

Format your response as a JSON array of strings:
["Subject 1", "Subject 2"]

If no clear subject is found, return: []

Text:
{text}
""".format(text=text[:3000])  # Limiter la taille

        try:
            response = self.llm_client.chat.completions.create(
                model="gpt-4o-mini",  # Modèle rapide pour extraction
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=200,
            )

            content = response.choices[0].message.content.strip()

            # Parser la réponse JSON
            import json
            # Nettoyer la réponse
            content = re.sub(r"```json\s*", "", content)
            content = re.sub(r"```\s*$", "", content)

            subjects = json.loads(content)
            if isinstance(subjects, list):
                return [s for s in subjects if isinstance(s, str)]

        except Exception as e:
            logger.warning(f"[ContextExtractor] LLM subject extraction failed: {e}")

        return []

    def _extract_qualifiers(
        self,
        passages: List[Passage],
        first_text: str,
        metadata: Optional[Dict[str, Any]],
    ) -> Tuple[Dict[str, str], Dict[str, str]]:
        """
        Découvre les qualificateurs d'applicabilité (INV-10).

        CORRECTIF 2: Bootstrap patterns vs Discovery
        - BOOTSTRAP_QUALIFIERS = mini-set pour accélérer, PAS universel
        - Discovery pipeline propose de nouvelles clés au fur et à mesure

        Args:
            passages: Passages du document
            first_text: Texte des premiers passages
            metadata: Métadonnées

        Returns:
            (qualifiers_validated, qualifier_candidates)
        """
        validated = {}
        candidates = {}

        # 1. Appliquer les patterns bootstrap
        bootstrap_found = extract_bootstrap_qualifiers(first_text)

        # Les patterns bootstrap sont considérés comme validés
        # (patterns universels comme version, region)
        for key in ["version", "region", "edition"]:
            if key in bootstrap_found:
                validated[key] = bootstrap_found[key]

        # year est un candidat (pas toujours pertinent)
        if "year" in bootstrap_found:
            candidates["year"] = bootstrap_found["year"]

        # 2. Chercher dans les métadonnées
        if metadata:
            meta_qualifiers = self._extract_qualifiers_from_metadata(metadata)
            for key, value in meta_qualifiers.items():
                if key in ["version", "region", "edition"]:
                    validated[key] = value
                else:
                    candidates[key] = value

        # 3. Découverte de nouveaux patterns (INV-10)
        # Ces candidats devront être validés par le corpus
        discovered = self._discover_new_qualifiers(first_text, passages)
        for key, value in discovered.items():
            if key not in validated:
                candidates[key] = value

        return validated, candidates

    def _extract_qualifiers_from_metadata(self, metadata: Dict[str, Any]) -> Dict[str, str]:
        """Extrait les qualificateurs depuis les métadonnées."""
        qualifiers = {}

        qualifier_keys = {
            "version": ["version", "release", "product_version"],
            "region": ["region", "geography", "market"],
            "edition": ["edition", "tier", "sku"],
            "language": ["language", "lang", "locale"],
        }

        for canonical_key, meta_keys in qualifier_keys.items():
            for meta_key in meta_keys:
                if meta_key in metadata:
                    qualifiers[canonical_key] = str(metadata[meta_key])
                    break

        return qualifiers

    def _discover_new_qualifiers(
        self,
        first_text: str,
        passages: List[Passage],
    ) -> Dict[str, str]:
        """
        Découvre de nouveaux qualificateurs (INV-10).

        Les patterns découverts sont proposés comme candidats.
        Ils deviennent "officiels" après validation corpus-first.

        Args:
            first_text: Texte des premiers passages
            passages: Tous les passages

        Returns:
            Dict des qualificateurs candidats
        """
        candidates = {}

        # Pattern pour dates (Q1 2024, January 2024, etc.)
        quarter_pattern = re.compile(r"\b(Q[1-4])\s+(\d{4})\b")
        match = quarter_pattern.search(first_text)
        if match:
            candidates["release_quarter"] = f"{match.group(1)} {match.group(2)}"

        # Pattern pour environnements (Production, Staging, etc.)
        env_pattern = re.compile(
            r"\b(Production|Staging|Development|Test)\s+(?:Environment|System)",
            re.IGNORECASE
        )
        match = env_pattern.search(first_text)
        if match:
            candidates["environment"] = match.group(1)

        # Pattern pour tiers/niveaux (Basic, Standard, Premium, etc.)
        tier_pattern = re.compile(
            r"\b(Basic|Standard|Premium|Enterprise|Professional)\s+(?:Tier|Plan|Level)",
            re.IGNORECASE
        )
        match = tier_pattern.search(first_text)
        if match:
            candidates["tier"] = match.group(1)

        return candidates

    def _infer_document_type(
        self,
        doc_title: Optional[str],
        first_text: str,
    ) -> Optional[str]:
        """Infère le type de document."""
        text_to_check = (doc_title or "") + "\n" + first_text[:1000]

        for doc_type, pattern in DOCUMENT_TYPE_PATTERNS.items():
            if pattern.search(text_to_check):
                return doc_type

        return None

    def _extract_temporal_scope(
        self,
        first_text: str,
        metadata: Optional[Dict[str, Any]],
    ) -> Optional[str]:
        """Extrait la portée temporelle."""
        # Pattern "as of <date>"
        as_of_pattern = re.compile(r"as\s+of\s+(\w+\s+\d{4}|\d{4})", re.IGNORECASE)
        match = as_of_pattern.search(first_text)
        if match:
            return f"as of {match.group(1)}"

        # Pattern "effective <date>"
        effective_pattern = re.compile(
            r"effective\s+(\w+\s+\d{1,2},?\s+\d{4}|\d{4})",
            re.IGNORECASE
        )
        match = effective_pattern.search(first_text)
        if match:
            return f"effective {match.group(1)}"

        # Métadonnées
        if metadata:
            for key in ["effective_date", "publication_date", "last_updated"]:
                if key in metadata:
                    return str(metadata[key])

        return None

    def get_stats(self) -> dict:
        """Retourne les statistiques."""
        return dict(self._stats)

    def reset_stats(self) -> None:
        """Réinitialise les statistiques."""
        for key in self._stats:
            self._stats[key] = 0


__all__ = [
    "ContextExtractor",
]
