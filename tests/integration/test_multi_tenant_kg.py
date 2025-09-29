"""
Tests d'intégration Phase 2 - Isolation Multi-Tenant Knowledge Graph
Valide l'isolation complète entre utilisateurs et la séparation Corporate/Personnel
"""

import pytest
from fastapi.testclient import TestClient
from knowbase.api.main import create_app


@pytest.fixture
def client():
    """Client de test FastAPI"""
    app = create_app()
    return TestClient(app)


@pytest.fixture
def test_users():
    """Utilisateurs de test"""
    return {
        "user1": "user_test_1",
        "user2": "user_test_2",
        "invalid": "user_invalid_xyz"
    }


class TestMultiTenantIsolation:
    """Tests d'isolation multi-tenant"""

    def test_corporate_mode_sans_header(self, client):
        """Test mode Corporate par défaut (sans X-User-ID)"""
        response = client.get("/api/knowledge-graph/health")

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "healthy"
        assert data["mode"] == "corporate"
        assert data["group_id"] == "corporate"
        assert data.get("user_id") is None

    def test_personal_mode_avec_header(self, client, test_users):
        """Test mode Personnel avec X-User-ID valide"""
        response = client.get(
            "/api/knowledge-graph/health",
            headers={"X-User-ID": test_users["user1"]}
        )

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "healthy"
        assert data["mode"] == "personnel"
        assert data["group_id"] == f"user_{test_users['user1']}"
        assert data["user_id"] == test_users["user1"]

    def test_utilisateur_invalide_rejete(self, client, test_users):
        """Test rejet utilisateur invalide"""
        response = client.get(
            "/api/knowledge-graph/health",
            headers={"X-User-ID": test_users["invalid"]}
        )

        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert "non trouvé" in data["detail"].lower()

    def test_isolation_creation_entite(self, client, test_users):
        """Test isolation création entité entre utilisateurs"""
        entity_data = {
            "name": "Test Entity User 1",
            "entity_type": "concept",
            "description": "Entité créée par user1"
        }

        # User1 crée une entité
        response1 = client.post(
            "/api/knowledge-graph/entities",
            json=entity_data,
            headers={"X-User-ID": test_users["user1"]}
        )

        assert response1.status_code == 200
        entity_id = response1.json()["uuid"]

        # User1 peut récupérer son entité
        response_user1_get = client.get(
            f"/api/knowledge-graph/entities/{entity_id}",
            headers={"X-User-ID": test_users["user1"]}
        )
        assert response_user1_get.status_code == 200

        # User2 NE DOIT PAS voir l'entité de User1 (même avec UUID connu)
        response_user2_get = client.get(
            f"/api/knowledge-graph/entities/{entity_id}",
            headers={"X-User-ID": test_users["user2"]}
        )
        assert response_user2_get.status_code == 404

    def test_isolation_cache_uuid_connu(self, client, test_users):
        """
        Test CRITIQUE : Vérifier qu'on ne peut pas bypasser l'isolation
        en utilisant un UUID connu d'un autre utilisateur
        (Correction audit Codex #2)
        """
        # User1 crée une entité
        entity_user1 = {
            "name": "Entity User1 Private",
            "entity_type": "concept",
            "description": "Entité strictement privée user1"
        }

        response_create = client.post(
            "/api/knowledge-graph/entities",
            json=entity_user1,
            headers={"X-User-ID": test_users["user1"]}
        )
        assert response_create.status_code == 200
        entity_id_user1 = response_create.json()["uuid"]

        # User1 accède plusieurs fois pour mettre en cache
        for _ in range(3):
            response = client.get(
                f"/api/knowledge-graph/entities/{entity_id_user1}",
                headers={"X-User-ID": test_users["user1"]}
            )
            assert response.status_code == 200

        # Maintenant l'entité est certainement en cache
        # User2 tente d'y accéder avec l'UUID connu (attaque)
        response_attack = client.get(
            f"/api/knowledge-graph/entities/{entity_id_user1}",
            headers={"X-User-ID": test_users["user2"]}
        )

        # DOIT échouer avec 404 malgré le cache
        assert response_attack.status_code == 404, \
            "FAILLE SÉCURITÉ: User2 a pu accéder à l'entité de User1 via le cache!"

    def test_isolation_liste_relations(self, client, test_users):
        """Test isolation listage relations entre utilisateurs"""
        # User1 liste ses relations
        response1 = client.get(
            "/api/knowledge-graph/relations",
            headers={"X-User-ID": test_users["user1"]}
        )
        assert response1.status_code == 200
        relations_user1 = response1.json()

        # User2 liste ses relations
        response2 = client.get(
            "/api/knowledge-graph/relations",
            headers={"X-User-ID": test_users["user2"]}
        )
        assert response2.status_code == 200
        relations_user2 = response2.json()

        # Les listes doivent être indépendantes (pas de fuite)
        # Note: ce test suppose des données initiales différentes
        # En pratique, sans données, les listes seront vides pour les deux
        assert isinstance(relations_user1, list)
        assert isinstance(relations_user2, list)

    def test_isolation_relations_personnel_vs_autres(self, client, test_users):
        """Créer une relation personnelle et vérifier l'isolation vs autres utilisateurs et corporate"""
        # Créer deux entités pour user1
        e1 = {
            "name": "U1 Entite A",
            "entity_type": "concept",
            "description": "Entite perso A"
        }
        e2 = {
            "name": "U1 Entite B",
            "entity_type": "concept",
            "description": "Entite perso B"
        }
        r1 = client.post("/api/knowledge-graph/entities", json=e1, headers={"X-User-ID": test_users["user1"]})
        r2 = client.post("/api/knowledge-graph/entities", json=e2, headers={"X-User-ID": test_users["user1"]})
        assert r1.status_code == 200 and r2.status_code == 200
        id1 = r1.json()["uuid"]
        id2 = r2.json()["uuid"]

        # Créer la relation pour user1
        rel_payload = {
            "source_entity_id": id1,
            "target_entity_id": id2,
            "relation_type": "relates_to",
            "description": "Lien perso U1"
        }
        rr = client.post("/api/knowledge-graph/relations", json=rel_payload, headers={"X-User-ID": test_users["user1"]})
        assert rr.status_code == 200
        rel_id = rr.json()["uuid"]

        # User1 voit la relation
        lr_u1 = client.get("/api/knowledge-graph/relations", headers={"X-User-ID": test_users["user1"]})
        assert lr_u1.status_code == 200
        rel_ids_u1 = {r["uuid"] for r in lr_u1.json()}
        assert rel_id in rel_ids_u1

        # User2 ne la voit pas
        lr_u2 = client.get("/api/knowledge-graph/relations", headers={"X-User-ID": test_users["user2"]})
        assert lr_u2.status_code == 200
        rel_ids_u2 = {r.get("uuid") for r in lr_u2.json()}
        assert rel_id not in rel_ids_u2

        # Corporate ne la voit pas
        lr_corp = client.get("/api/knowledge-graph/relations")
        assert lr_corp.status_code == 200
        rel_ids_corp = {r.get("uuid") for r in lr_corp.json()}
        assert rel_id not in rel_ids_corp

    def test_isolation_sous_graphe(self, client, test_users):
        """Sous-graphe doit respecter le groupe contextuel"""
        # Créer deux entités personnelles et une relation (user2)
        e1 = client.post(
            "/api/knowledge-graph/entities",
            json={"name": "U2 Node A", "entity_type": "concept"},
            headers={"X-User-ID": test_users["user2"]},
        )
        e2 = client.post(
            "/api/knowledge-graph/entities",
            json={"name": "U2 Node B", "entity_type": "concept"},
            headers={"X-User-ID": test_users["user2"]},
        )
        assert e1.status_code == 200 and e2.status_code == 200
        id1 = e1.json()["uuid"]
        id2 = e2.json()["uuid"]
        rel = client.post(
            "/api/knowledge-graph/relations",
            json={
                "source_entity_id": id1,
                "target_entity_id": id2,
                "relation_type": "contains"
            },
            headers={"X-User-ID": test_users["user2"]},
        )
        assert rel.status_code == 200

        # Sous-graphe pour user2: OK
        sg_u2 = client.post(
            "/api/knowledge-graph/subgraph",
            json={"entity_id": id1, "depth": 2},
            headers={"X-User-ID": test_users["user2"]},
        )
        assert sg_u2.status_code == 200
        data = sg_u2.json()
        assert data.get("total_nodes", 0) >= 1

        # Sous-graphe corporate sur l'entité perso user2: refus (entité inconnue dans ce groupe)
        sg_corp = client.post(
            "/api/knowledge-graph/subgraph",
            json={"entity_id": id1, "depth": 2}
        )
        # Service lève ValueError -> 400 côté router
        assert sg_corp.status_code == 400

    def test_isolation_stats(self, client, test_users):
        """Test statistiques isolées par utilisateur"""
        # Stats Corporate
        response_corporate = client.get("/api/knowledge-graph/stats")
        assert response_corporate.status_code == 200
        stats_corporate = response_corporate.json()

        # Stats User1
        response_user1 = client.get(
            "/api/knowledge-graph/stats",
            headers={"X-User-ID": test_users["user1"]}
        )
        assert response_user1.status_code == 200
        stats_user1 = response_user1.json()

        # Les stats doivent être différentes (groupes distincts)
        assert stats_corporate.get("group_id") == "corporate"
        assert stats_user1.get("group_id") == test_users["user1"]

    def test_headers_contextuels(self, client, test_users):
        """Test présence des headers contextuels X-Context-*"""
        response = client.get(
            "/api/knowledge-graph/health",
            headers={"X-User-ID": test_users["user1"]}
        )

        assert response.status_code == 200

        # Vérifier les headers de contexte
        assert "x-context-group-id" in response.headers
        assert "x-context-personal" in response.headers

        assert response.headers["x-context-group-id"] == f"user_{test_users['user1']}"
        assert response.headers["x-context-personal"] == "true"


