"""
Fixtures pytest pour tests API Facts.

Fournit mocks Neo4j, client test FastAPI, et données de test.
"""

from __future__ import annotations

import pytest
from datetime import datetime
from typing import Generator, Dict, Any
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient


@pytest.fixture
def mock_neo4j_client() -> Mock:
    """Mock du client Neo4j pour isoler les tests."""
    client = Mock()
    client.session.return_value.__enter__ = Mock()
    client.session.return_value.__exit__ = Mock()
    return client


@pytest.fixture
def mock_facts_queries(mock_neo4j_client: Mock) -> Mock:
    """Mock de FactsQueries avec méthodes pré-configurées."""
    queries = Mock()
    queries.client = mock_neo4j_client
    queries.tenant_id = "test_tenant"

    # Données fact par défaut
    queries.default_fact = {
        "uuid": "fact-uuid-123",
        "tenant_id": "test_tenant",
        "subject": "SAP S/4HANA Cloud",
        "predicate": "SLA_garantie",
        "object": "99.7%",
        "value": 99.7,
        "unit": "%",
        "value_type": "numeric",
        "fact_type": "SERVICE_LEVEL",
        "status": "proposed",
        "confidence": 0.95,
        "valid_from": "2024-01-01T00:00:00",
        "valid_until": None,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "source_chunk_id": "chunk-123",
        "source_document": "proposal_2024.pdf",
        "approved_by": None,
        "approved_at": None,
        "extraction_method": "llm_vision",
        "extraction_model": "gpt-4-vision",
        "extraction_prompt_id": "extract_facts_v1"
    }

    return queries


@pytest.fixture
def sample_fact_create() -> Dict[str, Any]:
    """Payload création fact valide."""
    return {
        "subject": "SAP S/4HANA Cloud, Private Edition",
        "predicate": "SLA_garantie",
        "object": "99.7%",
        "value": 99.7,
        "unit": "%",
        "value_type": "numeric",
        "fact_type": "SERVICE_LEVEL",
        "status": "proposed",
        "confidence": 0.95,
        "valid_from": "2024-01-01T00:00:00",
        "source_document": "proposal_2024.pdf",
        "extraction_method": "llm_vision",
        "extraction_model": "gpt-4-vision",
        "extraction_prompt_id": "extract_facts_v1"
    }


@pytest.fixture
def sample_fact_response(mock_facts_queries: Mock) -> Dict[str, Any]:
    """Réponse fact complète."""
    return mock_facts_queries.default_fact


@pytest.fixture
def sample_conflict() -> Dict[str, Any]:
    """Conflit type CONTRADICTS."""
    return {
        "conflict_type": "CONTRADICTS",
        "value_diff_pct": 0.002,
        "fact_approved": {
            "uuid": "fact-approved-123",
            "subject": "SAP S/4HANA Cloud",
            "predicate": "SLA_garantie",
            "value": 99.7,
            "status": "approved"
        },
        "fact_proposed": {
            "uuid": "fact-proposed-456",
            "subject": "SAP S/4HANA Cloud",
            "predicate": "SLA_garantie",
            "value": 99.5,
            "status": "proposed"
        }
    }


@pytest.fixture
def test_client() -> Generator[TestClient, None, None]:
    """Client de test FastAPI avec mocks Neo4j."""
    from knowbase.api.main import create_app

    # Patch get_neo4j_client pour éviter connexion réelle
    with patch("knowbase.neo4j_custom.get_neo4j_client") as mock_get_client:
        mock_client = Mock()
        mock_get_client.return_value = mock_client

        app = create_app()

        with TestClient(app) as client:
            yield client


@pytest.fixture
def auth_headers() -> Dict[str, str]:
    """Headers d'authentification JWT pour tests."""
    from knowbase.api.services.auth_service import get_auth_service

    auth_service = get_auth_service()
    token = auth_service.generate_access_token(
        user_id="test-user-id",
        email="test_user@example.com",
        role="editor",
        tenant_id="test_tenant"
    )

    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }


@pytest.fixture
def sample_stats() -> Dict[str, Any]:
    """Statistiques facts pour tests."""
    return {
        "total_facts": 156,
        "by_status": {
            "proposed": 23,
            "approved": 120,
            "rejected": 10,
            "conflicted": 3
        },
        "by_type": {
            "SERVICE_LEVEL": 45,
            "CAPACITY": 32,
            "PRICING": 28,
            "FEATURE": 35,
            "GENERAL": 16
        },
        "conflicts_count": 3,
        "latest_fact_created_at": "2024-10-03T16:45:00"
    }


@pytest.fixture
def sample_timeline() -> list[Dict[str, Any]]:
    """Timeline fact pour tests."""
    return [
        {
            "value": 99.5,
            "unit": "%",
            "valid_from": "2023-01-01T00:00:00",
            "valid_until": "2023-12-31T23:59:59",
            "source_document": "proposal_2023.pdf",
            "status": "approved"
        },
        {
            "value": 99.7,
            "unit": "%",
            "valid_from": "2024-01-01T00:00:00",
            "valid_until": None,
            "source_document": "proposal_2024.pdf",
            "status": "approved"
        }
    ]
