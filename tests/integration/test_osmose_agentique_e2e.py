"""
Tests end-to-end OSMOSE Architecture Agentique Phase 1.5.

Test complet du pipeline:
- Document → OsmoseAgentiqueService
- SupervisorAgent FSM (INIT → DONE)
- TopicSegmenter segmentation réelle
- ExtractorOrchestrator + PatternMiner + Gatekeeper
- Storage Neo4j Published-KG
- Métriques loggées
"""

import pytest
import asyncio
from pathlib import Path
from typing import Dict, Any

from knowbase.ingestion.osmose_agentique import OsmoseAgentiqueService
from knowbase.ingestion.osmose_integration import OsmoseIntegrationConfig


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_document_text() -> str:
    """Document test simple (texte SAP)."""
    return """
    SAP S/4HANA Cloud - Product Overview

    SAP S/4HANA Cloud is an intelligent ERP solution that runs on SAP HANA in-memory database.

    Key Features:
    - Real-time analytics and reporting
    - Machine Learning capabilities with SAP Leonardo
    - Integrated Fiori user experience
    - Cloud-native architecture with automatic updates

    Technical Architecture:
    The system leverages SAP HANA's columnar database for high-performance OLTP and OLAP workloads.
    Integration with SAP Business Technology Platform (BTP) enables seamless extensibility.

    Common Use Cases:
    - Finance and Controlling (FI/CO)
    - Materials Management (MM)
    - Sales and Distribution (SD)
    - Production Planning (PP)

    SAP S/4HANA Cloud supports multi-tenancy and offers flexible deployment options.
    """


@pytest.fixture
def osmose_config() -> OsmoseIntegrationConfig:
    """Configuration OSMOSE pour tests."""
    return OsmoseIntegrationConfig(
        enable_osmose=True,
        osmose_for_pdf=True,
        osmose_for_pptx=True,
        min_text_length=100,
        max_text_length=100_000,
        default_tenant_id="test_tenant",
        timeout_seconds=300
    )


@pytest.fixture
def supervisor_config() -> Dict[str, Any]:
    """Configuration SupervisorAgent pour tests."""
    return {
        "max_steps": 50,
        "timeout_seconds": 300,
        "retry_on_low_quality": True,
        "default_gate_profile": "BALANCED"
    }


# ============================================================================
# Tests End-to-End
# ============================================================================

@pytest.mark.asyncio
async def test_osmose_agentique_full_pipeline(
    sample_document_text: str,
    osmose_config: OsmoseIntegrationConfig,
    supervisor_config: Dict[str, Any],
    tmp_path: Path
):
    """
    Test E2E: Document → SupervisorAgent FSM → Neo4j Published-KG.

    Vérifie:
    - FSM parcourt tous les états (INIT → DONE)
    - Segmentation réelle (TopicSegmenter)
    - Extraction concepts (NER)
    - Promotion concepts (Gatekeeper → Neo4j)
    - Métriques loggées (cost, llm_calls, promotion_rate)
    """
    # Créer document test
    test_doc_path = tmp_path / "test_doc.txt"
    test_doc_path.write_text(sample_document_text)

    # Initialiser service
    service = OsmoseAgentiqueService(
        config=osmose_config,
        supervisor_config=supervisor_config
    )

    # Traiter document
    result = await service.process_document_agentique(
        document_id="test_doc_001",
        document_title="SAP S/4HANA Cloud Overview",
        document_path=test_doc_path,
        text_content=sample_document_text,
        tenant_id="test_tenant"
    )

    # Assertions basiques
    assert result.osmose_success is True, f"Pipeline failed: {result.osmose_error}"
    assert result.document_id == "test_doc_001"

    # Vérifier FSM completion
    assert result.final_fsm_state is not None
    assert result.final_fsm_state in ["DONE", "FINALIZE"], \
        f"FSM did not complete: final_state={result.final_fsm_state}"

    # Vérifier steps FSM
    assert result.fsm_steps_count > 0, "FSM did not execute any steps"
    assert result.fsm_steps_count <= supervisor_config["max_steps"], \
        f"FSM exceeded max_steps: {result.fsm_steps_count}"

    # Vérifier segmentation
    assert result.segments_count > 0, "TopicSegmenter did not produce segments"

    # Vérifier extraction concepts
    assert result.concepts_extracted >= 0, "Concepts extraction failed"

    # Vérifier métriques LLM
    assert result.llm_calls_count is not None
    assert "SMALL" in result.llm_calls_count or "BIG" in result.llm_calls_count, \
        "No LLM calls recorded"

    # Vérifier cost tracking
    assert result.cost >= 0.0, "Cost tracking failed"

    # Vérifier promotion
    if result.concepts_extracted > 0:
        assert result.concepts_promoted >= 0, "Promotion count missing"
        promotion_rate = result.concepts_promoted / result.concepts_extracted if result.concepts_extracted > 0 else 0.0
        assert 0.0 <= promotion_rate <= 1.0, f"Invalid promotion rate: {promotion_rate}"

    # Vérifier durée
    assert result.total_duration_seconds > 0.0
    assert result.total_duration_seconds < supervisor_config["timeout_seconds"], \
        f"Processing timeout: {result.total_duration_seconds}s"

    print(f"\n✅ E2E Test PASSED:")
    print(f"  - FSM: {result.final_fsm_state} ({result.fsm_steps_count} steps)")
    print(f"  - Segments: {result.segments_count}")
    print(f"  - Concepts: {result.concepts_extracted} extracted, {result.concepts_promoted} promoted")
    print(f"  - LLM Calls: {result.llm_calls_count}")
    print(f"  - Cost: ${result.cost:.4f}")
    print(f"  - Duration: {result.total_duration_seconds:.2f}s")


