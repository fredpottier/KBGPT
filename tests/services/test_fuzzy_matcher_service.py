"""
Tests pour FuzzyMatcherService.

Phase 5B - Step 3
"""
import pytest
from knowbase.api.services.fuzzy_matcher_service import FuzzyMatcherService


class TestFuzzyMatcherService:
    """Tests fuzzy matching avec seuils adaptatifs."""

    @pytest.fixture
    def service(self):
        """Fixture service."""
        return FuzzyMatcherService()

    def test_match_exact(self, service):
        """✅ Match exact (100%)."""
        ontology_entry = {
            "canonical_name": "SAP S/4HANA Private Cloud Edition",
            "aliases": ["SAP S/4HANA PCE"]
        }

        is_match, score, matched_name = service.match_entity_to_ontology(
            "SAP S/4HANA Private Cloud Edition",
            ontology_entry
        )

        assert is_match is True
        assert score == 100
        assert matched_name == "SAP S/4HANA Private Cloud Edition"

    def test_match_alias_high_score(self, service):
        """✅ Match alias avec score >= 90%."""
        ontology_entry = {
            "canonical_name": "SAP S/4HANA Private Cloud Edition",
            "aliases": ["SAP S/4HANA PCE", "S/4HANA Private Cloud"]
        }

        is_match, score, matched_name = service.match_entity_to_ontology(
            "SAP S/4HANA PCE",
            ontology_entry
        )

        assert is_match is True
        assert score >= 90  # Auto-match threshold
        assert "PCE" in matched_name or "Private Cloud" in matched_name

    def test_match_medium_score(self, service):
        """⚠️ Match suggéré avec score 75-89%."""
        ontology_entry = {
            "canonical_name": "SAP S/4HANA Private Cloud Edition",
            "aliases": []
        }

        is_match, score, matched_name = service.match_entity_to_ontology(
            "SAP S/4 HANA Cloud Private",  # Variante avec espace
            ontology_entry
        )

        assert is_match is True
        assert 75 <= score < 90  # Seuil manuel

    def test_no_match_low_score(self, service):
        """❌ Pas de match si score < 75%."""
        ontology_entry = {
            "canonical_name": "SAP S/4HANA Private Cloud Edition",
            "aliases": []
        }

        is_match, score, matched_name = service.match_entity_to_ontology(
            "SAP Business One",  # Complètement différent
            ontology_entry
        )

        assert is_match is False
        assert score < 75

    def test_compute_merge_preview(self, service):
        """✅ Calcul preview complet."""
        entities = [
            {"uuid": "1", "name": "SAP S/4HANA PCE", "description": ""},
            {"uuid": "2", "name": "SAP S/4HANA Private Cloud", "description": ""},
            {"uuid": "3", "name": "SAP Business One", "description": ""},
        ]

        ontology = {
            "SAP_S4HANA_PRIVATE_CLOUD": {
                "canonical_name": "SAP S/4HANA Private Cloud Edition",
                "aliases": ["SAP S/4HANA PCE", "S/4HANA Private Cloud"],
                "confidence": 0.95
            }
        }

        preview = service.compute_merge_preview(entities, ontology)

        assert preview["summary"]["total_entities"] == 3
        assert preview["summary"]["entities_matched"] >= 2  # Les 2 S/4HANA
        assert len(preview["merge_groups"]) >= 1

        # Vérifier groupe S4HANA
        s4_group = preview["merge_groups"][0]
        assert s4_group["canonical_key"] == "SAP_S4HANA_PRIVATE_CLOUD"
        assert len(s4_group["entities"]) >= 2

        # Vérifier auto_match pour score >= 90%
        for entity in s4_group["entities"]:
            if entity["score"] >= 90:
                assert entity["auto_match"] is True
                assert entity["selected"] is True
            else:
                assert entity["auto_match"] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
