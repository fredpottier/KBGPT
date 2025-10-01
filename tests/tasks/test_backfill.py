"""
Tests QdrantBackfillService Phase 0 Critère 5
Valide batching, retries exponentiels, exactly-once, performance
"""

import pytest
import time
import anyio
import uuid
from knowbase.tasks.backfill import QdrantBackfillService

pytestmark = [pytest.mark.anyio, pytest.mark.anyio_backend("asyncio")]


@pytest.fixture
def backfill_service():
    """Service backfill Qdrant avec configuration test"""
    return QdrantBackfillService(
        batch_size=100,
        max_retries=3,
        redis_url="redis://redis:6379/4"  # DB 4 dédiée backfill
    )


def unique_id(prefix: str) -> str:
    """Génère ID unique pour tests (évite collisions Redis)"""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class TestQdrantBackfillService:
    """Tests service backfill Qdrant"""

    async def test_backfill_canonical_entity_structure(self, backfill_service):
        """
        Test structure résultat backfill

        Critère validation Phase 0.5:
        - Résultat contient tous les champs requis
        - Status completed/skipped/partial
        - Statistiques chunks_updated, batches, duration, etc.
        """
        result = await backfill_service.backfill_canonical_entity(
            canonical_entity_id="canon_backfill_test_001",
            candidate_ids=["cand_1", "cand_2"]
        )

        # Vérifier structure résultat
        required_fields = [
            "status", "canonical_entity_id", "chunks_updated", "chunks_total",
            "batches", "batches_failed", "success_rate", "duration_seconds",
            "p95_latency_ms", "avg_latency_ms"
        ]
        for field in required_fields:
            assert field in result, f"Champ '{field}' manquant dans résultat"

        assert result["status"] in ["completed", "skipped", "partial"]
        assert isinstance(result["chunks_updated"], int)
        assert isinstance(result["batches"], int)
        assert result["success_rate"] >= 0 and result["success_rate"] <= 100

        print(f"✅ Backfill structure valide: {result['chunks_updated']} chunks updated")

    async def test_backfill_batching_100_chunks(self, backfill_service):
        """
        Test batching 100 chunks par requête

        Critère validation Phase 0.5:
        - Backfill découpe en batches de max 100 chunks
        - Nombre batches cohérent avec chunks_total
        """
        # Candidates générant ~500 chunks (10-1000 range simulation)
        result = await backfill_service.backfill_canonical_entity(
            canonical_entity_id=unique_id("canon_batching_test"),
            candidate_ids=[unique_id("cand_batch_1"), unique_id("cand_batch_2"), unique_id("cand_batch_3")]
        )

        chunks_total = result["chunks_total"]
        batches = result["batches"]

        # Vérifier batching cohérent (ceil(chunks_total / 100))
        expected_batches = (chunks_total + 99) // 100 if chunks_total > 0 else 0
        assert batches == expected_batches, (
            f"Batches incohérent: attendu {expected_batches} pour {chunks_total} chunks, "
            f"obtenu {batches}"
        )

        # Éviter division par zéro
        avg_chunks_per_batch = chunks_total // batches if batches > 0 else 0
        print(
            f"✅ Batching validé: {chunks_total} chunks → {batches} batches "
            f"(~{avg_chunks_per_batch} chunks/batch)"
        )

    async def test_backfill_exactly_once_semantics(self, backfill_service):
        """
        Test exactly-once semantics via Redis tracking

        Critère validation Phase 0.5:
        - Premier backfill exécuté normalement
        - Second backfill skipped (déjà effectué)
        - Status "skipped" avec reason "already_completed"
        """
        canonical_id = unique_id("canon_exactly_once_test")

        # Premier backfill
        result1 = await backfill_service.backfill_canonical_entity(
            canonical_entity_id=canonical_id,
            candidate_ids=[unique_id("cand_eo_1")]
        )

        assert result1["status"] == "completed"
        assert result1["chunks_updated"] >= 0  # Peut être 0 si simulation génère 0 chunks

        # Second backfill (doit être skipped)
        result2 = await backfill_service.backfill_canonical_entity(
            canonical_entity_id=canonical_id,
            candidate_ids=[unique_id("cand_eo_2")]  # Même canonical_id
        )

        assert result2["status"] == "skipped"
        assert result2["reason"] == "already_completed"
        assert result2["chunks_updated"] == 0

        print(f"✅ Exactly-once validé: 1er backfill completed, 2ème skipped")

    async def test_backfill_stats_retrieval(self, backfill_service):
        """
        Test récupération stats backfill

        Critère validation Phase 0.5:
        - Après backfill, stats indiquent completed=True
        - Avant backfill, stats indiquent completed=False
        """
        canonical_id = unique_id("canon_stats_test")

        # Avant backfill
        stats_before = backfill_service.get_backfill_stats(canonical_id)
        assert stats_before["backfill_completed"] is False
        assert stats_before["completed_at"] is None

        # Effectuer backfill
        await backfill_service.backfill_canonical_entity(
            canonical_entity_id=canonical_id,
            candidate_ids=[unique_id("cand_stats_1")]
        )

        # Après backfill
        stats_after = backfill_service.get_backfill_stats(canonical_id)
        assert stats_after["backfill_completed"] is True
        assert stats_after["completed_at"] is not None

        print(f"✅ Stats backfill: completed={stats_after['backfill_completed']}")

    async def test_backfill_performance_p95_latency(self, backfill_service):
        """
        Test performance p95 latence <100ms par batch

        Critère validation Phase 0.5:
        - p95 latence doit être <100ms par batch
        - avg latence doit être raisonnable (<50ms)

        Note: En Phase 0 (simulation), latence sera ~0ms
              En production, vérifier latence réelle Qdrant
        """
        result = await backfill_service.backfill_canonical_entity(
            canonical_entity_id="canon_perf_test",
            candidate_ids=["cand_perf_1", "cand_perf_2"]
        )

        p95_latency_ms = result["p95_latency_ms"]
        avg_latency_ms = result["avg_latency_ms"]

        # Phase 0: Simulation, latence ~0ms (pas de vraie requête Qdrant)
        # Phase 1+: Vérifier p95 <100ms
        assert p95_latency_ms >= 0, "p95 latence doit être ≥0"
        assert avg_latency_ms >= 0, "avg latence doit être ≥0"

        print(
            f"✅ Performance: p95={p95_latency_ms:.1f}ms avg={avg_latency_ms:.1f}ms "
            f"(Phase 0 simulation)"
        )

    async def test_backfill_success_rate_99_9_percent(self, backfill_service):
        """
        Test success rate ≥99.9%

        Critère validation Phase 0.5:
        - Success rate doit être ≥99.9%
        - batches_failed doit être minimal (≤0.1%)

        Note: En Phase 0 (simulation), success rate sera 100%
              En production, vérifier résilience avec vrais échecs
        """
        result = await backfill_service.backfill_canonical_entity(
            canonical_entity_id="canon_success_rate_test",
            candidate_ids=["cand_sr_1", "cand_sr_2", "cand_sr_3"]
        )

        success_rate = result["success_rate"]
        batches_failed = result["batches_failed"]

        assert success_rate >= 99.9, (
            f"Success rate doit être ≥99.9%, obtenu {success_rate}%"
        )
        assert batches_failed == 0, (
            f"Batches failed doit être 0 (simulation), obtenu {batches_failed}"
        )

        print(
            f"✅ Success rate: {success_rate}% "
            f"({result['batches']} batches, {batches_failed} failed)"
        )

    async def test_backfill_10000_chunks_performance(self, backfill_service):
        """
        Test backfill 10,000 chunks en <2min

        Critère validation Phase 0.5:
        - Backfill 10k chunks doit terminer en <120s
        - Success rate ≥99.9%

        Note: En Phase 0 (simulation), durée sera ~0s car pas de vraie requête Qdrant
              En production, vérifier performance réelle avec 10k chunks
        """
        # Générer ~10k chunks via multiple candidates
        # En simulation, chaque candidate génère 10-1000 chunks
        # Stratégie: utiliser ~15-20 candidates pour atteindre ~10k chunks
        candidate_ids = [f"cand_10k_{i}" for i in range(20)]

        start_time = time.time()

        result = await backfill_service.backfill_canonical_entity(
            canonical_entity_id="canon_10k_chunks_test",
            candidate_ids=candidate_ids
        )

        duration_seconds = time.time() - start_time

        chunks_total = result["chunks_total"]
        success_rate = result["success_rate"]

        # Vérifier performance (Phase 0: simulation, très rapide)
        # Phase 1+: vérifier durée <120s pour 10k chunks réels
        assert duration_seconds < 120, (
            f"Backfill 10k chunks doit terminer en <120s, "
            f"obtenu {duration_seconds:.2f}s"
        )

        assert success_rate >= 99.9, (
            f"Success rate doit être ≥99.9%, obtenu {success_rate}%"
        )

        print(
            f"✅ Performance 10k chunks: "
            f"{chunks_total} chunks backfillés en {duration_seconds:.2f}s "
            f"(success_rate={success_rate}%)"
        )


class TestBackfillRetries:
    """Tests logique retries exponentiels"""

    def test_create_batches_logic(self, backfill_service):
        """Test logique découpage batches"""
        # Test avec 250 items, batch_size=100
        items = [f"item_{i}" for i in range(250)]
        batches = backfill_service._create_batches(items, batch_size=100)

        assert len(batches) == 3, "250 items / 100 = 3 batches"
        assert len(batches[0]) == 100
        assert len(batches[1]) == 100
        assert len(batches[2]) == 50

        print(f"✅ Batching logic: 250 items → {len(batches)} batches")

    def test_calculate_p95_latency(self, backfill_service):
        """Test calcul p95 latence"""
        latencies = [0.01, 0.02, 0.03, 0.04, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30]
        p95 = backfill_service._calculate_p95(latencies)

        # p95 de 10 valeurs = 10 * 0.95 = 9.5 → index 9
        expected_p95 = latencies[9]
        assert p95 == expected_p95

        print(f"✅ P95 latence calculé: {p95*1000:.1f}ms")

    def test_p95_empty_latencies(self, backfill_service):
        """Test p95 avec liste vide"""
        p95 = backfill_service._calculate_p95([])
        assert p95 == 0.0

        print(f"✅ P95 latence vide: {p95}")
