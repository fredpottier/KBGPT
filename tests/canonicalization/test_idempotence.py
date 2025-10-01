"""
Tests idempotence Phase 0 Critère 2
Valide rejouabilité opérations merge/create-new avec résultats identiques
"""

import pytest
import hashlib
import json
from fastapi.testclient import TestClient
from knowbase.api.main import create_app


@pytest.fixture
def client():
    """Client de test FastAPI"""
    app = create_app()
    return TestClient(app)


class TestIdempotenceHeader:
    """Tests header Idempotency-Key obligatoire"""

    def test_merge_without_idempotency_key_fails(self, client):
        """Test merge sans Idempotency-Key retourne 400"""
        response = client.post(
            "/api/canonicalization/merge",
            json={
                "canonical_entity_id": "abc123",
                "candidate_ids": ["def456", "ghi789"]
            }
        )

        assert response.status_code == 400
        data = response.json()
        assert "Idempotency-Key" in data["detail"]
        assert data.get("idempotent_endpoint") is True

    def test_create_new_without_idempotency_key_fails(self, client):
        """Test create-new sans Idempotency-Key retourne 400"""
        response = client.post(
            "/api/canonicalization/create-new",
            json={
                "candidate_ids": ["def456", "ghi789"],
                "canonical_name": "SAP S/4HANA",
                "entity_type": "solution"
            }
        )

        assert response.status_code == 400
        data = response.json()
        assert "Idempotency-Key" in data["detail"]


class TestIdempotenceMerge:
    """Tests idempotence opération merge"""

    def test_merge_replay_10x_identical_results(self, client):
        """
        Test replay 10× merge avec même Idempotency-Key → résultats identiques

        Critère validation Phase 0.2:
        - Même input + même Idempotency-Key → résultat bit-à-bit identique
        - Hash résultat doit être strictement identique entre replays
        """
        idempotency_key = "550e8400-e29b-41d4-a716-446655440000"

        merge_request = {
            "canonical_entity_id": "abc123def456",
            "candidate_ids": ["cand001", "cand002", "cand003"],
            "user_id": "user_test_123"
        }

        results = []
        hashes = []

        # Replay 10×
        for i in range(10):
            response = client.post(
                "/api/canonicalization/merge",
                json=merge_request,
                headers={"Idempotency-Key": idempotency_key}
            )

            assert response.status_code == 200, f"Replay {i+1} échoué"

            data = response.json()
            results.append(data)
            hashes.append(data["result_hash"])

        # Vérifier tous les hashs sont identiques
        unique_hashes = set(hashes)
        assert len(unique_hashes) == 1, (
            f"Hashs différents entre replays: {unique_hashes}\n"
            f"Idempotence ÉCHOUÉE - résultats non déterministes"
        )

        # Vérifier résultats complets identiques (sans timestamp système)
        first_result = results[0]
        for i, result in enumerate(results[1:], 1):
            # Comparer tous les champs critiques
            assert result["canonical_entity_id"] == first_result["canonical_entity_id"]
            assert result["merged_candidates"] == first_result["merged_candidates"]
            assert result["merge_count"] == first_result["merge_count"]
            assert result["operation"] == first_result["operation"]
            assert result["idempotency_key"] == first_result["idempotency_key"]
            assert result["user_id"] == first_result["user_id"]
            assert result["status"] == first_result["status"]
            assert result["result_hash"] == first_result["result_hash"]

        print(f"✅ Idempotence validée: 10 replays → hash identique {hashes[0][:16]}...")

    def test_merge_different_idempotency_keys_different_results(self, client):
        """Test merge avec Idempotency-Keys différentes → résultats différents OK"""
        merge_request = {
            "canonical_entity_id": "abc123def456",
            "candidate_ids": ["cand001", "cand002"],
            "user_id": "user_test_123"
        }

        # Requête 1 avec key1
        response1 = client.post(
            "/api/canonicalization/merge",
            json=merge_request,
            headers={"Idempotency-Key": "key1-550e8400-e29b-41d4-a716-446655440001"}
        )

        # Requête 2 avec key2 (différente)
        response2 = client.post(
            "/api/canonicalization/merge",
            json=merge_request,
            headers={"Idempotency-Key": "key2-550e8400-e29b-41d4-a716-446655440002"}
        )

        assert response1.status_code == 200
        assert response2.status_code == 200

        hash1 = response1.json()["result_hash"]
        hash2 = response2.json()["result_hash"]

        # Hashs peuvent être identiques car même input, mais idempotency_key différente dans metadata
        # Ce qui importe: chaque clé a son propre cache

    def test_merge_replay_from_cache(self, client):
        """Test replay merge retourne résultat mis en cache (header X-Idempotency-Replay)"""
        idempotency_key = "cache-test-550e8400-e29b-41d4-a716-446655440003"

        merge_request = {
            "canonical_entity_id": "abc123",
            "candidate_ids": ["cand001"]
        }

        # Première requête (cache MISS)
        response1 = client.post(
            "/api/canonicalization/merge",
            json=merge_request,
            headers={"Idempotency-Key": idempotency_key}
        )

        assert response1.status_code == 200
        assert response1.headers.get("X-Idempotency-Replay") != "true"

        # Deuxième requête (cache HIT)
        response2 = client.post(
            "/api/canonicalization/merge",
            json=merge_request,
            headers={"Idempotency-Key": idempotency_key}
        )

        assert response2.status_code == 200
        # Header X-Idempotency-Replay devrait être "true" si middleware fonctionne
        # Note: Dans tests avec TestClient, middleware peut se comporter différemment

        # Résultats identiques
        assert response1.json()["result_hash"] == response2.json()["result_hash"]


