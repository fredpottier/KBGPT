"""V5 DSG (Document Structure Graph) — opérations Neo4j.

ADR V1.5 §3b : Persistance multi-tenant des structures documentaires.

Architecture :
- Réutilise `Neo4jClient` existant (Phase 1.5 OSMOSE) qui supporte tenant_id
- Labels préfixés V5* pour éviter collision avec KG anchor-driven existant
- Tous les Cypher incluent `tenant_id` dans WHERE/MATCH (enforced par TenantQueryGuard
  en runtime, validé par tests cross-tenant leak)

Schéma (cf migrations/v5_dsg_setup.cypher) :
  (:V5Document {tenant_id, doc_id, doc_internal_id, doc_name, n_pages, doc_version,
                source_uri, canonical_text_uri, ingested_at, extractor_version,
                active_status})
  (:V5Section {tenant_id, section_id, doc_id, level, numbering, title, section_path,
               page_start, page_end, text_snippet, contextual_prefix, text_uri,
               embedding_id})
  (:V5Table {tenant_id, table_id, doc_id, section_id, page, headers, rows, caption,
             footnotes, units})

  (:V5Document)-[:HAS_SECTION]->(:V5Section)
  (:V5Section)-[:HAS_CHILD {order}]->(:V5Section)
  (:V5Section)-[:NEXT_SIBLING]->(:V5Section)
  (:V5Section)-[:HAS_TABLE]->(:V5Table)
  (:V5Document)-[:HAS_VERSION_OF]->(:V5Document)

Note : text_snippet (500 chars) en Neo4j, text complet via text_uri (S3/MinIO) en S2.

Usage :
    from knowbase.runtime_v5.neo4j_dsg import V5DSG
    from knowbase.common.clients.neo4j_client import get_neo4j_client

    dsg = V5DSG(get_neo4j_client())
    dsg.setup_schema()  # idempotent
    dsg.upsert_document(tenant_id="default", doc={...})
    sections = dsg.list_sections(tenant_id="default", doc_id="003_...")
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Any, Optional

from knowbase.runtime_v5.tenant_guard import TenantQueryGuard, get_tenant_guard

logger = logging.getLogger(__name__)

# Schema constraints + indexes (embedded — équivalent migrations/v5_dsg_setup.cypher).
# Ordre : constraints d'abord puis indexes. Tous idempotents (IF NOT EXISTS).
_SCHEMA_STATEMENTS = [
    # ─── Constraints (multi-tenant composite keys) ───
    "CREATE CONSTRAINT v5_doc_tenant_unique IF NOT EXISTS "
    "FOR (d:V5Document) REQUIRE (d.tenant_id, d.doc_id) IS UNIQUE",

    "CREATE CONSTRAINT v5_doc_internal_unique IF NOT EXISTS "
    "FOR (d:V5Document) REQUIRE d.doc_internal_id IS UNIQUE",

    "CREATE CONSTRAINT v5_section_tenant_unique IF NOT EXISTS "
    "FOR (s:V5Section) REQUIRE (s.tenant_id, s.section_id) IS UNIQUE",

    "CREATE CONSTRAINT v5_table_tenant_unique IF NOT EXISTS "
    "FOR (t:V5Table) REQUIRE (t.tenant_id, t.table_id) IS UNIQUE",

    # ─── Indexes (recherche performante) ───
    "CREATE FULLTEXT INDEX v5_section_fulltext IF NOT EXISTS "
    "FOR (s:V5Section) ON EACH [s.title, s.text_snippet]",

    "CREATE FULLTEXT INDEX v5_table_fulltext IF NOT EXISTS "
    "FOR (t:V5Table) ON EACH [t.caption]",

    "CREATE INDEX v5_section_numbering IF NOT EXISTS "
    "FOR (s:V5Section) ON (s.tenant_id, s.doc_id, s.numbering)",

    "CREATE INDEX v5_section_level IF NOT EXISTS "
    "FOR (s:V5Section) ON (s.tenant_id, s.doc_id, s.level)",

    "CREATE INDEX v5_section_doc IF NOT EXISTS "
    "FOR (s:V5Section) ON (s.tenant_id, s.doc_id)",

    "CREATE INDEX v5_doc_active_status IF NOT EXISTS "
    "FOR (d:V5Document) ON (d.tenant_id, d.active_status)",
]


class V5DSG:
    """Document Structure Graph operations on Neo4j (multi-tenant).

    Toutes les requêtes Cypher V5 passent par la `TenantQueryGuard` qui refuse
    les requêtes sans filter `tenant_id` (défense en profondeur vs composite keys).
    """

    def __init__(self, neo4j_client, guard: Optional[TenantQueryGuard] = None) -> None:
        """Init avec un Neo4jClient existant (Phase 1.5 OSMOSE).

        Args:
            neo4j_client: Instance de knowbase.common.clients.neo4j_client.Neo4jClient
            guard: TenantQueryGuard optionnel (default = singleton strict)
        """
        self.client = neo4j_client
        self.guard = guard if guard is not None else get_tenant_guard(strict=True)

    # ────────────────────────────────────────────────────────────────────────
    # Internal helpers — wrapped client with tenant guard
    # ────────────────────────────────────────────────────────────────────────

    def _execute_query(self, cypher: str, *, tenant_id: Optional[str] = None,
                       allow_bypass: bool = False, reason: str = "", **params):
        """Execute read-only Cypher avec validation TenantQueryGuard."""
        self.guard.validate(cypher, tenant_id=tenant_id, allow_bypass=allow_bypass, reason=reason)
        return self.client.execute_query(cypher, tenant_id=tenant_id, **params) \
            if tenant_id is not None else self.client.execute_query(cypher, **params)

    def _execute_write(self, cypher: str, *, tenant_id: Optional[str] = None,
                       allow_bypass: bool = False, reason: str = "", **params):
        """Execute write Cypher avec validation TenantQueryGuard."""
        self.guard.validate(cypher, tenant_id=tenant_id, allow_bypass=allow_bypass, reason=reason)
        return self.client.execute_write(cypher, tenant_id=tenant_id, **params) \
            if tenant_id is not None else self.client.execute_write(cypher, **params)

    # ────────────────────────────────────────────────────────────────────────
    # Schema setup
    # ────────────────────────────────────────────────────────────────────────

    def setup_schema(self) -> dict:
        """Applique constraints + indexes V5 DSG (idempotent).

        Utilise les statements embarqués `_SCHEMA_STATEMENTS`. Idempotent
        grâce à IF NOT EXISTS sur chaque CREATE.

        Returns:
            {"applied": int, "total": int, "errors": list[dict]}
        """
        applied = 0
        errors = []
        for stmt in _SCHEMA_STATEMENTS:
            try:
                # DDL : skip naturellement via _DDL_PATTERN dans la garde
                self._execute_write(stmt)
                applied += 1
                logger.info(f"[V5DSG] Applied: {stmt[:80]}...")
            except Exception as e:
                errors.append({"stmt": stmt[:200], "error": str(e)})
                logger.error(f"[V5DSG] Failed: {stmt[:80]} — {e}")

        return {"applied": applied, "total": len(_SCHEMA_STATEMENTS), "errors": errors}

    # ────────────────────────────────────────────────────────────────────────
    # Document operations
    # ────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _doc_internal_id(tenant_id: str, doc_id: str) -> str:
        """Opaque global ID = sha256(tenant_id, doc_id) (anti-collision)."""
        return "doc_" + hashlib.sha256(f"{tenant_id}|{doc_id}".encode("utf-8")).hexdigest()[:24]

    def upsert_document(
        self,
        tenant_id: str,
        doc_id: str,
        doc_name: Optional[str] = None,
        n_pages: int = 0,
        doc_version: str = "1.0",
        source_uri: str = "",
        canonical_text_uri: str = "",
        extractor_version: str = "docling-page-fallback",
        active_status: str = "active",
    ) -> dict:
        """Upsert un Document V5.

        Args:
            tenant_id: tenant isolation key (obligatoire)
            doc_id: ID document (unique par tenant)

        Returns:
            dict avec doc_internal_id assigné
        """
        if not tenant_id or not doc_id:
            raise ValueError("tenant_id and doc_id required")
        doc_internal_id = self._doc_internal_id(tenant_id, doc_id)
        query = """
        MERGE (d:V5Document {tenant_id: $tenant_id, doc_id: $doc_id})
        ON CREATE SET
            d.doc_internal_id = $doc_internal_id,
            d.doc_name = $doc_name,
            d.n_pages = $n_pages,
            d.doc_version = $doc_version,
            d.source_uri = $source_uri,
            d.canonical_text_uri = $canonical_text_uri,
            d.extractor_version = $extractor_version,
            d.active_status = $active_status,
            d.ingested_at = datetime()
        ON MATCH SET
            d.doc_name = $doc_name,
            d.n_pages = $n_pages,
            d.doc_version = $doc_version,
            d.source_uri = $source_uri,
            d.canonical_text_uri = $canonical_text_uri,
            d.extractor_version = $extractor_version,
            d.active_status = $active_status,
            d.updated_at = datetime()
        RETURN d.doc_internal_id AS doc_internal_id, d.ingested_at AS ingested_at
        """
        result = self._execute_write(
            query,
            tenant_id=tenant_id,
            doc_id=doc_id,
            doc_internal_id=doc_internal_id,
            doc_name=doc_name or doc_id,
            n_pages=n_pages,
            doc_version=doc_version,
            source_uri=source_uri,
            canonical_text_uri=canonical_text_uri,
            extractor_version=extractor_version,
            active_status=active_status,
        )
        return result[0] if result else {"doc_internal_id": doc_internal_id}

    def upsert_section(
        self,
        tenant_id: str,
        doc_id: str,
        section: dict,
        text_max_snippet_chars: int = 500,
    ) -> dict:
        """Upsert une Section + relation HAS_SECTION au Document.

        Args:
            tenant_id: tenant isolation key (obligatoire)
            doc_id: parent document ID
            section: dict avec section_id, level, numbering, title, text, etc.
            text_max_snippet_chars: tronque text → text_snippet pour Neo4j (canonical en S3)

        Returns:
            dict avec section_id
        """
        if not tenant_id or not doc_id:
            raise ValueError("tenant_id and doc_id required")
        section_id = section.get("section_id")
        if not section_id:
            raise ValueError("section.section_id required")
        text = section.get("text", "") or ""
        text_snippet = text[:text_max_snippet_chars]
        page_range = section.get("page_range", [0, 0]) or [0, 0]
        page_start = page_range[0] if isinstance(page_range, list) and page_range else 0
        page_end = page_range[1] if isinstance(page_range, list) and len(page_range) > 1 else page_start

        query = """
        MATCH (d:V5Document {tenant_id: $tenant_id, doc_id: $doc_id})
        MERGE (s:V5Section {tenant_id: $tenant_id, section_id: $section_id})
        ON CREATE SET
            s.doc_id = $doc_id,
            s.level = $level,
            s.numbering = $numbering,
            s.title = $title,
            s.section_path = $section_path,
            s.page_start = $page_start,
            s.page_end = $page_end,
            s.text_snippet = $text_snippet,
            s.contextual_prefix = $contextual_prefix,
            s.text_uri = $text_uri,
            s.created_at = datetime()
        ON MATCH SET
            s.level = $level,
            s.numbering = $numbering,
            s.title = $title,
            s.section_path = $section_path,
            s.page_start = $page_start,
            s.page_end = $page_end,
            s.text_snippet = $text_snippet,
            s.contextual_prefix = $contextual_prefix,
            s.text_uri = $text_uri,
            s.updated_at = datetime()
        MERGE (d)-[:HAS_SECTION]->(s)
        RETURN s.section_id AS section_id
        """
        result = self._execute_write(
            query,
            tenant_id=tenant_id,
            doc_id=doc_id,
            section_id=section_id,
            level=section.get("level", 1),
            numbering=section.get("numbering", "") or "",
            title=section.get("title", "") or "",
            section_path=section.get("section_path", "") or "",
            page_start=page_start,
            page_end=page_end,
            text_snippet=text_snippet,
            contextual_prefix=section.get("contextual_prefix", "") or "",
            text_uri=section.get("text_uri", "") or "",
        )
        return result[0] if result else {"section_id": section_id}

    def link_section_parent(self, tenant_id: str, section_id: str, parent_section_id: str, order: int = 0) -> None:
        """Crée relation HAS_CHILD du parent vers la section (hiérarchie)."""
        if not tenant_id or not section_id or not parent_section_id:
            raise ValueError("tenant_id, section_id, parent_section_id required")
        query = """
        MATCH (parent:V5Section {tenant_id: $tenant_id, section_id: $parent_section_id})
        MATCH (child:V5Section {tenant_id: $tenant_id, section_id: $section_id})
        MERGE (parent)-[r:HAS_CHILD]->(child)
        ON CREATE SET r.order = $order
        """
        self._execute_write(query, tenant_id=tenant_id, section_id=section_id,
                            parent_section_id=parent_section_id, order=order)

    # ────────────────────────────────────────────────────────────────────────
    # Read operations (tenant_id MANDATORY in WHERE)
    # ────────────────────────────────────────────────────────────────────────

    def get_document(self, tenant_id: str, doc_id: str) -> Optional[dict]:
        """Récupère un Document par (tenant_id, doc_id)."""
        if not tenant_id or not doc_id:
            raise ValueError("tenant_id and doc_id required")
        query = """
        MATCH (d:V5Document {tenant_id: $tenant_id, doc_id: $doc_id})
        RETURN d
        """
        result = self._execute_query(query, tenant_id=tenant_id, doc_id=doc_id)
        if not result:
            return None
        return dict(result[0]["d"])

    def list_documents(self, tenant_id: str, active_only: bool = True) -> list[dict]:
        """Liste tous les Documents d'un tenant.

        Args:
            tenant_id: tenant isolation key (obligatoire)
            active_only: si True, filtre active_status='active'
        """
        if not tenant_id:
            raise ValueError("tenant_id required")
        if active_only:
            query = """
            MATCH (d:V5Document {tenant_id: $tenant_id, active_status: 'active'})
            RETURN d
            ORDER BY d.doc_id
            """
        else:
            query = """
            MATCH (d:V5Document {tenant_id: $tenant_id})
            RETURN d
            ORDER BY d.doc_id
            """
        result = self._execute_query(query, tenant_id=tenant_id)
        return [dict(r["d"]) for r in result]

    def get_section(self, tenant_id: str, section_id: str) -> Optional[dict]:
        """Récupère une Section par (tenant_id, section_id)."""
        if not tenant_id or not section_id:
            raise ValueError("tenant_id and section_id required")
        query = """
        MATCH (s:V5Section {tenant_id: $tenant_id, section_id: $section_id})
        RETURN s
        """
        result = self._execute_query(query, tenant_id=tenant_id, section_id=section_id)
        if not result:
            return None
        return dict(result[0]["s"])

    def list_sections(self, tenant_id: str, doc_id: str, level_max: Optional[int] = None) -> list[dict]:
        """Liste toutes les sections d'un document (ordonné par numbering)."""
        if not tenant_id or not doc_id:
            raise ValueError("tenant_id and doc_id required")
        query = """
        MATCH (d:V5Document {tenant_id: $tenant_id, doc_id: $doc_id})-[:HAS_SECTION]->(s:V5Section)
        WHERE $level_max IS NULL OR s.level <= $level_max
        RETURN s
        ORDER BY s.page_start, s.numbering
        """
        result = self._execute_query(
            query, tenant_id=tenant_id, doc_id=doc_id, level_max=level_max
        )
        return [dict(r["s"]) for r in result]

    def find_sections_by_numbering(self, tenant_id: str, doc_id: str, numbering: str) -> list[dict]:
        """Trouve section par numbering exact (pour navigate_by_toc)."""
        if not tenant_id or not doc_id:
            raise ValueError("tenant_id and doc_id required")
        query = """
        MATCH (s:V5Section {tenant_id: $tenant_id, doc_id: $doc_id, numbering: $numbering})
        RETURN s
        LIMIT 5
        """
        result = self._execute_query(
            query, tenant_id=tenant_id, doc_id=doc_id, numbering=numbering
        )
        return [dict(r["s"]) for r in result]

    def search_sections_fulltext(self, tenant_id: str, query: str, doc_id: Optional[str] = None,
                                  max_results: int = 10) -> list[dict]:
        """Full-text search sur title + text_snippet.

        Args:
            tenant_id: tenant isolation key (obligatoire)
            query: requête full-text Neo4j (peut contenir AND, OR, etc.)
            doc_id: optionnel, restreint à un doc
            max_results: limite
        """
        if not tenant_id or not query:
            raise ValueError("tenant_id and query required")
        if doc_id:
            cypher = """
            CALL db.index.fulltext.queryNodes('v5_section_fulltext', $ft_query) YIELD node, score
            WHERE node.tenant_id = $tenant_id AND node.doc_id = $doc_id
            RETURN node AS s, score
            ORDER BY score DESC
            LIMIT $max_results
            """
        else:
            cypher = """
            CALL db.index.fulltext.queryNodes('v5_section_fulltext', $ft_query) YIELD node, score
            WHERE node.tenant_id = $tenant_id
            RETURN node AS s, score
            ORDER BY score DESC
            LIMIT $max_results
            """
        result = self._execute_query(
            cypher, tenant_id=tenant_id, ft_query=query, doc_id=doc_id, max_results=max_results
        )
        return [{**dict(r["s"]), "_fulltext_score": r["score"]} for r in result]

    def get_section_children(self, tenant_id: str, section_id: str) -> list[dict]:
        """Récupère les enfants directs d'une section."""
        if not tenant_id or not section_id:
            raise ValueError("tenant_id and section_id required")
        query = """
        MATCH (parent:V5Section {tenant_id: $tenant_id, section_id: $section_id})-[r:HAS_CHILD]->(child:V5Section)
        RETURN child
        ORDER BY r.order
        """
        result = self._execute_query(query, tenant_id=tenant_id, section_id=section_id)
        return [dict(r["child"]) for r in result]

    def get_section_parent(self, tenant_id: str, section_id: str) -> Optional[dict]:
        """Récupère le parent direct d'une section."""
        if not tenant_id or not section_id:
            raise ValueError("tenant_id and section_id required")
        query = """
        MATCH (parent:V5Section)-[:HAS_CHILD]->(child:V5Section {tenant_id: $tenant_id, section_id: $section_id})
        RETURN parent
        LIMIT 1
        """
        result = self._execute_query(query, tenant_id=tenant_id, section_id=section_id)
        if not result:
            return None
        return dict(result[0]["parent"])

    # ────────────────────────────────────────────────────────────────────────
    # Tenant operations (purge, stats)
    # ────────────────────────────────────────────────────────────────────────

    def tenant_stats(self, tenant_id: str) -> dict:
        """Stats par tenant (compteurs nodes V5)."""
        if not tenant_id:
            raise ValueError("tenant_id required")
        query = """
        OPTIONAL MATCH (d:V5Document {tenant_id: $tenant_id})
        WITH count(d) AS n_documents, $tenant_id AS tid
        OPTIONAL MATCH (s:V5Section {tenant_id: tid})
        WITH n_documents, count(s) AS n_sections, tid
        OPTIONAL MATCH (t:V5Table {tenant_id: tid})
        RETURN n_documents, n_sections, count(t) AS n_tables
        """
        result = self._execute_query(query, tenant_id=tenant_id)
        return dict(result[0]) if result else {"n_documents": 0, "n_sections": 0, "n_tables": 0}

    def tenant_purge(
        self,
        tenant_id: str,
        confirm: bool = False,
        actor: str = "system",
        reason: str = "",
    ) -> dict:
        """Supprime TOUT le DSG d'un tenant (Documents + Sections + Tables).

        ATTENTION : opération destructive et IRREVERSIBLE. Trace persistée dans
        un V5AuditLog node pour conformité multi-tenant (RGPD/SOC2).

        Args:
            tenant_id: tenant à purger (obligatoire)
            confirm: doit être True (sécurité contre erreurs accidentelles)
            actor: identifiant de l'acteur exécutant (default 'system')
            reason: justification métier (audit)

        Returns:
            dict avec audit_id, tenant_id, before, after, purged_at, actor, reason
        """
        if not tenant_id:
            raise ValueError("tenant_id required")
        if not confirm:
            raise ValueError("tenant_purge() requires confirm=True (destructive operation)")
        before = self.tenant_stats(tenant_id)
        # Delete via DETACH DELETE (auto-suppression des relations)
        query = """
        MATCH (n {tenant_id: $tenant_id})
        WHERE (n:V5Document OR n:V5Section OR n:V5Table)
        DETACH DELETE n
        """
        self._execute_write(query, tenant_id=tenant_id)
        after = self.tenant_stats(tenant_id)
        purged_at = datetime.utcnow().isoformat()
        audit_id = "audit_" + hashlib.sha256(
            f"{tenant_id}|{purged_at}|{actor}".encode("utf-8")
        ).hexdigest()[:24]

        # Audit log : log structuré + persistance Neo4j (V5AuditLog node global, hors V5*)
        logger.warning(
            f"[V5DSG AUDIT] tenant_purge tenant_id={tenant_id} actor={actor!r} "
            f"reason={reason!r} before={before} after={after} audit_id={audit_id}"
        )
        try:
            # V5AuditLog n'est PAS un node V5* (hors scope guard) car il documente
            # l'opération sur le tenant — porte tenant_id en référence mais n'est
            # pas soumis à l'isolation (admin global)
            audit_query = """
            CREATE (a:V5AuditLog {
                audit_id: $audit_id,
                event_type: 'tenant_purge',
                tenant_id: $tenant_id,
                actor: $actor,
                reason: $reason,
                before_docs: $before_docs,
                before_sections: $before_sections,
                before_tables: $before_tables,
                after_docs: $after_docs,
                after_sections: $after_sections,
                after_tables: $after_tables,
                purged_at: datetime($purged_at)
            })
            RETURN a.audit_id AS audit_id
            """
            # V5AuditLog n'est pas V5*-prefixed dans _V5_SCOPE_PATTERN, donc skip guard naturellement.
            # Mais comme on a `:V5AuditLog`, on a pas de match — bonne chose.
            self.client.execute_write(
                audit_query,
                audit_id=audit_id,
                tenant_id=tenant_id,
                actor=actor,
                reason=reason,
                before_docs=before.get("n_documents", 0),
                before_sections=before.get("n_sections", 0),
                before_tables=before.get("n_tables", 0),
                after_docs=after.get("n_documents", 0),
                after_sections=after.get("n_sections", 0),
                after_tables=after.get("n_tables", 0),
                purged_at=purged_at,
            )
        except Exception as e:
            logger.error(f"[V5DSG AUDIT] Failed to persist audit log: {e}")
            # On NE bloque PAS la purge si l'audit persiste pas (le log structuré reste)

        return {
            "audit_id": audit_id,
            "tenant_id": tenant_id,
            "before": before,
            "after": after,
            "purged_at": purged_at,
            "actor": actor,
            "reason": reason,
        }

    def get_audit_log(self, tenant_id: Optional[str] = None, limit: int = 50) -> list[dict]:
        """Récupère les entrées d'audit V5AuditLog.

        Args:
            tenant_id: si fourni, filtre sur ce tenant. Sinon, tous tenants (admin).
            limit: max résultats

        Returns:
            Liste d'audit entries triées par purged_at DESC
        """
        if tenant_id:
            query = """
            MATCH (a:V5AuditLog {tenant_id: $tenant_id})
            RETURN a
            ORDER BY a.purged_at DESC
            LIMIT $limit
            """
            params = {"tenant_id": tenant_id, "limit": limit}
        else:
            query = """
            MATCH (a:V5AuditLog)
            RETURN a
            ORDER BY a.purged_at DESC
            LIMIT $limit
            """
            params = {"limit": limit}
        # V5AuditLog n'est pas V5* prefixed (au sens DSG), donc pas dans _V5_SCOPE_PATTERN
        result = self.client.execute_query(query, **params)
        out = []
        for r in result:
            d = dict(r["a"])
            # Convert Neo4j datetime to isoformat
            if "purged_at" in d and hasattr(d["purged_at"], "isoformat"):
                d["purged_at"] = d["purged_at"].isoformat()
            out.append(d)
        return out


def get_v5_dsg(neo4j_client=None) -> V5DSG:
    """Factory : retourne un V5DSG avec un Neo4jClient (default = singleton existant)."""
    if neo4j_client is None:
        from knowbase.common.clients.neo4j_client import get_neo4j_client
        neo4j_client = get_neo4j_client()
    return V5DSG(neo4j_client)