class TestAutoProvisioning:
    """Tests auto-provisioning groupes utilisateur"""

    def test_premier_acces_utilisateur(self, client, test_users):
        """Test création automatique groupe au premier accès"""
        # Premier accès user1 - devrait créer le groupe automatiquement
        response = client.post(
            "/api/knowledge-graph/entities",
            json={
                "name": "First Entity",
                "entity_type": "concept",
                "description": "Première entité déclenchant auto-provisioning"
            },
            headers={"X-User-ID": test_users["user1"]}
        )

        # Devrait réussir sans erreur (auto-provisioning transparent)
        assert response.status_code == 200

        # Vérifier que les métadonnées utilisateur ont été mises à jour
        # (nécessite endpoint /api/users/{user_id} pour validation complète)

    def test_acces_subsequents_utilisateur(self, client, test_users):
        """Test accès ultérieurs utilisent le groupe existant"""
        # Premier accès
        response1 = client.get(
            "/api/knowledge-graph/health",
            headers={"X-User-ID": test_users["user1"]}
        )
        assert response1.status_code == 200

        # Deuxième accès - devrait réutiliser le groupe
        response2 = client.get(
            "/api/knowledge-graph/health",
            headers={"X-User-ID": test_users["user1"]}
        )
        assert response2.status_code == 200

        # Les group_id doivent être identiques
        assert response1.json()["group_id"] == response2.json()["group_id"]


