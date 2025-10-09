"""
Package database - Modèles SQLAlchemy et session management.

Phase 2 - Entity Types Registry
Phase 6 - Document Types Management
"""
from .base import Base, get_db, init_db, SessionLocal
from .models import EntityTypeRegistry, DocumentType, DocumentTypeEntityType

__all__ = ["Base", "get_db", "init_db", "SessionLocal", "EntityTypeRegistry", "DocumentType", "DocumentTypeEntityType"]
