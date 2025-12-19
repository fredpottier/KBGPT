"""
Tests for Pagination Helper - src/knowbase/common/pagination.py

Tests cover:
- Basic pagination functionality
- Edge cases (empty list, single page, out of bounds)
- Boundary conditions
- Navigation metadata (has_next, has_prev)
- Page size limits
"""
from __future__ import annotations

from typing import List

import pytest

from knowbase.common.pagination import paginate


# ============================================
# Fixtures
# ============================================

@pytest.fixture
def sample_items() -> List[int]:
    """List of 100 items for testing."""
    return list(range(1, 101))  # 1 to 100


@pytest.fixture
def small_items() -> List[str]:
    """Small list for boundary testing."""
    return ["a", "b", "c", "d", "e"]


# ============================================
# Test Basic Pagination
# ============================================

class TestBasicPagination:
    """Tests for basic pagination functionality."""

    def test_first_page(self, sample_items: List[int]) -> None:
        """First page should return first page_size items."""
        result = paginate(sample_items, page=1, page_size=10)

        assert result["items"] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        assert result["page"] == 1
        assert result["page_size"] == 10

    def test_second_page(self, sample_items: List[int]) -> None:
        """Second page should return correct offset items."""
        result = paginate(sample_items, page=2, page_size=10)

        assert result["items"] == [11, 12, 13, 14, 15, 16, 17, 18, 19, 20]
        assert result["page"] == 2

    def test_last_page(self, sample_items: List[int]) -> None:
        """Last page should return remaining items."""
        result = paginate(sample_items, page=10, page_size=10)

        assert result["items"] == [91, 92, 93, 94, 95, 96, 97, 98, 99, 100]
        assert result["page"] == 10

    def test_total_count(self, sample_items: List[int]) -> None:
        """Total should reflect full list size."""
        result = paginate(sample_items, page=1, page_size=10)
        assert result["total"] == 100

    def test_total_pages(self, sample_items: List[int]) -> None:
        """Pages count should be calculated correctly."""
        result = paginate(sample_items, page=1, page_size=10)
        assert result["pages"] == 10

        result = paginate(sample_items, page=1, page_size=30)
        assert result["pages"] == 4  # ceil(100/30) = 4


# ============================================
# Test Return Structure
# ============================================

class TestReturnStructure:
    """Tests for pagination return structure."""

    def test_return_contains_all_keys(self, sample_items: List[int]) -> None:
        """Result should contain all expected keys."""
        result = paginate(sample_items, page=1, page_size=10)

        assert "items" in result
        assert "page" in result
        assert "page_size" in result
        assert "total" in result
        assert "pages" in result
        assert "has_next" in result
        assert "has_prev" in result

    def test_items_is_list(self, sample_items: List[int]) -> None:
        """Items should be a list."""
        result = paginate(sample_items, page=1, page_size=10)
        assert isinstance(result["items"], list)

    def test_metadata_types(self, sample_items: List[int]) -> None:
        """Metadata should have correct types."""
        result = paginate(sample_items, page=1, page_size=10)

        assert isinstance(result["page"], int)
        assert isinstance(result["page_size"], int)
        assert isinstance(result["total"], int)
        assert isinstance(result["pages"], int)
        assert isinstance(result["has_next"], bool)
        assert isinstance(result["has_prev"], bool)


# ============================================
# Test Navigation Metadata
# ============================================

class TestNavigationMetadata:
    """Tests for has_next and has_prev flags."""

    def test_first_page_has_next_no_prev(self, sample_items: List[int]) -> None:
        """First page should have next but no prev."""
        result = paginate(sample_items, page=1, page_size=10)

        assert result["has_next"] is True
        assert result["has_prev"] is False

    def test_middle_page_has_both(self, sample_items: List[int]) -> None:
        """Middle page should have both next and prev."""
        result = paginate(sample_items, page=5, page_size=10)

        assert result["has_next"] is True
        assert result["has_prev"] is True

    def test_last_page_has_prev_no_next(self, sample_items: List[int]) -> None:
        """Last page should have prev but no next."""
        result = paginate(sample_items, page=10, page_size=10)

        assert result["has_next"] is False
        assert result["has_prev"] is True

    def test_single_page_has_neither(self, small_items: List[str]) -> None:
        """Single page list should have neither next nor prev."""
        result = paginate(small_items, page=1, page_size=10)

        assert result["has_next"] is False
        assert result["has_prev"] is False


# ============================================
# Test Empty List
# ============================================

class TestEmptyList:
    """Tests for empty list input."""

    def test_empty_list_returns_empty_items(self) -> None:
        """Empty list should return empty items."""
        result = paginate([], page=1, page_size=10)
        assert result["items"] == []

    def test_empty_list_total_is_zero(self) -> None:
        """Empty list should have total of 0."""
        result = paginate([], page=1, page_size=10)
        assert result["total"] == 0

    def test_empty_list_pages_is_zero(self) -> None:
        """Empty list should have 0 pages."""
        result = paginate([], page=1, page_size=10)
        assert result["pages"] == 0

    def test_empty_list_no_navigation(self) -> None:
        """Empty list should have no navigation."""
        result = paginate([], page=1, page_size=10)
        assert result["has_next"] is False
        assert result["has_prev"] is False


# ============================================
# Test Edge Cases
# ============================================

