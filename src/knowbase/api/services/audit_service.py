"""
AuditService - Phase 0 Security Hardening - Semaine 4.

Service pour logger les actions critiques dans la table audit_log.
"""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session

from knowbase.db.models import AuditLog


class AuditService:
    """Service d'audit pour tracer les actions critiques."""

    def __init__(self, db: Session):
        self.db = db

    def log_action(
        self,
        user_id: str,
        user_email: str,
        action: str,
        resource_type: str,
        resource_id: Optional[str],
        tenant_id: str,
        details: Optional[str] = None
    ) -> AuditLog:
        """
        Log une action dans l'audit trail.

        Args:
            user_id: ID de l'utilisateur
            user_email: Email de l'utilisateur
            action: Type d'action (CREATE, UPDATE, DELETE, APPROVE, REJECT, etc.)
            resource_type: Type de ressource (entity, fact, entity_type, etc.)
            resource_id: ID de la ressource (peut être None pour actions globales)
            tenant_id: ID du tenant
            details: Détails optionnels en JSON ou texte

        Returns:
            AuditLog: L'entrée d'audit créée
        """
        audit_entry = AuditLog(
            user_id=user_id,
            user_email=user_email,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            tenant_id=tenant_id,
            details=details,
            timestamp=datetime.now(timezone.utc)
        )

        self.db.add(audit_entry)
        self.db.commit()
        self.db.refresh(audit_entry)

        return audit_entry

    def log_create(self, user_id: str, user_email: str, resource_type: str,
                   resource_id: str, tenant_id: str, details: Optional[str] = None) -> AuditLog:
        """Log une création de ressource."""
        return self.log_action(
            user_id=user_id,
            user_email=user_email,
            action="CREATE",
            resource_type=resource_type,
            resource_id=resource_id,
            tenant_id=tenant_id,
            details=details
        )

    def log_update(self, user_id: str, user_email: str, resource_type: str,
                   resource_id: str, tenant_id: str, details: Optional[str] = None) -> AuditLog:
        """Log une modification de ressource."""
        return self.log_action(
            user_id=user_id,
            user_email=user_email,
            action="UPDATE",
            resource_type=resource_type,
            resource_id=resource_id,
            tenant_id=tenant_id,
            details=details
        )

    def log_delete(self, user_id: str, user_email: str, resource_type: str,
                   resource_id: str, tenant_id: str, details: Optional[str] = None) -> AuditLog:
        """Log une suppression de ressource."""
        return self.log_action(
            user_id=user_id,
            user_email=user_email,
            action="DELETE",
            resource_type=resource_type,
            resource_id=resource_id,
            tenant_id=tenant_id,
            details=details
        )

    def log_approve(self, user_id: str, user_email: str, resource_type: str,
                    resource_id: str, tenant_id: str, details: Optional[str] = None) -> AuditLog:
        """Log une approbation."""
        return self.log_action(
            user_id=user_id,
            user_email=user_email,
            action="APPROVE",
            resource_type=resource_type,
            resource_id=resource_id,
            tenant_id=tenant_id,
            details=details
        )

    def log_reject(self, user_id: str, user_email: str, resource_type: str,
                   resource_id: str, tenant_id: str, details: Optional[str] = None) -> AuditLog:
        """Log un rejet."""
        return self.log_action(
            user_id=user_id,
            user_email=user_email,
            action="REJECT",
            resource_type=resource_type,
            resource_id=resource_id,
            tenant_id=tenant_id,
            details=details
        )

    def log_login(self, user_id: str, user_email: str, tenant_id: str,
                  details: Optional[str] = None) -> AuditLog:
        """Log une connexion utilisateur."""
        return self.log_action(
            user_id=user_id,
            user_email=user_email,
            action="LOGIN",
            resource_type="auth",
            resource_id=None,
            tenant_id=tenant_id,
            details=details
        )

    def log_logout(self, user_id: str, user_email: str, tenant_id: str,
                   details: Optional[str] = None) -> AuditLog:
        """Log une déconnexion utilisateur."""
        return self.log_action(
            user_id=user_id,
            user_email=user_email,
            action="LOGOUT",
            resource_type="auth",
            resource_id=None,
            tenant_id=tenant_id,
            details=details
        )

    def get_audit_logs(
        self,
        tenant_id: str,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> list[AuditLog]:
        """
        Récupère les logs d'audit avec filtres.

        Args:
            tenant_id: ID du tenant (obligatoire pour isolation)
            user_id: Filtrer par utilisateur
            action: Filtrer par type d'action
            resource_type: Filtrer par type de ressource
            limit: Nombre max de résultats
            offset: Offset pour pagination

        Returns:
            list[AuditLog]: Liste des logs d'audit
        """
        query = self.db.query(AuditLog).filter(AuditLog.tenant_id == tenant_id)

        if user_id:
            query = query.filter(AuditLog.user_id == user_id)

        if action:
            query = query.filter(AuditLog.action == action)

        if resource_type:
            query = query.filter(AuditLog.resource_type == resource_type)

        # Tri par timestamp décroissant (plus récents en premier)
        query = query.order_by(AuditLog.timestamp.desc())

        return query.limit(limit).offset(offset).all()


def get_audit_service(db: Session) -> AuditService:
    """Factory pour AuditService."""
    return AuditService(db)
