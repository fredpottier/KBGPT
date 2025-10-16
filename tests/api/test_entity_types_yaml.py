"""
Tests pour endpoints Import/Export YAML Entity Types.

Phase 4 Enhancement - YAML Import/Export
"""
import io
import pytest
from fastapi.testclient import TestClient


class TestEntityTypesYAMLImport:
    """Tests pour POST /api/entity-types/import-yaml."""

    def test_import_yaml_success(self, client: TestClient):
        """✅ Import YAML valide crée types."""
        yaml_content = """
TECHNOLOGY:
  canonical_name: "Technology"
  description: "Technology entities"
  category: "Tech"

COMPONENT:
  canonical_name: "Component"
  description: "Component entities"
"""
        file = io.BytesIO(yaml_content.encode('utf-8'))

        response = client.post(
            "/api/entity-types/import-yaml?auto_approve=true&skip_existing=true",
            files={"file": ("test.yaml", file, "application/x-yaml")}
        )

        assert response.status_code == 200
        data = response.json()

        assert "created" in data
        assert "skipped" in data
        assert "errors" in data
        assert data["created"] >= 2  # Au moins TECHNOLOGY et COMPONENT
        assert isinstance(data["types"], list)

    def test_import_yaml_invalid_format(self, client: TestClient):
        """❌ YAML invalide retourne 400."""
        invalid_yaml = "invalid: yaml: content: ["
        file = io.BytesIO(invalid_yaml.encode('utf-8'))

        response = client.post(
            "/api/entity-types/import-yaml",
            files={"file": ("test.yaml", file, "application/x-yaml")}
        )

        assert response.status_code == 400
        assert "Invalid YAML format" in response.json()["detail"]

    def test_import_yaml_wrong_extension(self, client: TestClient):
        """❌ Extension non-.yaml retourne 400."""
        yaml_content = "TECHNOLOGY:\n  description: test"
        file = io.BytesIO(yaml_content.encode('utf-8'))

        response = client.post(
            "/api/entity-types/import-yaml",
            files={"file": ("test.txt", file, "text/plain")}
        )

        assert response.status_code == 400
        assert "must be .yaml or .yml" in response.json()["detail"]

    def test_import_yaml_skip_existing(self, client: TestClient):
        """✅ Skip existing=true ignore types existants."""
        # Premier import
        yaml_content = "SOLUTION:\n  description: Solution type"
        file1 = io.BytesIO(yaml_content.encode('utf-8'))

        response1 = client.post(
            "/api/entity-types/import-yaml?auto_approve=true",
            files={"file": ("test1.yaml", file1, "application/x-yaml")}
        )
        assert response1.status_code == 200
        assert response1.json()["created"] == 1

        # Second import (doit skip)
        file2 = io.BytesIO(yaml_content.encode('utf-8'))
        response2 = client.post(
            "/api/entity-types/import-yaml?auto_approve=true&skip_existing=true",
            files={"file": ("test2.yaml", file2, "application/x-yaml")}
        )

        assert response2.status_code == 200
        assert response2.json()["skipped"] == 1
        assert response2.json()["created"] == 0

    def test_import_yaml_auto_approve_false(self, client: TestClient):
        """✅ Auto-approve=false crée types en pending."""
        yaml_content = "CUSTOM_TYPE:\n  description: Custom"
        file = io.BytesIO(yaml_content.encode('utf-8'))

        response = client.post(
            "/api/entity-types/import-yaml?auto_approve=false",
            files={"file": ("test.yaml", file, "application/x-yaml")}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["created"] >= 1

        # Vérifier status pending
        type_response = client.get("/api/entity-types/CUSTOM_TYPE")
        assert type_response.status_code == 200
        assert type_response.json()["status"] == "pending"


class TestEntityTypesYAMLExport:
    """Tests pour GET /api/entity-types/export-yaml."""

    def test_export_yaml_success(self, client: TestClient):
        """✅ Export YAML retourne fichier téléchargeable."""
        # Créer quelques types
        client.post(
            "/api/entity-types",
            json={"type_name": "EXPORT_TEST", "description": "Test export"}
        )

        response = client.get("/api/entity-types/export-yaml")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/x-yaml; charset=utf-8"
        assert "attachment" in response.headers.get("content-disposition", "")

        # Vérifier contenu YAML valide
        content = response.text
        assert "EXPORT_TEST:" in content
        assert "description:" in content

    def test_export_yaml_filter_status(self, client: TestClient):
        """✅ Export filtre par status."""
        # Créer type approved
        client.post(
            "/api/entity-types",
            json={"type_name": "APPROVED_TYPE", "description": "Approved"}
        )
        client.post(
            "/api/entity-types/APPROVED_TYPE/approve",
            json={"admin_email": "admin@test.com"}
        )

        # Export approved only
        response = client.get("/api/entity-types/export-yaml?status=approved")

        assert response.status_code == 200
        content = response.text
        assert "APPROVED_TYPE:" in content

    def test_export_yaml_empty(self, client: TestClient):
        """✅ Export sans types retourne YAML vide."""
        # S'assurer qu'il n'y a pas de types avec un tenant spécifique
        response = client.get("/api/entity-types/export-yaml?tenant_id=empty-tenant")

        assert response.status_code == 200
        # YAML vide = "{}\n" ou ""
        content = response.text
        assert len(content) <= 10  # Très court

    def test_export_yaml_filename(self, client: TestClient):
        """✅ Export génère nom fichier correct."""
        response = client.get("/api/entity-types/export-yaml?status=approved")

        assert response.status_code == 200
        disposition = response.headers.get("content-disposition", "")
        assert "entity_types_approved_default.yaml" in disposition


class TestEntityTypesYAMLRoundtrip:
    """Tests round-trip: Export → Import."""

    def test_roundtrip_export_import(self, client: TestClient):
        """✅ Export puis Import doit restaurer types."""
        # Créer types initiaux
        types_to_create = ["ROUNDTRIP_A", "ROUNDTRIP_B", "ROUNDTRIP_C"]

        for type_name in types_to_create:
            client.post(
                "/api/entity-types",
                json={"type_name": type_name, "description": f"Type {type_name}"}
            )
            client.post(
                f"/api/entity-types/{type_name}/approve",
                json={"admin_email": "admin@test.com"}
            )

        # Export
        export_response = client.get("/api/entity-types/export-yaml?status=approved")
        assert export_response.status_code == 200
        yaml_content = export_response.content

        # Supprimer types (simuler reset)
        for type_name in types_to_create:
            client.delete(f"/api/entity-types/{type_name}")

        # Import
        file = io.BytesIO(yaml_content)
        import_response = client.post(
            "/api/entity-types/import-yaml?auto_approve=true",
            files={"file": ("export.yaml", file, "application/x-yaml")}
        )

        assert import_response.status_code == 200
        data = import_response.json()
        assert data["created"] >= 3  # Au moins nos 3 types


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
