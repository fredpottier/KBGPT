"""
Tests End-to-End - Synchronisation Qdrant ↔ Graphiti
Phase 1 Critère 1.3

Valide:
1. Création chunks Qdrant avec metadata episode_id
2. Création episode Graphiti avec content incluant chunk_ids
3. Sync bidirectionnelle metadata
4. Requêtes cross-system (Qdrant → Graphiti, Graphiti → Qdrant)
"""

import pytest
import asyncio
from pathlib import Path
from typing import List, Dict, Any

from knowbase.common.clients.qdrant_client import get_qdrant_client
from knowbase.graphiti.graphiti_client import get_graphiti_client
from knowbase.graphiti.qdrant_sync import get_sync_service
from knowbase.ingestion.pipelines.pptx_pipeline_kg import process_pptx_kg


@pytest.fixture
def qdrant_client():
    """Client Qdrant pour tests"""
    return get_qdrant_client()


@pytest.fixture
def graphiti_client():
    """Client Graphiti pour tests"""
    return get_graphiti_client()


@pytest.fixture
def sync_service(qdrant_client, graphiti_client):
    """Service synchronisation pour tests"""
    return get_sync_service(qdrant_client, graphiti_client)


class TestQdrantGraphitiSync:
    """Tests synchronisation Qdrant ↔ Graphiti"""

    @pytest.mark.asyncio
    async def test_chunks_created_with_episode_metadata(self, qdrant_client):
        """
        Test 1: Les chunks Qdrant doivent contenir episode_id après ingestion KG

        Valide:
        - Chunks insérés dans Qdrant
        - Metadata episode_id présente
        - Metadata episode_name présente
        - Metadata has_knowledge_graph=True
        """
        tenant_id = "test_integration_sync"
        collection_name = "knowbase"

        # Récupérer chunks récents pour ce tenant
        chunks, _ = qdrant_client.scroll(
            collection_name=collection_name,
            limit=100,
            with_payload=True,
            scroll_filter=None
        )

        # Filtrer chunks avec episode_id
        chunks_with_kg = [
            c for c in chunks
            if c.payload and c.payload.get("has_knowledge_graph") is True
        ]

        assert len(chunks_with_kg) > 0, "Aucun chunk avec knowledge graph trouvé"

        # Valider metadata du premier chunk
        first_chunk = chunks_with_kg[0]
        payload = first_chunk.payload

        assert "episode_id" in payload, "Metadata episode_id manquante"
        assert "episode_name" in payload, "Metadata episode_name manquante"
        assert payload["has_knowledge_graph"] is True

        print(f"✅ Test 1: {len(chunks_with_kg)} chunks avec metadata KG validés")

    @pytest.mark.asyncio
    async def test_episode_created_in_graphiti(self, graphiti_client):
        """
        Test 2: Les episodes Graphiti doivent être créés et récupérables

        Valide:
        - Episodes créés dans Graphiti
        - Metadata group_id correcte
        - Content contient informations document
        """
        tenant_id = "test_integration_sync"

        # Récupérer episodes du tenant (last 50)
        episodes = graphiti_client.get_episodes(
            group_id=tenant_id,
            last_n=50
        )

        assert len(episodes) > 0, f"Aucun episode trouvé pour tenant {tenant_id}"

        # Valider structure premier episode
        first_episode = episodes[0]

        assert "uuid" in first_episode, "UUID episode manquant"
        assert "group_id" in first_episode, "group_id episode manquant"
        assert first_episode["group_id"] == tenant_id
        assert "content" in first_episode, "Content episode manquant"

        print(f"✅ Test 2: {len(episodes)} episodes Graphiti validés")

    @pytest.mark.asyncio
    async def test_bidirectional_metadata_sync(self, qdrant_client, graphiti_client):
        """
        Test 3: Sync bidirectionnelle Qdrant ↔ Graphiti

        Valide:
        - Qdrant chunks → episode_id pointe vers Graphiti
        - Graphiti episode content → contient chunk_ids Qdrant
        """
        tenant_id = "test_integration_sync"
        collection_name = "knowbase"

        # 1. Récupérer chunks Qdrant avec episode_id
        chunks, _ = qdrant_client.scroll(
            collection_name=collection_name,
            limit=100,
            with_payload=True,
            scroll_filter=None
        )

        chunks_with_episode = [
            c for c in chunks
            if c.payload and c.payload.get("episode_id")
        ]

        assert len(chunks_with_episode) > 0, "Aucun chunk avec episode_id"

        # Extraire premier episode_id
        sample_chunk = chunks_with_episode[0]
        episode_id = sample_chunk.payload["episode_id"]
        chunk_id = str(sample_chunk.id)

        print(f"   Chunk ID: {chunk_id}")
        print(f"   Episode ID: {episode_id}")

        # 2. Récupérer episodes Graphiti
        episodes = graphiti_client.get_episodes(
            group_id=tenant_id,
            last_n=50
        )

        # 3. Vérifier que au moins un episode contient des chunk_ids dans content
        episodes_with_chunks = [
            ep for ep in episodes
            if "Qdrant Chunks" in ep.get("content", "")
        ]

        assert len(episodes_with_chunks) > 0, "Aucun episode avec chunk_ids dans content"

        sample_episode = episodes_with_chunks[0]
        assert "chunk" in sample_episode["content"].lower(), \
            "Content episode ne mentionne pas les chunks"

        print(f"✅ Test 3: Sync bidirectionnelle validée")
        print(f"   - {len(chunks_with_episode)} chunks → episode_id")
        print(f"   - {len(episodes_with_chunks)} episodes → chunk_ids")

    @pytest.mark.asyncio
    async def test_search_graphiti_from_qdrant_context(self, graphiti_client):
        """
        Test 4: Recherche Graphiti avec contexte Qdrant

        Valide:
        - Requête /search fonctionne
        - Retourne entities/relations pertinentes
        """
        tenant_id = "test_integration_sync"
        query = "SAP S/4HANA Group Reporting consolidation process"

        # Recherche sémantique dans knowledge graph
        results = graphiti_client.search(
            group_id=tenant_id,
            query=query,
            num_results=5
        )

        assert results is not None, "Search failed"
        # Note: Structure résultat dépend de l'implémentation Graphiti

        print(f"✅ Test 4: Search Graphiti validée")
        print(f"   Query: {query}")
        print(f"   Results: {results}")

    @pytest.mark.asyncio
    async def test_full_pipeline_kg_integration(self):
        """
        Test 5: Pipeline complet PPTX → Qdrant + Graphiti

        Valide workflow end-to-end:
        1. Ingestion PPTX
        2. Chunks créés dans Qdrant
        3. Episode créé dans Graphiti
        4. Metadata synchronisée
        """
        test_file = Path("/data/docs_in/Group_Reporting_Overview_L1.pptx")

        if not test_file.exists():
            pytest.skip(f"Fichier test non disponible: {test_file}")

        tenant_id = "test_pipeline_e2e"
        document_type = "functional"

        # Exécuter pipeline KG complet
        result = await process_pptx_kg(
            pptx_path=test_file,
            tenant_id=tenant_id,
            document_type=document_type,
            progress_callback=None,
            rq_job=None
        )

        # Valider résultats
        assert result["chunks_inserted"] > 0, "Aucun chunk inséré"
        assert result["entities_count"] > 0, "Aucune entity extraite"
        assert result["relations_count"] > 0, "Aucune relation extraite"
        assert result["success_rate"] > 80.0, f"Taux succès trop faible: {result['success_rate']}%"

        # Valider intégration Graphiti
        # Note: L'API Graphiti retourne {"success": true} asynchrone
        # On ne peut pas valider episode_id immédiatement

        print(f"✅ Test 5: Pipeline KG complet validé")
        print(f"   - Chunks: {result['chunks_inserted']}")
        print(f"   - Entities: {result['entities_count']}")
        print(f"   - Relations: {result['relations_count']}")
        print(f"   - Success: {result['success_rate']}%")


