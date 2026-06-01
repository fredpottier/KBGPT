"""Tests unitaires ClaimFilter (A3.11).

Stratégie : embedder mocké pour scores cosine déterministes.
"""

from __future__ import annotations

from typing import List
from unittest.mock import MagicMock

import pytest

from knowbase.runtime_a3.claim_filter import (
    ClaimFilter,
    MIN_SCORE,
    TOP_K_DEFAULT,
    _claim_text,
    _claim_verbatim_text,
    _is_identifier_token,
    _lexical_overlap,
    _weighted_query_tokens,
    filter_claims,
)
from knowbase.runtime_a3.schemas import ClaimFilterResult, ClaimSummary


# ============================================================================
# Helpers
# ============================================================================


def _claim(cid: str, subj: str = "S", pred: str = "P", val: str = "V") -> ClaimSummary:
    return ClaimSummary(
        claim_id=cid, subject_canonical=subj, predicate=pred, value=val,
    )


def _make_embedder(mapping: dict):
    """Embedder mock : prend une liste de texts, retourne le vector mapping[t]
    si défini, sinon vector zéro 4D."""
    def _embed(texts: List[str]) -> List[List[float]]:
        return [mapping.get(t, [0.0, 0.0, 0.0, 0.0]) for t in texts]
    return _embed


# ============================================================================
# TestClaimText
# ============================================================================


class TestClaimText:
    def test_basic_concat(self):
        c = _claim("c1", subj="Workbench", pred="PROCESSES", val="print requests")
        assert _claim_text(c) == "Workbench processes print requests"

    def test_upper_snake_lowercased(self):
        c = _claim("c1", subj="X", pred="HAS_VERSION", val="2.0")
        assert "has version" in _claim_text(c).lower()

    def test_empty_predicate(self):
        c = ClaimSummary(claim_id="c1", subject_canonical="X", predicate=None, value="v")
        out = _claim_text(c)
        assert "X" in out
        assert "v" in out

    def test_uses_value_normalized_if_no_value(self):
        c = ClaimSummary(
            claim_id="c1", subject_canonical="X", predicate="P",
            value=None, value_normalized="normalized_v",
        )
        assert "normalized_v" in _claim_text(c)


# ============================================================================
# TestPassthrough
# ============================================================================


class TestPassthrough:
    def test_empty_question_returns_all(self):
        f = ClaimFilter(embedder=lambda t: [[0.0]*4]*len(t))
        claims = [_claim("c1"), _claim("c2")]
        kept, result = f.filter("", claims)
        assert kept == claims
        assert result.method == "passthrough"
        assert result.n_kept == 2

    def test_empty_claims_returns_empty(self):
        f = ClaimFilter(embedder=lambda t: [[0.0]*4]*len(t))
        kept, result = f.filter("any question", [])
        assert kept == []
        assert result.method == "passthrough"

    def test_whitespace_question(self):
        f = ClaimFilter(embedder=lambda t: [[0.0]*4]*len(t))
        kept, result = f.filter("   ", [_claim("c1")])
        assert result.method == "passthrough"


# ============================================================================
# TestRanking
# ============================================================================


class TestRanking:
    def test_top_claim_ranked_first(self):
        # Setup : query vector aligned with c1, orthogonal to c2/c3
        embed_map = {
            "query relevant": [1.0, 0.0, 0.0, 0.0],
            "X relevant claim": [1.0, 0.0, 0.0, 0.0],   # cos=1.0
            "X other thing": [0.0, 1.0, 0.0, 0.0],      # cos=0
            "X another thing": [0.0, 0.0, 1.0, 0.0],    # cos=0
        }
        f = ClaimFilter(embedder=_make_embedder(embed_map))
        claims = [
            ClaimSummary(claim_id="c2", subject_canonical="X", predicate="OTHER", value="thing"),
            ClaimSummary(claim_id="c1", subject_canonical="X", predicate="RELEVANT", value="claim"),
            ClaimSummary(claim_id="c3", subject_canonical="X", predicate="ANOTHER", value="thing"),
        ]
        kept, result = f.filter("query relevant", claims)
        assert kept[0].claim_id == "c1"

    def test_top_k_truncation(self):
        # 7 claims, TOP_K=5 → garde max 5
        embed_map = {"q": [1.0, 0.0]}
        embed_map.update({f"X p{i} v": [1.0 - i * 0.05, 0.1] for i in range(7)})
        f = ClaimFilter(embedder=_make_embedder(embed_map), top_k=5)
        claims = [
            ClaimSummary(claim_id=f"c{i}", subject_canonical="X", predicate=f"p{i}", value="v")
            for i in range(7)
        ]
        kept, result = f.filter("q", claims)
        assert len(kept) == 5
        assert result.n_input == 7
        assert result.n_kept == 5


