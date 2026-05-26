"""
Tests P1.4b-4 — GroundingGate. Scorer NLI injecté (pas de modèle) + 1 smoke modèle réel.
"""

import pytest

from knowbase.claimfirst.quality.grounding_gate import GroundingGate


# ── ancrage identifiants (déterministe, NLI désactivé) ────────────────────────
def test_identifier_unanchored_flags_marginal():
    g = GroundingGate(enabled=False)  # NLI off -> seul l'ancrage identifiants
    r = g.check("Use transaction CG5Z to delete batch records.",
                "You can delete records from this screen.")
    assert r.marginal is True
    assert "cg5z" in r.missing_identifiers
    assert r.entailed is None  # NLI non appliqué


def test_identifier_anchored_ok():
    g = GroundingGate(enabled=False)
    r = g.check("Use transaction CG5Z to delete batch records.",
                "The CG5Z transaction lets you delete batch records.")
    assert r.marginal is False
    assert r.identifier_anchored is True


def test_claim_without_identifier_not_flagged_by_id():
    g = GroundingGate(enabled=False)
    r = g.check("The system improves efficiency.", "Some unrelated text.")
    # pas d'identifiant -> ancrage OK ; NLI off -> pas marginal
    assert r.marginal is False


# ── NLI (scorer injecté) ──────────────────────────────────────────────────────
def _scorer(values):
    return lambda pairs: list(values)


def test_nli_low_score_flags():
    g = GroundingGate(nli_scorer=_scorer([0.05]))
    r = g.check("The engine weighs 600 kg.", "The engine weighs 500 kg.")
    assert r.entailed is False
    assert r.marginal is True


def test_nli_high_score_ok():
    g = GroundingGate(nli_scorer=_scorer([0.98]))
    r = g.check("Water boils at 100 C at sea level.", "Water boils at 100 degrees Celsius at standard pressure.")
    assert r.entailed is True
    assert r.marginal is False


def test_identifier_wins_even_if_entailed():
    # NLI dirait entailé mais un identifiant est inventé -> marginal quand même
    g = GroundingGate(nli_scorer=_scorer([0.99]))
    r = g.check("Use transaction ZZZ9 for this.", "You can do this from the main screen.")
    assert r.entailed is True
    assert r.identifier_anchored is False
    assert r.marginal is True


def test_scorer_failure_is_graceful():
    def boom(pairs):
        raise RuntimeError("NLI down")
    g = GroundingGate(nli_scorer=boom)
    r = g.check("The system improves efficiency.", "Some text.")
    # scorer KO -> entailed None (sauté), ancrage OK -> pas marginal
    assert r.entailed is None
    assert r.marginal is False


def test_batch():
    g = GroundingGate(nli_scorer=_scorer([0.9, 0.1]))
    rs = g.check_batch([
        ("X supports A.", "X supports A and B."),     # entailé
        ("X supports C.", "X supports A and B."),     # non entailé
    ])
    assert rs[0].marginal is False and rs[1].marginal is True


def test_empty():
    assert GroundingGate().check_batch([]) == []


# ── smoke modèle réel (skippable) ─────────────────────────────────────────────
def _nli_available() -> bool:
    try:
        from sentence_transformers import CrossEncoder  # noqa: F401
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _nli_available(), reason="sentence-transformers indisponible")
def test_real_model_separates_faithful_from_hallucination():
    g = GroundingGate()  # vrai cross-encoder/nli-deberta-v3-base
    faithful = g.check(
        "At sea level, water boils at 100 degrees Celsius.",
        "Water boils at 100 degrees Celsius at standard atmospheric pressure.",
    )
    hallu = g.check(
        "SAP NetWeaver Application Server supports SSO with X.509 certificates.",
        "SAP NetWeaver Application Server supports single sign-on.",
    )
    assert faithful.entailed is True and faithful.marginal is False
    assert hallu.entailed is False and hallu.marginal is True
