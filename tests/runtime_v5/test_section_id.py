"""Tests stable section_id + alias map (CH-52.3.1)."""
from __future__ import annotations

import pytest

from knowbase.runtime_v5.section_id import (
    SectionIdAliasMap,
    compute_section_id,
    normalize_title,
)


# ─── normalize_title ─────────────────────────────────────────────────────────

class TestNormalizeTitle:
    def test_lowercase(self):
        assert normalize_title("Upgrade Guide") == "upgrade guide"

    def test_strip_punctuation(self):
        assert normalize_title("Upgrade Guide: SAP S/4HANA") == "upgrade guide sap s 4hana"

    def test_collapse_whitespace(self):
        assert normalize_title("  Upgrade   Guide  ") == "upgrade guide"

    def test_unicode_nfkc(self):
        # Accent composé vs décomposé doivent donner le même résultat
        composed = "Procédure"  # é = U+00E9
        decomposed = "Procédure"  # e + combining acute accent
        assert normalize_title(composed) == normalize_title(decomposed)

    def test_empty(self):
        assert normalize_title("") == ""
        assert normalize_title(None) == ""

    def test_only_punct(self):
        assert normalize_title("!!!---///") == ""

    def test_multilingual(self):
        # Test multi-langue (charte domain-agnostic)
        assert normalize_title("Übersicht: Migration") == "übersicht migration"
        assert normalize_title("概要") == "概要"

    def test_numbering_in_title_preserved(self):
        # "3.1 Setup" → mots normalisés mais nombres préservés
        assert normalize_title("3.1 Setup") == "3 1 setup"


# ─── compute_section_id ──────────────────────────────────────────────────────

class TestComputeSectionId:
    def test_deterministic(self):
        a = compute_section_id("doc_x", "/3", "Setup", 4)
        b = compute_section_id("doc_x", "/3", "Setup", 4)
        assert a == b

    def test_format(self):
        sid = compute_section_id("doc_x", "/3", "Setup", 4)
        assert sid.startswith("sec_")
        assert len(sid) == 4 + 24  # "sec_" + 24 hex chars

    def test_different_doc_id_different_section_id(self):
        a = compute_section_id("doc_A", "/3", "Setup", 4)
        b = compute_section_id("doc_B", "/3", "Setup", 4)
        assert a != b

    def test_different_page_different_section_id(self):
        a = compute_section_id("doc_x", "/3", "Setup", 4)
        b = compute_section_id("doc_x", "/3", "Setup", 5)
        assert a != b

    def test_different_parent_path_different_section_id(self):
        a = compute_section_id("doc_x", "/3", "Setup", 4)
        b = compute_section_id("doc_x", "/4", "Setup", 4)
        assert a != b

    def test_normalization_invariance(self):
        """Title 'Setup' vs 'SETUP' vs ' Setup. ' → même ID (normalisation)."""
        a = compute_section_id("doc_x", "/3", "Setup", 4)
        b = compute_section_id("doc_x", "/3", "SETUP", 4)
        c = compute_section_id("doc_x", "/3", " Setup. ", 4)
        assert a == b == c

    def test_no_delimiter_collision(self):
        """Garantir que les composants ne se confondent pas si on injecte des chars spéciaux."""
        # doc_id="A|B" parent_path="C" title="" page=4
        # vs
        # doc_id="A"   parent_path="B|C" title="" page=4
        # Ces 2 tuples ne doivent PAS produire le même ID (sécurité par séparateur \x1f)
        a = compute_section_id("A|B", "C", "title", 4)
        b = compute_section_id("A", "B|C", "title", 4)
        assert a != b

    def test_empty_parent_path(self):
        sid = compute_section_id("doc_x", "", "Root", 0)
        assert sid.startswith("sec_")

    def test_page_zero(self):
        sid = compute_section_id("doc_x", "/", "Cover", 0)
        assert sid.startswith("sec_")

    def test_no_doc_id_raises(self):
        with pytest.raises(ValueError):
            compute_section_id("", "/3", "Setup", 4)

    def test_title_with_punctuation_collapses(self):
        # "1.1 Get Started" et "1.1: Get Started" et "1.1, Get Started" → même titre normalisé
        a = compute_section_id("doc_x", "/", "1.1 Get Started", 0)
        b = compute_section_id("doc_x", "/", "1.1: Get Started", 0)
        c = compute_section_id("doc_x", "/", "1.1, Get Started", 0)
        assert a == b == c

    def test_realistic_docling_section(self):
        """Cas concret repris du JSON Docling page-fallback."""
        sid = compute_section_id(
            doc_id="003_SAP_S4HANA_2023_Upgrade_Guide_299d71e9",
            parent_path="/Page 5",
            title="2 Getting Started",
            page_start=4,
        )
        assert sid.startswith("sec_")
        # Idempotence sur réingestion
        sid2 = compute_section_id(
            doc_id="003_SAP_S4HANA_2023_Upgrade_Guide_299d71e9",
            parent_path="/Page 5",
            title="2 Getting Started",
            page_start=4,
        )
        assert sid == sid2