@pytest.mark.asyncio
async def test_osmose_agentique_short_document_filtered(
    osmose_config: OsmoseIntegrationConfig,
    supervisor_config: Dict[str, Any],
    tmp_path: Path
):
    """
    Test E2E: Document trop court → filtré par should_process_with_osmose.
    """
    short_text = "This is too short."

    test_doc_path = tmp_path / "short_doc.txt"
    test_doc_path.write_text(short_text)

    service = OsmoseAgentiqueService(
        config=osmose_config,
        supervisor_config=supervisor_config
    )

    result = await service.process_document_agentique(
        document_id="short_doc_001",
        document_title="Short Document",
        document_path=test_doc_path,
        text_content=short_text,
        tenant_id="test_tenant"
    )

    # Document doit être skippé
    assert result.osmose_success is False
    assert "too short" in result.osmose_error.lower()

    print(f"\n✅ Short Document Filter Test PASSED:")
    print(f"  - Reason: {result.osmose_error}")


@pytest.mark.asyncio
async def test_osmose_agentique_neo4j_unavailable_degraded_mode(
    sample_document_text: str,
    osmose_config: OsmoseIntegrationConfig,
    tmp_path: Path
):
    """
    Test E2E: Neo4j unavailable → mode dégradé (promotion skipped).

    Vérifie que le pipeline continue sans Neo4j.
    """
    test_doc_path = tmp_path / "test_doc_neo4j_down.txt"
    test_doc_path.write_text(sample_document_text)

    # Config Supervisor avec Neo4j invalide
    supervisor_config_invalid_neo4j = {
        "max_steps": 50,
        "timeout_seconds": 300,
        "neo4j_uri": "bolt://invalid_host:7687",  # Neo4j invalide
        "neo4j_user": "neo4j",
        "neo4j_password": "wrong_password"
    }

    service = OsmoseAgentiqueService(
        config=osmose_config,
        supervisor_config=supervisor_config_invalid_neo4j
    )

    result = await service.process_document_agentique(
        document_id="test_doc_neo4j_down",
        document_title="Neo4j Unavailable Test",
        document_path=test_doc_path,
        text_content=sample_document_text,
        tenant_id="test_tenant"
    )

    # Pipeline doit réussir en mode dégradé
    assert result.osmose_success is True, \
        "Pipeline should succeed in degraded mode (Neo4j unavailable)"

    # Promotion skipped (count = 0)
    assert result.concepts_promoted == 0, \
        "Promotion should be skipped when Neo4j unavailable"

    print(f"\n✅ Degraded Mode Test PASSED:")
    print(f"  - Pipeline succeeded without Neo4j")
    print(f"  - Promotion skipped (degraded mode)")


# ============================================================================
# Tests Métriques
# ============================================================================

@pytest.mark.asyncio
async def test_osmose_agentique_metrics_logging(
    sample_document_text: str,
    osmose_config: OsmoseIntegrationConfig,
    supervisor_config: Dict[str, Any],
    tmp_path: Path
):
    """
    Test E2E: Vérifier que toutes les métriques sont loggées.
    """
    test_doc_path = tmp_path / "test_metrics.txt"
    test_doc_path.write_text(sample_document_text)

    service = OsmoseAgentiqueService(
        config=osmose_config,
        supervisor_config=supervisor_config
    )

    result = await service.process_document_agentique(
        document_id="test_metrics_001",
        document_title="Metrics Test",
        document_path=test_doc_path,
        text_content=sample_document_text,
        tenant_id="test_tenant"
    )

    # Vérifier présence métriques
    assert result.cost is not None, "Cost metric missing"
    assert result.llm_calls_count is not None, "LLM calls metric missing"
    assert result.segments_count is not None, "Segments count metric missing"
    assert result.concepts_extracted is not None, "Concepts extracted metric missing"
    assert result.concepts_promoted is not None, "Concepts promoted metric missing"
    assert result.total_duration_seconds is not None, "Duration metric missing"
    assert result.final_fsm_state is not None, "FSM state metric missing"
    assert result.fsm_steps_count is not None, "FSM steps metric missing"

    # Vérifier budget_remaining structure
    assert result.budget_remaining is not None
    assert "SMALL" in result.budget_remaining
    assert "BIG" in result.budget_remaining
    assert "VISION" in result.budget_remaining

    print(f"\n✅ Metrics Logging Test PASSED:")
    print(f"  - All metrics present and valid")


# ============================================================================
# Tests Performance
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.slow
async def test_osmose_agentique_performance_target(
    sample_document_text: str,
    osmose_config: OsmoseIntegrationConfig,
    supervisor_config: Dict[str, Any],
    tmp_path: Path
):
    """
    Test E2E: Vérifier performance < 30s/doc (P95 target).

    Note: Test marqué slow, exécuter avec pytest -m slow
    """
    test_doc_path = tmp_path / "test_perf.txt"
    test_doc_path.write_text(sample_document_text)

    service = OsmoseAgentiqueService(
        config=osmose_config,
        supervisor_config=supervisor_config
    )

    result = await service.process_document_agentique(
        document_id="test_perf_001",
        document_title="Performance Test",
        document_path=test_doc_path,
        text_content=sample_document_text,
        tenant_id="test_tenant"
    )

    # Vérifier target performance
    assert result.total_duration_seconds < 30.0, \
        f"Performance target missed: {result.total_duration_seconds:.2f}s > 30s"

    print(f"\n✅ Performance Target Test PASSED:")
    print(f"  - Duration: {result.total_duration_seconds:.2f}s < 30s target")
