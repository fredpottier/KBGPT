"""Predicate Resolver runtime — résout user predicate_hint → predicate KG canonique.

Pendant naturel du subject_resolver (A3.9). Le Parse LLM produit des
predicate_hints user-friendly ("transaction", "role", "version"), mais le
KG stocke des predicates canoniques UPPER_SNAKE ("PROCESSES", "ENABLES",
"HAS_VERSION"). Sans résolution, le filtre Cypher `c.predicate = $predicate`
ne match jamais.

Pipeline 3 étapes domain-agnostic :
    1. Passthrough — si predicate_hint est None/empty → return None
    2. Exact match — si predicate_hint déjà UPPER_SNAKE et présent en KG → use direct
    3. Embedding fallback — cosine similarity top-1 sur les predicates KG du tenant
       (cache LRU au premier accès). Si sim >= MIN_CONFIDENCE → use, sinon abstain.

Charte stricte : domain-agnostic. Aucun mapping hardcodé user→KG. Les predicates
KG sont chargés dynamiquement par tenant. L'embedding compare sémantiquement.

Toggle env var : `V6_PREDICATE_RESOLVER_ENABLED` (default "1").
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from knowbase.runtime_a3.schemas import (
    PredicateCandidate,
    PredicateResolverError,
    PredicateResolverResult,
)

logger = logging.getLogger("knowbase.runtime_a3.predicate_resolver")


# Constants
# MIN_CONFIDENCE calibré sur smoke 12 hints sur KG SAP (19 predicates) :
# - Lemma exact match (ex: 'uses' → USES) : score 1.00
# - Match sémantique fort (ex: 'integration' → INTEGRATED_IN) : 0.89-0.93
# - Match plausible (ex: 'transaction' → PROCESSES) : 0.82-0.84
# - Bruit pur ('unknown_xyz') : 0.83 (top1 indiscernable du noise floor)
# Seuil 0.88 = conservateur : abstient sur les matchs douteux ET le bruit.
# Stratégie fail-open : abstain → predicate=None → Cypher filtre rien → safe.
MIN_CONFIDENCE = 0.88
EXACT_CONFIDENCE = 1.0
TOP_K_RETURNED = 5

# Cache TTL pour la liste des predicates KG (par tenant)
PREDICATES_CACHE_TTL_S = 300.0  # 5 min — KG schema évolue rarement

# Reconnaît un predicate canonique UPPER_SNAKE_CASE
UPPER_SNAKE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class PredicateResolver:
    """Résout un user predicate_hint vers le predicate canonique du KG.

    Injection de dépendances :
        - `neo4j_client` : objet exposant `.execute_query(query, **params) -> List[Dict]`
        - `embedder` : callable `(texts: List[str]) -> List[List[float]]` (batch)
    """

    def __init__(
        self,
        neo4j_client: Any = None,
        embedder: Optional[Callable[[List[str]], List[List[float]]]] = None,
        min_confidence: float = MIN_CONFIDENCE,
    ):
        self._neo4j = neo4j_client
        self._embedder = embedder
        self._min_confidence = min_confidence
        # Cache : tenant_id -> (timestamp, predicates: List[str], embeddings: List[List[float]])
        self._cache: Dict[str, Tuple[float, List[str], List[List[float]]]] = {}

    # ------------------------------------------------------------------
    # Lazy default clients
    # ------------------------------------------------------------------

    def _get_neo4j(self):
        if self._neo4j is None:
            from knowbase.common.clients.neo4j_client import get_neo4j_client
            self._neo4j = get_neo4j_client()
        return self._neo4j

    def _get_embedder(self):
        if self._embedder is None:
            from knowbase.common.clients.embeddings import EmbeddingModelManager
            mgr = EmbeddingModelManager()
            self._embedder = lambda texts: [v.tolist() for v in mgr.encode(texts)]
        return self._embedder

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(
        self,
        predicate_hint: Optional[str],
        tenant_id: str = "default",
    ) -> PredicateResolverResult:
        """Résout predicate_hint → predicate KG canonique."""
        t0 = time.perf_counter()

        # Step 1 : passthrough
        if predicate_hint is None or not str(predicate_hint).strip():
            return PredicateResolverResult(
                method="passthrough",
                abstain_reason="empty predicate_hint",
                duration_s=time.perf_counter() - t0,
            )

        hint = predicate_hint.strip()

        # Charge la liste des predicates KG (cache)
        try:
            kg_predicates, kg_embeddings = self._get_kg_predicates(tenant_id)
        except Exception:
            logger.exception("predicate_resolver: failed to load KG predicates")
            return PredicateResolverResult(
                method="error",
                abstain_reason="failed to load KG predicates",
                duration_s=time.perf_counter() - t0,
            )

        if not kg_predicates:
            return PredicateResolverResult(
                method="no_kg_predicates",
                abstain_reason="no predicate in KG for this tenant",
                duration_s=time.perf_counter() - t0,
            )

        # Step 2 : exact match (UPPER_SNAKE + présent en KG)
        if UPPER_SNAKE_RE.match(hint) and hint in kg_predicates:
            return PredicateResolverResult(
                resolved=hint,
                confidence=EXACT_CONFIDENCE,
                method="exact_kg",
                candidates=[PredicateCandidate(
                    predicate=hint, score=EXACT_CONFIDENCE, source="exact_kg",
                )],
                duration_s=time.perf_counter() - t0,
            )

        # Step 3 : embedding cosine top-1
        # On embed le hint en lower (cohérent avec le preprocess des predicates)
        try:
            user_vec = self._get_embedder()([hint.lower().replace("_", " ")])[0]
        except Exception:
            logger.exception("predicate_resolver: embedder failed")
            return PredicateResolverResult(
                method="error",
                abstain_reason="embedder failed",
                duration_s=time.perf_counter() - t0,
            )

        scored = _cosine_topk(user_vec, kg_embeddings, kg_predicates, k=TOP_K_RETURNED)

        if not scored:
            return PredicateResolverResult(
                method="no_candidates",
                abstain_reason="no candidates after embedding",
                duration_s=time.perf_counter() - t0,
            )

        top_pred, top_score = scored[0]
        candidates = [
            PredicateCandidate(predicate=p, score=s, source="embedding")
            for p, s in scored
        ]

        if top_score < self._min_confidence:
            return PredicateResolverResult(
                method="low_confidence",
                abstain_reason=(
                    f"top candidate {top_pred!r} score {top_score:.2f} "
                    f"< {self._min_confidence}"
                ),
                candidates=candidates,
                duration_s=time.perf_counter() - t0,
            )

        return PredicateResolverResult(
            resolved=top_pred,
            confidence=top_score,
            method="embedding",
            candidates=candidates,
            duration_s=time.perf_counter() - t0,
        )

    # ------------------------------------------------------------------
    # KG predicates loading (cached per tenant)
    # ------------------------------------------------------------------

    def _get_kg_predicates(
        self, tenant_id: str,
    ) -> Tuple[List[str], List[List[float]]]:
        """Charge (avec cache TTL) les predicates distincts du KG et leurs embeddings."""
        now = time.time()
        cached = self._cache.get(tenant_id)
        if cached is not None:
            ts, preds, embs = cached
            if (now - ts) < PREDICATES_CACHE_TTL_S:
                return preds, embs

        # Recharge
        rows = self._get_neo4j().execute_query(
            """
            MATCH (c:Claim {tenant_id: $tid})
            WHERE c.predicate IS NOT NULL
            RETURN DISTINCT c.predicate AS predicate
            ORDER BY predicate
            """,
            tid=tenant_id,
        )
        predicates = [r["predicate"] for r in rows if r.get("predicate")]
        if not predicates:
            self._cache[tenant_id] = (now, [], [])
            return [], []

        # Pré-traitement : UPPER_SNAKE_CASE → "lower words" pour matcher
        # sémantiquement avec un hint user en langue naturelle.
        # Le predicate original (UPPER_SNAKE) reste la valeur retournée
        # par .resolved (cohérence schéma KG).
        readable = [p.replace("_", " ").lower() for p in predicates]
        embeddings = self._get_embedder()(readable)
        self._cache[tenant_id] = (now, predicates, embeddings)
        logger.info(
            "predicate_resolver: loaded %d KG predicates for tenant=%s",
            len(predicates), tenant_id,
        )
        return predicates, embeddings

    def invalidate_cache(self, tenant_id: Optional[str] = None) -> None:
        """Invalide le cache (utile après ingestion qui change le schéma)."""
        if tenant_id is None:
            self._cache.clear()
        else:
            self._cache.pop(tenant_id, None)


# ============================================================================
# Helpers
# ============================================================================


def _cosine_topk(
    query_vec: List[float],
    candidate_vecs: List[List[float]],
    candidate_labels: List[str],
    k: int = 5,
) -> List[Tuple[str, float]]:
    """Retourne les top-k candidates par cosine similarity DESC.

    Score normalisé dans [0, 1] (cosine sim sur vecteurs normalisés
    appartient en théorie à [-1, 1] mais en pratique pour des embeddings
    sentence-transformers c'est [0, 1] approximativement).

    On clamp dans [0, 1] pour respecter le schéma PredicateCandidate.
    """
    if not candidate_vecs or not query_vec:
        return []
    if len(candidate_vecs) != len(candidate_labels):
        raise ValueError("candidate_vecs and candidate_labels length mismatch")

    # Norme du query vec
    q_norm = sum(x * x for x in query_vec) ** 0.5
    if q_norm == 0:
        return []

    scored: List[Tuple[str, float]] = []
    for label, vec in zip(candidate_labels, candidate_vecs):
        c_norm = sum(x * x for x in vec) ** 0.5
        if c_norm == 0:
            continue
        dot = sum(a * b for a, b in zip(query_vec, vec))
        sim = dot / (q_norm * c_norm)
        # Clamp dans [0, 1]
        sim_clamped = max(0.0, min(1.0, sim))
        scored.append((label, sim_clamped))

    scored.sort(key=lambda t: t[1], reverse=True)
    return scored[:k]


# ============================================================================
# Top-level API
# ============================================================================


def resolve_predicate(
    predicate_hint: Optional[str],
    tenant_id: str = "default",
    resolver: Optional[PredicateResolver] = None,
) -> PredicateResolverResult:
    """API top-level."""
    r = resolver or PredicateResolver()
    return r.resolve(predicate_hint, tenant_id)
