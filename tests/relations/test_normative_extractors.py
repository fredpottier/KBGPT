"""
Tests pour NormativePatternExtractor et StructureParser.

ADR: doc/ongoing/ADR_NORMATIVE_RULES_SPEC_FACTS.md

Author: Claude Code
Date: 2026-01-21
"""

import pytest

from knowbase.relations.types import (
    NormativeModality,
    ConstraintType,
    SpecType,
    StructureType,
    NormativeRule,
    SpecFact,
    ExtractionMethod,
    normalize_for_dedup,
    dedup_key_rule,
    dedup_key_fact,
)
from knowbase.relations.normative_pattern_extractor import (
    NormativePatternExtractor,
    extract_normative_rules,
)
from knowbase.relations.structure_parser import (
    StructureParser,
    extract_spec_facts,
)


# =============================================================================
# Tests NormativeModality Enum
# =============================================================================

class TestNormativeModality:
    """Tests pour l'enum NormativeModality."""

    def test_modality_values(self):
        """Test que les valeurs sont correctes."""
        assert NormativeModality.MUST == "MUST"
        assert NormativeModality.MUST_NOT == "MUST_NOT"
        assert NormativeModality.SHOULD == "SHOULD"
        assert NormativeModality.SHOULD_NOT == "SHOULD_NOT"
        assert NormativeModality.MAY == "MAY"

    def test_domain_agnostic(self):
        """Test INV-AGN-01: Les modalités sont domain-agnostic."""
        # Aucune modalité ne doit contenir de terme métier
        domain_terms = ["sap", "hana", "medical", "car", "automotive"]
        for modality in NormativeModality:
            for term in domain_terms:
                assert term not in modality.value.lower()


# =============================================================================
# Tests ConstraintType Enum
# =============================================================================

class TestConstraintType:
    """Tests pour l'enum ConstraintType."""

    def test_constraint_values(self):
        """Test que les valeurs sont correctes."""
        assert ConstraintType.EQUALS == "EQUALS"
        assert ConstraintType.MIN == "MIN"
        assert ConstraintType.MAX == "MAX"
        assert ConstraintType.RANGE == "RANGE"
        assert ConstraintType.ENUM == "ENUM"
        assert ConstraintType.PATTERN == "PATTERN"


# =============================================================================
# Tests NormativePatternExtractor
# =============================================================================

class TestNormativePatternExtractor:
    """Tests pour l'extracteur de règles normatives."""

    @pytest.fixture
    def extractor(self):
        return NormativePatternExtractor(min_confidence=0.5)

    def test_extract_must_rule_en(self, extractor):
        """Test extraction d'une règle MUST en anglais."""
        text = "All HTTP connections must use TLS 1.2 or higher."
        rules = extractor.extract_from_text(
            text, source_doc_id="doc1", source_chunk_id="chunk1"
        )

        assert len(rules) == 1
        rule = rules[0]
        assert rule.modality == NormativeModality.MUST
        assert "HTTP connections" in rule.subject_text
        assert rule.evidence_span == text

    def test_extract_shall_rule_en(self, extractor):
        """Test extraction d'une règle SHALL en anglais."""
        text = "Passwords shall be at least 8 characters long."
        rules = extractor.extract_from_text(
            text, source_doc_id="doc1", source_chunk_id="chunk1"
        )

        assert len(rules) == 1
        rule = rules[0]
        assert rule.modality == NormativeModality.MUST

    def test_extract_must_not_rule_en(self, extractor):
        """Test extraction d'une règle MUST_NOT en anglais."""
        text = "Users must not share their credentials."
        rules = extractor.extract_from_text(
            text, source_doc_id="doc1", source_chunk_id="chunk1"
        )

        assert len(rules) == 1
        rule = rules[0]
        assert rule.modality == NormativeModality.MUST_NOT

    def test_extract_should_rule_en(self, extractor):
        """Test extraction d'une règle SHOULD en anglais."""
        text = "It is recommended to use 512GB RAM for production."
        rules = extractor.extract_from_text(
            text, source_doc_id="doc1", source_chunk_id="chunk1"
        )

        assert len(rules) == 1
        rule = rules[0]
        assert rule.modality == NormativeModality.SHOULD

    def test_extract_must_rule_fr(self, extractor):
        """Test extraction d'une règle MUST en français."""
        text = "Les connexions doivent utiliser TLS 1.2 au minimum."
        rules = extractor.extract_from_text(
            text, source_doc_id="doc1", source_chunk_id="chunk1"
        )

        assert len(rules) == 1
        rule = rules[0]
        assert rule.modality == NormativeModality.MUST

    def test_no_extraction_without_modal(self, extractor):
        """Test qu'on n'extrait pas sans marqueur modal."""
        text = "TLS 1.2 provides better security than older versions."
        rules = extractor.extract_from_text(
            text, source_doc_id="doc1", source_chunk_id="chunk1"
        )

        # Pas de marqueur modal = pas de règle
        assert len(rules) == 0

    def test_detect_min_constraint(self, extractor):
        """Test détection de contrainte MIN."""
        text = "RAM must be at least 256GB."
        rules = extractor.extract_from_text(
            text, source_doc_id="doc1", source_chunk_id="chunk1"
        )

        assert len(rules) == 1
        assert rules[0].constraint_type == ConstraintType.MIN

    def test_detect_condition(self, extractor):
        """Test détection de condition."""
        text = "TLS is required when connecting externally."
        rules = extractor.extract_from_text(
            text, source_doc_id="doc1", source_chunk_id="chunk1"
        )

        assert len(rules) == 1
        rule = rules[0]
        assert rule.constraint_condition_span is not None
        assert "when" in rule.constraint_condition_span.lower()

    def test_multiple_rules_in_text(self, extractor):
        """Test extraction de plusieurs règles."""
        text = """
        All connections must use TLS 1.2.
        Passwords shall be at least 12 characters.
        It is recommended to enable 2FA.
        """
        rules = extractor.extract_from_text(
            text, source_doc_id="doc1", source_chunk_id="chunk1"
        )

        assert len(rules) == 3

    def test_rule_has_source_info(self, extractor):
        """Test que les règles ont les infos de source."""
        text = "All APIs must use authentication."
        rules = extractor.extract_from_text(
            text,
            source_doc_id="doc123",
            source_chunk_id="chunk456",
            source_segment_id="slide_7",
            evidence_section="Security Requirements"
        )

        assert len(rules) == 1
        rule = rules[0]
        assert rule.source_doc_id == "doc123"
        assert rule.source_chunk_id == "chunk456"
        assert rule.source_segment_id == "slide_7"
        assert rule.evidence_section == "Security Requirements"


