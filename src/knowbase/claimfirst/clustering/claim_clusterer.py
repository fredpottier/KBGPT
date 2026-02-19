# src/knowbase/claimfirst/clustering/claim_clusterer.py
"""
ClaimClusterer - Clustering conservateur en 2 étages.

INV-6: ClaimClusterer conservateur (2 étages)

Étage 1: Candidats par embeddings (seuil 0.85)
Étage 2: Validation stricte avant merge
    - Mêmes entités principales mentionnées
    - Même modalité (must/shall ≠ may/should)
    - Pas de négation inversée
    - Overlap lexical minimal sur termes clés

Règle d'abstention: Si doute → PAS de cluster.
Mieux trop de clusters que des clusters faux.

INV-3: Claim = occurrence mono-document
L'agrégation inter-documents passe exclusivement par ClaimCluster.
Le cluster exprime "ces claims de différents docs disent la même chose".
"""

from __future__ import annotations

import logging
import re
import uuid
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

from knowbase.claimfirst.models.claim import Claim
from knowbase.claimfirst.models.result import ClaimCluster

logger = logging.getLogger(__name__)


# Seuils de clustering
EMBEDDING_THRESHOLD = 0.85  # Seuil cosine similarity (haut = conservateur)
LEXICAL_OVERLAP_MIN = 0.3  # % minimum de tokens clés en commun
MAX_CLUSTER_SIZE = 50  # Cap de taille max par cluster

# Patterns de modalité
STRONG_OBLIGATION = {"must", "shall", "required", "mandatory", "obligatory"}
WEAK_OBLIGATION = {"should", "recommended", "advisable"}
PERMISSION = {"may", "can", "allowed", "permitted", "optional"}

# Patterns de négation
NEGATION_PATTERNS = {
    r"\bnot\b", r"\bno\b", r"\bnever\b", r"\bnone\b",
    r"\bcannot\b", r"\bcan't\b", r"\bwon't\b", r"\bdon't\b",
    r"\bwithout\b", r"\bexcept\b", r"\bexclud",
}


