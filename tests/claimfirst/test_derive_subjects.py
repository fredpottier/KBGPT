# tests/claimfirst/test_derive_subjects.py
"""
Tests pour Phase 2.8 — _derive_subjects_from_entities().

Stratégie :
- Pré-mock des dépendances lourdes dans sys.modules au chargement du fichier
- Puis import normal de l'orchestrator
- Contrôle du LLM via le mock module déjà injecté
"""

import json
import sys
import uuid
import pytest
from collections import Counter
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Mock des modules lourds AVANT tout import orchestrator
# ---------------------------------------------------------------------------

def _make_mock_package(name: str) -> MagicMock:
    mock = MagicMock()
    mock.__path__ = []
    mock.__file__ = f"<mock {name}>"
    mock.__name__ = name
    mock.__package__ = name
    mock.__loader__ = None
    mock.__spec__ = None
    return mock


_MOCK_PACKAGES = [
    "neo4j", "neo4j.exceptions",
    "graphiti_core", "graphiti_core.nodes", "graphiti_core.edges",
    "sqlalchemy", "sqlalchemy.orm", "sqlalchemy.sql",
    "sqlalchemy.ext", "sqlalchemy.ext.declarative", "sqlalchemy.pool",
    "sqlalchemy.engine",
    "knowbase.db", "knowbase.db.base", "knowbase.db.models",
    "openai", "anthropic",
    "redis", "rq",
    "fastapi", "fastapi.security",
    "qdrant_client", "qdrant_client.models",
]

for _pkg in _MOCK_PACKAGES:
    if _pkg not in sys.modules:
        sys.modules[_pkg] = _make_mock_package(_pkg)

# Attributs attendus par certains imports
sys.modules["knowbase.db.base"].SessionLocal = MagicMock()
sys.modules["knowbase.db.base"].Base = MagicMock()
sys.modules["knowbase.db.models"].DomainContext = MagicMock()

# Mock LLM module — on contrôle get_llm_router et TaskType
_mock_llm_module = sys.modules.get("knowbase.common.llm_router")
if _mock_llm_module is None or not hasattr(_mock_llm_module, "_test_mock"):
    _mock_llm_module = _make_mock_package("knowbase.common.llm_router")
    _mock_llm_module._test_mock = True
    _mock_llm_module.TaskType = MagicMock()
    _mock_llm_module.TaskType.METADATA_EXTRACTION = "metadata_extraction"
    sys.modules["knowbase.common.llm_router"] = _mock_llm_module


# ---------------------------------------------------------------------------
# Imports réels (après mocks)
# ---------------------------------------------------------------------------

from knowbase.claimfirst.models.claim import Claim, ClaimType
from knowbase.claimfirst.models.entity import Entity, EntityType
from knowbase.claimfirst.models.subject_anchor import SubjectAnchor
from knowbase.claimfirst.models.document_context import DocumentContext, ResolutionStatus
from knowbase.claimfirst.orchestrator import ClaimFirstOrchestrator
from knowbase.claimfirst.resolution.subject_resolver import ResolverResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entity(name, entity_id, entity_type=EntityType.CONCEPT):
    return Entity(
        entity_id=entity_id, tenant_id="default", name=name,
        entity_type=entity_type, source_doc_ids=["doc_028"],
    )


def _make_claim(text, claim_id=None):
    if claim_id is None:
        claim_id = f"claim_{uuid.uuid4().hex[:8]}"
    return Claim(
        claim_id=claim_id, tenant_id="default", doc_id="doc_028",
        text=text, claim_type=ClaimType.FACTUAL,
        verbatim_quote=text if len(text) >= 10 else text + " (padding)",
        passage_id=f"pass_{uuid.uuid4().hex[:8]}", confidence=0.8,
    )


def _make_anchor(name, subject_id=None):
    if subject_id is None:
        subject_id = f"subject_{name.lower().replace(' ', '_')[:12]}"
    return SubjectAnchor(
        subject_id=subject_id, tenant_id="default",
        canonical_name=name, aliases_explicit=[name],
        source_doc_ids=["doc_028"],
    )


def _make_doc_context(subject_ids=None, primary_subject="SAP S/4HANA Security Guide"):
    return DocumentContext(
        doc_id="doc_028", tenant_id="default",
        primary_subject=primary_subject,
        subject_ids=list(subject_ids or []),
    )