# =============================================================================
# Tests Convenience Function
# =============================================================================

class TestExtractNormativeRulesConvenience:
    """Tests pour la fonction convenience."""

    def test_extract_normative_rules_function(self):
        """Test que la fonction convenience fonctionne."""
        text = "All data must be encrypted."
        rules = extract_normative_rules(text, "doc1", "chunk1")

        assert len(rules) == 1
        assert rules[0].modality == NormativeModality.MUST


# =============================================================================
# Tests StructureParser
# =============================================================================

class TestStructureParser:
    """Tests pour le parseur de structures."""

    @pytest.fixture
    def parser(self):
        return StructureParser()

    def test_extract_from_markdown_table(self, parser):
        """Test extraction depuis une table Markdown."""
        text = """
| Component | Minimum | Recommended |
|-----------|---------|-------------|
| RAM       | 256GB   | 512GB       |
| CPU       | 16      | 32          |
"""
        facts = parser.extract_from_text(
            text, source_doc_id="doc1", source_chunk_id="chunk1"
        )

        # 2 lignes x 2 colonnes valeur = 4 facts
        assert len(facts) >= 2

        # Vérifier qu'on a les attributs attendus
        attributes = {f.attribute_name for f in facts}
        assert "RAM" in attributes
        assert "CPU" in attributes

    def test_extract_from_key_value_list(self, parser):
        """Test extraction depuis une liste clé-valeur."""
        text = """
Timeout: 30 seconds
Port: 8080
Protocol: HTTPS
"""
        facts = parser.extract_from_text(
            text, source_doc_id="doc1", source_chunk_id="chunk1"
        )

        assert len(facts) >= 2
        attributes = {f.attribute_name for f in facts}
        assert "Timeout" in attributes or "Port" in attributes

    def test_extract_from_bullet_list(self, parser):
        """Test extraction depuis une liste à puces."""
        text = """
- Min RAM: 256GB
- Max connections: 1000
- Default port: 443
"""
        facts = parser.extract_from_text(
            text, source_doc_id="doc1", source_chunk_id="chunk1"
        )

        assert len(facts) >= 2

    def test_spec_type_detection_from_header(self, parser):
        """Test détection du SpecType depuis le header."""
        text = """
| Parameter | Minimum | Maximum |
|-----------|---------|---------|
| Memory    | 64GB    | 1TB     |
"""
        facts = parser.extract_from_text(
            text, source_doc_id="doc1", source_chunk_id="chunk1"
        )

        # Vérifier que les types sont correctement détectés
        types = {f.spec_type for f in facts}
        assert SpecType.MIN in types or SpecType.MAX in types

    def test_value_parsing_with_unit(self, parser):
        """Test parsing de valeur avec unité."""
        text = "Memory: 256GB"
        facts = parser.extract_from_text(
            text, source_doc_id="doc1", source_chunk_id="chunk1"
        )

        assert len(facts) >= 1
        fact = facts[0]
        assert fact.value_numeric == 256.0
        assert fact.unit == "GB"

    def test_no_extraction_from_plain_text(self, parser):
        """Test qu'on n'extrait pas du texte libre."""
        text = "The system needs about 256GB of RAM for optimal performance."
        facts = parser.extract_from_text(
            text, source_doc_id="doc1", source_chunk_id="chunk1"
        )

        # Pas de structure = pas de fact
        assert len(facts) == 0

    def test_fact_has_source_info(self, parser):
        """Test que les facts ont les infos de source."""
        text = "Port: 8080"
        facts = parser.extract_from_text(
            text,
            source_doc_id="doc123",
            source_chunk_id="chunk456",
            evidence_section="Configuration"
        )

        assert len(facts) >= 1
        fact = facts[0]
        assert fact.source_doc_id == "doc123"
        assert fact.source_chunk_id == "chunk456"


