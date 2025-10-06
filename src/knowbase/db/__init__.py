"""
Package database - Modèles SQLAlchemy et session management.

Phase 2 - Entity Types Registry
"""
from .base import Base, get_db, init_db
from .models import EntityTypeRegistry

__all__ = ["Base", "get_db", "init_db", "EntityTypeRegistry"]
