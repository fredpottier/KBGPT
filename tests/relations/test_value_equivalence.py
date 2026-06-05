"""Tests value_equivalence — requalification des fausses divergences d'unités."""

import pytest

from knowbase.relations.value_equivalence import (
    extract_quantities,
    quantities_equivalent,
)


def test_extract_lb_kn_kg():
    q = extract_quantities("the load does not exceed 1,500 lbs (6.67 kN)")
    assert "load" in q and len(q["load"]) == 2
    # 1500 lb ≈ 6672 N ; 6.67 kN = 6670 N
    assert all(abs(v - 6670) < 70 for v in q["load"])


# Le cas réel FAA/EASA qui a déclenché le fix (chat 05/06)
def test_faa_easa_lumbar_load_equivalent():
    faa = ("The maximum compressive load measure between the pelvis and the "
           "lumbar column of the ATD does not exceed 1,500 lbs (6.67 kN).")
    easa = ("The maximum compressive load measured between the pelvis and the "
            "lumbar column of the anthropomorphic dummy must not exceed 680 kg (1500 lb).")
    assert quantities_equivalent(faa, easa) is True


def test_real_divergence_kept():
    # Vraie divergence : 0.09 s vs 0.08 s (cas AC 25-17A vs NPA 2013-20)
    a = "The time duration shall not exceed 0.09 seconds."
    b = "The time duration shall not exceed 0.08 seconds."
    assert quantities_equivalent(a, b) is False


def test_channel_class_not_confused():
    # Pas de dimension partagée extraite → non-équivalent (on ne sur-affirme pas)
    a = "Loads shall be measured in accordance with Channel Class 60."
    b = "Neck moments shall be measured in accordance with Channel Class 600."
    assert quantities_equivalent(a, b) is False


def test_inches_mm_equivalent():
    a = "The displacement must not exceed 2 inches."
    b = "Le déplacement ne doit pas dépasser 50,8 mm."
    assert quantities_equivalent(a, b) is True


def test_no_quantities():
    assert quantities_equivalent("no numbers here", "none here either") is False


def test_thousands_separator():
    q = extract_quantities("limit of 1,500 lb and also 1 500 lb")
    assert len(q.get("load", [])) == 2
