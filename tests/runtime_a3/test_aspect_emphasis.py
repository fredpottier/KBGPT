"""Test _aspect_emphasized_query — emphase l'aspect pour les questions multi-aspect.

Cf project_multihop_audit : les sous-buts multi-aspect partagent le subject ; sans
emphase, ils requêtent tous la question subject-dominée → mêmes claims génériques.
"""
from __future__ import annotations

import types

from knowbase.runtime_a3.execute import Executor


def _sg(subject, predicate=None, obj=None, kind="list_enumeration"):
    return types.SimpleNamespace(
        subject_canonical=subject, predicate_hint=predicate, object_hint=obj, kind=kind,
    )


def _tc(idx):
    return types.SimpleNamespace(tool="kg_claims_list", sub_goal_idx=idx)


def _exec_with(sub_goals) -> Executor:
    ex = Executor(neo4j_client=object(), qdrant_search=lambda **k: [], embedder=lambda t: [0.0])
    ex._current_parse_output = types.SimpleNamespace(sub_goals=sub_goals)
    return ex


def test_multi_aspect_emphasizes_aspect(monkeypatch):
    monkeypatch.setenv("V6_ASPECT_EMPHASIS", "1")
    sgs = [
        _sg("SAP Cloud Private Edition", "connectivité réseau"),
        _sg("SAP Cloud Private Edition", "options VPN"),
        _sg("SAP Cloud Private Edition", "options Express Route"),
    ]
    ex = _exec_with(sgs)
    # sous-but [1] = VPN → aspect répété en tête, sujet en contexte
    q = ex._aspect_emphasized_query(_tc(1))
    assert q == "options vpn options vpn SAP Cloud Private Edition"
    # sous-but [2] = Express Route
    assert ex._aspect_emphasized_query(_tc(2)) == "options express route options express route SAP Cloud Private Edition"


def test_single_aspect_returns_none(monkeypatch):
    monkeypatch.setenv("V6_ASPECT_EMPHASIS", "1")
    ex = _exec_with([_sg("MRP", "transactions")])  # 1 seul sous-but
    assert ex._aspect_emphasized_query(_tc(0)) is None


def test_different_subjects_not_multi_aspect(monkeypatch):
    monkeypatch.setenv("V6_ASPECT_EMPHASIS", "1")
    # 2 sous-buts mais subjects différents → pas multi-aspect
    ex = _exec_with([_sg("A", "x"), _sg("B", "y")])
    assert ex._aspect_emphasized_query(_tc(0)) is None


def test_toggle_off_returns_none(monkeypatch):
    monkeypatch.setenv("V6_ASPECT_EMPHASIS", "0")
    sgs = [_sg("X", "a"), _sg("X", "b")]
    assert _exec_with(sgs)._aspect_emphasized_query(_tc(0)) is None


def test_no_aspect_returns_none(monkeypatch):
    monkeypatch.setenv("V6_ASPECT_EMPHASIS", "1")
    # 2 sous-buts même subject mais sans predicate/object → pas d'aspect
    ex = _exec_with([_sg("X", None), _sg("X", None)])
    assert ex._aspect_emphasized_query(_tc(0)) is None
