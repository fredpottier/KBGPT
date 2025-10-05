"""
Neo4j Custom Client

Wrapper autour du driver Neo4j officiel avec fonctionnalités:
- Gestion connexion resilient
- Retry automatique
- Logging structuré
- Health checks
- Transaction management
"""

import os
import logging
from typing import Optional, Dict, Any, List
from contextlib import contextmanager

from neo4j import GraphDatabase, Driver, Session, Transaction
from neo4j.exceptions import ServiceUnavailable, TransientError

logger = logging.getLogger(__name__)


class Neo4jConnectionError(Exception):
    """Erreur connexion Neo4j"""
    pass


class Neo4jQueryError(Exception):
    """Erreur exécution query Neo4j"""
    pass


class Neo4jCustomClient:
    """
    Client Neo4j custom avec retry logic et health checks.

    Usage:
        client = Neo4jCustomClient()
        with client.session() as session:
            result = session.run("MATCH (n) RETURN count(n)")
            count = result.single()[0]
    """

    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: str = "neo4j",
        max_connection_lifetime: int = 3600,
        max_connection_pool_size: int = 50,
        connection_timeout: float = 30.0,
        max_retry_attempts: int = 3,
    ):
        """
        Initialise client Neo4j.

        Args:
            uri: URI Neo4j (default: env NEO4J_URI)
            user: Username (default: env NEO4J_USER)
            password: Password (default: env NEO4J_PASSWORD)
            database: Database name
            max_connection_lifetime: Max lifetime connexion (secondes)
            max_connection_pool_size: Taille pool connexions
            connection_timeout: Timeout connexion (secondes)
            max_retry_attempts: Nombre max tentatives retry
        """
        self.uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self.user = user or os.getenv("NEO4J_USER", "neo4j")
        self.password = password or os.getenv("NEO4J_PASSWORD", "neo4j_password")
        self.database = database
        self.max_retry_attempts = max_retry_attempts

        self._driver: Optional[Driver] = None

        # Configuration driver
        self._driver_config = {
            "max_connection_lifetime": max_connection_lifetime,
            "max_connection_pool_size": max_connection_pool_size,
            "connection_timeout": connection_timeout,
            "encrypted": False,  # True en production avec TLS
        }

        logger.info(
            f"Neo4jCustomClient initialized - URI: {self.uri}, "
            f"User: {self.user}, Database: {self.database}"
        )

    def connect(self) -> None:
        """Établit connexion Neo4j avec retry."""
        if self._driver is not None:
            logger.warning("Driver already connected")
            return

        for attempt in range(1, self.max_retry_attempts + 1):
            try:
                self._driver = GraphDatabase.driver(
                    self.uri,
                    auth=(self.user, self.password),
                    **self._driver_config
                )

                # Test connexion
                self._driver.verify_connectivity()

                logger.info(
                    f"✅ Connected to Neo4j - Attempt {attempt}/{self.max_retry_attempts}"
                )
                return

            except ServiceUnavailable as e:
                logger.warning(
                    f"⚠️ Neo4j connection attempt {attempt}/{self.max_retry_attempts} failed: {e}"
                )

                if attempt == self.max_retry_attempts:
                    raise Neo4jConnectionError(
                        f"Failed to connect to Neo4j after {self.max_retry_attempts} attempts"
                    ) from e

                # Exponential backoff
                import time
                time.sleep(2 ** attempt)

    def close(self) -> None:
        """Ferme connexion Neo4j proprement."""
        if self._driver is not None:
            self._driver.close()
            self._driver = None
            logger.info("Neo4j connection closed")

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    @property
    def driver(self) -> Driver:
        """Retourne driver Neo4j (lazy connect)."""
        if self._driver is None:
            self.connect()
        return self._driver

    @contextmanager
    def session(self, database: Optional[str] = None) -> Session:
        """
        Context manager pour session Neo4j.

        Usage:
            with client.session() as session:
                result = session.run("MATCH (n) RETURN n")
        """
        db = database or self.database
        session = self.driver.session(database=db)
        try:
            yield session
        finally:
            session.close()

    def execute_query(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Exécute query Cypher et retourne résultats.

        Args:
            query: Query Cypher
            parameters: Paramètres query
            database: Database (optionnel)

        Returns:
            Liste de dictionnaires (résultats)

        Raises:
            Neo4jQueryError: Si erreur exécution query
        """
        params = parameters or {}

        try:
            with self.session(database=database) as session:
                result = session.run(query, params)

                # Convertir résultats en liste de dicts
                records = []
                for record in result:
                    records.append(dict(record))

                logger.debug(
                    f"Query executed - Records: {len(records)}, "
                    f"Query: {query[:100]}..."
                )

                return records

        except TransientError as e:
            logger.error(f"Transient error executing query: {e}")
            raise Neo4jQueryError(f"Transient error: {e}") from e

        except Exception as e:
            logger.error(f"Error executing query: {e}")
            raise Neo4jQueryError(f"Query failed: {e}") from e

    def execute_write_query(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        database: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Exécute write query (CREATE, UPDATE, DELETE) en transaction.

        Args:
            query: Query Cypher
            parameters: Paramètres query
            database: Database (optionnel)

        Returns:
            Liste de dictionnaires (résultats)
        """
        params = parameters or {}

        def _execute_tx(tx: Transaction):
            result = tx.run(query, params)
            return [dict(record) for record in result]

        try:
            with self.session(database=database) as session:
                records = session.execute_write(_execute_tx)

                logger.debug(
                    f"Write query executed - Records: {len(records)}, "
                    f"Query: {query[:100]}..."
                )

                return records

        except Exception as e:
            logger.error(f"Error executing write query: {e}")
            raise Neo4jQueryError(f"Write query failed: {e}") from e

    def verify_connectivity(self) -> bool:
        """
        Vérifie connectivité Neo4j.

        Returns:
            True si connexion OK, False sinon
        """
        try:
            self.driver.verify_connectivity()
            return True
        except Exception as e:
            logger.error(f"Connectivity check failed: {e}")
            return False

    def get_server_info(self) -> Dict[str, Any]:
        """
        Retourne informations serveur Neo4j.

        Returns:
            Dict avec version, address, etc.
        """
        try:
            with self.session() as session:
                result = session.run("CALL dbms.components() YIELD name, versions, edition")
                record = result.single()

                if record:
                    return {
                        "name": record["name"],
                        "versions": record["versions"],
                        "edition": record["edition"],
                    }

                return {}

        except Exception as e:
            logger.error(f"Failed to get server info: {e}")
            return {}

    def health_check(self) -> Dict[str, Any]:
        """
        Health check complet Neo4j.

        Returns:
            Dict avec status, latency, node_count, etc.
        """
        import time

        health = {
            "status": "unhealthy",
            "latency_ms": None,
            "node_count": None,
            "error": None,
        }

        try:
            # Mesurer latency
            start = time.time()

            with self.session() as session:
                result = session.run("MATCH (n) RETURN count(n) as count")
                count = result.single()["count"]

            latency_ms = (time.time() - start) * 1000

            health.update({
                "status": "healthy",
                "latency_ms": round(latency_ms, 2),
                "node_count": count,
            })

        except Exception as e:
            health["error"] = str(e)
            logger.error(f"Health check failed: {e}")

        return health


# Singleton global client (lazy initialized)
_global_client: Optional[Neo4jCustomClient] = None


def get_neo4j_client() -> Neo4jCustomClient:
    """
    Retourne client Neo4j singleton.

    Usage:
        client = get_neo4j_client()
        with client.session() as session:
            ...
    """
    global _global_client

    if _global_client is None:
        _global_client = Neo4jCustomClient()
        _global_client.connect()

    return _global_client


def close_neo4j_client() -> None:
    """Ferme client Neo4j singleton."""
    global _global_client

    if _global_client is not None:
        _global_client.close()
        _global_client = None