class TestEdgeCases:
    """Tests for edge cases."""

    def test_page_zero_treated_as_one(self, sample_items: List[int]) -> None:
        """Page 0 should be treated as page 1."""
        result = paginate(sample_items, page=0, page_size=10)
        assert result["page"] == 1
        assert result["items"] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

    def test_negative_page_treated_as_one(self, sample_items: List[int]) -> None:
        """Negative page should be treated as page 1."""
        result = paginate(sample_items, page=-5, page_size=10)
        assert result["page"] == 1

    def test_page_beyond_last_returns_empty(self, sample_items: List[int]) -> None:
        """Page beyond last should return empty items."""
        result = paginate(sample_items, page=20, page_size=10)
        assert result["items"] == []

    def test_partial_last_page(self) -> None:
        """Last page with fewer items than page_size."""
        items = list(range(1, 26))  # 25 items
        result = paginate(items, page=3, page_size=10)

        assert result["items"] == [21, 22, 23, 24, 25]
        assert len(result["items"]) == 5

    def test_exact_page_boundary(self) -> None:
        """List size exactly divisible by page_size."""
        items = list(range(1, 31))  # 30 items
        result = paginate(items, page=3, page_size=10)

        assert result["items"] == [21, 22, 23, 24, 25, 26, 27, 28, 29, 30]
        assert result["pages"] == 3


# ============================================
# Test Page Size Limits
# ============================================

class TestPageSizeLimits:
    """Tests for page size limiting."""

    def test_page_size_limited_to_max(self, sample_items: List[int]) -> None:
        """Page size should be capped at max_page_size."""
        result = paginate(sample_items, page=1, page_size=200, max_page_size=100)

        assert result["page_size"] == 100
        assert len(result["items"]) == 100

    def test_default_max_page_size(self, sample_items: List[int]) -> None:
        """Default max_page_size should be 100."""
        result = paginate(sample_items, page=1, page_size=150)

        assert result["page_size"] == 100

    def test_page_size_below_max_unchanged(self, sample_items: List[int]) -> None:
        """Page size below max should be unchanged."""
        result = paginate(sample_items, page=1, page_size=25, max_page_size=100)

        assert result["page_size"] == 25

    def test_custom_max_page_size(self, sample_items: List[int]) -> None:
        """Custom max_page_size should be respected."""
        result = paginate(sample_items, page=1, page_size=50, max_page_size=30)

        assert result["page_size"] == 30
        assert len(result["items"]) == 30


# ============================================
# Test Default Values
# ============================================

class TestDefaultValues:
    """Tests for default parameter values."""

    def test_default_page_is_one(self, sample_items: List[int]) -> None:
        """Default page should be 1."""
        result = paginate(sample_items, page_size=10)
        assert result["page"] == 1

    def test_default_page_size_is_50(self, sample_items: List[int]) -> None:
        """Default page_size should be 50."""
        result = paginate(sample_items, page=1)
        assert result["page_size"] == 50


# ============================================
# Test Different Data Types
# ============================================

class TestDifferentDataTypes:
    """Tests for pagination with different data types."""

    def test_paginate_strings(self) -> None:
        """Should work with string items."""
        items = ["apple", "banana", "cherry", "date", "elderberry"]
        result = paginate(items, page=1, page_size=2)

        assert result["items"] == ["apple", "banana"]
        assert result["total"] == 5

    def test_paginate_dicts(self) -> None:
        """Should work with dict items."""
        items = [
            {"id": 1, "name": "Alice"},
            {"id": 2, "name": "Bob"},
            {"id": 3, "name": "Charlie"},
        ]
        result = paginate(items, page=1, page_size=2)

        assert len(result["items"]) == 2
        assert result["items"][0]["name"] == "Alice"

    def test_paginate_mixed_types(self) -> None:
        """Should work with mixed type items."""
        items = [1, "two", 3.0, {"four": 4}, [5]]
        result = paginate(items, page=1, page_size=3)

        assert result["items"] == [1, "two", 3.0]

    def test_paginate_nested_structures(self) -> None:
        """Should work with nested data structures."""
        items = [
            {"users": [{"name": "Alice"}]},
            {"users": [{"name": "Bob"}, {"name": "Carol"}]},
        ]
        result = paginate(items, page=1, page_size=10)

        assert len(result["items"]) == 2


# ============================================
# Test Page Calculation
# ============================================

class TestPageCalculation:
    """Tests for correct page count calculation."""

    def test_pages_rounded_up(self) -> None:
        """Page count should be ceiling of total/page_size."""
        # 7 items, 3 per page = 3 pages (ceil(7/3) = 3)
        items = list(range(7))
        result = paginate(items, page=1, page_size=3)
        assert result["pages"] == 3

    def test_single_item_single_page(self) -> None:
        """Single item should result in single page."""
        result = paginate([1], page=1, page_size=10)
        assert result["pages"] == 1

    def test_page_size_equals_total(self) -> None:
        """When page_size equals total, should have 1 page."""
        items = list(range(50))
        result = paginate(items, page=1, page_size=50)
        assert result["pages"] == 1


# ============================================
# Test Performance Edge Cases
# ============================================

class TestPerformanceEdgeCases:
    """Tests for performance-related edge cases."""

    def test_large_page_number(self) -> None:
        """Very large page number should work."""
        items = list(range(10))
        result = paginate(items, page=1000000, page_size=10)

        assert result["items"] == []
        assert result["page"] == 1000000

    def test_page_size_one(self) -> None:
        """Page size of 1 should work correctly."""
        items = list(range(5))
        result = paginate(items, page=3, page_size=1)

        assert result["items"] == [2]
        assert result["pages"] == 5
        assert result["has_next"] is True
        assert result["has_prev"] is True

    def test_page_size_larger_than_total(self) -> None:
        """Page size larger than total items."""
        items = list(range(5))
        result = paginate(items, page=1, page_size=100)

        assert result["items"] == [0, 1, 2, 3, 4]
        assert result["pages"] == 1
        assert result["has_next"] is False
