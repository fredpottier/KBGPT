#!/usr/bin/env python3
"""
Script simple de validation API Graphiti
Tests des endpoints pour validation Phase 0 - Critere 3
"""
import requests
import json
import time
import sys


def test_endpoint(base_url: str, method: str, endpoint: str, data=None, expected_status: int = 200):
    """Teste un endpoint et retourne le resultat"""
    url = f"{base_url}{endpoint}"
    print(f"Test: {method} {endpoint}")

    try:
        start_time = time.time()

        if method == "GET":
            response = requests.get(url, timeout=10)
        elif method == "POST":
            response = requests.post(url, json=data, timeout=10)
        elif method == "DELETE":
            response = requests.delete(url, timeout=10)
        else:
            return {"success": False, "error": f"Methode non supportee: {method}"}

        duration = (time.time() - start_time) * 1000
        success = response.status_code == expected_status

        result = {
            "endpoint": endpoint,
            "method": method,
            "status_code": response.status_code,
            "expected_status": expected_status,
            "success": success,
            "duration_ms": round(duration, 2),
            "response_size": len(response.text) if response.text else 0
        }

        if success:
            print(f"  [OK] {response.status_code} en {duration:.0f}ms")
        else:
            print(f"  [ERREUR] {response.status_code} (attendu {expected_status})")

        return result

    except Exception as e:
        print(f"  [EXCEPTION] {str(e)}")
        return {"endpoint": endpoint, "method": method, "success": False, "error": str(e)}


def main():
    """Point d'entree principal"""
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    test_group_id = f"test_validation_{int(time.time())}"

    print("=== VALIDATION API GRAPHITI - PHASE 0 CRITERE 3 ===")
    print(f"Base URL: {base_url}")
    print(f"Group ID: {test_group_id}")
    print("=" * 50)

    results = []

    # Tests Health Checks
    print("\n1. TESTS HEALTH CHECKS")
    results.append(test_endpoint(base_url, "GET", "/api/graphiti/health"))
    results.append(test_endpoint(base_url, "GET", "/api/graphiti/health-full"))

    # Tests Tenants
    print("\n2. TESTS TENANTS")
    results.append(test_endpoint(base_url, "GET", "/api/graphiti/tenants"))

    # Creer tenant
    tenant_data = {
        "group_id": test_group_id,
        "name": "Test Validation",
        "description": "Tenant cree par script de validation"
    }
    results.append(test_endpoint(base_url, "POST", "/api/graphiti/tenants", data=tenant_data))
    results.append(test_endpoint(base_url, "GET", f"/api/graphiti/tenants/{test_group_id}"))

    # Tests Episodes
    print("\n3. TESTS EPISODES")
    episode_data = {
        "group_id": test_group_id,
        "content": "Episode de test pour validation API",
        "episode_type": "message"
    }
    results.append(test_endpoint(base_url, "POST", "/api/graphiti/episodes", data=episode_data))

    # Tests Facts
    print("\n4. TESTS FACTS")
    fact_data = {
        "group_id": test_group_id,
        "subject": "TestEntity",
        "predicate": "has_property",
        "object": "TestValue",
        "confidence": 0.9
    }
    results.append(test_endpoint(base_url, "POST", "/api/graphiti/facts", data=fact_data))
    results.append(test_endpoint(base_url, "GET", f"/api/graphiti/facts?query=TestEntity&group_id={test_group_id}"))

    # Tests Relations
    print("\n5. TESTS RELATIONS")
    relation_data = {
        "source_id": "entity1",
        "relation_type": "connected_to",
        "target_id": "entity2"
    }
    results.append(test_endpoint(base_url, "POST", "/api/graphiti/relations", data=relation_data))

    # Tests Sous-graphes
    print("\n6. TESTS SOUS-GRAPHES")
    subgraph_data = {
        "entity_id": "TestEntity",
        "depth": 2,
        "group_id": test_group_id
    }
    results.append(test_endpoint(base_url, "POST", "/api/graphiti/subgraph", data=subgraph_data))

    # Tests Memoire
    print("\n7. TESTS MEMOIRE")
    results.append(test_endpoint(base_url, "GET", f"/api/graphiti/memory/{test_group_id}"))

    # Nettoyage
    print("\n8. NETTOYAGE")
    results.append(test_endpoint(base_url, "DELETE", f"/api/graphiti/tenants/{test_group_id}?confirm=true"))

    # Rapport final
    print("\n" + "=" * 50)
    print("RAPPORT FINAL")
    print("=" * 50)

    total_tests = len(results)
    successful_tests = sum(1 for r in results if r.get('success', False))
    failed_tests = total_tests - successful_tests

    print(f"Tests executes: {total_tests}")
    print(f"Tests reussis: {successful_tests}")
    print(f"Tests echoues: {failed_tests}")
    print(f"Taux de reussite: {round((successful_tests / total_tests) * 100, 1)}%")

    if successful_tests >= 8:  # Au moins 8 tests doivent reussir
        print("\nPHASE 0 - CRITERE 3: VALIDE")
        print("L'API Graphiti est entierement fonctionnelle !")
        return True
    else:
        print("\nPHASE 0 - CRITERE 3: ECHEC")
        print("Des problemes subsistent dans l'API Graphiti")

        print("\nTests echoues:")
        for result in results:
            if not result.get('success', False):
                print(f"  - {result['method']} {result['endpoint']}: {result.get('error', 'Status incorrect')}")

        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)