def _build_orchestrator():
    orch = ClaimFirstOrchestrator.__new__(ClaimFirstOrchestrator)
    orch._subject_anchors = []
    orch.tenant_id = "default"
    orch.subject_resolver = MagicMock()
    return orch


def _set_llm_response(response_json):
    """Configure le mock LLM pour retourner une réponse JSON."""
    mock_router = MagicMock()
    mock_router.complete.return_value = json.dumps(response_json)
    _mock_llm_module.get_llm_router.return_value = mock_router
    return mock_router


def _set_llm_error(error):
    """Configure le mock LLM pour lever une exception."""
    mock_router = MagicMock()
    mock_router.complete.side_effect = error
    _mock_llm_module.get_llm_router.return_value = mock_router
    return mock_router


def _make_realistic_scenario(total_claims=200):
    """6 entités avec coverages variées : 30, 20, 16, 14, 10, 3 claims."""
    claims = [
        _make_claim(f"Claim text number {i} with enough length", claim_id=f"c_{i:03d}")
        for i in range(total_claims)
    ]
    entities = [
        _make_entity("SAP S/4HANA", "ent_s4hana", EntityType.PRODUCT),
        _make_entity("Personal Data", "ent_pdata", EntityType.CONCEPT),
        _make_entity("ABAP", "ent_abap", EntityType.CONCEPT),
        _make_entity("role", "ent_role", EntityType.ACTOR),
        _make_entity("Authorization Concept", "ent_authconcept", EntityType.CONCEPT),
        _make_entity("Minor Entity", "ent_minor", EntityType.CONCEPT),
    ]
    claim_entity_map = {}
    for i in range(total_claims):
        cid = f"c_{i:03d}"
        eids = []
        if i < 30:
            eids.append("ent_s4hana")
        if i < 20:
            eids.append("ent_pdata")
        if i < 16:
            eids.append("ent_abap")
        if i < 14:
            eids.append("ent_role")
        if i < 10:
            eids.append("ent_authconcept")
        if i < 3:
            eids.append("ent_minor")
        if eids:
            claim_entity_map[cid] = eids
    return claims, entities, claim_entity_map


# ===================================================================
# Tests Étape A — Filtrage coverage (logique pure)
# ===================================================================

class TestCoverageFilter:
    MIN_CLAIMS = 8
    MIN_COV = 0.03

    def _run_filter(self, claims, entities, cem):
        counts = Counter()
        for eids in cem.values():
            for eid in eids:
                counts[eid] += 1
        by_id = {e.entity_id: e for e in entities}
        total = len(claims)
        cands = []
        for eid, cnt in counts.items():
            ent = by_id.get(eid)
            if not ent:
                continue
            cov = cnt / total if total > 0 else 0
            if cnt >= self.MIN_CLAIMS and cov >= self.MIN_COV:
                cands.append((ent, cnt, cov))
        cands.sort(key=lambda x: x[1], reverse=True)
        return cands

    def test_keeps_high_count_entities(self):
        claims, entities, cem = _make_realistic_scenario(200)
        names = {c[0].name for c in self._run_filter(claims, entities, cem)}
        assert "SAP S/4HANA" in names
        assert "Personal Data" in names
        assert "ABAP" in names
        assert "role" in names
        assert "Authorization Concept" in names

    def test_removes_low_count_entities(self):
        claims, entities, cem = _make_realistic_scenario(200)
        names = {c[0].name for c in self._run_filter(claims, entities, cem)}
        assert "Minor Entity" not in names

    def test_sorted_by_count_desc(self):
        claims, entities, cem = _make_realistic_scenario(200)
        counts = [c[1] for c in self._run_filter(claims, entities, cem)]
        assert counts == sorted(counts, reverse=True)

    def test_empty_on_small_doc(self):
        claims = [_make_claim(f"Short claim {i}", claim_id=f"c_{i}") for i in range(5)]
        entities = [_make_entity("Minor", "ent_m", EntityType.OTHER)]
        cem = {"c_0": ["ent_m"], "c_1": ["ent_m"]}
        assert len(self._run_filter(claims, entities, cem)) == 0

    def test_removes_low_percentage_entities(self):
        """>=8 claims mais <3% coverage → exclu."""
        claims = [_make_claim(f"Claim {i} enough text", claim_id=f"c_{i}") for i in range(500)]
        entities = [_make_entity("Rare", "ent_r")]
        cem = {f"c_{i}": ["ent_r"] for i in range(10)}  # 10/500 = 2%
        assert len(self._run_filter(claims, entities, cem)) == 0


