"""Tests unitaires LifecycleDeclarationValidator — tokenizer + resolver."""
from __future__ import annotations

import pytest

from knowbase.lifecycle.declaration_validator import LifecycleDeclarationValidator


def test_extract_identifying_tokens_keeps_only_digits():
    """Le tokenizer ne garde que les tokens contenant ≥ 1 chiffre."""
    f = LifecycleDeclarationValidator._extract_identifying_tokens
    assert f("Council Regulation (EC) No 428/2009") == ["428/2009"]
    assert f("Regulation (EU) 2021/821") == ["2021/821"]
    assert f("CS-25 Amendment 27") == ["CS-25", "27"]
    assert f("Directive 95/46/EC") == ["95/46/EC"]
    assert f("Geneva Convention") == []  # pas de chiffre → pas identifiable


def test_atomize_tokens_breaks_on_separators():
    f = LifecycleDeclarationValidator._atomize_tokens
    # Tokens alpha-only retirés (CS, EC, ISO)
    assert f(["428/2009"]) == ["428", "2009"]
    assert f(["CS-25", "27"]) == ["25", "27"]
    assert f(["95/46/EC"]) == ["95", "46"]
    assert f(["9001:2015"]) == ["9001", "2015"]
    assert f(["MIL-STD-810H"]) == ["810h"]


def test_tokenize_searchable_strips_hash_suffix():
    f = LifecycleDeclarationValidator._tokenize_searchable
    # Le hash 8+ chars hex est retiré
    result = f("dualuse_reg_428_2009_original_372b7ac3", "")
    assert "372b7ac3" not in result  # hash strippé
    assert "428" in result
    assert "2009" in result
    assert "dualuse" in result


def test_atomize_dedupes():
    """Pas de doublons dans atomic tokens."""
    f = LifecycleDeclarationValidator._atomize_tokens
    assert f(["428/2009", "428"]) == ["428", "2009"]


def test_extract_strips_punctuation():
    f = LifecycleDeclarationValidator._extract_identifying_tokens
    assert f("Document 428/2009.") == ["428/2009"]
    assert f('"428/2009"') == ["428/2009"]