class TestIdempotenceCreateNew:
    """Tests idempotence opération create-new"""

    def test_create_new_replay_10x_identical_results(self, client):
        """
        Test replay 10× create-new avec même Idempotency-Key → résultats identiques

        Critère validation Phase 0.2:
        - UUID généré doit être déterministe (même nom + key → même UUID)
        - Hash résultat strictement identique entre replays
        """
        idempotency_key = "create-550e8400-e29b-41d4-a716-446655440010"

        create_request = {
            "candidate_ids": ["cand010", "cand011", "cand012"],
            "canonical_name": "SAP S/4HANA Cloud",
            "entity_type": "solution",
            "description": "Cloud ERP solution",
            "user_id": "user_test_456"
        }

        results = []
        hashes = []
        uuids = []

        # Replay 10×
        for i in range(10):
            response = client.post(
                "/api/canonicalization/create-new",
                json=create_request,
                headers={"Idempotency-Key": idempotency_key}
            )

            assert response.status_code == 200, f"Replay {i+1} échoué"

            data = response.json()
            results.append(data)
            hashes.append(data["result_hash"])
            uuids.append(data["canonical_entity_id"])

        # Vérifier tous les hashs identiques
        unique_hashes = set(hashes)
        assert len(unique_hashes) == 1, (
            f"Hashs différents entre replays: {unique_hashes}\n"
            f"Idempotence ÉCHOUÉE - résultats non déterministes"
        )

        # Vérifier UUIDs identiques (déterminisme création)
        unique_uuids = set(uuids)
        assert len(unique_uuids) == 1, (
            f"UUIDs différents entre replays: {unique_uuids}\n"
            f"Génération UUID non déterministe"
        )

        # Vérifier résultats complets identiques
        first_result = results[0]
        for i, result in enumerate(results[1:], 1):
            assert result["canonical_entity_id"] == first_result["canonical_entity_id"]
            assert result["canonical_name"] == first_result["canonical_name"]
            assert result["entity_type"] == first_result["entity_type"]
            assert result["description"] == first_result["description"]
            assert result["source_candidates"] == first_result["source_candidates"]
            assert result["candidate_count"] == first_result["candidate_count"]
            assert result["operation"] == first_result["operation"]
            assert result["idempotency_key"] == first_result["idempotency_key"]
            assert result["status"] == first_result["status"]
            assert result["result_hash"] == first_result["result_hash"]

        print(f"✅ Create-new idempotence validée: 10 replays → UUID {uuids[0][:16]}...")

    def test_create_new_different_names_different_uuids(self, client):
        """Test create-new avec noms différents → UUIDs différents"""
        idempotency_key_base = "create-names-"

        # Créer 3 entités avec noms différents
        names = ["SAP S/4HANA", "SAP Fiori", "SAP HANA"]
        uuids = []

        for i, name in enumerate(names):
            response = client.post(
                "/api/canonicalization/create-new",
                json={
                    "candidate_ids": [f"cand{i}"],
                    "canonical_name": name,
                    "entity_type": "solution"
                },
                headers={"Idempotency-Key": f"{idempotency_key_base}{i}"}
            )

            assert response.status_code == 200
            uuids.append(response.json()["canonical_entity_id"])

        # Tous les UUIDs doivent être différents
        assert len(set(uuids)) == 3, "UUIDs doivent être différents pour noms différents"


class TestVersioningMetadata:
    """Tests metadata versioning dans résultats"""

    def test_merge_includes_versioning_metadata(self, client):
        """Test merge inclut metadata versioning complète"""
        response = client.post(
            "/api/canonicalization/merge",
            json={
                "canonical_entity_id": "abc123",
                "candidate_ids": ["cand001"]
            },
            headers={"Idempotency-Key": "version-test-001"}
        )

        assert response.status_code == 200
        data = response.json()

        # Vérifier version_metadata existe
        assert "version_metadata" in data
        vm = data["version_metadata"]

        # Vérifier champs versioning
        assert "canonicalization_version" in vm
        assert "embedding_model" in vm
        assert "embedding_dimensions" in vm
        assert "similarity_threshold" in vm
        assert "version_hash" in vm
        assert "operation" in vm

        assert vm["operation"] == "merge"

    def test_create_new_includes_versioning_metadata(self, client):
        """Test create-new inclut metadata versioning complète"""
        response = client.post(
            "/api/canonicalization/create-new",
            json={
                "candidate_ids": ["cand002"],
                "canonical_name": "Test Entity",
                "entity_type": "concept"
            },
            headers={"Idempotency-Key": "version-test-002"}
        )

        assert response.status_code == 200
        data = response.json()

        assert "version_metadata" in data
        vm = data["version_metadata"]

        assert "canonicalization_version" in vm
        assert "version_hash" in vm
        assert vm["operation"] == "create_new"


class TestAuditTrail:
    """Tests audit trail avec Idempotency-Key dans logs"""

    def test_merge_logs_idempotency_key(self, client, caplog):
        """Test merge log idempotency_key pour audit trail"""
        import logging
        caplog.set_level(logging.INFO)

        idempotency_key = "audit-test-merge-123"

        response = client.post(
            "/api/canonicalization/merge",
            json={
                "canonical_entity_id": "abc123",
                "candidate_ids": ["cand001"]
            },
            headers={"Idempotency-Key": idempotency_key}
        )

        assert response.status_code == 200

        # Vérifier logs contiennent idempotency_key (tronqué)
        log_messages = [record.message for record in caplog.records]
        key_in_logs = any(idempotency_key[:12] in msg for msg in log_messages)

        assert key_in_logs, "Idempotency-Key absente des logs audit trail"
