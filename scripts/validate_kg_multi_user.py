#!/usr/bin/env python3
"""
Script de validation Knowledge Graph Multi-Utilisateur - Phase 2
Tests complets des 3 critères d'achievement multi-tenant
"""

import requests
import json
import time
import sys
from typing import Dict, List, Any

# Configuration
BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
TEST_TIMEOUT = 15

class KGMultiUserValidator:
    """Validateur Knowledge Graph Multi-Utilisateur Phase 2"""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.results = []
        self.test_users = ["user_test_1", "user_test_2", "user_test_3"]
        self.user_entities = {}  # user_id -> [entity_ids]
        self.user_relations = {}  # user_id -> [relation_ids]

    def test_endpoint(self, method: str, endpoint: str, headers=None, data=None, expected_status: int = 200) -> Dict[str, Any]:
        """Teste un endpoint avec headers et retourne le résultat"""
        url = f"{self.base_url}{endpoint}"
        print(f"Test: {method} {endpoint} (headers: {headers})")

        try:
            start_time = time.time()
            headers = headers or {}

            if method == "GET":
                response = requests.get(url, headers=headers, timeout=TEST_TIMEOUT)
            elif method == "POST":
                response = requests.post(url, json=data, headers=headers, timeout=TEST_TIMEOUT)
            elif method == "DELETE":
                response = requests.delete(url, headers=headers, timeout=TEST_TIMEOUT)
            else:
                return {"success": False, "error": f"Méthode non supportée: {method}"}

            duration = (time.time() - start_time) * 1000
            success = response.status_code == expected_status

            result = {
                "endpoint": endpoint,
                "method": method,
                "headers": headers,
                "status_code": response.status_code,
                "expected_status": expected_status,
                "success": success,
                "duration_ms": round(duration, 2)
            }

            if success:
                print(f"  ✅ {response.status_code} en {duration:.0f}ms")
                try:
                    result["response_data"] = response.json()
                except:
                    result["response_data"] = response.text
            else:
                print(f"  ❌ {response.status_code} (attendu {expected_status})")
                result["error_details"] = response.text[:200]

            return result

        except Exception as e:
            print(f"  💥 Exception: {str(e)}")
            return {"endpoint": endpoint, "method": method, "success": False, "error": str(e)}

    def validate_phase_2(self) -> Dict[str, Any]:
        """Valide tous les critères de la Phase 2"""
        print("=== VALIDATION KNOWLEDGE GRAPH MULTI-UTILISATEUR - PHASE 2 ===")
        print("=" * 60)
        print(f"URL de base: {self.base_url}")
        print(f"Utilisateurs test: {', '.join(self.test_users)}")
        print("=" * 60)

        # Critère 1: Mapping X-User-ID → group_id
        print("\n1️⃣ CRITÈRE 1: MAPPING X-USER-ID → GROUP_ID")
        print("-" * 40)
        criterion_1_score = self._test_criterion_1()

        # Critère 2: Auto-provisioning groupes utilisateur
        print("\n2️⃣ CRITÈRE 2: AUTO-PROVISIONING GROUPES UTILISATEUR")
        print("-" * 40)
        criterion_2_score = self._test_criterion_2()

        # Critère 3: Isolation multi-tenant
        print("\n3️⃣ CRITÈRE 3: ISOLATION MULTI-TENANT")
        print("-" * 40)
        criterion_3_score = self._test_criterion_3()

        # Calcul du score global
        total_tests = len(self.results)
        successful_tests = sum(1 for r in self.results if r.get('success', False))
        success_rate = (successful_tests / total_tests) * 100 if total_tests > 0 else 0

        # Score par critère
        criteria_scores = {
            "criterion_1": criterion_1_score,
            "criterion_2": criterion_2_score,
            "criterion_3": criterion_3_score
        }

        return {
            "total_tests": total_tests,
            "successful_tests": successful_tests,
            "success_rate": round(success_rate, 1),
            "criteria_scores": criteria_scores,
            "phase_2_validated": all(score >= 0.8 for score in criteria_scores.values()),
            "detailed_results": self.results
        }

    def _test_criterion_1(self) -> float:
        """Teste Critère 1: Mapping X-User-ID → group_id"""
        tests_c1 = []

        # Test 1: Health check sans X-User-ID (mode corporate)
        result = self.test_endpoint("GET", "/api/knowledge-graph/health")
        tests_c1.append(result)
        self.results.append(result)

        if result.get("success") and result.get("response_data"):
            response_data = result["response_data"]
            is_corporate = response_data.get("group_id") == "corporate"
            print(f"  📋 Mode corporate par défaut: {'✅' if is_corporate else '❌'}")

        # Test 2: Health check avec X-User-ID (mode utilisateur)
        headers = {"X-User-ID": self.test_users[0]}
        result = self.test_endpoint("GET", "/api/knowledge-graph/health", headers=headers)
        tests_c1.append(result)
        self.results.append(result)

        if result.get("success") and result.get("response_data"):
            response_data = result["response_data"]
            expected_group = self.test_users[0]  # Le service doit retourner user_id clean
            actual_group = response_data.get("group_id")
            mapping_ok = actual_group == expected_group
            print(f"  🔄 Mapping X-User-ID: {'✅' if mapping_ok else '❌'} ({self.test_users[0]} → {actual_group})")

        # Test 3: Performance middleware (< 50ms overhead)
        start_time = time.time()
        result = self.test_endpoint("GET", "/api/knowledge-graph/stats", headers=headers)
        middleware_duration = (time.time() - start_time) * 1000

        tests_c1.append(result)
        self.results.append(result)

        performance_ok = middleware_duration < 50
        print(f"  ⚡ Performance middleware: {'✅' if performance_ok else '⚠️'} ({middleware_duration:.1f}ms)")

        # Test 4: Utilisateur invalide (doit échouer)
        invalid_headers = {"X-User-ID": "user_invalid_999"}
        result = self.test_endpoint("GET", "/api/knowledge-graph/health", headers=invalid_headers, expected_status=404)
        tests_c1.append(result)
        self.results.append(result)

        if result.get("success"):
            print(f"  🛡️ Validation utilisateur invalide: ✅ (rejeté correctement)")

        success_rate = sum(1 for t in tests_c1 if t.get('success', False)) / len(tests_c1)
        print(f"  📊 Score Critère 1: {success_rate:.1%}")
        return success_rate

    def _test_criterion_2(self) -> float:
        """Teste Critère 2: Auto-provisioning groupes utilisateur"""
        tests_c2 = []

        for user_id in self.test_users:
            headers = {"X-User-ID": user_id}

            # Test création entité pour chaque utilisateur (auto-provisioning)
            entity_data = {
                "name": f"Entité test {user_id}",
                "entity_type": "document",
                "description": f"Document personnel de {user_id}",
                "attributes": {"user_test": True, "user_owner": user_id}
            }

            result = self.test_endpoint("POST", "/api/knowledge-graph/entities", headers=headers, data=entity_data)
            tests_c2.append(result)
            self.results.append(result)

            if result.get("success") and result.get("response_data"):
                entity_id = result["response_data"]["uuid"]
                if user_id not in self.user_entities:
                    self.user_entities[user_id] = []
                self.user_entities[user_id].append(entity_id)
                print(f"  📄 Entité créée pour {user_id}: {entity_id[:8]}...")

            # Test stats utilisateur (vérifier group séparé)
            result = self.test_endpoint("GET", "/api/knowledge-graph/stats", headers=headers)
            tests_c2.append(result)
            self.results.append(result)

            if result.get("success") and result.get("response_data"):
                stats = result["response_data"]
                user_stats = stats.get("total_entities", 0) > 0
                print(f"  📊 Stats utilisateur {user_id}: {'✅' if user_stats else '❌'} ({stats.get('total_entities', 0)} entités)")

        success_rate = sum(1 for t in tests_c2 if t.get('success', False)) / len(tests_c2)
        print(f"  📊 Score Critère 2: {success_rate:.1%}")
        return success_rate

    def _test_criterion_3(self) -> float:
        """Teste Critère 3: Isolation multi-tenant"""
        tests_c3 = []

        # Test isolation: user_1 ne doit pas voir entités de user_2
        if len(self.test_users) >= 2:
            user1 = self.test_users[0]
            user2 = self.test_users[1]

            # User1 essaie de récupérer les stats (ne doit voir que ses entités)
            headers_user1 = {"X-User-ID": user1}
            result = self.test_endpoint("GET", "/api/knowledge-graph/stats", headers=headers_user1)
            tests_c3.append(result)
            self.results.append(result)

            if result.get("success") and result.get("response_data"):
                stats_user1 = result["response_data"]
                entities_user1 = stats_user1.get("total_entities", 0)

                # User2 essaie de récupérer les stats
                headers_user2 = {"X-User-ID": user2}
                result = self.test_endpoint("GET", "/api/knowledge-graph/stats", headers=headers_user2)
                tests_c3.append(result)
                self.results.append(result)

                if result.get("success") and result.get("response_data"):
                    stats_user2 = result["response_data"]
                    entities_user2 = stats_user2.get("total_entities", 0)

                    # Vérifier isolation (chaque user ne voit que ses entités)
                    isolation_ok = (entities_user1 > 0 and entities_user2 > 0 and
                                  entities_user1 == len(self.user_entities.get(user1, [])) and
                                  entities_user2 == len(self.user_entities.get(user2, [])))

                    print(f"  🔒 Isolation données: {'✅' if isolation_ok else '❌'}")
                    print(f"    User1: {entities_user1} entités, User2: {entities_user2} entités")

        # Test sécurité: mode corporate reste accessible
        result = self.test_endpoint("GET", "/api/knowledge-graph/stats")
        tests_c3.append(result)
        self.results.append(result)

        if result.get("success"):
            print(f"  🏢 Accès mode corporate: ✅ (maintenu)")

        success_rate = sum(1 for t in tests_c3 if t.get('success', False)) / len(tests_c3)
        print(f"  📊 Score Critère 3: {success_rate:.1%}")
        return success_rate