class ClaimClusterer:
    """
    Clustering conservateur pour agrégation inter-documents.

    Étage 1: Filtrage par similarité cosine (embeddings)
    Étage 2: Validation stricte par règles

    INV-6: Règle d'abstention stricte - si doute → PAS de cluster.
    """

    def __init__(
        self,
        embedding_threshold: float = EMBEDDING_THRESHOLD,
        lexical_overlap_min: float = LEXICAL_OVERLAP_MIN,
        require_same_modality: bool = True,
        check_negation: bool = True,
    ):
        """
        Initialise le clusterer.

        Args:
            embedding_threshold: Seuil de similarité cosine
            lexical_overlap_min: Overlap lexical minimum
            require_same_modality: Exiger même modalité
            check_negation: Vérifier négation inversée
        """
        self.embedding_threshold = embedding_threshold
        self.lexical_overlap_min = lexical_overlap_min
        self.require_same_modality = require_same_modality
        self.check_negation = check_negation

        self.stats = {
            "claims_processed": 0,
            "candidate_pairs": 0,
            "validated_pairs": 0,
            "rejected_pairs": 0,
            "clusters_created": 0,
            "rejections": {
                "no_common_entity": 0,
                "modality_mismatch": 0,
                "negation_inversion": 0,
                "low_lexical_overlap": 0,
            }
        }

    def cluster(
        self,
        claims: List[Claim],
        embeddings: Optional[Dict[str, np.ndarray]] = None,
        entities_by_claim: Optional[Dict[str, List[str]]] = None,
        tenant_id: str = "default",
    ) -> List[ClaimCluster]:
        """
        Cluster les claims en groupes sémantiquement équivalents.

        Args:
            claims: Claims à clusterer
            embeddings: Dict claim_id → embedding vector (optionnel)
            entities_by_claim: Dict claim_id → [entity_ids] (optionnel)
            tenant_id: Tenant ID

        Returns:
            Liste de ClaimClusters
        """
        if len(claims) < 2:
            return []

        self.stats["claims_processed"] = len(claims)

        # Étage 1: Trouver les pairs candidats
        candidate_pairs = self._find_candidate_pairs(claims, embeddings)
        self.stats["candidate_pairs"] = len(candidate_pairs)

        logger.info(
            f"[OSMOSE:ClaimClusterer] Étage 1: {len(candidate_pairs)} candidate pairs "
            f"from {len(claims)} claims"
        )

        # Étage 2: Validation stricte
        valid_pairs = []
        for c1, c2, similarity in candidate_pairs:
            if self._validate_pair(c1, c2, entities_by_claim):
                valid_pairs.append((c1, c2))
                self.stats["validated_pairs"] += 1
            else:
                self.stats["rejected_pairs"] += 1

        logger.info(
            f"[OSMOSE:ClaimClusterer] Étage 2: {len(valid_pairs)} valid pairs "
            f"({self.stats['rejected_pairs']} rejected)"
        )

        # Construire les clusters via Union-Find
        clusters = self._build_clusters(claims, valid_pairs, tenant_id, embeddings)
        self.stats["clusters_created"] = len(clusters)

        return clusters

    def _find_candidate_pairs(
        self,
        claims: List[Claim],
        embeddings: Optional[Dict[str, np.ndarray]],
    ) -> List[Tuple[Claim, Claim, float]]:
        """
        Étage 1: Trouver les pairs candidats par similarité.

        Si embeddings disponibles: cosine similarity
        Sinon: Jaccard sur tokens
        """
        candidates = []

        if embeddings and len(embeddings) >= 2:
            # Similarité cosine sur embeddings
            for i, c1 in enumerate(claims):
                emb1 = embeddings.get(c1.claim_id)
                if emb1 is None:
                    continue

                for c2 in claims[i + 1:]:
                    emb2 = embeddings.get(c2.claim_id)
                    if emb2 is None:
                        continue

                    similarity = self._cosine_similarity(emb1, emb2)
                    if similarity >= self.embedding_threshold:
                        candidates.append((c1, c2, similarity))
        else:
            # Fallback: Jaccard sur tokens
            logger.info(
                "[OSMOSE:ClaimClusterer] No embeddings, using Jaccard similarity"
            )
            for i, c1 in enumerate(claims):
                tokens1 = self._extract_key_tokens(c1.text)

                for c2 in claims[i + 1:]:
                    tokens2 = self._extract_key_tokens(c2.text)

                    jaccard = self._jaccard_similarity(tokens1, tokens2)
                    if jaccard >= self.lexical_overlap_min:
                        candidates.append((c1, c2, jaccard))

        return candidates

    def _validate_pair(
        self,
        c1: Claim,
        c2: Claim,
        entities_by_claim: Optional[Dict[str, List[str]]],
    ) -> bool:
        """
        Étage 2: Validation stricte avant merge.

        INV-6: Règle d'abstention - si doute → PAS de cluster.
        """
        # 1. Mêmes entités principales mentionnées
        if entities_by_claim:
            e1 = set(entities_by_claim.get(c1.claim_id, []))
            e2 = set(entities_by_claim.get(c2.claim_id, []))
            if e1 and e2 and not e1.intersection(e2):
                self.stats["rejections"]["no_common_entity"] += 1
                return False

        # 2. Même modalité
        if self.require_same_modality:
            m1 = self._extract_modality(c1.text)
            m2 = self._extract_modality(c2.text)
            if m1 != m2:
                self.stats["rejections"]["modality_mismatch"] += 1
                return False

        # 3. Pas de négation inversée
        if self.check_negation:
            if self._has_inverted_negation(c1.text, c2.text):
                self.stats["rejections"]["negation_inversion"] += 1
                return False

        # 4. Overlap lexical minimal sur termes clés
        tokens1 = self._extract_key_tokens(c1.text)
        tokens2 = self._extract_key_tokens(c2.text)
        overlap = self._jaccard_similarity(tokens1, tokens2)
        if overlap < self.lexical_overlap_min:
            self.stats["rejections"]["low_lexical_overlap"] += 1
            return False

        return True

    def _build_clusters(
        self,
        claims: List[Claim],
        valid_pairs: List[Tuple[Claim, Claim]],
        tenant_id: str,
        embeddings: Optional[Dict[str, np.ndarray]] = None,
    ) -> List[ClaimCluster]:
        """
        Construit les clusters via Union-Find.

        Args:
            claims: Toutes les claims
            valid_pairs: Pairs validées (c1, c2)
            tenant_id: Tenant ID
            embeddings: Dict claim_id → embedding vector (pour trim centroïde)

        Returns:
            Liste de ClaimClusters
        """
        if not valid_pairs:
            return []

        # Index claim_id → Claim
        claim_index = {c.claim_id: c for c in claims}

        # Union-Find
        parent: Dict[str, str] = {}

        def find(x: str) -> str:
            if x not in parent:
                parent[x] = x
            if parent[x] != x:
                parent[x] = find(parent[x])  # Path compression
            return parent[x]

        def union(x: str, y: str) -> None:
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        # Unir les pairs
        for c1, c2 in valid_pairs:
            union(c1.claim_id, c2.claim_id)

        # Grouper par racine
        groups: Dict[str, List[str]] = defaultdict(list)
        for c1, c2 in valid_pairs:
            groups[find(c1.claim_id)].append(c1.claim_id)
            groups[find(c2.claim_id)].append(c2.claim_id)

        # Créer les clusters
        clusters = []
        seen_claims: Set[str] = set()

        for root, claim_ids in groups.items():
            unique_ids = sorted(set(claim_ids))  # sorted() pour déterminisme
            if len(unique_ids) < 2:
                continue

            # Skip si déjà traités
            if any(cid in seen_claims for cid in unique_ids):
                continue

            # Récupérer les claims
            cluster_claims = [claim_index[cid] for cid in unique_ids if cid in claim_index]
            if len(cluster_claims) < 2:
                continue

            # Cap de taille : si trop grand, garder les N claims les plus proches du centroïde
            if len(cluster_claims) > MAX_CLUSTER_SIZE and embeddings:
                cluster_claims = self._trim_to_core(cluster_claims, embeddings, MAX_CLUSTER_SIZE)
                unique_ids = [c.claim_id for c in cluster_claims]
            elif len(cluster_claims) > MAX_CLUSTER_SIZE:
                # Sans embeddings : garder les N avec meilleure confiance
                cluster_claims = sorted(
                    cluster_claims, key=lambda c: (-c.confidence, c.claim_id)
                )[:MAX_CLUSTER_SIZE]
                unique_ids = [c.claim_id for c in cluster_claims]

            # seen_claims APRÈS le trim (ne marquer que les claims gardées)
            seen_claims.update(unique_ids)

            # Choisir le label canonique (claim avec meilleure confiance)
            best_claim = max(cluster_claims, key=lambda c: c.confidence)

            # V1.4 — Marquer champion et redundants
            best_claim.is_champion = True
            for c in cluster_claims:
                if c.claim_id != best_claim.claim_id:
                    c.redundant = True
                    c.champion_claim_id = best_claim.claim_id

            # Documents uniques
            doc_ids = sorted(set(c.doc_id for c in cluster_claims))

            cluster = ClaimCluster(
                cluster_id=f"cluster_{uuid.uuid4().hex[:12]}",
                tenant_id=tenant_id,
                canonical_label=best_claim.text[:100],
                claim_ids=unique_ids,
                doc_ids=doc_ids,
                claim_count=len(unique_ids),
                doc_count=len(doc_ids),
                avg_confidence=sum(c.confidence for c in cluster_claims) / len(cluster_claims),
            )
            clusters.append(cluster)

        return clusters

    def _trim_to_core(
        self,
        claims: List[Claim],
        embeddings: Dict[str, np.ndarray],
        max_size: int,
    ) -> List[Claim]:
        """Garde les max_size claims les plus proches du centroïde du cluster."""
        vectors = [embeddings[c.claim_id] for c in claims if c.claim_id in embeddings]
        if not vectors:
            # Fallback sans embeddings : confiance + ID pour déterminisme
            return sorted(claims, key=lambda c: (-c.confidence, c.claim_id))[:max_size]
        centroid = np.mean(vectors, axis=0)
        scored = []
        for c in claims:
            if c.claim_id in embeddings:
                sim = self._cosine_similarity(embeddings[c.claim_id], centroid)
            else:
                sim = 0.0
            scored.append((sim, c.claim_id, c))  # claim_id pour tie-breaking déterministe
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [c for _, _, c in scored[:max_size]]

    def _cosine_similarity(self, v1: np.ndarray, v2: np.ndarray) -> float:
        """Calcule la similarité cosine entre deux vecteurs."""
        if v1 is None or v2 is None:
            return 0.0
        norm1 = np.linalg.norm(v1)
        norm2 = np.linalg.norm(v2)
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return float(np.dot(v1, v2) / (norm1 * norm2))

    def _jaccard_similarity(self, tokens1: Set[str], tokens2: Set[str]) -> float:
        """Calcule la similarité Jaccard entre deux ensembles de tokens."""
        if not tokens1 or not tokens2:
            return 0.0
        intersection = len(tokens1 & tokens2)
        union = len(tokens1 | tokens2)
        return intersection / union if union > 0 else 0.0

    def _extract_key_tokens(self, text: str) -> Set[str]:
        """
        Extrait les tokens clés d'un texte.

        Exclut les stop words et tokens courts.
        """
        # Stop words minimaux
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "must", "shall",
            "can", "need", "to", "of", "in", "for", "on", "with", "at",
            "by", "from", "as", "into", "through", "during", "before",
            "after", "above", "below", "between", "under", "again",
            "further", "then", "once", "here", "there", "when", "where",
            "why", "how", "all", "each", "few", "more", "most", "other",
            "some", "such", "no", "nor", "not", "only", "own", "same",
            "so", "than", "too", "very", "just", "and", "but", "if",
            "or", "because", "until", "while", "this", "that", "these",
            "those", "which", "who", "whom", "what", "whose",
        }

        # Tokenizer simple
        tokens = re.findall(r"\b[a-zA-Z]+\b", text.lower())

        # Filtrer
        return {t for t in tokens if t not in stop_words and len(t) > 2}

    def _extract_modality(self, text: str) -> str:
        """
        Extrait la modalité d'un texte.

        Returns:
            "strong" (must/shall), "weak" (should), "permission" (may/can), "neutral"
        """
        text_lower = text.lower()

        for word in STRONG_OBLIGATION:
            if re.search(rf"\b{word}\b", text_lower):
                return "strong"

        for word in WEAK_OBLIGATION:
            if re.search(rf"\b{word}\b", text_lower):
                return "weak"

        for word in PERMISSION:
            if re.search(rf"\b{word}\b", text_lower):
                return "permission"

        return "neutral"

    def _has_inverted_negation(self, text1: str, text2: str) -> bool:
        """
        Détecte si deux textes ont une négation inversée.

        Ex: "X is required" vs "X is not required"
        """
        neg1 = self._count_negations(text1)
        neg2 = self._count_negations(text2)

        # Si un a une négation et pas l'autre
        return (neg1 > 0) != (neg2 > 0)

    def _count_negations(self, text: str) -> int:
        """Compte le nombre de négations dans un texte."""
        count = 0
        text_lower = text.lower()
        for pattern in NEGATION_PATTERNS:
            count += len(re.findall(pattern, text_lower))
        return count

    def get_stats(self) -> dict:
        """Retourne les statistiques de clustering."""
        return dict(self.stats)

    def reset_stats(self) -> None:
        """Réinitialise les statistiques."""
        self.stats = {
            "claims_processed": 0,
            "candidate_pairs": 0,
            "validated_pairs": 0,
            "rejected_pairs": 0,
            "clusters_created": 0,
            "rejections": {
                "no_common_entity": 0,
                "modality_mismatch": 0,
                "negation_inversion": 0,
                "low_lexical_overlap": 0,
            }
        }


__all__ = [
    "ClaimClusterer",
    "EMBEDDING_THRESHOLD",
    "LEXICAL_OVERLAP_MIN",
    "MAX_CLUSTER_SIZE",
]
