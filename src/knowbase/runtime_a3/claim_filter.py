"""Claim Filter runtime — score sémantique claim↔question pour Synthesize.

Post-A3.9-bis : le grounding (subject + predicate) est résolu, mais Synthesize
reçoit TOUS les claims du subject (jusqu'à 30) et le LLM en choisit certains
hors-sujet pour la question précise. Ce module pré-filtre les claims par
score sémantique avant qu'ils n'arrivent au prompt LLM.

Pipeline :
    1. Concaténer chaque claim en "{subject} {predicate} {value}" (string lisible).
    2. Encoder la question + chaque claim_text via Sentence Transformer (batch).
    3. Cosine similarity entre la question et chaque claim.
    4. Garder top-K claims avec score >= MIN_SCORE.
    5. Si filtre vide → renvoyer top-1 quand même (graceful fallback : on garde
       au moins 1 claim pour que Synthesize puisse produire une réponse).

Charte stricte : aucun token corpus-spécifique, scoring purement sémantique.

Toggle env var : `V6_CLAIM_FILTER_ENABLED` (default "1").
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from knowbase.runtime_a3.schemas import (
    ClaimFilterResult,
    ClaimSummary,
    ScoredClaim,
)

logger = logging.getLogger("knowbase.runtime_a3.claim_filter")


# Constants
# MIN_SCORE calibré sur ms-marco-style relevance (sentence-transformers e5-large)
# cosine similarity. Score [0.5, 0.7] = relevance plausible, [0.7+] = fort.
# Seuil 0.55 = conservateur (laisse passer relevance faible mais filtre noise).
# MIN_SCORE et TOP_K calibrés sur smoke Q "options connectivite Azure RISE" :
# top-1 ExpressRoute=0.91, last skeleton=0.85. Scores serrés (e5-large encodings
# claim_text courts). On vise top-K dur pour réduire le bruit envoyé au LLM
# Synthesize plutôt que de compter sur le seuil.
MIN_SCORE = 0.55
TOP_K_DEFAULT = 5  # max claims envoyés à Synthesize après filtrage
MIN_KEPT = 1        # garde toujours au moins 1 claim (graceful fallback)

# L1 (31/05/2026) — Gate final fusionné cos + lexical.
# Le gate final (ClaimFilter) déterminait jusqu'ici la sélection top-K via un
# cosinus e5 PUR sur le triplet reconstruit subject+predicate+value. Deux
# faiblesses corrigées ici, toutes deux GRATUITES en LLM :
#   1. Scorer sur le c.text VERBATIM quand dispo (cohérent avec CE + Synthesize ;
#      cf fix c.text P2.4 jamais propagé au ClaimFilter). Toggle V6_GATE_VERBATIM_TEXT.
#   2. Fusionner un signal LEXICAL pondéré-identifiants pour protéger l'exact-id
#      (le cosinus sémantique pur perd le signal type-BM25 sur les codes/entités).
#      final = (1-λ)·cos + λ·lexical. Toggle V6_GATE_LEXICAL_WEIGHT (λ).
# Domain-agnostic strict : aucun token corpus-spécifique ; "identifiant" = forme
# (chiffres, ponctuation interne alnum, ALLCAPS court) — vrai en médical/légal/aéro.
#
# RÉSULTAT BENCH A/B/C (31/05/2026, 50q déterministe + juge) :
#   - verbatim=1 SEUL  → exact_id 0.712→0.732, abstention 84%→96%, C1 0.43→0.49 (GAIN NET).
#   - + lexical λ=0.25 → ANNULE le gain (exact_id 0.711, factual juge 0.500→0.367). NOCIF.
# → défaut : verbatim ON, lexical OFF (λ=0). Le code lexical reste dispo (toggle) mais
#   l'isolation a réfuté l'hypothèse globale. L'exact_id factual reste bloqué à 0.60 dans
#   les 3 bras → le goulot exact_id est le POOL DE RETRIEVAL, pas le gate (cf L3/L5).
_LEXICAL_WEIGHT_DEFAULT = float(os.getenv("V6_GATE_LEXICAL_WEIGHT", "0.0"))
_USE_VERBATIM_DEFAULT = os.getenv("V6_GATE_VERBATIM_TEXT", "1") == "1"
_IDENTIFIER_TOKEN_WEIGHT = 3.0  # un identifiant matché pèse 3× un mot ordinaire

_TOKEN_RE = re.compile(r"[A-Za-z0-9_/.\-]+")
# Stopwords FR+EN + mots interrogatifs : du bruit pour le matching lexical.
_STOPWORDS = frozenset({
    "the", "and", "for", "with", "what", "which", "who", "whom", "whose", "when",
    "where", "why", "how", "are", "is", "was", "were", "does", "did", "can",
    "could", "should", "would", "this", "that", "these", "those", "from", "into",
    "about", "between", "of", "to", "in", "on", "by", "as", "at", "or", "an", "a",
    "le", "la", "les", "des", "une", "un", "du", "de", "et", "ou", "que", "qui",
    "quoi", "quel", "quelle", "quels", "quelles", "comment", "pour", "avec", "sur",
    "dans", "est", "sont", "quand", "entre", "par", "aux", "ce", "ces", "cette",
})


def _claim_text(claim: ClaimSummary) -> str:
    """Concat subject + predicate + value en string lisible pour embedding."""
    parts: List[str] = []
    if claim.subject_canonical:
        parts.append(claim.subject_canonical)
    if claim.predicate:
        # UPPER_SNAKE → "lower words" pour matcher la question naturelle
        parts.append(claim.predicate.replace("_", " ").lower())
    val = claim.value or claim.value_normalized
    if val:
        parts.append(str(val))
    return " ".join(parts).strip()


def _claim_verbatim_text(claim: ClaimSummary) -> str:
    """Texte le plus riche du claim pour scoring : c.text verbatim > triplet.

    Cohérent avec le chemin cross-encoder (_claim_to_rerank_text) et Synthesize.
    Le verbatim (extra Pydantic `text`, posé par _claim_from_node) capte les
    claims narratifs que le triplet subject+predicate+value laisse quasi-vides.
    """
    extras = claim.model_dump()
    for key in ("text", "claim_text_full", "verbatim_quote", "passage_text"):
        val = extras.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return _claim_text(claim)


def _is_identifier_token(tok: str) -> bool:
    """Heuristique de FORME (domain-agnostic) : le token ressemble-t-il à un
    identifiant/code (transaction SAP, réf réglementaire, code aéro, etc.) ?

    Vrai si : contient un chiffre, OU ponctuation interne alnum (/ _ . -), OU
    ALLCAPS court (≥2). Aucune liste corpus-spécifique.
    """
    if any(ch.isdigit() for ch in tok):
        return True
    if any(ch in "/_.-" for ch in tok) and any(ch.isalnum() for ch in tok):
        return True
    if len(tok) >= 2 and tok.isupper():
        return True
    return False


def _weighted_query_tokens(question: str) -> Dict[str, float]:
    """Tokens de contenu de la question → poids (identifiants sur-pondérés).

    Classifie l'identifiant-ness sur la casse d'origine, puis indexe en lowercase
    pour le matching insensible à la casse.
    """
    weights: Dict[str, float] = {}
    for tok in _TOKEN_RE.findall(question or ""):
        low = tok.lower()
        if low in _STOPWORDS:
            continue
        ident = _is_identifier_token(tok)
        if len(tok) < 3 and not ident:
            continue
        w = _IDENTIFIER_TOKEN_WEIGHT if ident else 1.0
        weights[low] = max(weights.get(low, 0.0), w)
    return weights


def _lexical_overlap(q_weights: Dict[str, float], claim_text: str) -> float:
    """Containment pondéré des tokens-question dans le texte du claim → [0,1].

    num = Σ poids(t) pour t présent dans le claim ; den = Σ poids(t). Les
    identifiants (poids 3) dominent : matcher un code rare prime sur les mots
    ordinaires. 0 si la question n'a aucun token de contenu (→ fusion = cos pur).
    """
    if not q_weights:
        return 0.0
    claim_tokens = {t.lower() for t in _TOKEN_RE.findall(claim_text or "")}
    if not claim_tokens:
        return 0.0
    num = sum(w for t, w in q_weights.items() if t in claim_tokens)
    den = sum(q_weights.values())
    return (num / den) if den else 0.0


class ClaimFilter:
    """Filtre les claims par score sémantique vs la question.

    Injection de dépendances :
        - `embedder` : callable `(texts: List[str]) -> List[List[float]]` (batch)
    """

    def __init__(
        self,
        embedder: Optional[Callable[[List[str]], List[List[float]]]] = None,
        min_score: float = MIN_SCORE,
        top_k: int = TOP_K_DEFAULT,
        min_kept: int = MIN_KEPT,
        lexical_weight: Optional[float] = None,
        use_verbatim_text: Optional[bool] = None,
    ):
        self._embedder = embedder
        self._min_score = min_score
        self._top_k = top_k
        self._min_kept = min_kept
        # L1 — fusion gate final. Défauts via env (V6_GATE_*), surchargeables
        # par paramètre (tests / bench d'ablation isolé).
        self._lexical_weight = (
            lexical_weight if lexical_weight is not None else _LEXICAL_WEIGHT_DEFAULT
        )
        self._use_verbatim_text = (
            use_verbatim_text if use_verbatim_text is not None else _USE_VERBATIM_DEFAULT
        )

    def _get_embedder(self):
        if self._embedder is None:
            from knowbase.common.clients.embeddings import EmbeddingModelManager
            mgr = EmbeddingModelManager()
            self._embedder = lambda texts: [v.tolist() for v in mgr.encode(texts)]
        return self._embedder

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def filter(
        self,
        question: str,
        claims: List[ClaimSummary],
        groups: Optional[List[int]] = None,
        top_k: Optional[int] = None,
    ) -> Tuple[List[ClaimSummary], ClaimFilterResult]:
        """Filtre les claims par pertinence sémantique vs la question.

        Args:
            question : la question utilisateur
            claims : liste de claims à filtrer
            groups : liste parallèle d'IDs de groupe (typiquement sub_goal_idx).
                Si fourni, applique top-K **par groupe** (préserve la diversité
                pour les comparaisons et list_enumeration multi-sub_goal).
                Si None, top-K global.
            top_k : override du top-K par défaut (P3.2 — élargi pour les
                questions-liste afin de ne pas tronquer les réponses multi-items).

        Returns:
            (kept_claims, ClaimFilterResult)
            - kept_claims : sous-liste, ordre = score DESC (ou intra-groupe DESC)
            - ClaimFilterResult : trace observability
        """
        t0 = time.perf_counter()
        n_in = len(claims)
        eff_top_k = top_k if top_k is not None else self._top_k

        if groups is not None and len(groups) != len(claims):
            raise ValueError(
                f"groups length ({len(groups)}) must match claims length ({len(claims)})"
            )

        if not question or not question.strip() or not claims:
            return claims, ClaimFilterResult(
                n_input=n_in,
                n_kept=n_in,
                method="passthrough",
                duration_s=time.perf_counter() - t0,
            )

        # Préparer les textes. L1 — embedding sur c.text verbatim si activé
        # (capte les claims narratifs) ; sinon triplet legacy (ablation baseline).
        if self._use_verbatim_text:
            claim_texts = [_claim_verbatim_text(c) for c in claims]
        else:
            claim_texts = [_claim_text(c) for c in claims]
        # Texte pour le matching lexical : toujours le plus riche (verbatim),
        # car on cherche la présence d'identifiants/entités où qu'ils soient.
        lex_texts = [_claim_verbatim_text(c) for c in claims]
        q_weights = (
            _weighted_query_tokens(question) if self._lexical_weight > 0.0 else {}
        )
        # Filtrer les claims sans texte (rare mais on garde l'index)
        valid_indices = [i for i, t in enumerate(claim_texts) if t]
        if not valid_indices:
            return claims, ClaimFilterResult(
                n_input=n_in,
                n_kept=n_in,
                method="no_claim_text",
                duration_s=time.perf_counter() - t0,
            )

        try:
            # Batch encode : question + tous claim_texts en 1 appel
            all_texts = [question] + [claim_texts[i] for i in valid_indices]
            embeddings = self._get_embedder()(all_texts)
        except Exception:
            logger.exception("claim_filter: embedder failed, passthrough")
            return claims, ClaimFilterResult(
                n_input=n_in,
                n_kept=n_in,
                method="embedder_error",
                duration_s=time.perf_counter() - t0,
            )

        q_vec = embeddings[0]
        claim_vecs = embeddings[1:]

        # Cosine similarity
        scored: List[Tuple[int, float]] = []
        q_norm = sum(x * x for x in q_vec) ** 0.5
        if q_norm == 0:
            return claims, ClaimFilterResult(
                n_input=n_in,
                n_kept=n_in,
                method="zero_query_norm",
                duration_s=time.perf_counter() - t0,
            )

        lam = self._lexical_weight
        for local_i, vec in enumerate(claim_vecs):
            c_norm = sum(x * x for x in vec) ** 0.5
            if c_norm == 0:
                continue
            dot = sum(a * b for a, b in zip(q_vec, vec))
            sim = max(0.0, min(1.0, dot / (q_norm * c_norm)))
            original_idx = valid_indices[local_i]
            # L1 — fusion : final = (1-λ)·cos + λ·lexical. λ=0 → cosinus pur
            # (baseline strictement préservée).
            if lam > 0.0 and q_weights:
                lex = _lexical_overlap(q_weights, lex_texts[original_idx])
                final = (1.0 - lam) * sim + lam * lex
            else:
                final = sim
            scored.append((original_idx, final))

        if not scored:
            return claims, ClaimFilterResult(
                n_input=n_in,
                n_kept=n_in,
                method="no_valid_vec",
                duration_s=time.perf_counter() - t0,
            )

        # Sort DESC par score
        scored.sort(key=lambda t: t[1], reverse=True)

        # Sélection : top-K avec score >= MIN_SCORE, mais au moins MIN_KEPT.
        # Si `groups` fourni, top-K est appliqué PAR groupe (stratification).
        if groups is None:
            kept_with_threshold = [(i, s) for i, s in scored if s >= self._min_score]
            if len(kept_with_threshold) < self._min_kept:
                kept_indices_scores = scored[: self._min_kept]
            else:
                kept_indices_scores = kept_with_threshold[: eff_top_k]
        else:
            # Stratification par groupe : top-K par groupe distinct
            kept_per_group: Dict[int, List[Tuple[int, float]]] = {}
            for idx, sim in scored:
                g = groups[idx]
                if g not in kept_per_group:
                    kept_per_group[g] = []
                # On limite top-K par groupe, en respectant le seuil (sauf min_kept)
                if sim >= self._min_score or len(kept_per_group[g]) < self._min_kept:
                    if len(kept_per_group[g]) < eff_top_k:
                        kept_per_group[g].append((idx, sim))
            # Flat back to a list, intra-group DESC déjà respecté (scored est DESC)
            kept_indices_scores = []
            for g_items in kept_per_group.values():
                kept_indices_scores.extend(g_items)
            # Tri global final DESC pour cohérence
            kept_indices_scores.sort(key=lambda t: t[1], reverse=True)

        kept_set = {i for i, _ in kept_indices_scores}

        # Ordre kept : par score DESC
        kept_claims: List[ClaimSummary] = []
        for idx, _ in kept_indices_scores:
            kept_claims.append(claims[idx])

        # Trace : tous claims scorés (kept + filtered)
        scored_results: List[ScoredClaim] = []
        for idx, sim in scored:
            scored_results.append(ScoredClaim(
                claim_id=claims[idx].claim_id or f"idx_{idx}",
                score=sim,
                kept=(idx in kept_set),
            ))

        if lam > 0.0:
            method = f"fused_cos_lex(λ={lam:.2f},verbatim={int(self._use_verbatim_text)})"
        elif self._use_verbatim_text:
            method = "embedding_cosine(verbatim)"
        else:
            method = "embedding_cosine"
        result = ClaimFilterResult(
            scored=scored_results,
            n_input=n_in,
            n_kept=len(kept_claims),
            method=method,
            duration_s=time.perf_counter() - t0,
        )

        if logger.isEnabledFor(logging.INFO):
            kept_preview = [
                f"{claims[i].claim_id}({s:.2f})"
                for i, s in kept_indices_scores[:5]
            ]
            logger.info(
                "claim_filter: %d→%d kept (top-5: %s) in %.2fs",
                n_in, len(kept_claims), kept_preview, result.duration_s,
            )

        return kept_claims, result


# ============================================================================
# Top-level API
# ============================================================================


def filter_claims(
    question: str,
    claims: List[ClaimSummary],
    filter_obj: Optional[ClaimFilter] = None,
) -> Tuple[List[ClaimSummary], ClaimFilterResult]:
    """API top-level."""
    f = filter_obj or ClaimFilter()
    return f.filter(question, claims)
