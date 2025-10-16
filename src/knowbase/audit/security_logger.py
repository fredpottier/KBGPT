"""
Security Audit Logger - Phase 0.5 P1.9

Logs sécurité pour compliance (qui fait quoi, quand):
- Actions sensibles (merge, undo, bootstrap, delete)
- Tentatives accès non autorisé
- Rate limit exceeded
- Lock timeouts

Usage:
    from knowbase.audit.security_logger import log_security_event

    log_security_event(
        event_type="merge",
        user_id="user123",
        action="canonicalization.merge",
        resource_id="canon_entity_001",
        metadata={"candidates": ["cand1", "cand2"]}
    )
"""

import logging
import json
from datetime import datetime
from typing import Optional, Dict, Any

logger = logging.getLogger("security_audit")


def log_security_event(
    event_type: str,
    action: str,
    user_id: Optional[str] = None,
    resource_id: Optional[str] = None,
    status: str = "success",
    metadata: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None
):
    """
    Logger événement sécurité

    Args:
        event_type: Type (merge, undo, bootstrap, access_denied, etc.)
        action: Action détaillée (ex: "canonicalization.merge")
        user_id: Utilisateur effectuant action
        resource_id: ID ressource impactée
        status: success, failed, denied
        metadata: Données additionnelles
        ip_address: IP client
    """
    event = {
        "timestamp": datetime.utcnow().isoformat(),
        "event_type": event_type,
        "action": action,
        "user_id": user_id or "anonymous",
        "resource_id": resource_id,
        "status": status,
        "ip_address": ip_address,
        "metadata": metadata or {}
    }

    # Log JSON structuré pour parsing facile
    logger.info(json.dumps(event))
