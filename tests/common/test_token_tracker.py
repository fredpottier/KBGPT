"""
Tests for Token Tracker Module - src/knowbase/common/token_tracker.py

Tests cover:
- TokenUsage dataclass
- ModelPricing dataclass
- TokenTracker class methods
- Cost calculation accuracy
- Statistics aggregation
- Provider comparison
- File logging
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from knowbase.common.token_tracker import (
    TokenUsage,
    ModelPricing,
    TokenTracker,
    get_token_tracker,
    track_tokens,
)


# ============================================
# Fixtures
# ============================================

@pytest.fixture
def token_tracker() -> TokenTracker:
    """Create a fresh token tracker without file logging."""
    return TokenTracker(log_file=None)


@pytest.fixture
def token_tracker_with_file(tmp_path: Path) -> TokenTracker:
    """Create a token tracker with file logging."""
    log_file = tmp_path / "token_usage.jsonl"
    return TokenTracker(log_file=log_file)


@pytest.fixture
def sample_token_usage() -> TokenUsage:
    """Create a sample TokenUsage instance."""
    return TokenUsage(
        model="gpt-4o",
        task_type="extraction",
        input_tokens=1000,
        output_tokens=500,
        timestamp=datetime.now(),
        context="slide_1"
    )


# ============================================
# Test TokenUsage Dataclass
# ============================================

class TestTokenUsage:
    """Tests for TokenUsage dataclass."""

    def test_create_token_usage(self) -> None:
        """Create TokenUsage with all fields."""
        ts = datetime.now()
        usage = TokenUsage(
            model="gpt-4o",
            task_type="summarization",
            input_tokens=2000,
            output_tokens=1000,
            timestamp=ts,
            context="deck_summary"
        )

        assert usage.model == "gpt-4o"
        assert usage.task_type == "summarization"
        assert usage.input_tokens == 2000
        assert usage.output_tokens == 1000
        assert usage.timestamp == ts
        assert usage.context == "deck_summary"

    def test_total_tokens_property(self) -> None:
        """total_tokens should sum input and output."""
        usage = TokenUsage(
            model="gpt-4o",
            task_type="test",
            input_tokens=1500,
            output_tokens=500,
            timestamp=datetime.now()
        )

        assert usage.total_tokens == 2000

    def test_default_context(self) -> None:
        """context should default to empty string."""
        usage = TokenUsage(
            model="gpt-4o",
            task_type="test",
            input_tokens=100,
            output_tokens=50,
            timestamp=datetime.now()
        )

        assert usage.context == ""

    def test_total_tokens_with_zero_values(self) -> None:
        """total_tokens should work with zero values."""
        usage = TokenUsage(
            model="gpt-4o",
            task_type="test",
            input_tokens=0,
            output_tokens=0,
            timestamp=datetime.now()
        )

        assert usage.total_tokens == 0


# ============================================
# Test ModelPricing Dataclass
# ============================================

class TestModelPricing:
    """Tests for ModelPricing dataclass."""

    def test_create_model_pricing(self) -> None:
        """Create ModelPricing with all fields."""
        pricing = ModelPricing(
            name="test-model",
            input_price_per_1k=0.01,
            output_price_per_1k=0.02,
            provider="test-provider"
        )

        assert pricing.name == "test-model"
        assert pricing.input_price_per_1k == 0.01
        assert pricing.output_price_per_1k == 0.02
        assert pricing.provider == "test-provider"


# ============================================
# Test TokenTracker Initialization
# ============================================

class TestTokenTrackerInit:
    """Tests for TokenTracker initialization."""

    def test_init_without_log_file(self) -> None:
        """Initialize without file logging."""
        tracker = TokenTracker()
        assert tracker.usage_history == []
        assert tracker.log_file is None

    def test_init_with_log_file(self, tmp_path: Path) -> None:
        """Initialize with file logging."""
        log_file = tmp_path / "tokens.jsonl"
        tracker = TokenTracker(log_file=log_file)
        assert tracker.log_file == log_file

    def test_model_pricing_dict_populated(self) -> None:
        """MODEL_PRICING should have pre-defined models."""
        assert "gpt-4o" in TokenTracker.MODEL_PRICING
        assert "gpt-4o-mini" in TokenTracker.MODEL_PRICING
        assert "claude-3.5-sonnet" in TokenTracker.MODEL_PRICING
        assert "claude-3-haiku" in TokenTracker.MODEL_PRICING


# ============================================
# Test add_usage Method
# ============================================

class TestAddUsage:
    """Tests for add_usage method."""

    def test_add_usage_stores_in_history(self, token_tracker: TokenTracker) -> None:
        """add_usage should append to usage_history."""
        assert len(token_tracker.usage_history) == 0

        token_tracker.add_usage(
            model="gpt-4o",
            task_type="extraction",
            input_tokens=1000,
            output_tokens=500,
            context="test"
        )

        assert len(token_tracker.usage_history) == 1

    def test_add_usage_creates_correct_token_usage(
        self, token_tracker: TokenTracker
    ) -> None:
        """add_usage should create correct TokenUsage object."""
        token_tracker.add_usage(
            model="claude-3.5-sonnet",
            task_type="summarization",
            input_tokens=2000,
            output_tokens=1000,
            context="deck"
        )

        usage = token_tracker.usage_history[0]
        assert usage.model == "claude-3.5-sonnet"
        assert usage.task_type == "summarization"
        assert usage.input_tokens == 2000
        assert usage.output_tokens == 1000
        assert usage.context == "deck"
        assert isinstance(usage.timestamp, datetime)

    def test_add_usage_writes_to_file(
        self, token_tracker_with_file: TokenTracker
    ) -> None:
        """add_usage should write to log file if configured."""
        token_tracker_with_file.add_usage(
            model="gpt-4o",
            task_type="test",
            input_tokens=100,
            output_tokens=50
        )

        # Check file was written
        assert token_tracker_with_file.log_file.exists()

        # Parse file content
        with open(token_tracker_with_file.log_file) as f:
            line = f.readline()
            data = json.loads(line)

        assert data["model"] == "gpt-4o"
        assert data["input_tokens"] == 100
        assert data["output_tokens"] == 50


# ============================================
# Test calculate_cost Method
# ============================================

class TestCalculateCost:
    """Tests for calculate_cost method."""

    def test_calculate_cost_gpt4o(self, token_tracker: TokenTracker) -> None:
        """Calculate cost for gpt-4o model."""
        usage = TokenUsage(
            model="gpt-4o",
            task_type="test",
            input_tokens=1000,  # 1K tokens
            output_tokens=1000,  # 1K tokens
            timestamp=datetime.now()
        )

        cost = token_tracker.calculate_cost(usage)

        # gpt-4o: $0.005/1K input, $0.015/1K output
        expected = 0.005 + 0.015
        assert cost == pytest.approx(expected, rel=1e-6)

    def test_calculate_cost_claude_haiku(self, token_tracker: TokenTracker) -> None:
        """Calculate cost for claude-3-haiku model."""
        usage = TokenUsage(
            model="claude-3-haiku",
            task_type="test",
            input_tokens=10000,  # 10K tokens
            output_tokens=5000,  # 5K tokens
            timestamp=datetime.now()
        )

        cost = token_tracker.calculate_cost(usage)

        # claude-3-haiku: $0.00025/1K input, $0.00125/1K output
        expected = (10 * 0.00025) + (5 * 0.00125)
        assert cost == pytest.approx(expected, rel=1e-6)

    def test_calculate_cost_unknown_model_returns_zero(
        self, token_tracker: TokenTracker
    ) -> None:
        """Unknown model should return 0 cost."""
        usage = TokenUsage(
            model="unknown-model",
            task_type="test",
            input_tokens=1000,
            output_tokens=500,
            timestamp=datetime.now()
        )

        cost = token_tracker.calculate_cost(usage)
        assert cost == 0.0

    def test_calculate_cost_with_zero_tokens(
        self, token_tracker: TokenTracker
    ) -> None:
        """Zero tokens should result in zero cost."""
        usage = TokenUsage(
            model="gpt-4o",
            task_type="test",
            input_tokens=0,
            output_tokens=0,
            timestamp=datetime.now()
        )

        cost = token_tracker.calculate_cost(usage)
        assert cost == 0.0


# ============================================
# Test get_total_cost Method
# ============================================

class TestGetTotalCost:
    """Tests for get_total_cost method."""

    def test_get_total_cost_empty_history(self, token_tracker: TokenTracker) -> None:
        """Empty history should return 0."""
        assert token_tracker.get_total_cost() == 0.0

    def test_get_total_cost_sums_all(self, token_tracker: TokenTracker) -> None:
        """Should sum all costs without filter."""
        token_tracker.add_usage("gpt-4o", "task1", 1000, 1000)
        token_tracker.add_usage("gpt-4o", "task2", 1000, 1000)

        total = token_tracker.get_total_cost()

        # Each: $0.005 + $0.015 = $0.02
        assert total == pytest.approx(0.04, rel=1e-6)

    def test_get_total_cost_filter_by_task_type(
        self, token_tracker: TokenTracker
    ) -> None:
        """Should filter by task_type."""
        token_tracker.add_usage("gpt-4o", "extraction", 1000, 1000)
        token_tracker.add_usage("gpt-4o", "summarization", 1000, 1000)
        token_tracker.add_usage("gpt-4o", "extraction", 1000, 1000)

        extraction_total = token_tracker.get_total_cost(task_type="extraction")

        # 2 extraction tasks
        assert extraction_total == pytest.approx(0.04, rel=1e-6)

    def test_get_total_cost_filter_by_context(
        self, token_tracker: TokenTracker
    ) -> None:
        """Should filter by context substring."""
        token_tracker.add_usage("gpt-4o", "task", 1000, 1000, context="slide_1")
        token_tracker.add_usage("gpt-4o", "task", 1000, 1000, context="slide_2")
        token_tracker.add_usage("gpt-4o", "task", 1000, 1000, context="deck_summary")

        slide_total = token_tracker.get_total_cost(context_filter="slide")

        # 2 slide contexts
        assert slide_total == pytest.approx(0.04, rel=1e-6)


# ============================================
# Test get_stats_by_model Method
# ============================================

class TestGetStatsByModel:
    """Tests for get_stats_by_model method."""

    def test_empty_history_returns_empty_dict(
        self, token_tracker: TokenTracker
    ) -> None:
        """Empty history should return empty dict."""
        stats = token_tracker.get_stats_by_model()
        assert stats == {}

    def test_stats_grouped_by_model(self, token_tracker: TokenTracker) -> None:
        """Stats should be grouped by model."""
        token_tracker.add_usage("gpt-4o", "task1", 1000, 500)
        token_tracker.add_usage("gpt-4o", "task2", 2000, 1000)
        token_tracker.add_usage("claude-3.5-sonnet", "task1", 500, 250)

        stats = token_tracker.get_stats_by_model()

        assert "gpt-4o" in stats
        assert "claude-3.5-sonnet" in stats

        # gpt-4o stats
        assert stats["gpt-4o"]["total_calls"] == 2
        assert stats["gpt-4o"]["total_input_tokens"] == 3000
        assert stats["gpt-4o"]["total_output_tokens"] == 1500

        # claude stats
        assert stats["claude-3.5-sonnet"]["total_calls"] == 1
        assert stats["claude-3.5-sonnet"]["total_input_tokens"] == 500
        assert stats["claude-3.5-sonnet"]["total_output_tokens"] == 250


# ============================================
# Test estimate_deck_cost Method
# ============================================

class TestEstimateDeckCost:
    """Tests for estimate_deck_cost method."""

    def test_estimate_deck_cost_basic(self, token_tracker: TokenTracker) -> None:
        """Basic deck cost estimation."""
        estimate = token_tracker.estimate_deck_cost(
            num_slides=10,
            model="gpt-4o"
        )

        assert "model" in estimate
        assert "num_slides" in estimate
        assert "deck_summary_cost" in estimate
        assert "slides_analysis_cost" in estimate
        assert "total_cost" in estimate
        assert "cost_per_slide" in estimate
        assert "total_tokens" in estimate

        assert estimate["model"] == "gpt-4o"
        assert estimate["num_slides"] == 10
        assert estimate["total_cost"] > 0

    def test_estimate_deck_cost_unknown_model(
        self, token_tracker: TokenTracker
    ) -> None:
        """Unknown model should return error."""
        estimate = token_tracker.estimate_deck_cost(
            num_slides=10,
            model="unknown-model"
        )

        assert "error" in estimate

    def test_estimate_deck_cost_custom_tokens(
        self, token_tracker: TokenTracker
    ) -> None:
        """Custom token counts should be respected."""
        estimate = token_tracker.estimate_deck_cost(
            num_slides=5,
            avg_input_tokens=1000,
            avg_output_tokens=500,
            model="gpt-4o"
        )

        # 5 slides * 1000 input + 5 slides * 500 output = 7500 tokens
        # Plus deck summary tokens
        assert estimate["total_tokens"] > 7500


# ============================================
# Test compare_providers Method
# ============================================

class TestCompareProviders:
    """Tests for compare_providers method."""

    def test_compare_providers_includes_base_model(
        self, token_tracker: TokenTracker, sample_token_usage: TokenUsage
    ) -> None:
        """Should include base model in comparison."""
        comparisons = token_tracker.compare_providers(sample_token_usage)
        assert sample_token_usage.model in comparisons

    def test_compare_providers_includes_equivalents(
        self, token_tracker: TokenTracker
    ) -> None:
        """Should include equivalent models."""
        usage = TokenUsage(
            model="gpt-4o",
            task_type="test",
            input_tokens=1000,
            output_tokens=500,
            timestamp=datetime.now()
        )

        comparisons = token_tracker.compare_providers(usage)

        # gpt-4o equivalents should be included
        assert "gpt-4o" in comparisons
        assert "claude-3.5-sonnet" in comparisons

    def test_compare_providers_returns_costs(
        self, token_tracker: TokenTracker
    ) -> None:
        """All comparison values should be costs (floats)."""
        usage = TokenUsage(
            model="claude-3-haiku",
            task_type="test",
            input_tokens=1000,
            output_tokens=500,
            timestamp=datetime.now()
        )

        comparisons = token_tracker.compare_providers(usage)

        for model, cost in comparisons.items():
            assert isinstance(cost, float)
            assert cost >= 0


# ============================================
# Test File Logging
# ============================================

class TestFileLogging:
    """Tests for file logging functionality."""

    def test_file_logging_creates_file(
        self, token_tracker_with_file: TokenTracker
    ) -> None:
        """Adding usage should create log file."""
        token_tracker_with_file.add_usage("gpt-4o", "test", 100, 50)
        assert token_tracker_with_file.log_file.exists()

    def test_file_logging_appends_jsonl(
        self, token_tracker_with_file: TokenTracker
    ) -> None:
        """Multiple usages should append to file."""
        token_tracker_with_file.add_usage("gpt-4o", "task1", 100, 50)
        token_tracker_with_file.add_usage("claude-3.5-sonnet", "task2", 200, 100)

        with open(token_tracker_with_file.log_file) as f:
            lines = f.readlines()

        assert len(lines) == 2

        # Verify both entries
        entry1 = json.loads(lines[0])
        entry2 = json.loads(lines[1])

        assert entry1["model"] == "gpt-4o"
        assert entry2["model"] == "claude-3.5-sonnet"

    def test_file_logging_includes_all_fields(
        self, token_tracker_with_file: TokenTracker
    ) -> None:
        """Log entry should include all required fields."""
        token_tracker_with_file.add_usage(
            model="gpt-4o",
            task_type="extraction",
            input_tokens=1000,
            output_tokens=500,
            context="slide_1"
        )

        with open(token_tracker_with_file.log_file) as f:
            entry = json.loads(f.readline())

        assert "timestamp" in entry
        assert "model" in entry
        assert "task_type" in entry
        assert "input_tokens" in entry
        assert "output_tokens" in entry
        assert "total_tokens" in entry
        assert "cost" in entry
        assert "context" in entry

    def test_file_logging_handles_write_error(
        self, token_tracker: TokenTracker
    ) -> None:
        """Write errors should be handled gracefully."""
        # Set invalid path
        token_tracker.log_file = Path("/invalid/path/tokens.jsonl")

        # Should not raise
        token_tracker.add_usage("gpt-4o", "test", 100, 50)

        # Usage should still be tracked in memory
        assert len(token_tracker.usage_history) == 1


# ============================================
# Test Utility Functions
# ============================================

class TestUtilityFunctions:
    """Tests for module-level utility functions."""

    def test_track_tokens_function(self) -> None:
        """track_tokens should use global tracker."""
        with patch("knowbase.common.token_tracker.get_token_tracker") as mock_get:
            mock_tracker = MagicMock()
            mock_get.return_value = mock_tracker

            track_tokens(
                model="gpt-4o",
                task_type="test",
                input_tokens=100,
                output_tokens=50,
                context="test_context"
            )

            mock_tracker.add_usage.assert_called_once_with(
                "gpt-4o", "test", 100, 50, "test_context"
            )


# ============================================
# Test Model Pricing Accuracy
# ============================================

class TestModelPricingAccuracy:
    """Tests to verify model pricing values are reasonable."""

    def test_openai_models_pricing(self) -> None:
        """OpenAI models should have expected pricing."""
        pricing = TokenTracker.MODEL_PRICING

        # gpt-4o
        assert pricing["gpt-4o"].provider == "openai"
        assert pricing["gpt-4o"].input_price_per_1k > 0
        assert pricing["gpt-4o"].output_price_per_1k > pricing["gpt-4o"].input_price_per_1k

        # gpt-4o-mini should be cheaper than gpt-4o
        assert pricing["gpt-4o-mini"].input_price_per_1k < pricing["gpt-4o"].input_price_per_1k

    def test_anthropic_models_pricing(self) -> None:
        """Anthropic models should have expected pricing."""
        pricing = TokenTracker.MODEL_PRICING

        # claude-3.5-sonnet
        assert pricing["claude-3.5-sonnet"].provider == "anthropic"

        # haiku should be cheaper than sonnet
        assert pricing["claude-3-haiku"].input_price_per_1k < pricing["claude-3.5-sonnet"].input_price_per_1k

        # opus should be more expensive
        assert pricing["claude-3-opus"].input_price_per_1k > pricing["claude-3.5-sonnet"].input_price_per_1k

    def test_sagemaker_models_pricing(self) -> None:
        """SageMaker models should have expected pricing."""
        pricing = TokenTracker.MODEL_PRICING

        # SageMaker models
        assert pricing["llama3.1:70b"].provider == "sagemaker"
        assert pricing["qwen2.5:32b"].provider == "sagemaker"

        # Smaller models should generally be cheaper
        assert pricing["qwen2.5:7b"].input_price_per_1k < pricing["qwen2.5:32b"].input_price_per_1k
