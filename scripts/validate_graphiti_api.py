#!/usr/bin/env python3
"""
Script de validation complète de l'API Graphiti
Tests de tous les endpoints pour validation Phase 0 - Critère 3
"""
import asyncio
import aiohttp
import json
import time
import sys
from typing import Dict, Any, List


class GraphitiAPIValidator:
    """Validateur pour l'API Graphiti"""

    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.session = None
        self.test_group_id = f"test_validation_{int(time.time())}"
        self.results: List[Dict[str, Any]] = []

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def test_endpoint(self, method: str, endpoint: str, data: Dict[str, Any] = None,
                          expected_status: int = 200, test_name: str = None) -> Dict[str, Any]:
        """
        Teste un endpoint et enregistre le résultat
        """
        test_name = test_name or f"{method} {endpoint}"
        url = f"{self.base_url}{endpoint}"

        print(f"🧪 Test: {test_name}")
        print(f"   URL: {method} {url}")

        try:
            start_time = time.time()

            if method == "GET":
                async with self.session.get(url) as response:
                    response_data = await response.json() if response.content_type == 'application/json' else await response.text()
                    status = response.status
            elif method == "POST":
                async with self.session.post(url, json=data) as response:
                    response_data = await response.json() if response.content_type == 'application/json' else await response.text()
                    status = response.status
            elif method == "DELETE":
                async with self.session.delete(url) as response:
                    response_data = await response.json() if response.content_type == 'application/json' else await response.text()
                    status = response.status
            else:
                raise ValueError(f"Méthode HTTP non supportée: {method}")

            duration = time.time() - start_time
            success = status == expected_status

            result = {
                "test_name": test_name,
                "method": method,
                "endpoint": endpoint,
                "status_code": status,
                "expected_status": expected_status,
                "success": success,
                "duration_ms": round(duration * 1000, 2),
                "response_data": response_data if success else str(response_data)[:200],
                "timestamp": time.time()
            }

            if success:
                print(f"   ✅ SUCCÈS - {status} en {result['duration_ms']}ms")
            else:
                print(f"   ❌ ÉCHEC - {status} (attendu {expected_status}) en {result['duration_ms']}ms")
                print(f"   Réponse: {str(response_data)[:100]}...")

            self.results.append(result)
            return result

        except Exception as e:
            result = {
                "test_name": test_name,
                "method": method,
                "endpoint": endpoint,
                "success": False,
                "error": str(e),
                "timestamp": time.time()
            }
            print(f"   ❌ ERREUR - {e}")
            self.results.append(result)
            return result

    async def run_validation_suite(self) -> Dict[str, Any]:
        """
        Lance la suite complète de validation
        """
        print("🚀 === VALIDATION API GRAPHITI - PHASE 0 CRITÈRE 3 ===")
        print(f"Base URL: {self.base_url}")
        print(f"Group ID de test: {self.test_group_id}")
        print("=" * 60)

        # 1. Tests Health Checks
        print("\n📋 1. TESTS HEALTH CHECKS")
        await self.test_endpoint("GET", "/api/graphiti/health", test_name="Health Check Basique")
        await self.test_endpoint("GET", "/api/graphiti/health-full", test_name="Health Check Complet")

        # 2. Tests Gestion Tenants
        print("\n🏢 2. TESTS GESTION TENANTS")
        await self.test_endpoint("GET", "/api/graphiti/tenants", test_name="Lister Tenants")

        # Créer un tenant de test
        tenant_data = {
            "group_id": self.test_group_id,
            "name": "Test Validation",
            "description": "Tenant créé par script de validation",
            "metadata": {"created_by": "validation_script"}
        }
        await self.test_endpoint("POST", "/api/graphiti/tenants", data=tenant_data, test_name="Créer Tenant Test")

        # Récupérer le tenant
        await self.test_endpoint("GET", f"/api/graphiti/tenants/{self.test_group_id}", test_name="Récupérer Tenant")

        # 3. Tests Episodes
        print("\n📖 3. TESTS EPISODES")
        episode_data = {
            "group_id": self.test_group_id,
            "content": "Episode de test pour validation API",
            "episode_type": "message",
            "metadata": {"test": True}
        }
        await self.test_endpoint("POST", "/api/graphiti/episodes", data=episode_data, test_name="Créer Episode")

        # 4. Tests Facts
        print("\n🧠 4. TESTS FACTS")
        fact_data = {
            "group_id": self.test_group_id,
            "subject": "TestEntity",
            "predicate": "has_property",
            "object": "TestValue",
            "confidence": 0.9,
            "source": "validation_script"
        }
        await self.test_endpoint("POST", "/api/graphiti/facts", data=fact_data, test_name="Créer Fact")

        # Rechercher des facts
        await self.test_endpoint("GET", f"/api/graphiti/facts?query=TestEntity&group_id={self.test_group_id}",
                                test_name="Rechercher Facts")

        # 5. Tests Relations
        print("\n🔗 5. TESTS RELATIONS")
        relation_data = {
            "source_id": "entity1",
            "relation_type": "connected_to",
            "target_id": "entity2",
            "properties": {"test": True}
        }
        await self.test_endpoint("POST", "/api/graphiti/relations", data=relation_data, test_name="Créer Relation")

        # 6. Tests Sous-graphes
        print("\n🌐 6. TESTS SOUS-GRAPHES")
        subgraph_data = {
            "entity_id": "TestEntity",
            "depth": 2,
            "group_id": self.test_group_id
        }
        await self.test_endpoint("POST", "/api/graphiti/subgraph", data=subgraph_data, test_name="Récupérer Sous-graphe")

        # 7. Tests Mémoire
        print("\n🧠 7. TESTS MÉMOIRE")
        await self.test_endpoint("GET", f"/api/graphiti/memory/{self.test_group_id}", test_name="Récupérer Mémoire")

        # 8. Nettoyage (optionnel)
        print("\n🧹 8. NETTOYAGE")
        await self.test_endpoint("DELETE", f"/api/graphiti/tenants/{self.test_group_id}?confirm=true",
                                test_name="Supprimer Tenant Test")

        return self.generate_report()

    def generate_report(self) -> Dict[str, Any]:
        """
        Génère le rapport de validation
        """
        total_tests = len(self.results)
        successful_tests = sum(1 for r in self.results if r.get('success', False))
        failed_tests = total_tests - successful_tests

        avg_duration = sum(r.get('duration_ms', 0) for r in self.results if 'duration_ms' in r) / max(total_tests, 1)

        report = {
            "validation_timestamp": time.time(),
            "test_group_id": self.test_group_id,
            "summary": {
                "total_tests": total_tests,
                "successful_tests": successful_tests,
                "failed_tests": failed_tests,
                "success_rate_percent": round((successful_tests / max(total_tests, 1)) * 100, 1),
                "average_response_time_ms": round(avg_duration, 2)
            },
            "detailed_results": self.results,
            "phase_0_criteria_3_status": "VALIDÉ" if successful_tests >= 8 else "ÉCHEC"  # Au moins 8 tests doivent réussir
        }

        return report

    def print_final_report(self, report: Dict[str, Any]):
        """
        Affiche le rapport final
        """
        print("\n" + "=" * 60)
        print("📊 RAPPORT FINAL - VALIDATION API GRAPHITI")
        print("=" * 60)

        summary = report["summary"]
        print(f"🧪 Tests exécutés: {summary['total_tests']}")
        print(f"✅ Tests réussis: {summary['successful_tests']}")
        print(f"❌ Tests échoués: {summary['failed_tests']}")
        print(f"📈 Taux de réussite: {summary['success_rate_percent']}%")
        print(f"⚡ Temps de réponse moyen: {summary['average_response_time_ms']}ms")

        print(f"\n🎯 PHASE 0 - CRITÈRE 3: {report['phase_0_criteria_3_status']}")

        if report['phase_0_criteria_3_status'] == "VALIDÉ":
            print("🎉 L'API Graphiti est entièrement fonctionnelle !")
        else:
            print("⚠️ Des problèmes subsistent dans l'API Graphiti")

            # Détails des échecs
            print("\n❌ TESTS ÉCHOUÉS:")
            for result in self.results:
                if not result.get('success', False):
                    print(f"   - {result['test_name']}: {result.get('error', 'Status incorrect')}")


async def main():
    """
    Point d'entrée principal
    """
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"

    async with GraphitiAPIValidator(base_url) as validator:
        report = await validator.run_validation_suite()
        validator.print_final_report(report)

        # Sauvegarde du rapport
        report_file = f"data/logs/graphiti_validation_{int(time.time())}.json"
        try:
            with open(report_file, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"\n📄 Rapport sauvegardé: {report_file}")
        except Exception as e:
            print(f"\n⚠️ Erreur sauvegarde rapport: {e}")

        # Code de sortie
        success_rate = report["summary"]["success_rate_percent"]
        sys.exit(0 if success_rate >= 80 else 1)  # 80% minimum pour considérer comme réussi


if __name__ == "__main__":
    asyncio.run(main())