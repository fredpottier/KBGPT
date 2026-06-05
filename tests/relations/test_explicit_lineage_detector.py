"""Tests de la logique pure du détecteur de lignée explicite (#443).

Couvre `normalize_reg_key`, `find_reg_ids`, `parse_lineage` — y compris les
pièges réels rencontrés sur le corpus aéro (FSSR canceled-by, « replace »
générique, auto-référence, mentions incidentes). Domain-agnostic.
"""

import pytest

from knowbase.relations.explicit_lineage_detector import (
    LineageParse,
    LineageReject,
    find_reg_ids,
    normalize_reg_key,
    parse_lineage,
    regulatory_authority,
)


@pytest.mark.parametrize(
    "doc,expected",
    [
        ("AC_25-17A_55f08065", "FAA"),
        ("AC 21-25B", "FAA"),
        ("CFR_part25_seats_extract", "FAA"),
        ("TSO-C127", "FAA"),
        ("ETSO-C127c_amd17", "EASA"),
        ("NPA_2013-20_seat", "EASA"),
        ("CS-25", "EASA"),
        ("patent_US9399518", None),
        ("side_facing_seat_research", None),
        (None, None),
    ],
)
def test_regulatory_authority(doc, expected):
    assert regulatory_authority(doc) == expected


# --------------------------------------------------------------------------- #
# normalize_reg_key
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected",
    [
        # doc_id (suffixe de hash retiré)
        ("AC_21-25A_515205d7", "AC 21-25A"),
        ("AC_25.562-1B_e14eda4f", "AC 25.562-1B"),
        ("AC_20-146_cancelled_5fb3ed5e", "AC 20-146"),
        ("AC_25-17A_55f08065", "AC 25-17A"),
        ("ETSO-C127c_amd17_d2c85ef0", "ETSO-C127C"),
        ("NPA_2013-20_seat_crashworthiness_fdd93d4d", "NPA 2013-20"),
        # mentions en texte libre
        ("AC 21-25A", "AC 21-25A"),
        ("Advisory Circular 25.562-1", "AC 25.562-1"),
        ("ADVISORY CIRCULAR 25-17", "AC 25-17"),
        ("AC 00-20", "AC 00-20"),
        # non reconnus -> None
        ("patent_US9399518_energy_absorber_bdef6e4f", None),
        ("side_facing_seat_research_ada1d53b", None),
        ("the 1998 policy", None),
        ("AS8049C", None),  # norme, pas un document réglementaire
        ("", None),
        (None, None),
    ],
)
def test_normalize_reg_key(raw, expected):
    assert normalize_reg_key(raw) == expected


def test_find_reg_ids_in_order():
    txt = "This AC cancels AC 21-25A, see also Advisory Circular 25.562-1."
    keys = [k for k, _ in find_reg_ids(txt)]
    assert "AC 21-25A" in keys
    assert "AC 25.562-1" in keys


# --------------------------------------------------------------------------- #
# parse_lineage — cas ACCEPTÉS
# --------------------------------------------------------------------------- #
def test_active_supersession_source_is_superseder():
    txt = "This AC cancels AC 21-25A, Approval of Modified Seating Systems, dated 6/3/97."
    res = parse_lineage(txt, source_key="AC 21-25B")
    assert isinstance(res, LineageParse)
    assert res.superseder_key == "AC 21-25B"
    assert res.superseded_key == "AC 21-25A"
    assert res.superseder_is_source is True
    assert res.pattern == "active"
    assert res.stated_date == "6/3/97"


def test_passive_supersession_source_is_superseder():
    txt = "AC 21-25, Approval of Modified Seats and Berths, dated 4/24/89, is canceled."
    res = parse_lineage(txt, source_key="AC 21-25A")
    assert isinstance(res, LineageParse)
    assert res.superseder_key == "AC 21-25A"
    assert res.superseded_key == "AC 21-25"
    assert res.pattern == "passive"
    assert res.stated_date == "4/24/89"  # queue « , is canceled » coupée


def test_active_with_long_date():
    txt = "This AC cancels AC 20-146, Methodology for Dynamic Seat Certification, dated May 19, 2003."
    res = parse_lineage(txt, source_key="AC 20-146A")
    assert isinstance(res, LineageParse)
    assert res.superseded_key == "AC 20-146"
    assert res.stated_date == "May 19, 2003"


# --------------------------------------------------------------------------- #
# parse_lineage — cas REJETÉS (les pièges)
# --------------------------------------------------------------------------- #
def test_reject_canceled_by_agent_without_doc_subject():
    # « The FSSR was canceled by AC 00-20 » : le sujet superséd é (FSSR) n'est pas
    # un document reconnu, seul l'agent l'est -> on n'invente pas d'edge.
    txt = "The FSSR was canceled by AC 00-20, 'Cancellation of Flight Standards Service Releases.'"
    res = parse_lineage(txt, source_key="AC 25-17A")
    assert isinstance(res, LineageReject)


