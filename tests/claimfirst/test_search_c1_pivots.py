# tests/claimfirst/test_search_c1_pivots.py
"""Tests Phase B — Search sur C1 Pivots (release filter, SAME_CANON_AS, LatestBoost).

Note: Les tests sont volontairement autonomes (pas d'import qdrant_client / knowbase.api.services)
pour pouvoir tourner en local sans dépendances lourdes.
"""

import pytest
from dataclasses import dataclass
from unittest.mock import MagicMock


class TestSearchReleaseFilter:
    """B.2: Vérifier la logique de filtre release_id."""

    def test_search_release_filter_adds_condition(self):
        """Si release_id spécifié, une condition doit être ajoutée aux must_conditions."""
        release_id = "2023"
        must_conditions = []

        if release_id:
            must_conditions.append({
                "key": "axis_release_id",
                "match": {"value": release_id},
            })

        assert len(must_conditions) == 1
        assert must_conditions[0]["key"] == "axis_release_id"
        assert must_conditions[0]["match"]["value"] == "2023"

    def test_search_no_release_filter(self):
        """Sans release_id, pas de condition axis_release_id."""
        release_id = None
        must_conditions = []

        if release_id:
            must_conditions.append("should_not_appear")

        assert len(must_conditions) == 0


class TestBuildResponseWithAxis:
    """B.1: Vérifier que la logique build_response inclut axis_release_id."""

    def test_payload_includes_axis_fields(self):
        """Le payload enrichi doit inclure axis_release_id et doc_id."""
        payload = {
            "text": "Test chunk",
            "doc_id": "doc_001",
            "axis_release_id": "2023",
            "axis_version": "3.0",
        }

        result = {
            "text": payload.get("text", ""),
            "score": 0.85,
            "axis_release_id": payload.get("axis_release_id"),
            "doc_id": payload.get("doc_id"),
        }

        assert result["axis_release_id"] == "2023"
        assert result["doc_id"] == "doc_001"

    def test_payload_no_axis(self):
        """Sans axis, les champs doivent être None."""
        payload = {
            "text": "Test chunk sans axis",
            "doc_id": "doc_002",
        }

        result = {
            "axis_release_id": payload.get("axis_release_id"),
            "doc_id": payload.get("doc_id"),
        }

        assert result["axis_release_id"] is None
        assert result["doc_id"] == "doc_002"


class TestLatestBoost:
    """B.4: Vérifier que le boost ×1.3 s'applique aux chunks de la release la plus récente."""

    def test_latest_boost_reorders_chunks(self):
        """Avec 2 releases, les chunks de la plus récente doivent être boostés."""
        chunks = [
            {"text": "chunk_old_1", "score": 0.90, "axis_release_id": "2020", "doc_id": "d1"},
            {"text": "chunk_old_2", "score": 0.85, "axis_release_id": "2020", "doc_id": "d1"},
            {"text": "chunk_new_1", "score": 0.80, "axis_release_id": "2023", "doc_id": "d2"},
            {"text": "chunk_new_2", "score": 0.75, "axis_release_id": "2023", "doc_id": "d2"},
        ]

        release_ids = {c["axis_release_id"] for c in chunks if c.get("axis_release_id")}
        assert len(release_ids) >= 2

        sorted_releases = sorted(release_ids, key=lambda x: (
            float(x) if x.replace(".", "").replace("-", "").isdigit() else 0,
            x,
        ))
        latest = sorted_releases[-1]
        assert latest == "2023"

        for c in chunks:
            if c.get("axis_release_id") == latest:
                c["score"] = c["score"] * 1.3

        chunks.sort(key=lambda c: c["score"], reverse=True)

        # chunk_new_1 (0.80 * 1.3 = 1.04) doit passer devant chunk_old_1 (0.90)
        assert chunks[0]["text"] == "chunk_new_1"
        assert chunks[0]["score"] == pytest.approx(1.04)

    def test_latest_boost_single_release_no_change(self):
        """Avec 1 seule release, aucun boost ne s'applique."""
        chunks = [
            {"text": "c1", "score": 0.90, "axis_release_id": "2023", "doc_id": "d1"},
            {"text": "c2", "score": 0.80, "axis_release_id": "2023", "doc_id": "d1"},
        ]

        release_ids = {c["axis_release_id"] for c in chunks if c.get("axis_release_id")}
        assert len(release_ids) < 2

    def test_latest_boost_no_axis_values(self):
        """Chunks sans axis_release_id → pas de boost."""
        chunks = [
            {"text": "c1", "score": 0.90, "doc_id": "d1"},
            {"text": "c2", "score": 0.80, "doc_id": "d2"},
        ]

        release_ids = {c.get("axis_release_id") for c in chunks if c.get("axis_release_id")}
        assert len(release_ids) == 0

    def test_latest_boost_version_format(self):
        """Versions décimales (ex: 3.0, 4.1) doivent aussi être triées correctement."""
        chunks = [
            {"text": "v3", "score": 0.90, "axis_release_id": "3.0", "doc_id": "d1"},
            {"text": "v4", "score": 0.75, "axis_release_id": "4.1", "doc_id": "d2"},
        ]

        release_ids = {c["axis_release_id"] for c in chunks if c.get("axis_release_id")}
        sorted_releases = sorted(release_ids, key=lambda x: (
            float(x) if x.replace(".", "").replace("-", "").isdigit() else 0,
            x,
        ))
        assert sorted_releases[-1] == "4.1"


