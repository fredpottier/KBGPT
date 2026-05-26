"""
Tests P1.4b-1 — détecteur d'énumération + intégration au segmenteur.

Vérifie :
1. EnumerationDetector classe correctement énumérations vs pièges (0 faux positif).
2. AssertionUnitIndexer(keep_enumeration_as_unit=False) = comportement historique
   inchangé (une énumération longue est fragmentée).
3. AssertionUnitIndexer(keep_enumeration_as_unit=True) = l'énumération reste 1 unité.

Nécessite spaCy (en_core_web_md / fr_core_news_md) + fasttext lid — présents dans le
container app. Skip propre si absents.
"""

import pytest

from knowbase.stratified.pass1.assertion_unit_indexer import AssertionUnitIndexer
from knowbase.stratified.pass1.enumeration_detector import EnumerationDetector


@pytest.fixture(scope="module")
def detector():
    det = EnumerationDetector(enabled=True)
    # skip si la stack NLP n'est pas dispo dans l'environnement de test
    if det._get_nlp("en") is None:
        pytest.skip("spaCy en_core_web_md indisponible")
    return det


# ── 1. Détecteur : énumérations (True) ────────────────────────────────────────
@pytest.mark.parametrize("text,lang", [
    ("The system supports SSO, LDAP, and OAuth.", "en"),
    ("Supply elements include stock, purchase orders, and production orders.", "en"),
    ("Le module gère les taxes, les douanes et les accises.", "fr"),
])
def test_detector_true_on_object_enumerations(detector, text, lang):
    assert detector.is_object_enumeration(text, lang) is True


# ── 1bis. Détecteur : pièges (False — 0 faux positif) ─────────────────────────
@pytest.mark.parametrize("text,lang", [
    ("The pilot and the copilot must verify the landing gear.", "en"),   # sujets coordonnés
    ("Procedure A or B may be used.", "en"),                              # alternative
    ("The system checks the input, validates the schema, and processes the record.", "en"),  # verbes
    ("The engine weighs 500 kilograms.", "en"),                          # pas de coordination
    ("Le pilote et le copilote doivent vérifier le train.", "fr"),       # sujets FR
    ("La procédure A ou B peut être utilisée.", "fr"),                   # alternative FR
])
def test_detector_false_on_traps(detector, text, lang):
    assert detector.is_object_enumeration(text, lang) is False


def test_detector_fast_path_no_coordination(detector):
    # pas de virgule ni 'and'/'et' → False immédiat
    assert detector.is_object_enumeration("Water boils at 100 degrees Celsius.", "en") is False


def test_detector_graceful_fallback_unknown_language(detector):
    # langue non supportée → False sûr (pas d'exception)
    assert detector.is_object_enumeration("foo, bar and baz", lang="zz") is False


# ── 2 & 3. Intégration segmenteur ─────────────────────────────────────────────
ENUM_SENTENCE = (
    "The platform supports single sign-on, multi-factor authentication, "
    "role-based access control, and detailed audit logging."
)


def _nlp_available() -> bool:
    return EnumerationDetector(enabled=True)._get_nlp("en") is not None


@pytest.mark.skipif(not _nlp_available(), reason="spaCy indisponible")
def test_indexer_default_fragments_long_enumeration():
    # comportement HISTORIQUE (flag OFF) : au-delà de max_unit_length, comma-split
    idx = AssertionUnitIndexer(min_unit_length=5, max_unit_length=80,
                               keep_enumeration_as_unit=False)
    res = idx.index_docitem("doc:1", ENUM_SENTENCE, item_type="paragraph")
    assert len(res.units) > 1  # fragmenté


@pytest.mark.skipif(not _nlp_available(), reason="spaCy indisponible")
def test_indexer_keeps_enumeration_as_single_unit():
    # P1.4b-1 (flag ON) : l'énumération reste 1 unité, jamais fragmentée
    idx = AssertionUnitIndexer(min_unit_length=5, max_unit_length=80,
                               keep_enumeration_as_unit=True)
    res = idx.index_docitem("doc:1", ENUM_SENTENCE, item_type="paragraph")
    assert len(res.units) == 1
    assert res.units[0].unit_type == "enumeration"
    assert res.units[0].text == ENUM_SENTENCE


@pytest.mark.skipif(not _nlp_available(), reason="spaCy indisponible")
def test_indexer_flag_on_does_not_merge_coordinated_subjects():
    # un piège (sujets coordonnés) ne doit PAS être typé enumeration
    idx = AssertionUnitIndexer(min_unit_length=5, max_unit_length=500,
                               keep_enumeration_as_unit=True)
    res = idx.index_docitem(
        "doc:2", "The pilot and the copilot must verify the gear.", item_type="paragraph"
    )
    assert all(u.unit_type != "enumeration" for u in res.units)


@pytest.mark.skipif(not _nlp_available(), reason="spaCy indisponible")
def test_indexer_list_item_still_atomic_with_flag():
    # un list_item reste atomique (priorité ATOMIC_TYPES, indépendant du flag)
    idx = AssertionUnitIndexer(min_unit_length=5, keep_enumeration_as_unit=True)
    res = idx.index_docitem("doc:3", "stock, purchase orders, and production orders",
                            item_type="list_item")
    assert len(res.units) == 1
    assert res.units[0].unit_type == "bullet"
