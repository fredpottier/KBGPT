# tests/claimfirst/test_dimension_mapper.py
"""Tests Phase 4 — Dimension Mapper (v1 compatible + v2 embedding)."""

import pytest
import numpy as np
from unittest.mock import patch, MagicMock

from knowbase.claimfirst.extractors.dimension_mapper import (
    map_to_dimension,
    DimensionMapperV2,
    MatchTrace,
    _cosine_similarity,
    _compute_embedding_bonus,
)
from knowbase.claimfirst.models.question_dimension import QuestionDimension


def _make_dim(key: str, value_type: str = "number", operators: list = None,
              status: str = "candidate") -> QuestionDimension:
    """Helper pour créer une QuestionDimension de test."""
    operators = operators or ["="]
    return QuestionDimension(
        dimension_id=QuestionDimension.make_id("default", key),
        dimension_key=key,
        canonical_question=f"What is the {key.replace('_', ' ')}?",
        value_type=value_type,
        allowed_operators=operators,
        status=status,
        tenant_id="default",
    )


# ── Tests v1 API (régression) ─────────────────────────────────────────

class TestDimensionMapper:

    def test_exact_match(self):
        registry = [_make_dim("data_retention_period")]
        dim_id, score = map_to_dimension(
            "data_retention_period", "What is the retention period?",
            "number", "=", registry,
        )
        assert dim_id is not None
        assert score == 1.0

    def test_new_dimension(self):
        registry = [_make_dim("data_retention_period")]
        dim_id, score = map_to_dimension(
            "backup_frequency", "How often are backups performed?",
            "enum", "=", registry,
        )
        assert dim_id is None
        assert score == 0.0

    def test_veto_inversion_min_max(self):
        registry = [_make_dim("min_version", "version", [">="])]
        dim_id, score = map_to_dimension(
            "max_version", "What is the maximum version?",
            "version", "<=", registry,
        )
        assert dim_id is None

    def test_incompatible_value_type(self):
        registry = [_make_dim("feature_status", "boolean")]
        dim_id, score = map_to_dimension(
            "feature_status", "Is the feature enabled?",
            "number", "=", registry,
        )
        assert dim_id is None

    def test_incompatible_operator(self):
        registry = [_make_dim("threshold", "number", [">="])]
        dim_id, score = map_to_dimension(
            "threshold", "What is the threshold?",
            "number", "<=", registry,
        )
        assert dim_id is None

    def test_empty_registry(self):
        dim_id, score = map_to_dimension(
            "any_key", "Any question?",
            "string", "=", [],
        )
        assert dim_id is None

    def test_prefix_match(self):
        registry = [_make_dim("data_retention_days", "number")]
        dim_id, score = map_to_dimension(
            "data_retention_period", "What is the retention period?",
            "number", "=", registry,
        )
        assert dim_id is not None
        assert score == 0.8

    def test_veto_enabled_disabled(self):
        registry = [_make_dim("feature_enabled", "boolean")]
        dim_id, score = map_to_dimension(
            "feature_disabled", "Is the feature disabled?",
            "boolean", "=", registry,
        )
        assert dim_id is None

    def test_merged_dimension_skipped(self):
        """Dimensions avec status=merged sont ignorées."""
        registry = [_make_dim("data_retention_period", status="merged")]
        dim_id, score = map_to_dimension(
            "data_retention_period", "What is the retention period?",
            "number", "=", registry,
        )
        assert dim_id is None


# ── Tests v2 : DimensionMapperV2 ─────────────────────────────────────

