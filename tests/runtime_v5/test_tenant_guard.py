"""Tests TenantQueryGuard — validation isolation multi-tenant V5 DSG."""
from __future__ import annotations

import pytest

from knowbase.runtime_v5.tenant_guard import (
    TenantIsolationError,
    TenantQueryGuard,
    get_tenant_guard,
    reset_tenant_guard,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_tenant_guard()
    yield
    reset_tenant_guard()


@pytest.fixture
def guard():
    return TenantQueryGuard(strict=True)


# ─── Cypher VALIDES (avec filter tenant_id) ──────────────────────────────────

class TestValidQueries:
    """Cypher conformes : doivent passer sans exception."""

    def test_inline_property_with_param(self, guard):
        guard.validate(
            "MATCH (d:V5Document {tenant_id: $tenant_id, doc_id: $doc_id}) RETURN d",
            tenant_id="default",
        )

    def test_inline_property_with_literal(self, guard):
        guard.validate(
            "MATCH (d:V5Document {tenant_id: 'default'}) RETURN d",
            tenant_id="default",
        )

    def test_where_clause(self, guard):
        guard.validate(
            "MATCH (s:V5Section) WHERE s.tenant_id = $tenant_id RETURN s",
            tenant_id="default",
        )

    def test_where_clause_double_quotes(self, guard):
        guard.validate(
            'MATCH (s:V5Section) WHERE s.tenant_id = "default" RETURN s',
            tenant_id="default",
        )

    def test_where_in_clause(self, guard):
        guard.validate(
            "MATCH (s:V5Section) WHERE s.tenant_id IN $tenants RETURN s",
            tenant_id="default",
        )

    def test_merge_with_inline(self, guard):
        guard.validate(
            """
            MERGE (d:V5Document {tenant_id: $tenant_id, doc_id: $doc_id})
            ON CREATE SET d.name = $name
            RETURN d
            """,
            tenant_id="default",
        )

    def test_create_with_set_tenant(self, guard):
        guard.validate(
            "CREATE (s:V5Section) SET s.tenant_id = $tenant_id, s.title = $title",
            tenant_id="default",
        )

    def test_multiline_with_where(self, guard):
        guard.validate(
            """
            MATCH (d:V5Document)-[:HAS_SECTION]->(s:V5Section)
            WHERE d.tenant_id = $tenant_id
              AND s.tenant_id = $tenant_id
              AND d.doc_id = $doc_id
            RETURN s
            ORDER BY s.numbering
            """,
            tenant_id="default",
        )

    def test_v5_table_with_filter(self, guard):
        guard.validate(
            "MATCH (t:V5Table {tenant_id: $tenant_id}) RETURN t",
            tenant_id="default",
        )


# ─── Cypher INVALIDES (sans filter tenant_id) ────────────────────────────────

class TestViolations:
    """Cypher non-conformes : doivent lever TenantIsolationError en strict."""

    def test_section_no_filter(self, guard):
        with pytest.raises(TenantIsolationError, match="missing tenant_id"):
            guard.validate("MATCH (s:V5Section) RETURN s", tenant_id="default")

    def test_document_no_filter(self, guard):
        with pytest.raises(TenantIsolationError):
            guard.validate("MATCH (d:V5Document) RETURN d.doc_id", tenant_id="default")

    def test_other_property_doc_id_only(self, guard):
        with pytest.raises(TenantIsolationError):
            guard.validate(
                "MATCH (d:V5Document {doc_id: $doc_id}) RETURN d",
                tenant_id="default",
            )

    def test_where_on_wrong_field(self, guard):
        with pytest.raises(TenantIsolationError):
            guard.validate(
                "MATCH (s:V5Section) WHERE s.doc_id = $doc_id RETURN s",
                tenant_id="default",
            )

    def test_create_without_tenant_set(self, guard):
        with pytest.raises(TenantIsolationError):
            guard.validate(
                "CREATE (s:V5Section {section_id: $sid}) RETURN s",
                tenant_id="default",
            )

    def test_delete_without_tenant(self, guard):
        with pytest.raises(TenantIsolationError):
            guard.validate(
                "MATCH (d:V5Document) DETACH DELETE d",
                tenant_id="default",
            )

    def test_table_no_filter(self, guard):
        with pytest.raises(TenantIsolationError):
            guard.validate("MATCH (t:V5Table) RETURN t", tenant_id="default")


# ─── Cypher hors-scope V5 (passent sans validation) ──────────────────────────

class TestOutOfScope:
    """Cypher sans labels V5* : pas de validation requise (KG anchor-driven)."""

    def test_anchor_master(self, guard):
        guard.validate("MATCH (a:AnchorMaster) RETURN a", tenant_id="default")

    def test_claim(self, guard):
        guard.validate("MATCH (c:Claim {tenant_id: $tid}) RETURN c", tenant_id="default")

    def test_perspective(self, guard):
        guard.validate("MATCH (p:Perspective) RETURN p LIMIT 10", tenant_id="default")

    def test_show_constraints(self, guard):
        guard.validate("SHOW CONSTRAINTS", tenant_id="default")


# ─── Mode bypass (admin) ─────────────────────────────────────────────────────

class TestBypass:
    """allow_bypass=True permet d'exécuter sans filter (admin only)."""

    def test_bypass_skips_validation(self, guard):
        guard.validate(
            "MATCH (s:V5Section) DETACH DELETE s",
            tenant_id=None,
            allow_bypass=True,
            reason="tenant_purge_full_admin",
        )

    def test_bypass_increments_counter(self, guard):
        guard.reset_stats()
        guard.validate(
            "MATCH (s:V5Section) RETURN count(s)",
            allow_bypass=True,
            reason="admin_stats",
        )
        assert guard.stats()["n_bypass"] == 1
        assert guard.stats()["n_violations"] == 0


# ─── Mode non-strict (dev) ───────────────────────────────────────────────────

class TestNonStrict:
    """strict=False : log warning au lieu de raise."""

    def test_non_strict_does_not_raise(self):
        guard = TenantQueryGuard(strict=False)
        # Ne doit pas lever
        guard.validate("MATCH (s:V5Section) RETURN s", tenant_id="default")
        assert guard.stats()["n_violations"] == 1


# ─── Stats & singleton ───────────────────────────────────────────────────────

class TestStats:
    def test_stats_counters(self, guard):
        guard.reset_stats()
        guard.validate("MATCH (s:V5Section {tenant_id: $tid}) RETURN s", tenant_id="t1")
        guard.validate("MATCH (a:AnchorMaster) RETURN a", tenant_id="t1")
        s = guard.stats()
        assert s["n_validated"] == 2
        assert s["n_violations"] == 0
        assert s["n_bypass"] == 0

    def test_singleton(self):
        g1 = get_tenant_guard()
        g2 = get_tenant_guard()
        assert g1 is g2

    def test_singleton_reset(self):
        g1 = get_tenant_guard()
        reset_tenant_guard()
        g2 = get_tenant_guard()
        assert g1 is not g2


# ─── Cas piégeux / faux positifs potentiels ──────────────────────────────────

class TestEdgeCases:
    """Cas limites identifiés dans la doc du module."""

    def test_tenant_id_in_comment_only_should_fail(self, guard):
        """Limite connue : tenant_id mentionné en commentaire est accepté par regex.
        Documenté dans le module — couverture défense en profondeur via tests cross-tenant e2e (S1.4)."""
        # On accepte ce faux négatif pour l'instant — tests e2e couvrent
        # (le commentaire `// tenant_id` ne matche pas WHERE/inline mais pourrait
        # matcher si on étend les patterns trop libéralement)
        with pytest.raises(TenantIsolationError):
            guard.validate(
                "// filtre tenant_id à ajouter\nMATCH (s:V5Section) RETURN s",
                tenant_id="default",
            )

    def test_case_insensitive_label(self, guard):
        """Cypher case-insensitive sur les labels — pattern doit le tolérer."""
        with pytest.raises(TenantIsolationError):
            guard.validate("MATCH (s:v5section) RETURN s", tenant_id="default")

    def test_match_with_other_property_then_where_tenant(self, guard):
        """Combinaison : inline `{doc_id: X}` mais WHERE `tenant_id = Y`."""
        guard.validate(
            """
            MATCH (s:V5Section {doc_id: $doc_id})
            WHERE s.tenant_id = $tenant_id
            RETURN s
            """,
            tenant_id="default",
        )

    def test_ddl_create_constraint_no_filter_ok(self, guard):
        """DDL CREATE CONSTRAINT : pas de filter tenant_id requis (schéma)."""
        guard.validate(
            "CREATE CONSTRAINT v5_doc_tenant_unique IF NOT EXISTS "
            "FOR (d:V5Document) REQUIRE (d.tenant_id, d.doc_id) IS UNIQUE",
            tenant_id="default",
        )

    def test_ddl_create_index_no_filter_ok(self, guard):
        guard.validate(
            "CREATE INDEX v5_section_doc IF NOT EXISTS "
            "FOR (s:V5Section) ON (s.tenant_id, s.doc_id)",
            tenant_id="default",
        )

    def test_ddl_create_fulltext_index_ok(self, guard):
        guard.validate(
            "CREATE FULLTEXT INDEX v5_section_fulltext IF NOT EXISTS "
            "FOR (s:V5Section) ON EACH [s.title, s.text_snippet]",
            tenant_id="default",
        )

    def test_ddl_drop_constraint_ok(self, guard):
        guard.validate("DROP CONSTRAINT v5_doc_tenant_unique", tenant_id="default")

    def test_fulltext_procedure_with_filter_ok(self, guard):
        """Procédure fulltext V5 avec WHERE tenant_id : valide."""
        guard.validate(
            """
            CALL db.index.fulltext.queryNodes('v5_section_fulltext', $query) YIELD node, score
            WHERE node.tenant_id = $tenant_id
            RETURN node, score
            """,
            tenant_id="default",
        )

    def test_fulltext_procedure_without_filter_fails(self, guard):
        """Procédure fulltext V5 sans WHERE tenant_id : violation."""
        with pytest.raises(TenantIsolationError):
            guard.validate(
                """
                CALL db.index.fulltext.queryNodes('v5_section_fulltext', $query) YIELD node, score
                RETURN node, score
                """,
                tenant_id="default",
            )

    def test_multiple_v5_nodes_only_one_filtered(self, guard):
        """Cas pernicieux : 2 nœuds V5 mais filter sur un seul.

        Le parser regex actuel accepte (présence d'un filter tenant_id quelque part).
        Documenté limite — atténué par composite key constraints + tests e2e.
        """
        # Acceptation tactique : le filter sur d propage via la relation
        guard.validate(
            """
            MATCH (d:V5Document {tenant_id: $tenant_id})-[:HAS_SECTION]->(s:V5Section)
            RETURN s
            """,
            tenant_id="default",
        )