# =============================================================================
# Tests Convenience Function
# =============================================================================

class TestExtractSpecFactsConvenience:
    """Tests pour la fonction convenience."""

    def test_extract_spec_facts_function(self):
        """Test que la fonction convenience fonctionne."""
        text = "Timeout: 30s"
        facts = extract_spec_facts(text, "doc1", "chunk1")

        assert len(facts) >= 1


# =============================================================================
# Tests Deduplication Functions
# =============================================================================

class TestDeduplication:
    """Tests pour les fonctions de déduplication."""

    def test_normalize_for_dedup(self):
        """Test normalisation pour dédup."""
        assert normalize_for_dedup("HTTP Connections") == "http_connections"
        assert normalize_for_dedup("TLS 1.2+") == "tls_12"
        assert normalize_for_dedup("256GB") == "256gb"

    def test_dedup_key_rule_consistency(self):
        """Test que la clé de dédup est consistante."""
        rule = NormativeRule(
            rule_id="test1",
            subject_text="HTTP connections",
            modality=NormativeModality.MUST,
            constraint_type=ConstraintType.MIN,
            constraint_value="TLS 1.2",
            evidence_span="All HTTP connections must use TLS 1.2",
            source_doc_id="doc1",
            source_chunk_id="chunk1",
            extraction_method=ExtractionMethod.PATTERN,
            confidence=0.9,
        )

        key1 = dedup_key_rule(rule)
        key2 = dedup_key_rule(rule)
        assert key1 == key2

    def test_dedup_key_fact_consistency(self):
        """Test que la clé de dédup est consistante."""
        fact = SpecFact(
            fact_id="test1",
            attribute_name="RAM",
            spec_type=SpecType.MIN,
            value="256",
            unit="GB",
            source_structure=StructureType.TABLE,
            evidence_text="RAM: 256GB",
            source_doc_id="doc1",
            source_chunk_id="chunk1",
            extraction_method=ExtractionMethod.PATTERN,
            confidence=0.9,
        )

        key1 = dedup_key_fact(fact)
        key2 = dedup_key_fact(fact)
        assert key1 == key2


# =============================================================================
# Tests Invariants (INV-NORM-*)
# =============================================================================

class TestInvariants:
    """Tests pour les invariants ADR."""

    def test_inv_norm_01_evidence_required(self):
        """Test INV-NORM-01: Preuve locale obligatoire."""
        # NormativeRule doit avoir evidence_span
        with pytest.raises(Exception):  # pydantic validation
            NormativeRule(
                rule_id="test",
                subject_text="test",
                modality=NormativeModality.MUST,
                constraint_type=ConstraintType.EQUALS,
                constraint_value="value",
                # evidence_span manquant
                source_doc_id="doc1",
                source_chunk_id="chunk1",
                extraction_method=ExtractionMethod.PATTERN,
                confidence=0.9,
            )

    def test_inv_norm_03_structure_required_for_specfact(self):
        """Test INV-NORM-03: Structure explicite requise pour SpecFact."""
        # SpecFact doit avoir source_structure
        with pytest.raises(Exception):  # pydantic validation
            SpecFact(
                fact_id="test",
                attribute_name="RAM",
                spec_type=SpecType.VALUE,
                value="256GB",
                # source_structure manquant
                evidence_text="RAM: 256GB",
                source_doc_id="doc1",
                source_chunk_id="chunk1",
                extraction_method=ExtractionMethod.PATTERN,
                confidence=0.9,
            )

    def test_inv_agn_01_no_domain_specific_types(self):
        """Test INV-AGN-01: Pas de types domain-specific."""
        # Vérifier que tous les types sont domain-agnostic
        domain_terms = ["sap", "hana", "oracle", "medical", "car", "pharmaceutical"]

        for modality in NormativeModality:
            for term in domain_terms:
                assert term not in modality.value.lower(), \
                    f"Domain term '{term}' found in {modality}"

        for ctype in ConstraintType:
            for term in domain_terms:
                assert term not in ctype.value.lower(), \
                    f"Domain term '{term}' found in {ctype}"

        for stype in SpecType:
            for term in domain_terms:
                assert term not in stype.value.lower(), \
                    f"Domain term '{term}' found in {stype}"