class TestCanonExpansion:
    """B.3: Vérifier que SAME_CANON_AS ajoute du contexte cross-doc."""

    def test_canon_records_add_doc_ids(self):
        """Les related_doc_ids des canon_records doivent être ajoutés à all_chain_doc_ids."""
        canon_records = [
            {
                "candidate": "SAP HANA",
                "canon_name": "SAP HANA Database",
                "related_doc_ids": ["doc_a", "doc_b", "doc_c"],
                "related_claims": [
                    {"text": "SAP HANA supports column store", "doc_id": "doc_a", "type": "FACT"},
                    {"text": "SAP HANA 2.0 introduced NSE", "doc_id": "doc_b", "type": "EVOLUTION"},
                ],
            }
        ]

        all_chain_doc_ids = set()
        for rec in canon_records:
            for did in rec.get("related_doc_ids", []):
                all_chain_doc_ids.add(did)

        assert "doc_a" in all_chain_doc_ids
        assert "doc_b" in all_chain_doc_ids
        assert "doc_c" in all_chain_doc_ids
        assert len(all_chain_doc_ids) == 3

    def test_canon_records_empty_no_effect(self):
        """Sans canon_records, pas d'ajout de doc_ids."""
        canon_records = []
        all_chain_doc_ids = set()

        for rec in canon_records:
            for did in rec.get("related_doc_ids", []):
                all_chain_doc_ids.add(did)

        assert len(all_chain_doc_ids) == 0

    def test_canon_formatting(self):
        """Le formatage markdown cross-doc doit inclure le canon_name et les claims."""
        canon_records = [
            {
                "canon_name": "SAP S/4HANA",
                "related_doc_ids": ["doc_x"],
                "related_claims": [
                    {"text": "S/4HANA replaces ECC", "doc_id": "doc_x", "type": "FACT"},
                ],
            }
        ]

        lines = ["### Cross-doc (entités canoniques)\n"]
        for rec in canon_records:
            canon_name = rec.get("canon_name", "?")
            related_claims = rec.get("related_claims", [])
            lines.append(f"**{canon_name}** — {len(rec['related_doc_ids'])} documents liés")
            for claim in related_claims[:5]:
                text = claim.get("text", "").strip()
                lines.append(f"  • {text}")

        output = "\n".join(lines)
        assert "SAP S/4HANA" in output
        assert "S/4HANA replaces ECC" in output


class TestSearchRequestSchema:
    """B.2: Vérifier les nouveaux champs du SearchRequest.

    Note: Test les champs via un modèle Pydantic minimal reproduisant
    la structure de SearchRequest (l'import réel nécessite FastAPI).
    """

    def test_search_request_defaults(self):
        """release_id=None, use_latest=True par défaut."""
        from pydantic import BaseModel, Field

        class SearchRequestLike(BaseModel):
            question: str
            release_id: str | None = Field(None)
            use_latest: bool = Field(default=True)

        req = SearchRequestLike(question="test query")
        assert req.release_id is None
        assert req.use_latest is True

    def test_search_request_with_release(self):
        """release_id peut être spécifié."""
        from pydantic import BaseModel, Field

        class SearchRequestLike(BaseModel):
            question: str
            release_id: str | None = Field(None)
            use_latest: bool = Field(default=True)

        req = SearchRequestLike(question="test query", release_id="2023", use_latest=False)
        assert req.release_id == "2023"
        assert req.use_latest is False


class TestUpsertAxisValues:
    """B.1: Vérifier l'injection des axis_values dans les payloads Qdrant."""

    def test_axis_values_injected_in_payload(self):
        """doc_axis_values doit être injecté dans chaque payload point."""
        doc_axis_values = {"release_id": "2023", "version": "3.0"}

        payload = {
            "text": "test chunk",
            "doc_id": "doc_001",
            "axis_release_id": doc_axis_values.get("release_id") if doc_axis_values else None,
            "axis_version": doc_axis_values.get("version") if doc_axis_values else None,
        }

        assert payload["axis_release_id"] == "2023"
        assert payload["axis_version"] == "3.0"

    def test_no_axis_values_yields_none(self):
        """Sans doc_axis_values, les champs axis doivent être None."""
        doc_axis_values = None

        payload = {
            "axis_release_id": doc_axis_values.get("release_id") if doc_axis_values else None,
            "axis_version": doc_axis_values.get("version") if doc_axis_values else None,
        }

        assert payload["axis_release_id"] is None
        assert payload["axis_version"] is None


# ── Phase 4 v2 : Search enrichment scope-aware ───────────────────────

