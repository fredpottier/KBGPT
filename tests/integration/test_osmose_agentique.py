"""
Tests d'intégration pour OSMOSE Agentique Phase 1.5.
"""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.knowbase.ingestion.osmose_agentique import (
    OsmoseAgentiqueService,
    process_document_with_osmose_agentique
)
from src.knowbase.ingestion.osmose_integration import OsmoseIntegrationConfig
from src.knowbase.agents.base import AgentState


class TestOsmoseAgentiqueService:
    """Tests pour OsmoseAgentiqueService."""

    @pytest.fixture
    def config(self):
        """Fixture configuration OSMOSE."""
        return OsmoseIntegrationConfig(
            enable_osmose=True,
            osmose_for_pptx=True,
            osmose_for_pdf=True,
            min_text_length=100,
            timeout_seconds=60
        )

    @pytest.fixture
    def service(self, config):
        """Fixture service agentique."""
        return OsmoseAgentiqueService(config=config)

    def test_service_initialization(self, service):
        """Test initialisation service."""
        assert service.config.enable_osmose is True
        assert service.supervisor is None  # Lazy init

    def test_get_supervisor_lazy_init(self, service):
        """Test lazy initialization SupervisorAgent."""
        # Premier appel: création
        supervisor = service._get_supervisor()
        assert supervisor is not None
        assert service.supervisor is supervisor

        # Deuxième appel: même instance
        supervisor2 = service._get_supervisor()
        assert supervisor2 is supervisor

    def test_should_process_with_osmose_valid(self, service):
        """Test filtres activation - document valide."""
        should_process, reason = service._should_process_with_osmose(
            document_type="pptx",
            text_content="A" * 1000  # 1000 chars
        )

        assert should_process is True
        assert reason is None

    def test_should_process_with_osmose_too_short(self, service):
        """Test filtres activation - texte trop court."""
        should_process, reason = service._should_process_with_osmose(
            document_type="pptx",
            text_content="Short"  # 5 chars < 100
        )

        assert should_process is False
        assert "too short" in reason.lower()

    def test_should_process_with_osmose_disabled(self):
        """Test filtres activation - OSMOSE désactivé."""
        config = OsmoseIntegrationConfig(enable_osmose=False)
        service = OsmoseAgentiqueService(config=config)

        should_process, reason = service._should_process_with_osmose(
            document_type="pptx",
            text_content="A" * 1000
        )

        assert should_process is False
        assert "disabled" in reason.lower()

    @pytest.mark.asyncio
    async def test_process_document_agentique_skipped(self, service):
        """Test traitement document - skip (texte trop court)."""
        result = await service.process_document_agentique(
            document_id="test-doc",
            document_title="Test Document",
            document_path=Path("/tmp/test.pptx"),
            text_content="Too short",  # < 100 chars
            tenant_id="test-tenant"
        )

        assert result.osmose_success is False
        assert "too short" in result.osmose_error.lower()
        assert result.concepts_extracted == 0

    @pytest.mark.skip(reason="Test mocke FSM SupervisorAgent mais Hybrid Anchor Model est activé par défaut")
    @pytest.mark.asyncio
    async def test_process_document_agentique_success_mock(self, service):
        """Test traitement document - succès (SupervisorAgent mocké)."""
        # Mock SupervisorAgent
        mock_supervisor = MagicMock()

        # Mock final state après FSM
        final_state = AgentState(
            document_id="test-doc",
            tenant_id="test-tenant"
        )
        final_state.current_step = "done"
        final_state.steps_count = 10
        final_state.cost_incurred = 0.05
        final_state.candidates = [
            {"name": "SAP S/4HANA", "type": "PRODUCT"},
            {"name": "SAP Fiori", "type": "TOOL"}
        ]
        final_state.promoted = [
            {"name": "SAP S/4HANA", "type": "PRODUCT"}
        ]
        final_state.llm_calls_count = {"SMALL": 5, "BIG": 1, "VISION": 0}
        final_state.budget_remaining = {"SMALL": 115, "BIG": 7, "VISION": 2}
        final_state.errors = []

        mock_supervisor.execute = AsyncMock(return_value=final_state)

        # Injecter mock dans service
        service.supervisor = mock_supervisor

        # Exécuter traitement
        result = await service.process_document_agentique(
            document_id="test-doc",
            document_title="Test SAP Document",
            document_path=Path("/tmp/test.pptx"),
            text_content="A" * 1000,  # Texte suffisant
            tenant_id="test-tenant"
        )

        # Vérifications
        assert result.osmose_success is True
        assert result.osmose_error is None
        assert result.concepts_extracted == 2  # candidates
        assert result.canonical_concepts == 1  # promoted
        assert result.document_id == "test-doc"
        assert result.document_type == "pptx"

        # Vérifier que SupervisorAgent.execute a été appelé
        mock_supervisor.execute.assert_called_once()

    @pytest.mark.skip(reason="Test mocke FSM SupervisorAgent mais Hybrid Anchor Model est activé par défaut")
    @pytest.mark.asyncio
    async def test_process_document_agentique_fsm_error(self, service):
        """Test traitement document - erreur FSM."""
        # Mock SupervisorAgent avec erreurs
        mock_supervisor = MagicMock()

        final_state = AgentState(
            document_id="test-doc",
            tenant_id="test-tenant"
        )
        final_state.current_step = "error"
        final_state.errors = ["Budget insufficient", "Max steps reached"]
        final_state.candidates = []
        final_state.promoted = []

        mock_supervisor.execute = AsyncMock(return_value=final_state)

        service.supervisor = mock_supervisor

        # Exécuter traitement
        result = await service.process_document_agentique(
            document_id="test-doc",
            document_title="Test Document",
            document_path=Path("/tmp/test.pptx"),
            text_content="A" * 1000,
            tenant_id="test-tenant"
        )

        # Vérifications
        assert result.osmose_success is False
        assert result.osmose_error is not None
        assert "Budget insufficient" in result.osmose_error
        assert result.concepts_extracted == 0
        assert result.canonical_concepts == 0

    @pytest.mark.skip(reason="Test mocke FSM SupervisorAgent mais Hybrid Anchor Model est activé par défaut")
    @pytest.mark.asyncio
    async def test_process_document_agentique_timeout(self):
        """Test traitement document - timeout."""
        # Config avec timeout très court
        config = OsmoseIntegrationConfig(
            enable_osmose=True,
            timeout_seconds=0.1  # 100ms
        )
        service = OsmoseAgentiqueService(config=config)

        # Mock SupervisorAgent qui prend trop de temps
        mock_supervisor = MagicMock()

        async def slow_execute(state):
            import asyncio
            await asyncio.sleep(1)  # 1s > 100ms
            return state

        mock_supervisor.execute = slow_execute

        service.supervisor = mock_supervisor

        # Exécuter traitement
        result = await service.process_document_agentique(
            document_id="test-doc",
            document_title="Test Document",
            document_path=Path("/tmp/test.pptx"),
            text_content="A" * 1000,
            tenant_id="test-tenant"
        )

        # Vérifications
        assert result.osmose_success is False
        assert result.osmose_error is not None
        assert "timeout" in result.osmose_error.lower()


