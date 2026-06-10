"""Tests du module document_profile (B1+B2, chantier en-tête de nature documentaire)."""

from __future__ import annotations

import json

import pytest

from knowbase.claimfirst.document_profile import (
    DocumentProfiler,
    DocumentRoleRegistry,
    _extract_json,
    _role_key,
    doc_profile_enabled,
    persist_document_profile,
    run_document_profiling,
)


# ──────────────────────────────────────────────────────────────────────────────
# Doubles de test
# ──────────────────────────────────────────────────────────────────────────────
class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class FakeSession:
    def __init__(self, driver):
        self._driver = driver

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, **params):
        self._driver.calls.append((query, params))
        if "MATCH (r:DocRole" in query:
            return FakeResult(self._driver.existing_roles)
        return FakeResult([])


class FakeDriver:
    def __init__(self, existing_roles=None):
        self.calls = []
        self.existing_roles = existing_roles or []

    def session(self):
        return FakeSession(self)


class FakeRouter:
    """Routeur LLM minimal : renvoie une réponse fixe (ou lève)."""

    def __init__(self, response=None, raise_exc=None):
        self.response = response
        self.raise_exc = raise_exc
        self.last_messages = None

    def complete(self, *, task_type, messages, **kwargs):  # noqa: D401
        self.last_messages = messages
        if self.raise_exc:
            raise self.raise_exc
        return self.response


# ──────────────────────────────────────────────────────────────────────────────
# Flag
# ──────────────────────────────────────────────────────────────────────────────
def test_flag_default_on(monkeypatch):
    monkeypatch.delenv("V6_DOC_PROFILE", raising=False)
    assert doc_profile_enabled() is True


def test_flag_off(monkeypatch):
    monkeypatch.setenv("V6_DOC_PROFILE", "0")
    assert doc_profile_enabled() is False


# ──────────────────────────────────────────────────────────────────────────────
# B1 — registre / normalisation
# ──────────────────────────────────────────────────────────────────────────────
def test_role_key_folds_plural_and_case():
    assert _role_key("Regulation") == _role_key("regulations")
    assert _role_key("Advisory Circular") == "advisorycircular"


def test_registry_collapses_variants_and_registers_new():
    driver = FakeDriver()
    reg = DocumentRoleRegistry("aero")
    reg.load(driver)

    c1 = reg.normalize("regulation", neo4j_driver=driver)
    c2 = reg.normalize("Regulations", neo4j_driver=driver)
    assert c1 == c2  # variantes repliées sur un seul canonical
    assert c1 == "Regulation"

    # Un seul MERGE :DocRole (le 2e label réutilise le canonical)
    merges = [c for c in driver.calls if "MERGE (r:DocRole" in c[0]]
    assert len(merges) == 1

    c3 = reg.normalize("specification", neo4j_driver=driver)
    assert c3 == "Specification"
    merges = [c for c in driver.calls if "MERGE (r:DocRole" in c[0]]
    assert len(merges) == 2


def test_registry_reuses_preloaded_canonical():
    driver = FakeDriver(existing_roles=[{"canonical": "Standard"}])
    reg = DocumentRoleRegistry("aero")
    reg.load(driver)
    # "standards" doit retomber sur le canonical préchargé, sans nouveau MERGE
    assert reg.normalize("standards", neo4j_driver=driver) == "Standard"
    merges = [c for c in driver.calls if "MERGE (r:DocRole" in c[0]]
    assert len(merges) == 0


def test_registry_load_is_resilient_without_driver():
    reg = DocumentRoleRegistry("aero")
    reg.load(None)  # ne doit pas lever
    assert reg.normalize(None) is None
    assert reg.normalize("") is None


# ──────────────────────────────────────────────────────────────────────────────
# Parsing JSON tolérant
# ──────────────────────────────────────────────────────────────────────────────
def test_extract_json_plain():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_embedded():
    assert _extract_json('blabla {"a": 1} trailing')["a"] == 1


def test_extract_json_garbage_returns_none():
    assert _extract_json("not json at all") is None


