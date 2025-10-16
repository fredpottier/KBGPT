"""
Base SQLAlchemy et session management.

Phase 2 - Entity Types Registry
"""
from __future__ import annotations

from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

from knowbase.config.settings import get_settings

settings = get_settings()

# URL base de données
# Pour l'instant SQLite, migration vers PostgreSQL possible plus tard
DATABASE_URL = f"sqlite:///{settings.data_dir}/knowbase.db"

# Engine SQLAlchemy
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # SQLite uniquement
    echo=settings.debug_mode  # Log SQL si debug
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
    from knowbase.db.models import EntityTypeRegistry  # noqa: F401

    # Créer toutes les tables
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    """
    Dependency FastAPI pour obtenir une session DB.

    Usage:
        @router.get("/endpoint")
        async def endpoint(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


__all__ = ["Base", "engine", "SessionLocal", "init_db", "get_db"]
