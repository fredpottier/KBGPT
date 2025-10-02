"""
Tests GraphitiProxy - Workaround API Limitations

Valide:
1. add_episode() enrichi avec episode_uuid
2. get_episode() par UUID ou custom_id
3. Cache persistence (mémoire + disque)
4. Fallback vers client standard si proxy désactivé
5. Feature flag GRAPHITI_USE_PROXY
"""

import pytest
import json
import tempfile
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
from datetime import datetime

from knowbase.graphiti.graphiti_proxy import GraphitiProxy, EpisodeCacheEntry
from knowbase.graphiti.graphiti_factory import get_graphiti_service, is_proxy_enabled


class TestGraphitiProxy:
    """Tests GraphitiProxy"""

    def test_add_episode_enriches_response(self, tmp_path):
        """Test 1: add_episode enrichit réponse avec episode_uuid"""
        # Mock client Graphiti
        mock_client = Mock()
        mock_client.add_episode.return_value = {"success": True}

        # Mock get_episodes retourne episode créé
        mock_client.get_episodes.return_value = [
            {
                "uuid": "abc-123-def",
                "name": "Test Episode",
                "group_id": "test_tenant",
                "content": "Test content here",
                "created_at": "2025-10-02T12:00:00Z",
                "entity_edges": []
            }
        ]

        # Créer proxy
        proxy = GraphitiProxy(
            graphiti_client=mock_client,
            cache_dir=tmp_path,
            enable_cache=True
        )

        # Appel add_episode
        result = proxy.add_episode(
            group_id="test_tenant",
            messages=[{"content": "Test", "role_type": "user"}],
            custom_id="my_episode_001"
        )

        # Validate
        assert result["success"] is True
        assert result["episode_uuid"] == "abc-123-def"  # ← ENRICHI
        assert result["custom_id"] == "my_episode_001"
        assert result["group_id"] == "test_tenant"
        assert "created_at" in result

        # Verify cache
        cache_file = tmp_path / "my_episode_001.json"
        assert cache_file.exists()

        cached_data = json.loads(cache_file.read_text())
        assert cached_data["episode_uuid"] == "abc-123-def"
        assert cached_data["custom_id"] == "my_episode_001"

        print(f"✅ Test 1: add_episode enrichi avec episode_uuid={result['episode_uuid']}")

    def test_add_episode_auto_generates_custom_id(self, tmp_path):
        """Test 2: add_episode génère custom_id si non fourni"""
        mock_client = Mock()
        mock_client.add_episode.return_value = {"success": True}
        mock_client.get_episodes.return_value = [
            {
                "uuid": "xyz-456",
                "group_id": "tenant_2",
                "content": "Content",
                "created_at": datetime.now().isoformat(),
                "entity_edges": []
            }
        ]

        proxy = GraphitiProxy(mock_client, cache_dir=tmp_path)

        # Appel sans custom_id
        result = proxy.add_episode(
            group_id="tenant_2",
            messages=[{"content": "Test", "role_type": "user"}]
        )

        # Validate custom_id auto-généré
        assert "custom_id" in result
        assert result["custom_id"].startswith("tenant_2_episode_")
        assert result["episode_uuid"] == "xyz-456"

        print(f"✅ Test 2: custom_id auto-généré = {result['custom_id']}")

    def test_get_episode_by_custom_id(self, tmp_path):
        """Test 3: get_episode() par custom_id depuis cache"""
        mock_client = Mock()
        mock_client.add_episode.return_value = {"success": True}
        mock_client.get_episodes.side_effect = [
            # Premier appel: création episode
            [{
                "uuid": "episode-uuid-123",
                "group_id": "test",
                "content": "Episode content",
                "created_at": datetime.now().isoformat(),
                "entity_edges": []
            }],
            # Deuxième appel: récupération par UUID
            [{
                "uuid": "episode-uuid-123",
                "group_id": "test",
                "content": "Episode content",
                "name": "My Episode",
                "created_at": datetime.now().isoformat(),
                "entity_edges": []
            }]
        ]

        proxy = GraphitiProxy(mock_client, cache_dir=tmp_path)

        # 1. Créer episode
        result = proxy.add_episode(
            group_id="test",
            messages=[{"content": "Test", "role_type": "user"}],
            custom_id="episode_custom_001"
        )

        episode_uuid = result["episode_uuid"]

        # 2. Récupérer par custom_id
        episode = proxy.get_episode("episode_custom_001", id_type="custom")

        # Validate
        assert episode is not None
        assert episode["uuid"] == episode_uuid
        assert episode["custom_id"] == "episode_custom_001"

        print(f"✅ Test 3: get_episode par custom_id retourné episode UUID={episode_uuid}")

    def test_get_episode_by_uuid(self, tmp_path):
        """Test 4: get_episode() par UUID Graphiti"""
        mock_client = Mock()

        # Mock get_episodes pour recherche UUID
        mock_client.get_episodes.return_value = [
            {
                "uuid": "target-uuid-789",
                "group_id": "test",
                "content": "Content",
                "created_at": datetime.now().isoformat(),
                "entity_edges": []
            },
            {
                "uuid": "other-uuid-000",
                "group_id": "test",
                "content": "Other",
                "created_at": datetime.now().isoformat(),
                "entity_edges": []
            }
        ]

        proxy = GraphitiProxy(mock_client, cache_dir=tmp_path)

        # Récupérer par UUID
        episode = proxy.get_episode("target-uuid-789", id_type="uuid")

        # Validate
        assert episode is not None
        assert episode["uuid"] == "target-uuid-789"

        print(f"✅ Test 4: get_episode par UUID fonctionne")

    def test_cache_persistence(self, tmp_path):
        """Test 5: Cache persiste entre instances proxy"""
        mock_client = Mock()
        mock_client.add_episode.return_value = {"success": True}
        mock_client.get_episodes.return_value = [{
            "uuid": "persisted-uuid",
            "group_id": "test",
            "content": "Content",
            "created_at": datetime.now().isoformat(),
            "entity_edges": []
        }]

        # Instance 1: créer episode
        proxy1 = GraphitiProxy(mock_client, cache_dir=tmp_path)
        result = proxy1.add_episode(
            group_id="test",
            messages=[{"content": "Test", "role_type": "user"}],
            custom_id="persisted_episode"
        )

        # Instance 2: charger depuis cache disque
        proxy2 = GraphitiProxy(mock_client, cache_dir=tmp_path)

        # Verify cache loaded
        cached_entry = proxy2._get_from_cache("persisted_episode")
        assert cached_entry is not None
        assert cached_entry.episode_uuid == "persisted-uuid"

        print(f"✅ Test 5: Cache persiste entre instances")

    def test_cache_disabled(self, tmp_path):
        """Test 6: Cache peut être désactivé"""
        mock_client = Mock()
        mock_client.add_episode.return_value = {"success": True}
        mock_client.get_episodes.return_value = [{
            "uuid": "no-cache-uuid",
            "group_id": "test",
            "content": "Content",
            "created_at": datetime.now().isoformat(),
            "entity_edges": []
        }]

        # Créer proxy SANS cache
        proxy = GraphitiProxy(
            mock_client,
            cache_dir=tmp_path,
            enable_cache=False
        )

        result = proxy.add_episode(
            group_id="test",
            messages=[{"content": "Test", "role_type": "user"}],
            custom_id="no_cache_episode"
        )

        # Validate: pas de fichier cache créé
        cache_file = tmp_path / "no_cache_episode.json"
        assert not cache_file.exists()

        # get_episode par custom_id devrait échouer (pas de cache)
        episode = proxy.get_episode("no_cache_episode", id_type="custom")
        assert episode is None

        print(f"✅ Test 6: Cache peut être désactivé")

    def test_clear_cache(self, tmp_path):
        """Test 7: clear_cache() nettoie cache"""
        mock_client = Mock()
        mock_client.add_episode.return_value = {"success": True}
        mock_client.get_episodes.return_value = [{
            "uuid": "to-clear-uuid",
            "group_id": "test",
            "content": "Content",
            "created_at": datetime.now().isoformat(),
            "entity_edges": []
        }]

        proxy = GraphitiProxy(mock_client, cache_dir=tmp_path)

        # Créer episodes
        proxy.add_episode(
            group_id="test",
            messages=[{"content": "Test 1", "role_type": "user"}],
            custom_id="episode_1"
        )
        proxy.add_episode(
            group_id="test",
            messages=[{"content": "Test 2", "role_type": "user"}],
            custom_id="episode_2"
        )

        # Verify cache files exist
        assert (tmp_path / "episode_1.json").exists()
        assert (tmp_path / "episode_2.json").exists()

        # Clear specific episode
        proxy.clear_cache("episode_1")
        assert not (tmp_path / "episode_1.json").exists()
        assert (tmp_path / "episode_2.json").exists()

        # Clear all
        proxy.clear_cache()
        assert not (tmp_path / "episode_2.json").exists()

        print(f"✅ Test 7: clear_cache() fonctionne")

    def test_fallback_on_api_error(self, tmp_path):
        """Test 8: Fallback gracieux si get_episodes échoue"""
        mock_client = Mock()
        mock_client.add_episode.return_value = {"success": True}

        # get_episodes échoue
        mock_client.get_episodes.side_effect = Exception("API Error")

        proxy = GraphitiProxy(mock_client, cache_dir=tmp_path)

        # add_episode devrait retourner résultat minimal sans crash
        result = proxy.add_episode(
            group_id="test",
            messages=[{"content": "Test", "role_type": "user"}],
            custom_id="fallback_episode"
        )

        # Validate: success mais pas d'enrichissement
        assert result["success"] is True
        assert result["custom_id"] == "fallback_episode"
        assert "episode_uuid" not in result  # Pas enrichi

        print(f"✅ Test 8: Fallback gracieux si API error")

    def test_is_uuid_detection(self):
        """Test 9: _is_uuid() détecte format UUID"""
        # Valid UUIDs
        assert GraphitiProxy._is_uuid("abc-123-def") is False  # Pas format UUID
        assert GraphitiProxy._is_uuid("123e4567-e89b-12d3-a456-426614174000") is True
        assert GraphitiProxy._is_uuid("550e8400-e29b-41d4-a716-446655440000") is True

        # Invalid UUIDs
        assert GraphitiProxy._is_uuid("not-a-uuid") is False
        assert GraphitiProxy._is_uuid("custom_episode_001") is False

        print(f"✅ Test 9: _is_uuid() détecte UUIDs correctement")

    def test_transparent_proxy_other_methods(self, tmp_path):
        """Test 10: Proxy délègue méthodes non-interceptées"""
        mock_client = Mock()

        # Mock méthode non-interceptée (ex: search)
        mock_client.search.return_value = {"results": ["result1", "result2"]}

        proxy = GraphitiProxy(mock_client, cache_dir=tmp_path)

        # Appel search via proxy (doit être délégué au client)
        results = proxy.search(query="test query")

        # Validate
        assert results == {"results": ["result1", "result2"]}
        mock_client.search.assert_called_once_with(query="test query")

        print(f"✅ Test 10: Proxy transparent pour méthodes non-interceptées")


