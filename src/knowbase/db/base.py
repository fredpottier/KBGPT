"""
Base SQLAlchemy et session management.

Phase 2 - Entity Types Registry
Phase 2.5 - Memory Layer (PostgreSQL)
"""
from __future__ import annotations

import os
import logging
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session as SQLAlchemySession
from sqlalchemy.pool import QueuePool

from knowbase.config.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# URL base de données
# Priorité: DATABASE_URL env var > PostgreSQL config > SQLite fallback
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    # Essayer de construire l'URL PostgreSQL depuis les variables individuelles
    pg_host = os.getenv("POSTGRES_HOST")
    pg_port = os.getenv("POSTGRES_PORT", "5432")
    pg_db = os.getenv("POSTGRES_DB")
    pg_user = os.getenv("POSTGRES_USER")
    pg_pass = os.getenv("POSTGRES_PASSWORD")

    if all([pg_host, pg_db, pg_user, pg_pass]):
        DATABASE_URL = f"postgresql://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}"
        logger.info(f"[DB] Using PostgreSQL: {pg_host}:{pg_port}/{pg_db}")
    else:
        # Fallback SQLite
        DATABASE_URL = f"sqlite:///{settings.data_dir}/knowbase.db"
        logger.warning(f"[DB] PostgreSQL not configured, using SQLite fallback: {DATABASE_URL}")

# Détecter le type de base de données
is_sqlite = DATABASE_URL.startswith("sqlite")

# Engine SQLAlchemy avec configuration adaptée
if is_sqlite:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        echo=settings.debug_mode
    )
else:
    # PostgreSQL avec connection pooling
    engine = create_engine(
        DATABASE_URL,
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,  # Vérifie connexion avant utilisation
        echo=settings.debug_mode
    )

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base declarative pour modèles
Base = declarative_base()


def init_db() -> None:
    """
    Initialise la base de données (créé toutes les tables).

    À appeler au démarrage de l'application.
    """
    # Import tous les modèles pour que Base.metadata les connaisse
    from knowbase.db.models import (  # noqa: F401
        EntityTypeRegistry,
        DocumentType,
        DocumentTypeEntityType,
        User,
        AuditLog,
        Session,
        SessionMessage,
        DomainContext
    )

    # Créer toutes les tables
    Base.metadata.create_all(bind=engine)
    logger.info("[DB] Tables created/verified successfully")


def get_db() -> Generator[SQLAlchemySession, None, None]:
    """
    Dependency FastAPI pour obtenir une session DB.

    Usage:
        @router.get("/endpoint")
        async def endpoint(db: SQLAlchemySession = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Export Session alias for backward compatibility
DBSession = SQLAlchemySession

__all__ = ["Base", "engine", "SessionLocal", "init_db", "get_db", "DBSession", "is_sqlite"]
