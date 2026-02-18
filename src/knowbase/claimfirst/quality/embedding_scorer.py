# src/knowbase/claimfirst/quality/embedding_scorer.py
"""
Calcul de scores embedding pour les gates qualité.

Utilise EmbeddingModelManager (singleton, multilingual-e5-large)
pour calculer les similarités cosinus en batch.

V1.3: Quality gates pipeline.
"""

from __future__ import annotations

import json
import logging
from typing import Dict, List, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from knowbase.claimfirst.models.claim import Claim

logger = logging.getLogger(__name__)


class EmbeddingScorer:
    """Calcule les scores embedding pour les gates qualité."""

    def __init__(self):
        from knowbase.common.clients.embeddings import get_embedding_manager
        self._manager = get_embedding_manager()

    def _encode_batch(self, texts: List[str]) -> np.ndarray:
        """Encode un batch de textes via le manager singleton."""
        if not texts:
            return np.array([])
        return self._manager.encode(texts)

    @staticmethod
    def _cosine_similarity_batch(
        embeddings_a: np.ndarray,
        embeddings_b: np.ndarray,
    ) -> np.ndarray:
        """Similarité cosinus élément par élément entre deux matrices."""
        norms_a = np.linalg.norm(embeddings_a, axis=1, keepdims=True)
        norms_b = np.linalg.norm(embeddings_b, axis=1, keepdims=True)
        # Éviter division par zéro
        norms_a = np.maximum(norms_a, 1e-10)
        norms_b = np.maximum(norms_b, 1e-10)
        a_norm = embeddings_a / norms_a
        b_norm = embeddings_b / norms_b
        return np.sum(a_norm * b_norm, axis=1)

    def score_verifiability(self, claims: List["Claim"]) -> Dict[str, float]:
        """
        cos(claim.text, claim.verbatim_quote) pour chaque claim.

        Returns:
            Dict claim_id → similarity score
        """
        if not claims:
            return {}

        texts = [c.text for c in claims]
        verbatims = [c.verbatim_quote for c in claims]

        emb_texts = self._encode_batch(texts)
        emb_verbatims = self._encode_batch(verbatims)

        similarities = self._cosine_similarity_batch(emb_texts, emb_verbatims)

        return {
            claims[i].claim_id: float(similarities[i])
            for i in range(len(claims))
        }

    def score_sf_alignment(self, claims: List["Claim"]) -> Dict[str, float]:
        """
        cos(serialize(SF), claim.text) pour claims avec structured_form.

        Returns:
            Dict claim_id → similarity score (seulement pour claims avec SF)
        """
        claims_with_sf = [c for c in claims if c.structured_form]
        if not claims_with_sf:
            return {}

        texts = [c.text for c in claims_with_sf]
        sf_serialized = [self._serialize_sf(c.structured_form) for c in claims_with_sf]

        emb_texts = self._encode_batch(texts)
        emb_sf = self._encode_batch(sf_serialized)

        similarities = self._cosine_similarity_batch(emb_texts, emb_sf)

        return {
            claims_with_sf[i].claim_id: float(similarities[i])
            for i in range(len(claims_with_sf))
        }

    def score_triviality(self, claims: List["Claim"]) -> Dict[str, float]:
        """
        cos(SF.subject, SF.object) pour claims avec structured_form.

        Returns:
            Dict claim_id → similarity score (seulement pour claims avec SF)
        """
        claims_with_spo = [
            c for c in claims
            if c.structured_form
            and c.structured_form.get("subject")
            and c.structured_form.get("object")
        ]
        if not claims_with_spo:
            return {}

        subjects = [str(c.structured_form["subject"]) for c in claims_with_spo]
        objects_ = [str(c.structured_form["object"]) for c in claims_with_spo]

        emb_subjects = self._encode_batch(subjects)
        emb_objects = self._encode_batch(objects_)

        similarities = self._cosine_similarity_batch(emb_subjects, emb_objects)

        return {
            claims_with_spo[i].claim_id: float(similarities[i])
            for i in range(len(claims_with_spo))
        }

    def score_entity_in_text(
        self,
        entity_names: List[str],
        claim_texts: List[str],
    ) -> np.ndarray:
        """
        cos(entity_name, claim_text) pour chaque paire.

        Utilisé par IndependenceResolver pour vérifier si une entité
        est mentionnée dans le texte de la claim.

        Returns:
            Array de similarités (même longueur que les inputs)
        """
        if not entity_names or not claim_texts:
            return np.array([])

        emb_entities = self._encode_batch(entity_names)
        emb_texts = self._encode_batch(claim_texts)

        return self._cosine_similarity_batch(emb_entities, emb_texts)

    def score_verifiability_pair(self, text: str, verbatim: str) -> float:
        """
        cos(text, verbatim) pour une seule paire.

        Utilisé par EvidenceRewriter pour le post-check.
        """
        emb = self._encode_batch([text, verbatim])
        if len(emb) < 2:
            return 0.0
        sim = self._cosine_similarity_batch(
            emb[:1], emb[1:],
        )
        return float(sim[0])

    @staticmethod
    def _serialize_sf(sf: dict) -> str:
        """Sérialise un structured_form en texte lisible."""
        subject = sf.get("subject", "")
        predicate = sf.get("predicate", "")
        object_ = sf.get("object", "")
        conditions = sf.get("conditions", [])

        parts = []
        if subject:
            parts.append(str(subject))
        if predicate:
            parts.append(str(predicate))
        if object_:
            parts.append(str(object_))
        if conditions:
            parts.append("when " + ", ".join(str(c) for c in conditions))

        return " ".join(parts) if parts else ""


__all__ = [
    "EmbeddingScorer",
]