class TestGraphitiFactory:
    """Tests factory get_graphiti_service()"""

    @patch('knowbase.graphiti.graphiti_factory.get_graphiti_client')
    @patch.dict('os.environ', {"GRAPHITI_USE_PROXY": "true"})
    def test_factory_returns_proxy_when_enabled(self, mock_get_client, tmp_path):
        """Test 11: Factory retourne proxy si GRAPHITI_USE_PROXY=true"""
        mock_client = Mock()
        mock_get_client.return_value = mock_client

        service = get_graphiti_service(cache_dir=tmp_path)

        # Validate: retourne GraphitiProxy
        assert isinstance(service, GraphitiProxy)
        assert service.client == mock_client

        print(f"✅ Test 11: Factory retourne GraphitiProxy si env=true")

    @patch('knowbase.graphiti.graphiti_factory.get_graphiti_client')
    @patch.dict('os.environ', {"GRAPHITI_USE_PROXY": "false"})
    def test_factory_returns_client_when_disabled(self, mock_get_client):
        """Test 12: Factory retourne client standard si GRAPHITI_USE_PROXY=false"""
        mock_client = Mock()
        mock_get_client.return_value = mock_client

        service = get_graphiti_service()

        # Validate: retourne client standard (pas proxy)
        assert service == mock_client
        assert not isinstance(service, GraphitiProxy)

        print(f"✅ Test 12: Factory retourne client standard si env=false")

    @patch.dict('os.environ', {"GRAPHITI_USE_PROXY": "true"})
    def test_is_proxy_enabled(self):
        """Test 13: is_proxy_enabled() lit env var"""
        assert is_proxy_enabled() is True

        with patch.dict('os.environ', {"GRAPHITI_USE_PROXY": "false"}):
            assert is_proxy_enabled() is False

        print(f"✅ Test 13: is_proxy_enabled() fonctionne")


class TestEpisodeCacheEntry:
    """Tests dataclass EpisodeCacheEntry"""

    def test_cache_entry_to_dict(self):
        """Test 14: EpisodeCacheEntry.to_dict()"""
        entry = EpisodeCacheEntry(
            custom_id="test_episode",
            episode_uuid="uuid-123",
            group_id="test_tenant",
            created_at="2025-10-02T12:00:00Z",
            cached_at="2025-10-02T12:00:01Z",
            metadata={"name": "Test", "content_length": 100}
        )

        result = entry.to_dict()

        # Validate
        assert isinstance(result, dict)
        assert result["custom_id"] == "test_episode"
        assert result["episode_uuid"] == "uuid-123"
        assert result["metadata"]["name"] == "Test"

        print(f"✅ Test 14: EpisodeCacheEntry.to_dict() fonctionne")


if __name__ == "__main__":
    # Exécution tests localement
    pytest.main([__file__, "-v", "-s"])
