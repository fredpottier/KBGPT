"""Tests Carte du Référentiel (#456) — helpers purs du router."""

from knowbase.api.routers.referentiel import _doc_title, _parse_stated_date


class TestDocTitle:
    def test_reg_key_prioritaire(self):
        assert _doc_title("AC_25-17A_55f08065", "AC 25-17A") == "AC 25-17A"

    def test_fallback_strip_hash_et_underscores(self):
        assert _doc_title("AC_25-17A_55f08065", None) == "AC 25-17A"

    def test_fallback_sans_hash(self):
        # pas de suffixe hash → seuls les underscores sont remplacés
        assert _doc_title("side_facing_seat_research", None) == "side facing seat research"

    def test_doc_id_vide(self):
        assert _doc_title("", None) == ""


class TestParseStatedDate:
    """Formats réels rencontrés dans les déclarations de supersession."""

    def test_us_numeric_2_digits(self):
        assert _parse_stated_date("4/24/89") == "1989-04-24"
        assert _parse_stated_date("6/3/97") == "1997-06-03"

    def test_us_numeric_pivot_siecle(self):
        # ≤ 30 → 2000s (citations récentes), > 30 → 1900s
        assert _parse_stated_date("3/6/12") == "2012-03-06"

    def test_month_name(self):
        assert _parse_stated_date("July 15, 1991") == "1991-07-15"
        assert _parse_stated_date("March 6, 1990") == "1990-03-06"

    def test_invalides(self):
        assert _parse_stated_date(None) is None
        assert _parse_stated_date("") is None
        assert _parse_stated_date("n/a") is None
        assert _parse_stated_date("13/45/89") is None  # mois impossible