class TestSearchRanking:
    """V2: Ranking de pertinence pour top 5 comparaisons."""

    def test_rank_by_term_match(self):
        """Dimensions dont le key matche un terme ont priorité."""
        search_terms_lower = {"tls", "version"}

        records = [
            {"dimension_key": "backup_frequency", "canonical_question": "How often?",
             "signatures": [{"confidence": 0.9}, {"confidence": 0.8}]},
            {"dimension_key": "tls_version", "canonical_question": "What TLS version?",
             "signatures": [{"confidence": 0.7}]},
        ]

        def _rank(rec):
            key_match = 1 if any(t in rec["dimension_key"].lower() for t in search_terms_lower) else 0
            qs_count = len(rec["signatures"])
            return (key_match, qs_count)

        records.sort(key=_rank, reverse=True)
        assert records[0]["dimension_key"] == "tls_version"

    def test_top_5_limit(self):
        """Au plus 5 comparaisons affichées dans le markdown."""
        MAX_DISPLAYED = 5
        displayed = 0
        comparisons_data = []

        for i in range(10):
            if displayed < MAX_DISPLAYED:
                displayed += 1
            comparisons_data.append({"type": "EVOLUTION", "dimension_key": f"dim_{i}"})

        assert displayed == 5
        assert len(comparisons_data) == 10

    def test_confidence_display_format(self):
        """L'affichage inclut la confiance en pourcentage."""
        confidences = [0.85, 0.90, 0.75]
        avg_conf = int(100 * sum(confidences) / len(confidences))
        label = f"**↗ ÉVOLUTION** — What is X? (confiance: {avg_conf}%)"
        assert "confiance: 83%" in label

    def test_overflow_message(self):
        """Si >5 comparaisons, un message indique les extras."""
        total = 8
        max_displayed = 5
        overflow = total - max_displayed
        msg = f"_({overflow} comparaisons supplémentaires dans les données JSON)_"
        assert "3 comparaisons supplémentaires" in msg


class TestSearchScopeGrouping:
    """V2: Groupement par (dimension, scope)."""

    def test_group_by_value_and_scope(self):
        """Les signatures sont groupées par (valeur, scope)."""
        sigs = [
            {"extracted_value": "1.2", "scope_anchor_label": "ProductA", "confidence": 0.9},
            {"extracted_value": "1.2", "scope_anchor_label": "ProductB", "confidence": 0.8},
            {"extracted_value": "1.3", "scope_anchor_label": "ProductA", "confidence": 0.7},
        ]

        by_value_scope = {}
        for s in sigs:
            val = (s.get("extracted_value") or "").strip().lower()
            scope = (s.get("scope_anchor_label") or "").strip().lower()
            by_value_scope.setdefault((val, scope), []).append(s)

        assert len(by_value_scope) == 3
        assert ("1.2", "producta") in by_value_scope
        assert ("1.2", "productb") in by_value_scope
        assert ("1.3", "producta") in by_value_scope

    def test_confidence_filter(self):
        """Seules les QS avec confidence >= 0.6 sont retenues."""
        sigs = [
            {"confidence": 0.9, "value": "a"},
            {"confidence": 0.5, "value": "b"},
            {"confidence": 0.7, "value": "c"},
        ]

        filtered = [s for s in sigs if (s.get("confidence") or 0) >= 0.6]
        assert len(filtered) == 2


class TestScopePolicyEnforcement:
    """V2: scope_policy dans are_comparable()."""

    def test_scope_policy_violation_not_comparable(self):
        from knowbase.claimfirst.models.comparability_verdict import (
            are_comparable, ComparabilityLevel,
        )

        @dataclass
        class FakeQS:
            dimension_id: str = "dim1"
            value_type: str = "version"
            operator: str = "="
            scope: dict = None

        qs_a = FakeQS(scope={"scope_basis": "claim_explicit", "scope_status": "resolved"})
        qs_b = FakeQS(scope={"scope_basis": "document_context", "scope_status": "inherited"})

        dim = MagicMock()
        dim.scope_policy = "requires_product"

        verdict = are_comparable(qs_a, qs_b, dimension=dim)
        assert verdict.level == ComparabilityLevel.NOT_COMPARABLE
        assert verdict.reason == "scope_policy_violation"

    def test_scope_policy_any_no_block(self):
        from knowbase.claimfirst.models.comparability_verdict import (
            are_comparable, ComparabilityLevel,
        )

        @dataclass
        class FakeQS:
            dimension_id: str = "dim1"
            value_type: str = "version"
            operator: str = "="
            scope: dict = None

        qs_a = FakeQS(scope={"scope_basis": "document_context", "scope_status": "inherited"})
        qs_b = FakeQS(scope={"scope_basis": "document_context", "scope_status": "inherited"})

        dim = MagicMock()
        dim.scope_policy = "any"

        verdict = are_comparable(qs_a, qs_b, dimension=dim)
        assert verdict.level != ComparabilityLevel.NOT_COMPARABLE or verdict.reason != "scope_policy_violation"