# ──────────────────────────────────────────────────────────────────────────────
# B1 — profileur
# ──────────────────────────────────────────────────────────────────────────────
def test_profiler_parses_and_truncates():
    payload = {
        "summary": "S" * 500,
        "role": "Regulation",
        "role_confidence": 0.9,
        "role_rationale": "Le document est une Advisory Circular de la FAA.",
    }
    router = FakeRouter(response=json.dumps(payload))
    out = DocumentProfiler(router=router).profile(title="AC 25.562-1B", text="Advisory Circular...")
    assert out is not None
    assert len(out["summary"]) == 320  # tronqué
    assert out["role_raw"] == "Regulation"
    assert out["role_confidence"] == 0.9
    # Le system prompt impose un rôle = catégorie, vérifions qu'il est bien envoyé
    assert "NATURE / KIND" in router.last_messages[0]["content"]


def test_profiler_handles_bad_confidence():
    payload = {"summary": "x", "role": "standard", "role_confidence": "high", "role_rationale": "y"}
    out = DocumentProfiler(router=FakeRouter(response=json.dumps(payload))).profile("t", "x")
    assert out["role_confidence"] is None  # non castable → None, pas d'exception


def test_profiler_returns_none_on_llm_error():
    out = DocumentProfiler(router=FakeRouter(raise_exc=RuntimeError("boom"))).profile("t", "x")
    assert out is None


def test_profiler_returns_none_on_unparseable():
    out = DocumentProfiler(router=FakeRouter(response="garbage")).profile("t", "x")
    assert out is None


# ──────────────────────────────────────────────────────────────────────────────
# B2 — persistance
# ──────────────────────────────────────────────────────────────────────────────
def test_persist_does_not_overwrite_title_with_doc_id():
    driver = FakeDriver()
    persist_document_profile(
        driver, "DOC_abc", "aero",
        title="DOC_abc",  # == doc_id → ne doit pas être persisté tel quel
        summary="s", role="Regulation", role_confidence=0.8, role_rationale="r",
    )
    _, params = driver.calls[-1]
    assert params["title"] is None  # coalesce gardera l'existant
    assert params["role"] == "Regulation"


def test_persist_keeps_real_title():
    driver = FakeDriver()
    persist_document_profile(
        driver, "DOC_abc", "aero",
        title="Advisory Circular 25.562-1B", summary="s", role="Regulation",
    )
    _, params = driver.calls[-1]
    assert params["title"] == "Advisory Circular 25.562-1B"


# ──────────────────────────────────────────────────────────────────────────────
# Orchestration bout-en-bout (B1 → normalize → B2)
# ──────────────────────────────────────────────────────────────────────────────
def test_run_document_profiling_persists_and_returns_role():
    driver = FakeDriver()
    reg = DocumentRoleRegistry("aero")
    reg.load(driver)
    router = FakeRouter(response=json.dumps({
        "summary": "Norme de crashworthiness des sièges.",
        "role": "standard",
        "role_confidence": 0.85,
        "role_rationale": "En-tête « Technical Standard Order ».",
    }))

    role = run_document_profiling(
        neo4j_driver=driver,
        registry=reg,
        doc_id="TSO_C127",
        tenant_id="aero",
        title="TSO-C127b",
        full_text="Technical Standard Order ...",
        authority="FAA",
        router=router,
    )
    assert role == "Standard"
    # Un SET role/summary/title a bien été émis
    sets = [c for c in driver.calls if "SET d.role" in c[0]]
    assert len(sets) == 1
    assert sets[0][1]["summary"].startswith("Norme de crashworthiness")


def test_run_document_profiling_none_when_profile_fails():
    driver = FakeDriver()
    reg = DocumentRoleRegistry("aero")
    role = run_document_profiling(
        neo4j_driver=driver,
        registry=reg,
        doc_id="X",
        tenant_id="aero",
        title="t",
        full_text="x",
        router=FakeRouter(response="garbage"),
    )
    assert role is None
    # Aucune écriture de profil si le profilage échoue
    assert not [c for c in driver.calls if "SET d.role" in c[0]]
