"""Tests TwoPhasePublisher V5 DSG (CH-52.3.3)."""
from __future__ import annotations

import threading
import time
import uuid
from typing import Optional

import pytest

from knowbase.runtime_v5.neo4j_dsg import get_v5_dsg
from knowbase.runtime_v5.redlock import get_redlock_client, reset_redlock_client
from knowbase.runtime_v5.tenant_guard import reset_tenant_guard
from knowbase.runtime_v5.two_phase_publish import (
    ACTIVE_STATUS_ACTIVE,
    ACTIVE_STATUS_DEPRECATED,
    ACTIVE_STATUS_STAGED,
    PublishResult,
    TwoPhasePublisher,
)


@pytest.fixture(scope="module")
def publisher():
    reset_tenant_guard()
    reset_redlock_client()
    dsg = get_v5_dsg()
    dsg.setup_schema()
    redlock = get_redlock_client()
    return TwoPhasePublisher(dsg=dsg, redlock=redlock)


def _rand_tenant():
    return "test_tpp_" + uuid.uuid4().hex[:8]


def _sample_structure(doc_id: str, n_sections: int = 3) -> dict:
    return {
        "doc_id": doc_id,
        "doc_name": f"Test Doc {doc_id}",
        "n_pages": n_sections + 1,
        "extractor_version": "test-v1",
        "sections": [
            {
                "section_id": f"sec_{doc_id}_{i}",
                "level": 1,
                "numbering": str(i + 1),
                "title": f"Section {i+1}",
                "section_path": f"/Page {i+1}",
                "page_range": [i, i + 1],
                "text": f"Content of section {i+1} for doc {doc_id}",
            }
            for i in range(n_sections)
        ],
    }


def _cleanup_tenant(publisher: TwoPhasePublisher, tenant_id: str):
    publisher.dsg.tenant_purge(tenant_id, confirm=True)


# ─────────────────────────────────────────────────────────────────────────────
# Cas nominal : première publication
# ─────────────────────────────────────────────────────────────────────────────

class TestFirstPublish:
    def test_publish_v1(self, publisher):
        tenant = _rand_tenant()
        try:
            struct = _sample_structure("doc_test_v1", n_sections=3)
            result = publisher.publish(tenant, struct)

            assert result.success is True, f"failed: {result.error}"
            assert result.doc_version == 1
            assert result.n_sections_active == 3
            assert result.deprecated_version is None
            assert all(inv.passed for inv in result.invariants)

            # Le doc est désormais ACTIVE
            doc = publisher.get_active_version(tenant, "doc_test_v1")
            assert doc is not None
            assert doc["active_status"] == ACTIVE_STATUS_ACTIVE
            assert doc["doc_version"] == 1
        finally:
            _cleanup_tenant(publisher, tenant)


# ─────────────────────────────────────────────────────────────────────────────
# Re-publish (version 2 supersedes version 1)
# ─────────────────────────────────────────────────────────────────────────────

class TestRepublish:
    def test_v2_supersedes_v1(self, publisher):
        tenant = _rand_tenant()
        try:
            # v1
            r1 = publisher.publish(tenant, _sample_structure("doc_x", n_sections=3))
            assert r1.success
            assert r1.doc_version == 1

            # v2
            r2 = publisher.publish(tenant, _sample_structure("doc_x", n_sections=4))
            assert r2.success, f"v2 failed: {r2.error}"
            assert r2.doc_version == 2
            assert r2.deprecated_version == 1

            # Le doc actif est v2
            active = publisher.get_active_version(tenant, "doc_x")
            assert active is not None
            assert active["doc_version"] == 2
            assert active["active_status"] == ACTIVE_STATUS_ACTIVE

            # v1 est deprecated, présent en historique
            v1 = publisher.dsg.get_document(
                tenant, "doc_x", doc_version=1, active_only=False
            )
            assert v1 is not None
            assert v1["active_status"] == ACTIVE_STATUS_DEPRECATED
        finally:
            _cleanup_tenant(publisher, tenant)

    def test_v3_after_v2(self, publisher):
        """Chaîne v1 → v2 → v3."""
        tenant = _rand_tenant()
        try:
            r1 = publisher.publish(tenant, _sample_structure("doc_y", n_sections=2))
            r2 = publisher.publish(tenant, _sample_structure("doc_y", n_sections=3))
            r3 = publisher.publish(tenant, _sample_structure("doc_y", n_sections=4))
            assert r1.doc_version == 1
            assert r2.doc_version == 2
            assert r3.doc_version == 3
            assert r3.deprecated_version == 2
            active = publisher.get_active_version(tenant, "doc_y")
            assert active["doc_version"] == 3
        finally:
            _cleanup_tenant(publisher, tenant)


# ─────────────────────────────────────────────────────────────────────────────
# Validation invariants
# ─────────────────────────────────────────────────────────────────────────────

class TestValidationInvariants:
    def test_min_sections_threshold(self, publisher):
        tenant = _rand_tenant()
        try:
            # Doc avec 0 sections → invariant min_sections_threshold échoue
            struct = {"doc_id": "doc_empty", "doc_name": "Empty", "sections": []}
            result = publisher.publish(tenant, struct)
            assert result.success is False
            assert result.rolled_back is True
            # invariant min_sections_threshold doit être marqué passed=False
            failed_names = [inv.name for inv in result.invariants if not inv.passed]
            assert "min_sections_threshold" in failed_names

            # Aucun document actif créé
            assert publisher.get_active_version(tenant, "doc_empty") is None
        finally:
            _cleanup_tenant(publisher, tenant)

    def test_duplicate_section_ids_rejected(self, publisher):
        tenant = _rand_tenant()
        try:
            struct = _sample_structure("doc_dup", n_sections=2)
            # Force duplicate section_id
            struct["sections"][1]["section_id"] = struct["sections"][0]["section_id"]
            result = publisher.publish(tenant, struct)
            assert result.success is False
            failed = [inv.name for inv in result.invariants if not inv.passed]
            assert "unique_section_ids_input" in failed
        finally:
            _cleanup_tenant(publisher, tenant)


