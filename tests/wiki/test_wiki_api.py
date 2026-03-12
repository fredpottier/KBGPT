"""
Tests unitaires pour la Wiki Generation Console (Phase 3).

Teste les schemas, la logique du job store, et le pipeline via mocks.
Charge les modules directement par spec_from_file_location pour éviter
la chaîne d'imports transitifs (FastAPI, httpx, etc. non installés localement).
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# ── Chemin racine du projet ──────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[2]  # tests/wiki → racine projet
_SRC = _ROOT / "src"

# ── Mock des dépendances lourdes ─────────────────────────────────────────
_MOCK_MODS = [
    "debugpy", "httpx", "fastapi", "fastapi.middleware",
    "fastapi.middleware.cors", "fastapi.staticfiles",
    "slowapi", "slowapi.util", "slowapi.errors",
    "starlette", "starlette.responses",
]

for _m in _MOCK_MODS:
    if _m not in sys.modules:
        sys.modules[_m] = MagicMock()

# fastapi doit avoir de vrais callables
_fa = sys.modules["fastapi"]
_fa.APIRouter = lambda **kw: type("_R", (), {
    "post": lambda self=None, *a, **k: (lambda f: f),
    "get": lambda self=None, *a, **k: (lambda f: f),
})()
_fa.BackgroundTasks = MagicMock
_fa.Depends = lambda x: x
_fa.HTTPException = type("HTTPException", (Exception,), {
    "__init__": lambda self, status_code=0, detail="": None
})
_fa.Query = lambda *a, **kw: kw.get("default")


def _load_module_from_file(name: str, filepath: Path):
    """Charge un module Python directement depuis son fichier, sans résoudre le package parent."""
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── Charger schemas wiki (pas de deps lourdes — juste pydantic) ─────────
# Il faut s'assurer que knowbase.api.schemas est un package
_schemas_init = _SRC / "knowbase" / "api" / "schemas" / "__init__.py"
if "knowbase.api.schemas" not in sys.modules:
    _pkg = types.ModuleType("knowbase.api.schemas")
    _pkg.__path__ = [str(_schemas_init.parent)]
    _pkg.__package__ = "knowbase.api.schemas"
    sys.modules["knowbase.api.schemas"] = _pkg

_schemas = _load_module_from_file(
    "knowbase.api.schemas.wiki",
    _SRC / "knowbase" / "api" / "schemas" / "wiki.py",
)

# ── Charger le router wiki (deps = schemas + fastapi mockée) ─────────────
# Mock knowbase.api.dependencies pour get_tenant_id
_deps_mock = types.ModuleType("knowbase.api.dependencies")
_deps_mock.get_tenant_id = lambda: "default"
sys.modules["knowbase.api.dependencies"] = _deps_mock

_wiki_mod = _load_module_from_file(
    "knowbase.api.routers.wiki",
    _SRC / "knowbase" / "api" / "routers" / "wiki.py",
)

# ── Extraire les objets nécessaires ──────────────────────────────────────
_wiki_jobs = _wiki_mod._wiki_jobs
_active_jobs = _wiki_mod._active_jobs
WikiJobState = _wiki_mod.WikiJobState
_run_wiki_pipeline = _wiki_mod._run_wiki_pipeline
_job_key = _wiki_mod._job_key
_is_reusable = _wiki_mod._is_reusable

WikiGenerateRequest = _schemas.WikiGenerateRequest
WikiGenerateResponse = _schemas.WikiGenerateResponse
WikiJobStatus = _schemas.WikiJobStatus
WikiArticleResponse = _schemas.WikiArticleResponse
WikiConceptSearchResponse = _schemas.WikiConceptSearchResponse
WikiResolutionInfo = _schemas.WikiResolutionInfo


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def clear_jobs():
    _wiki_jobs.clear()
    _active_jobs.clear()
    yield
    _wiki_jobs.clear()
    _active_jobs.clear()


# ── Tests Schemas ────────────────────────────────────────────────────────


class TestSchemas:
    def test_generate_request_defaults(self):
        req = WikiGenerateRequest(concept_name="GDPR")
        assert req.concept_name == "GDPR"
        assert req.language == "français"

    def test_generate_request_custom_language(self):
        req = WikiGenerateRequest(concept_name="GDPR", language="english")
        assert req.language == "english"

    def test_resolution_info(self):
        info = WikiResolutionInfo(
            resolution_method="exact+canon",
            resolution_confidence=0.95,
            matched_entities=3,
        )
        assert info.resolution_method == "exact+canon"
        assert info.matched_entities == 3

    def test_article_response_has_generation_confidence(self):
        resp = WikiArticleResponse(
            job_id="j1", concept_name="GDPR", language="français",
            markdown="# GDPR", sections_count=3, total_citations=10,
            generation_confidence=0.78, all_gaps=["gap1"],
            source_count=2, unit_count=15,
            resolution=WikiResolutionInfo(
                resolution_method="exact", resolution_confidence=1.0,
                matched_entities=1,
            ),
            generated_at="2026-03-12T10:00:00",
        )
        assert resp.generation_confidence == 0.78
        assert resp.resolution.resolution_method == "exact"

    def test_concept_search_response(self):
        resp = WikiConceptSearchResponse(
            results=[{"entity_name": "GDPR", "entity_type": "regulation", "claim_count": 42}],
            total=1,
        )
        assert resp.results[0].entity_name == "GDPR"
        assert resp.total == 1

    def test_job_status_optional_fields(self):
        st = WikiJobStatus(job_id="x", status="running", progress="Étape 2")
        assert st.progress == "Étape 2"
        assert st.error is None


# ── Tests Job Store ──────────────────────────────────────────────────────


class TestJobStore:
    def test_job_key_normalization(self):
        assert _job_key("default", "GDPR", "français") == "default:gdpr:français"
        assert _job_key("default", "  GDPR  ", "  Français  ") == "default:gdpr:français"

    def test_job_state_defaults(self):
        job = WikiJobState(
            job_id="t1", concept_name="GDPR", language="français",
            tenant_id="default", created_at="",
        )
        assert job.status == "pending"
        assert job.markdown is None

    def test_is_reusable_pending(self):
        job = WikiJobState(job_id="j", concept_name="X", language="f",
                           tenant_id="t", status="pending", created_at="")
        assert _is_reusable(job) is True

    def test_is_reusable_running(self):
        job = WikiJobState(job_id="j", concept_name="X", language="f",
                           tenant_id="t", status="running", created_at="")
        assert _is_reusable(job) is True

    def test_is_reusable_failed(self):
        job = WikiJobState(job_id="j", concept_name="X", language="f",
                           tenant_id="t", status="failed", created_at="")
        assert _is_reusable(job) is False

    def test_idempotence_pending(self):
        job = WikiJobState(
            job_id="job-1", concept_name="GDPR", language="français",
            tenant_id="default", status="pending", created_at="",
        )
        _wiki_jobs["job-1"] = job
        _active_jobs["default:gdpr:français"] = "job-1"

        existing = _wiki_jobs[_active_jobs["default:gdpr:français"]]
        assert existing.job_id == "job-1"
        assert _is_reusable(existing)

    def test_idempotence_running(self):
        job = WikiJobState(
            job_id="job-2", concept_name="GDPR", language="français",
            tenant_id="default", status="running", created_at="",
        )
        _wiki_jobs["job-2"] = job
        _active_jobs["default:gdpr:français"] = "job-2"

        assert _is_reusable(_wiki_jobs[_active_jobs["default:gdpr:français"]])


# ── Tests Pipeline (mocked) ─────────────────────────────────────────────


def _make_mock_resolved():
    from knowbase.wiki.models import ResolvedConcept
    return ResolvedConcept(
        canonical_name="GDPR", entity_type="regulation",
        entity_ids=["e1", "e2"],
        resolution_method="exact+canon", resolution_confidence=0.95,
    )


def _make_mock_pack():
    from knowbase.wiki.models import EvidencePack, ResolvedConcept, QualitySignals, SourceEntry
    return EvidencePack(
        concept=ResolvedConcept(
            canonical_name="GDPR", entity_type="regulation", entity_ids=["e1"],
        ),
        source_index=[SourceEntry(doc_id="d1", doc_title="D1", unit_count=5, contribution_pct=1.0)],
        quality_signals=QualitySignals(total_units=5, doc_count=1, coverage_score=0.8),
    )


def _make_mock_article(confidence=0.85, gaps=None):
    from knowbase.wiki.models import GeneratedArticle, ArticlePlan, GeneratedSection
    return GeneratedArticle(
        concept_name="GDPR",
        plan=ArticlePlan(concept_name="GDPR", slug="gdpr"),
        sections=[GeneratedSection(
            section_type="overview", title="Vue d'ensemble",
            content="content", citations_used=["eu_1", "eu_2"],
            confidence=confidence, gaps=[],
        )],
        generated_at="2026-03-12T10:00:00+00:00",
        total_citations=2, average_confidence=confidence,
        all_gaps=gaps or [],
    )


def _patch_full_pipeline(resolved=None, pack=None, article=None, md="# GDPR"):
    """Context manager qui mocke tout le pipeline wiki (lazy imports inclus)."""
    from contextlib import contextmanager

    @contextmanager
    def ctx():
        r = MagicMock(); r.resolve.return_value = resolved or _make_mock_resolved()
        b = MagicMock(); b.build.return_value = pack or _make_mock_pack()
        from knowbase.wiki.models import ArticlePlan
        p = MagicMock(); p.plan.return_value = ArticlePlan(concept_name="GDPR", slug="gdpr")
        g = MagicMock()
        g.generate.return_value = article or _make_mock_article()
        g.render_markdown.return_value = md

        # Mock les modules lazy-importés par _run_wiki_pipeline
        mock_neo4j_mod = MagicMock()
        mock_neo4j_mod.get_neo4j_client.return_value = MagicMock()
        mock_clients_mod = MagicMock()
        mock_clients_mod.get_qdrant_client.return_value = MagicMock()
        mock_emb_mod = MagicMock()
        mock_emb_mod.get_embedding_manager.return_value = MagicMock()

        with (
            patch.dict(sys.modules, {
                "knowbase.common.clients.neo4j_client": mock_neo4j_mod,
                "knowbase.common.clients": mock_clients_mod,
                "knowbase.common.clients.embeddings": mock_emb_mod,
                "knowbase.wiki.concept_resolver": MagicMock(ConceptResolver=lambda *a: r),
                "knowbase.wiki.evidence_pack_builder": MagicMock(EvidencePackBuilder=lambda *a, **kw: b),
                "knowbase.wiki.section_planner": MagicMock(SectionPlanner=lambda *a: p),
                "knowbase.wiki.constrained_generator": MagicMock(ConstrainedGenerator=lambda *a: g),
            }),
        ):
            yield
    return ctx()


class TestPipeline:
    def test_completed(self):
        job = WikiJobState(
            job_id="p1", concept_name="GDPR", language="français",
            tenant_id="default", created_at="",
        )
        _wiki_jobs["p1"] = job

        with _patch_full_pipeline():
            _run_wiki_pipeline("p1", "GDPR", "français", "default")

        assert job.status == "completed"
        assert job.markdown == "# GDPR"
        assert job.article_data["total_citations"] == 2
        assert job.article_data["generation_confidence"] == 0.85
        assert job.resolution_info["resolution_method"] == "exact+canon"
        assert job.resolution_info["matched_entities"] == 2

    def test_completed_with_warnings_fuzzy(self):
        job = WikiJobState(
            job_id="p2", concept_name="T", language="fr",
            tenant_id="default", created_at="",
        )
        _wiki_jobs["p2"] = job

        resolved = _make_mock_resolved()
        resolved.resolution_method = "fuzzy"

        with _patch_full_pipeline(resolved=resolved):
            _run_wiki_pipeline("p2", "T", "fr", "default")

        assert job.status == "completed_with_warnings"

    def test_completed_with_warnings_low_confidence(self):
        job = WikiJobState(
            job_id="p3", concept_name="W", language="fr",
            tenant_id="default", created_at="",
        )
        _wiki_jobs["p3"] = job

        with _patch_full_pipeline(article=_make_mock_article(confidence=0.3)):
            _run_wiki_pipeline("p3", "W", "fr", "default")

        assert job.status == "completed_with_warnings"

    def test_completed_with_warnings_many_gaps(self):
        job = WikiJobState(
            job_id="p4", concept_name="G", language="fr",
            tenant_id="default", created_at="",
        )
        _wiki_jobs["p4"] = job

        with _patch_full_pipeline(article=_make_mock_article(gaps=["a", "b", "c", "d"])):
            _run_wiki_pipeline("p4", "G", "fr", "default")

        assert job.status == "completed_with_warnings"

    def test_concept_not_found(self):
        job = WikiJobState(
            job_id="p5", concept_name="Nope", language="fr",
            tenant_id="default", created_at="",
        )
        _wiki_jobs["p5"] = job

        mock_r = MagicMock()
        mock_r.resolve.side_effect = ValueError("Aucune entité pour 'Nope'")

        mock_neo4j_mod = MagicMock()
        mock_neo4j_mod.get_neo4j_client.return_value = MagicMock()

        with patch.dict(sys.modules, {
            "knowbase.common.clients.neo4j_client": mock_neo4j_mod,
            "knowbase.wiki.concept_resolver": MagicMock(ConceptResolver=lambda *a: mock_r),
        }):
            _run_wiki_pipeline("p5", "Nope", "fr", "default")

        assert job.status == "failed"
        assert "Nope" in job.error
        assert job.progress is None

    def test_unexpected_exception(self):
        job = WikiJobState(
            job_id="p6", concept_name="Crash", language="fr",
            tenant_id="default", created_at="",
        )
        _wiki_jobs["p6"] = job

        mock_r = MagicMock()
        mock_r.resolve.side_effect = RuntimeError("Connection lost")

        mock_neo4j_mod = MagicMock()
        mock_neo4j_mod.get_neo4j_client.return_value = MagicMock()

        with patch.dict(sys.modules, {
            "knowbase.common.clients.neo4j_client": mock_neo4j_mod,
            "knowbase.wiki.concept_resolver": MagicMock(ConceptResolver=lambda *a: mock_r),
        }):
            _run_wiki_pipeline("p6", "Crash", "fr", "default")

        assert job.status == "failed"
        assert "Connection lost" in job.error
