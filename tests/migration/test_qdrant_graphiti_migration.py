"""
Tests Migration Qdrant → Graphiti - Phase 1 Critère 1.5

Valide:
1. Migration chunks sans KG vers Graphiti
2. Groupement chunks par source
3. Création episodes avec metadata sync
4. Analyse besoins migration
5. Mode dry-run
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime

from knowbase.migration.qdrant_graphiti_migration import (
    migrate_tenant,
    analyze_migration_needs,
    MigrationStats,
    _combine_chunks_content
)


class TestMigrateTenant:
    """Tests fonction migrate_tenant()"""

    @pytest.mark.asyncio
    @patch('knowbase.migration.qdrant_graphiti_migration.get_qdrant_client')
    @patch('knowbase.migration.qdrant_graphiti_migration.get_graphiti_client')
    @patch('knowbase.migration.qdrant_graphiti_migration.get_sync_service')
    async def test_migrate_tenant_dry_run(self, mock_sync, mock_graphiti, mock_qdrant):
        """Test 1: Dry-run ne modifie pas les données"""
        # Mock chunks Qdrant
        chunk1 = Mock()
        chunk1.id = "chunk_001"
        chunk1.payload = {
            "text": "SAP S/4HANA content",
            "filename": "test_doc.pptx",
            "import_id": "import_123",
            "has_knowledge_graph": False
        }

        chunk2 = Mock()
        chunk2.id = "chunk_002"
        chunk2.payload = {
            "text": "More content",
            "filename": "test_doc.pptx",
            "import_id": "import_123",
            "has_knowledge_graph": False
        }

        mock_qdrant.return_value.scroll.return_value = ([chunk1, chunk2], None)

        # Execute dry-run
        stats = await migrate_tenant(
            tenant_id="test_tenant",
            dry_run=True
        )

        # Validate
        assert isinstance(stats, MigrationStats)
        assert stats.dry_run is True
        assert stats.chunks_total == 2
        assert stats.chunks_to_migrate == 2
        assert stats.sources_found == 1  # Même source (filename + import_id)

        # Verify Graphiti client not called in dry-run
        mock_graphiti.return_value.add_episode.assert_not_called()

        print(f"✅ Test 1: Dry-run - {stats.sources_found} source, {stats.chunks_to_migrate} chunks")

    @pytest.mark.asyncio
    @patch('knowbase.migration.qdrant_graphiti_migration.get_qdrant_client')
    @patch('knowbase.migration.qdrant_graphiti_migration.get_graphiti_client')
    @patch('knowbase.migration.qdrant_graphiti_migration.get_sync_service')
    async def test_migrate_tenant_filters_chunks_with_kg(self, mock_sync, mock_graphiti, mock_qdrant):
        """Test 2: Filtre chunks déjà avec KG"""
        # Mock chunks: 2 sans KG, 1 avec KG
        chunk_without_kg1 = Mock()
        chunk_without_kg1.id = "chunk_001"
        chunk_without_kg1.payload = {
            "text": "Content 1",
            "filename": "doc1.pptx",
            "has_knowledge_graph": False
        }

        chunk_without_kg2 = Mock()
        chunk_without_kg2.id = "chunk_002"
        chunk_without_kg2.payload = {
            "text": "Content 2",
            "filename": "doc2.pptx",
            "has_knowledge_graph": False
        }

        chunk_with_kg = Mock()
        chunk_with_kg.id = "chunk_003"
        chunk_with_kg.payload = {
            "text": "Content 3",
            "filename": "doc3.pptx",
            "has_knowledge_graph": True
        }

        mock_qdrant.return_value.scroll.return_value = (
            [chunk_without_kg1, chunk_without_kg2, chunk_with_kg],
            None
        )

        # Execute dry-run
        stats = await migrate_tenant(
            tenant_id="test_tenant",
            dry_run=True
        )

        # Validate filtering
        assert stats.chunks_total == 3
        assert stats.chunks_already_migrated == 1
        assert stats.chunks_to_migrate == 2

        print(f"✅ Test 2: Filtre KG - {stats.chunks_already_migrated} déjà migrés, {stats.chunks_to_migrate} à migrer")

    @pytest.mark.asyncio
    @patch('knowbase.migration.qdrant_graphiti_migration.get_qdrant_client')
    @patch('knowbase.migration.qdrant_graphiti_migration.get_graphiti_client')
    @patch('knowbase.migration.qdrant_graphiti_migration.get_sync_service')
    async def test_migrate_tenant_groups_by_source(self, mock_sync, mock_graphiti, mock_qdrant):
        """Test 3: Groupement chunks par source (filename + import_id)"""
        # Mock 3 chunks: 2 même source, 1 autre source
        chunk1_source1 = Mock()
        chunk1_source1.id = "chunk_001"
        chunk1_source1.payload = {
            "text": "Content 1",
            "filename": "doc_A.pptx",
            "import_id": "import_001",
            "has_knowledge_graph": False
        }

        chunk2_source1 = Mock()
        chunk2_source1.id = "chunk_002"
        chunk2_source1.payload = {
            "text": "Content 2",
            "filename": "doc_A.pptx",
            "import_id": "import_001",
            "has_knowledge_graph": False
        }

        chunk1_source2 = Mock()
        chunk1_source2.id = "chunk_003"
        chunk1_source2.payload = {
            "text": "Content 3",
            "filename": "doc_B.pptx",
            "import_id": "import_002",
            "has_knowledge_graph": False
        }

        mock_qdrant.return_value.scroll.return_value = (
            [chunk1_source1, chunk2_source1, chunk1_source2],
            None
        )

        # Execute dry-run
        stats = await migrate_tenant(
            tenant_id="test_tenant",
            dry_run=True
        )

        # Validate grouping
        assert stats.sources_found == 2  # 2 sources distinctes
        assert stats.episodes_created == 2  # 1 episode par source

        print(f"✅ Test 3: Groupement - {stats.sources_found} sources, {stats.episodes_created} episodes")

    @pytest.mark.asyncio
    @patch('knowbase.migration.qdrant_graphiti_migration.get_qdrant_client')
    @patch('knowbase.migration.qdrant_graphiti_migration.get_graphiti_client')
    @patch('knowbase.migration.qdrant_graphiti_migration.get_sync_service')
    async def test_migrate_tenant_real_migration(self, mock_sync, mock_graphiti, mock_qdrant):
        """Test 4: Migration réelle crée episodes et update metadata"""
        # Mock chunks
        chunk = Mock()
        chunk.id = "chunk_001"
        chunk.payload = {
            "text": "SAP content",
            "filename": "test.pptx",
            "import_id": "import_123",
            "has_knowledge_graph": False
        }

        mock_qdrant.return_value.scroll.return_value = ([chunk], None)

        # Mock Graphiti success
        mock_graphiti.return_value.add_episode.return_value = {"success": True}

        # Mock sync service
        mock_sync_instance = AsyncMock()
        mock_sync.return_value = mock_sync_instance

        # Execute migration RÉELLE (dry_run=False)
        stats = await migrate_tenant(
            tenant_id="test_tenant",
            dry_run=False
        )

        # Validate calls
        mock_graphiti.return_value.add_episode.assert_called_once()
        mock_sync_instance.link_chunks_to_episode.assert_called_once()
        mock_qdrant.return_value.set_payload.assert_called_once()

        # Validate stats
        assert stats.dry_run is False
        assert stats.episodes_created == 1
        assert stats.chunks_migrated == 1

        print(f"✅ Test 4: Migration réelle - {stats.episodes_created} episode créé")

    @pytest.mark.asyncio
    @patch('knowbase.migration.qdrant_graphiti_migration.get_qdrant_client')
    @patch('knowbase.migration.qdrant_graphiti_migration.get_graphiti_client')
    @patch('knowbase.migration.qdrant_graphiti_migration.get_sync_service')
    async def test_migrate_tenant_limit_parameter(self, mock_sync, mock_graphiti, mock_qdrant):
        """Test 5: Paramètre limit fonctionne"""
        # Mock 10 chunks
        chunks = []
        for i in range(10):
            chunk = Mock()
            chunk.id = f"chunk_{i:03d}"
            chunk.payload = {
                "text": f"Content {i}",
                "filename": "test.pptx",
                "has_knowledge_graph": False
            }
            chunks.append(chunk)

        mock_qdrant.return_value.scroll.return_value = (chunks, None)

        # Execute avec limit=5
        stats = await migrate_tenant(
            tenant_id="test_tenant",
            dry_run=True,
            limit=5
        )

        # Validate scroll called with limit
        mock_qdrant.return_value.scroll.assert_called_once()
        call_kwargs = mock_qdrant.return_value.scroll.call_args[1]
        assert call_kwargs['limit'] == 5

        print(f"✅ Test 5: Limit paramètre - scroll appelé avec limit=5")

    @pytest.mark.asyncio
    @patch('knowbase.migration.qdrant_graphiti_migration.get_qdrant_client')
    @patch('knowbase.migration.qdrant_graphiti_migration.get_graphiti_client')
    @patch('knowbase.migration.qdrant_graphiti_migration.get_sync_service')
    async def test_migrate_tenant_handles_errors(self, mock_sync, mock_graphiti, mock_qdrant):
        """Test 6: Gestion erreurs lors migration"""
        # Mock 2 sources, 1 échoue
        chunk1 = Mock()
        chunk1.id = "chunk_001"
        chunk1.payload = {
            "text": "Content 1",
            "filename": "good.pptx",
            "has_knowledge_graph": False
        }

        chunk2 = Mock()
        chunk2.id = "chunk_002"
        chunk2.payload = {
            "text": "Content 2",
            "filename": "bad.pptx",
            "has_knowledge_graph": False
        }

        mock_qdrant.return_value.scroll.return_value = ([chunk1, chunk2], None)

        # Mock Graphiti: success pour first, erreur pour second
        call_count = 0
        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"success": True}
            else:
                raise Exception("Graphiti error")

        mock_graphiti.return_value.add_episode.side_effect = side_effect

        # Mock sync service
        mock_sync_instance = AsyncMock()
        mock_sync.return_value = mock_sync_instance

        # Execute migration
        stats = await migrate_tenant(
            tenant_id="test_tenant",
            dry_run=False
        )

        # Validate error tracking
        assert stats.errors == 1
        assert stats.episodes_created == 1  # 1 success, 1 erreur

        print(f"✅ Test 6: Gestion erreurs - {stats.errors} erreur, {stats.episodes_created} succès")


class TestAnalyzeMigrationNeeds:
    """Tests fonction analyze_migration_needs()"""

    @pytest.mark.asyncio
    @patch('knowbase.migration.qdrant_graphiti_migration.get_qdrant_client')
    async def test_analyze_migration_needs(self, mock_qdrant):
        """Test 7: Analyse retourne statistiques correctes"""
        # Mock chunks: 3 sans KG, 2 avec KG
        chunks = []

        for i in range(3):
            chunk = Mock()
            chunk.id = f"chunk_{i:03d}"
            chunk.payload = {
                "text": f"Content {i}",
                "filename": f"doc_{i % 2}.pptx",  # 2 fichiers distincts
                "has_knowledge_graph": False
            }
            chunks.append(chunk)

        for i in range(2):
            chunk = Mock()
            chunk.id = f"chunk_with_kg_{i:03d}"
            chunk.payload = {
                "text": f"Content with KG {i}",
                "filename": "doc_kg.pptx",
                "has_knowledge_graph": True
            }
            chunks.append(chunk)

        mock_qdrant.return_value.scroll.return_value = (chunks, None)

        # Execute
        analysis = await analyze_migration_needs(tenant_id="test_tenant")

        # Validate
        assert analysis['chunks_total'] == 5
        assert analysis['chunks_without_kg'] == 3
        assert analysis['chunks_with_kg'] == 2
        assert analysis['sources_count'] == 2  # 2 fichiers distincts (sans KG)
        assert analysis['migration_recommended'] is True

        # Top sources
        assert len(analysis['top_sources']) == 2

        print(f"✅ Test 7: Analyse - {analysis['chunks_without_kg']}/{analysis['chunks_total']} chunks à migrer")

    @pytest.mark.asyncio
    @patch('knowbase.migration.qdrant_graphiti_migration.get_qdrant_client')
    async def test_analyze_no_migration_needed(self, mock_qdrant):
        """Test 8: Analyse quand tous chunks ont déjà un KG"""
        # Mock chunks: tous avec KG
        chunks = []
        for i in range(5):
            chunk = Mock()
            chunk.id = f"chunk_{i:03d}"
            chunk.payload = {
                "text": f"Content {i}",
                "filename": "doc.pptx",
                "has_knowledge_graph": True
            }
            chunks.append(chunk)

        mock_qdrant.return_value.scroll.return_value = (chunks, None)

        # Execute
        analysis = await analyze_migration_needs(tenant_id="test_tenant")

        # Validate
        assert analysis['chunks_without_kg'] == 0
        assert analysis['migration_recommended'] is False

        print(f"✅ Test 8: Pas de migration nécessaire (tous chunks avec KG)")


class TestCombineChunksContent:
    """Tests fonction helper _combine_chunks_content()"""

    def test_combine_chunks_content_basic(self):
        """Test 9: Combine contenu chunks basique"""
        chunk1 = Mock()
        chunk1.payload = {"text": "First content"}

        chunk2 = Mock()
        chunk2.payload = {"text": "Second content"}

        combined = _combine_chunks_content([chunk1, chunk2])

        assert "First content" in combined
        assert "Second content" in combined
        assert len(combined) > 0

        print(f"✅ Test 9: Combine chunks - {len(combined)} chars")

    def test_combine_chunks_content_respects_max_chars(self):
        """Test 10: Limite max_chars respectée"""
        # Create chunk with long text
        chunk = Mock()
        chunk.payload = {"text": "A" * 20000}

        combined = _combine_chunks_content([chunk], max_chars=5000)

        assert len(combined) <= 5000

        print(f"✅ Test 10: Limite max_chars - {len(combined)} <= 5000 chars")


class TestMigrationStats:
    """Tests dataclass MigrationStats"""

    def test_migration_stats_to_dict(self):
        """Test 11: Conversion to_dict() fonctionne"""
        stats = MigrationStats(
            chunks_total=100,
            chunks_already_migrated=20,
            chunks_to_migrate=80,
            sources_found=10,
            episodes_created=10,
            chunks_migrated=80,
            errors=2,
            duration_seconds=45.5,
            dry_run=False
        )

        result = stats.to_dict()

        # Validate
        assert isinstance(result, dict)
        assert result['chunks_total'] == 100
        assert result['chunks_migrated'] == 80
        assert result['errors'] == 2
        assert result['dry_run'] is False

        print(f"✅ Test 11: to_dict() - {len(result)} clés")

    def test_migration_stats_print_report(self, capsys):
        """Test 12: print_report() affiche rapport"""
        stats = MigrationStats(
            chunks_total=50,
            chunks_already_migrated=10,
            chunks_to_migrate=40,
            sources_found=5,
            episodes_created=5,
            chunks_migrated=40,
            errors=0,
            duration_seconds=12.3,
            dry_run=True
        )

        stats.print_report()

        # Capture output
        captured = capsys.readouterr()

        # Validate rapport contient info clés
        assert "RAPPORT MIGRATION" in captured.out
        assert "DRY-RUN" in captured.out
        assert "50" in captured.out  # chunks_total
        assert "40" in captured.out  # chunks_to_migrate
        assert "5" in captured.out  # episodes_created

        print(f"✅ Test 12: print_report() génère rapport complet")


if __name__ == "__main__":
    # Exécution tests localement
    pytest.main([__file__, "-v", "-s"])