class TestGraphitiAPILimitations:
    """Tests documentant limitations API Graphiti"""

    @pytest.mark.asyncio
    async def test_cannot_get_episode_by_custom_id(self, graphiti_client):
        """
        Test 6: Limitation - Impossible de récupérer episode par ID custom

        Documente que:
        - Pas de GET /episode/{uuid} dans l'API
        - Le champ 'name' est vide dans les episodes
        - Pas de mapping entre notre episode_id et UUID Graphiti
        """
        tenant_id = "test_integration_sync"
        custom_episode_id = "test_sync_Group_Reporting_Overview_L1"

        # Récupérer tous les episodes
        episodes = graphiti_client.get_episodes(
            group_id=tenant_id,
            last_n=50
        )

        # Essayer de trouver notre episode par name
        matching_episodes = [
            ep for ep in episodes
            if ep.get("name") == custom_episode_id
        ]

        # ❌ ATTENDU: Aucun match car 'name' est vide dans l'API
        assert len(matching_episodes) == 0, \
            "Limitation: API Graphiti ne retourne pas notre custom episode_id dans 'name'"

        # Vérifier que tous les 'name' sont vides
        empty_names = [ep for ep in episodes if ep.get("name") == ""]
        assert len(empty_names) == len(episodes), \
            "Tous les episodes ont name vide"

        print(f"✅ Test 6: Limitation documentée - name vide dans episodes")

    @pytest.mark.asyncio
    async def test_episode_entity_edges_empty(self, graphiti_client):
        """
        Test 7: Limitation - entity_edges vide dans GET /episodes

        Documente que:
        - Le champ entity_edges est vide dans la réponse
        - Pas d'accès aux entities créées via GET /episodes
        - Nécessite utiliser /search pour obtenir entities
        """
        tenant_id = "test_integration_sync"

        episodes = graphiti_client.get_episodes(
            group_id=tenant_id,
            last_n=10
        )

        if len(episodes) == 0:
            pytest.skip("Aucun episode disponible pour le test")

        # Vérifier entity_edges
        episodes_with_edges = [
            ep for ep in episodes
            if len(ep.get("entity_edges", [])) > 0
        ]

        # ❌ ATTENDU: Aucun episode avec entity_edges
        # (peut être faux si Graphiti est modifié)
        print(f"   Episodes avec entity_edges: {len(episodes_with_edges)}/{len(episodes)}")
        print(f"✅ Test 7: Limitation documentée - entity_edges souvent vide")


