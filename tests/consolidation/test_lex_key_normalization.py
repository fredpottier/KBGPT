"""
Tests de non-régression pour compute_lex_key et le corpus-aware lex_key normalization.

ADR: doc/ongoing/ADR_CORPUS_AWARE_LEX_KEY_NORMALIZATION.md

Ces tests vérifient que la normalisation lex_key:
- Gère la ponctuation (S/4HANA → s 4hana)
- Gère les accents (Données → donnee)
- Gère les espaces multiples
- Gère la casse
- Gère les pluriels (light singularization)

Author: OSMOSE
Date: 2026-01-11
"""

import pytest
from knowbase.consolidation.lex_utils import compute_lex_key


class TestComputeLexKey:
    """Tests pour compute_lex_key()."""

    def test_empty_string(self):
        """Empty string returns empty string."""
        assert compute_lex_key("") == ""

    def test_lowercase(self):
        """Conversion en minuscules."""
        assert compute_lex_key("SAP") == "sap"
        assert compute_lex_key("CLOUD") == "cloud"

    def test_strip_whitespace(self):
        """Supprime les espaces en début et fin."""
        assert compute_lex_key("  SAP  ") == "sap"
        assert compute_lex_key("\tCloud\n") == "cloud"

    def test_normalize_whitespace(self):
        """Normalise les espaces multiples."""
        assert compute_lex_key("SAP   Cloud") == "sap cloud"
        # Note: "business" is an exception in singularization, so it stays "business"
        assert compute_lex_key("Business  Intelligence  Platform") == "business intelligence platform"

    def test_remove_punctuation(self):
        """Supprime la ponctuation."""
        assert compute_lex_key("S/4HANA") == "s 4hana"
        assert compute_lex_key("SAP-Cloud") == "sap cloud"
        assert compute_lex_key("(test)") == "test"
        assert compute_lex_key("AI/ML") == "ai ml"

    def test_remove_accents(self):
        """Supprime les accents (normalisation Unicode)."""
        assert compute_lex_key("Données") == "donnee"
        assert compute_lex_key("Éléments") == "element"
        assert compute_lex_key("café") == "cafe"
        assert compute_lex_key("naïve") == "naive"

    def test_light_singularization(self):
        """Singularisation légère (EN/FR)."""
        assert compute_lex_key("documents") == "document"
        assert compute_lex_key("concepts") == "concept"
        assert compute_lex_key("entities") == "entitie"  # Light singularization
        # Exceptions preserved
        assert compute_lex_key("analysis") == "analysis"
        assert compute_lex_key("business") == "business"
        assert compute_lex_key("process") == "process"

    def test_short_words_not_singularized(self):
        """Mots courts (<=3 chars) ne sont pas singularisés."""
        assert compute_lex_key("SAP") == "sap"  # Not "sa"
        assert compute_lex_key("ERP") == "erp"  # Not "er"
        assert compute_lex_key("bus") == "bus"  # Not "bu"

    def test_acronyms_preserved(self):
        """Les acronymes sont préservés (en lowercase)."""
        assert compute_lex_key("GDPR") == "gdpr"
        assert compute_lex_key("NIS2") == "nis2"
        assert compute_lex_key("AI") == "ai"

    def test_combined_transformations(self):
        """Transformations combinées."""
        assert compute_lex_key("SAP S/4HANA") == compute_lex_key("sap s 4hana")
        assert compute_lex_key("  Données  Clients  ") == "donnee client"
        assert compute_lex_key("SAP-S/4HANA-Cloud") == "sap s 4hana cloud"


class TestLexKeyEquivalence:
    """Tests que des variantes du même concept produisent le même lex_key."""

    def test_sap_s4hana_variants(self):
        """Toutes les variantes de SAP S/4HANA produisent le même lex_key."""
        expected = compute_lex_key("SAP S/4HANA")
        assert compute_lex_key("SAP S/4HANA") == expected
        assert compute_lex_key("sap s/4hana") == expected
        assert compute_lex_key("SAP S 4HANA") == expected
        assert compute_lex_key("SAP S-4HANA") == expected
        assert compute_lex_key("  SAP  S/4HANA  ") == expected

    def test_accent_variants(self):
        """Variantes avec/sans accents produisent le même lex_key."""
        assert compute_lex_key("Données") == compute_lex_key("Donnees")
        assert compute_lex_key("Éléments") == compute_lex_key("Elements")
        assert compute_lex_key("schéma") == compute_lex_key("schema")

    def test_case_variants(self):
        """Variantes de casse produisent le même lex_key."""
        assert compute_lex_key("Business Process") == compute_lex_key("business process")
        assert compute_lex_key("ENTERPRISE RESOURCE PLANNING") == compute_lex_key("Enterprise Resource Planning")

    def test_plural_variants(self):
        """Singulier et pluriel produisent le même lex_key."""
        assert compute_lex_key("document") == compute_lex_key("documents")
        assert compute_lex_key("concept") == compute_lex_key("concepts")
        assert compute_lex_key("entity") == compute_lex_key("entitys")  # Même si grammaticalement incorrect


