"""Tests #457 — datation documentaire des cartouches US (formats à 2 chiffres).

Cas réel : AC 25.562-1A page 1 contient « Date:\\n01/19/96 » que l'ancien
extracteur ne reconnaissait pas (mot-clé « date: » absent, format M/D/YY non
géré, lecture européenne). Doit désormais donner 1996-01-19.
"""

from knowbase.ingestion.document_valid_from_extractor import (
    _extract_s2_core,
    _normalize_match,
    _disambiguate_dmy,
)


class TestDisambiguateDmy:
    def test_jour_superieur_12_tranche_DM(self):
        assert _disambiguate_dmy(19, 1) == (19, 1)   # 19/1 → jour 19 mois 1

    def test_jour_en_second_tranche_MD(self):
        assert _disambiguate_dmy(1, 19) == (19, 1)   # 1/19 (US M/D) → jour 19 mois 1

    def test_ambigu_defaut_US_MD(self):
        # 3/6 ambigu → US M/D : mois 3, jour 6
        assert _disambiguate_dmy(3, 6) == (6, 3)

    def test_impossible(self):
        assert _disambiguate_dmy(19, 19) is None


class TestNormalizeMatchShort:
    def test_us_short_pivot_siecle(self):
        # 01/19/96 → 1996-01-19 (US M/D, pivot 96 → 1996)
        assert _normalize_match("slash_short", ("01", "19", "96")) == "1996-01-19"

    def test_us_short_annee_2000s(self):
        assert _normalize_match("slash_short", ("3", "6", "12")) == "2012-03-06"

    def test_slash_long_plausibilite(self):
        # 19/01/1996 (européen, 19>12) → 1996-01-19
        assert _normalize_match("slash", ("19", "01", "1996")) == "1996-01-19"
        # 01/19/1996 (US, 19>12) → 1996-01-19
        assert _normalize_match("slash", ("01", "19", "1996")) == "1996-01-19"


class TestExtractS2Cartouche:
    def test_cartouche_faa_date_courte(self):
        # reproduit la page 1 de l'AC 25.562-1A (texte lowercased)
        page1 = (
            "advisory circular\n"
            "date:\n01/19/96\n"
            "initiated by:\nanm_110\n"
            "ac no:\n25.562-1a\n"
            "subject:: dynamic evaluation of seat restraint systems"
        )
        res = _extract_s2_core(page1)
        assert res["found"] is True
        assert res["value"] == "1996-01-19"

    def test_keyword_specifique_prioritaire(self):
        # « effective date » (spécifique) l'emporte sur « date: » nu
        page1 = "foo effective date: 03/15/1999 bar\ndate:\n01/19/96 baz"
        res = _extract_s2_core(page1)
        assert res["found"] is True
        assert res["value"] == "1999-03-15"
