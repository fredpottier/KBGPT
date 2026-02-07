"""
Tests pour l'assainissement des entities :
- ENTITY_STOPLIST enrichie (mots-outils)
- strip_version_qualifier (domain-agnostic)
- is_valid_entity_name avec PHRASE_FRAGMENT_INDICATORS
- Source #6 entity extractor (structured_form)
"""

import pytest

from knowbase.claimfirst.models.entity import (
    Entity,
    ENTITY_STOPLIST,
    PHRASE_FRAGMENT_INDICATORS,
    is_valid_entity_name,
    strip_version_qualifier,
)


class TestEnrichedStoplist:
    """Vérifie que les mots-outils domain-agnostic sont dans la stoplist."""

    @pytest.mark.parametrize("word", [
        # Prépositions
        "to", "of", "in", "on", "at", "by", "for", "with", "from",
        "into", "onto", "upon", "about", "between", "through",
        # Conjonctions / négations
        "and", "or", "but", "not", "no", "nor",
        # Adverbes
        "also", "very", "only", "just",
        # Verbes courts
        "use", "used", "uses", "set", "get", "run", "make",
        # Pronoms
        "his", "her", "our", "your", "their", "my",
        "which", "where", "when", "how", "what", "who",
    ])
    def test_function_words_in_stoplist(self, word):
        assert word in ENTITY_STOPLIST, f"'{word}' devrait être dans ENTITY_STOPLIST"

    @pytest.mark.parametrize("word", [
        # Termes métier qui NE doivent PAS être dans la stoplist
        "production", "sales", "goods", "scheduling", "manufacturing",
        "inventory", "warehouse", "authentication", "encryption",
        "database", "network", "cloud",
    ])
    def test_domain_terms_not_in_stoplist(self, word):
        assert word not in ENTITY_STOPLIST, f"'{word}' ne devrait PAS être dans ENTITY_STOPLIST (domain-agnostic)"


class TestIsValidEntityName:
    """Vérifie que is_valid_entity_name rejette les candidats garbage."""

    @pytest.mark.parametrize("name", [
        "To", "IS", "OF", "Not", "And", "Or", "By", "For", "With",
        "Use", "Used", "Set", "Get", "Run", "Make",
        "His", "Her", "Our", "Their",
    ])
    def test_rejects_function_words(self, name):
        assert not is_valid_entity_name(name), f"'{name}' devrait être rejeté"

    @pytest.mark.parametrize("name", [
        "SAP S/4HANA", "Material Ledger", "Cloud Connector",
        "TLS", "GDPR", "ISO 27001",
        "Identity Authentication", "Credit Management",
    ])
    def test_accepts_valid_entities(self, name):
        assert is_valid_entity_name(name), f"'{name}' devrait être accepté"

    def test_rejects_phrase_fragments(self):
        """Les noms contenant des verbes auxiliaires sont des fragments de phrase."""
        assert not is_valid_entity_name("Customer is required")
        assert not is_valid_entity_name("Data has been migrated")
        assert not is_valid_entity_name("System should be configured")

    def test_accepts_acronyms(self):
        """Les acronymes majuscules 2-5 lettres sont toujours valides."""
        assert is_valid_entity_name("EU")
        assert is_valid_entity_name("BTP")
        assert is_valid_entity_name("GDPR")


class TestStripVersionQualifier:
    """Vérifie le version stripping domain-agnostic."""

    @pytest.mark.parametrize("name, expected_base, expected_version", [
        # Versions numériques
        ("S/4HANA 2023", "S/4HANA", "2023"),
        ("Windows 11", "Windows", "11"),
        ("React 18.2", "React", "18.2"),
        ("Python 3.13", "Python", "3.13"),
        ("v3.2.1", "v3.2.1", None),  # base trop courte après strip
        # Versions avec préfixe v
        ("Product v2", "Product", "v2"),
        ("OpenSSL v1.1.1", "OpenSSL", "v1.1.1"),
        # Versions romaines
        ("Clio III", "Clio", "III"),
        # Pas de version
        ("SAP BTP", "SAP BTP", None),
        ("Cloud Connector", "Cloud Connector", None),
        ("TLS", "TLS", None),
        # Cas limite : version seule
        ("2023", "2023", None),  # pas de base
    ])
    def test_strip_version(self, name, expected_base, expected_version):
        base, version = strip_version_qualifier(name)
        assert base == expected_base, f"base pour '{name}': attendu '{expected_base}', obtenu '{base}'"
        assert version == expected_version, f"version pour '{name}': attendu '{expected_version}', obtenu '{version}'"

    def test_strip_preserves_whitespace(self):
        """Le stripping doit gérer les espaces autour."""
        base, version = strip_version_qualifier("  S/4HANA 2023  ")
        assert base == "S/4HANA"
        assert version == "2023"


