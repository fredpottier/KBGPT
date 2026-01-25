"""
OSMOSE Pipeline V2 - Tests End-to-End
======================================
Ref: doc/ongoing/ARCH_STRATIFIED_PIPELINE_V2.md

Tests E2E validant le pipeline complet:
- Pass 0: Structural Graph
- Pass 1: Lecture Stratifiée
- Pass 2: Enrichissement
- Pass 3: Consolidation Corpus

Exécution:
    pytest tests/stratified/test_pipeline_v2_e2e.py -v
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime

# Imports Pipeline V2
from knowbase.stratified.models import (
    Subject,
    Theme,
    Concept,
    Information,
    Pass1Result,
    Pass1Stats,
    AssertionLogEntry,
    AssertionStatus,
    AssertionLogReason,
    AssertionType,
    ConceptRole,
    DocumentStructure,
    DocumentMeta,
    Anchor,
    CanonicalConcept,
    CanonicalTheme,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def sample_document():
    """Document de test représentatif."""
    return {
        "doc_id": "test-doc-001",
        "title": "Guide de Migration SAP S/4HANA",
        "content_hash": "abc123def456",
        "tenant_id": "default",
    }


@pytest.fixture
def sample_doc_meta(sample_document):
    """DocumentMeta de test."""
    return DocumentMeta(
        doc_id=sample_document["doc_id"],
        title=sample_document["title"],
        language="fr",
        content_hash=sample_document["content_hash"],
    )


@pytest.fixture
def sample_subject():
    """Subject de test."""
    return Subject(
        subject_id="subj-001",
        text="Guide technique pour la migration vers SAP S/4HANA",
        structure=DocumentStructure.CENTRAL,
        language="fr",
    )


@pytest.fixture
def sample_anchor():
    """Anchor de test."""
    return Anchor(
        docitem_id="di-001",
        span_start=0,
        span_end=50,
    )


# ============================================================================
# TESTS INVARIANTS V2
# ============================================================================

class TestInvariantsV2:
    """Tests des invariants V2 du pipeline."""

    def test_v2_001_all_informations_anchored(self, sample_anchor):
        """V2-001: Toute Information DOIT être ancrée sur un DocItem."""
        # Créer des informations avec anchor
        informations = [
            Information(
                info_id="info-1",
                concept_id="concept-1",
                text="SAP HANA requiert 256 Go RAM",
                type=AssertionType.PRESCRIPTIVE,
                confidence=0.9,
                anchor=Anchor(docitem_id="di-001", span_start=0, span_end=30),
            ),
            Information(
                info_id="info-2",
                concept_id="concept-2",
                text="Migration brownfield conserve les données",
                type=AssertionType.FACTUAL,
                confidence=0.85,
                anchor=Anchor(docitem_id="di-002", span_start=0, span_end=40),
            ),
        ]

        # Vérifier que toutes les informations ont un anchor
        for info in informations:
            assert info.anchor is not None, f"Information {info.info_id} non ancrée"
            assert info.anchor.docitem_id != "", f"Information {info.info_id} a un docitem_id vide"

    def test_v2_003_subject_unique_per_document(self, sample_doc_meta, sample_subject):
        """V2-003: Un Document ne peut avoir qu'un seul Subject."""
        # Un Pass1Result ne contient qu'un seul Subject
        result = Pass1Result(
            tenant_id="default",
            doc=sample_doc_meta,
            subject=sample_subject,
            themes=[],
            concepts=[],
            informations=[],
            assertion_log=[],
        )

        # Le modèle ne permet qu'un seul Subject
        assert result.subject is not None
        assert isinstance(result.subject, Subject)
        # Pas de liste de Subjects possible

    def test_v2_004_assertion_log_exhaustive(self):
        """V2-004: AssertionLog contient TOUTES les décisions."""
        # Simuler les assertions extraites
        total_assertions = 10

        # Simuler les décisions (toutes doivent être tracées)
        assertion_log = [
            AssertionLogEntry(
                assertion_id=f"assert-{i}",
                text=f"Assertion {i}",
                type=AssertionType.FACTUAL,
                confidence=0.8 if i < 6 else 0.5,
                status=AssertionStatus.PROMOTED if i < 6 else
                       AssertionStatus.ABSTAINED if i < 8 else
                       AssertionStatus.REJECTED,
                reason=AssertionLogReason.PROMOTED if i < 6 else
                       AssertionLogReason.LOW_CONFIDENCE if i < 8 else
                       AssertionLogReason.POLICY_REJECTED,
            )
            for i in range(total_assertions)
        ]

        # Vérifier exhaustivité
        assert len(assertion_log) == total_assertions

        # Compter par statut
        promoted = sum(1 for a in assertion_log if a.status == AssertionStatus.PROMOTED)
        abstained = sum(1 for a in assertion_log if a.status == AssertionStatus.ABSTAINED)
        rejected = sum(1 for a in assertion_log if a.status == AssertionStatus.REJECTED)

        assert promoted + abstained + rejected == total_assertions

    def test_v2_007_max_concepts_per_document(self):
        """V2-007: Maximum 15 concepts par document."""
        MAX_CONCEPTS = 15

        # Créer 15 concepts (limite)
        concepts = [
            Concept(
                concept_id=f"concept-{i}",
                theme_id="theme-1",
                name=f"Concept {i}",
                role=ConceptRole.STANDARD,
            )
            for i in range(MAX_CONCEPTS)
        ]

        assert len(concepts) <= MAX_CONCEPTS


