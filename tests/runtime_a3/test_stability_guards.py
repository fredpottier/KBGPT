"""Tests gardes stabilité (chantier 05/06) — rescue TEXT_ONLY + Parse dégénéré."""

import json
import pytest

from knowbase.runtime_a3.schemas import (
    ClaimSummary, EvaluateOutput, ExecuteOutput, ParseOutput, SubGoal,
    SynthesizeInput, SynthesizeOutput, ToolResult,
)
from knowbase.runtime_a3.synthesize import Synthesizer


def _claim(cid, text="some claim text"):
    return ClaimSummary(claim_id=cid, subject_canonical="X", predicate="STATES",
                        value=text, text=text)


def _inp(n_claims=8):
    claims = [_claim(f"c{i}", f"fact number {i}") for i in range(n_claims)]
    po = ParseOutput(
        raw_question="What is fact 3?",
        language="en",
        parse_confidence=0.9,
        sub_goals=[SubGoal(kind="fact_lookup", subject_canonical="X")],
        schema_version="a3.0",
    )
    eo = ExecuteOutput(results=[ToolResult(
        sub_goal_idx=0, tool="kg_claims", claims=claims, sections=[],
    )])
    ev = EvaluateOutput(verdict="CORRECT", covered_sub_goals=[0],
                        uncovered_sub_goals=[], confidence=0.9, reasoning="ok",
                        re_plan_hint="none", schema_version="a3.0")
    return SynthesizeInput(parse_output=po, execute_output=eo,
                           evaluate_output=ev, response_mode="structured")


class _FlippyLLM:
    """1er appel : déclare TEXT_ONLY ; 2e appel : répond REASONED."""
    def __init__(self):
        self.calls = 0

    def complete(self, system, user):
        self.calls += 1
        mode = "TEXT_ONLY" if self.calls == 1 else "REASONED"
        answer = ("The evidence does not document this."
                  if self.calls == 1 else "Fact 3 is documented [claim_id=c3].")
        return json.dumps({
            "answer_text": answer,
            "cited_claims": [] if self.calls == 1 else [
                {"claim_id": "c3", "claim_verbatim": "fact number 3"}],
            "mode": mode, "synthesize_warnings": [], "schema_version": "a3.0",
        })


def test_textonly_rescue_recovers(monkeypatch):
    monkeypatch.setenv("V6_TEXTONLY_RESCUE", "1")
    monkeypatch.setenv("V6_CLAIM_FILTER_ENABLED", "0")  # hmm — voir note plus bas
    llm = _FlippyLLM()
    # claim_filter désactivé → filtered == tous les claims → widened pas plus grand
    # → pour exercer le rescue, on active le filtre avec un embedder factice.
    import knowbase.runtime_a3.synthesize as synthmod

    class _FakeFilter:
        def __init__(self):
            self.calls = []
        def filter(self, question, claims, groups=None, top_k=None):
            self.calls.append(top_k)
            k = top_k or 5
            return claims[:k], None

    s = Synthesizer(llm_client=llm, claim_filter=_FakeFilter(), claim_filter_enabled=True)
    out = s.synthesize(_inp(n_claims=8))
    assert out.mode == "REASONED"
    assert "textonly_rescue_applied" in out.synthesize_warnings
    assert llm.calls == 2


def test_textonly_rescue_respects_confirmed_textonly(monkeypatch):
    monkeypatch.setenv("V6_TEXTONLY_RESCUE", "1")

    class _AlwaysTextOnly:
        def __init__(self):
            self.calls = 0
        def complete(self, system, user):
            self.calls += 1
            return json.dumps({
                "answer_text": "The evidence does not document this.",
                "cited_claims": [], "mode": "TEXT_ONLY",
                "synthesize_warnings": [], "schema_version": "a3.0",
            })

    class _FakeFilter:
        def filter(self, question, claims, groups=None, top_k=None):
            return claims[:(top_k or 5)], None

    llm = _AlwaysTextOnly()
    s = Synthesizer(llm_client=llm, claim_filter=_FakeFilter(), claim_filter_enabled=True)
    out = s.synthesize(_inp(n_claims=8))
    assert out.mode == "TEXT_ONLY"  # le constat honnête est respecté
    assert "textonly_rescue_unchanged" in out.synthesize_warnings


def test_textonly_rescue_disabled(monkeypatch):
    monkeypatch.setenv("V6_TEXTONLY_RESCUE", "0")
    llm = _FlippyLLM()

    class _FakeFilter:
        def filter(self, question, claims, groups=None, top_k=None):
            return claims[:(top_k or 5)], None

    s = Synthesizer(llm_client=llm, claim_filter=_FakeFilter(), claim_filter_enabled=True)
    out = s.synthesize(_inp(n_claims=8))
    assert out.mode == "TEXT_ONLY"
    assert llm.calls == 1


def test_textonly_rescue_skipped_when_no_more_claims(monkeypatch):
    # widened == même taille (3 claims < top_k 5) → pas de retry
    monkeypatch.setenv("V6_TEXTONLY_RESCUE", "1")
    llm = _FlippyLLM()

    class _FakeFilter:
        def filter(self, question, claims, groups=None, top_k=None):
            return claims[:(top_k or 5)], None

    s = Synthesizer(llm_client=llm, claim_filter=_FakeFilter(), claim_filter_enabled=True)
    out = s.synthesize(_inp(n_claims=3))
    assert out.mode == "TEXT_ONLY"
    assert llm.calls == 1


# ── Parse dégénéré ─────────────────────────────────────────────────────────────

