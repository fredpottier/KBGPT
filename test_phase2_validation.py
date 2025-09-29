"""
Script de validation Phase 2 - Knowledge Graph Multi-Tenant
Démontre et valide les 3 critères de la Phase 2:
1. Middleware X-User-ID → group_id
2. Auto-provisioning groupes utilisateur
3. Isolation multi-tenant complète
"""

import requests
import json
from typing import Dict, Any
import sys


BASE_URL = "http://localhost:8000"
API_URL = f"{BASE_URL}/api"


def print_section(title: str):
    """Affiche un titre de section"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


def print_result(test_name: str, success: bool, details: str = ""):
    """Affiche le résultat d'un test"""
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"{status} - {test_name}")
    if details:
        print(f"     {details}")


def test_corporate_mode() -> bool:
    """Test 1: Mode Corporate (sans X-User-ID)"""
    print_section("TEST 1 - Mode Corporate (défaut)")

    try:
        response = requests.get(f"{API_URL}/knowledge-graph/health")
        data = response.json()

        checks = {
            "Status 200": response.status_code == 200,
            "Mode corporate": data.get("mode") == "corporate",
            "Group ID corporate": data.get("group_id") == "corporate",
            "Pas de user_id": data.get("user_id") is None
        }

        all_pass = all(checks.values())

        for check_name, result in checks.items():
            print_result(check_name, result)

        if all_pass:
            print(f"\n📊 Réponse: {json.dumps(data, indent=2, ensure_ascii=False)}")

        return all_pass

    except Exception as e:
        print_result("Test Corporate", False, str(e))
        return False


def test_personal_mode(user_id: str = "user_test_1") -> bool:
    """Test 2: Mode Personnel (avec X-User-ID)"""
    print_section(f"TEST 2 - Mode Personnel (X-User-ID: {user_id})")

    try:
        headers = {"X-User-ID": user_id}
        response = requests.get(f"{API_URL}/knowledge-graph/health", headers=headers)
        data = response.json()

        expected_group_id = f"user_{user_id}"

        checks = {
            "Status 200": response.status_code == 200,
            "Mode personnel": data.get("mode") == "personnel",
            f"Group ID {expected_group_id}": data.get("group_id") == expected_group_id,
            f"User ID présent": data.get("user_id") == user_id,
            "Header X-Context-Group-ID": response.headers.get("x-context-group-id") == expected_group_id,
            "Header X-Context-Personal": response.headers.get("x-context-personal") == "true"
        }

        all_pass = all(checks.values())

        for check_name, result in checks.items():
            print_result(check_name, result)

        if all_pass:
            print(f"\n📊 Réponse: {json.dumps(data, indent=2, ensure_ascii=False)}")

        return all_pass

    except Exception as e:
        print_result("Test Personnel", False, str(e))
        return False


def test_invalid_user() -> bool:
    """Test 3: Rejet utilisateur invalide"""
    print_section("TEST 3 - Validation utilisateur (utilisateur invalide)")

    try:
        headers = {"X-User-ID": "user_invalid_xyz"}
        response = requests.get(f"{API_URL}/knowledge-graph/health", headers=headers)

        checks = {
            "Status 404": response.status_code == 404,
            "Message d'erreur présent": "detail" in response.json()
        }

        all_pass = all(checks.values())

        for check_name, result in checks.items():
            print_result(check_name, result)

        if all_pass:
            print(f"\n📊 Message erreur: {response.json().get('detail')}")

        return all_pass

    except Exception as e:
        print_result("Test validation", False, str(e))
        return False


