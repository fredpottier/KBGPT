"""
Tests Request ID Middleware - Phase 0.5 Durcissement P0.4
"""
import pytest
import logging
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from knowbase.api.middleware.request_id import (
    RequestIDMiddleware,
    get_request_id,
    set_request_id,
    RequestIDLogFilter,
    configure_request_id_logging
)


@pytest.fixture
def app():
    """Application FastAPI test avec middleware Request ID"""
    app = FastAPI()

    # Ajouter middleware
    app.add_middleware(RequestIDMiddleware)

    # Endpoints test
    @app.get("/test")
    async def test_endpoint():
        return {"request_id": get_request_id()}

    @app.get("/test/nested")
    async def test_nested():
        # Simuler appel service qui utilise request_id
        req_id = get_request_id()
        return {"nested_request_id": req_id}

    @app.get("/test/error")
    async def test_error():
        raise ValueError("Test error")

    return app


@pytest.fixture
def client(app):
    """Client test FastAPI"""
    return TestClient(app)


class TestRequestIDMiddlewareBasic:
    """Tests fonctionnalités de base du middleware"""

    def test_generates_request_id(self, client):
        """
        Test génération automatique request_id

        Expected: Header X-Request-ID présent dans response
        """
        response = client.get("/test")

        assert response.status_code == 200
        assert "X-Request-ID" in response.headers

        request_id = response.headers["X-Request-ID"]
        assert len(request_id) == 36  # UUID format

        # Vérifier aussi dans body
        data = response.json()
        assert data["request_id"] == request_id

        print(f"OK: Request ID generated: {request_id}")

    def test_accepts_client_request_id(self, client):
        """
        Test propagation request_id depuis client

        Expected: Request_id client propagé dans response
        """
        custom_id = "custom-req-id-12345"

        response = client.get(
            "/test",
            headers={"X-Request-ID": custom_id}
        )

        assert response.status_code == 200
        assert response.headers["X-Request-ID"] == custom_id

        data = response.json()
        assert data["request_id"] == custom_id

        print(f"OK: Client request ID propagated: {custom_id}")

    def test_request_id_accessible_in_handler(self, client):
        """
        Test request_id accessible via get_request_id() dans handler

        Expected: Même request_id partout dans la requête
        """
        response = client.get("/test/nested")

        assert response.status_code == 200

        header_id = response.headers["X-Request-ID"]
        body_id = response.json()["nested_request_id"]

        assert header_id == body_id

        print(f"OK: Request ID accessible in handler: {header_id}")

    def test_different_requests_different_ids(self, client):
        """
        Test requêtes différentes ont request_id différents

        Expected: Chaque requête a un UUID unique
        """
        response1 = client.get("/test")
        response2 = client.get("/test")

        id1 = response1.headers["X-Request-ID"]
        id2 = response2.headers["X-Request-ID"]

        assert id1 != id2

        print(f"OK: Different request IDs: {id1[:12]}... vs {id2[:12]}...")


class TestRequestIDContext:
    """Tests contextvars et isolation"""

    def test_get_request_id_outside_request(self):
        """
        Test get_request_id() hors requête HTTP

        Expected: Retourne "no-request-id" par défaut
        """
        req_id = get_request_id()
        assert req_id == "no-request-id"

        print("OK: get_request_id() outside request returns default")

    def test_set_and_get_request_id(self):
        """
        Test set/get request_id manuel

        Expected: Valeur stockée/récupérée correctement
        """
        test_id = "manual-test-id-789"
        set_request_id(test_id)

        retrieved = get_request_id()
        assert retrieved == test_id

        print(f"OK: Manual set/get request ID: {test_id}")


