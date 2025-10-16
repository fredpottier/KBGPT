"""
Tests pour EntityMergeService.

Phase 5B - Step 4
"""
import pytest
from unittest.mock import MagicMock, patch
from knowbase.api.services.entity_merge_service import EntityMergeService


class TestEntityMergeService:
    """Tests merge entités Neo4j."""

    @pytest.fixture
    def service(self):
        """Fixture service avec Neo4j mocké."""
        kg_service = MagicMock()
        return EntityMergeService(kg_service=kg_service)

    def test_merge_entities_no_duplicates(self, service):
        """✅ Aucune entité à merger."""
        result = service.merge_entities(
            master_uuid="master-1",
            duplicate_uuids=["master-1"],  # Même UUID
            canonical_name="Test",
            tenant_id="default"
        )

        assert result["duplicates_merged"] == 0
        assert result["relations_transferred"]["out"] == 0

    @patch("knowbase.api.services.entity_merge_service.GraphDatabase")
    def test_merge_entities_with_relations(self, mock_graph, service):
        """✅ Merge avec transfert relations."""
        # Mock Neo4j driver
        mock_driver = MagicMock()
        mock_session = MagicMock()
        mock_tx = MagicMock()

        mock_graph.driver.return_value = mock_driver
        mock_driver.session.return_value.__enter__.return_value = mock_session

        # Mock résultats queries
        def mock_execute_write(func):
            return func(mock_tx)

        mock_session.execute_write = mock_execute_write

        # Mock résultats run
        mock_tx.run.side_effect = [
            MagicMock(single=lambda: {"count_out": 3}),  # Relations OUT
            MagicMock(single=lambda: {"count_in": 2}),   # Relations IN
            MagicMock(),  # Update master
            MagicMock(single=lambda: {"deleted_count": 2})  # Delete
        ]

        result = service.merge_entities(
            master_uuid="master-1",
            duplicate_uuids=["dup-1", "dup-2"],
            canonical_name="Canonical Name",
            tenant_id="default"
        )

        assert result["duplicates_merged"] == 2
        assert result["relations_transferred"]["out"] == 3
        assert result["relations_transferred"]["in"] == 2
        assert result["canonical_name"] == "Canonical Name"

    def test_batch_merge_multiple_groups(self, service):
        """✅ Batch merge plusieurs groupes."""
        merge_groups = [
            {
                "canonical_key": "GROUP_A",
                "canonical_name": "Group A",
                "master_uuid": "master-a",
                "entities": [
                    {"uuid": "master-a", "name": "A"},
                    {"uuid": "dup-a1", "name": "A1"}
                ]
            },
            {
                "canonical_key": "GROUP_B",
                "canonical_name": "Group B",
                "master_uuid": "master-b",
                "entities": [
                    {"uuid": "master-b", "name": "B"},
                    {"uuid": "dup-b1", "name": "B1"}
                ]
            }
        ]

        # Mock merge_entities pour retourner succès
        service.merge_entities = MagicMock(side_effect=[
            {
                "duplicates_merged": 1,
                "relations_transferred": {"out": 1, "in": 0}
            },
            {
                "duplicates_merged": 1,
                "relations_transferred": {"out": 0, "in": 1}
            }
        ])

        result = service.batch_merge_from_preview(merge_groups)

        assert result["groups_processed"] == 2
        assert result["entities_merged"] == 2
        assert result["relations_transferred"]["out"] == 1
        assert result["relations_transferred"]["in"] == 1
        assert len(result["errors"]) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
