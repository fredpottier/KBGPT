"""
Claim Retriever — V2-S4.

Récupère les claims pertinents pour une question dans un scope de doc_ids.
Mécanisme : embedding question → Qdrant search filtré par doc_id ∈ scope → top-K claims.

Depuis CH-35.A1 : retrieval hybride dense + BM25 avec fusion RRF (Reciprocal Rank
Fusion). Capture les termes exacts (Article 8, CS 25.788, NPA 2015-19) que le
vector seul rate. Toggle via env `RUNTIME_V2_HYBRID_RETRIEVAL` (default: true).

Domain-agnostic : aucune logique métier, juste recherche vectorielle/lexicale scope-restreinte.
"""
from __future__ import annotations

import logging
import os
import re
from types import SimpleNamespace
from typing import Optional

from neo4j import Driver
from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchText, MatchValue

from knowbase.runtime_v2.models import EvidenceClaim

logger = logging.getLogger(__name__)

# CH-35.A1 — Hybrid retrieval BM25+vector avec RRF
HYBRID_ENABLED = os.getenv("RUNTIME_V2_HYBRID_RETRIEVAL", "true").lower() == "true"
RRF_K = 60  # constante standard RRF (Cormack et al. 2009)
PREFETCH_MULTIPLIER = 3  # fetch top_k * 3 candidats par source avant fusion

