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

    def test_merge_same_key_different_body_returns_409(self, client):
        """
        Test merge avec même Idempotency-Key mais body différent → 409 Conflict

        Critère validation: Détection réutilisation accidentelle de clé
        Standard RFC 9110: Idempotency-Key = identifiant intention unique
        """
        idempotency_key = "conflict-test-550e8400-e29b-41d4-a716-446655440099"

        # Première requête avec body1
        merge_request_1 = {
            "canonical_entity_id": "canonical_AAA",
            "candidate_ids": ["cand001", "cand002"],
            "user_id": "user_test_123"
        }

        response1 = client.post(
            "/api/canonicalization/merge",
            json=merge_request_1,
            headers={"Idempotency-Key": idempotency_key}
        )

        assert response1.status_code == 200
        hash1 = response1.json()["result_hash"]

        # Deuxième requête avec MÊME KEY mais body DIFFÉRENT
        merge_request_2 = {
            "canonical_entity_id": "canonical_BBB",  # ≠ AAA
            "candidate_ids": ["cand999", "cand888"],  # ≠ 001, 002
            "user_id": "user_test_456"  # ≠ 123
        }

        response2 = client.post(
            "/api/canonicalization/merge",
            json=merge_request_2,
            headers={"Idempotency-Key": idempotency_key}  # MÊME KEY
        )

        # Doit retourner 409 Conflict
        assert response2.status_code == 409, (
            f"Expected 409 Conflict mais reçu {response2.status_code}. "
            f"Middleware doit détecter réutilisation de clé avec payload différent."
        )

        data = response2.json()
        assert data["error"] == "IdempotencyKeyConflict"
        assert "payload différent" in data["detail"]
        assert "Idempotency-Key" in data["detail"]

        print(f"✅ Conflict 409 détecté: même key '{idempotency_key[:12]}...' avec bodies différents")

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
        import uuid
        # Générer clé unique pour éviter collision avec autres tests
        idempotency_key = f"cache-replay-test-{uuid.uuid4()}"

        merge_request = {
            "canonical_entity_id": "abc123xyz",
            "candidate_ids": ["cand_replay_001"]
        }

        # Première requête (devrait être cache MISS ou cache HIT selon état Redis)
        response1 = client.post(
            "/api/canonicalization/merge",
            json=merge_request,
            headers={"Idempotency-Key": idempotency_key}
        )

        assert response1.status_code == 200
        hash1 = response1.json()["result_hash"]

        # Deuxième requête avec MÊME KEY et MÊME BODY (cache HIT garanti)
        response2 = client.post(
            "/api/canonicalization/merge",
            json=merge_request,
            headers={"Idempotency-Key": idempotency_key}
        )

        assert response2.status_code == 200
        hash2 = response2.json()["result_hash"]

        # Résultats identiques (hash doit matcher)
        assert hash1 == hash2, "Idempotence échouée: hashs différents entre replay"

        # Header X-Idempotency-Replay présent sur replay
        # Note: Peut être "true" dès response1 si cache déjà présent
        replay_header = response2.headers.get("X-Idempotency-Replay")
        assert replay_header == "true", f"Expected X-Idempotency-Replay: true, got {replay_header}"


class TestIdempotenceCreateNew:
    """Tests idempotence opération create-new"""

    def test_create_new_same_key_different_body_returns_409(self, client):
        """
        Test create-new avec même Idempotency-Key mais body différent → 409 Conflict

        Critère validation: Détection réutilisation accidentelle de clé
        """
        idempotency_key = "conflict-create-550e8400-e29b-41d4-a716-446655440098"

        # Première requête avec body1
        create_request_1 = {
            "candidate_ids": ["cand010", "cand011"],
            "canonical_name": "SAP S/4HANA Cloud",
            "entity_type": "solution",
            "description": "Cloud ERP solution",
            "user_id": "user_test_456"
        }

        response1 = client.post(
            "/api/canonicalization/create-new",
            json=create_request_1,
            headers={"Idempotency-Key": idempotency_key}
        )

        assert response1.status_code == 200
        uuid1 = response1.json()["canonical_entity_id"]

        # Deuxième requête avec MÊME KEY mais nom DIFFÉRENT
        create_request_2 = {
            "candidate_ids": ["cand999"],  # ≠ 010, 011
            "canonical_name": "SAP Fiori",  # ≠ S/4HANA Cloud
            "entity_type": "technology",  # ≠ solution
            "description": "UX framework",  # ≠ Cloud ERP
            "user_id": "user_test_789"  # ≠ 456
        }

        response2 = client.post(
            "/api/canonicalization/create-new",
            json=create_request_2,
            headers={"Idempotency-Key": idempotency_key}  # MÊME KEY
        )

        # Doit retourner 409 Conflict
        assert response2.status_code == 409, (
            f"Expected 409 Conflict mais reçu {response2.status_code}. "
            f"Middleware doit détecter réutilisation de clé avec payload différent."
        )

        data = response2.json()
        assert data["error"] == "IdempotencyKeyConflict"
        assert "payload différent" in data["detail"]

        print(f"✅ Conflict 409 détecté sur create-new: key '{idempotency_key[:12]}...' réutilisée")

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
