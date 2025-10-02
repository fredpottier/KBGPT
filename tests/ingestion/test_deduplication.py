"""
Tests unitaires pour le module deduplication

Phase 1 - Critère 1.5
"""

import pytest
import hashlib
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch
from knowbase.ingestion.deduplication import (
    compute_file_hash,
    compute_content_hash,
    check_duplicate,
    get_import_metadata,
    get_imports_history,
    DuplicateStatus,
    DuplicateInfo
)


class TestComputeFileHash:
    """Tests calcul file_hash (SHA256 fichier brut)"""

    def test_compute_file_hash_same_file(self, tmp_path):
        """Test: même fichier → même hash"""
        file_path = tmp_path / "test.txt"
        file_path.write_text("Hello World", encoding="utf-8")

        hash1 = compute_file_hash(file_path)
        hash2 = compute_file_hash(file_path)

        assert hash1 == hash2
        assert hash1.startswith("sha256:")
        assert len(hash1) == 71  # "sha256:" + 64 caractères hex

    def test_compute_file_hash_different_files(self, tmp_path):
        """Test: fichiers différents → hashes différents"""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"

        file1.write_text("Content A", encoding="utf-8")
        file2.write_text("Content B", encoding="utf-8")

        hash1 = compute_file_hash(file1)
        hash2 = compute_file_hash(file2)

        assert hash1 != hash2

    def test_compute_file_hash_file_not_found(self, tmp_path):
        """Test: fichier inexistant → FileNotFoundError"""
        file_path = tmp_path / "nonexistent.txt"

        with pytest.raises(FileNotFoundError):
            compute_file_hash(file_path)

    def test_compute_file_hash_binary_file(self, tmp_path):
        """Test: fichier binaire (PPTX simulé)"""
        file_path = tmp_path / "test.pptx"
        file_path.write_bytes(b'\x50\x4b\x03\x04' * 100)  # ZIP signature + data

        hash_result = compute_file_hash(file_path)

        assert hash_result.startswith("sha256:")
        assert len(hash_result) == 71


class TestComputeContentHash:
    """Tests calcul content_hash (SHA256 contenu normalisé)"""

    def test_compute_content_hash_same_content(self):
        """Test: même contenu → même hash"""
        content = "This is a test content with some text"

        hash1 = compute_content_hash(content)
        hash2 = compute_content_hash(content)

        assert hash1 == hash2
        assert hash1.startswith("sha256:")

    def test_compute_content_hash_whitespace_normalization(self):
        """Test: normalisation whitespace (multiples espaces → simple)"""
        content1 = "Hello    World"
        content2 = "Hello World"

        hash1 = compute_content_hash(content1)
        hash2 = compute_content_hash(content2)

        # Doivent être identiques après normalisation
        assert hash1 == hash2

    def test_compute_content_hash_case_insensitive(self):
        """Test: insensible à la casse (lowercase normalization)"""
        content1 = "Hello World"
        content2 = "HELLO WORLD"

        hash1 = compute_content_hash(content1)
        hash2 = compute_content_hash(content2)

        assert hash1 == hash2

    def test_compute_content_hash_pptx_sort_lines(self):
        """Test: PPTX → tri lignes pour robustesse ordre slides"""
        content1 = "Slide 1\nSlide 2\nSlide 3"
        content2 = "Slide 3\nSlide 1\nSlide 2"

        hash1 = compute_content_hash(content1, source_type="pptx")
        hash2 = compute_content_hash(content2, source_type="pptx")

        # Doivent être identiques (ordre slides ignoré)
        assert hash1 == hash2

    def test_compute_content_hash_empty_content(self):
        """Test: contenu vide → hash SHA256 empty string"""
        content = ""

        hash_result = compute_content_hash(content)

        # SHA256 empty string (valeur connue)
        expected = "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        assert hash_result == expected

    def test_compute_content_hash_different_content(self):
        """Test: contenus différents → hashes différents"""
        content1 = "Content A"
        content2 = "Content B"

        hash1 = compute_content_hash(content1)
        hash2 = compute_content_hash(content2)

        assert hash1 != hash2


class TestCheckDuplicate:
    """Tests vérification duplicate via Qdrant"""

    @pytest.mark.asyncio
    async def test_check_duplicate_new_document(self):
        """Test: nouveau document (pas de match)"""
        # Mock Qdrant client
        mock_qdrant = Mock()
        mock_qdrant.scroll = Mock(return_value=([], None))

        content_hash = "sha256:abc123"
        tenant_id = "corporate"

        result = await check_duplicate(
            content_hash=content_hash,
            tenant_id=tenant_id,
            qdrant_client=mock_qdrant,
            collection_name="test_collection"
        )

        assert result.status == DuplicateStatus.NEW_DOCUMENT
        assert result.is_duplicate is False
        assert result.allow_upload is True
        assert result.existing_import_id is None

    @pytest.mark.asyncio
    async def test_check_duplicate_exact_match(self):
        """Test: duplicate exact (même content_hash)"""
        # Mock Qdrant client avec résultat
        mock_chunk = Mock()
        mock_chunk.payload = {
            "document": {
                "import_id": "import-123",
                "source_name": "existing_doc.pptx",
                "imported_at": "2025-10-01T10:00:00Z"
            },
            "episode_uuid": "ep_abc123"
        }

        mock_qdrant = Mock()
        mock_qdrant.scroll = Mock(return_value=([mock_chunk], None))

        # Mock count chunks (simulation)
        with patch('knowbase.ingestion.deduplication._count_chunks_by_import', new_callable=AsyncMock) as mock_count:
            mock_count.return_value = 42

            content_hash = "sha256:same_hash"
            tenant_id = "corporate"

            result = await check_duplicate(
                content_hash=content_hash,
                tenant_id=tenant_id,
                qdrant_client=mock_qdrant,
                collection_name="test_collection"
            )

            assert result.status == DuplicateStatus.EXACT_DUPLICATE
            assert result.is_duplicate is True
            assert result.allow_upload is False
            assert result.existing_import_id == "import-123"
            assert result.existing_filename == "existing_doc.pptx"
            assert result.existing_chunk_count == 42
            assert result.existing_episode_uuid == "ep_abc123"

    @pytest.mark.asyncio
    async def test_check_duplicate_error_handling(self):
        """Test: erreur Qdrant → fail-open (autoriser import)"""
        # Mock Qdrant qui raise exception
        mock_qdrant = Mock()
        mock_qdrant.scroll = Mock(side_effect=Exception("Qdrant connection error"))

        content_hash = "sha256:test"
        tenant_id = "corporate"

        result = await check_duplicate(
            content_hash=content_hash,
            tenant_id=tenant_id,
            qdrant_client=mock_qdrant,
            collection_name="test_collection"
        )

        # Fail-open: autoriser import malgré erreur
        assert result.status == DuplicateStatus.NEW_DOCUMENT
        assert result.allow_upload is True


