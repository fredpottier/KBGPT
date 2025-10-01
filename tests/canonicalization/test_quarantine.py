"""
Tests quarantine workflow Phase 0 Critère 4
Valide délai 24h avant backfill Qdrant avec status quarantine → approved
"""

import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient
from knowbase.api.main import create_app
from knowbase.tasks.quarantine_processor import QuarantineProcessor
from knowbase.audit.audit_logger import AuditLogger


@pytest.fixture
def client():
    """Client de test FastAPI"""
    app = create_app()
    return TestClient(app)


@pytest.fixture
def processor():
    """Quarantine processor"""
    return QuarantineProcessor()


@pytest.fixture
def audit_logger():
    """Audit logger"""
    return AuditLogger()


class TestQuarantineWorkflow:
    """Tests workflow quarantine complet"""

    def test_merge_creates_quarantine_status(self, client):
        """
        Test merge crée status quarantine avec quarantine_until 24h

        Critère validation Phase 0.4:
        - Merge créé avec status="quarantine"
        - quarantine_until = now + 24h
        """
        merge_response = client.post(
            "/api/canonicalization/merge",
            json={
                "canonical_entity_id": "canon_quarantine_001",
                "candidate_ids": ["qc1", "qc2", "qc3"]
            },
            headers={"Idempotency-Key": "test-quarantine-workflow-001"}
        )

        assert merge_response.status_code == 200
        data = merge_response.json()

        # Vérifier status quarantine
        assert "merge_status" in data
        assert data["merge_status"] == "quarantine"

        # Vérifier quarantine_until présent et ~24h dans futur
        assert "quarantine_until" in data
        assert data["quarantine_until"] is not None

        quarantine_until = datetime.fromisoformat(data["quarantine_until"])
        now = datetime.utcnow()
        delta = quarantine_until - now

        # Doit être ~24h (accepter 23h-25h pour tolérance)
        assert 23 * 3600 <= delta.total_seconds() <= 25 * 3600, (
            f"quarantine_until devrait être ~24h dans futur, "
            f"mais delta={delta.total_seconds()/3600:.1f}h"
        )

        print(f"✅ Merge en quarantine: {data['merge_id'][:12]}... jusqu'à {data['quarantine_until']}")

    def test_quarantine_processor_finds_no_ready_merges_initially(self, processor):
        """Test processor ne trouve aucun merge ready initialement (tous <24h)"""
        result = processor.process_quarantine_merges()

        assert result["status"] == "completed"
        assert result["processed"] == 0
        assert result["approved"] == 0
        assert result["failed"] == 0

        print(f"✅ Processor: 0 merges ready (normal, tous en quarantine)")

    def test_quarantine_stats_empty_initially(self, processor):
        """Test stats quarantine vide initialement"""
        stats = processor.get_quarantine_stats()

        assert "quarantine_ready" in stats
        assert stats["quarantine_ready"] == 0  # Aucun merge >24h

        print(f"✅ Stats quarantine: {stats['quarantine_ready']} ready")

    def test_audit_logger_tracks_quarantine_status(self, client, audit_logger):
        """Test audit logger track correctement status quarantine"""
        # Créer merge
        merge_response = client.post(
            "/api/canonicalization/merge",
            json={
                "canonical_entity_id": "canon_audit_quarantine",
                "candidate_ids": ["qac1", "qac2"]
            },
            headers={"Idempotency-Key": "test-audit-quarantine-001"}
        )

        merge_id = merge_response.json()["merge_id"]

        # Récupérer depuis audit trail
        entry = audit_logger.get_merge_entry(merge_id)

        assert entry is not None
        assert entry.merge_status == "quarantine"
        assert entry.quarantine_until is not None

        print(f"✅ Audit trail: merge_id={merge_id[:12]}... status={entry.merge_status}")

    def test_update_merge_status_to_approved(self, client, audit_logger):
        """Test mise à jour status quarantine → approved"""
        # Créer merge
        merge_response = client.post(
            "/api/canonicalization/merge",
            json={
                "canonical_entity_id": "canon_status_update",
                "candidate_ids": ["qsu1"]
            },
            headers={"Idempotency-Key": "test-status-update-001"}
        )

        merge_id = merge_response.json()["merge_id"]

        # Mettre à jour status → approved
        success = audit_logger.update_merge_status(merge_id, "approved")
        assert success is True

        # Vérifier mise à jour
        entry = audit_logger.get_merge_entry(merge_id)
        assert entry.merge_status == "approved"

        print(f"✅ Status mis à jour: {merge_id[:12]}... quarantine → approved")


class TestQuarantineProcessorLogic:
    """Tests logique QuarantineProcessor"""

    def test_processor_structure(self, processor):
        """Test structure processor (méthodes disponibles)"""
        assert hasattr(processor, "process_quarantine_merges")
        assert hasattr(processor, "get_quarantine_stats")
        assert hasattr(processor, "_process_single_merge")

        print(f"✅ QuarantineProcessor structure valide")

    def test_processor_returns_stats(self, processor):
        """Test processor retourne statistiques complètes"""
        result = processor.process_quarantine_merges()

        required_fields = ["status", "processed", "approved", "failed"]
        for field in required_fields:
            assert field in result, f"Champ '{field}' manquant dans résultat"

        assert result["status"] in ["completed", "failed"]
        assert isinstance(result["processed"], int)
        assert isinstance(result["approved"], int)
        assert isinstance(result["failed"], int)

        print(f"✅ Processor stats: {result}")