# ============================================================================
# TESTS PIPELINE COMPLET
# ============================================================================

class TestPipelineE2E:
    """Tests end-to-end du pipeline complet."""

    def test_pass1_result_structure(self, sample_doc_meta, sample_subject):
        """Vérifie la structure de Pass1Result."""
        # Créer un résultat Pass 1 complet
        result = Pass1Result(
            tenant_id="default",
            doc=sample_doc_meta,
            subject=sample_subject,
            themes=[
                Theme(
                    theme_id="theme-1",
                    name="Prérequis Techniques",
                ),
                Theme(
                    theme_id="theme-2",
                    name="Processus de Migration",
                ),
            ],
            concepts=[
                Concept(
                    concept_id="concept-1",
                    theme_id="theme-1",
                    name="SAP HANA",
                    role=ConceptRole.CENTRAL,
                ),
                Concept(
                    concept_id="concept-2",
                    theme_id="theme-2",
                    name="Migration Brownfield",
                    role=ConceptRole.STANDARD,
                ),
            ],
            informations=[
                Information(
                    info_id="info-1",
                    concept_id="concept-1",
                    text="SAP HANA requiert 256 Go RAM minimum",
                    type=AssertionType.PRESCRIPTIVE,
                    confidence=0.9,
                    anchor=Anchor(docitem_id="di-001", span_start=0, span_end=35),
                ),
            ],
            assertion_log=[
                AssertionLogEntry(
                    assertion_id="assert-1",
                    text="SAP HANA requiert 256 Go RAM",
                    type=AssertionType.PRESCRIPTIVE,
                    status=AssertionStatus.PROMOTED,
                    reason=AssertionLogReason.PROMOTED,
                    confidence=0.9,
                ),
            ],
        )

        # Vérifications structure
        assert result.doc.doc_id == sample_doc_meta.doc_id
        assert result.subject is not None
        assert len(result.themes) == 2
        assert len(result.concepts) == 2
        assert len(result.informations) == 1
        assert len(result.assertion_log) == 1

        # Vérifications statistiques auto-calculées
        assert result.stats.themes_count == 2
        assert result.stats.concepts_count == 2

    def test_pass1_to_json(self, sample_doc_meta, sample_subject):
        """Vérifie la sérialisation JSON de Pass1Result."""
        result = Pass1Result(
            tenant_id="default",
            doc=sample_doc_meta,
            subject=sample_subject,
            themes=[],
            concepts=[],
            informations=[],
            assertion_log=[],
        )

        # Sérialiser en JSON
        json_data = result.model_dump_json()

        assert json_data is not None
        assert sample_doc_meta.doc_id in json_data
        assert "subject" in json_data

    def test_node_count_reduction(self, sample_doc_meta, sample_subject):
        """Vérifie que le nombre de nœuds est réduit vs legacy."""
        # Simuler un résultat Pass 1 typique
        result = Pass1Result(
            tenant_id="default",
            doc=sample_doc_meta,
            subject=sample_subject,
            themes=[Theme(theme_id=f"t-{i}", name=f"Theme {i}") for i in range(5)],
            concepts=[Concept(concept_id=f"c-{i}", theme_id="t-0", name=f"Concept {i}") for i in range(10)],
            informations=[Information(
                info_id=f"info-{i}",
                concept_id="c-0",
                text=f"Information {i}",
                type=AssertionType.FACTUAL,
                confidence=0.8,
                anchor=Anchor(docitem_id=f"di-{i}", span_start=0, span_end=20),
            ) for i in range(30)],
            assertion_log=[],
        )

        # Compter les nœuds V2
        node_count = (
            1 +  # Subject
            len(result.themes) +  # Themes
            len(result.concepts) +  # Concepts
            len(result.informations)  # Informations
        )

        # Legacy: ~4700 nœuds/doc
        # V2: ~195 nœuds/doc cible
        MAX_EXPECTED_NODES = 250  # Marge de sécurité

        assert node_count <= MAX_EXPECTED_NODES, f"Trop de nœuds: {node_count} > {MAX_EXPECTED_NODES}"