class TestRequestIDLogging:
    """Tests injection request_id dans logs"""

    def test_log_filter_adds_request_id(self):
        """
        Test RequestIDLogFilter ajoute request_id au LogRecord

        Expected: LogRecord enrichi avec attribut request_id
        """
        # Configurer logger test
        logger = logging.getLogger("test_request_id")
        logger.setLevel(logging.INFO)

        # Ajouter filter
        handler = logging.StreamHandler()
        handler.addFilter(RequestIDLogFilter())
        logger.addHandler(handler)

        # Set request_id dans context
        set_request_id("test-log-id-456")

        # Créer LogRecord
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None
        )

        # Appliquer filter
        log_filter = RequestIDLogFilter()
        log_filter.filter(record)

        # Vérifier attribut request_id ajouté
        assert hasattr(record, "request_id")
        assert record.request_id == "test-log-id-"  # Tronqué à 12 chars

        print(f"OK: Log filter adds request_id: {record.request_id}")

    def test_log_filter_truncates_long_id(self):
        """
        Test log filter tronque request_id long à 12 chars

        Expected: UUID tronqué pour lisibilité logs
        """
        set_request_id("very-long-request-id-1234567890-abcdef")

        log_filter = RequestIDLogFilter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test",
            args=(),
            exc_info=None
        )

        log_filter.filter(record)

        assert len(record.request_id) == 12
        assert record.request_id == "very-long-re"

        print(f"OK: Request ID truncated: {record.request_id}")


class TestRequestIDMiddlewareError:
    """Tests gestion erreurs avec request_id"""

    def test_request_id_logged_on_error(self, client, caplog):
        """
        Test request_id logué même si endpoint raise exception

        Expected: Request_id présent dans logs d'erreur
        """
        with caplog.at_level(logging.ERROR):
            try:
                response = client.get("/test/error")
            except Exception:
                pass  # Exception propagée OK

        # Vérifier logs contiennent request_id
        error_logs = [r for r in caplog.records if r.levelname == "ERROR"]
        assert len(error_logs) > 0

        # Log doit mentionner req_id
        error_msg = error_logs[0].message
        assert "req_id=" in error_msg

        print(f"OK: Request ID logged on error: {error_msg[:80]}...")


class TestRequestIDIntegration:
    """Tests intégration complète"""

    def test_request_id_propagation_end_to_end(self, client):
        """
        Test propagation request_id end-to-end

        Expected: Request_id client → middleware → handler → response
        """
        custom_id = "e2e-test-request-id"

        response = client.get(
            "/test/nested",
            headers={"X-Request-ID": custom_id}
        )

        assert response.status_code == 200

        # Vérifier header response
        assert response.headers["X-Request-ID"] == custom_id

        # Vérifier body response
        data = response.json()
        assert data["nested_request_id"] == custom_id

        print(f"OK: End-to-end propagation: {custom_id}")

    def test_multiple_concurrent_requests(self, client):
        """
        Test isolation request_id entre requêtes concurrentes

        Expected: Chaque requête a son propre request_id isolé
        """
        # Simuler 5 requêtes "concurrentes" (séquentielles mais rapides)
        ids = []
        for i in range(5):
            response = client.get("/test")
            req_id = response.headers["X-Request-ID"]
            ids.append(req_id)

        # Vérifier tous différents
        unique_ids = set(ids)
        assert len(unique_ids) == 5

        print(f"OK: 5 concurrent requests with unique IDs: {[id[:8] for id in ids]}")


class TestConfigureRequestIDLogging:
    """Tests configuration logging globale"""

    def test_configure_adds_filter_to_handlers(self):
        """
        Test configure_request_id_logging() ajoute filter à tous handlers

        Expected: Tous handlers root logger ont RequestIDLogFilter
        """
        # Configurer logging test
        logger = logging.getLogger()
        handler = logging.StreamHandler()
        logger.addHandler(handler)

        # Configurer request_id logging
        configure_request_id_logging()

        # Vérifier filter ajouté
        filters = [f for f in handler.filters if isinstance(f, RequestIDLogFilter)]
        assert len(filters) >= 1

        # Cleanup
        logger.removeHandler(handler)

        print("OK: configure_request_id_logging adds filter")