# CH-35.A4 — Cross-encoder re-rank (BAAI/bge-reranker-v2-m3 multilingue par défaut)
# Note: ms-marco-MiniLM est monolingue anglais → régresse sur questions FR/DE/ES.
# bge-reranker-v2-m3 supporte 100+ langues mais est plus lourd (568M params, ~600MB).
# Sur GPU : ~30-50ms / 30 chunks. Sur CPU : ~28s (prohibitif).
RERANK_ENABLED = os.getenv("RUNTIME_V2_RERANK", "true").lower() == "true"
RERANK_MODEL = os.getenv("RUNTIME_V2_RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
RERANK_DEVICE = os.getenv("RUNTIME_V2_RERANK_DEVICE", "cuda")  # cuda|cpu, fallback CPU si GPU indispo
RERANK_PREFETCH = int(os.getenv("RUNTIME_V2_RERANK_PREFETCH", "30"))  # candidats avant re-rank


def _extract_keywords_for_bm25(question: str) -> tuple[list[str], int]:
    """Extrait les termes techniques de la question pour BM25 MatchText.

    Heuristique simple, domain-agnostic : garde les mots avec signal technique
    (majuscules, chiffres, slash, underscore, mots composés). Limite à 4 termes
    pour éviter que le AND de MatchText soit trop restrictif.

    Returns:
        (keywords, max_score) — max_score permet de gating l'activation BM25.
        Si max_score < 4 (pas de terme vraiment discriminant comme "2021/821",
        "CS-25", "428/2009"), on bascule en dense-only car BM25 sur termes génériques
        dilue les résultats.

    Examples:
        "Article 8 du règlement 2021/821" → ["2021/821"], max=9
        "Quels CS 25.788 modifie l'amdt 28 ?" → ["25.788", "CS"], max=9
        "courtier basé hors UE" → ["UE"], max=3 → BM25 NOT activated (dense-only)
    """
    cleaned = re.sub(r'[?!.,;:()"\'\[\]{}]', ' ', question)
    words = cleaned.split()

    def score(w: str) -> int:
        # Garder les ALL_CAPS courts (CS, AMC, EU) — sigles importants en régulatoire
        if len(w) <= 2 and not w.isupper():
            return 0
        if len(w) == 1:
            return 0
        s = 0
        if "/" in w or "_" in w:                # 2021/821, S/4HANA, /SCWM/, NPA_2015
            s += 5
        if any(c.isdigit() for c in w):         # années, articles, codes
            s += 4
        if w.isupper() and len(w) >= 2:         # CS, AMC, RGPD, EU
            s += 3
        elif any(c.isupper() for c in w[1:]):   # camelCase
            s += 2
        elif w[0].isupper() and len(w) > 3:     # Noms propres
            s += 1
        return s

    # Dédupe (préserve ordre du score le plus haut)
    seen = set()
    scored = []
    for w in words:
        s = score(w)
        if s > 0 and w not in seen:
            seen.add(w)
            scored.append((w, s))
    scored.sort(key=lambda x: x[1], reverse=True)
    # Filtre final : si on a des termes très techniques (score ≥ 4), on jette les "noms propres" score 1
    max_score = scored[0][1] if scored else 0
    if scored and scored[0][1] >= 4:
        scored = [(w, s) for w, s in scored if s >= 2]
    return [w for w, _ in scored[:4]], max_score


class ClaimRetriever:
    """Recherche les claims dans un scope de doc_ids via embeddings Qdrant."""

    def __init__(
        self,
        qdrant_client,
        embedder,
        driver: Driver,
        collection_name: str = "knowbase_chunks_v2",
        tenant_id: str = "default",
    ) -> None:
        self.qdrant = qdrant_client
        self.embedder = embedder
        self.driver = driver
        self.collection = collection_name
        self.tenant_id = tenant_id

    def retrieve(
        self,
        question: str,
        doc_ids: Optional[list[str]] = None,
        top_k: int = 10,
    ) -> list[EvidenceClaim]:
        """Recherche les claims pertinents pour la question dans le scope.

        Mode hybride par défaut (CH-35.A1) : combine dense (e5-large) + sparse
        (BM25 via MatchText) avec fusion RRF. Bascule en dense-only si l'env
        `RUNTIME_V2_HYBRID_RETRIEVAL` vaut "false".

        Args:
            question: question utilisateur (sera encodée puis cherchée par cosine)
            doc_ids: scope autoritaire (None = pas de filtre, tous docs)
            top_k: nombre max de claims retournés

        Returns:
            Liste d'EvidenceClaim triée par score desc.
        """
        # Encode question
        try:
            vec = self.embedder.encode(f"query: {question}").tolist()
        except Exception as exc:  # noqa: BLE001
            logger.error("Embedder failed for question: %s", exc)
            return []

        # Build filter
        filters = []
        if doc_ids is not None and len(doc_ids) > 0:
            filters.append(FieldCondition(key="doc_id", match=MatchAny(any=doc_ids)))
        filters.append(FieldCondition(key="tenant_id", match=MatchValue(value=self.tenant_id)))
        query_filter = Filter(must=filters)

        # Si re-rank activé, on fetch plus de candidats pour avoir matière à re-ranker
        fetch_k = max(top_k, RERANK_PREFETCH) if RERANK_ENABLED else top_k

        if HYBRID_ENABLED:
            results = self._hybrid_search(question, vec, query_filter, fetch_k)
        else:
            try:
                results = self.qdrant.search(
                    collection_name=self.collection,
                    query_vector=vec,
                    limit=fetch_k,
                    query_filter=query_filter,
                    with_payload=True,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Qdrant search failed: %s", exc)
                return []

        # CH-35.A4 — Cross-encoder re-rank top-N → top_k
        if RERANK_ENABLED and len(results) > top_k:
            results = self._rerank(question, results, top_k)

        claims: list[EvidenceClaim] = []
        for r in results:
            payload = dict(getattr(r, "payload", None) or {})
            cid = payload.get("claim_id") or payload.get("chunk_id") or str(getattr(r, "id", ""))
            text = payload.get("text") or payload.get("passage_text") or ""
            claims.append(
                EvidenceClaim(
                    claim_id=cid,
                    doc_id=payload.get("doc_id", "unknown"),
                    text=text,
                    score=float(getattr(r, "score", 0.0)),
                    publication_date=payload.get("publication_date"),
                )
            )
        return claims

    def _hybrid_search(
        self,
        question: str,
        query_vector: list[float],
        query_filter: Filter,
        top_k: int,
    ) -> list:
        """Hybrid dense+BM25 avec fusion Reciprocal Rank Fusion.

        1. Dense search Qdrant query_points → top_k*3 candidats avec score cosine
        2. BM25 scroll via MatchText sur keywords techniques → top_k*3 candidats
        3. Fusion RRF : score = 1/(k+rank_dense) + 1/(k+rank_bm25)

        Le dense capture la sémantique, BM25 capture les termes exacts (CS 25.788,
        Article 8, NPA 2015-19) que le vector rate.

        Fallback dense-only si BM25 échoue.
        """
        prefetch = max(top_k * PREFETCH_MULTIPLIER, top_k + 5)

        try:
            # ── 1. Dense search ─────────────────────────────────────
            dense_resp = self.qdrant.query_points(
                collection_name=self.collection,
                query=query_vector,
                limit=prefetch,
                with_payload=True,
                query_filter=query_filter,
            )
            dense_hits = dense_resp.points if hasattr(dense_resp, "points") else dense_resp

            # ── 2. BM25 scroll via MatchText ────────────────────────
            bm25_hits = []
            keywords, max_score = _extract_keywords_for_bm25(question)
            bm25_activated = bool(keywords)
            if bm25_activated:
                keyword_query = " ".join(keywords)
                bm25_must = list(query_filter.must or []) + [
                    FieldCondition(key="text", match=MatchText(text=keyword_query))
                ]
                bm25_filter = Filter(
                    must=bm25_must,
                    must_not=query_filter.must_not,
                )
                scroll_result, _ = self.qdrant.scroll(
                    collection_name=self.collection,
                    scroll_filter=bm25_filter,
                    limit=prefetch,
                    with_payload=True,
                    with_vectors=False,
                )
                bm25_hits = scroll_result

            # ── 3. Fusion RRF ───────────────────────────────────────
            dense_rank = {h.id: r for r, h in enumerate(dense_hits)}
            bm25_rank = {h.id: r for r, h in enumerate(bm25_hits)}

            all_points: dict = {}
            for hit in dense_hits:
                all_points[hit.id] = hit
            for hit in bm25_hits:
                if hit.id not in all_points:
                    all_points[hit.id] = hit

            fused = []
            for pid, point in all_points.items():
                rd = dense_rank.get(pid, prefetch + 1)
                rb = bm25_rank.get(pid, prefetch + 1)
                rrf = 1.0 / (RRF_K + rd) + 1.0 / (RRF_K + rb)
                payload = dict(getattr(point, "payload", None) or {})
                payload["_dense_rank"] = rd if pid in dense_rank else None
                payload["_bm25_rank"] = rb if pid in bm25_rank else None
                fused.append(SimpleNamespace(id=pid, score=rrf, payload=payload))

            fused.sort(key=lambda p: p.score, reverse=True)

            both = sum(1 for pid in all_points if pid in dense_rank and pid in bm25_rank)
            dense_only = sum(1 for pid in all_points if pid not in bm25_rank)
            bm25_only = sum(1 for pid in all_points if pid not in dense_rank)
            logger.info(
                "[runtime_v2:Hybrid] dense=%d bm25=%d (kw=%s, activated=%s) merged=%d (both=%d, d_only=%d, b_only=%d) → top %d",
                len(dense_hits), len(bm25_hits), keywords, bm25_activated, len(all_points),
                both, dense_only, bm25_only, min(top_k, len(fused)),
            )
            return fused[:top_k]

        except Exception as exc:  # noqa: BLE001
            logger.warning("[runtime_v2:Hybrid] failed (%s) → fallback dense-only", exc)
            try:
                resp = self.qdrant.search(
                    collection_name=self.collection,
                    query_vector=query_vector,
                    limit=top_k,
                    query_filter=query_filter,
                    with_payload=True,
                )
                return resp
            except Exception as exc2:  # noqa: BLE001
                logger.error("[runtime_v2:Hybrid] dense fallback also failed: %s", exc2)
                return []

    def _rerank(self, question: str, candidates: list, top_k: int) -> list:
        """Cross-encoder re-rank des candidats.

        Utilise BAAI/bge-reranker-v2-m3 par défaut (multilingue 100+ langues, 568M params,
        latence ~300-500ms sur 30 chunks CPU). Override via env `RUNTIME_V2_RERANK_MODEL`.
        Repromote les chunks pertinents bien classés sémantiquement mais battus
        par le score cosine ou la fusion RRF.
        """
        try:
            from knowbase.common.clients.reranker import get_cross_encoder
            # GPU si dispo, sinon CPU (avec warning latence)
            device = RERANK_DEVICE
            if device == "cuda":
                try:
                    import torch
                    if not torch.cuda.is_available():
                        logger.warning("[runtime_v2:Rerank] CUDA requested but unavailable, fallback CPU")
                        device = "cpu"
                except Exception:
                    device = "cpu"
            ce = get_cross_encoder(model_name=RERANK_MODEL, device=device)
            pairs = [(question, getattr(c, "payload", {}).get("text") or "") for c in candidates]
            scores = ce.predict(pairs)
            # Préserver le payload original, juste réordonner avec un score rerank
            scored = []
            for c, s in zip(candidates, scores):
                # Wrap dans SimpleNamespace pour ne pas muter l'objet original
                payload = dict(getattr(c, "payload", None) or {})
                payload["_rerank_score"] = float(s)
                ns = SimpleNamespace(
                    id=getattr(c, "id", None),
                    score=float(s),  # nouveau score = rerank score (ms-marco logits)
                    payload=payload,
                )
                scored.append(ns)
            scored.sort(key=lambda x: x.score, reverse=True)
            logger.info(
                "[runtime_v2:Rerank] reranked %d candidates → top %d (top_score=%.3f)",
                len(candidates), top_k, scored[0].score if scored else 0,
            )
            return scored[:top_k]
        except Exception as exc:  # noqa: BLE001
            logger.warning("[runtime_v2:Rerank] failed (%s) → returning original top %d", exc, top_k)
            return candidates[:top_k]

    def retrieve_chronological(
        self,
        question: str,
        doc_ids: list[str],
        top_k_per_doc: int = 3,
    ) -> dict[str, list[EvidenceClaim]]:
        """Retrieval pour mode RANGE : top claims par doc, organisé par doc_id.

        Used by Evolution Builder pour reconstruire la timeline.
        """
        result: dict[str, list[EvidenceClaim]] = {}
        for doc_id in doc_ids:
            claims = self.retrieve(question, doc_ids=[doc_id], top_k=top_k_per_doc)
            if claims:
                result[doc_id] = claims
        return result

    def topic_with_coherence(
        self,
        question: str,
        top_k_chunks: int = 30,
        top_k_docs: int = 6,
        min_score: float = 0.3,
    ) -> dict:
        """Identifie les doc_ids pertinents + analyse de cohérence du sujet.

        Substitut domain-agnostic du Subject Resolver (P2.2) :
        1. Pré-retrieval Qdrant top chunks → doc_ids
        2. Récupère primary_subject de chaque doc en Neo4j
        3. Analyse cohérence : les top docs partagent-ils un cluster sémantique ?
           - Heuristique : préfixe commun du doc_id (ex: "cs25_*", "dualuse_*")
           - OU primary_subject contient des tokens communs

        Returns:
            {
              "doc_ids": [...],            # top doc_ids (comme avant)
              "topic_consistent": bool,    # True si cluster cohérent identifié
              "topic_signature": str,      # "cs25" / "dualuse" / "mixed" / etc.
              "ambiguity_reason": str | None
            }
        """
        doc_ids = self.topic_doc_ids(question, top_k_chunks, top_k_docs, min_score)
        if not doc_ids:
            return {
                "doc_ids": [],
                "topic_consistent": False,
                "topic_signature": "empty",
                "ambiguity_reason": "No documents matched the question semantically.",
            }

        # Récupérer primary_subject de chaque doc_id pour analyse cohérence
        with self.driver.session() as session:
            rows = session.run(
                """
                MATCH (dc:DocumentContext)
                WHERE dc.tenant_id = $tenant_id AND dc.doc_id IN $doc_ids
                RETURN dc.doc_id AS doc_id,
                       coalesce(dc.primary_subject, '') AS primary_subject
                """,
                tenant_id=self.tenant_id,
                doc_ids=doc_ids,
            ).data()

        # Analyse cohérence
        prefixes = [d.split("_")[0] if "_" in d else d for d in doc_ids]
        prefix_counts: dict[str, int] = {}
        for p in prefixes:
            prefix_counts[p] = prefix_counts.get(p, 0) + 1

        if not prefix_counts:
            return {
                "doc_ids": doc_ids,
                "topic_consistent": False,
                "topic_signature": "empty",
                "ambiguity_reason": "Empty prefix analysis.",
            }

        # Top prefix doit représenter ≥ 60% des top docs pour être cohérent
        sorted_prefixes = sorted(prefix_counts.items(), key=lambda x: x[1], reverse=True)
        top_prefix, top_count = sorted_prefixes[0]
        consistency_ratio = top_count / len(doc_ids)

        if consistency_ratio >= 0.6:
            return {
                "doc_ids": doc_ids,
                "topic_consistent": True,
                "topic_signature": top_prefix,
                "ambiguity_reason": None,
            }

        # Ambigu : mélange de domaines dans les top docs
        return {
            "doc_ids": doc_ids,
            "topic_consistent": False,
            "topic_signature": "mixed",
            "ambiguity_reason": (
                f"Mixed topics in top docs: "
                f"{', '.join(f'{p}({c})' for p, c in sorted_prefixes[:3])}. "
                f"Consider clarifying the subject."
            ),
        }

    def topic_doc_ids(
        self,
        question: str,
        top_k_chunks: int = 30,
        top_k_docs: int = 6,
        min_score: float = 0.3,
    ) -> list[str]:
        """Identifie les doc_ids les plus pertinents pour une question (pré-retrieval).

        Substitute léger d'un Subject Resolver : on encode la question, on cherche
        top-K chunks dans tout le KG, on agrège par doc_id avec score = max(scores chunks).
        Retourne les top_k_docs doc_ids.

        Used by Pipeline V2 pour restreindre le Current Resolver au sujet implicite.

        Args:
            question: question utilisateur
            top_k_chunks: nombre de chunks Qdrant pour le pré-scan (large)
            top_k_docs: nombre de doc_ids retournés
            min_score: filtre les chunks avec score < seuil (signal faible)
        """
        try:
            vec = self.embedder.encode(f"query: {question}").tolist()
        except Exception as exc:  # noqa: BLE001
            logger.error("Embedder failed for topic detection: %s", exc)
            return []

        try:
            results = self.qdrant.search(
                collection_name=self.collection,
                query_vector=vec,
                limit=top_k_chunks,
                query_filter=Filter(
                    must=[FieldCondition(key="tenant_id", match=MatchValue(value=self.tenant_id))]
                ),
                with_payload=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Qdrant pre-retrieval for topic failed: %s", exc)
            return []

        # Agrège par doc_id : score = max(scores chunks)
        doc_scores: dict[str, float] = {}
        for r in results:
            if r.score < min_score:
                continue
            doc_id = (r.payload or {}).get("doc_id", "")
            if not doc_id:
                continue
            if doc_id not in doc_scores or r.score > doc_scores[doc_id]:
                doc_scores[doc_id] = r.score

        # Tri desc par score, top_k_docs
        sorted_docs = sorted(doc_scores.items(), key=lambda x: x[1], reverse=True)
        return [doc_id for doc_id, _ in sorted_docs[:top_k_docs]]
