"""Entry point for running the ingestion worker as a module."""

from __future__ import annotations

from .worker import main

if __name__ == "__main__":
    main()