"""
OSMOSIS Retriever — Hybrid dense+BM25 Qdrant search (invariant Type A).

Ce module isole le retrieval pur du KG. Les chunks retournes sont
IDENTIQUES a ceux d'un RAG classique. Zero KG, zero enrichissement.

Hybrid search : combine dense (embeddings e5-large) + sparse (BM25 text index)
via Qdrant Query API avec fusion RRF. Le dense capture la semantique,
le BM25 capture les termes exacts (noms produits, versions, codes).

C'est le socle invariant de non-regression : OSMOSIS >= RAG sur Type A.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue
from sentence_transformers import SentenceTransformer

from knowbase.config.settings import Settings
from knowbase.common.clients import rerank_chunks

logger = logging.getLogger(__name__)

TOP_K = 10
SCORE_THRESHOLD = 0.5
HYBRID_ENABLED = os.getenv("HYBRID_SEARCH_ENABLED", "true").lower() == "true"
PUBLIC_URL = os.getenv("PUBLIC_URL", "knowbase.ngrok.app")


@dataclass
class RetrievalResult:
    """Resultat du retrieval Qdrant pur."""
    chunks: list[dict[str, Any]]
    query_vector: list[float]
    docs_involved: set[str] = field(default_factory=set)
    top_score: float = 0.0


def embed_query(
    text: str,
    embedding_model: SentenceTransformer,
) -> list[float]:
    """Encode une question en vecteur. Retourne une liste de floats."""
    query_vector = embedding_model.encode(text)
    if hasattr(query_vector, "tolist"):
        query_vector = query_vector.tolist()
    elif hasattr(query_vector, "numpy"):
        query_vector = query_vector.numpy().tolist()
    return [float(x) for x in query_vector]


def retrieve_chunks(
    *,
    question: str,
    query_vector: list[float],
    qdrant_client: QdrantClient,
    settings: Settings,
    top_k: int = TOP_K,
    score_threshold: float = SCORE_THRESHOLD,
    solution_filter: str | None = None,
    release_filter: str | None = None,
    axis_filters: dict[str, str] | None = None,
    doc_filter: list[str] | None = None,
) -> RetrievalResult:
    """
    Qdrant vector search pur — invariant Type A.

    Retourne les memes chunks qu'un RAG classique.
    Zero KG, zero enrichissement, zero modification.

    Args:
        axis_filters: Filtres d'axes domain-agnostic (ex: {"release_id": "2023", "edition": "RISE"}).
                      Chaque cle est mappee vers un FieldCondition sur "axis_{key}" dans Qdrant.
                      Prioritaire sur release_filter si les deux sont fournis.
    """
    # Construction du filtre
    must_not_conditions = []
    must_conditions = []

    if settings.qdrant_collection == "knowbase":
        must_not_conditions.append(
            FieldCondition(key="type", match=MatchValue(value="rfp_qa"))
        )

    if solution_filter:
        must_conditions.append(
            FieldCondition(key="solution.main", match=MatchValue(value=solution_filter))
        )

    # Domain-agnostic axis filters (QD-2) — prioritaire sur release_filter
    if axis_filters:
        for axis_key, axis_value in axis_filters.items():
            if axis_value:
                # Convention Qdrant : "axis_{discriminating_role}" (ex: axis_release_id, axis_edition)
                qdrant_key = f"axis_{axis_key}" if not axis_key.startswith("axis_") else axis_key
                must_conditions.append(
                    FieldCondition(key=qdrant_key, match=MatchValue(value=axis_value))
                )
    elif release_filter:
        # Backward compat : release_filter simple (ancien comportement)
        must_conditions.append(
            FieldCondition(key="axis_release_id", match=MatchValue(value=release_filter))
        )

    if doc_filter:
        must_conditions.append(
            FieldCondition(key="doc_id", match=MatchAny(any=doc_filter))
        )

    query_filter = Filter(
        must_not=must_not_conditions if must_not_conditions else None,
        must=must_conditions if must_conditions else None,
    )

    # --- Hybrid dense + BM25 via Qdrant Query API ---
    if HYBRID_ENABLED:
        results = _hybrid_search(
            qdrant_client=qdrant_client,
            collection_name=settings.qdrant_collection,
            query_vector=query_vector,
            question=question,
            query_filter=query_filter,
            top_k=top_k,
        )
    else:
        results = qdrant_client.search(
            collection_name=settings.qdrant_collection,
            query_vector=query_vector,
            limit=top_k,
            with_payload=True,
            query_filter=query_filter,
        )

    # En mode hybrid RRF, les scores sont des rangs fusionnes (<<1.0)
    # et ne sont pas comparables au score_threshold cosine.
    # On ne filtre que si on est en mode dense-only.
    if HYBRID_ENABLED:
        filtered = results  # Pas de filtrage — le RRF gere la pertinence par le ranking
    else:
        filtered = [r for r in results if r.score >= score_threshold]

    if not filtered:
        return RetrievalResult(chunks=[], query_vector=query_vector)

    # Build response payloads
    from .search import build_response_payload
    response_chunks = [build_response_payload(r, PUBLIC_URL) for r in filtered]

    # Rerank
    reranked = rerank_chunks(question, response_chunks, top_k=top_k)

    # Collect metadata
    docs = set()
    top_score = 0.0
    for chunk in reranked:
        doc_id = chunk.get("doc_id", chunk.get("source_file", ""))
        if doc_id:
            docs.add(doc_id)
        score = chunk.get("score", 0)
        if score > top_score:
            top_score = score

    return RetrievalResult(
        chunks=reranked,
        query_vector=query_vector,
        docs_involved=docs,
        top_score=top_score,
    )


# Liste fixe _BM25_STOPWORDS supprimee — remplacee par IDF dynamique via corpus_stats
from knowbase.common.corpus_stats import is_generic_by_idf, is_corpus_large_enough


def _extract_bm25_keywords(question: str) -> list[str]:
    """Extrait les termes techniques significatifs pour le BM25.

    Strategie : garder uniquement les mots qui ont un "signal technique" fort
    (majuscules, chiffres, slash, underscore) et quelques noms communs utiles.
    Limiter a 4 termes pour eviter que le AND de MatchText soit trop restrictif.
    """
    import re
    # Nettoyer la ponctuation sauf / et _ (SAP S/4HANA, SAP_NOTE, /SCWM/...)
    cleaned = re.sub(r'[?!.,;:()"\'\[\]{}]', ' ', question)
    words = cleaned.split()

    def is_technical(w: str) -> int:
        """Score de specificite technique. 0 = pas technique."""
        if len(w) <= 2:
            return 0
        # IDF dynamique : mot tres frequent dans le corpus = pas technique
        if is_corpus_large_enough() and is_generic_by_idf(w.lower(), threshold=1.5):
            return 0
        # Micro-heuristique fallback : mots courts purement alphabetiques sans signal
        if not is_corpus_large_enough() and len(w) <= 3 and w.isalpha() and w.islower():
            return 0
        score = 0
        if '/' in w or '_' in w:     # /SCWM/R_BW..., SAP_WFRT
            score += 5
        if any(c.isdigit() for c in w):  # 2023, 2008727, S/4HANA
            score += 4
        if w.isupper() and len(w) >= 2:  # SAP, MRP, EWM, TLS
            score += 3
        elif any(c.isupper() for c in w[1:]):  # S/4HANA, camelCase
            score += 2
        elif w[0].isupper():  # Nom propre: Note, Database
            score += 1
        return score

    # Gazetteer matching : si un domain pack est actif, chercher les produits/entites
    # connus dans la question. Score eleve car match exact sur un terme du domaine.
    # Domain-agnostic : chaque pack fournit son propre gazetteer.
    gazetteer_matches = []
    try:
        from knowbase.domain_packs.registry import get_pack_registry
        registry = get_pack_registry()
        packs = registry.get_active_packs("default")
        if packs:
            question_lower = cleaned.lower()
            for pack in packs:
                # Gazetteer : noms de produits/entites connus
                for product in pack.get_product_gazetteer():
                    prod_lower = product.lower()
                    if len(prod_lower) > 3 and prod_lower in question_lower:
                        gazetteer_matches.append((product, 6))  # score 6 = plus haut que tout
                # Aliases : noms alternatifs
                for alias, canonical in pack.get_canonical_aliases().items():
                    alias_lower = alias.lower()
                    if len(alias_lower) > 3 and alias_lower in question_lower:
                        gazetteer_matches.append((alias, 6))
            if gazetteer_matches:
                # Garder le match le plus long (eviter "ALM" si "Cloud ALM" matche aussi)
                gazetteer_matches.sort(key=lambda x: len(x[0]), reverse=True)
    except Exception:
        pass  # domain pack indisponible = pas de boost gazetteer

    # Detecter les noms composes (sequences de mots capitalises consecutifs)
    # "Business Data Cloud" → un seul terme technique score=3
    # Domain-agnostic : fonctionne pour "Extended Warehouse Management", "Phase III Trial", etc.
    compound_terms = []
    i = 0
    while i < len(words):
        if words[i][0].isupper() and words[i][1:].islower() and words[i].isalpha() and len(words[i]) > 2:
            # Debut potentiel d'un nom compose
            compound = [words[i]]
            j = i + 1
            while j < len(words) and words[j][0].isupper() and words[j].isalpha() and len(words[j]) > 1:
                compound.append(words[j])
                j += 1
            if len(compound) >= 2:
                compound_terms.append((" ".join(compound), 3))  # score 3 = meme que ALL_CAPS
                i = j
                continue
        i += 1

    # Scorer les mots individuels
    scored = []
    for i, w in enumerate(words):
        s = is_technical(w)
        # Le premier mot de la question a souvent une majuscule contextuelle
        # (debut de phrase) → ne pas le scorer comme "nom propre" s'il n'a
        # aucun autre signal technique (/, _, chiffre, ALL_CAPS, camelCase)
        if i == 0 and s == 1 and w[0].isupper() and w[1:].islower() and w.isalpha():
            s = 0
        if s > 0:
            scored.append((w, s))

    # Fusionner : gazetteer (priorite max) > noms composes > mots individuels
    scored.extend(compound_terms)
    scored.extend(gazetteer_matches)
    scored.sort(key=lambda x: x[1], reverse=True)

    # Garder max 4 termes (le AND de MatchText est restrictif)
    keywords = [w for w, _ in scored[:4]]

    return keywords


def _hybrid_search(
    *,
    qdrant_client: QdrantClient,
    collection_name: str,
    query_vector: list[float],
    question: str,
    query_filter: Filter | None,
    top_k: int,
) -> list:
    """
    Hybrid dense + BM25 avec fusion RRF manuelle.

    1. Dense search (embeddings e5-large) → top N resultats avec score cosine
    2. BM25 scroll (text index Qdrant) → top N resultats par pertinence lexicale
    3. Fusion RRF : score = 1/(k + rank_dense) + 1/(k + rank_bm25)

    Le dense capture la semantique, le BM25 capture les termes exacts
    (SAP Notes, transactions, codes, noms de tables) que le dense rate.
    """
    from qdrant_client.models import MatchText

    RRF_K = 60  # Constante RRF (standard: 60)
    PREFETCH_LIMIT = top_k * 3  # Candidats par source

    try:
        # ── 1. Dense search ──────────────────────────────────────
        dense_results = qdrant_client.query_points(
            collection_name=collection_name,
            query=query_vector,
            limit=PREFETCH_LIMIT,
            with_payload=True,
            query_filter=query_filter,
        )
        dense_hits = dense_results.points if hasattr(dense_results, "points") else dense_results

        # ── 2. BM25 scroll (text-only, sans vecteur) ────────────
        bm25_hits = []
        keywords = _extract_bm25_keywords(question)
        if keywords:
            keyword_query = " ".join(keywords)
            bm25_conditions = [
                FieldCondition(key="text", match=MatchText(text=keyword_query)),
            ]
            if query_filter and query_filter.must:
                bm25_must = list(query_filter.must) + bm25_conditions
            else:
                bm25_must = bm25_conditions

            bm25_filter = Filter(
                must=bm25_must,
                must_not=query_filter.must_not if query_filter else None,
            )

            scroll_result, _ = qdrant_client.scroll(
                collection_name=collection_name,
                scroll_filter=bm25_filter,
                limit=PREFETCH_LIMIT,
                with_payload=True,
                with_vectors=False,
            )
            bm25_hits = scroll_result

        # ── 3. Fusion RRF manuelle ──────────────────────────────
        # Construire les rankings
        dense_ranking = {}  # point_id → rank (0-indexed)
        for rank, hit in enumerate(dense_hits):
            dense_ranking[hit.id] = rank

        bm25_ranking = {}  # point_id → rank (0-indexed)
        for rank, hit in enumerate(bm25_hits):
            bm25_ranking[hit.id] = rank

        # Collecter tous les points uniques avec leurs payloads
        all_points = {}  # point_id → ScoredPoint
        for hit in dense_hits:
            all_points[hit.id] = hit
        for hit in bm25_hits:
            if hit.id not in all_points:
                all_points[hit.id] = hit

        # Calculer le score RRF pour chaque point
        # Les BM25 hits sont des Record (pas ScoredPoint) — on cree un wrapper
        from types import SimpleNamespace

        rrf_scored = []
        for point_id, point in all_points.items():
            rank_dense = dense_ranking.get(point_id, PREFETCH_LIMIT + 1)
            rank_bm25 = bm25_ranking.get(point_id, PREFETCH_LIMIT + 1)
            rrf_score = 1.0 / (RRF_K + rank_dense) + 1.0 / (RRF_K + rank_bm25)

            # Score dense brut (pour le signal de repondabilite)
            dense_score = getattr(point, "score", 0) if point_id in dense_ranking else 0

            # Wrapper avec score RRF + payload du point original + score dense brut
            payload = point.payload if hasattr(point, "payload") else {}
            payload["_dense_score"] = round(float(dense_score), 4) if dense_score else 0

            scored = SimpleNamespace(
                id=point_id,
                score=rrf_score,
                payload=payload,
            )
            rrf_scored.append(scored)

        # Trier par score RRF descendant
        rrf_scored.sort(key=lambda p: p.score, reverse=True)

        # Stats pour debug
        dense_only = sum(1 for pid in all_points if pid not in bm25_ranking)
        bm25_only = sum(1 for pid in all_points if pid not in dense_ranking)
        both = sum(1 for pid in all_points if pid in dense_ranking and pid in bm25_ranking)

        logger.info(
            f"[OSMOSIS:Retriever] Hybrid RRF: "
            f"dense={len(dense_hits)}, bm25={len(bm25_hits)}, "
            f"merged={len(all_points)} (both={both}, dense_only={dense_only}, bm25_only={bm25_only}), "
            f"returning top {min(top_k, len(rrf_scored))}"
        )

        return rrf_scored[:top_k]

    except Exception as e:
        logger.warning(
            f"[OSMOSIS:Retriever] Hybrid search failed, fallback dense-only: {e}"
        )
        try:
            results = qdrant_client.query_points(
                collection_name=collection_name,
                query=query_vector,
                limit=top_k,
                with_payload=True,
                query_filter=query_filter,
            )
            return results.points if hasattr(results, "points") else results
        except Exception:
            return []