class TestEntityExtractorSource6:
    """Vérifie la Source #6 (structured_form) dans l'extracteur."""

    def test_extract_from_structured_form(self):
        """L'extracteur doit extraire les entities depuis structured_form."""
        pytest.importorskip("yaml", reason="yaml non installé localement")
        from knowbase.claimfirst.extractors.entity_extractor import EntityExtractor
        from knowbase.claimfirst.models.claim import Claim, ClaimType

        claim = Claim(
            claim_id="test_claim_1",
            tenant_id="test",
            doc_id="doc1",
            text="Material Ledger replaces traditional Inventory Management",
            claim_type=ClaimType.FACTUAL,
            verbatim_quote="Material Ledger replaces traditional Inventory Management",
            passage_id="p1",
            structured_form={
                "subject": "Material Ledger",
                "predicate": "REPLACES",
                "object": "Inventory Management",
            },
        )

        extractor = EntityExtractor()
        candidates = extractor._extract_candidates_from_claim(claim, {})

        # Vérifier que subject et object du SF sont dans les candidats
        candidate_names = [name for name, _ in candidates]
        candidate_norms = [Entity.normalize(name) for name, _ in candidates]

        assert "material ledger" in candidate_norms, \
            f"'Material Ledger' (subject) devrait être extrait. Candidats: {candidate_names}"
        assert "inventory management" in candidate_norms, \
            f"'Inventory Management' (object) devrait être extrait. Candidats: {candidate_names}"

    def test_sf_invalid_entities_filtered(self):
        """Les entities invalides depuis SF doivent être filtrées."""
        pytest.importorskip("yaml", reason="yaml non installé localement")
        from knowbase.claimfirst.extractors.entity_extractor import EntityExtractor
        from knowbase.claimfirst.models.claim import Claim, ClaimType

        claim = Claim(
            claim_id="test_claim_2",
            tenant_id="test",
            doc_id="doc1",
            text="The system provides data processing capabilities",
            claim_type=ClaimType.FACTUAL,
            verbatim_quote="The system provides data processing capabilities",
            passage_id="p1",
            structured_form={
                "subject": "system",  # dans la stoplist
                "predicate": "PROVIDES",
                "object": "data",  # dans la stoplist
            },
        )

        extractor = EntityExtractor()
        candidates = extractor._extract_candidates_from_claim(claim, {})

        candidate_norms = [Entity.normalize(name) for name, _ in candidates]
        assert "system" not in candidate_norms, "'system' devrait être filtré (stoplist)"
        assert "data" not in candidate_norms, "'data' devrait être filtré (stoplist)"


class TestVersionStrippingInExtractor:
    """Vérifie que le version stripping est appliqué dans l'extracteur."""

    def test_version_stripped_during_extraction(self):
        """L'extracteur doit créer les entities sans suffixe version."""
        pytest.importorskip("yaml", reason="yaml non installé localement")
        from knowbase.claimfirst.extractors.entity_extractor import EntityExtractor
        from knowbase.claimfirst.models.claim import Claim, ClaimType

        claim = Claim(
            claim_id="test_claim_3",
            tenant_id="test",
            doc_id="doc1",
            text="S/4HANA 2023 supports Material Ledger",
            claim_type=ClaimType.FACTUAL,
            verbatim_quote="S/4HANA 2023 supports Material Ledger",
            passage_id="p1",
        )

        extractor = EntityExtractor()
        entities, claim_map = extractor.extract_from_claims([claim], [], "test")

        entity_names = [e.name for e in entities]
        entity_norms = [e.normalized_name for e in entities]

        # "S/4HANA 2023" ne doit PAS apparaître, mais "S/4HANA" doit
        # Note: cela dépend de si le pattern capture "S/4HANA 2023"
        for name in entity_names:
            assert "2023" not in name, \
                f"Version '2023' ne devrait pas être dans le nom d'entity '{name}'"