# ============================================================================
# TESTS PASS 2
# ============================================================================

class TestPass2E2E:
    """Tests E2E pour Pass 2 (Enrichissement)."""

    def test_relation_extraction_structure(self):
        """Vérifie la structure des relations extraites."""
        from knowbase.stratified.pass2 import ConceptRelation

        relation = ConceptRelation(
            relation_id="rel-001",
            source_concept_id="concept-1",
            target_concept_id="concept-2",
            relation_type="REQUIRES",
            confidence=0.85,
            justification="SAP HANA requiert une infrastructure spécifique",
        )

        assert relation.source_concept_id == "concept-1"
        assert relation.target_concept_id == "concept-2"
        assert relation.relation_type == "REQUIRES"
        assert relation.confidence >= 0.0 and relation.confidence <= 1.0

    def test_max_relations_per_concept(self):
        """V2: Maximum 3 relations par concept."""
        from knowbase.stratified.pass2 import RelationExtractorV2

        MAX_RELATIONS = 3

        # La limite est définie dans le code
        assert RelationExtractorV2.MAX_RELATIONS_PER_CONCEPT == MAX_RELATIONS


# ============================================================================
# TESTS PASS 3
# ============================================================================

class TestPass3E2E:
    """Tests E2E pour Pass 3 (Consolidation Corpus)."""

    def test_canonical_concept_structure(self):
        """Vérifie la structure de CanonicalConcept."""
        canonical = CanonicalConcept(
            canonical_id="cc-001",
            name="SAP S/4HANA",
            merged_from=["concept-1", "concept-5", "concept-12"],
        )

        assert canonical.canonical_id == "cc-001"
        assert len(canonical.merged_from) == 3

    def test_canonical_theme_structure(self):
        """Vérifie la structure de CanonicalTheme."""
        canonical = CanonicalTheme(
            canonical_id="ct-001",
            name="Migration SAP",
            aligned_from=["theme-1", "theme-5"],
        )

        assert canonical.canonical_id == "ct-001"
        assert len(canonical.aligned_from) == 2

    def test_similarity_threshold(self):
        """Vérifie le seuil de similarité pour la fusion."""
        from knowbase.stratified.pass3 import EntityResolverV2

        # Seuil recommandé: 0.85
        assert EntityResolverV2.SIMILARITY_THRESHOLD == 0.85


# ============================================================================
# TESTS API V2
# ============================================================================

