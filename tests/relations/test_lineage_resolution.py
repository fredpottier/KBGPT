"""Tests de la logique pure de la résolution par lignée (ADR niveaux 1-2)."""

import pytest

from knowbase.relations.lineage_resolution import family_and_suffix, suffix_order


@pytest.mark.parametrize(
    "key,expected",
    [
        ("AC 25.785-1A", ("AC 25.785-1", "A")),
        ("AC 25.785-1B", ("AC 25.785-1", "B")),
        ("ETSO-C127C", ("ETSO-C127", "C")),
        ("ETSO-C127A", ("ETSO-C127", "A")),
        ("AC 25-17A", ("AC 25-17", "A")),
        # Pas de suffixe : édition originale
        ("AC 21-25", ("AC 21-25", "")),
        # Le chiffre final n'est PAS un suffixe (piège « 25.785-2 » de la revue B1)
        ("AC 21-49", ("AC 21-49", "")),
        ("NPA 2013-20", ("NPA 2013-20", "")),
        (None, None),
    ],
)
def test_family_and_suffix(key, expected):
    assert family_and_suffix(key) == expected


def test_suffix_order():
    assert suffix_order("") == 0
    assert suffix_order("A") == 1
    assert suffix_order("B") == 2
    assert suffix_order("") < suffix_order("A") < suffix_order("B") < suffix_order("C")


def test_same_base_different_families_not_confused():
    # « 25.785-1A » et « 25.785-2 » : bases différentes -> familles différentes
    b1 = family_and_suffix("AC 25.785-1A")
    b2 = family_and_suffix("AC 25.785-2")
    assert b1[0] != b2[0]
