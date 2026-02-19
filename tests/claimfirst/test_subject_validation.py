# tests/claimfirst/test_subject_validation.py
"""
Tests pour la validation des sujets (quality gate).

Partie 1 (locale) : gates structurelles + DocumentContext.remove_subject
Partie 2 (Docker) : validation LLM via orchestrateur
"""

import json
import pytest
from unittest.mock import MagicMock, patch

from knowbase.claimfirst.models.subject_anchor import SubjectAnchor, is_valid_subject_name
from knowbase.claimfirst.models.document_context import DocumentContext


# --- Fixtures ---

def _make_anchor(name: str, subject_id: str = None, doc_id: str = "doc_001") -> SubjectAnchor:
    """Crée un SubjectAnchor de test."""
    if subject_id is None:
        subject_id = f"subject_{name.lower().replace(' ', '_')[:12]}"
    return SubjectAnchor(
        subject_id=subject_id,
        tenant_id="default",
        canonical_name=name,
        aliases_explicit=[name],
        source_doc_ids=[doc_id],
    )


def _make_doc_context(subject_ids: list, primary_subject: str = "SAP S/4HANA") -> DocumentContext:
    """Crée un DocumentContext de test."""
    return DocumentContext(
        doc_id="doc_001",
        tenant_id="default",
        primary_subject=primary_subject,
        subject_ids=list(subject_ids),
    )


# === Partie 1 : Tests locaux (pas de dépendances lourdes) ===

class TestIsValidSubjectName:
    """Tests pour les gates structurelles de is_valid_subject_name."""

    def test_rejects_short_terms(self):
        """Rejet des termes trop courts (<2 mots ET <10 chars)."""
        assert not is_valid_subject_name("API")
        assert not is_valid_subject_name("DB")
        assert not is_valid_subject_name("SAP")

    def test_rejects_too_few_alpha(self):
        """Rejet si <5 caractères alphabétiques."""
        assert not is_valid_subject_name("1234 5678")
        assert not is_valid_subject_name("-- 12.3")

    def test_rejects_too_many_words(self):
        """Rejet des phrases >8 mots."""
        assert not is_valid_subject_name(
            "using this feature in lower releases of the product"
        )
        assert not is_valid_subject_name(
            "this is a very long sentence that describes something in detail"
        )

    def test_rejects_too_many_chars(self):
        """Rejet des noms >100 caractères."""
        long_name = "SAP S/4HANA Cloud " + "x" * 90
        assert not is_valid_subject_name(long_name)

    def test_rejects_sentence_punctuation(self):
        """Rejet si ponctuation de phrase (;!?)."""
        assert not is_valid_subject_name("What is SAP HANA?")
        assert not is_valid_subject_name("Feature A; Feature B")
        assert not is_valid_subject_name("New feature available!")

    def test_rejects_pipe_layout(self):
        """Rejet des marqueurs layout (|)."""
        assert not is_valid_subject_name("Column A | Column B")
        assert not is_valid_subject_name("Header | Value")

    def test_rejects_non_alphanum_start(self):
        """Rejet si commence par non-alphanum (bullet tronquée)."""
        assert not is_valid_subject_name("• Feature overview")
        assert not is_valid_subject_name("- Data processing")
        assert not is_valid_subject_name("* Important note")

    def test_rejects_high_comma_ratio(self):
        """Rejet si ratio virgules élevé (≥3 et ≥50% des mots)."""
        assert not is_valid_subject_name("data, processing, agreement, requirements")
        assert not is_valid_subject_name("one, two, three, four, five, six")

    def test_accepts_valid_subjects(self):
        """Acceptation des sujets légitimes."""
        assert is_valid_subject_name("SAP S/4HANA")
        assert is_valid_subject_name("Microsoft Azure")
        assert is_valid_subject_name("GDPR Compliance")
        assert is_valid_subject_name("Output Management for SAP S/4HANA")
        assert is_valid_subject_name("Business Partner")
        assert is_valid_subject_name("SAP S/4HANA Cloud")
        assert is_valid_subject_name("Kubernetes")  # 1 mot mais >=10 chars

    def test_accepts_single_long_word(self):
        """Acceptation d'un mot unique >=10 chars."""
        assert is_valid_subject_name("Kubernetes")
        assert is_valid_subject_name("Elasticsearch")

    def test_borderline_word_count(self):
        """8 mots exactement → accepté, 9 mots → rejeté."""
        assert is_valid_subject_name("one two three four five six seven eight")
        assert not is_valid_subject_name("one two three four five six seven eight nine")

    def test_comma_below_threshold(self):
        """Peu de virgules → accepté."""
        assert is_valid_subject_name("SAP S/4HANA, Cloud Edition")