def main():
    """Point d'entrée principal"""
    try:
        validator = KGMultiUserValidator(BASE_URL)
        results = validator.validate_phase_2()

        print("\n" + "=" * 60)
        print("📋 RAPPORT FINAL PHASE 2")
        print("=" * 60)

        print(f"Tests exécutés: {results['total_tests']}")
        print(f"Tests réussis: {results['successful_tests']}")
        print(f"Taux de réussite global: {results['success_rate']}%")

        print(f"\n📊 SCORES PAR CRITÈRE:")
        for criterion, score in results['criteria_scores'].items():
            status = "✅" if score >= 0.8 else "❌"
            print(f"  {criterion}: {score:.1%} {status}")

        print(f"\n🎯 PHASE 2 VALIDÉE: {'✅ OUI' if results['phase_2_validated'] else '❌ NON'}")

        if results['phase_2_validated']:
            print("\n🚀 Knowledge Graph Multi-Utilisateur est prêt pour la Phase 3!")
            return 0
        else:
            print("\n⚠️ Des améliorations sont nécessaires avant la Phase 3")
            return 1

    except KeyboardInterrupt:
        print("\n⚠️ Validation interrompue par l'utilisateur")
        return 130
    except Exception as e:
        print(f"\n❌ Erreur critique: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())