# ─── SectionIdAliasMap (e2e Neo4j) ───────────────────────────────────────────

@pytest.fixture(scope="module")
def alias_map():
    """SectionIdAliasMap partagé pour le module + setup_schema."""
    from knowbase.common.clients.neo4j_client import get_neo4j_client
    m = SectionIdAliasMap(get_neo4j_client())
    m.setup_schema()
    yield m
    # cleanup test data
    m.client.execute_write(
        "MATCH (a:V5SectionAlias) WHERE a.tenant_id STARTS WITH 'test_alias_' "
        "DELETE a"
    )


class TestSectionIdAliasMap:
    def test_setup_schema_idempotent(self, alias_map):
        r1 = alias_map.setup_schema()
        r2 = alias_map.setup_schema()
        assert r1["applied"] == r1["total"]
        assert r2["applied"] == r2["total"]
        assert r1["errors"] == [] and r2["errors"] == []

    def test_add_and_resolve(self, alias_map):
        tenant = "test_alias_basic"
        r = alias_map.add(tenant, "sec_old1", "sec_new1", reason="test")
        assert "alias_id" in r
        resolved = alias_map.resolve(tenant, "sec_old1")
        assert resolved == "sec_new1"

    def test_resolve_no_alias_returns_input(self, alias_map):
        assert alias_map.resolve("test_alias_basic", "sec_no_alias_xxx") == "sec_no_alias_xxx"

    def test_chain_resolution(self, alias_map):
        tenant = "test_alias_chain"
        # sec_v1 → sec_v2 → sec_v3
        alias_map.add(tenant, "sec_v1", "sec_v2")
        alias_map.add(tenant, "sec_v2", "sec_v3")
        assert alias_map.resolve(tenant, "sec_v1") == "sec_v3"

    def test_cycle_detection(self, alias_map):
        tenant = "test_alias_cycle"
        # Cycle artificiel : sec_a → sec_b → sec_a (mauvaise admin)
        alias_map.add(tenant, "sec_a", "sec_b")
        alias_map.add(tenant, "sec_b", "sec_a")
        # Doit retourner soit sec_a soit sec_b sans boucler
        resolved = alias_map.resolve(tenant, "sec_a")
        assert resolved in ("sec_a", "sec_b")

    def test_same_old_and_new_raises(self, alias_map):
        with pytest.raises(ValueError):
            alias_map.add("test_alias_basic", "sec_x", "sec_x")

    def test_idempotent_add(self, alias_map):
        tenant = "test_alias_idempotent"
        a = alias_map.add(tenant, "sec_old", "sec_new")
        b = alias_map.add(tenant, "sec_old", "sec_new", reason="re-add")
        assert a["alias_id"] == b["alias_id"]

    def test_update_target(self, alias_map):
        tenant = "test_alias_update"
        alias_map.add(tenant, "sec_old", "sec_v1")
        alias_map.add(tenant, "sec_old", "sec_v2", reason="corrected")
        assert alias_map.resolve(tenant, "sec_old") == "sec_v2"

    def test_get_aliases(self, alias_map):
        tenant = "test_alias_get"
        alias_map.add(tenant, "sec_old1", "sec_current")
        alias_map.add(tenant, "sec_old2", "sec_current")
        aliases = alias_map.get_aliases(tenant, "sec_current")
        old_ids = {a["old_section_id"] for a in aliases}
        assert old_ids == {"sec_old1", "sec_old2"}

    def test_tenant_isolation(self, alias_map):
        """Alias d'un tenant ne contamine pas un autre tenant."""
        alias_map.add("test_alias_iso_a", "sec_X", "sec_Y_for_a")
        alias_map.add("test_alias_iso_b", "sec_X", "sec_Y_for_b")
        assert alias_map.resolve("test_alias_iso_a", "sec_X") == "sec_Y_for_a"
        assert alias_map.resolve("test_alias_iso_b", "sec_X") == "sec_Y_for_b"

    def test_remove(self, alias_map):
        tenant = "test_alias_remove"
        alias_map.add(tenant, "sec_old", "sec_new")
        assert alias_map.resolve(tenant, "sec_old") == "sec_new"
        deleted = alias_map.remove(tenant, "sec_old")
        assert deleted is True
        assert alias_map.resolve(tenant, "sec_old") == "sec_old"  # back to input

    def test_remove_nonexistent_returns_false(self, alias_map):
        deleted = alias_map.remove("test_alias_remove", "sec_inexistant_xyz")
        assert deleted is False
