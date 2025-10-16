"""
🤖 OSMOSE Agentique - LLM Dispatcher

Agent spécialisé pour orchestration appels LLM.

Responsabilités:
- Rate limiting: 500/100/50 RPM (SMALL/BIG/VISION)
- Priority queue: P0 (retry) > P1 (first pass) > P2 (batch)
- Concurrency control: 10 calls simultanées max
- Circuit breaker: Suspend si taux erreur > 30%

Phase 1.5 V1.1
"""

from .dispatcher import LLMDispatcher

__all__ = ["LLMDispatcher"]
