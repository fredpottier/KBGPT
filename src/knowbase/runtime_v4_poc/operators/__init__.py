"""POC Operators — déterministes par construction.

Couvert :
- temporal_active_version : version active d'un document à une date donnée
"""
from knowbase.runtime_v4_poc.operators.temporal_active_version import (
    TemporalActiveVersionOperator,
    TemporalActiveResult,
)

__all__ = ["TemporalActiveVersionOperator", "TemporalActiveResult"]
