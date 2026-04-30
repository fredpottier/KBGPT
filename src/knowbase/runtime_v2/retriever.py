"""
Claim Retriever — V2-S4.

Récupère les claims pertinents pour une question dans un scope de doc_ids.
Mécanisme : embedding question → Qdrant search filtré par doc_id ∈ scope → top-K claims.

Domain-agnostic : aucune logique métier, juste recherche vectorielle scope-restreinte.
"""
from __future__ import annotations

import logging
from typing import Optional

from neo4j import Driver
from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

from knowbase.runtime_v2.models import EvidenceClaim

logger = logging.getLogger(__name__)


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
        # tenant filter
        filters.append(FieldCondition(key="tenant_id", match=MatchValue(value=self.tenant_id)))

        try:
            results = self.qdrant.search(
                collection_name=self.collection,
                query_vector=vec,
                limit=top_k,
                query_filter=Filter(must=filters),
                with_payload=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Qdrant search failed: %s", exc)
            return []

        claims: list[EvidenceClaim] = []
        for r in results:
            payload = dict(r.payload or {})
            cid = payload.get("claim_id") or payload.get("chunk_id") or str(r.id)
            text = payload.get("text") or payload.get("passage_text") or ""
            claims.append(
                EvidenceClaim(
                    claim_id=cid,
                    doc_id=payload.get("doc_id", "unknown"),
                    text=text,
                    score=float(r.score),
                    publication_date=payload.get("publication_date"),
                )
            )
        return claims

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