class TestDimensionMapperV2:

    def _make_mapper_with_mock_embeddings(self, similarity: float):
        """Crée un mapper v2 avec embeddings mockés retournant une similarité fixe."""
        mapper = DimensionMapperV2()
        vec_a = np.array([1.0, 0.0, 0.0])
        vec_b = np.array([similarity, np.sqrt(max(0, 1 - similarity**2)), 0.0])
        # Track texts to assign consistent vectors
        text_vecs = {}
        call_count = [0]

        def fake_encode(texts):
            results = []
            for t in texts:
                if t not in text_vecs:
                    # First unique text → vec_a, second → vec_b
                    text_vecs[t] = vec_a if call_count[0] == 0 else vec_b
                    call_count[0] += 1
                results.append(text_vecs[t])
            return np.array(results)

        mock_encoder = MagicMock()
        mock_encoder.encode = fake_encode
        mapper._encoder = mock_encoder
        return mapper

    def test_exact_match_no_embedding(self):
        """Match exact → score 1.0, pas de bonus embedding."""
        mapper = DimensionMapperV2()
        registry = [_make_dim("data_retention_period")]
        dim_id, score, trace = mapper.map_to_dimension(
            "data_retention_period", "What is the retention?",
            "number", "=", registry, use_embeddings=False,
        )
        assert dim_id is not None
        assert score == 1.0
        assert trace.match_strategy == "exact"

    def test_embedding_bonus_high_similarity(self):
        """Cosine ≥ 0.85 → score final ≥ 0.75 → merge via embedding."""
        mapper = self._make_mapper_with_mock_embeddings(0.90)
        # "max_tls_version" vs "maximum_tls_version" : prefix ratio ~15% → det = 0
        # Mais cosine 0.90 ≥ 0.85 → final = max(0.3, 0.75) = 0.75 → merge
        registry = [_make_dim("maximum_tls_version", "version")]
        dim_id, score, trace = mapper.map_to_dimension(
            "max_tls_version", "What is the max TLS version?",
            "version", "=", registry,
        )
        assert dim_id is not None
        assert trace.match_strategy == "embedding_bonus"
        assert trace.score_embedding is not None
        assert score >= 0.7

    def test_embedding_no_bonus_low_similarity(self):
        """Cosine < 0.60 → pas de bonus → pas de merge."""
        mapper = self._make_mapper_with_mock_embeddings(0.40)
        registry = [_make_dim("backup_frequency", "enum")]
        dim_id, score, trace = mapper.map_to_dimension(
            "authorization_required", "Is authorization required?",
            "enum", "=", registry,
        )
        assert dim_id is None
        assert trace.match_strategy == "new_dimension"

    def test_semantic_inversion_blocks_embedding(self):
        """min/max inversion bloque AVANT l'embedding."""
        mapper = self._make_mapper_with_mock_embeddings(0.95)
        registry = [_make_dim("min_tls_version", "version", [">="])]
        dim_id, score, trace = mapper.map_to_dimension(
            "max_tls_version", "What is the max TLS version?",
            "version", "=", registry,
        )
        assert dim_id is None

    def test_merged_dimension_skipped_v2(self):
        """V2 ignore aussi les dimensions merged."""
        mapper = DimensionMapperV2()
        registry = [_make_dim("data_retention_period", status="merged")]
        dim_id, score, trace = mapper.map_to_dimension(
            "data_retention_period", "What is the retention?",
            "number", "=", registry, use_embeddings=False,
        )
        assert dim_id is None
        assert trace.match_strategy == "new_dimension"

    def test_embedding_disabled(self):
        """use_embeddings=False → pas de bonus embedding."""
        mapper = DimensionMapperV2()
        registry = [_make_dim("maximum_tls_version", "version")]
        dim_id, score, trace = mapper.map_to_dimension(
            "max_tls_version", "What is the max TLS version?",
            "version", "=", registry, use_embeddings=False,
        )
        # Pas de prefix match → score 0 → no merge
        assert dim_id is None
        assert trace.score_embedding is None

    def test_embedding_bonus_proportional(self):
        """Cosine entre 0.60 et 0.85 → bonus proportionnel."""
        mapper = self._make_mapper_with_mock_embeddings(0.72)
        registry = [_make_dim("connection_timeout", "number")]
        dim_id, score, trace = mapper.map_to_dimension(
            "request_timeout", "What is the request timeout?",
            "number", "=", registry,
        )
        # Le bonus sera proportionnel : 0.3 * (0.72-0.60)/(0.85-0.60) ≈ 0.144
        # score_final = 0 + 0.144 = 0.144 < 0.7 → no merge
        assert trace.score_embedding is not None


# ── Tests helper functions ────────────────────────────────────────────

class TestCosineHelper:

    def test_identical_vectors(self):
        v = np.array([1.0, 2.0, 3.0])
        assert _cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        v1 = np.array([1.0, 0.0])
        v2 = np.array([0.0, 1.0])
        assert _cosine_similarity(v1, v2) == pytest.approx(0.0)

    def test_zero_vector(self):
        v1 = np.array([0.0, 0.0])
        v2 = np.array([1.0, 2.0])
        assert _cosine_similarity(v1, v2) == 0.0


class TestEmbeddingBonus:

    def test_high_similarity(self):
        assert _compute_embedding_bonus(0.90) == 0.3

    def test_low_similarity(self):
        assert _compute_embedding_bonus(0.50) == 0.0

    def test_boundary_085(self):
        assert _compute_embedding_bonus(0.85) == pytest.approx(0.3)

    def test_boundary_060(self):
        assert _compute_embedding_bonus(0.60) == pytest.approx(0.0)

    def test_middle_value(self):
        bonus = _compute_embedding_bonus(0.725)
        expected = 0.3 * (0.725 - 0.60) / (0.85 - 0.60)
        assert bonus == pytest.approx(expected)
