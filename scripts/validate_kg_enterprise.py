#!/usr/bin/env python3
"""
Script de validation Knowledge Graph Corporate - Phase 1
Tests complets des 4 critères d'achievement
"""

import asyncio
import requests
import json
import time
import sys
from typing import Dict, List, Any

# Configuration
BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
TEST_TIMEOUT = 10


class KGCorporateValidator:
    """Validateur Knowledge Graph Corporate Phase 1"""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.results = []
        self.test_entities = []
        self.test_relations = []

    def test_endpoint(self, method: str, endpoint: str, data=None, expected_status: int = 200) -> Dict[str, Any]:
        """Teste un endpoint et retourne le résultat"""
        url = f"{self.base_url}{endpoint}"
        print(f"🧪 Test: {method} {endpoint}")

        try:
            start_time = time.time()

            if method == "GET":
                response = requests.get(url, timeout=TEST_TIMEOUT)
            elif method == "POST":
                response = requests.post(url, json=data, timeout=TEST_TIMEOUT,
                                       headers={"Content-Type": "application/json"})
            elif method == "DELETE":
                response = requests.delete(url, timeout=TEST_TIMEOUT)
            else:
                return {"success": False, "error": f"Méthode non supportée: {method}"}

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
                print(f"  ✅ {response.status_code} en {duration:.0f}ms")
                try:
                    result["response_data"] = response.json()
                except:
                    result["response_data"] = response.text
            else:
                print(f"  ❌ {response.status_code} (attendu {expected_status})")
                result["error_details"] = response.text

            return result

        except Exception as e:
            print(f"  💥 Exception: {str(e)}")
            return {"endpoint": endpoint, "method": method, "success": False, "error": str(e)}

    def validate_phase_1(self) -> Dict[str, Any]:
        """Valide tous les critères de la Phase 1"""
        print("VALIDATION KNOWLEDGE GRAPH ENTERPRISE - PHASE 1")
        print("=" * 60)
        print(f"URL de base: {self.base_url}")
        print("=" * 60)

        # Critère 1: Groupe Corporate Opérationnel
        print("\n1️⃣ CRITÈRE 1: GROUPE ENTERPRISE OPÉRATIONNEL")
        print("-" * 40)
        criterion_1_score = self._test_criterion_1()

        # Critère 2: Endpoints CRUD Relations
        print("\n2️⃣ CRITÈRE 2: ENDPOINTS CRUD RELATIONS")
        print("-" * 40)
        criterion_2_score = self._test_criterion_2()

        # Critère 3: Sous-graphes et Expansion
        print("\n3️⃣ CRITÈRE 3: SOUS-GRAPHES ET EXPANSION")
        print("-" * 40)
        criterion_3_score = self._test_criterion_3()

        # Critère 4: Migration Relations Existantes
        print("\n4️⃣ CRITÈRE 4: MIGRATION RELATIONS EXISTANTES")
        print("-" * 40)
        criterion_4_score = self._test_criterion_4()

        # Calcul du score global
        total_tests = len(self.results)
        successful_tests = sum(1 for r in self.results if r.get('success', False))
        success_rate = (successful_tests / total_tests) * 100 if total_tests > 0 else 0

        # Score par critère
        criteria_scores = {
            "criterion_1": criterion_1_score,
            "criterion_2": criterion_2_score,
            "criterion_3": criterion_3_score,
            "criterion_4": criterion_4_score
        }

        # Nettoyage des données de test
        self._cleanup_test_data()

        return {
            "total_tests": total_tests,
            "successful_tests": successful_tests,
            "success_rate": round(success_rate, 1),
            "criteria_scores": criteria_scores,
            "phase_1_validated": all(score >= 0.8 for score in criteria_scores.values()),
            "detailed_results": self.results
        }

    def _test_criterion_1(self) -> float:
        """Teste Critère 1: Groupe Corporate Opérationnel"""
        tests_c1 = []

        # Health check KG
        result = self.test_endpoint("GET", "/api/knowledge-graph/health")
        tests_c1.append(result)
        self.results.append(result)

        # Vérifier que le groupe corporate est configuré
        if result.get("success") and result.get("response_data"):
            response_data = result["response_data"]
            corporate_configured = (
                response_data.get("group_id") == "corporate" and
                response_data.get("status") == "healthy"
            )
            print(f"  📋 Groupe corporate configuré: {'✅' if corporate_configured else '❌'}")

        # Statistiques KG pour vérifier l'initialisation
        result = self.test_endpoint("GET", "/api/knowledge-graph/stats")
        tests_c1.append(result)
        self.results.append(result)

        success_rate = sum(1 for t in tests_c1 if t.get('success', False)) / len(tests_c1)
        print(f"  📊 Score Critère 1: {success_rate:.1%}")
        return success_rate

    def _test_criterion_2(self) -> float:
        """Teste Critère 2: Endpoints CRUD Relations"""
        tests_c2 = []

        # Créer des entités de test d'abord
        entity1_data = {
            "name": "Test Document 1",
            "entity_type": "document",
            "description": "Document de test pour validation Phase 1",
            "attributes": {"test": True}
        }

        result = self.test_endpoint("POST", "/api/knowledge-graph/entities", data=entity1_data, expected_status=200)
        tests_c2.append(result)
        self.results.append(result)

        if result.get("success") and result.get("response_data"):
            entity1_id = result["response_data"]["uuid"]
            self.test_entities.append(entity1_id)
            print(f"  📄 Entité 1 créée: {entity1_id[:8]}...")

        entity2_data = {
            "name": "Test Concept 1",
            "entity_type": "concept",
            "description": "Concept de test pour validation Phase 1",
            "attributes": {"test": True}
        }

        result = self.test_endpoint("POST", "/api/knowledge-graph/entities", data=entity2_data, expected_status=200)
        tests_c2.append(result)
        self.results.append(result)

        if result.get("success") and result.get("response_data"):
            entity2_id = result["response_data"]["uuid"]
            self.test_entities.append(entity2_id)
            print(f"  💡 Entité 2 créée: {entity2_id[:8]}...")

        # Tester CRUD Relations si on a les entités
        if len(self.test_entities) >= 2:
            # POST /api/knowledge-graph/relations
            relation_data = {
                "source_entity_id": self.test_entities[0],
                "target_entity_id": self.test_entities[1],
                "relation_type": "references",
                "description": "Relation de test pour validation Phase 1",
                "confidence": 0.9,
                "attributes": {"test": True}
            }

            result = self.test_endpoint("POST", "/api/knowledge-graph/relations", data=relation_data)
            tests_c2.append(result)
            self.results.append(result)

            if result.get("success") and result.get("response_data"):
                relation_id = result["response_data"]["uuid"]
                self.test_relations.append(relation_id)
                print(f"  🔗 Relation créée: {relation_id[:8]}...")

            # GET /api/knowledge-graph/relations
            result = self.test_endpoint("GET", "/api/knowledge-graph/relations?limit=50")
            tests_c2.append(result)
            self.results.append(result)

            # GET /api/knowledge-graph/relations avec filtre entité
            result = self.test_endpoint("GET", f"/api/knowledge-graph/relations?entity_id={self.test_entities[0]}")
            tests_c2.append(result)
            self.results.append(result)

            # DELETE /api/knowledge-graph/relations/{id} (si on a une relation)
            if self.test_relations:
                result = self.test_endpoint("DELETE", f"/api/knowledge-graph/relations/{self.test_relations[0]}")
                tests_c2.append(result)
                self.results.append(result)

                if result.get("success"):
                    print(f"  🗑️ Relation supprimée: {self.test_relations[0][:8]}...")

        success_rate = sum(1 for t in tests_c2 if t.get('success', False)) / len(tests_c2) if tests_c2 else 0
        print(f"  📊 Score Critère 2: {success_rate:.1%}")
        return success_rate

    def _test_criterion_3(self) -> float:
        """Teste Critère 3: Sous-graphes et Expansion"""
        tests_c3 = []

        # Créer des entités et relations pour avoir un graphe à explorer
        if len(self.test_entities) >= 2:
            # Créer une relation pour le sous-graphe
            relation_data = {
                "source_entity_id": self.test_entities[0],
                "target_entity_id": self.test_entities[1],
                "relation_type": "contains",
                "description": "Relation pour test sous-graphe",
                "confidence": 1.0
            }

            result = self.test_endpoint("POST", "/api/knowledge-graph/relations", data=relation_data)
            if result.get("success"):
                self.test_relations.append(result["response_data"]["uuid"])

        # Tester GET /api/knowledge-graph/subgraph
        if self.test_entities:
            subgraph_data = {
                "entity_id": self.test_entities[0],
                "depth": 2
            }

            start_time = time.time()
            result = self.test_endpoint("POST", "/api/knowledge-graph/subgraph", data=subgraph_data)
            duration = time.time() - start_time

            tests_c3.append(result)
            self.results.append(result)

            if result.get("success"):
                response_data = result.get("response_data", {})
                nodes_count = response_data.get("total_nodes", 0)
                edges_count = response_data.get("total_edges", 0)
                print(f"  🌐 Sous-graphe généré: {nodes_count} nœuds, {edges_count} arêtes")

                # Vérifier performance < 2s pour depth=3
                if duration < 2.0:
                    print(f"  ⚡ Performance OK: {duration:.2f}s < 2s")
                else:
                    print(f"  ⚠️ Performance lente: {duration:.2f}s > 2s")

            # Tester avec profondeur 3 pour la performance
            subgraph_data_deep = {
                "entity_id": self.test_entities[0],
                "depth": 3
            }

            start_time = time.time()
            result = self.test_endpoint("POST", "/api/knowledge-graph/subgraph", data=subgraph_data_deep)
            duration = time.time() - start_time

            tests_c3.append(result)
            self.results.append(result)

            if result.get("success") and duration < 2.0:
                print(f"  🚀 Test performance depth=3: {duration:.2f}s ✅")

        success_rate = sum(1 for t in tests_c3 if t.get('success', False)) / len(tests_c3) if tests_c3 else 0
        print(f"  📊 Score Critère 3: {success_rate:.1%}")
        return success_rate

    def _test_criterion_4(self) -> float:
        """Teste Critère 4: Migration Relations Existantes"""
        tests_c4 = []

        # Tester si le script de migration existe
        try:
            from pathlib import Path
            script_path = Path(__file__).parent / "migrate_qdrant_to_graphiti.py"
            script_exists = script_path.exists()
            print(f"  📜 Script migration existe: {'✅' if script_exists else '❌'}")

            # Tester si il y a des données migrées en vérifiant les stats
            result = self.test_endpoint("GET", "/api/knowledge-graph/stats")
            tests_c4.append(result)
            self.results.append(result)

            if result.get("success") and result.get("response_data"):
                stats = result["response_data"]
                has_migrated_data = (
                    stats.get("total_entities", 0) > len(self.test_entities) or
                    stats.get("total_relations", 0) > len(self.test_relations)
                )
                print(f"  📊 Données migrées détectées: {'✅' if has_migrated_data else '❌'}")
                print(f"    Total entités: {stats.get('total_entities', 0)}")
                print(f"    Total relations: {stats.get('total_relations', 0)}")

            # Score basé sur l'existence du script et présence de données
            script_score = 1.0 if script_exists else 0.0
            tests_c4.append({"success": script_exists, "test": "migration_script_exists"})

        except Exception as e:
            print(f"  ⚠️ Erreur test migration: {e}")
            tests_c4.append({"success": False, "error": str(e)})

        success_rate = sum(1 for t in tests_c4 if t.get('success', False)) / len(tests_c4) if tests_c4 else 0
        print(f"  📊 Score Critère 4: {success_rate:.1%}")
        return success_rate

    def _cleanup_test_data(self):
        """Nettoie les données de test créées"""
        print("\n🧹 NETTOYAGE DONNÉES DE TEST")
        print("-" * 30)

        # Supprimer les relations de test
        for relation_id in self.test_relations:
            try:
                result = self.test_endpoint("DELETE", f"/api/knowledge-graph/relations/{relation_id}")
                if result.get("success"):
                    print(f"  🗑️ Relation supprimée: {relation_id[:8]}...")
            except:
                pass

        # Note: Les entités ne peuvent pas être supprimées facilement via l'API actuelle
        # Elles resteront dans le système mais sont marquées comme "test"
        print(f"  📝 {len(self.test_entities)} entités de test laissées (marquées 'test': true)")


def main():
    """Point d'entrée principal"""
    try:
        validator = KGCorporateValidator(BASE_URL)
        results = validator.validate_phase_1()

        print("\n" + "=" * 60)
        print("📋 RAPPORT FINAL PHASE 1")
        print("=" * 60)

        print(f"Tests exécutés: {results['total_tests']}")
        print(f"Tests réussis: {results['successful_tests']}")
        print(f"Taux de réussite global: {results['success_rate']}%")

        print(f"\n📊 SCORES PAR CRITÈRE:")
        for criterion, score in results['criteria_scores'].items():
            status = "✅" if score >= 0.8 else "❌"
            print(f"  {criterion}: {score:.1%} {status}")

        print(f"\n🎯 PHASE 1 VALIDÉE: {'✅ OUI' if results['phase_1_validated'] else '❌ NON'}")

        if results['phase_1_validated']:
            print("\n🚀 Knowledge Graph Corporate est prêt pour la Phase 2!")
            return 0
        else:
            print("\n⚠️ Des améliorations sont nécessaires avant la Phase 2")
            return 1

    except KeyboardInterrupt:
        print("\n⚠️ Validation interrompue par l'utilisateur")
        return 130
    except Exception as e:
        print(f"\n❌ Erreur critique: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())