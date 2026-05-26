"""
Tests P1.4b-2 — SelectionGate (Stage A check-worthiness) + identifier_guard.

LLM mocké → pas de dépendance réseau/burst. Teste la LOGIQUE :
KEEP/DROP, garde-fou identifiants (override DROP→KEEP), défaillances sûres (→KEEP).
"""

import json

import pytest

from knowbase.claimfirst.extractors.selection_gate import SelectionGate
from knowbase.claimfirst.quality.identifier_guard import (
    has_specific_identifier,
    protected_identifiers,
    specific_identifiers,
)


# ── identifier_guard ──────────────────────────────────────────────────────────
def test_specific_identifiers_keeps_codes_and_paths():
    assert "cg5z" in specific_identifiers("Use transaction CG5Z to delete batches.")
    assert any("ana_pai_ps_srv" == t for t in specific_identifiers("Call ANA_PAI_PS_SRV service."))
    assert "2021/821" in specific_identifiers("Regulation 2021/821 applies.")


def test_specific_identifiers_excludes_short_acronyms_and_product_name():
    # 'sap'/'hr' (alpha <=3) ne sont PAS des identifiants spécifiques
    assert specific_identifiers("SAP shall not be liable for damages.") == []
    assert specific_identifiers("HR staff productivity improves.") == []


def test_protected_is_broader_than_specific():
    # la version large garde les acronymes courts (pour la dédup), pas la stricte
    assert "sap" in protected_identifiers("SAP shall not be liable.")
    assert "sap" not in specific_identifiers("SAP shall not be liable.")


def test_has_specific_identifier():
    assert has_specific_identifier("Run /SCWM/VALUATION_SET weekly.") is True
    assert has_specific_identifier("The system improves efficiency.") is False


# ── SelectionGate ─────────────────────────────────────────────────────────────
def _llm_returning(label_map):
    """Construit un faux llm_call renvoyant les labels donnés (id->label)."""
    def _llm(system, user):
        return json.dumps({
            "verdicts": [{"id": uid, "label": lab, "category": "x"}
                         for uid, lab in label_map.items()]
        })
    return _llm


def test_basic_keep_drop():
    units = [("u1", "Water boils at 100 degrees Celsius."),
             ("u2", "The platform delivers powerful capabilities for success.")]
    gate = SelectionGate(_llm_returning({"u1": "KEEP", "u2": "DROP"}))
    res = gate.classify(units)
    assert res.kept_ids == ["u1"]
    assert res.n_dropped == 1
    assert res.dropped[0].unit_id == "u2"
    assert res.guard_overrides == 0


def test_guard_overrides_drop_with_specific_identifier():
    # le juge veut DROP mais l'unité porte un identifiant précis → KEEP forcé
    units = [("u1", "Use transaction CG5Z to delete batch records.")]
    gate = SelectionGate(_llm_returning({"u1": "DROP"}))
    res = gate.classify(units)
    assert res.kept_ids == ["u1"]
    assert res.guard_overrides == 1
    assert res.verdicts[0].judge_label == "DROP"
    assert res.verdicts[0].label == "KEEP"
    assert res.verdicts[0].guard_override is True


def test_no_override_without_identifier():
    units = [("u1", "The solution provides many benefits.")]
    gate = SelectionGate(_llm_returning({"u1": "DROP"}))
    res = gate.classify(units)
    assert res.kept_ids == []
    assert res.n_dropped == 1
    assert res.guard_overrides == 0


def test_missing_verdict_defaults_keep():
    units = [("u1", "Fact A is true."), ("u2", "Fact B is true.")]
    gate = SelectionGate(_llm_returning({"u1": "DROP"}))  # u2 non jugé
    res = gate.classify(units)
    # u1 DROP (pas d'identifiant), u2 KEEP par défaut (non jugé = sûr)
    assert "u2" in res.kept_ids
    assert res.verdicts[1].category == "not_judged"


def test_judge_failure_keeps_all():
    units = [("u1", "x"), ("u2", "y")]
    gate = SelectionGate(lambda s, u: "not json at all <<<")
    res = gate.classify(units)
    assert res.judge_failed is True
    assert set(res.kept_ids) == {"u1", "u2"}


def test_llm_exception_keeps_all():
    def boom(s, u):
        raise RuntimeError("LLM down")
    res = SelectionGate(boom).classify([("u1", "x")])
    assert res.judge_failed is True
    assert res.kept_ids == ["u1"]


def test_disabled_is_noop_without_calling_llm():
    def must_not_call(s, u):
        raise AssertionError("LLM should not be called when disabled")
    gate = SelectionGate(must_not_call, enabled=False)
    res = gate.classify([("u1", "x"), ("u2", "y")])
    assert set(res.kept_ids) == {"u1", "u2"}


def test_empty_units():
    res = SelectionGate(_llm_returning({})).classify([])
    assert res.n_kept == 0 and res.n_dropped == 0
