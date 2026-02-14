# tests/claimfirst/test_versioning_hints.py
"""
Tests unitaires — Champ versioning_hints dans DomainContextProfile.

Vérifie la propagation du champ à travers le stack :
modèle Pydantic, sérialisation Neo4j, injector, API schemas.
"""

import pytest
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

# Stub des modules lourds non disponibles en local
import types

_heavy_deps = [
    "neo4j", "neo4j.GraphDatabase",
    "yaml", "debugpy",
    "knowbase.ontology.neo4j_schema",
    "knowbase.ontology.migrate_yaml_to_neo4j",
    "knowbase.ontology.entity_normalizer_neo4j",
    "knowbase.ontology.ontology_saver",
    "knowbase.db", "knowbase.db.base", "knowbase.db.models",
    "sqlalchemy", "sqlalchemy.orm",
]
for mod_name in _heavy_deps:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = MagicMock()

from knowbase.ontology.domain_context import DomainContextProfile
from knowbase.ontology.domain_context_injector import DomainContextInjector

# Charger les API schemas directement par chemin (évite la cascade knowbase.api.__init__)
import importlib.util
import pathlib

_schema_path = pathlib.Path(__file__).resolve().parents[2] / "src" / "knowbase" / "api" / "schemas" / "domain_context.py"
_spec = importlib.util.spec_from_file_location("knowbase.api.schemas.domain_context", _schema_path)
_schemas_mod = importlib.util.module_from_spec(_spec)
sys.modules["knowbase.api.schemas.domain_context"] = _schemas_mod
_spec.loader.exec_module(_schemas_mod)

DomainContextCreate = _schemas_mod.DomainContextCreate
DomainContextResponse = _schemas_mod.DomainContextResponse
DomainContextPreviewRequest = _schemas_mod.DomainContextPreviewRequest


# ── Helpers ───────────────────────────────────────────────


def _make_profile(**overrides) -> DomainContextProfile:
    """Crée un profil de test avec des valeurs par défaut sensibles."""
    defaults = dict(
        tenant_id="test_tenant",
        domain_summary="Enterprise software ecosystem for SAP products",
        industry="enterprise_software",
        sub_domains=["ERP", "HCM"],
        target_users=["consultants"],
        document_types=["technical"],
        common_acronyms={"SAC": "SAP Analytics Cloud"},
        key_concepts=["S/4HANA", "BTP"],
        context_priority="high",
        llm_injection_prompt="You are analyzing SAP enterprise documents. Interpret SAC as SAP Analytics Cloud.",
        versioning_hints="",
        created_at=datetime(2025, 1, 1),
        updated_at=datetime(2025, 1, 1),
    )
    defaults.update(overrides)
    return DomainContextProfile(**defaults)


# ── Tests Modèle Pydantic ─────────────────────────────────


class TestDomainContextProfileVersioningHints:
    """Tests champ versioning_hints dans DomainContextProfile."""

    def test_profile_with_hints(self):
        """Création profil avec versioning_hints non-vide."""
        profile = _make_profile(
            versioning_hints="FPS01 < FPS02 < FPS03 are ordered Feature Pack Stacks."
        )
        assert profile.versioning_hints == "FPS01 < FPS02 < FPS03 are ordered Feature Pack Stacks."

    def test_profile_without_hints(self):
        """Champ optionnel, défaut vide."""
        profile = _make_profile()
        assert profile.versioning_hints == ""

    def test_neo4j_roundtrip_with_hints(self):
        """Sérialisation/désérialisation Neo4j préserve versioning_hints."""
        hints = "2023/2024 refer to release IDs, not calendar years."
        profile = _make_profile(versioning_hints=hints)

        props = profile.to_neo4j_properties()
        assert props["versioning_hints"] == hints

        restored = DomainContextProfile.from_neo4j_properties(props)
        assert restored.versioning_hints == hints

    def test_neo4j_roundtrip_without_hints(self):
        """Désérialisation sans le champ retourne chaîne vide."""
        profile = _make_profile()
        props = profile.to_neo4j_properties()

        # Simuler un ancien noeud Neo4j sans le champ
        del props["versioning_hints"]
        restored = DomainContextProfile.from_neo4j_properties(props)
        assert restored.versioning_hints == ""

    def test_max_length_validation(self):
        """versioning_hints > 500 chars est rejeté."""
        with pytest.raises(Exception):
            _make_profile(versioning_hints="x" * 501)


