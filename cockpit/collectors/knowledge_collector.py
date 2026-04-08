"""
Collecteur Knowledge — métriques Qdrant + Neo4j.

Interroge directement les APIs pour obtenir les compteurs métier.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from cockpit.config import QDRANT_URL, QDRANT_COLLECTION, NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
from cockpit.models import KnowledgeStatus

logger = logging.getLogger(__name__)


class KnowledgeCollector:
    def __init__(self):
        self._neo4j_driver = None

    def _get_neo4j(self):
        if self._neo4j_driver is None:
            try:
                from neo4j import GraphDatabase
                self._neo4j_driver = GraphDatabase.driver(
                    NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD),
                )
            except Exception as e:
                logger.warning(f"[COCKPIT:KNOWLEDGE] Neo4j init failed: {e}")
        return self._neo4j_driver

    def collect(self) -> KnowledgeStatus:
        """Collecte les métriques Qdrant + Neo4j."""
        status = KnowledgeStatus(
            last_refresh=datetime.now(timezone.utc).isoformat(),
        )

        # Qdrant
        self._collect_qdrant(status)

        # Neo4j
        self._collect_neo4j(status)

        return status

    def _collect_qdrant(self, status: KnowledgeStatus):
        """Interroge Qdrant HTTP API."""
        try:
            import httpx
            # Collections list
            resp = httpx.get(f"{QDRANT_URL}/collections", timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                collections = data.get("result", {}).get("collections", [])
                status.qdrant_collections = len(collections)
                status.qdrant_ok = True

                # Points count pour la collection principale
                resp2 = httpx.get(
                    f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}", timeout=5.0,
                )
                if resp2.status_code == 200:
                    info = resp2.json().get("result", {})
                    status.qdrant_chunks = info.get("points_count", 0)
        except Exception as e:
            logger.debug(f"[COCKPIT:KNOWLEDGE] Qdrant failed: {e}")
            status.qdrant_ok = False

    def _collect_neo4j(self, status: KnowledgeStatus):
        """Interroge Neo4j via Bolt."""
        driver = self._get_neo4j()
        if driver is None:
            return

        queries = {
            "neo4j_nodes": "MATCH (n) WHERE NOT n:OntologyEntity AND NOT n:OntologyAlias RETURN count(n) as c",
            "neo4j_claims": "MATCH (n:Claim) RETURN count(n) as c",
            "neo4j_entities": "MATCH (n:Entity) RETURN count(n) as c",
            "neo4j_facets": "MATCH (n:Facet) RETURN count(n) as c",
            "neo4j_perspectives": "MATCH (n:Perspective) RETURN count(n) as c",
            "neo4j_subjects": "MATCH (n:ComparableSubject) RETURN count(n) as c",
            "neo4j_relations": "MATCH ()-[r]->() RETURN count(r) as c",
            "neo4j_contradictions": "MATCH (:Claim)-[r:CONTRADICTS]->(:Claim) RETURN count(r) as c",
        }

        try:
            with driver.session() as session:
                for attr, query in queries.items():
                    try:
                        result = session.run(query)
                        record = result.single()
                        if record:
                            setattr(status, attr, record["c"])
                    except Exception as e:
                        logger.debug(f"[COCKPIT:KNOWLEDGE] Neo4j query {attr} failed: {e}")
                status.neo4j_ok = True
        except Exception as e:
            logger.debug(f"[COCKPIT:KNOWLEDGE] Neo4j session failed: {e}")
            status.neo4j_ok = False