# ─────────────────────────────────────────────────────────────────────────────
# Rollback explicite
# ─────────────────────────────────────────────────────────────────────────────

class TestRollback:
    def test_rollback_staged_orphan(self, publisher):
        """Si on publie v1, puis qu'on injecte manuellement un staged orphelin,
        rollback_staged doit le nettoyer sans toucher l'active."""
        tenant = _rand_tenant()
        try:
            r1 = publisher.publish(tenant, _sample_structure("doc_r", n_sections=2))
            assert r1.success

            # Inject manuellement un staged (simule un crash entre stage et flip)
            publisher._stage_document(
                tenant, _sample_structure("doc_r", n_sections=3), doc_version=2,
                sections=_sample_structure("doc_r", n_sections=3)["sections"],
            )
            # Vérifier qu'il y a bien un staged
            staged = publisher.dsg.get_document(
                tenant, "doc_r", doc_version=2, active_only=False
            )
            assert staged is not None and staged["active_status"] == "staged"

            # Rollback staged
            res = publisher.rollback_staged(tenant, "doc_r")
            assert res["removed"] is True
            assert res["doc_version"] == 2

            # active reste intact
            active = publisher.get_active_version(tenant, "doc_r")
            assert active is not None
            assert active["doc_version"] == 1
        finally:
            _cleanup_tenant(publisher, tenant)

    def test_rollback_no_staged(self, publisher):
        tenant = _rand_tenant()
        try:
            publisher.publish(tenant, _sample_structure("doc_nostaged", n_sections=1))
            res = publisher.rollback_staged(tenant, "doc_nostaged")
            assert res["removed"] is False
        finally:
            _cleanup_tenant(publisher, tenant)


# ─────────────────────────────────────────────────────────────────────────────
# Lock concurrent
# ─────────────────────────────────────────────────────────────────────────────

class TestConcurrentPublish:
    def test_fail_fast_when_locked(self, publisher):
        """Si un publish est en cours, un autre publish fail-fast retourne success=False."""
        tenant = _rand_tenant()
        try:
            # Acquire le lock manuellement
            redlock = publisher.redlock
            token = redlock.acquire(tenant, "doc_locked", timeout_s=30, wait_s=0)
            try:
                # Tenter publish
                result = publisher.publish(
                    tenant, _sample_structure("doc_locked", n_sections=2),
                    wait_lock_s=0.0,
                )
                assert result.success is False
                assert "lock_timeout" in (result.error or "")
            finally:
                redlock.release(tenant, "doc_locked", token)
        finally:
            _cleanup_tenant(publisher, tenant)

    def test_serialized_publishes(self, publisher):
        """2 threads publish en parallèle : tous deux réussissent sérialisés."""
        tenant = _rand_tenant()
        try:
            results = []
            results_lock = threading.Lock()

            def _publish(version_marker):
                struct = _sample_structure(f"doc_serial", n_sections=2 + version_marker)
                r = publisher.publish(tenant, struct, wait_lock_s=15.0)
                with results_lock:
                    results.append(r)

            threads = [threading.Thread(target=_publish, args=(i,)) for i in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            successes = [r for r in results if r.success]
            assert len(successes) == 2, f"expected 2 successes, got {len(successes)}"
            # Final active doc_version doit être 2 (v1 + v2 séquentiels)
            active = publisher.get_active_version(tenant, "doc_serial")
            assert active["doc_version"] == 2
        finally:
            _cleanup_tenant(publisher, tenant)


# ─────────────────────────────────────────────────────────────────────────────
# Tenant isolation
# ─────────────────────────────────────────────────────────────────────────────

class TestTenantIsolation:
    def test_publishes_dont_interfere_across_tenants(self, publisher):
        ta = _rand_tenant()
        tb = _rand_tenant()
        try:
            ra = publisher.publish(ta, _sample_structure("doc_shared_id", n_sections=2))
            rb = publisher.publish(tb, _sample_structure("doc_shared_id", n_sections=5))
            assert ra.success and rb.success
            # Les versions sont indépendantes (v1 pour les deux)
            assert ra.doc_version == 1
            assert rb.doc_version == 1
            # Counts sections diffèrent
            assert ra.n_sections_active == 2
            assert rb.n_sections_active == 5
        finally:
            _cleanup_tenant(publisher, ta)
            _cleanup_tenant(publisher, tb)


# ─────────────────────────────────────────────────────────────────────────────
# Recompute section_ids
# ─────────────────────────────────────────────────────────────────────────────

class TestRecomputeSectionIds:
    def test_recompute_section_ids(self, publisher):
        """Avec recompute_section_ids=True, les section_id sont remplacés par
        sha256 stable (S2.1) calculé à partir de doc_id + title + page."""
        tenant = _rand_tenant()
        try:
            struct = _sample_structure("doc_rc", n_sections=2)
            original_sids = [s["section_id"] for s in struct["sections"]]
            r = publisher.publish(tenant, struct, recompute_section_ids=True)
            assert r.success

            sections = publisher.dsg.list_sections(tenant, "doc_rc")
            new_sids = [s["section_id"] for s in sections]
            # IDs sont des hashes sha256 prefixés sec_
            assert all(sid.startswith("sec_") and len(sid) == 28 for sid in new_sids)
            # Et différents des originaux qu'on avait fournis
            assert set(new_sids) != set(original_sids)
        finally:
            _cleanup_tenant(publisher, tenant)
