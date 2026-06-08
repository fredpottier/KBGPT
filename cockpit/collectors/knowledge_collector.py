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
        """Collecte l'agrégat (compat). Cf collect_full() pour le détail par tenant."""
        agg, _ = self.collect_full()
        return agg

    def collect_full(self) -> tuple[KnowledgeStatus, list[KnowledgeStatus]]:
        """Collecte agrégat + ventilation par tenant.

        Retourne (agrégat tous tenants, [KnowledgeStatus par tenant]).
        Les tenants sont auto-découverts (DISTINCT c.tenant_id).
        """
        now = datetime.now(timezone.utc).isoformat()
        agg = KnowledgeStatus(tenant=None, last_refresh=now)

        # Qdrant (agrégat — collection partagée)
        self._collect_qdrant(agg)

        # Neo4j agrégat (tous tenants)
        self._collect_neo4j(agg, tenant=None)

        # Neo4j par tenant
        per_tenant: list[KnowledgeStatus] = []
        for tid in self._discover_tenants():
            st = KnowledgeStatus(tenant=tid, last_refresh=now,
                                 qdrant_ok=agg.qdrant_ok,
                                 qdrant_collections=agg.qdrant_collections)
            self._collect_neo4j(st, tenant=tid)
            self._collect_qdrant_tenant(st, tid)
            per_tenant.append(st)

        # Tri : plus gros KG d'abord
        per_tenant.sort(key=lambda s: s.neo4j_claims, reverse=True)
        return agg, per_tenant

    def _discover_tenants(self) -> list[str]:
        """Liste les tenants présents dans le KG (DISTINCT c.tenant_id)."""
        driver = self._get_neo4j()
        if driver is None:
            return []
        try:
            with driver.session() as s:
                rows = s.run(
                    "MATCH (c:Claim) WHERE c.tenant_id IS NOT NULL "
                    "RETURN DISTINCT c.tenant_id AS t"
                )
                return [r["t"] for r in rows if r["t"]]
        except Exception as e:
            logger.debug(f"[COCKPIT:KNOWLEDGE] discover tenants failed: {e}")
            return []

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

    def _collect_neo4j(self, status: KnowledgeStatus, tenant: Optional[str] = None):
        """Interroge Neo4j via Bolt. Si `tenant` fourni, filtre par tenant_id."""
        driver = self._get_neo4j()
        if driver is None:
            return

        # Filtre tenant : on paramètre $t et on ajoute le prédicat aux MATCH de nœuds.
        # Pour les relations, on scope sur le tenant du nœud source (Claim).
        if tenant:
            queries = {
                "neo4j_nodes": "MATCH (n) WHERE n.tenant_id = $t AND NOT n:OntologyEntity AND NOT n:OntologyAlias RETURN count(n) as c",
                "neo4j_claims": "MATCH (n:Claim {tenant_id: $t}) RETURN count(n) as c",
                "neo4j_entities": "MATCH (n:Entity {tenant_id: $t}) RETURN count(n) as c",
                "neo4j_facets": "MATCH (n:Facet {tenant_id: $t}) RETURN count(n) as c",
                "neo4j_perspectives": "MATCH (n:Perspective {tenant_id: $t}) RETURN count(n) as c",
                "neo4j_subjects": "MATCH (n:ComparableSubject {tenant_id: $t}) RETURN count(n) as c",
                "neo4j_relations": "MATCH (a:Claim {tenant_id: $t})-[r]->() RETURN count(r) as c",
                "neo4j_contradictions": "MATCH (:Claim {tenant_id: $t})-[r:CONTRADICTS]->(:Claim) RETURN count(r) as c",
                "neo4j_documents": "MATCH (d:Document {tenant_id: $t}) RETURN count(d) as c",
                "neo4j_supersedes_doc": "MATCH (:Document {tenant_id: $t})-[r:SUPERSEDES_DOC]->() RETURN count(r) as c",
            }
            params = {"t": tenant}
        else:
            queries = {
                "neo4j_nodes": "MATCH (n) WHERE NOT n:OntologyEntity AND NOT n:OntologyAlias RETURN count(n) as c",
                "neo4j_claims": "MATCH (n:Claim) RETURN count(n) as c",
                "neo4j_entities": "MATCH (n:Entity) RETURN count(n) as c",
                "neo4j_facets": "MATCH (n:Facet) RETURN count(n) as c",
                "neo4j_perspectives": "MATCH (n:Perspective) RETURN count(n) as c",
                "neo4j_subjects": "MATCH (n:ComparableSubject) RETURN count(n) as c",
                "neo4j_relations": "MATCH ()-[r]->() RETURN count(r) as c",
                "neo4j_contradictions": "MATCH (:Claim)-[r:CONTRADICTS]->(:Claim) RETURN count(r) as c",
                "neo4j_documents": "MATCH (d:Document) RETURN count(d) as c",
                "neo4j_supersedes_doc": "MATCH (:Document)-[r:SUPERSEDES_DOC]->() RETURN count(r) as c",
            }
            params = {}

        try:
            with driver.session() as session:
                for attr, query in queries.items():
                    try:
                        record = session.run(query, **params).single()
                        if record:
                            setattr(status, attr, record["c"])
                    except Exception as e:
                        logger.debug(f"[COCKPIT:KNOWLEDGE] Neo4j query {attr} failed: {e}")
                status.neo4j_ok = True
        except Exception as e:
            logger.debug(f"[COCKPIT:KNOWLEDGE] Neo4j session failed: {e}")
            status.neo4j_ok = False

    def _collect_qdrant_tenant(self, status: KnowledgeStatus, tenant: str):
        """Compte les chunks Qdrant filtrés par tenant_id (payload)."""
        try:
            import httpx
            resp = httpx.post(
                f"{QDRANT_URL}/collections/{QDRANT_COLLECTION}/points/count",
                json={"filter": {"must": [{"key": "tenant_id", "match": {"value": tenant}}]}, "exact": True},
                timeout=5.0,
            )
            if resp.status_code == 200:
                status.qdrant_chunks = resp.json().get("result", {}).get("count", 0)
                status.qdrant_ok = True
        except Exception as e:
            logger.debug(f"[COCKPIT:KNOWLEDGE] Qdrant tenant count failed: {e}")