# ============================================================================
# TestMinScore
# ============================================================================


class TestMinScore:
    def test_below_min_score_filtered(self):
        # 2 claims, l'un fort, l'autre orthogonal
        embed_map = {
            "q": [1.0, 0.0],
            "X strong v": [1.0, 0.0],       # cos=1.0
            "X weak v": [0.0, 1.0],         # cos=0.0
        }
        f = ClaimFilter(
            embedder=_make_embedder(embed_map),
            min_score=0.5,
            min_kept=1,
        )
        claims = [
            ClaimSummary(claim_id="strong", subject_canonical="X", predicate="strong", value="v"),
            ClaimSummary(claim_id="weak", subject_canonical="X", predicate="weak", value="v"),
        ]
        kept, result = f.filter("q", claims)
        # Strong gardé, weak filtré
        kept_ids = [c.claim_id for c in kept]
        assert "strong" in kept_ids
        assert "weak" not in kept_ids

    def test_min_kept_floor(self):
        # Tous claims sous seuil → garde min_kept quand même
        embed_map = {"q": [1.0, 0.0], "X p1 v": [0.0, 1.0], "X p2 v": [0.0, 1.0]}
        f = ClaimFilter(
            embedder=_make_embedder(embed_map),
            min_score=0.9,
            min_kept=2,
        )
        claims = [
            ClaimSummary(claim_id="c1", subject_canonical="X", predicate="p1", value="v"),
            ClaimSummary(claim_id="c2", subject_canonical="X", predicate="p2", value="v"),
        ]
        kept, _ = f.filter("q", claims)
        assert len(kept) == 2  # min_kept=2, tous gardés malgré min_score=0.9


# ============================================================================
# TestErrorHandling
# ============================================================================


class TestErrorHandling:
    def test_embedder_exception_fallback_unfiltered(self):
        def _embed(texts):
            raise RuntimeError("embedder down")
        f = ClaimFilter(embedder=_embed)
        claims = [_claim("c1"), _claim("c2")]
        kept, result = f.filter("q", claims)
        assert kept == claims  # fallback : tous gardés
        assert result.method == "embedder_error"

    def test_zero_norm_query_returns_unfiltered(self):
        embed_map = {"q": [0.0, 0.0, 0.0, 0.0]}
        f = ClaimFilter(embedder=_make_embedder(embed_map))
        claims = [_claim("c1"), _claim("c2")]
        kept, result = f.filter("q", claims)
        assert kept == claims
        assert result.method == "zero_query_norm"

    def test_zero_norm_claim_skipped(self):
        # c1 OK, c2 zero-norm
        embed_map = {
            "q": [1.0, 0.0],
            "X p1 v": [1.0, 0.0],
            "X p2 v": [0.0, 0.0],
        }
        f = ClaimFilter(embedder=_make_embedder(embed_map))
        claims = [
            ClaimSummary(claim_id="c1", subject_canonical="X", predicate="p1", value="v"),
            ClaimSummary(claim_id="c2", subject_canonical="X", predicate="p2", value="v"),
        ]
        kept, result = f.filter("q", claims)
        kept_ids = [c.claim_id for c in kept]
        assert "c1" in kept_ids


# ============================================================================
# TestResultTrace
# ============================================================================


class TestResultTrace:
    def test_scored_includes_all_with_kept_flag(self):
        embed_map = {
            "q": [1.0, 0.0],
            "X strong v": [1.0, 0.0],
            "X weak v": [0.0, 1.0],
        }
        f = ClaimFilter(
            embedder=_make_embedder(embed_map),
            min_score=0.5,
        )
        claims = [
            ClaimSummary(claim_id="strong", subject_canonical="X", predicate="strong", value="v"),
            ClaimSummary(claim_id="weak", subject_canonical="X", predicate="weak", value="v"),
        ]
        _, result = f.filter("q", claims)
        # Les 2 claims doivent apparaitre dans scored avec kept flag
        assert len(result.scored) == 2
        sm = {s.claim_id: s for s in result.scored}
        assert sm["strong"].kept is True
        assert sm["weak"].kept is False


