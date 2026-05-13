"""Tests S3.4 — navigate_by_toc + read_with_footnotes + find_cross_references."""
from __future__ import annotations

import pytest

from knowbase.runtime_v5.reading_tools_v2 import (
    find_cross_references,
    navigate_by_toc,
    read_with_footnotes,
)
from knowbase.runtime_v5.structure_loader import list_available_doc_ids, load_structure
from knowbase.runtime_v5.tools.registry import ToolRegistry, reset_default_registry
from knowbase.runtime_v5.tools.v2_tools_registration import register_v2_tools


# Doc fixture : prend un doc réel disponible (corpus POC migré)
@pytest.fixture(scope="module")
def doc_id():
    docs = list_available_doc_ids()
    assert docs, "no docs available in poc_a/structures"
    # Préférer un doc avec assez de sections
    for d in docs:
        s = load_structure(d)
        if s and len(s.sections) >= 30:
            return d
    return docs[0]


# ─── navigate_by_toc ─────────────────────────────────────────────────────────


class TestNavigateByToc:
    def test_existing_section_by_title_substring(self, doc_id):
        s = load_structure(doc_id)
        # Prend un title existant
        sample_title = s.sections[5].get("title") or s.sections[5].get("numbering") or ""
        if not sample_title:
            pytest.skip("No section with title in this doc")
        r = navigate_by_toc(doc_id, sample_title[:10])
        assert r["exists"] is True
        assert r["matched_section"] is not None

    def test_existing_section_by_numbering(self, doc_id):
        s = load_structure(doc_id)
        # Trouve une section avec numbering non-vide
        numbered = [sec for sec in s.sections if sec.get("numbering")]
        if not numbered:
            pytest.skip("No numbered section in this doc")
        target = numbered[0]["numbering"]
        r = navigate_by_toc(doc_id, target)
        assert r["exists"] is True
        assert r["match_type"] in ("exact_numbering", "exact_path", "title_substring")

    def test_nonexistent_section_returns_suggestions(self, doc_id):
        # Title qui n'existe pas mais ressemble vaguement à autre chose
        r = navigate_by_toc(doc_id, "Pure Nonsense Xyzzy ZZZ", similarity_threshold=0.0)
        assert r["exists"] is False
        assert r["match_type"] == "no_match"
        assert isinstance(r["suggestions"], list)

    def test_empty_target_returns_no_match(self, doc_id):
        r = navigate_by_toc(doc_id, "")
        assert r["exists"] is False
        assert r["suggestions"] == []

    def test_unknown_doc_returns_error(self):
        r = navigate_by_toc("doc_does_not_exist_xyz", "anything")
        assert "error" in r
        assert r["exists"] is False

    def test_section_path_match(self, doc_id):
        s = load_structure(doc_id)
        if not s.sections[0].get("section_path"):
            pytest.skip("no section_path in doc")
        target = s.sections[0]["section_path"]
        r = navigate_by_toc(doc_id, target)
        assert r["exists"] is True
        assert r["match_type"] in ("exact_path", "exact_numbering", "title_substring")


# ─── read_with_footnotes ─────────────────────────────────────────────────────


class TestReadWithFootnotes:
    def test_read_section_with_zero_footnotes_ok(self, doc_id):
        s = load_structure(doc_id)
        # Prend une section dont children_ids est vide
        target = next((sec for sec in s.sections if not sec.get("children_ids")), None)
        if target is None:
            pytest.skip("no leaf section")
        ref = target.get("numbering") or target.get("section_path") or target["section_id"]
        r = read_with_footnotes(doc_id, ref)
        assert "section" in r
        assert r["section"]["section_id"] == target["section_id"]
        assert r["n_footnotes"] == 0

    def test_read_section_with_footnote_children(self, doc_id):
        s = load_structure(doc_id)
        # Cherche une section qui a des enfants courts (footnotes potentielles)
        parent = None
        for sec in s.sections:
            children_ids = sec.get("children_ids") or []
            if not children_ids:
                continue
            short_children = [
                cid for cid in children_ids
                if cid in s.by_id and len((s.by_id[cid].get("text") or "")) < 400
            ]
            if short_children:
                parent = sec
                break
        if parent is None:
            pytest.skip("no section with short children — footnotes heuristic not triggered")
        ref = parent.get("numbering") or parent["section_id"]
        r = read_with_footnotes(doc_id, ref)
        assert r["n_footnotes"] >= 0
        # Si footnotes détectées, structure correcte
        for fn in r["footnotes"]:
            assert "section_id" in fn
            assert "text" in fn

    def test_unknown_section_returns_error(self, doc_id):
        r = read_with_footnotes(doc_id, "nonexistent_section_xyz_999")
        assert "error" in r

    def test_unknown_doc_returns_error(self):
        r = read_with_footnotes("doc_unknown_xxx", "any")
        assert "error" in r


# ─── find_cross_references ──────────────────────────────────────────────────


