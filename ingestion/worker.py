"""Compatibility entry-point for the ingestion worker."""

from __future__ import annotations

from knowbase.ingestion.queue.worker import main

__all__ = ["main"]

if __name__ == "__main__":
    main()