# ============================================================================
# TestTopLevelAPI
# ============================================================================


class TestStratification:
    """A3.11-fix : top-K par sub_goal pour préserver diversité (comparison)."""

    def test_groups_preserve_diversity(self):
        # 4 claims : groupe 0 (sub_goal_idx=0) a 3 claims, groupe 1 a 1 claim
        # Sans stratif + top_k=2, on garderait 2 claims du groupe 0 (les plus scorés)
        # AVEC stratif + top_k=2 par groupe, on garde au max 2 par groupe.
        # Or il faut au moins garder le claim du groupe 1.
        embed_map = {
            "q": [1.0, 0.0, 0.0],
            "X p1 v1": [1.0, 0.0, 0.0],  # cos=1.0  (groupe 0)
            "X p2 v2": [0.9, 0.1, 0.0],  # cos≈0.9 (groupe 0)
            "X p3 v3": [0.8, 0.0, 0.1],  # cos≈0.8 (groupe 0)
            "Y p4 v4": [0.5, 0.5, 0.0],  # cos≈0.5 (groupe 1)
        }
        f = ClaimFilter(embedder=_make_embedder(embed_map), top_k=2, min_score=0.3)
        claims = [
            ClaimSummary(claim_id="c1", subject_canonical="X", predicate="p1", value="v1"),
            ClaimSummary(claim_id="c2", subject_canonical="X", predicate="p2", value="v2"),
            ClaimSummary(claim_id="c3", subject_canonical="X", predicate="p3", value="v3"),
            ClaimSummary(claim_id="c4", subject_canonical="Y", predicate="p4", value="v4"),
        ]
        groups = [0, 0, 0, 1]
        kept, _ = f.filter("q", claims, groups=groups)
        kept_ids = {c.claim_id for c in kept}
        # Doit contenir c4 (groupe 1) + top-2 du groupe 0
        assert "c4" in kept_ids
        # Top-2 du groupe 0 = c1 (1.0) + c2 (0.9)
        assert "c1" in kept_ids
        assert "c2" in kept_ids
        # c3 filtré (3e du groupe 0)
        assert "c3" not in kept_ids
        assert len(kept) == 3

    def test_groups_length_mismatch_raises(self):
        f = ClaimFilter(embedder=lambda t: [[1.0]] * len(t))
        with pytest.raises(ValueError):
            f.filter("q", [_claim("c1")], groups=[0, 1])

    def test_groups_none_keeps_global_behavior(self):
        # Pas de groups → comportement global classique
        embed_map = {"q": [1.0, 0.0], "X p v": [1.0, 0.0]}
        f = ClaimFilter(embedder=_make_embedder(embed_map))
        claims = [_claim("c1", pred="p", val="v")]
        kept, _ = f.filter("q", claims, groups=None)
        assert kept == claims


class TestTopLevelAPI:
    def test_filter_claims_uses_injected(self):
        embed_map = {"q": [1.0, 0.0], "X p v": [1.0, 0.0]}
        injected = ClaimFilter(embedder=_make_embedder(embed_map))
        claims = [_claim("c1", pred="p", val="v")]
        kept, result = filter_claims("q", claims, filter_obj=injected)
        assert isinstance(result, ClaimFilterResult)
        assert kept == claims


# ============================================================================
# L1 — Gate final fusionné (verbatim c.text + signal lexical)
# ============================================================================


class TestIdentifierToken:
    def test_digit_token_is_identifier(self):
        assert _is_identifier_token("CG5Z") is True
        assert _is_identifier_token("2021/821") is True

    def test_internal_punct_is_identifier(self):
        assert _is_identifier_token("/SAPAPO/OM03") is True
        assert _is_identifier_token("S_ALR_87012326") is True

    def test_allcaps_short_is_identifier(self):
        assert _is_identifier_token("RISE") is True
        assert _is_identifier_token("WWI") is True

    def test_ordinary_word_not_identifier(self):
        assert _is_identifier_token("transaction") is False
        assert _is_identifier_token("Workbench") is False


