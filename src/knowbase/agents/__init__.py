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
"""

__version__ = "1.1.0"
