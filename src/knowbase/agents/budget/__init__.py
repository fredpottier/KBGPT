"""
🤖 OSMOSE Agentique - Budget Manager

Agent spécialisé pour gestion budgets LLM.

Responsabilités:
- Budget caps durs par document (SMALL: 120, BIG: 8, VISION: 2)
- Quotas tenant/jour (SMALL: 10k/j, BIG: 500/j, VISION: 100/j)
- Consommation tracking temps-réel
- Refund logic si retry échoue

Phase 1.5 V1.1
"""

from .budget import BudgetManager

__all__ = ["BudgetManager"]
