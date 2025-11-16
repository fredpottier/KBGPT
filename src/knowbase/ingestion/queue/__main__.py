"""Entry point for running the ingestion worker as a module."""

from __future__ import annotations

# CRITICAL: Force 'spawn' method BEFORE any torch/CUDA imports
# This must be the first thing executed to avoid CUDA fork errors
import multiprocessing
try:
    multiprocessing.set_start_method('spawn', force=True)
except RuntimeError:
    pass  # Already set

from .worker import main

if __name__ == "__main__":
    main()