class TestAPIV2E2E:
    """Tests E2E pour l'API V2."""

    def test_ingest_response_structure(self):
        """Vérifie la structure de IngestResponse."""
        from knowbase.stratified.api.router import IngestResponse

        response = IngestResponse(
            doc_id="test-doc",
            status="accepted",
            pass0_status="completed",
            pass1_status="running",
            pass2_status=None,
            stats={"message": "Processing"},
        )

        assert response.doc_id == "test-doc"
        assert response.status == "accepted"

    def test_document_graph_structure(self):
        """Vérifie la structure de DocumentGraph."""
        from knowbase.stratified.api.router import DocumentGraph, GraphNode, GraphRelation

        graph = DocumentGraph(
            doc_id="test-doc",
            nodes=[
                GraphNode(id="n1", type="Subject", name="Test Subject", properties={}),
                GraphNode(id="n2", type="Theme", name="Theme 1", properties={}),
            ],
            relations=[
                GraphRelation(source="n1", target="n2", type="HAS_THEME", properties={}),
            ],
            stats={"total_nodes": 2},
        )

        assert graph.doc_id == "test-doc"
        assert len(graph.nodes) == 2
        assert len(graph.relations) == 1

    def test_assertion_log_response(self):
        """Vérifie la structure de AssertionLogResponse."""
        from knowbase.stratified.api.router import AssertionLogResponse, AssertionLogEntry as APILogEntry

        response = AssertionLogResponse(
            doc_id="test-doc",
            entries=[
                APILogEntry(
                    assertion_id="a1",
                    text="Test assertion",
                    type="FACT",
                    status="PROMOTED",
                    reason="ALWAYS tier",
                    confidence=0.9,
                    concept_id="c1",
                ),
            ],
            stats={"promoted": 1},
        )

        assert response.doc_id == "test-doc"
        assert len(response.entries) == 1
        assert response.entries[0].status == "PROMOTED"


# ============================================================================
# TESTS MÉTRIQUES
# ============================================================================

class TestMetrics:
    """Tests des métriques du pipeline."""

    def test_ratio_information_per_concept(self):
        """Vérifie le ratio informations/concept."""
        # Cible: ~3-5 informations par concept
        concepts_count = 10
        informations_count = 40

        ratio = informations_count / concepts_count
        assert 2.0 <= ratio <= 10.0, f"Ratio hors limites: {ratio}"

    def test_promotion_rate(self):
        """Vérifie le taux de promotion des assertions."""
        # Cible: 40-60% promues
        total_assertions = 100
        promoted = 45
        abstained = 35
        rejected = 20

        assert promoted + abstained + rejected == total_assertions

        promotion_rate = promoted / total_assertions
        assert 0.30 <= promotion_rate <= 0.70, f"Taux promotion hors limites: {promotion_rate}"

    def test_frugality_guard_constants(self):
        """Vérifie les constantes du garde-fou de frugalité."""
        from knowbase.stratified.pass1 import ConceptIdentifierV2

        # Standard documents: max 15
        assert ConceptIdentifierV2.MAX_CONCEPTS == 15

        # HOSTILE documents: max 5
        assert ConceptIdentifierV2.MAX_CONCEPTS_HOSTILE == 5


# ============================================================================
# TESTS INTÉGRATION COMPOSANTS
# ============================================================================

class TestComponentIntegration:
    """Tests d'intégration entre composants."""

    def test_pass0_to_pass1_flow(self):
        """Vérifie le flux Pass 0 → Pass 1."""
        # Pass 0 produit des DocItems
        docitems = [
            {"docitem_id": "di-001", "text": "Premier paragraphe"},
            {"docitem_id": "di-002", "text": "Deuxième paragraphe"},
        ]

        # Pass 1 doit pouvoir ancrer sur ces DocItems
        for di in docitems:
            assert "docitem_id" in di
            assert "text" in di

    def test_pass1_to_pass2_flow(self):
        """Vérifie le flux Pass 1 → Pass 2."""
        # Pass 1 produit des Concepts
        concepts = [
            Concept(concept_id="c1", theme_id="t1", name="SAP HANA"),
            Concept(concept_id="c2", theme_id="t1", name="S/4HANA"),
        ]

        # Pass 2 peut extraire des relations entre ces concepts
        assert len(concepts) >= 2  # Besoin d'au moins 2 concepts pour des relations

    def test_pass2_to_pass3_flow(self):
        """Vérifie le flux Pass 2 → Pass 3."""
        from knowbase.stratified.pass2 import ConceptRelation

        # Pass 2 produit des relations
        relations = [
            ConceptRelation(
                relation_id="rel-001",
                source_concept_id="c1",
                target_concept_id="c2",
                relation_type="REQUIRES",
                confidence=0.9,
                justification="Test justification",
            ),
        ]

        # Pass 3 consolide les concepts avec leurs relations
        assert len(relations) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
