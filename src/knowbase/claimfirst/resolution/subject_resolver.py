# src/knowbase/claimfirst/resolution/subject_resolver.py
"""
SubjectResolver - Résolution conservative des sujets.

INV-9: Conservative Subject Resolution (Anti-Hallucination Alias)

Principe: La résolution de sujets ne doit JAMAIS auto-fusionner sur
simple embedding ou inférence LLM.

Ordre de résolution STRICT:
1. Exact match sur canonical_name ou aliases_explicit → OK
2. Normalisation lexicale → re-test exact
3. Exact match sur aliases_learned → OK (confiance 0.95)
4. Soft match embedding → CANDIDAT UNIQUEMENT (règle delta)
5. Si ambigu → statut AMBIGUOUS
6. Si rien → création nouveau SubjectAnchor (avec filtre)

CORRECTIF 3 - Règle DELTA:
- EMBEDDING_THRESHOLD = 0.85
- DELTA_THRESHOLD = 0.06 (écart minimum avec 2ème candidat)
- Accepté en LOW_CONFIDENCE seulement si threshold ET delta suffisants
- Sinon → AMBIGUOUS (même si top1 > 0.85)

CORRECTIF 4 - Filtre avant création:
- Ne PAS créer pour termes courts (<3 mots)
- Blacklist de termes génériques
- Condition de création: preuve dans le texte (heading, n-gram répété)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from knowbase.claimfirst.models.subject_anchor import (
    SubjectAnchor,
    SUBJECT_BLACKLIST,
    is_valid_subject_name,
)
from knowbase.claimfirst.models.document_context import ResolutionStatus

logger = logging.getLogger(__name__)


@dataclass
class ResolverResult:
    """Résultat d'une résolution de sujet."""

    anchor: Optional[SubjectAnchor]
    """SubjectAnchor trouvé ou créé (None si rejeté)."""

    status: ResolutionStatus
    """Statut de la résolution."""

    confidence: float
    """Score de confiance [0-1]."""

    match_type: str
    """Type de match: 'exact', 'normalized', 'learned', 'embedding', 'new', 'rejected'."""

    candidates: Optional[List[Tuple[SubjectAnchor, float]]] = None
    """Candidats alternatifs (pour AMBIGUOUS)."""