from knowbase.runtime_a3.parse import Parser
from knowbase.runtime_a3.schemas import ParseInput


class _DegenerateThenGoodLLM:
    """1er appel : sous-buts sans subject ni predicate ; 2e : sous-but complet."""
    def __init__(self):
        self.calls = 0

    def complete(self, messages, temperature=0.0, max_tokens=2000):
        self.calls += 1
        sg = ({"kind": "fact_lookup", "subject_canonical": None,
               "predicate_hint": None}
              if self.calls == 1 else
              {"kind": "fact_lookup", "subject_canonical": "HIC limit",
               "predicate_hint": "maximum allowable"})
        return json.dumps({
            "raw_question": "q", "language": "en", "parse_confidence": 0.9,
            "sub_goals": [sg], "schema_version": "a3.0",
        })


def test_parse_degenerate_retry(monkeypatch):
    monkeypatch.setenv("V6_PARSE_DEGENERATE_RETRY", "1")
    llm = _DegenerateThenGoodLLM()
    p = Parser(llm_client=llm)
    out = p.parse(ParseInput(question="What is the maximum allowable HIC?", tenant_id="default"))
    assert llm.calls == 2
    assert out.sub_goals[0].subject_canonical == "HIC limit"
    assert "degenerate_retry_recovered" in out.parse_warnings


def test_parse_degenerate_confirmed(monkeypatch):
    monkeypatch.setenv("V6_PARSE_DEGENERATE_RETRY", "1")

    class _AlwaysDegenerate:
        def __init__(self):
            self.calls = 0
        def complete(self, messages, temperature=0.0, max_tokens=2000):
            self.calls += 1
            return json.dumps({
                "raw_question": "q", "language": "en", "parse_confidence": 0.5,
                "sub_goals": [{"kind": "fact_lookup",
                               "subject_canonical": None, "predicate_hint": None}],
                "schema_version": "a3.0",
            })

    llm = _AlwaysDegenerate()
    p = Parser(llm_client=llm)
    out = p.parse(ParseInput(question="anything", tenant_id="default"))
    assert llm.calls == 2
    assert "degenerate_confirmed" in out.parse_warnings


# ── PremiseVerifier double-check (cause racine des flips LIST_0003) ────────────


def _wire_premise(s, statuses):
    """Injecte un PremiseVerifier factice qui rend les statuts successifs donnés."""
    class _Result:
        def __init__(self, status):
            self.status = status
            self.is_false_premise = status.startswith("FALSE")
            self.correction = None

    class _FakePV:
        def __init__(self):
            self.calls = 0
        def verify(self, question, pipeline_evidence=None):
            st = statuses[min(self.calls, len(statuses) - 1)]
            self.calls += 1
            return _Result(st)

    s._premise_verifier = _FakePV()
    return s._premise_verifier


def test_premise_unsupported_skipped_on_correct_verdict(monkeypatch):
    # Étayé bench @70460ba : FALSE_UNSUPPORTED sous verdict CORRECT = toujours
    # un tir à tort (jamais une détection réussie) → ignoré, synthèse normale.
    monkeypatch.setenv("V6_PREMISE_UNSUPPORTED_SKIP_ON_CORRECT", "1")
    monkeypatch.setenv("V6_PREMISE_VERIFIER_ENABLED", "1")

    class _GoodLLM:
        def complete(self, system, user):
            return json.dumps({
                "answer_text": "Fact 3 is documented [claim_id=c3].",
                "cited_claims": [{"claim_id": "c3", "claim_verbatim": "fact number 3"}],
                "mode": "REASONED", "synthesize_warnings": [], "schema_version": "a3.0",
            })

    class _FakeFilter:
        def filter(self, question, claims, groups=None, top_k=None):
            return claims[:(top_k or 5)], None

    s = Synthesizer(llm_client=_GoodLLM(), claim_filter=_FakeFilter(), claim_filter_enabled=True)
    pv = _wire_premise(s, ["FALSE_UNSUPPORTED"])
    out = s.synthesize(_inp(n_claims=8))
    assert pv.calls == 1
    assert out.mode == "REASONED"  # le court-circuit correctif a été ignoré


def test_premise_unsupported_applies_when_verdict_not_correct(monkeypatch):
    # Hors verdict CORRECT, FALSE_UNSUPPORTED garde son rôle de détection.
    monkeypatch.setenv("V6_PREMISE_UNSUPPORTED_SKIP_ON_CORRECT", "1")
    monkeypatch.setenv("V6_PREMISE_VERIFIER_ENABLED", "1")

    inp = _inp(n_claims=8)
    inp.evaluate_output.verdict = "AMBIGUOUS"
    s = Synthesizer(llm_client=None, claim_filter=None, claim_filter_enabled=False)
    pv = _wire_premise(s, ["FALSE_UNSUPPORTED"])
    out = s.synthesize(inp)
    assert pv.calls == 1
    assert out.mode == "TEXT_ONLY"
    assert "premise_false_unsupported" in out.synthesize_warnings


def test_premise_contradicted_stays_authoritative(monkeypatch):
    monkeypatch.setenv("V6_PREMISE_DOUBLECHECK", "1")
    monkeypatch.setenv("V6_PREMISE_VERIFIER_ENABLED", "1")

    s = Synthesizer(llm_client=None, claim_filter=None, claim_filter_enabled=False)
    pv = _wire_premise(s, ["FALSE_CONTRADICTED"])  # signal fort → pas de double-check
    out = s.synthesize(_inp(n_claims=8))
    assert pv.calls == 1
    assert out.mode == "TEXT_ONLY"
