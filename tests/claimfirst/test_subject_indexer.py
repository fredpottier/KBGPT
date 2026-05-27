"""Tests unitaires SubjectIndexer (A4.2).

Stratégie : LLM mocké via injection callable, validation logique de décision.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from knowbase.claimfirst.subject_indexer import (
    MIN_CONFIDENCE,
    SubjectIndexResult,
    SubjectIndexer,
    _normalize_subject,
    index_claims,
    is_enabled,
)


# ============================================================================
# TestNormalize
# ============================================================================


class TestNormalize:
    def test_strip_whitespace(self):
        assert _normalize_subject("  SAP S/4HANA  ") == "SAP S/4HANA"

    def test_strip_initial_article_the(self):
        assert _normalize_subject("the Budget Management") == "Budget Management"

    def test_strip_initial_article_a(self):
        assert _normalize_subject("a transaction") == "transaction"

    def test_strip_initial_article_french(self):
        assert _normalize_subject("le système SAP") == "système SAP"

    def test_case_insensitive_article(self):
        assert _normalize_subject("THE banking capability") == "banking capability"

    def test_cap_length_200(self):
        long_str = "X" * 300
        assert len(_normalize_subject(long_str)) == 200

    def test_keep_inner_articles(self):
        # Articles INTERNES préservés
        assert _normalize_subject("the in-house banking") == "in-house banking"
        # Article interne préservé
        out = _normalize_subject("Account for the customer")
        assert "the customer" in out


# ============================================================================
# TestIndexOne
# ============================================================================


def _llm_returning(d: dict):
    """Helper : retourne un LLM mock qui retourne le JSON `d` stringifié."""
    return lambda text: json.dumps(d)


class TestIndexOne:
    def test_success_high_confidence(self):
        llm = _llm_returning({
            "subject": "SAP S/4HANA",
            "confidence": 0.95,
            "marginal": False,
            "reasoning": "Clear entity",
        })
        idx = SubjectIndexer(llm_complete=llm)
        r = idx.index_one("c1", "SAP S/4HANA is the next-gen ERP")
        assert r.subject == "SAP S/4HANA"
        assert r.confidence == 0.95
        assert r.marginal is False
        assert r.failure_reason is None

    def test_marginal_no_subject(self):
        llm = _llm_returning({
            "subject": None,
            "confidence": 0.9,
            "marginal": True,
            "reasoning": "Generic phrase",
        })
        idx = SubjectIndexer(llm_complete=llm)
        r = idx.index_one("c1", "You can do things efficiently")
        assert r.subject is None
        assert r.marginal is True

    def test_empty_text_returns_marginal(self):
        idx = SubjectIndexer(llm_complete=lambda t: "")
        r = idx.index_one("c1", "")
        assert r.subject is None
        assert r.marginal is True
        assert r.failure_reason == "EmptyText"

    def test_whitespace_text_returns_marginal(self):
        idx = SubjectIndexer(llm_complete=lambda t: "")
        r = idx.index_one("c1", "   \n  ")
        assert r.marginal is True
        assert r.failure_reason == "EmptyText"

    def test_low_confidence_retries_then_marginal(self):
        # Always low confidence → toutes tentatives échouent → marginal
        llm = _llm_returning({
            "subject": "Maybe",
            "confidence": 0.4,
            "marginal": False,
            "reasoning": "Unclear",
        })
        idx = SubjectIndexer(llm_complete=llm, min_confidence=0.7, max_retries=2)
        r = idx.index_one("c1", "Something")
        assert r.marginal is True
        assert "LowConfidence" in (r.failure_reason or "")

    def test_llm_error_then_marginal(self):
        def _failing(text):
            raise RuntimeError("LLM down")
        idx = SubjectIndexer(llm_complete=_failing, max_retries=2)
        r = idx.index_one("c1", "Something")
        assert r.marginal is True
        assert r.failure_reason is not None
        assert "LLMError" in r.failure_reason

    def test_normalization_applied(self):
        llm = _llm_returning({
            "subject": "  the SAP S/4HANA Cloud  ",
            "confidence": 0.9,
            "marginal": False,
            "reasoning": "OK",
        })
        idx = SubjectIndexer(llm_complete=llm)
        r = idx.index_one("c1", "blah")
        assert r.subject == "SAP S/4HANA Cloud"

    def test_subject_becomes_empty_after_normalization(self):
        # LLM retourne juste un article → normalisé devient ""
        llm = _llm_returning({
            "subject": "the",
            "confidence": 0.9,
            "marginal": False,
            "reasoning": "OK",
        })
        idx = SubjectIndexer(llm_complete=llm)
        r = idx.index_one("c1", "blah")
        # Après normalisation, "the" → "" → None
        # Le code retry et fall-back en marginal
        assert r.subject is None

    def test_markdown_fence_stripped(self):
        # LLM retourne avec markdown fences
        def _llm(text):
            return '```json\n{"subject":"X","confidence":0.9,"marginal":false,"reasoning":""}\n```'
        idx = SubjectIndexer(llm_complete=_llm)
        r = idx.index_one("c1", "blah")
        assert r.subject == "X"


# ============================================================================
# TestIndexClaims (batch + priorité SF)
# ============================================================================


class _MockClaim:
    """Mock Claim object pour tests."""
    def __init__(self, claim_id, text, structured_form=None):
        self.claim_id = claim_id
        self.text = text
        self.structured_form = structured_form
        self.subject_canonical = None
        self.marginal = None
        self.subject_extraction_confidence = None


class TestIndexClaims:
    def test_skip_claims_with_sf_subject(self):
        # SF.subject = "X" → skip LLM extraction, force subject_canonical = "X"
        llm_called = {"count": 0}
        def _llm(text):
            llm_called["count"] += 1
            return json.dumps({"subject": "Y", "confidence": 0.9, "marginal": False, "reasoning": ""})

        c1 = _MockClaim("c1", "blah", structured_form={"subject": "X", "predicate": "USES", "object": "Y"})
        c2 = _MockClaim("c2", "another claim")

        idx = SubjectIndexer(llm_complete=_llm)
        results = idx.index_claims([c1, c2])

        # c1 skip (SF.subject existe) → subject_canonical = "X"
        assert c1.subject_canonical == "X"
        # c2 traité → LLM appelé une fois
        assert llm_called["count"] == 1
        assert c2.subject_canonical == "Y"
        # results contient SEULEMENT c2 (les claims skip ne sont pas dans results)
        assert len(results) == 1
        assert results[0].claim_id == "c2"

    def test_apply_subject_and_marginal_to_claims(self):
        # Claim 1 : extracted clean, Claim 2 : marginal.
        # Mock déterministe (map par texte) car l'indexation est PARALLÈLE → l'ordre
        # des appels n'est pas garanti.
        def _llm(text):
            if "Entity does X" in text:
                return json.dumps({"subject": "Entity", "confidence": 0.95, "marginal": False, "reasoning": ""})
            return json.dumps({"subject": None, "confidence": 0.9, "marginal": True, "reasoning": "Generic"})

        c1 = _MockClaim("c1", "Entity does X")
        c2 = _MockClaim("c2", "You can do things")

        idx = SubjectIndexer(llm_complete=_llm)
        results = idx.index_claims([c1, c2])

        assert c1.subject_canonical == "Entity"
        assert c1.marginal is False
        assert c1.subject_extraction_confidence == 0.95

        assert c2.subject_canonical is None
        assert c2.marginal is True

        assert len(results) == 2


# ============================================================================
# TestToggle
# ============================================================================


class TestToggle:
    def test_is_enabled_default_true(self, monkeypatch):
        monkeypatch.delenv("V6_SUBJECT_INDEXER_ENABLED", raising=False)
        assert is_enabled() is True

    def test_is_enabled_explicit_off(self, monkeypatch):
        monkeypatch.setenv("V6_SUBJECT_INDEXER_ENABLED", "0")
        assert is_enabled() is False

    def test_is_enabled_explicit_on(self, monkeypatch):
        monkeypatch.setenv("V6_SUBJECT_INDEXER_ENABLED", "1")
        assert is_enabled() is True

    def test_index_claims_skipped_if_disabled(self, monkeypatch):
        monkeypatch.setenv("V6_SUBJECT_INDEXER_ENABLED", "0")
        c1 = _MockClaim("c1", "blah")
        results = index_claims([c1])
        # Pas d'exécution → liste vide
        assert results == []


# ============================================================================
# TestConstants
# ============================================================================


class TestConstants:
    def test_min_confidence_sensible(self):
        assert 0.5 <= MIN_CONFIDENCE <= 0.9


# ============================================================================
# TestClaimNeo4jPersistence — Garantit que to_neo4j_properties() écrit bien
# subject_canonical et marginal sur Claim post-A4.2, peu importe la source
# (SF.subject ou SubjectIndexer)
# ============================================================================


class TestClaimNeo4jPersistence:
    """Guard rails sur Claim.to_neo4j_properties() pour A4.2.

    Garantit que tout nouveau Claim ingéré écrit bien subject_canonical et
    marginal en Neo4j — quel que soit le chemin (SF rempli ou SubjectIndexer).
    """

    def _make_minimal_claim(self, **overrides):
        """Crée un Claim minimal pour test, avec overrides."""
        from knowbase.claimfirst.models.claim import Claim, ClaimType, ClaimScope
        defaults = {
            "claim_id": "c_test_001",
            "tenant_id": "test",
            "doc_id": "doc_001",
            "text": "Test claim text.",
            "claim_type": ClaimType.FACTUAL,
            "verbatim_quote": "Test claim text.",
            "passage_id": "p_001",
            "unit_ids": ["u_001"],
            "confidence": 0.9,
            "scope": ClaimScope(),
        }
        defaults.update(overrides)
        return Claim(**defaults)

    def test_subject_canonical_from_structured_form_priority(self):
        """SF.subject prend priorité absolue sur claim.subject_canonical."""
        c = self._make_minimal_claim(
            structured_form={"subject": "X_from_SF", "predicate": "USES", "object": "Y"},
            subject_canonical="X_from_indexer",  # devrait être ignoré
        )
        props = c.to_neo4j_properties()
        assert props["subject_canonical"] == "X_from_SF"

    def test_subject_canonical_from_indexer_when_no_sf(self):
        """Sans SF, subject_canonical du SubjectIndexer est persisté."""
        c = self._make_minimal_claim(
            structured_form=None,
            subject_canonical="X_indexed",
            subject_extraction_confidence=0.85,
        )
        props = c.to_neo4j_properties()
        assert props["subject_canonical"] == "X_indexed"
        assert props["subject_extraction_confidence"] == 0.85

    def test_marginal_flag_persisted(self):
        """Si claim est marginal, le flag passe en Neo4j."""
        c = self._make_minimal_claim(
            structured_form=None,
            subject_canonical=None,
            marginal=True,
            subject_extraction_confidence=0.9,
        )
        props = c.to_neo4j_properties()
        assert props.get("marginal") is True
        assert "subject_canonical" not in props  # None → pas écrit
        assert props["subject_extraction_confidence"] == 0.9

    def test_marginal_false_not_written_implicitly(self):
        """marginal=None ne doit pas être écrit (différencie 'pas traité' vs 'évalué non-marginal')."""
        c = self._make_minimal_claim(structured_form=None, subject_canonical="X")
        props = c.to_neo4j_properties()
        # marginal pas dans props si None (claim pas encore traité par SubjectIndexer)
        assert "marginal" not in props or props["marginal"] is None

    def test_no_subject_no_marginal_writes_nothing(self):
        """Claim brut sans aucun traitement A4.2 → props sans subject_canonical ni marginal."""
        c = self._make_minimal_claim(structured_form=None)
        props = c.to_neo4j_properties()
        assert "subject_canonical" not in props
        # marginal soit absent soit None
        assert props.get("marginal") in (None,)