class TestRemoveSubject:
    """Tests pour DocumentContext.remove_subject()."""

    def test_removes_existing_subject(self):
        ctx = _make_doc_context(["sub_a", "sub_b", "sub_c"])
        ctx.remove_subject("sub_b")
        assert ctx.subject_ids == ["sub_a", "sub_c"]

    def test_removes_nonexistent_is_noop(self):
        ctx = _make_doc_context(["sub_a", "sub_b"])
        ctx.remove_subject("sub_z")
        assert ctx.subject_ids == ["sub_a", "sub_b"]

    def test_removes_all_occurrences(self):
        ctx = _make_doc_context(["sub_a", "sub_b", "sub_a"])
        ctx.remove_subject("sub_a")
        assert ctx.subject_ids == ["sub_b"]


# === Partie 2 : Tests LLM (nécessitent l'import de l'orchestrateur) ===

try:
    from knowbase.claimfirst.orchestrator import ClaimFirstOrchestrator
    _ORCHESTRATOR_AVAILABLE = True
except ImportError:
    _ORCHESTRATOR_AVAILABLE = False


def _make_orchestrator_stub(subject_anchors=None):
    """Crée un stub d'orchestrateur."""
    orch = object.__new__(ClaimFirstOrchestrator)
    orch._subject_anchors = list(subject_anchors or [])
    return orch


@pytest.mark.skipif(not _ORCHESTRATOR_AVAILABLE, reason="Orchestrator deps not available locally")
class TestValidateNewSubjectsLLM:
    """Tests pour _validate_new_subjects_llm (orchestrateur)."""

    def test_noise_is_revoked(self):
        """Un sujet NOISE est retiré du cache, doc_context et all_anchors."""
        anchor_noise = _make_anchor("using this feature", "sub_noise")
        anchor_valid = _make_anchor("SAP S/4HANA", "sub_valid")

        orch = _make_orchestrator_stub([anchor_noise, anchor_valid])
        doc_ctx = _make_doc_context(["sub_noise", "sub_valid"])

        with patch.object(orch, "_llm_validate_subject_batch") as mock_batch:
            mock_batch.return_value = {
                1: {"verdict": "NOISE", "reason": "sentence fragment"},
                2: {"verdict": "VALID", "reason": "product name"},
            }
            result = orch._validate_new_subjects_llm(
                new_subjects=[anchor_noise, anchor_valid],
                all_anchors=[anchor_noise, anchor_valid],
                doc_context=doc_ctx,
                doc_title="Test Doc",
            )

        assert anchor_noise not in orch._subject_anchors
        assert "sub_noise" not in doc_ctx.subject_ids
        assert anchor_noise not in result
        assert anchor_valid in orch._subject_anchors
        assert "sub_valid" in doc_ctx.subject_ids
        assert anchor_valid in result

    def test_uncertain_is_kept(self):
        """Un sujet UNCERTAIN est conservé (pas de révocation)."""
        anchor = _make_anchor("Cloud Platform", "sub_uncertain")
        orch = _make_orchestrator_stub([anchor])
        doc_ctx = _make_doc_context(["sub_uncertain"])

        with patch.object(orch, "_llm_validate_subject_batch") as mock_batch:
            mock_batch.return_value = {
                1: {"verdict": "UNCERTAIN", "reason": "ambiguous"},
            }
            result = orch._validate_new_subjects_llm(
                new_subjects=[anchor],
                all_anchors=[anchor],
                doc_context=doc_ctx,
            )

        assert anchor in orch._subject_anchors
        assert "sub_uncertain" in doc_ctx.subject_ids
        assert anchor in result

    def test_empty_subjects_returns_unchanged(self):
        """Aucun sujet → retour inchangé."""
        orch = _make_orchestrator_stub()
        doc_ctx = _make_doc_context([])
        result = orch._validate_new_subjects_llm(
            new_subjects=[],
            all_anchors=[_make_anchor("SAP", "sub_x")],
            doc_context=doc_ctx,
        )
        assert len(result) == 1

    def test_fail_open_on_none_verdicts(self):
        """Si LLM retourne None (erreur) → tous les sujets conservés."""
        anchor = _make_anchor("Suspicious Name", "sub_sus")
        orch = _make_orchestrator_stub([anchor])
        doc_ctx = _make_doc_context(["sub_sus"])

        with patch.object(orch, "_llm_validate_subject_batch") as mock_batch:
            mock_batch.return_value = None
            result = orch._validate_new_subjects_llm(
                new_subjects=[anchor],
                all_anchors=[anchor],
                doc_context=doc_ctx,
            )

        assert anchor in result
        assert anchor in orch._subject_anchors
        assert "sub_sus" in doc_ctx.subject_ids

    def test_missing_index_means_keep(self):
        """Index manquant dans la réponse → sujet conservé (fail-open par index)."""
        anchor1 = _make_anchor("Subject A", "sub_1")
        anchor2 = _make_anchor("Subject B", "sub_2")
        orch = _make_orchestrator_stub([anchor1, anchor2])
        doc_ctx = _make_doc_context(["sub_1", "sub_2"])

        with patch.object(orch, "_llm_validate_subject_batch") as mock_batch:
            mock_batch.return_value = {
                1: {"verdict": "NOISE", "reason": "generic"},
            }
            result = orch._validate_new_subjects_llm(
                new_subjects=[anchor1, anchor2],
                all_anchors=[anchor1, anchor2],
                doc_context=doc_ctx,
            )

        assert anchor1 not in result
        assert anchor2 in result
        assert "sub_2" in doc_ctx.subject_ids