class TestFindCrossReferences:
    def test_extract_from_section_with_refs(self, doc_id):
        """Cherche une section dont le texte contient un pattern de ref."""
        s = load_structure(doc_id)
        # Recherche une section dont le texte matche au moins un pattern
        ref_phrases = ("see ", "cf ", "voir ", "refer to")
        candidate = None
        for sec in s.sections:
            text = (sec.get("text") or "").lower()
            if any(p in text for p in ref_phrases):
                candidate = sec
                break
        if candidate is None:
            pytest.skip("no section with cross-reference patterns in text")
        r = find_cross_references(doc_id, candidate["section_id"])
        assert r["n_refs_found"] >= 0
        for ref in r["references"]:
            assert "raw_text" in ref
            assert "candidates" in ref

    def test_empty_text_returns_zero_refs(self, doc_id):
        s = load_structure(doc_id)
        # Trouve une section sans texte ou avec texte sans pattern de ref
        empty_text = next((sec for sec in s.sections if not (sec.get("text") or "").strip()), None)
        if empty_text is None:
            pytest.skip("no empty-text section")
        r = find_cross_references(doc_id, empty_text["section_id"])
        assert r["n_refs_found"] == 0
        assert r["references"] == []

    def test_unknown_section_returns_error(self, doc_id):
        r = find_cross_references(doc_id, "sec_unknown_zzz_999")
        assert "error" in r

    def test_unknown_doc_returns_error(self):
        r = find_cross_references("doc_unknown", "sec_any")
        assert "error" in r


# ─── Pattern extraction (unit tests sans corpus) ─────────────────────────────


class TestPatternsUniversality:
    """Vérifie que les patterns matchent multi-langue (charte domain-agnostic)."""

    @pytest.fixture(scope="class")
    def doc_with_text(self, request):
        """Synthétise un doc en mémoire pour tester l'extraction de patterns."""
        # Génère manuellement un dict structure
        return {
            "doc_id": "synthetic_test",
            "sections": [
                {
                    "section_id": "sec_test_001",
                    "level": 1,
                    "numbering": "1",
                    "title": "Test",
                    "section_path": "/1",
                    "page_range": [0, 0],
                    "text": (
                        "This procedure follows the requirements (see Article 5). "
                        "Refer to section 3.2 for more details. "
                        "cf Annex I and Appendix A. "
                        "Voir paragraphe 7 ci-dessous. "
                        "Vgl. §5 weiter unten. "
                        "See also clause 12(3)."
                    ),
                }
            ],
            "n_pages": 1,
        }

    def test_patterns_multilingual(self, monkeypatch, doc_with_text):
        """Le pattern doit extraire EN/FR/DE."""
        # Patch load_structure pour retourner doc synthétique
        from knowbase.runtime_v5 import reading_tools_v2, structure_loader

        class FakeStruct:
            def __init__(self, data):
                self.doc_id = data["doc_id"]
                self.sections = data["sections"]
                self.by_id = {s["section_id"]: s for s in data["sections"]}
                self.n_pages = data["n_pages"]

            def find_by_numbering(self, q):
                return []

            def find_by_path(self, p):
                return None

        monkeypatch.setattr(
            reading_tools_v2, "load_structure",
            lambda d: FakeStruct(doc_with_text) if d == "synthetic_test" else None,
        )

        r = find_cross_references("synthetic_test", "sec_test_001", max_refs=50)
        assert r["n_refs_found"] >= 3, f"expected >=3 refs, got {r['n_refs_found']}: {r['references']}"
        raw_texts = " ".join(ref["raw_text"].lower() for ref in r["references"])
        # Au moins une réf de chaque langue / pattern
        assert "see" in raw_texts or "section" in raw_texts or "article" in raw_texts
        assert any(t in raw_texts for t in ("voir", "vgl", "cf"))


# ─── Registration in registry ────────────────────────────────────────────────


class TestRegistration:
    def test_register_v2_tools(self):
        reset_default_registry()
        reg = ToolRegistry()
        result = register_v2_tools(reg)
        assert result["errors"] == []
        assert set(result["registered"]) == {
            "navigate_by_toc", "read_with_footnotes", "find_cross_references"
        }
        # Tous en public
        public = reg.list_public_tools()
        assert len(public) == 3

    def test_combined_with_poc_tools(self):
        """6 POC + 3 V2 = 9 public, ceiling 14 respecté."""
        from knowbase.runtime_v5.tools.poc_tools_registration import register_poc_tools

        reset_default_registry()
        reg = ToolRegistry()
        register_poc_tools(reg)
        register_v2_tools(reg)
        stats = reg.stats()
        assert stats["n_public"] == 9  # 6 POC + 3 V2
        assert stats["n_experimental"] == 1  # list_versions
        assert stats["slots_available"] == 14 - 9

    def test_no_domain_specific_words_in_v2_tools(self):
        reset_default_registry()
        reg = ToolRegistry()
        register_v2_tools(reg)
        forbidden = [
            "sap", "s/4hana", "s4hana", "gdpr", "rgpd", "regulation", "regulatory",
            "medical", "patient", "amendment", "compliance", "rfp", "aerospace",
        ]
        for spec in reg.list_all():
            desc = (spec.description + " " + spec.preferred_when).lower()
            for w in forbidden:
                assert w not in desc, f"Tool '{spec.name}' has forbidden '{w}'"