class TestWeightedQueryTokens:
    def test_identifiers_overweighted(self):
        w = _weighted_query_tokens("What does transaction CG5Z do")
        # CG5Z (identifiant) pèse 3, transaction pèse 1
        assert w["cg5z"] == 3.0
        assert w["transaction"] == 1.0

    def test_stopwords_and_short_dropped(self):
        w = _weighted_query_tokens("What is the X of Y")
        # what/is/the/of dropped ; X/Y trop courts et non-identifiants → droppés
        assert "what" not in w
        assert "the" not in w

    def test_empty_question(self):
        assert _weighted_query_tokens("") == {}


class TestLexicalOverlap:
    def test_identifier_match_dominates(self):
        qw = _weighted_query_tokens("transaction CG5Z")  # {transaction:1, cg5z:3}
        # claim contenant l'identifiant → overlap élevé
        high = _lexical_overlap(qw, "The CG5Z transaction shows documents")
        low = _lexical_overlap(qw, "Some other unrelated content here")
        assert high > 0.9
        assert low == 0.0

    def test_empty_weights_returns_zero(self):
        assert _lexical_overlap({}, "anything") == 0.0


class TestVerbatimText:
    def test_prefers_verbatim_over_triplet(self):
        c = ClaimSummary(
            claim_id="c1", subject_canonical="X", predicate="P", value="v",
            text="Full verbatim claim text about CG5Z",
        )
        assert _claim_verbatim_text(c) == "Full verbatim claim text about CG5Z"

    def test_falls_back_to_triplet_without_text(self):
        c = ClaimSummary(claim_id="c1", subject_canonical="X", predicate="P", value="v")
        assert _claim_verbatim_text(c) == _claim_text(c)


class TestFusionRanking:
    """Le signal lexical doit rattraper un match exact-id que le cosinus rate."""

    def _claims(self):
        return [
            ClaimSummary(
                claim_id="wrong", subject_canonical="X", predicate="P", value="v",
                text="some semantically similar blah",
            ),
            ClaimSummary(
                claim_id="right", subject_canonical="X", predicate="P", value="v",
                text="the CG5Z transaction displays documents",
            ),
        ]

    def _embedder(self):
        # cosinus PIÉGÉ : le mauvais claim est sémantiquement "proche", le bon ne l'est pas
        return _make_embedder({
            "transaction CG5Z": [1.0, 0.0],
            "some semantically similar blah": [1.0, 0.0],       # cos=1.0 (piège)
            "the CG5Z transaction displays documents": [0.0, 1.0],  # cos=0.0
        })

    def test_lambda_zero_is_pure_cosine_baseline(self):
        f = ClaimFilter(embedder=self._embedder(), lexical_weight=0.0, min_score=0.0)
        kept, result = f.filter("transaction CG5Z", self._claims())
        # cosinus pur → le piège gagne
        assert kept[0].claim_id == "wrong"
        assert result.method.startswith("embedding_cosine")

    def test_lexical_fusion_rescues_exact_id(self):
        f = ClaimFilter(embedder=self._embedder(), lexical_weight=0.7, min_score=0.0)
        kept, result = f.filter("transaction CG5Z", self._claims())
        # fusion λ=0.7 → le claim contenant l'identifiant remonte premier
        assert kept[0].claim_id == "right"
        assert "fused" in result.method

    def test_verbatim_used_for_embedding(self):
        # Si verbatim OFF, l'embedding se fait sur le triplet "X p v" (pas le text)
        f = ClaimFilter(
            embedder=_make_embedder({"transaction CG5Z": [1.0, 0.0], "X P v": [1.0, 0.0]}),
            lexical_weight=0.0, use_verbatim_text=False, min_score=0.0,
        )
        c = ClaimSummary(
            claim_id="c1", subject_canonical="X", predicate="P", value="v",
            text="the CG5Z transaction displays documents",
        )
        kept, _ = f.filter("transaction CG5Z", [c])
        # pas d'exception + claim gardé (embedding sur triplet "X p v")
        assert kept[0].claim_id == "c1"