@pytest.mark.skipif(not _ORCHESTRATOR_AVAILABLE, reason="Orchestrator deps not available locally")
class TestLLMValidateSubjectBatch:
    """Tests pour _llm_validate_subject_batch (appel LLM + parsing)."""

    def test_parses_valid_response(self):
        """Parse correct d'une réponse LLM bien formée."""
        anchor1 = _make_anchor("SAP HANA", "sub_1")
        anchor2 = _make_anchor("random phrase", "sub_2")
        orch = _make_orchestrator_stub()

        llm_response = json.dumps({
            "results": [
                {"index": 1, "verdict": "VALID", "reason": "database product"},
                {"index": 2, "verdict": "NOISE", "reason": "not a subject"},
            ]
        })

        mock_router = MagicMock()
        mock_router.complete.return_value = llm_response

        with patch("knowbase.common.llm_router.get_llm_router", return_value=mock_router):
            verdicts = orch._llm_validate_subject_batch(
                [anchor1, anchor2], doc_title="Test Doc",
            )

        assert verdicts is not None
        assert verdicts[1]["verdict"] == "VALID"
        assert verdicts[2]["verdict"] == "NOISE"

    def test_fail_open_on_json_error(self):
        """JSON invalide → retourne None (fail-open)."""
        anchor = _make_anchor("Test Subject", "sub_1")
        orch = _make_orchestrator_stub()

        mock_router = MagicMock()
        mock_router.complete.return_value = "NOT VALID JSON {{"

        with patch("knowbase.common.llm_router.get_llm_router", return_value=mock_router):
            verdicts = orch._llm_validate_subject_batch(
                [anchor], doc_title="Test Doc",
            )

        assert verdicts is None

    def test_fail_open_on_exception(self):
        """Exception LLM → retourne None (fail-open)."""
        anchor = _make_anchor("Test Subject", "sub_1")
        orch = _make_orchestrator_stub()

        mock_router = MagicMock()
        mock_router.complete.side_effect = TimeoutError("LLM timeout")

        with patch("knowbase.common.llm_router.get_llm_router", return_value=mock_router):
            verdicts = orch._llm_validate_subject_batch(
                [anchor], doc_title="Test Doc",
            )

        assert verdicts is None

    def test_ignores_out_of_range_index(self):
        """Index hors range dans la réponse LLM → ignoré."""
        anchor = _make_anchor("SAP HANA", "sub_1")
        orch = _make_orchestrator_stub()

        llm_response = json.dumps({
            "results": [
                {"index": 1, "verdict": "VALID", "reason": "ok"},
                {"index": 99, "verdict": "NOISE", "reason": "phantom"},
            ]
        })

        mock_router = MagicMock()
        mock_router.complete.return_value = llm_response

        with patch("knowbase.common.llm_router.get_llm_router", return_value=mock_router):
            verdicts = orch._llm_validate_subject_batch(
                [anchor], doc_title="Test Doc",
            )

        assert verdicts is not None
        assert 1 in verdicts
        assert 99 not in verdicts