# ── Tests Injector ────────────────────────────────────────


class TestInjectorVersioningHints:
    """Tests injection de la section versioning dans [DOMAIN CONTEXT]."""

    @patch("knowbase.ontology.domain_context_injector.get_domain_context_store")
    def test_injector_includes_versioning_hints(self, mock_get_store):
        """Le bloc [DOMAIN CONTEXT] contient la section Versioning quand hints non-vide."""
        hints = "FPS01 < FPS02 < FPS03 are ordered Feature Pack Stacks."
        profile = _make_profile(versioning_hints=hints)

        mock_store = MagicMock()
        mock_store.get_profile.return_value = profile
        mock_get_store.return_value = mock_store

        injector = DomainContextInjector()
        result = injector.inject_context("Base prompt.", "test_tenant")

        assert "Versioning conventions for this domain:" in result
        assert "FPS01 < FPS02 < FPS03" in result

    @patch("knowbase.ontology.domain_context_injector.get_domain_context_store")
    def test_injector_excludes_empty_hints(self, mock_get_store):
        """Pas de section Versioning si hints vide."""
        profile = _make_profile(versioning_hints="")

        mock_store = MagicMock()
        mock_store.get_profile.return_value = profile
        mock_get_store.return_value = mock_store

        injector = DomainContextInjector()
        result = injector.inject_context("Base prompt.", "test_tenant")

        assert "Versioning conventions" not in result

    @patch("knowbase.ontology.domain_context_injector.get_domain_context_store")
    def test_injector_excludes_whitespace_hints(self, mock_get_store):
        """Pas de section Versioning si hints contient seulement des espaces."""
        profile = _make_profile(versioning_hints="   ")

        mock_store = MagicMock()
        mock_store.get_profile.return_value = profile
        mock_get_store.return_value = mock_store

        injector = DomainContextInjector()
        result = injector.inject_context("Base prompt.", "test_tenant")

        assert "Versioning conventions" not in result


# ── Tests API Schemas ─────────────────────────────────────


class TestAPISchemaVersioningHints:
    """Tests propagation dans les schemas API."""

    def test_create_schema_accepts_hints(self):
        """DomainContextCreate accepte versioning_hints."""
        schema = DomainContextCreate(
            domain_summary="Enterprise software ecosystem for SAP products",
            industry="enterprise_software",
            versioning_hints="FPS01 < FPS02 are ordered.",
        )
        assert schema.versioning_hints == "FPS01 < FPS02 are ordered."

    def test_create_schema_default_empty(self):
        """versioning_hints est vide par défaut."""
        schema = DomainContextCreate(
            domain_summary="Enterprise software ecosystem for SAP products",
            industry="enterprise_software",
        )
        assert schema.versioning_hints == ""

    def test_response_schema_includes_hints(self):
        """DomainContextResponse inclut versioning_hints."""
        now = datetime.utcnow()
        resp = DomainContextResponse(
            tenant_id="default",
            domain_summary="test",
            industry="tech",
            llm_injection_prompt="prompt text for injection here.",
            created_at=now,
            updated_at=now,
            versioning_hints="some hints",
        )
        assert resp.versioning_hints == "some hints"

    def test_preview_schema_accepts_hints(self):
        """DomainContextPreviewRequest accepte versioning_hints."""
        schema = DomainContextPreviewRequest(
            domain_summary="Enterprise software ecosystem for SAP products",
            industry="enterprise_software",
            versioning_hints="hints here",
        )
        assert schema.versioning_hints == "hints here"