class TestCorporatePersonnelCoexistence:
    """Tests coexistence KG Corporate et Personnel"""

    def test_entite_corporate_visible_par_tous(self, client, test_users):
        """Test entité Corporate visible par tous les modes"""
        entity_corporate = {
            "name": "Corporate Entity",
            "entity_type": "concept",
            "description": "Entité corporate partagée"
        }

        # Créer entité en mode Corporate
        response_create = client.post(
            "/api/knowledge-graph/entities",
            json=entity_corporate
        )
        assert response_create.status_code == 200
        entity_id = response_create.json()["uuid"]

        # Accessible en mode Corporate
        response_corporate = client.get(
            f"/api/knowledge-graph/entities/{entity_id}"
        )
        assert response_corporate.status_code == 200

        # Note: En mode Personnel, l'entité Corporate n'est pas visible
        # car l'isolation est stricte. Si besoin de recherche hybride,
        # cela sera implémenté dans le service de recherche.

    def test_entite_personnelle_invisible_en_corporate(self, client, test_users):
        """Test entité Personnel invisible en mode Corporate"""
        entity_personal = {
            "name": "Personal Entity User1",
            "entity_type": "concept",
            "description": "Entité personnelle user1"
        }

        # User1 crée une entité personnelle
        response_create = client.post(
            "/api/knowledge-graph/entities",
            json=entity_personal,
            headers={"X-User-ID": test_users["user1"]}
        )
        assert response_create.status_code == 200
        entity_id = response_create.json()["uuid"]

        # Accessible par User1
        response_user1 = client.get(
            f"/api/knowledge-graph/entities/{entity_id}",
            headers={"X-User-ID": test_users["user1"]}
        )
        assert response_user1.status_code == 200

        # Invisible en mode Corporate
        response_corporate = client.get(
            f"/api/knowledge-graph/entities/{entity_id}"
        )
        assert response_corporate.status_code == 404


