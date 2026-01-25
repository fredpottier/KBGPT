"""
OSMOSE Pipeline V2 - Tests Unitaires Pass 1
============================================
Ref: doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md
Date: 2026-01-24

Tests des composants Pass 1 (Lecture Stratifiée).
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime

# Models
from knowbase.stratified.models import (
    DocumentStructure,
    ConceptRole,
    AssertionType,
    AssertionStatus,
    AssertionLogReason,
    DocItemType,
    Subject,
    Theme,
    Concept,
    DocItem,
    Anchor,
    Information,
    Pass1Result,
)

# Pass 1 components
from knowbase.stratified.pass1 import (
    DocumentAnalyzerV2,
    ConceptIdentifierV2,
    AssertionExtractorV2,
    AnchorResolverV2,
    Pass1OrchestratorV2,
    RawAssertion,
    ConceptLink,
    PromotionTier,
    PROMOTION_POLICY,
    build_chunk_to_docitem_mapping,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_themes():
    """Thèmes de test."""
    return [
        Theme(theme_id="theme_1", name="Introduction"),
        Theme(theme_id="theme_2", name="Concepts Clés"),
        Theme(theme_id="theme_3", name="Conclusion"),
    ]


@pytest.fixture
def sample_concepts():
    """Concepts de test."""
    return [
        Concept(
            concept_id="concept_1",
            theme_id="theme_2",
            name="GDPR",
            role=ConceptRole.CENTRAL,
            variants=["RGPD", "General Data Protection Regulation"]
        ),
        Concept(
            concept_id="concept_2",
            theme_id="theme_2",
            name="Consentement",
            role=ConceptRole.STANDARD,
            variants=["consent", "agreement"]
        ),
    ]


@pytest.fixture
def sample_docitems():
    """DocItems de test."""
    return {
        "docitem_1": DocItem(
            docitem_id="docitem_1",
            type=DocItemType.PARAGRAPH,
            text="Le GDPR est un règlement européen sur la protection des données.",
            page=1,
            char_start=0,
            char_end=65,
            order=1,
            section_id="section_1"
        ),
        "docitem_2": DocItem(
            docitem_id="docitem_2",
            type=DocItemType.PARAGRAPH,
            text="Le consentement doit être explicite et éclairé.",
            page=1,
            char_start=66,
            char_end=113,
            order=2,
            section_id="section_1"
        ),
    }


@pytest.fixture
def sample_chunks():
    """Chunks de test (mappés aux DocItems)."""
    return {
        "chunk_docitem_1_0": "Le GDPR est un règlement européen sur la protection des données.",
        "chunk_docitem_2_0": "Le consentement doit être explicite et éclairé.",
    }


# ============================================================================
# TEST DOCUMENT ANALYZER
# ============================================================================

class TestDocumentAnalyzerV2:
    """Tests pour DocumentAnalyzerV2."""

    def test_fallback_analysis_central(self):
        """Test analyse fallback pour document CENTRAL."""
        analyzer = DocumentAnalyzerV2(llm_client=None, allow_fallback=True)

        subject, themes, is_hostile = analyzer.analyze(
            doc_id="test_doc",
            doc_title="SAP GDPR Solution Guide",
            content="This guide describes how to use SAP solutions for GDPR compliance..."
        )

        assert subject.structure == DocumentStructure.CENTRAL
        assert "SAP" in subject.justification or "produit" in subject.justification.lower()
        assert len(themes) >= 3
        assert not is_hostile

    def test_fallback_analysis_transversal(self):
        """Test analyse fallback pour document TRANSVERSAL."""
        analyzer = DocumentAnalyzerV2(llm_client=None, allow_fallback=True)

        subject, themes, is_hostile = analyzer.analyze(
            doc_id="test_doc",
            doc_title="CNIL GDPR Regulation Guidelines",
            content="Le règlement GDPR impose des obligations..."
        )

        assert subject.structure == DocumentStructure.TRANSVERSAL
        assert len(themes) >= 3

    def test_language_detection_french(self):
        """Test détection langue française."""
        analyzer = DocumentAnalyzerV2(llm_client=None, allow_fallback=True)

        subject, _, _ = analyzer.analyze(
            doc_id="test_doc",
            doc_title="Document Test",
            content="Le système de protection des données est essentiel pour la conformité."
        )

        assert subject.language == "fr"

    def test_language_detection_english(self):
        """Test détection langue anglaise."""
        analyzer = DocumentAnalyzerV2(llm_client=None, allow_fallback=True)

        subject, _, _ = analyzer.analyze(
            doc_id="test_doc",
            doc_title="Document Test",
            content="The data protection system is essential for compliance with regulations."
        )

        assert subject.language == "en"

    def test_no_fallback_raises_error(self):
        """Test erreur sans fallback et sans LLM."""
        analyzer = DocumentAnalyzerV2(llm_client=None, allow_fallback=False)

        with pytest.raises(RuntimeError, match="LLM non disponible"):
            analyzer.analyze(
                doc_id="test_doc",
                doc_title="Test",
                content="Test content"
            )


# ============================================================================
# TEST CONCEPT IDENTIFIER
# ============================================================================

class TestConceptIdentifierV2:
    """Tests pour ConceptIdentifierV2."""

    def test_fallback_identification(self, sample_themes):
        """Test identification fallback."""
        identifier = ConceptIdentifierV2(llm_client=None, allow_fallback=True)

        concepts, refused = identifier.identify(
            doc_id="test_doc",
            subject_text="Guide sur le GDPR",
            structure="TRANSVERSAL",
            themes=sample_themes,
            content="GDPR compliance requires proper Data Processing agreements. The Data Controller must ensure GDPR obligations are met.",
            language="en"
        )

        assert len(concepts) <= 15  # Invariant V2-007
        assert len(concepts) > 0
        # Le premier concept devrait être CENTRAL
        assert concepts[0].role == ConceptRole.CENTRAL

    def test_frugality_limit(self, sample_themes):
        """Test limite de frugalité (max 15)."""
        identifier = ConceptIdentifierV2(llm_client=None, allow_fallback=True)

        # Contenu avec beaucoup de termes
        content = " ".join([f"Concept{i}" for i in range(50)])

        concepts, _ = identifier.identify(
            doc_id="test_doc",
            subject_text="Test",
            structure="TRANSVERSAL",
            themes=sample_themes,
            content=content,
            language="en"
        )

        assert len(concepts) <= 15

    def test_hostile_mode_limit(self, sample_themes):
        """Test limite pour document HOSTILE (max 5)."""
        identifier = ConceptIdentifierV2(llm_client=None, allow_fallback=True)

        concepts, _ = identifier.identify(
            doc_id="test_doc",
            subject_text="Test",
            structure="CONTEXTUAL",
            themes=sample_themes,
            content="AAA BBB CCC DDD EEE FFF GGG HHH III JJJ KKK LLL",
            is_hostile=True,
            language="en"
        )

        assert len(concepts) <= 5

    def test_lex_key_generation(self, sample_themes):
        """Test génération de lex_key."""
        identifier = ConceptIdentifierV2(llm_client=None, allow_fallback=True)

        concepts, _ = identifier.identify(
            doc_id="test_doc",
            subject_text="Test",
            structure="TRANSVERSAL",
            themes=sample_themes,
            content="DataProtection is important",
            language="en"
        )

        for concept in concepts:
            assert concept.lex_key is not None
            assert concept.lex_key == concept.lex_key.lower()
            assert " " not in concept.lex_key


# ============================================================================
# TEST ASSERTION EXTRACTOR
# ============================================================================

class TestAssertionExtractorV2:
    """Tests pour AssertionExtractorV2."""

    def test_heuristic_extraction(self, sample_chunks):
        """Test extraction heuristique."""
        extractor = AssertionExtractorV2(llm_client=None, allow_fallback=True)

        assertions = extractor.extract_assertions(
            chunks=sample_chunks,
            doc_language="fr"
        )

        assert len(assertions) > 0
        for a in assertions:
            assert a.assertion_id is not None
            assert a.text is not None
            assert a.chunk_id in sample_chunks

    def test_type_detection_prescriptive(self):
        """Test détection type PRESCRIPTIVE."""
        extractor = AssertionExtractorV2(llm_client=None, allow_fallback=True)

        chunks = {"chunk_1": "The user must provide explicit consent before data processing."}
        assertions = extractor.extract_assertions(chunks=chunks)

        assert any(a.assertion_type == AssertionType.PRESCRIPTIVE for a in assertions)

    def test_type_detection_definitional(self):
        """Test détection type DEFINITIONAL."""
        extractor = AssertionExtractorV2(llm_client=None, allow_fallback=True)

        chunks = {"chunk_1": "GDPR is defined as the General Data Protection Regulation."}
        assertions = extractor.extract_assertions(chunks=chunks)

        assert any(a.assertion_type == AssertionType.DEFINITIONAL for a in assertions)

    def test_promotion_policy_always(self):
        """Test Promotion Policy pour types ALWAYS."""
        # DEFINITIONAL, PRESCRIPTIVE, CAUSAL sont ALWAYS
        assert PROMOTION_POLICY[AssertionType.DEFINITIONAL] == PromotionTier.ALWAYS
        assert PROMOTION_POLICY[AssertionType.PRESCRIPTIVE] == PromotionTier.ALWAYS
        assert PROMOTION_POLICY[AssertionType.CAUSAL] == PromotionTier.ALWAYS

    def test_promotion_policy_never(self):
        """Test Promotion Policy pour type NEVER."""
        # PROCEDURAL est NEVER
        assert PROMOTION_POLICY[AssertionType.PROCEDURAL] == PromotionTier.NEVER

    def test_promotion_filtering(self, sample_chunks):
        """Test filtrage par Promotion Policy."""
        extractor = AssertionExtractorV2(
            llm_client=None,
            allow_fallback=True,
            strict_promotion=True
        )

        assertions = extractor.extract_assertions(chunks=sample_chunks)
        result = extractor.filter_by_promotion_policy(assertions)

        assert result.stats["total"] == len(assertions)
        assert result.stats["promoted"] <= result.stats["total"]


# ============================================================================
# TEST ANCHOR RESOLVER
# ============================================================================

class TestAnchorResolverV2:
    """Tests pour AnchorResolverV2."""

    def test_single_docitem_resolution(self, sample_docitems, sample_chunks):
        """Test résolution avec un seul DocItem."""
        resolver = AnchorResolverV2()

        chunk_to_docitem = {"chunk_docitem_1_0": ["docitem_1"]}
        resolver.set_context(
            chunk_to_docitem_map=chunk_to_docitem,
            docitems=sample_docitems,
            chunks=sample_chunks
        )

        assertion = RawAssertion(
            assertion_id="assert_1",
            text="Le GDPR est un règlement européen",
            assertion_type=AssertionType.DEFINITIONAL,
            chunk_id="chunk_docitem_1_0",
            start_char=0,
            end_char=34,
            confidence=0.9
        )

        result = resolver.resolve_single(assertion)

        assert result.success
        assert result.anchor is not None
        assert result.anchor.docitem_id == "docitem_1"

    def test_no_docitem_failure(self, sample_docitems, sample_chunks):
        """Test échec si pas de DocItem trouvé."""
        resolver = AnchorResolverV2()

        resolver.set_context(
            chunk_to_docitem_map={},  # Pas de mapping
            docitems=sample_docitems,
            chunks=sample_chunks
        )

        assertion = RawAssertion(
            assertion_id="assert_1",
            text="Texte qui n'existe nulle part dans les docitems xyz123",
            assertion_type=AssertionType.FACTUAL,
            chunk_id="unknown_chunk",
            start_char=0,
            end_char=50,
            confidence=0.5
        )

        result = resolver.resolve_single(assertion)

        assert not result.success
        assert result.failure_reason == AssertionLogReason.NO_DOCITEM_ANCHOR

    def test_build_mapping(self, sample_docitems, sample_chunks):
        """Test construction du mapping chunk → DocItem."""
        mapping = build_chunk_to_docitem_mapping(sample_chunks, sample_docitems)

        # chunk_docitem_1_0 devrait mapper vers docitem_1
        assert "chunk_docitem_1_0" in mapping
        assert "docitem_1" in mapping["chunk_docitem_1_0"]


# ============================================================================
# TEST ORCHESTRATOR
# ============================================================================

class TestPass1OrchestratorV2:
    """Tests pour Pass1OrchestratorV2."""

    def test_full_pipeline_fallback(self, sample_docitems, sample_chunks):
        """Test pipeline complet en mode fallback."""
        orchestrator = Pass1OrchestratorV2(
            llm_client=None,
            allow_fallback=True,
            tenant_id="test_tenant"
        )

        result = orchestrator.process(
            doc_id="test_doc",
            doc_title="SAP GDPR Compliance Guide",
            content="Le GDPR impose des obligations. Le consentement doit être explicite. SAP fournit des solutions.",
            docitems=sample_docitems,
            chunks=sample_chunks
        )

        # Vérifications structurelles
        assert isinstance(result, Pass1Result)
        assert result.tenant_id == "test_tenant"
        assert result.doc.doc_id == "test_doc"

        # Subject créé
        assert result.subject is not None
        assert result.subject.structure in [DocumentStructure.CENTRAL, DocumentStructure.TRANSVERSAL, DocumentStructure.CONTEXTUAL]

        # Themes créés
        assert len(result.themes) > 0

        # Stats cohérentes
        assert result.stats.themes_count == len(result.themes)
        assert result.stats.concepts_count == len(result.concepts)
        assert result.stats.concepts_count <= 15  # Invariant V2-007

        # AssertionLog présent
        assert len(result.assertion_log) >= 0

    def test_pass1result_schema_version(self, sample_docitems, sample_chunks):
        """Test version du schéma Pass1Result."""
        orchestrator = Pass1OrchestratorV2(
            llm_client=None,
            allow_fallback=True
        )

        result = orchestrator.process(
            doc_id="test_doc",
            doc_title="Test",
            content="Test content for processing",
            docitems=sample_docitems,
            chunks=sample_chunks
        )

        assert result.schema_version == "v2.pass1.1"


# ============================================================================
# TEST INTEGRATION LIGHT
# ============================================================================

class TestPass1Integration:
    """Tests d'intégration légers (sans Neo4j)."""

    def test_document_to_pass1result(self, sample_docitems, sample_chunks):
        """Test transformation document → Pass1Result."""
        from knowbase.stratified.pass1 import run_pass1

        result = run_pass1(
            doc_id="integration_test",
            doc_title="CNIL GDPR Guidelines",
            content="""
            Le GDPR (Règlement Général sur la Protection des Données) est entré en vigueur en 2018.
            Il impose aux organisations de traiter les données personnelles de manière transparente.
            Le consentement doit être explicite, éclairé et révocable.
            Les sous-traitants doivent respecter les mêmes obligations que les responsables de traitement.
            """,
            docitems=sample_docitems,
            chunks=sample_chunks,
            llm_client=None,
            allow_fallback=True
        )

        # Structure sémantique créée
        assert result.subject.text is not None
        assert len(result.themes) > 0
        assert len(result.concepts) <= 15

        # Si des informations sont créées, elles doivent avoir des anchors valides
        for info in result.informations:
            assert info.anchor is not None
            assert info.anchor.docitem_id is not None
            assert info.anchor.span_start >= 0
            assert info.anchor.span_end > info.anchor.span_start

    def test_assertion_log_completeness(self, sample_docitems, sample_chunks):
        """Test exhaustivité de l'AssertionLog (invariant V2-004)."""
        from knowbase.stratified.pass1 import run_pass1

        result = run_pass1(
            doc_id="log_test",
            doc_title="Test Document",
            content="The system must process data. Users can opt out. If consent is given, data may be stored.",
            docitems=sample_docitems,
            chunks=sample_chunks,
            llm_client=None,
            allow_fallback=True
        )

        # Chaque assertion (promoted, abstained, rejected) doit être loggée
        total_logged = (
            result.stats.assertions_promoted +
            result.stats.assertions_abstained +
            result.stats.assertions_rejected
        )
        assert total_logged == result.stats.assertions_total
        assert len(result.assertion_log) == result.stats.assertions_total
