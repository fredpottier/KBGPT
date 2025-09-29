#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de test pour l'API Graphiti
"""
import asyncio
import json
import httpx
import sys
import io
from typing import Dict, Any

# Configuration UTF-8 pour Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

API_BASE = "http://localhost:8000/api/graphiti"


async def test_graphiti_api():
    """
    Test complet de l'API Graphiti
    """
    print("🧪 Test de l'API Graphiti")
    print("=" * 50)

    async with httpx.AsyncClient() as client:

        # 1. Health Check
        print("\n1. 🔍 Health Check")
        try:
            response = await client.get(f"{API_BASE}/health")
            if response.status_code == 200:
                health_data = response.json()
                print(f"✅ Statut: {health_data['status']}")
                print(f"📊 Détails: {health_data['details']['status']}")
            else:
                print(f"❌ Health Check échoué: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Erreur Health Check: {e}")
            return False

        # 2. Créer un tenant
        print("\n2. 🏢 Création d'un tenant")
        tenant_data = {
            "group_id": "test_sap_kb",
            "name": "Test SAP Knowledge Base",
            "description": "Groupe de test pour POC Graphiti",
            "metadata": {
                "environment": "test",
                "created_by": "poc_script"
            }
        }

        try:
            response = await client.post(f"{API_BASE}/tenants", json=tenant_data)
            if response.status_code == 200:
                tenant_result = response.json()
                print(f"✅ Tenant créé: {tenant_result['tenant']['group_id']}")
            else:
                print(f"❌ Création tenant échouée: {response.status_code}")
                print(response.text)
        except Exception as e:
            print(f"❌ Erreur création tenant: {e}")

        # 3. Créer des épisodes
        print("\n3. 📝 Création d'épisodes")
        episodes = [
            {
                "group_id": "test_sap_kb",
                "content": "SAP S/4HANA est la suite ERP de nouvelle génération de SAP",
                "episode_type": "knowledge",
                "metadata": {
                    "source": "documentation",
                    "topic": "SAP_S4HANA"
                }
            },
            {
                "group_id": "test_sap_kb",
                "content": "SAP Fiori offre une expérience utilisateur moderne et intuitive",
                "episode_type": "knowledge",
                "metadata": {
                    "source": "documentation",
                    "topic": "SAP_Fiori"
                }
            },
            {
                "group_id": "test_sap_kb",
                "content": "Comment configurer la réplication de données entre SAP ECC et S/4HANA ?",
                "episode_type": "question",
                "metadata": {
                    "source": "rfp",
                    "category": "migration"
                }
            }
        ]

        episode_uuids = []
        for i, episode in enumerate(episodes):
            try:
                response = await client.post(f"{API_BASE}/episodes", json=episode)
                if response.status_code == 200:
                    result = response.json()
                    episode_uuid = result["episode_uuid"]
                    episode_uuids.append(episode_uuid)
                    print(f"✅ Épisode {i+1} créé: {episode_uuid[:8]}...")
                else:
                    print(f"❌ Création épisode {i+1} échouée: {response.status_code}")
            except Exception as e:
                print(f"❌ Erreur création épisode {i+1}: {e}")

        # 4. Créer des faits
        print("\n4. 🔗 Création de faits")
        facts = [
            {
                "group_id": "test_sap_kb",
                "subject": "SAP S/4HANA",
                "predicate": "est_une",
                "object": "suite ERP",
                "confidence": 0.95,
                "source": "documentation_officielle",
                "status": "APPROVED"
            },
            {
                "group_id": "test_sap_kb",
                "subject": "SAP Fiori",
                "predicate": "offre",
                "object": "expérience utilisateur moderne",
                "confidence": 0.90,
                "source": "documentation_produit",
                "status": "APPROVED"
            },
            {
                "group_id": "test_sap_kb",
                "subject": "Migration S/4HANA",
                "predicate": "nécessite",
                "object": "réplication de données",
                "confidence": 0.85,
                "source": "guide_migration",
                "status": "PROPOSED"
            }
        ]

        fact_uuids = []
        for i, fact in enumerate(facts):
            try:
                response = await client.post(f"{API_BASE}/facts", json=fact)
                if response.status_code == 200:
                    result = response.json()
                    fact_uuid = result["fact_uuid"]
                    fact_uuids.append(fact_uuid)
                    print(f"✅ Fait {i+1} créé: {fact['subject']} {fact['predicate']} {fact['object']}")
                else:
                    print(f"❌ Création fait {i+1} échouée: {response.status_code}")
            except Exception as e:
                print(f"❌ Erreur création fait {i+1}: {e}")

        # 5. Rechercher des faits
        print("\n5. 🔍 Recherche de faits")
        search_queries = ["SAP S/4HANA", "Fiori", "migration"]

        for query in search_queries:
            try:
                params = {
                    "query": query,
                    "group_id": "test_sap_kb",
                    "limit": 5
                }
                response = await client.get(f"{API_BASE}/facts", params=params)
                if response.status_code == 200:
                    result = response.json()
                    count = result["results_count"]
                    print(f"✅ Recherche '{query}': {count} résultats")

                    for fact in result["facts"][:2]:  # Afficher les 2 premiers
                        print(f"   📋 {fact['subject']} {fact['predicate']} {fact['object']} (conf: {fact['confidence']})")
                else:
                    print(f"❌ Recherche '{query}' échouée: {response.status_code}")
            except Exception as e:
                print(f"❌ Erreur recherche '{query}': {e}")

        # 6. Récupérer la mémoire du groupe
        print("\n6. 🧠 Récupération de la mémoire")
        try:
            response = await client.get(f"{API_BASE}/memory/test_sap_kb?limit=10")
            if response.status_code == 200:
                result = response.json()
                memory_count = result["memory_count"]
                print(f"✅ Mémoire récupérée: {memory_count} éléments")

                for item in result["memory"][:3]:  # Afficher les 3 premiers
                    episode_type = item.get("episode_type", "unknown")
                    content_preview = item["content"][:60] + "..." if len(item["content"]) > 60 else item["content"]
                    print(f"   💭 [{episode_type}] {content_preview}")
            else:
                print(f"❌ Récupération mémoire échouée: {response.status_code}")
        except Exception as e:
            print(f"❌ Erreur récupération mémoire: {e}")

        # 7. Récupérer un sous-graphe
        print("\n7. 🕸️ Récupération de sous-graphe")
        if episode_uuids:
            subgraph_request = {
                "entity_id": "SAP S/4HANA",
                "depth": 2,
                "group_id": "test_sap_kb"
            }

            try:
                response = await client.post(f"{API_BASE}/subgraph", json=subgraph_request)
                if response.status_code == 200:
                    result = response.json()
                    subgraph = result["subgraph"]
                    episodes_count = len(subgraph.get("episodes", []))
                    entities_count = len(subgraph.get("entities", []))
                    print(f"✅ Sous-graphe récupéré: {episodes_count} épisodes, {entities_count} entités")
                else:
                    print(f"❌ Récupération sous-graphe échouée: {response.status_code}")
            except Exception as e:
                print(f"❌ Erreur récupération sous-graphe: {e}")

        # 8. Lister les tenants
        print("\n8. 🏢 Liste des tenants")
        try:
            response = await client.get(f"{API_BASE}/tenants")
            if response.status_code == 200:
                result = response.json()
                tenants_count = result["tenants_count"]
                print(f"✅ Tenants trouvés: {tenants_count}")

                for tenant in result["tenants"]:
                    group_id = tenant["group_id"]
                    episodes_count = tenant["stats"]["episodes_count"]
                    facts_count = tenant["stats"]["facts_count"]
                    print(f"   🏢 {group_id}: {episodes_count} épisodes, {facts_count} faits")
            else:
                print(f"❌ Liste tenants échouée: {response.status_code}")
        except Exception as e:
            print(f"❌ Erreur liste tenants: {e}")

    print("\n" + "=" * 50)
    print("✅ Test terminé avec succès !")
    return True


async def test_api_availability():
    """
    Test simple de disponibilité de l'API
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{API_BASE}/health", timeout=5.0)
            return response.status_code == 200
    except:
        return False


if __name__ == "__main__":
    print("🚀 Démarrage des tests Graphiti API")

    # Test de disponibilité
    if not asyncio.run(test_api_availability()):
        print("❌ API Graphiti non disponible. Vérifiez que les services sont démarrés:")
        print("   docker-compose -f docker-compose.graphiti.yml up -d")
        print("   docker-compose up -d")
        exit(1)

    # Test complet
    asyncio.run(test_graphiti_api())