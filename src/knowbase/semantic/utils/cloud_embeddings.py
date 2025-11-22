"""
🌊 OSMOSE Semantic Intelligence - Cloud Embeddings

Embeddings accélérés via API cloud (OpenAI, Voyage, Cohere)
avec fallback sur modèle local.

Architecture Hybrid:
- Petits batches (<1000): Local CPU (gratuit, rapide)
- Gros batches (>1000): Cloud API (20× plus rapide)

Phase 1.8.1e - Accélération Embeddings
"""

import logging
from typing import List, Optional
import numpy as np
from openai import OpenAI
import os

logger = logging.getLogger(__name__)


class CloudEmbedder:
    """
    Embeddings cloud avec OpenAI API.

    Utilise text-embedding-3-large avec dimensions=1024 pour:
    - Compatibilité avec Qdrant existant (1024D)
    - Vitesse 20× supérieure vs local CPU
    - Qualité supérieure vs multilingual-e5-large

    Coût: ~$0.02 par document de 230 slides (13k chunks)
    Temps: 30-60s vs 15 min local
    """

    def __init__(self, model: str = "text-embedding-3-large", dimensions: int = 1024):
        """
        Initialise le cloud embedder.

        Args:
            model: Modèle OpenAI (text-embedding-3-large ou text-embedding-3-small)
            dimensions: Dimension forcée (1024 pour compatibilité Qdrant)
        """
        self.model = model
        self.dimensions = dimensions

        # Initialiser client OpenAI
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment")

        self.client = OpenAI(api_key=api_key)

        logger.info(
            f"[OSMOSE:CloudEmbedder] ✅ Initialized: {model} "
            f"(forcing {dimensions}D for Qdrant compatibility)"
        )

    def encode(self, texts: List[str], batch_size: int = 2048) -> np.ndarray:
        """
        Encode batch de textes via OpenAI API.

        Args:
            texts: Liste de textes à encoder
            batch_size: Taille des batches OpenAI (max 2048)

        Returns:
            np.ndarray: Matrice embeddings (N x dimensions)
        """
        if not texts:
            return np.array([])

        logger.info(
            f"[OSMOSE:CloudEmbedder] Encoding {len(texts)} texts "
            f"in batches of {batch_size}..."
        )

        all_embeddings = []

        # Traiter par batches (limite OpenAI = 2048 texts/request)
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]

            try:
                response = self.client.embeddings.create(
                    model=self.model,
                    input=batch,
                    dimensions=self.dimensions
                )

                # Extraire embeddings
                batch_embeddings = [item.embedding for item in response.data]
                all_embeddings.extend(batch_embeddings)

                logger.debug(
                    f"[OSMOSE:CloudEmbedder] Batch {i//batch_size + 1}: "
                    f"{len(batch)} texts encoded"
                )

            except Exception as e:
                logger.error(f"[OSMOSE:CloudEmbedder] Error encoding batch: {e}")
                raise

        embeddings_matrix = np.array(all_embeddings, dtype=np.float32)

        logger.info(
            f"[OSMOSE:CloudEmbedder] ✅ Encoded {len(texts)} texts "
            f"→ {embeddings_matrix.shape}"
        )

        return embeddings_matrix


class HybridEmbedder:
    """
    Embeddings hybride: local pour petits batches, cloud pour gros batches.

    Stratégie intelligente:
    - < threshold: Local CPU (multilingual-e5-large)
    - >= threshold: Cloud API (OpenAI text-embedding-3-large)

    Configuration via environnement:
    - EMBEDDING_MODE=hybrid|local|cloud
    - EMBEDDING_CLOUD_THRESHOLD=1000
    - EMBEDDING_CLOUD_MODEL=text-embedding-3-large
    """

    def __init__(self, local_embedder, threshold: int = 1000):
        """
        Initialise embedder hybride.

        Args:
            local_embedder: MultilingualEmbedder local
            threshold: Seuil pour basculer sur cloud
        """
        self.local_embedder = local_embedder
        self.threshold = threshold
        self.mode = os.getenv("EMBEDDING_MODE", "hybrid")

        # Initialiser cloud embedder si mode cloud ou hybrid
        self.cloud_embedder = None
        if self.mode in ["cloud", "hybrid"]:
            try:
                cloud_model = os.getenv("EMBEDDING_CLOUD_MODEL", "text-embedding-3-large")
                self.cloud_embedder = CloudEmbedder(
                    model=cloud_model,
                    dimensions=1024
                )
                logger.info(
                    f"[OSMOSE:HybridEmbedder] ✅ Mode: {self.mode} "
                    f"(threshold={threshold})"
                )
            except Exception as e:
                logger.warning(
                    f"[OSMOSE:HybridEmbedder] Cloud embedder init failed: {e}. "
                    f"Falling back to local only."
                )
                self.mode = "local"

    def encode(self, texts: List[str], **kwargs) -> np.ndarray:
        """
        Encode textes avec stratégie hybride.

        Args:
            texts: Liste de textes à encoder
            **kwargs: Arguments additionnels (batch_size, show_progress_bar, convert_to_numpy)
                     Passés au local_embedder, ignorés par cloud_embedder

        Returns:
            np.ndarray: Matrice embeddings (N x 1024)
        """
        if not texts:
            return np.array([])

        batch_size = len(texts)

        # Mode local forcé
        if self.mode == "local":
            return self.local_embedder.encode(texts, **kwargs)

        # Mode cloud forcé
        if self.mode == "cloud":
            if self.cloud_embedder:
                # CloudEmbedder n'utilise pas les kwargs (gère batch_size en interne)
                return self.cloud_embedder.encode(texts)
            else:
                logger.warning("[OSMOSE:HybridEmbedder] Cloud not available, using local")
                return self.local_embedder.encode(texts, **kwargs)

        # Mode hybrid: décision intelligente
        if batch_size < self.threshold:
            logger.info(
                f"[OSMOSE:HybridEmbedder] Small batch ({batch_size} < {self.threshold}) "
                f"→ Using LOCAL embedder"
            )
            return self.local_embedder.encode(texts, **kwargs)
        else:
            if self.cloud_embedder:
                logger.info(
                    f"[OSMOSE:HybridEmbedder] Large batch ({batch_size} >= {self.threshold}) "
                    f"→ Using CLOUD embedder (20× faster)"
                )
                # CloudEmbedder n'utilise pas les kwargs
                return self.cloud_embedder.encode(texts)
            else:
                logger.warning(
                    f"[OSMOSE:HybridEmbedder] Cloud not available for large batch "
                    f"({batch_size}), falling back to local"
                )
                return self.local_embedder.encode(texts, **kwargs)
