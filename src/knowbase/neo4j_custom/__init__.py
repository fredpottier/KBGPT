"""
Neo4j Native Custom Layer

Ce module fournit une couche d'abstraction custom pour Neo4j,
adaptée aux besoins spécifiques du projet (Facts governance).

Composants:
- client.py: Neo4jCustomClient (wrapper driver Neo4j)
- schemas.py: Schémas Cypher (Facts, Entities, Relations)
- queries.py: Requêtes Cypher réutilisables
- migrations.py: Gestion migrations schéma

Usage:
    from knowbase.neo4j_custom import get_neo4j_client, FactsQueries, apply_migrations

    # Get client
    client = get_neo4j_client()

    # Apply migrations
    apply_migrations(client)

    # Use Facts queries
    facts = FactsQueries(client, tenant_id="acme")
    fact = facts.create_fact(
        subject="SAP S/4HANA Cloud",
        predicate="SLA_garantie",
        object_str="99.7%",
        value=99.7,
        unit="%"
    )
"""

__version__ = "1.0.0"

from .client import (
    Neo4jCustomClient,
    Neo4jConnectionError,
    Neo4jQueryError,
    get_neo4j_client,
    close_neo4j_client,
)

from .migrations import (
    Neo4jMigrations,
    MigrationError,
    apply_migrations,
)

from .queries import FactsQueries

__all__ = [
    # Client
    "Neo4jCustomClient",
    "Neo4jConnectionError",
    "Neo4jQueryError",
    "get_neo4j_client",
    "close_neo4j_client",

    # Migrations
    "Neo4jMigrations",
    "MigrationError",
    "apply_migrations",

    # Queries
    "FactsQueries",
]