class TestCorrectGroupIdResponses:
    """Tests validation group_id correct dans les réponses API (Audit Codex #2.5)"""

    def test_entity_creation_returns_correct_group_id(self, client, test_users):
        """Test que EntityResponse contient le bon group_id (personnel)"""
        entity_data = {
            "name": "Test Entity Group ID",
            "entity_type": "concept",
            "description": "Test group_id dans réponse"
        }

        # User1 crée une entité personnelle
        response = client.post(
            "/api/knowledge-graph/entities",
            json=entity_data,
            headers={"X-User-ID": test_users["user1"]}
        )

        assert response.status_code == 200
        data = response.json()

        # ✅ CRITIQUE: Le group_id dans la réponse DOIT être user_user_test_1
        expected_group_id = f"user_{test_users['user1']}"
        assert "group_id" in data, "group_id manquant dans EntityResponse"
        assert data["group_id"] == expected_group_id, \
            f"group_id incorrect: {data['group_id']} != {expected_group_id}"

    def test_relation_creation_returns_correct_group_id(self, client, test_users):
        """Test que RelationResponse contient le bon group_id (personnel)"""
        # Créer deux entités d'abord
        entity1_data = {
            "name": "Source Entity Group Test",
            "entity_type": "concept",
            "description": "Source"
        }
        entity2_data = {
            "name": "Target Entity Group Test",
            "entity_type": "concept",
            "description": "Target"
        }

        headers = {"X-User-ID": test_users["user1"]}

        response1 = client.post("/api/knowledge-graph/entities", json=entity1_data, headers=headers)
        response2 = client.post("/api/knowledge-graph/entities", json=entity2_data, headers=headers)

        assert response1.status_code == 200
        assert response2.status_code == 200

        entity1_id = response1.json()["uuid"]
        entity2_id = response2.json()["uuid"]

        # Créer relation
        relation_data = {
            "source_entity_id": entity1_id,
            "target_entity_id": entity2_id,
            "relation_type": "relates_to",
            "description": "Test relation group_id"
        }

        response = client.post(
            "/api/knowledge-graph/relations",
            json=relation_data,
            headers=headers
        )

        assert response.status_code == 200
        data = response.json()

        # ✅ CRITIQUE: Le group_id dans la réponse DOIT être user_user_test_1
        expected_group_id = f"user_{test_users['user1']}"
        assert "group_id" in data, "group_id manquant dans RelationResponse"
        assert data["group_id"] == expected_group_id, \
            f"group_id incorrect: {data['group_id']} != {expected_group_id}"

    def test_corporate_entity_returns_corporate_group_id(self, client):
        """Test que EntityResponse en mode corporate retourne 'corporate'"""
        entity_data = {
            "name": "Corporate Entity Group Test",
            "entity_type": "concept",
            "description": "Test group_id corporate"
        }

        # Sans X-User-ID = mode corporate
        response = client.post(
            "/api/knowledge-graph/entities",
            json=entity_data
        )

        assert response.status_code == 200
        data = response.json()

        # ✅ En mode corporate, group_id doit être "corporate"
        assert data["group_id"] == "corporate", \
            f"group_id incorrect en mode corporate: {data['group_id']}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
