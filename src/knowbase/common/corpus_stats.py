"""
Cache IDF/DF mutualisé pour le corpus Qdrant.

Calcule une fois l'IDF et la Document Frequency (DF) a partir d'un echantillon
de chunks Qdrant, et expose les resultats via un singleton cache en memoire.

Utilise par :
- kg_signal_detector.py (Signal 5 : Question-Context Gap)
- retriever.py (BM25 keyword extraction)
- entity.py (filtrage entites generiques)

Remplace les listes de stopwords figees FR+EN par un mecanisme adaptatif :
un mot avec un IDF tres bas est, par definition, un mot generique dans le corpus,
quelle que soit la langue.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from typing import Optional

logger = logging.getLogger(__name__)

# ── Singleton cache ───────────────────────────────────────────────────────────

_idf_cache: Optional[dict[str, float]] = None
_df_cache: Optional[dict[str, int]] = None
_corpus_size: int = 0
_total_chunks: int = 0

# Seuil minimum de documents dans le corpus pour activer le filtrage IDF.
# En dessous, le corpus est trop petit pour que les frequences soient fiables.
MIN_CORPUS_FOR_IDF = 20


def _tokenize_raw(text: str) -> list[str]:
    """Tokenisation brute sans filtrage stopwords. Utilisee pour construire l'index IDF."""
    return re.findall(r"[a-zA-ZÀ-ÿ0-9_/-]{3,}", text.lower())


def _build_index() -> None:
    """Construit l'index IDF + DF a partir d'un echantillon Qdrant."""
    global _idf_cache, _df_cache, _corpus_size, _total_chunks

    try:
        from knowbase.retrieval.qdrant_layer_r import get_qdrant_client
        from knowbase.config.settings import get_settings

        settings = get_settings()
        client = get_qdrant_client()
        collection = settings.qdrant_collection

        info = client.get_collection(collection)
        _total_chunks = info.points_count
        if _total_chunks == 0:
            _idf_cache = {}
            _df_cache = {}
            _corpus_size = 0
            return

        sample_size = min(_total_chunks, 2000)
        results, _ = client.scroll(
            collection_name=collection,
            limit=sample_size,
            with_payload=True,
            with_vectors=False,
        )

        doc_freq: Counter = Counter()
        n_docs = len(results)

        for point in results:
            text = point.payload.get("text", "")
            tokens = set(_tokenize_raw(text))
            for token in tokens:
                doc_freq[token] += 1

        _df_cache = dict(doc_freq)
        _idf_cache = {}
        for token, df in doc_freq.items():
            _idf_cache[token] = math.log(n_docs / df) if df > 0 else 0
        _corpus_size = n_docs

        logger.info(
            f"[CORPUS_STATS] IDF index built: {len(_idf_cache)} terms "
            f"from {n_docs} chunks (total corpus: {_total_chunks})"
        )

    except Exception as e:
        logger.warning(f"[CORPUS_STATS] Failed to build IDF index: {e}")
        _idf_cache = {}
        _df_cache = {}
        _corpus_size = 0


# ── Public API ────────────────────────────────────────────────────────────────


def get_corpus_idf() -> dict[str, float]:
    """Retourne le cache IDF du corpus (calcule une fois, lazy init)."""
    if _idf_cache is None:
        _build_index()
    return _idf_cache  # type: ignore


def get_corpus_df() -> dict[str, int]:
    """Retourne le cache Document Frequency brut."""
    if _df_cache is None:
        _build_index()
    return _df_cache  # type: ignore


def get_corpus_size() -> int:
    """Nombre de chunks dans l'echantillon utilise pour l'index."""
    if _idf_cache is None:
        _build_index()
    return _corpus_size


def is_corpus_large_enough() -> bool:
    """True si le corpus est assez grand pour que l'IDF soit fiable."""
    if _idf_cache is None:
        _build_index()
    return _corpus_size >= MIN_CORPUS_FOR_IDF


def is_generic_by_idf(term: str, threshold: float = 1.5) -> bool:
    """True si le terme est generique dans le corpus (IDF bas = tres frequent).

    Args:
        term: mot lowercase
        threshold: IDF en dessous duquel le terme est considere generique.
                   1.5 ≈ present dans >22% des chunks.
                   2.0 ≈ present dans >13% des chunks.
    """
    idf = get_corpus_idf()
    if not idf or not is_corpus_large_enough():
        return False  # corpus trop petit, pas de filtrage IDF
    score = idf.get(term.lower())
    if score is None:
        return False  # terme absent du corpus = pas generique (peut etre un gap reel)
    return score < threshold


def is_in_corpus(term: str) -> bool:
    """True si le terme apparait au moins une fois dans l'echantillon du corpus."""
    idf = get_corpus_idf()
    return term.lower() in idf


def invalidate_cache() -> None:
    """Force le recalcul au prochain appel (utile apres une ingestion).

    Invalide aussi le cache stopwords multilingues car une nouvelle ingestion
    peut introduire des documents dans une nouvelle langue.
    """
    global _idf_cache, _df_cache, _corpus_size, _total_chunks
    _idf_cache = None
    _df_cache = None
    _corpus_size = 0
    _total_chunks = 0
    # Invalider aussi les stopwords (nouvelle langue possible)
    try:
        from knowbase.common.stopwords import invalidate_cache as invalidate_stopwords
        invalidate_stopwords()
    except Exception:
        pass