def test_reject_generic_replace_ballast():
    txt = "Items of mass on the seat, such as under-seat IFE boxes, may be replaced by ballast."
    res = parse_lineage(txt, source_key="AC 25-17A")
    assert isinstance(res, LineageReject)  # « replace » n'est pas un verbe de supersession


def test_reject_incidental_reference():
    txt = "Further, we have deleted a reference to canceled AC 25-17 that is no longer relevant."
    res = parse_lineage(txt, source_key="AC 25.562-1B")
    assert isinstance(res, LineageReject)
    assert "incidente" in res.reason


def test_reject_paragraph_renumbering():
    txt = "Paragraphs 5e(5)(e) are redesignated as paragraphs 5e(5)(d)2 and 5e(5)(d)3."
    res = parse_lineage(txt, source_key="AC 25-17A")
    assert isinstance(res, LineageReject)


def test_reject_self_reference_only():
    txt = "This AC supersedes guidance but cites no other document."
    res = parse_lineage(txt, source_key="AC 25-17A")
    assert isinstance(res, LineageReject)


def test_reject_no_verb():
    txt = "AC 21-25A is the current advisory circular for modified seats."
    res = parse_lineage(txt, source_key="AC 21-25B")
    assert isinstance(res, LineageReject)
    assert "verbe" in res.reason


def test_reject_negated_supersession():
    # Bug réel 04/06 : « does not supersede » matchait le verbe → edge fantôme.
    txt = ("This policy memorandum does not supersede any of the other methods of "
           "compliance pertaining to AC 25-17.")
    res = parse_lineage(txt, source_key="AC 25-17A")
    assert isinstance(res, LineageReject)
    assert "nié" in res.reason


def test_negated_and_affirmative_mix_is_kept():
    # Une occurrence affirmative suffit, même si une autre est niée.
    txt = ("This AC does not supersede AC 21-49; however, this AC cancels AC 21-25A, "
           "dated 6/3/97.")
    res = parse_lineage(txt, source_key="AC 21-25B")
    assert isinstance(res, LineageParse)
    assert res.superseded_key in ("AC 21-25A", "AC 21-49")


# --------------------------------------------------------------------------- #
# is_doc_supersession_statement (garde lifecycle de la selection gate)
# --------------------------------------------------------------------------- #
from knowbase.relations.explicit_lineage_detector import is_doc_supersession_statement


@pytest.mark.parametrize(
    "txt,expected",
    [
        ("This AC cancels AC 21-25A, Approval of Modified Seating Systems, dated 6/3/97.", True),
        ("Advisory Circular 25.562-1 is cancelled.", True),
        ("This policy memorandum does not supersede AC 25-17.", False),  # nié
        ("This guide is organized into five chapters.", False),  # doc_meta sans verbe
        ("Items of mass may be replaced by ballast.", False),  # replace ≠ verbe de supersession
        ("The system supersedes expectations.", False),  # verbe mais aucun identifiant de doc
    ],
)
def test_is_doc_supersession_statement(txt, expected):
    assert is_doc_supersession_statement(txt) is expected


# ── is_regulatory_lifecycle_statement (audit #450, 05/06/2026) ─────────────────
# Ancres réelles perdues par la selection gate lors de la ré-ingestion staged.

from knowbase.relations.explicit_lineage_detector import is_regulatory_lifecycle_statement


@pytest.mark.parametrize(
    "txt,expected",
    [
        # Changements structurels réglementaires (changelog AC 25.562-1B, AC 25-17A)
        ("Deletes paragraph 5e(5)(d) and the bulleted list of items that follow it.", True),
        ("Redesignates paragraph 5e(5)(e) as paragraph 5e(5)(d).", True),
        ("This amendment substantially revised the regulation to move the test criteria to a new Appendix J of the regulation.", True),
        ("Section 25.791 did not exist prior to Amendment 25-32.", True),
        ("Added a new requirement that areas likely to become wet in service have slip resistant floors (§ 25.793).", True),
        # Provenance documentaire identifiée (memo PSAIR100 perdu)
        ("The FAA has published guidance to assist with classifying major vs. minor changes by the TSO seat manufacturer in policy memorandum PSAIR100-9/8/2003.", True),
        # Négatifs : verbe sans cible structurelle / méta-doc pur / en-tête
        ("The kit adds a cable and a charger.", False),
        ("This guide is organized into five chapters.", False),
        ("7.20 Follow-Up Activities", False),
        ("The platform delivers powerful capabilities for success.", False),
        # « published » sans identifiant précis → pas de rescue provenance
        ("The agency published guidance on this topic.", False),
    ],
)
def test_is_regulatory_lifecycle_statement(txt, expected):
    assert is_regulatory_lifecycle_statement(txt) is expected
