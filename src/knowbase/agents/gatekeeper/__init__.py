"""
🤖 OSMOSE Agentique - Gatekeeper Delegate

Agent spécialisé pour quality control et promotion.

Responsabilités:
- Quality gate check: Score concepts selon Gate Profiles
- Promotion Proto→Published: Concepts ≥ seuil
- Retry logic: Signale si retry avec BIG model nécessaire
- Hard rejection: Fragments, stopwords, PII

Phase 1.5 V1.1
"""

from .gatekeeper import GatekeeperDelegate

__all__ = ["GatekeeperDelegate"]