class TestGetImportMetadata:
    """Tests récupération metadata import"""

    @pytest.mark.asyncio
    async def test_get_import_metadata_success(self):
        """Test: récupération metadata import existant"""
        # Mock Qdrant chunk
        mock_chunk = Mock()
        mock_chunk.payload = {
            "document": {
                "import_id": "import-456",
                "source_name": "my_doc.pptx",
                "source_file_hash": "sha256:file123",
                "content_hash": "sha256:content456",
                "imported_at": "2025-10-02T14:00:00Z"
            },
            "episode_uuid": "ep_xyz789"
        }

        mock_qdrant = Mock()
        mock_qdrant.scroll = Mock(return_value=([mock_chunk], None))

        with patch('knowbase.ingestion.deduplication._count_chunks_by_import', new_callable=AsyncMock) as mock_count:
            mock_count.return_value = 25

            metadata = await get_import_metadata(
                import_id="import-456",
                tenant_id="corporate",
                qdrant_client=mock_qdrant
            )

            assert metadata is not None
            assert metadata["import_id"] == "import-456"
            assert metadata["filename"] == "my_doc.pptx"
            assert metadata["chunk_count"] == 25
            assert metadata["episode_uuid"] == "ep_xyz789"

    @pytest.mark.asyncio
    async def test_get_import_metadata_not_found(self):
        """Test: import introuvable"""
        mock_qdrant = Mock()
        mock_qdrant.scroll = Mock(return_value=([], None))

        metadata = await get_import_metadata(
            import_id="nonexistent",
            tenant_id="corporate",
            qdrant_client=mock_qdrant
        )

        assert metadata is None


class TestGetImportsHistory:
    """Tests historique imports"""

    @pytest.mark.asyncio
    async def test_get_imports_history_multiple_imports(self):
        """Test: agrégation imports multiples"""
        # Mock 3 chunks de 2 imports différents
        mock_chunk1 = Mock()
        mock_chunk1.payload = {
            "document": {
                "import_id": "import-1",
                "source_name": "doc1.pptx",
                "source_file_hash": "sha256:hash1",
                "content_hash": "sha256:content1",
                "imported_at": "2025-10-02T10:00:00Z"
            },
            "episode_uuid": "ep_1"
        }

        mock_chunk2 = Mock()
        mock_chunk2.payload = {
            "document": {
                "import_id": "import-1",  # Même import
                "source_name": "doc1.pptx",
                "source_file_hash": "sha256:hash1",
                "content_hash": "sha256:content1",
                "imported_at": "2025-10-02T10:00:00Z"
            },
            "episode_uuid": "ep_1"
        }

        mock_chunk3 = Mock()
        mock_chunk3.payload = {
            "document": {
                "import_id": "import-2",  # Import différent
                "source_name": "doc2.pptx",
                "source_file_hash": "sha256:hash2",
                "content_hash": "sha256:content2",
                "imported_at": "2025-10-02T11:00:00Z"
            },
            "episode_uuid": "ep_2"
        }

        mock_qdrant = Mock()
        mock_qdrant.scroll = Mock(return_value=([mock_chunk1, mock_chunk2, mock_chunk3], None))

        history = await get_imports_history(
            tenant_id="corporate",
            qdrant_client=mock_qdrant,
            limit=10,
            offset=0
        )

        assert len(history) == 2  # 2 imports distincts
        # Vérifier agrégation chunk_count
        import1 = [h for h in history if h["import_id"] == "import-1"][0]
        assert import1["chunk_count"] == 2
        import2 = [h for h in history if h["import_id"] == "import-2"][0]
        assert import2["chunk_count"] == 1

    @pytest.mark.asyncio
    async def test_get_imports_history_pagination(self):
        """Test: pagination limit/offset"""
        # Mock 5 imports
        mock_chunks = []
        for i in range(5):
            mock_chunk = Mock()
            mock_chunk.payload = {
                "document": {
                    "import_id": f"import-{i}",
                    "source_name": f"doc{i}.pptx",
                    "imported_at": f"2025-10-02T{10+i}:00:00Z"
                },
                "episode_uuid": f"ep_{i}"
            }
            mock_chunks.append(mock_chunk)

        mock_qdrant = Mock()
        mock_qdrant.scroll = Mock(return_value=(mock_chunks, None))

        # Récupérer avec limit=2, offset=1
        history = await get_imports_history(
            tenant_id="corporate",
            qdrant_client=mock_qdrant,
            limit=2,
            offset=1
        )

        # Après offset=1, devrait retourner 2 éléments
        assert len(history) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
