"""
Pagination Helper - Phase 0.5 P1.8

Usage:
    from knowbase.common.pagination import paginate

    items = [1, 2, 3, ..., 100]
    result = paginate(items, page=2, page_size=20)
    # result = {"items": [...], "page": 2, "page_size": 20, "total": 100, "pages": 5}
"""

from typing import List, Any, Dict
from math import ceil


def paginate(
    items: List[Any],
    page: int = 1,
    page_size: int = 50,
    max_page_size: int = 100
) -> Dict[str, Any]:
    """
    Paginer liste

    Args:
        items: Liste complète
        page: Numéro page (1-indexed)
        page_size: Taille page (défaut 50)
        max_page_size: Taille max (défaut 100)

    Returns:
        Dict avec items paginés + metadata
    """
    # Limiter page_size au max
    page_size = min(page_size, max_page_size)
    page = max(1, page)  # Au moins page 1

    total = len(items)
    total_pages = ceil(total / page_size) if page_size > 0 else 0

    # Calculer offsets
    start = (page - 1) * page_size
    end = start + page_size

    return {
        "items": items[start:end],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1
    }