class TestHelperFunction:
    """Tests pour helper function process_document_with_osmose_agentique."""

    @pytest.mark.asyncio
    async def test_helper_function_skipped(self):
        """Test helper function - document skip."""
        result = await process_document_with_osmose_agentique(
            document_id="test-doc",
            document_title="Test Document",
            document_path=Path("/tmp/test.pptx"),
            text_content="Too short",
            tenant_id="test-tenant"
        )

        assert result.osmose_success is False
        assert "too short" in result.osmose_error.lower()

    @pytest.mark.asyncio
    async def test_helper_function_with_custom_config(self):
        """Test helper function avec config custom."""
        config = OsmoseIntegrationConfig(
            enable_osmose=True,
            min_text_length=10,  # Seuil bas pour test
            timeout_seconds=60
        )

        # Mock service pour éviter exécution réelle
        with patch('src.knowbase.ingestion.osmose_agentique.OsmoseAgentiqueService') as mock_service_class:
            mock_service_instance = MagicMock()
            mock_service_class.return_value = mock_service_instance

            # Mock result
            mock_result = MagicMock()
            mock_result.osmose_success = True
            mock_service_instance.process_document_agentique = AsyncMock(return_value=mock_result)

            # Appeler helper
            result = await process_document_with_osmose_agentique(
                document_id="test-doc",
                document_title="Test Document",
                document_path=Path("/tmp/test.pptx"),
                text_content="Valid text content",
                tenant_id="test-tenant",
                config=config
            )

            # Vérifier que service a été créé avec config
            mock_service_class.assert_called_once_with(config=config)

            # Vérifier que process_document_agentique a été appelé
            mock_service_instance.process_document_agentique.assert_called_once()
