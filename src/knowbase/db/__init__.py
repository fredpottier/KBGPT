"""
Package database - Modèles SQLAlchemy et session management.

Phase 0 - Security Hardening (User, AuditLog)
Phase 2 - Entity Types Registry
Phase 6 - Document Types Management
"""
from .base import Base, get_db, init_db, SessionLocal
from .models import EntityTypeRegistry, DocumentType, DocumentTypeEntityType, User, AuditLog
from .init_admin import init_default_admin

__all__ = [
    "Base",
    "get_db",
    "init_db",
    "SessionLocal",
    "EntityTypeRegistry",
    "DocumentType",
    "DocumentTypeEntityType",
    "User",
    "AuditLog",
    "init_default_admin"
]
