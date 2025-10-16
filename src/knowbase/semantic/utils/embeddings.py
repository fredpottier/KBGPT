"""
🌊 OSMOSE Semantic Intelligence V2.1 - Embeddings Multilingues

Gestionnaire embeddings cross-lingual avec multilingual-e5-large
"""

from sentence_transformers import SentenceTransformer
from typing import List, Optional
import numpy as np
from functools import lru_cache
import logging

logger = logging.getLogger(__name__)


class MultilingualEmbedder:
    """
    Embeddings multilingues avec cache.

    Utilise multilingual-e5-large (1024 dimensions) pour:
    - Cross-lingual similarity (FR ↔ EN ↔ DE)
    - Canonicalization de concepts
    - Topic clustering

    Phase 1 V2.1 - Semaine 1
    """

    def __init__(self, config):
        """
        Initialise le gestionnaire d'embeddings.

        Args:
            config: Configuration SemanticConfig avec config.embeddings
        """
        self.config = config

        # Charger le modèle multilingual-e5-large
        logger.info(f"[OSMOSE] Loading embeddings model: {config.embeddings.model}...")
        self.model = SentenceTransformer(
            config.embeddings.model,
            device=config.embeddings.device
        )
        logger.info(
            f"[OSMOSE] ✅ Embeddings model loaded: {config.embeddings.model} "
            f"({config.embeddings.dimension}D, device: {config.embeddings.device})"
        )

    @lru_cache(maxsize=1000)
    def encode_cached(self, text: str) -> np.ndarray:
        """
        Encode un texte avec cache LRU.

        Utile pour concepts répétés (ex: "ISO 27001" apparaît 50 fois).

        Args:
            text: Texte à encoder

        Returns:
            np.ndarray: Vecteur embedding (1024D)
        """
        embedding = self.model.encode(
            text,
            convert_to_numpy=True,
            normalize_embeddings=self.config.embeddings.normalize
        )
        return embedding

    def encode(self, texts: List[str], prefix_type: Optional[str] = None) -> np.ndarray:
        """
        Encode un batch de textes.

        Args:
            texts: Liste de textes à encoder
            prefix_type: Type de préfixe e5 ("query", "passage", ou None)
                        Recommandation OpenAI: +2-5% précision retrieval

        Returns:
            np.ndarray: Matrice embeddings (N x 1024)
        """
        if not texts:
            return np.array([])

        # Ajouter préfixes e5 si demandé (recommandation OpenAI)
        if prefix_type == "query":
            texts = [f"query: {text}" for text in texts]
        elif prefix_type == "passage":
            texts = [f"passage: {text}" for text in texts]

        embeddings = self.model.encode(
            texts,
            batch_size=self.config.embeddings.batch_size,
            convert_to_numpy=True,
            normalize_embeddings=self.config.embeddings.normalize,
            show_progress_bar=False
        )

        logger.debug(
            f"[OSMOSE] Encoded {len(texts)} texts (prefix={prefix_type}) → {embeddings.shape}"
        )

        return embeddings

    def encode_single(self, text: str, use_cache: bool = True) -> np.ndarray:
        """
        Encode un texte unique.

        Args:
            text: Texte à encoder
            use_cache: Utiliser le cache LRU (default: True)

        Returns:
            np.ndarray: Vecteur embedding (1024D)
        """
        if use_cache:
            return self.encode_cached(text)
        else:
            return self.model.encode(
                text,
                convert_to_numpy=True,
                normalize_embeddings=self.config.embeddings.normalize
            )

    def similarity(
        self,
        text1: str,
        text2: str
    ) -> float:
        """
        Calcule la similarité cosine entre deux textes.

        Cross-lingual : "authentication" (EN) vs "authentification" (FR) → ~0.92

        Args:
            text1: Premier texte
            text2: Deuxième texte

        Returns:
            float: Similarité cosine [0.0, 1.0]
        """
        emb1 = self.encode_cached(text1)
        emb2 = self.encode_cached(text2)

        # Cosine similarity (vecteurs déjà normalisés si config.normalize=True)
        if self.config.embeddings.normalize:
            similarity = float(np.dot(emb1, emb2))
        else:
            similarity = float(
                np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2))
            )

        return similarity

    def similarity_matrix(
        self,
        texts1: List[str],
        texts2: Optional[List[str]] = None
    ) -> np.ndarray:
        """
        Calcule la matrice de similarité entre deux ensembles de textes.

        Si texts2 est None, calcule la similarité entre tous les textes de texts1.

        Args:
            texts1: Premier ensemble de textes
            texts2: Deuxième ensemble (optionnel)

        Returns:
            np.ndarray: Matrice similarité (N x M)
        """
        emb1 = self.encode(texts1)

        if texts2 is None:
            emb2 = emb1
        else:
            emb2 = self.encode(texts2)

        # Similarité cosine matricielle
        if self.config.embeddings.normalize:
            # Vecteurs déjà normalisés → produit scalaire = cosine
            similarity_matrix = np.dot(emb1, emb2.T)
        else:
            # Normaliser puis produit scalaire
            emb1_norm = emb1 / np.linalg.norm(emb1, axis=1, keepdims=True)
            emb2_norm = emb2 / np.linalg.norm(emb2, axis=1, keepdims=True)
            similarity_matrix = np.dot(emb1_norm, emb2_norm.T)

        logger.debug(
            f"[OSMOSE] Similarity matrix: {similarity_matrix.shape}"
        )

        return similarity_matrix

    def find_similar(
        self,
        query_text: str,
        candidate_texts: List[str],
        threshold: float = 0.8,
        top_k: int = 5,
        use_e5_prefixes: bool = False
    ) -> List[tuple]:
        """
        Trouve les textes les plus similaires au query.

        Utile pour canonicalization (trouver concepts similaires cross-lingual).

        Args:
            query_text: Texte de recherche
            candidate_texts: Liste de textes candidats
            threshold: Seuil de similarité minimum
            top_k: Nombre max de résultats
            use_e5_prefixes: Utiliser préfixes e5 "query:" et "passage:" (+2-5% précision)

        Returns:
            List[tuple]: Liste de (index, text, similarity) triée par similarité décroissante
        """
        if not candidate_texts:
            return []

        # Utiliser préfixes e5 si demandé (recommandation OpenAI)
        if use_e5_prefixes:
            query_emb = self.model.encode(
                f"query: {query_text}",
                convert_to_numpy=True,
                normalize_embeddings=self.config.embeddings.normalize
            )
            candidate_embs = self.encode(candidate_texts, prefix_type="passage")
        else:
            query_emb = self.encode_cached(query_text)
            candidate_embs = self.encode(candidate_texts)

        # Calcul similarités
        if self.config.embeddings.normalize:
            similarities = np.dot(candidate_embs, query_emb)
        else:
            query_norm = query_emb / np.linalg.norm(query_emb)
            candidate_norms = candidate_embs / np.linalg.norm(candidate_embs, axis=1, keepdims=True)
            similarities = np.dot(candidate_norms, query_norm)

        # Filtrer par threshold et top_k
        results = []
        for idx, similarity in enumerate(similarities):
            if similarity >= threshold:
                results.append((idx, candidate_texts[idx], float(similarity)))

        # Trier par similarité décroissante
        results.sort(key=lambda x: x[2], reverse=True)

        return results[:top_k]

    def clear_cache(self):
        """
        Vide le cache LRU.

        Utile si mémoire limitée ou après traitement d'un gros batch.
        """
        self.encode_cached.cache_clear()
        logger.info("[OSMOSE] Embeddings cache cleared")

    def get_cache_info(self):
        """
        Retourne les statistiques du cache LRU.

        Returns:
            CacheInfo: hits, misses, maxsize, currsize
        """
        return self.encode_cached.cache_info()


# ===================================
# FACTORY PATTERN
# ===================================

_embedder_instance: Optional[MultilingualEmbedder] = None


def get_embedder(config) -> MultilingualEmbedder:
    """
    Récupère l'instance singleton du gestionnaire embeddings.

    Args:
        config: Configuration SemanticConfig

    Returns:
        MultilingualEmbedder: Instance unique
    """
    global _embedder_instance

    if _embedder_instance is None:
        _embedder_instance = MultilingualEmbedder(config)

    return _embedder_instance