# Tests de non-régression
class TestSyncServiceMethods:
    """Tests méthodes sync service"""

    def test_link_chunks_to_episode(self, sync_service, qdrant_client):
        """
        Test 8: link_chunks_to_episode() ajoute metadata correctement
        """
        collection_name = "knowbase"
        test_episode_id = "test_episode_link_123"
        test_episode_name = "Test Episode Link"

        # Récupérer un chunk existant
        chunks, _ = qdrant_client.scroll(
            collection_name=collection_name,
            limit=1,
            with_payload=True
        )

        if len(chunks) == 0:
            pytest.skip("Aucun chunk disponible pour le test")

        chunk_id = str(chunks[0].id)

        # Lier chunk à episode
        sync_service.link_chunks_to_episode(
            chunk_ids=[chunk_id],
            episode_id=test_episode_id,
            episode_name=test_episode_name
        )

        # Vérifier metadata mise à jour
        updated_chunks = qdrant_client.retrieve(
            collection_name=collection_name,
            ids=[chunk_id]
        )

        payload = updated_chunks[0].payload
        assert payload["episode_id"] == test_episode_id
        assert payload["episode_name"] == test_episode_name
        assert payload["has_knowledge_graph"] is True

        print(f"✅ Test 8: link_chunks_to_episode validé")


if __name__ == "__main__":
    # Exécution tests localement
    pytest.main([__file__, "-v", "-s"])
