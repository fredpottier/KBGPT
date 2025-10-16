"""
Helper functions pour simplifier l'audit logging dans les routers.

Phase 0 - Security Hardening - Audit Trail
"""
from typing import Optional
from knowbase.api.services.audit_service import get_audit_service
from knowbase.db import SessionLocal


def log_audit(
    action: str,
    user: dict,
    resource_type: str,
    resource_id: Optional[str],
    tenant_id: str,
    details: Optional[str] = None
) -> None:
    """
    Helper pour logger une action d'audit de manière simple.

    Args:
        action: Type d'action (CREATE, UPDATE, DELETE, APPROVE, REJECT, etc.)
        user: Dict current_user depuis JWT (contient sub, email, etc.)
        resource_type: Type de ressource (entity, fact, entity_type, etc.)
        resource_id: ID de la ressource
        tenant_id: Tenant ID
        details: Détails optionnels

    Example:
        ```python
        log_audit(
            action="DELETE",
            user=current_user,
            resource_type="entity",
            resource_id=uuid,
            tenant_id=tenant_id,
            details="Entity deleted with cascade"
        )
        ```
    """
    try:
        db = SessionLocal()
        audit_service = get_audit_service(db)

        audit_service.log_action(
            user_id=user.get("sub"),
            user_email=user.get("email"),
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            tenant_id=tenant_id,
            details=details
        )

        db.close()
    except Exception as e:
        # Log failure silencieusement (ne pas bloquer l'opération)
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"⚠️ Audit log failed: {e}")
