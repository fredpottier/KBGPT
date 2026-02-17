"""
Conftest pour tests resolution — mock des modules externes non disponibles localement.

Les tests de reclassification n'ont pas besoin de neo4j, sqlalchemy, graphiti, etc.
On les mock au niveau sys.modules pour éviter les ImportError.
"""

import sys
from unittest.mock import MagicMock


def _make_mock_package(name: str) -> MagicMock:
    """Crée un MagicMock qui se comporte comme un package Python."""
    mock = MagicMock()
    mock.__path__ = []
    mock.__file__ = f"<mock {name}>"
    mock.__name__ = name
    mock.__package__ = name
    mock.__loader__ = None
    mock.__spec__ = None
    return mock


def _install_mock(name: str) -> None:
    if name not in sys.modules:
        sys.modules[name] = _make_mock_package(name)


# Modules à mocker avant tout import de knowbase.claimfirst.resolution
_PACKAGES = [
    # Neo4j
    "neo4j", "neo4j.exceptions",
    # Graphiti
    "graphiti_core", "graphiti_core.nodes", "graphiti_core.edges",
    # SQLAlchemy (arbre complet)
    "sqlalchemy", "sqlalchemy.orm", "sqlalchemy.sql", "sqlalchemy.sql.func",
    "sqlalchemy.ext", "sqlalchemy.ext.declarative", "sqlalchemy.pool",
    "sqlalchemy.engine",
    # DB knowbase
    "knowbase.db", "knowbase.db.base", "knowbase.db.models",
    # OpenAI / LLM
    "openai", "anthropic",
    # Redis / RQ
    "redis", "rq",
    # FastAPI
    "fastapi", "fastapi.security",
    # Qdrant
    "qdrant_client", "qdrant_client.models",
]

for pkg in _PACKAGES:
    _install_mock(pkg)

# knowbase.db.base doit exposer SessionLocal et Base
sys.modules["knowbase.db.base"].SessionLocal = MagicMock()
sys.modules["knowbase.db.base"].Base = MagicMock()
sys.modules["knowbase.db.models"].DomainContext = MagicMock()