class TestLexKeyDifferentiation:
    """Tests que des concepts différents produisent des lex_keys différents."""

    def test_different_concepts(self):
        """Concepts différents ont des lex_keys différents."""
        assert compute_lex_key("SAP") != compute_lex_key("Oracle")
        assert compute_lex_key("ERP") != compute_lex_key("CRM")
        assert compute_lex_key("Cloud") != compute_lex_key("On-Premise")

    def test_similar_but_different(self):
        """Concepts similaires mais différents restent distincts."""
        assert compute_lex_key("S/4HANA") != compute_lex_key("S/4HANA Cloud")
        assert compute_lex_key("Business") != compute_lex_key("Business Intelligence")


class TestCorpusPromotionIntegration:
    """Tests d'intégration pour le groupement par lex_key dans corpus_promotion."""

    def test_group_by_lex_key_basic(self):
        """Test basique du groupement par lex_key."""
        from knowbase.consolidation.corpus_promotion import CorpusPromotionEngine

        # Create engine without actual Neo4j connection for unit testing
        # Just test the _get_lex_key helper
        engine = CorpusPromotionEngine.__new__(CorpusPromotionEngine)

        # Test _get_lex_key with stored lex_key
        proto_with_key = {"lex_key": "sap s 4hana", "label": "SAP S/4HANA"}
        assert engine._get_lex_key(proto_with_key) == "sap s 4hana"

        # Test _get_lex_key with fallback
        proto_without_key = {"label": "SAP S/4HANA"}
        assert engine._get_lex_key(proto_without_key) == compute_lex_key("SAP S/4HANA")

    def test_type_guard_dominance(self):
        """Test du type guard avec dominance."""
        from knowbase.consolidation.corpus_promotion import CorpusPromotionEngine

        engine = CorpusPromotionEngine.__new__(CorpusPromotionEngine)

        # 70%+ dominance → pas de split
        protos = [
            {"label": "SAP", "type_heuristic": "product"},
            {"label": "SAP", "type_heuristic": "product"},
            {"label": "SAP", "type_heuristic": "product"},
            {"label": "SAP", "type_heuristic": "company"},  # 25% minority
        ]
        result = engine.split_by_type_if_divergent("sap", protos)
        assert len(result) == 1
        assert result[0][0] == "product"  # Type dominant
        assert result[0][2] is False  # Pas de conflit

    def test_type_guard_divergence_short(self):
        """Test du type guard avec divergence sur label court."""
        from knowbase.consolidation.corpus_promotion import CorpusPromotionEngine

        engine = CorpusPromotionEngine.__new__(CorpusPromotionEngine)

        # Divergence forte + label court → split agressif
        protos = [
            {"label": "SAP", "type_heuristic": "product"},
            {"label": "SAP", "type_heuristic": "company"},
        ]
        result = engine.split_by_type_if_divergent("sap", protos)
        assert len(result) == 2  # Split par type
        types = {r[0] for r in result}
        assert "product" in types
        assert "company" in types

    def test_type_guard_divergence_long(self):
        """Test du type guard avec divergence sur label long."""
        from knowbase.consolidation.corpus_promotion import CorpusPromotionEngine

        engine = CorpusPromotionEngine.__new__(CorpusPromotionEngine)

        # Divergence forte + label long → garder ensemble + flag
        protos = [
            {"label": "Enterprise Resource Planning", "type_heuristic": "concept"},
            {"label": "Enterprise Resource Planning", "type_heuristic": "software"},
        ]
        result = engine.split_by_type_if_divergent("enterprise resource planning", protos)
        assert len(result) == 1  # Pas de split
        assert result[0][2] is True  # type_conflict=True


class TestMigrationScriptImport:
    """Tests que le script de migration peut être importé."""

    def test_import_migrate_lex_key(self):
        """Le script de migration peut être importé."""
        try:
            from scripts.migrate_lex_key import migrate_lex_keys, verify_migration
            assert callable(migrate_lex_keys)
            assert callable(verify_migration)
        except ImportError as e:
            pytest.skip(f"Script import failed (expected if not in PYTHONPATH): {e}")
