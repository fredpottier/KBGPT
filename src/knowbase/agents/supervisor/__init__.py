"""
🤖 OSMOSE Agentique - Supervisor Agent

Orchestrateur principal (FSM Master) de l'architecture agentique.

Responsabilités:
- FSM Master: Gère transitions état par état
- Timeout enforcement: 300s/doc
- Error handling: Rollback, retry, failover
- Agent coordination: Appels séquentiels aux specialists
- Metrics tracking: KPIs temps-réel

Phase 1.5 V1.1
"""

from .supervisor import SupervisorAgent

__all__ = ["SupervisorAgent"]
