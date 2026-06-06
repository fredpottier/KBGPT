"""Tests Carte du Référentiel (#456) — helpers purs du router."""

from knowbase.api.routers.referentiel import _doc_title


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