def test_user_isolation() -> bool:
    """Test 4: Isolation entre utilisateurs"""
    print_section("TEST 4 - Isolation Multi-Tenant")

    user1 = "user_test_1"
    user2 = "user_test_2"

    try:
        # User1 crée une entité
        entity_data = {
            "name": "Entity User 1 Private",
            "entity_type": "concept",
            "description": "Entité privée de user1"
        }

        headers_user1 = {"X-User-ID": user1}
        response_create = requests.post(
            f"{API_URL}/knowledge-graph/entities",
            json=entity_data,
            headers=headers_user1
        )

        checks = {}

        if response_create.status_code != 200:
            print_result("Création entité user1", False, f"Status {response_create.status_code}")
            return False

        entity_id = response_create.json().get("uuid")
        print_result("Création entité user1", True, f"Entity ID: {entity_id}")

        # User1 peut voir son entité
        response_user1_get = requests.get(
            f"{API_URL}/knowledge-graph/entities/{entity_id}",
            headers=headers_user1
        )
        checks["User1 voit son entité"] = response_user1_get.status_code == 200

        # User2 NE DOIT PAS voir l'entité de user1
        headers_user2 = {"X-User-ID": user2}
        response_user2_get = requests.get(
            f"{API_URL}/knowledge-graph/entities/{entity_id}",
            headers=headers_user2
        )
        checks["User2 ne voit PAS l'entité user1 (404)"] = response_user2_get.status_code == 404

        # Corporate NE DOIT PAS voir l'entité personnelle
        response_corporate_get = requests.get(
            f"{API_URL}/knowledge-graph/entities/{entity_id}"
        )
        checks["Corporate ne voit PAS l'entité personnelle (404)"] = response_corporate_get.status_code == 404

        all_pass = all(checks.values())

        for check_name, result in checks.items():
            print_result(check_name, result)

        return all_pass

    except Exception as e:
        print_result("Test isolation", False, str(e))
        return False


def test_auto_provisioning() -> bool:
    """Test 5: Auto-provisioning groupe utilisateur"""
    print_section("TEST 5 - Auto-Provisioning Groupe Utilisateur")

    user_id = "user_test_1"

    try:
        # Premier accès devrait déclencher auto-provisioning
        headers = {"X-User-ID": user_id}

        # Créer une entité (déclenche auto-provisioning si nécessaire)
        entity_data = {
            "name": "Auto-provision Test Entity",
            "entity_type": "concept",
            "description": "Test auto-provisioning"
        }

        response = requests.post(
            f"{API_URL}/knowledge-graph/entities",
            json=entity_data,
            headers=headers
        )

        checks = {
            "Création réussie sans erreur": response.status_code == 200,
            "Entité retournée avec UUID": "uuid" in response.json()
        }

        all_pass = all(checks.values())

        for check_name, result in checks.items():
            print_result(check_name, result)

        if all_pass:
            print(f"\n✅ Auto-provisioning transparent pour {user_id}")
            print(f"📊 Entity créée: {response.json().get('uuid')}")

        return all_pass

    except Exception as e:
        print_result("Test auto-provisioning", False, str(e))
        return False


def main():
    """Exécution de tous les tests de validation Phase 2"""
    print("\n" + "🎯" * 40)
    print("  VALIDATION PHASE 2 - KNOWLEDGE GRAPH MULTI-TENANT")
    print("🎯" * 40)
    print(f"\nAPI URL: {API_URL}")
    print("Critères testés:")
    print("  1. Middleware X-User-ID → group_id")
    print("  2. Auto-provisioning groupes utilisateur")
    print("  3. Isolation multi-tenant complète")

    results = {
        "Mode Corporate": test_corporate_mode(),
        "Mode Personnel": test_personal_mode(),
        "Validation utilisateur": test_invalid_user(),
        "Isolation multi-tenant": test_user_isolation(),
        "Auto-provisioning": test_auto_provisioning()
    }

    # Résumé final
    print_section("RÉSUMÉ VALIDATION PHASE 2")

    total = len(results)
    passed = sum(1 for r in results.values() if r)

    for test_name, result in results.items():
        print_result(test_name, result)

    percentage = (passed / total) * 100

    print("\n" + "=" * 80)
    print(f"Score Final: {passed}/{total} tests passés ({percentage:.0f}%)")

    if percentage == 100:
        print("✅ PHASE 2 VALIDÉE À 100% - Architecture Multi-Tenant Fonctionnelle")
        return 0
    else:
        print(f"❌ PHASE 2 INCOMPLÈTE - {total - passed} tests échoués")
        print("   Corriger les problèmes avant de valider la Phase 2")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)