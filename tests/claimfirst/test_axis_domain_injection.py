# tests/claimfirst/test_axis_domain_injection.py
"""
Tests unitaires — Injection Domain Context dans AxisDetector et AxisValueValidator.

Vérifie que le contexte métier est injecté dans les prompts LLM
quand un tenant_id est configuré avec un profil.
"""

import sys
import types
import enum
import pytest
from unittest.mock import patch, MagicMock

# ── Stub des modules lourds ──────────────────────────────
# Les imports paresseux dans _call_llm() font:
#   from knowbase.common.llm_router import get_llm_router, TaskType
#   from knowbase.ontology.domain_context_injector import get_domain_context_injector
#
# On enregistre des mock modules dans sys.modules pour que:
# 1) Les imports paresseux trouvent ces modules
# 2) @patch puisse les cibler

_heavy_deps = [
    "neo4j", "neo4j.GraphDatabase",
    "yaml",
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

# Charger domain_context_injector réel (fonctionne avec les stubs ontology)
from knowbase.ontology import domain_context_injector as _dci_mod  # noqa: E402

# Pour llm_router: créer un module stub avec les attributs requis
# (le vrai module a trop de deps: qdrant, openai, anthropic, etc.)
class _TaskType(enum.Enum):
    FAST_CLASSIFICATION = "fast_classification"
    METADATA_EXTRACTION = "metadata_extraction"
    TRANSLATION = "translation"

_llm_router_mod = types.ModuleType("knowbase.common.llm_router")
_llm_router_mod.get_llm_router = MagicMock()
_llm_router_mod.TaskType = _TaskType
_llm_router_mod.LLMRouter = MagicMock
sys.modules["knowbase.common.llm_router"] = _llm_router_mod

from knowbase.claimfirst.axes.axis_detector import ApplicabilityAxisDetector  # noqa: E402
from knowbase.claimfirst.axes.axis_value_validator import AxisValueValidator  # noqa: E402


# ── Fixtures ──────────────────────────────────────────────


@pytest.fixture
def mock_injector_with_profile():
    """Injector qui enrichit le prompt avec [DOMAIN CONTEXT]."""
    injector = MagicMock()

    def inject_side_effect(base_prompt, tenant_id):
        return base_prompt + "\n\n[DOMAIN CONTEXT - Priority: HIGH]\nSAP ecosystem docs.\n[END DOMAIN CONTEXT]"

    injector.inject_context.side_effect = inject_side_effect
    return injector


@pytest.fixture
def mock_injector_no_profile():
    """Injector qui retourne le prompt inchangé (pas de profil)."""
    injector = MagicMock()
    injector.inject_context.side_effect = lambda base, tid: base
    return injector


# ── Tests AxisDetector ────────────────────────────────────


class TestAxisDetectorDomainInjection:
    """Tests injection domain context dans AxisDetector._call_llm."""

    @patch("knowbase.common.llm_router.get_llm_router")
    @patch("knowbase.ontology.domain_context_injector.get_domain_context_injector")
    def test_axis_detector_injects_domain_context(
        self, mock_get_injector, mock_get_router, mock_injector_with_profile
    ):
        """Vérifie que le prompt système contient [DOMAIN CONTEXT] quand profil existe."""
        mock_get_injector.return_value = mock_injector_with_profile

        mock_router = MagicMock()
        mock_router.complete.return_value = '{"subject": "test", "domain": "test", "axes": []}'
        mock_get_router.return_value = mock_router

        detector = ApplicabilityAxisDetector(
            llm_client=MagicMock(),
            tenant_id="default",
        )

        detector._call_llm("Detect axes for this document")

        # Vérifier que complete a été appelé avec un message système enrichi
        call_args = mock_router.complete.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
        system_msg = messages[0]
        assert system_msg["role"] == "system"
        assert "[DOMAIN CONTEXT" in system_msg["content"]
        assert "SAP ecosystem" in system_msg["content"]

    @patch("knowbase.common.llm_router.get_llm_router")
    @patch("knowbase.ontology.domain_context_injector.get_domain_context_injector")
    def test_no_injection_without_tenant(self, mock_get_injector, mock_get_router):
        """Vérifie que sans tenant_id, l'injector n'est PAS appelé."""
        mock_router = MagicMock()
        mock_router.complete.return_value = '{"axes": []}'
        mock_get_router.return_value = mock_router

        detector = ApplicabilityAxisDetector(
            llm_client=MagicMock(),
            tenant_id=None,
        )

        detector._call_llm("Detect axes for this document")

        mock_get_injector.assert_not_called()

        call_args = mock_router.complete.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
        system_msg = messages[0]
        assert "[DOMAIN CONTEXT" not in system_msg["content"]

    @patch("knowbase.common.llm_router.get_llm_router")
    @patch("knowbase.ontology.domain_context_injector.get_domain_context_injector")
    def test_no_injection_without_profile(
        self, mock_get_injector, mock_get_router, mock_injector_no_profile
    ):
        """Vérifie que si le tenant n'a pas de profil, le prompt reste inchangé."""
        mock_get_injector.return_value = mock_injector_no_profile

        mock_router = MagicMock()
        mock_router.complete.return_value = '{"axes": []}'
        mock_get_router.return_value = mock_router

        detector = ApplicabilityAxisDetector(
            llm_client=MagicMock(),
            tenant_id="unknown_tenant",
        )

        detector._call_llm("Detect axes")

        call_args = mock_router.complete.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
        system_msg = messages[0]
        assert "[DOMAIN CONTEXT" not in system_msg["content"]
        assert system_msg["content"] == "You are an expert in document versioning axis detection."


# ── Tests AxisValueValidator ──────────────────────────────


class TestAxisValidatorDomainInjection:
    """Tests injection domain context dans AxisValueValidator._call_llm."""

    @patch("knowbase.common.llm_router.get_llm_router")
    @patch("knowbase.ontology.domain_context_injector.get_domain_context_injector")
    def test_axis_validator_injects_domain_context(
        self, mock_get_injector, mock_get_router, mock_injector_with_profile
    ):
        """Vérifie que le validator injecte le domain context."""
        mock_get_injector.return_value = mock_injector_with_profile

        mock_router = MagicMock()
        mock_router.complete.return_value = '{"selected_value": "6.0", "confidence": 0.9}'
        mock_get_router.return_value = mock_router

        validator = AxisValueValidator(
            llm_client=MagicMock(),
            tenant_id="default",
        )

        validator._call_llm("Validate this axis value")

        call_args = mock_router.complete.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
        system_msg = messages[0]
        assert system_msg["role"] == "system"
        assert "[DOMAIN CONTEXT" in system_msg["content"]

    @patch("knowbase.common.llm_router.get_llm_router")
    @patch("knowbase.ontology.domain_context_injector.get_domain_context_injector")
    def test_validator_no_injection_without_tenant(
        self, mock_get_injector, mock_get_router
    ):
        """Vérifie que sans tenant_id, pas d'injection."""
        mock_router = MagicMock()
        mock_router.complete.return_value = '{"selected_value": "6.0"}'
        mock_get_router.return_value = mock_router

        validator = AxisValueValidator(
            llm_client=MagicMock(),
            tenant_id=None,
        )

        validator._call_llm("Validate this")

        mock_get_injector.assert_not_called()

        call_args = mock_router.complete.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
        system_msg = messages[0]
        assert "[DOMAIN CONTEXT" not in system_msg["content"]
