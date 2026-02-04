"""
🤖 OSMOSE Architecture Agentique V1.1

6 Agents Spécialisés pour maîtrise coûts LLM et scalabilité production.

Agents:
- Supervisor: FSM Master, timeout enforcement
- Extractor Orchestrator: Routing NO_LLM/SMALL/BIG
- Pattern Miner: Cross-segment reasoning
- Gatekeeper Delegate: Quality control, promotion Proto→Published
- Budget Manager: Caps durs, quotas tenant/jour
- LLM Dispatcher: Rate limits (500/100/50 RPM), concurrency, priority queue

Phase 1.5 (Sem 11-13) - Pilote Agentique

DEPRECATED: Cette architecture agentique Phase 1.5 n'a jamais été complétée.
Seul le module base.py contient du code utilisé par le pipeline stratified.
"""

from knowbase.common.deprecation import deprecated_module, DeprecationKind

deprecated_module(
    kind=DeprecationKind.PHASE_ABANDONED,
    reason="Architecture agentique Phase 1.5 non complétée, seul base.py est utilisé",
    alternative="knowbase.stratified pour le pipeline d'extraction",
    removal_version="2.0.0",
)

__version__ = "1.1.0"