# ===================================================================
# Tests Étape B — Evidence pack diversifié
# ===================================================================

class TestEvidencePack:
    @staticmethod
    def _pick(claim_ids, claim_by_id, n=3):
        valid = [cid for cid in claim_ids if cid in claim_by_id]
        if len(valid) <= n:
            return [claim_by_id[cid] for cid in valid]
        step = max(1, len(valid) // n)
        return [claim_by_id[valid[i * step]] for i in range(n)]

    def test_small_list(self):
        data = {"c_0": "Text A", "c_1": "Text B"}
        assert len(self._pick(["c_0", "c_1"], data)) == 2

    def test_large_list_diversified(self):
        data = {f"c_{i}": f"Text {i}" for i in range(30)}
        result = self._pick(list(data.keys()), data)
        assert len(result) == 3
        assert len(set(result)) == 3


# ===================================================================
# Tests Étapes C/D/E — LLM + Resolver + DocContext
# ===================================================================

class TestLLMClassification:
    def test_subject_and_generic(self):
        """SUBJECT gardés, TOO_GENERIC/NOISE exclus."""
        claims, entities, cem = _make_realistic_scenario(200)
        orch = _build_orchestrator()
        doc_context = _make_doc_context(subject_ids=["old_subject_1"])

        _set_llm_response({"decisions": [
            {"index": 1, "verdict": "SUBJECT", "reason": "central product"},
            {"index": 2, "verdict": "SUBJECT", "reason": "privacy concept"},
            {"index": 3, "verdict": "SUBJECT", "reason": "programming language"},
            {"index": 4, "verdict": "TOO_GENERIC", "reason": "too broad"},
            {"index": 5, "verdict": "NOISE", "reason": "not meaningful"},
        ]})

        orch.subject_resolver.resolve_batch.return_value = [
            ResolverResult(anchor=_make_anchor("SAP S/4HANA", "subj_s4"), status=ResolutionStatus.RESOLVED, confidence=0.95, match_type="new"),
            ResolverResult(anchor=_make_anchor("Personal Data", "subj_pd"), status=ResolutionStatus.RESOLVED, confidence=0.95, match_type="new"),
            ResolverResult(anchor=_make_anchor("ABAP", "subj_abap"), status=ResolutionStatus.RESOLVED, confidence=0.95, match_type="new"),
        ]

        anchors, ctx = orch._derive_subjects_from_entities(
            entities=entities, claim_entity_map=cem, claims=claims,
            doc_context=doc_context, doc_id="doc_028", tenant_id="default",
            doc_title="SAP S/4HANA Security Guide",
        )

        assert len(anchors) == 3
        names = {a.canonical_name for a in anchors}
        assert names == {"SAP S/4HANA", "Personal Data", "ABAP"}

        # resolve_batch reçoit uniquement les SUBJECT
        raw = orch.subject_resolver.resolve_batch.call_args.kwargs["raw_subjects"]
        assert set(raw) == {"SAP S/4HANA", "Personal Data", "ABAP"}

    def test_uses_canonical_entity_names(self):
        """Les noms envoyés au resolver sont les noms canoniques (post Phase 2.5)."""
        claims = [_make_claim(f"Text {i} enough length here", claim_id=f"c_{i:03d}") for i in range(100)]
        entities = [_make_entity("SAP S/4HANA", "ent_canon", EntityType.PRODUCT)]
        cem = {f"c_{i:03d}": ["ent_canon"] for i in range(20)}

        orch = _build_orchestrator()
        _set_llm_response({"decisions": [{"index": 1, "verdict": "SUBJECT", "reason": "main"}]})
        orch.subject_resolver.resolve_batch.return_value = [
            ResolverResult(anchor=_make_anchor("SAP S/4HANA"), status=ResolutionStatus.RESOLVED, confidence=0.95, match_type="new"),
        ]

        orch._derive_subjects_from_entities(
            entities=entities, claim_entity_map=cem, claims=claims,
            doc_context=_make_doc_context(), doc_id="doc_028", tenant_id="default",
        )

        raw = orch.subject_resolver.resolve_batch.call_args.kwargs["raw_subjects"]
        assert raw == ["SAP S/4HANA"]


class TestFallbacks:
    def test_no_candidates_small_doc(self):
        """Petit doc → vide, Phase 0.5 préservée."""
        orch = _build_orchestrator()
        claims = [_make_claim(f"Short claim {i} padded", claim_id=f"c_{i}") for i in range(5)]
        doc_context = _make_doc_context(subject_ids=["old_1"])

        anchors, ctx = orch._derive_subjects_from_entities(
            entities=[_make_entity("Minor", "ent_m")],
            claim_entity_map={"c_0": ["ent_m"], "c_1": ["ent_m"]},
            claims=claims, doc_context=doc_context,
            doc_id="doc_small", tenant_id="default",
        )
        assert anchors == []
        assert "old_1" in ctx.subject_ids

    def test_llm_error_failopen(self):
        """Erreur LLM → fail-open, Phase 0.5 préservée."""
        claims = [_make_claim(f"Text {i} enough padding here", claim_id=f"c_{i:03d}") for i in range(100)]
        cem = {f"c_{i:03d}": ["ent_big"] for i in range(20)}

        orch = _build_orchestrator()
        doc_context = _make_doc_context(subject_ids=["old_1"])
        _set_llm_error(Exception("LLM timeout"))

        anchors, ctx = orch._derive_subjects_from_entities(
            entities=[_make_entity("Big Entity", "ent_big")],
            claim_entity_map=cem, claims=claims,
            doc_context=doc_context, doc_id="doc_028", tenant_id="default",
        )
        assert anchors == []
        assert "old_1" in ctx.subject_ids

    def test_llm_few_decisions_failopen(self):
        """LLM retourne <50% des verdicts → fail-open."""
        claims = [_make_claim(f"Text {i} padding for length", claim_id=f"c_{i:03d}") for i in range(200)]
        entities = [
            _make_entity("Entity A", "ent_a"),
            _make_entity("Entity B", "ent_b"),
            _make_entity("Entity C", "ent_c"),
        ]
        cem = {}
        for i in range(60):
            cem[f"c_{i:03d}"] = [f"ent_{'abc'[i // 20]}"]

        orch = _build_orchestrator()
        doc_context = _make_doc_context(subject_ids=["old_1"])
        # 1 verdict sur 3 → <50%
        _set_llm_response({"decisions": [{"index": 1, "verdict": "SUBJECT", "reason": "ok"}]})

        anchors, ctx = orch._derive_subjects_from_entities(
            entities=entities, claim_entity_map=cem, claims=claims,
            doc_context=doc_context, doc_id="doc_028", tenant_id="default",
        )
        assert anchors == []
        assert "old_1" in ctx.subject_ids

    def test_empty_claims(self):
        orch = _build_orchestrator()
        anchors, _ = orch._derive_subjects_from_entities(
            entities=[], claim_entity_map={}, claims=[],
            doc_context=_make_doc_context(), doc_id="doc_028", tenant_id="default",
        )
        assert anchors == []


class TestResolverDedup:
    def test_existing_anchor_no_duplicate(self):
        """match_type=exact → pas de doublon dans _subject_anchors."""
        claims = [_make_claim(f"Text {i} enough padding", claim_id=f"c_{i:03d}") for i in range(100)]
        cem = {f"c_{i:03d}": ["ent_1"] for i in range(15)}

        orch = _build_orchestrator()
        existing = _make_anchor("SAP S/4HANA", "subj_existing")
        orch._subject_anchors = [existing]

        _set_llm_response({"decisions": [{"index": 1, "verdict": "SUBJECT", "reason": "product"}]})
        orch.subject_resolver.resolve_batch.return_value = [
            ResolverResult(anchor=existing, status=ResolutionStatus.RESOLVED, confidence=1.0, match_type="exact"),
        ]

        anchors, _ = orch._derive_subjects_from_entities(
            entities=[_make_entity("SAP S/4HANA", "ent_1", EntityType.PRODUCT)],
            claim_entity_map=cem, claims=claims,
            doc_context=_make_doc_context(), doc_id="doc_028", tenant_id="default",
        )

        assert len(anchors) == 1
        assert anchors[0].subject_id == "subj_existing"
        assert len(orch._subject_anchors) == 1


class TestDocContextUpdate:
    def test_subject_ids_replaced(self):
        """Les subject_ids Phase 0.5 sont remplacés par les entity-derived."""
        claims = [_make_claim(f"Text {i} enough padding", claim_id=f"c_{i:03d}") for i in range(100)]
        cem = {f"c_{i:03d}": ["ent_pd"] for i in range(15)}

        orch = _build_orchestrator()
        doc_context = _make_doc_context(subject_ids=["old_05_1", "old_05_2"])

        _set_llm_response({"decisions": [{"index": 1, "verdict": "SUBJECT", "reason": "privacy"}]})
        new_anchor = _make_anchor("Personal Data", "subj_pd_new")
        orch.subject_resolver.resolve_batch.return_value = [
            ResolverResult(anchor=new_anchor, status=ResolutionStatus.RESOLVED, confidence=0.95, match_type="new"),
        ]

        anchors, ctx = orch._derive_subjects_from_entities(
            entities=[_make_entity("Personal Data", "ent_pd")],
            claim_entity_map=cem, claims=claims,
            doc_context=doc_context, doc_id="doc_028", tenant_id="default",
        )

        assert "old_05_1" not in ctx.subject_ids
        assert "old_05_2" not in ctx.subject_ids
        assert "subj_pd_new" in ctx.subject_ids

    def test_primary_subject_preserved(self):
        """primary_subject (string) n'est PAS touché par le remplacement."""
        claims = [_make_claim(f"Text {i} enough padding", claim_id=f"c_{i:03d}") for i in range(100)]
        cem = {f"c_{i:03d}": ["ent_abap"] for i in range(20)}

        orch = _build_orchestrator()
        doc_context = _make_doc_context(subject_ids=["old_1"])

        _set_llm_response({"decisions": [{"index": 1, "verdict": "SUBJECT", "reason": "lang"}]})
        orch.subject_resolver.resolve_batch.return_value = [
            ResolverResult(anchor=_make_anchor("ABAP", "subj_abap"), status=ResolutionStatus.RESOLVED, confidence=0.95, match_type="new"),
        ]

        _, ctx = orch._derive_subjects_from_entities(
            entities=[_make_entity("ABAP", "ent_abap")],
            claim_entity_map=cem, claims=claims,
            doc_context=doc_context, doc_id="doc_028", tenant_id="default",
        )

        assert ctx.primary_subject == "SAP S/4HANA Security Guide"


class TestLimits:
    def test_max_5_subjects(self):
        """Max 5 sujets finaux même si LLM en accepte 8."""
        claims = [_make_claim(f"Text {i} enough padding", claim_id=f"c_{i:03d}") for i in range(300)]
        entities = [
            _make_entity(f"Entity {chr(65 + j)}", f"ent_{j}")
            for j in range(8)
        ]
        cem = {}
        for i in range(160):
            ent_idx = i // 20
            if ent_idx < 8:
                cem[f"c_{i:03d}"] = [f"ent_{ent_idx}"]

        orch = _build_orchestrator()
        _set_llm_response({"decisions": [
            {"index": j + 1, "verdict": "SUBJECT", "reason": f"topic {j}"}
            for j in range(8)
        ]})

        def fake_resolve(raw_subjects, existing_anchors, doc_id):
            return [
                ResolverResult(
                    anchor=_make_anchor(name, f"subj_{i}"),
                    status=ResolutionStatus.RESOLVED, confidence=0.95, match_type="new",
                )
                for i, name in enumerate(raw_subjects)
            ]

        orch.subject_resolver.resolve_batch.side_effect = fake_resolve

        anchors, _ = orch._derive_subjects_from_entities(
            entities=entities, claim_entity_map=cem, claims=claims,
            doc_context=_make_doc_context(), doc_id="doc_028", tenant_id="default",
        )

        raw = orch.subject_resolver.resolve_batch.call_args.kwargs.get(
            "raw_subjects",
            orch.subject_resolver.resolve_batch.call_args[0][0] if orch.subject_resolver.resolve_batch.call_args[0] else [],
        )
        assert len(raw) <= 5
        assert len(anchors) <= 5