class SubjectResolver:
    """
    Résolution conservative des sujets (INV-9).

    Ordre STRICT:
    1. Exact match sur canonical_name ou aliases_explicit
    2. Normalisation lexicale → re-test exact
    3. Exact match sur aliases_learned (confiance 0.95)
    4. Soft match embedding → CANDIDAT uniquement (règle delta)
    5. Si ambigu → statut AMBIGUOUS
    6. Si rien → création nouveau SubjectAnchor (avec filtre)
    """

    # CORRECTIF 3: Seuils pour soft matching
    EMBEDDING_THRESHOLD = 0.85
    DELTA_THRESHOLD = 0.06  # Écart minimum avec 2ème candidat

    # Confiance pour matches non-exact
    LEARNED_CONFIDENCE = 0.95
    NORMALIZED_CONFIDENCE = 1.0
    EXACT_CONFIDENCE = 1.0

    def __init__(
        self,
        embeddings_client: Any = None,
        tenant_id: str = "default",
    ):
        """
        Initialise le resolver.

        Args:
            embeddings_client: Client embeddings pour soft matching (optionnel)
            tenant_id: Tenant ID par défaut
        """
        self.embeddings_client = embeddings_client
        self.tenant_id = tenant_id

        # Stats
        self._stats = {
            "exact_matches": 0,
            "normalized_matches": 0,
            "learned_matches": 0,
            "embedding_low_confidence": 0,
            "embedding_ambiguous": 0,
            "new_created": 0,
            "rejected": 0,
        }

    def resolve(
        self,
        raw_subject: str,
        existing_anchors: List[SubjectAnchor],
        doc_id: Optional[str] = None,
        create_if_missing: bool = True,
    ) -> ResolverResult:
        """
        Résout un sujet brut vers un SubjectAnchor.

        Args:
            raw_subject: Sujet brut à résoudre
            existing_anchors: Liste des SubjectAnchor existants
            doc_id: Document source (pour provenance)
            create_if_missing: Si True, crée un nouveau sujet si non trouvé

        Returns:
            ResolverResult avec (anchor, status, confidence)
        """
        raw_subject = raw_subject.strip()
        if not raw_subject:
            return ResolverResult(
                anchor=None,
                status=ResolutionStatus.UNRESOLVED,
                confidence=0.0,
                match_type="rejected",
            )

        normalized = self._normalize(raw_subject)

        # 1. Exact match sur canonical_name
        for anchor in existing_anchors:
            if self._normalize(anchor.canonical_name) == normalized:
                self._stats["exact_matches"] += 1
                return ResolverResult(
                    anchor=anchor,
                    status=ResolutionStatus.RESOLVED,
                    confidence=self.EXACT_CONFIDENCE,
                    match_type="exact",
                )

        # 2. Exact match sur aliases_explicit (FORT)
        for anchor in existing_anchors:
            for alias in anchor.aliases_explicit:
                if self._normalize(alias) == normalized:
                    self._stats["exact_matches"] += 1
                    return ResolverResult(
                        anchor=anchor,
                        status=ResolutionStatus.RESOLVED,
                        confidence=self.EXACT_CONFIDENCE,
                        match_type="exact",
                    )

        # 3. Exact match sur aliases_learned (MOYEN)
        for anchor in existing_anchors:
            for alias in anchor.aliases_learned:
                if self._normalize(alias) == normalized:
                    self._stats["learned_matches"] += 1
                    return ResolverResult(
                        anchor=anchor,
                        status=ResolutionStatus.RESOLVED,
                        confidence=self.LEARNED_CONFIDENCE,
                        match_type="learned",
                    )

        # 4. Soft match embedding avec règle DELTA (CORRECTIF 3)
        if self.embeddings_client and existing_anchors:
            embedding_result = self._resolve_by_embedding(
                raw_subject, normalized, existing_anchors
            )
            if embedding_result:
                return embedding_result

        # 5. Rien trouvé → créer nouveau SubjectAnchor (AVEC FILTRE - CORRECTIF 4)
        if create_if_missing:
            return self._create_new_anchor(raw_subject, doc_id)
        else:
            return ResolverResult(
                anchor=None,
                status=ResolutionStatus.UNRESOLVED,
                confidence=0.0,
                match_type="rejected",
            )

    def _resolve_by_embedding(
        self,
        raw_subject: str,
        normalized: str,
        existing_anchors: List[SubjectAnchor],
    ) -> Optional[ResolverResult]:
        """
        Résolution par embedding avec règle DELTA (CORRECTIF 3).

        Conditions pour LOW_CONFIDENCE (pas auto-link):
        - top1_score >= EMBEDDING_THRESHOLD
        - (top1_score - top2_score) >= DELTA_THRESHOLD

        Sinon → AMBIGUOUS (même si top1 > 0.85)

        Args:
            raw_subject: Sujet brut
            normalized: Sujet normalisé
            existing_anchors: Anchors existants

        Returns:
            ResolverResult ou None si pas de match embedding
        """
        try:
            candidates = self._find_embedding_candidates(raw_subject, existing_anchors)
            if not candidates:
                return None

            candidates = sorted(candidates, key=lambda x: x[1], reverse=True)

            top1_anchor, top1_score = candidates[0]
            top2_score = candidates[1][1] if len(candidates) > 1 else 0.0
            delta = top1_score - top2_score

            # LOW_CONFIDENCE seulement si threshold ET delta suffisants
            if top1_score >= self.EMBEDDING_THRESHOLD and delta >= self.DELTA_THRESHOLD:
                self._stats["embedding_low_confidence"] += 1
                logger.debug(
                    f"[SubjectResolver] Embedding match: '{raw_subject}' → "
                    f"'{top1_anchor.canonical_name}' (score={top1_score:.3f}, delta={delta:.3f})"
                )
                return ResolverResult(
                    anchor=top1_anchor,
                    status=ResolutionStatus.LOW_CONFIDENCE,
                    confidence=top1_score,
                    match_type="embedding",
                    candidates=candidates[:3],  # Top 3 pour review
                )

            # AMBIGUOUS (même si top1 > threshold mais delta insuffisant)
            if top1_score >= self.EMBEDDING_THRESHOLD:
                self._stats["embedding_ambiguous"] += 1
                logger.debug(
                    f"[SubjectResolver] Ambiguous embedding: '{raw_subject}' "
                    f"(top1={top1_score:.3f}, delta={delta:.3f} < {self.DELTA_THRESHOLD})"
                )
                return ResolverResult(
                    anchor=top1_anchor,  # Le meilleur candidat
                    status=ResolutionStatus.AMBIGUOUS,
                    confidence=top1_score,
                    match_type="embedding",
                    candidates=candidates[:3],
                )

            # Pas de match suffisant
            return None

        except Exception as e:
            logger.warning(f"[SubjectResolver] Embedding resolution failed: {e}")
            return None

    def _find_embedding_candidates(
        self,
        raw_subject: str,
        existing_anchors: List[SubjectAnchor],
    ) -> List[Tuple[SubjectAnchor, float]]:
        """
        Trouve les candidats par similarité embedding.

        Args:
            raw_subject: Sujet brut à encoder
            existing_anchors: Anchors existants avec embeddings

        Returns:
            Liste de (anchor, score) triée par score décroissant
        """
        if not self.embeddings_client:
            return []

        candidates = []

        try:
            # Encoder le sujet brut
            subject_embedding = self._get_embedding(raw_subject)
            if not subject_embedding:
                return []

            # Comparer avec les anchors qui ont des embeddings
            for anchor in existing_anchors:
                if anchor.embedding:
                    similarity = self._cosine_similarity(
                        subject_embedding, anchor.embedding
                    )
                    candidates.append((anchor, similarity))

        except Exception as e:
            logger.warning(f"[SubjectResolver] Failed to compute embeddings: {e}")

        return candidates

    def _get_embedding(self, text: str) -> Optional[List[float]]:
        """Obtient l'embedding d'un texte."""
        if not self.embeddings_client:
            return None

        try:
            # Interface OpenAI-like
            if hasattr(self.embeddings_client, "embeddings"):
                response = self.embeddings_client.embeddings.create(
                    model="text-embedding-3-small",
                    input=[text],
                )
                return response.data[0].embedding

            # Interface custom
            elif hasattr(self.embeddings_client, "encode"):
                vectors = self.embeddings_client.encode([text])
                return vectors[0] if vectors else None

        except Exception as e:
            logger.warning(f"[SubjectResolver] Failed to get embedding: {e}")

        return None

    def _cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        """Calcule la similarité cosinus entre deux vecteurs."""
        if len(v1) != len(v2):
            return 0.0

        dot_product = sum(a * b for a, b in zip(v1, v2))
        norm1 = sum(a * a for a in v1) ** 0.5
        norm2 = sum(b * b for b in v2) ** 0.5

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    def _create_new_anchor(
        self,
        raw_subject: str,
        doc_id: Optional[str],
    ) -> ResolverResult:
        """
        Crée un nouveau SubjectAnchor avec filtrage (CORRECTIF 4).

        Conditions:
        - Pas dans la blacklist
        - Longueur minimale (≥2 mots ou ≥10 chars)
        - Preuve locale requise (à vérifier en amont)

        Args:
            raw_subject: Sujet brut
            doc_id: Document source

        Returns:
            ResolverResult avec nouveau anchor ou rejection
        """
        if not is_valid_subject_name(raw_subject):
            self._stats["rejected"] += 1
            logger.debug(
                f"[SubjectResolver] Rejected subject (invalid): '{raw_subject}'"
            )
            return ResolverResult(
                anchor=None,
                status=ResolutionStatus.UNRESOLVED,
                confidence=0.0,
                match_type="rejected",
            )

        # Créer le nouveau SubjectAnchor
        new_anchor = SubjectAnchor.create_new(
            tenant_id=self.tenant_id,
            canonical_name=raw_subject,
            doc_id=doc_id,
        )

        self._stats["new_created"] += 1
        logger.info(
            f"[SubjectResolver] Created new subject: '{new_anchor.canonical_name}' "
            f"(id={new_anchor.subject_id})"
        )

        return ResolverResult(
            anchor=new_anchor,
            status=ResolutionStatus.UNRESOLVED,  # Nouveau = pas encore confirmé
            confidence=0.0,
            match_type="new",
        )

    def _normalize(self, text: str) -> str:
        """
        Normalisation lexicale GÉNÉRIQUE (PATCH D - domain-agnostic).

        ⚠️ Pas de normalisation domain-specific ici.
        Le matching se fait sur les formes exactes + aliases.

        Args:
            text: Texte à normaliser

        Returns:
            Texte normalisé
        """
        n = text.lower().strip()
        # Remove noise chars (garder alphanumeric, espaces, tirets, slashs)
        n = re.sub(r"[^\w\s\-/]", "", n)
        # Collapse multiple spaces
        n = re.sub(r"\s+", " ", n)
        return n

    def resolve_batch(
        self,
        raw_subjects: List[str],
        existing_anchors: List[SubjectAnchor],
        doc_id: Optional[str] = None,
    ) -> List[ResolverResult]:
        """
        Résout une liste de sujets bruts.

        Args:
            raw_subjects: Sujets bruts à résoudre
            existing_anchors: Anchors existants
            doc_id: Document source

        Returns:
            Liste de ResolverResult
        """
        results = []

        # Garder une liste des anchors mis à jour (nouveaux créés)
        current_anchors = list(existing_anchors)

        for raw_subject in raw_subjects:
            result = self.resolve(
                raw_subject=raw_subject,
                existing_anchors=current_anchors,
                doc_id=doc_id,
            )
            results.append(result)

            # Ajouter les nouveaux anchors à la liste
            if result.anchor and result.match_type == "new":
                current_anchors.append(result.anchor)

        return results

    def suggest_equivalence(
        self,
        anchor1: SubjectAnchor,
        anchor2: SubjectAnchor,
    ) -> None:
        """
        Suggère une équivalence possible entre deux SubjectAnchor.

        INV-9: Ne fusionne PAS automatiquement.
        Crée une relation POSSIBLE_EQUIVALENT pour review.

        Args:
            anchor1: Premier anchor
            anchor2: Deuxième anchor
        """
        if anchor2.subject_id not in anchor1.possible_equivalents:
            anchor1.possible_equivalents.append(anchor2.subject_id)
        if anchor1.subject_id not in anchor2.possible_equivalents:
            anchor2.possible_equivalents.append(anchor1.subject_id)

        logger.debug(
            f"[SubjectResolver] Suggested equivalence: "
            f"'{anchor1.canonical_name}' ↔ '{anchor2.canonical_name}'"
        )

    def get_stats(self) -> dict:
        """Retourne les statistiques."""
        return dict(self._stats)

    def reset_stats(self) -> None:
        """Réinitialise les statistiques."""
        for key in self._stats:
            self._stats[key] = 0


__all__ = [
    "SubjectResolver",
    "ResolverResult",
]
