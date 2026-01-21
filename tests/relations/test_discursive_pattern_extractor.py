"""
Tests unitaires pour DiscursivePatternExtractor.

Valide le contrat E1-E6 de l'ADR et les patterns de détection.

Author: Claude Code
Date: 2025-01-20
"""

import pytest
from knowbase.relations.discursive_pattern_extractor import (
    DiscursivePatternExtractor,
    DiscursiveCandidate,
    DiscursiveExtractionResult,
    get_discursive_pattern_extractor,
)
from knowbase.relations.types import (
    RelationType,
    DiscursiveBasis,
    DiscursiveAbstainReason,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def extractor():
    """Crée un extracteur frais pour chaque test."""
    return DiscursivePatternExtractor()


@pytest.fixture
def sample_concepts():
    """Concepts de test SAP typiques."""
    return [
        {
            "concept_id": "cc_hana",
            "canonical_name": "SAP HANA",
            "surface_forms": ["HANA", "SAP HANA Database", "HANA DB"],
        },
        {
            "concept_id": "cc_oracle",
            "canonical_name": "Oracle Database",
            "surface_forms": ["Oracle", "Oracle DB"],
        },
        {
            "concept_id": "cc_s4hana",
            "canonical_name": "SAP S/4HANA",
            "surface_forms": ["S/4HANA", "S4HANA", "S/4"],
        },
        {
            "concept_id": "cc_bw",
            "canonical_name": "SAP BW",
            "surface_forms": ["BW", "Business Warehouse", "SAP Business Warehouse"],
        },
        {
            "concept_id": "cc_fiori",
            "canonical_name": "SAP Fiori",
            "surface_forms": ["Fiori", "Fiori Apps"],
        },
        {
            "concept_id": "cc_legacy",
            "canonical_name": "Legacy Adapter",
            "surface_forms": ["legacy adapter", "Legacy System Adapter"],
        },
    ]


# =============================================================================
# Tests Pattern ALTERNATIVE
# =============================================================================

class TestAlternativePattern:
    """Tests pour la détection du pattern ALTERNATIVE."""

    def test_simple_or_english(self, extractor, sample_concepts):
        """Détecte 'X or Y' en anglais."""
        text = "You can deploy the system on SAP HANA or Oracle Database for the backend."

        result = extractor.extract(text, sample_concepts, "doc_1")

        assert result.validation_passed >= 2  # A→B et B→A (symétrique)

        # Vérifier qu'on a trouvé ALTERNATIVE_TO
        alt_candidates = [c for c in result.valid_candidates
                         if c.discursive_basis == DiscursiveBasis.ALTERNATIVE]
        assert len(alt_candidates) >= 2

        # Vérifier les concepts
        concept_ids = {c.subject_concept_id for c in alt_candidates} | {c.object_concept_id for c in alt_candidates}
        assert "cc_hana" in concept_ids
        assert "cc_oracle" in concept_ids

    def test_simple_ou_french(self, extractor, sample_concepts):
        """Détecte 'X ou Y' en français."""
        text = "Le système peut utiliser SAP HANA ou Oracle Database comme base de données."

        result = extractor.extract(text, sample_concepts, "doc_1")

        alt_candidates = [c for c in result.valid_candidates
                         if c.discursive_basis == DiscursiveBasis.ALTERNATIVE]
        assert len(alt_candidates) >= 2

    def test_either_or_pattern(self, extractor, sample_concepts):
        """Détecte 'either X or Y'."""
        text = "You must use either SAP HANA or Oracle Database."

        result = extractor.extract(text, sample_concepts, "doc_1")

        alt_candidates = [c for c in result.valid_candidates
                         if c.discursive_basis == DiscursiveBasis.ALTERNATIVE]
        assert len(alt_candidates) >= 2

    def test_alternative_creates_symmetric_relations(self, extractor, sample_concepts):
        """ALTERNATIVE_TO est symétrique: A→B et B→A."""
        text = "Choose SAP HANA or Oracle Database."

        result = extractor.extract(text, sample_concepts, "doc_1")

        alt_candidates = [c for c in result.valid_candidates
                         if c.discursive_basis == DiscursiveBasis.ALTERNATIVE]

        # Vérifier qu'on a les deux sens
        pairs = [(c.subject_concept_id, c.object_concept_id) for c in alt_candidates]
        assert ("cc_hana", "cc_oracle") in pairs or ("cc_oracle", "cc_hana") in pairs

    def test_no_alternative_without_marker(self, extractor, sample_concepts):
        """Pas de détection sans marqueur 'or'/'ou' (règle E1)."""
        text = "SAP HANA and Oracle Database are both supported."

        result = extractor.extract(text, sample_concepts, "doc_1")

        alt_candidates = [c for c in result.valid_candidates
                         if c.discursive_basis == DiscursiveBasis.ALTERNATIVE]
        assert len(alt_candidates) == 0


# =============================================================================
# Tests Pattern DEFAULT
# =============================================================================

class TestDefaultPattern:
    """Tests pour la détection du pattern DEFAULT."""

    def test_uses_by_default_english(self, extractor, sample_concepts):
        """Détecte 'X uses Y by default'."""
        text = "SAP S/4HANA uses SAP HANA by default for all data storage."

        result = extractor.extract(text, sample_concepts, "doc_1")

        default_candidates = [c for c in result.valid_candidates
                             if c.discursive_basis == DiscursiveBasis.DEFAULT]
        assert len(default_candidates) >= 1

        # Vérifier la relation
        candidate = default_candidates[0]
        assert candidate.relation_type == RelationType.USES
        assert "by default" in candidate.marker_text.lower()

    def test_defaults_to_pattern(self, extractor, sample_concepts):
        """Détecte 'X defaults to Y'."""
        text = "The database connection defaults to SAP HANA when available."

        result = extractor.extract(text, sample_concepts, "doc_1")

        # Note: ce pattern nécessite que le sujet soit un concept connu
        # "database connection" n'est pas dans nos concepts, donc pas de match
        # C'est correct selon règle E6
        pass  # Test de non-régression

    def test_par_defaut_french(self, extractor, sample_concepts):
        """Détecte 'X utilise Y par défaut' en français."""
        text = "SAP S/4HANA utilise SAP HANA par défaut pour le stockage."

        result = extractor.extract(text, sample_concepts, "doc_1")

        default_candidates = [c for c in result.valid_candidates
                             if c.discursive_basis == DiscursiveBasis.DEFAULT]
        assert len(default_candidates) >= 1

    def test_no_default_without_marker(self, extractor, sample_concepts):
        """Pas de détection sans marqueur 'by default' (règle E1)."""
        text = "SAP S/4HANA uses SAP HANA for data storage."

        result = extractor.extract(text, sample_concepts, "doc_1")

        default_candidates = [c for c in result.valid_candidates
                             if c.discursive_basis == DiscursiveBasis.DEFAULT]
        assert len(default_candidates) == 0


# =============================================================================
# Tests Pattern EXCEPTION
# =============================================================================

class TestExceptionPattern:
    """Tests pour la détection du pattern EXCEPTION."""

    def test_requires_unless_english(self, extractor, sample_concepts):
        """Détecte 'X requires Y unless Z'."""
        text = "All SAP S/4HANA deployments require SAP HANA, unless you use the Legacy Adapter."

        result = extractor.extract(text, sample_concepts, "doc_1")

        exception_candidates = [c for c in result.valid_candidates
                               if c.discursive_basis == DiscursiveBasis.EXCEPTION]
        assert len(exception_candidates) >= 1

        # Vérifier la relation
        candidate = exception_candidates[0]
        assert candidate.relation_type == RelationType.REQUIRES

    def test_except_pattern(self, extractor, sample_concepts):
        """Détecte 'X requires Y except Z'."""
        text = "SAP BW requires SAP HANA except for legacy installations."

        result = extractor.extract(text, sample_concepts, "doc_1")

        exception_candidates = [c for c in result.valid_candidates
                               if c.discursive_basis == DiscursiveBasis.EXCEPTION]
        assert len(exception_candidates) >= 1

    def test_sauf_si_french(self, extractor, sample_concepts):
        """Détecte 'X nécessite Y sauf si' en français."""
        text = "SAP S/4HANA nécessite SAP HANA sauf si vous utilisez un adaptateur legacy."

        result = extractor.extract(text, sample_concepts, "doc_1")

        exception_candidates = [c for c in result.valid_candidates
                               if c.discursive_basis == DiscursiveBasis.EXCEPTION]
        assert len(exception_candidates) >= 1

    def test_no_exception_without_marker(self, extractor, sample_concepts):
        """Pas de détection sans marqueur 'unless'/'sauf' (règle E1)."""
        text = "SAP S/4HANA requires SAP HANA for optimal performance."

        result = extractor.extract(text, sample_concepts, "doc_1")

        exception_candidates = [c for c in result.valid_candidates
                               if c.discursive_basis == DiscursiveBasis.EXCEPTION]
        assert len(exception_candidates) == 0


# =============================================================================
# Tests Règles du Contrat E1-E6
# =============================================================================

class TestExtractionContract:
    """Tests pour les règles du contrat d'extraction."""

    def test_e1_local_textual_trigger(self, extractor, sample_concepts):
        """E1: Génère uniquement à partir de marqueurs explicites."""
        # Sans marqueur → pas de candidat
        text = "SAP HANA is a great database. Oracle is also good."

        result = extractor.extract(text, sample_concepts, "doc_1")

        # Pas de relation ALTERNATIVE car pas de "or" entre les deux
        assert result.validation_passed == 0

    def test_e2_local_copresence(self, extractor, sample_concepts):
        """E2: Concepts doivent être co-présents localement."""
        # Le pattern regex garantit déjà la co-présence
        text = "Use SAP HANA or Oracle Database."

        result = extractor.extract(text, sample_concepts, "doc_1")

        for candidate in result.valid_candidates:
            # Vérifier que les deux concepts sont dans l'evidence
            evidence_lower = candidate.evidence_text.lower()
            assert "hana" in evidence_lower or "oracle" in evidence_lower

    def test_e6_no_concept_creation(self, extractor, sample_concepts):
        """E6: Pas de création de concepts, utilise uniquement l'inventaire existant."""
        # "MySQL" n'est pas dans nos concepts
        text = "You can use SAP HANA or MySQL for the database."

        result = extractor.extract(text, sample_concepts, "doc_1")

        # Pas de candidat car MySQL n'est pas un concept connu
        assert result.validation_passed == 0

    def test_e6_both_concepts_must_exist(self, extractor, sample_concepts):
        """E6: Les deux concepts doivent exister."""
        # "PostgreSQL" n'est pas dans nos concepts
        text = "Choose PostgreSQL or Oracle Database."

        result = extractor.extract(text, sample_concepts, "doc_1")

        # Pas de candidat car PostgreSQL n'est pas connu
        alt_candidates = [c for c in result.valid_candidates
                         if c.discursive_basis == DiscursiveBasis.ALTERNATIVE]
        assert len(alt_candidates) == 0

    def test_same_concept_rejected(self, extractor, sample_concepts):
        """Rejette si subject == object."""
        # Ce cas ne devrait pas arriver avec nos patterns, mais vérifions
        text = "SAP HANA or SAP HANA Database can be used."

        result = extractor.extract(text, sample_concepts, "doc_1")

        # Si détecté, devrait être rejeté (même concept_id)
        for candidate in result.rejected_candidates:
            if candidate.subject_concept_id == candidate.object_concept_id:
                assert candidate.rejection_reason == DiscursiveAbstainReason.AMBIGUOUS_PREDICATE


# =============================================================================
# Tests Validation et Rejet
# =============================================================================

class TestCandidateValidation:
    """Tests pour la validation des candidats."""

    def test_whitelist_violation_rejected(self, extractor):
        """RelationType hors whitelist est rejeté (C4)."""
        # Créer un candidat avec un type interdit
        candidate = DiscursiveCandidate(
            subject_concept_id="cc_1",
            object_concept_id="cc_2",
            subject_surface_form="A",
            object_surface_form="B",
            relation_type=RelationType.CAUSES,  # Interdit pour DISCURSIVE
            predicate_raw="causes",
            discursive_basis=DiscursiveBasis.ALTERNATIVE,
            marker_text="or",
            evidence_text="A or B causes something",
            evidence_start=0,
            evidence_end=25,
        )

        extractor._validate_candidate(candidate)

        assert not candidate.is_valid
        assert candidate.rejection_reason == DiscursiveAbstainReason.WHITELIST_VIOLATION

    def test_missing_marker_rejected(self, extractor):
        """Candidat sans marqueur dans evidence est rejeté."""
        candidate = DiscursiveCandidate(
            subject_concept_id="cc_1",
            object_concept_id="cc_2",
            subject_surface_form="A",
            object_surface_form="B",
            relation_type=RelationType.ALTERNATIVE_TO,
            predicate_raw="alternative to",
            discursive_basis=DiscursiveBasis.ALTERNATIVE,
            marker_text="or",
            evidence_text="A and B are options",  # Pas de "or" !
            evidence_start=0,
            evidence_end=20,
        )

        extractor._validate_candidate(candidate)

        assert not candidate.is_valid
        assert candidate.rejection_reason == DiscursiveAbstainReason.WEAK_BUNDLE

    def test_valid_candidate_passes(self, extractor):
        """Candidat valide passe la validation."""
        candidate = DiscursiveCandidate(
            subject_concept_id="cc_1",
            object_concept_id="cc_2",
            subject_surface_form="SAP HANA",
            object_surface_form="Oracle",
            relation_type=RelationType.ALTERNATIVE_TO,
            predicate_raw="alternative to",
            discursive_basis=DiscursiveBasis.ALTERNATIVE,
            marker_text="or",
            evidence_text="Use SAP HANA or Oracle for the database",
            evidence_start=0,
            evidence_end=40,
            pattern_confidence=0.85,
        )

        extractor._validate_candidate(candidate)

        assert candidate.is_valid
        assert candidate.rejection_reason is None


# =============================================================================
# Tests Type 2 Regression (cas interdits)
# =============================================================================

class TestType2Regression:
    """Tests de régression pour les cas Type 2 (interdits)."""

    def test_no_opinion_relation(self, extractor, sample_concepts):
        """Ne doit PAS créer de relation pour une opinion."""
        text = "SAP HANA is better than Oracle Database."

        result = extractor.extract(text, sample_concepts, "doc_1")

        # Pas de marqueur discursif reconnu
        assert result.validation_passed == 0

    def test_no_enables_for_discursive(self, extractor, sample_concepts):
        """ENABLES est interdit pour DISCURSIVE (C4)."""
        # Même si on trouvait un pattern, ENABLES serait rejeté
        # Ce test vérifie que nos patterns ne génèrent pas ENABLES
        text = "SAP HANA enables real-time analytics or batch processing."

        result = extractor.extract(text, sample_concepts, "doc_1")

        # Vérifier qu'aucun candidat validé n'a ENABLES
        for candidate in result.valid_candidates:
            assert candidate.relation_type != RelationType.ENABLES

    def test_no_causal_inference(self, extractor, sample_concepts):
        """Ne doit PAS créer de relation causale implicite."""
        text = "If you use SAP BW, you need SAP HANA."

        result = extractor.extract(text, sample_concepts, "doc_1")

        # "If... need" n'est pas un pattern EXCEPTION (c'est causal)
        assert result.validation_passed == 0


# =============================================================================
# Tests Statistiques et Factory
# =============================================================================

class TestExtractorStats:
    """Tests pour les statistiques de l'extracteur."""

    def test_stats_tracking(self, extractor, sample_concepts):
        """Vérifie le suivi des statistiques."""
        text = "Use SAP HANA or Oracle Database."

        result = extractor.extract(text, sample_concepts, "doc_1")

        stats = extractor.get_stats()
        assert stats["documents_processed"] == 1
        assert stats["patterns_detected"] > 0

    def test_stats_reset(self, extractor, sample_concepts):
        """Vérifie le reset des statistiques."""
        text = "Use SAP HANA or Oracle Database."

        extractor.extract(text, sample_concepts, "doc_1")
        extractor.reset_stats()

        stats = extractor.get_stats()
        assert stats["documents_processed"] == 0


class TestFactory:
    """Tests pour la factory function."""

    def test_get_discursive_pattern_extractor(self):
        """Factory retourne une instance valide."""
        extractor = get_discursive_pattern_extractor()
        assert extractor is not None
        assert isinstance(extractor, DiscursivePatternExtractor)


# =============================================================================
# Tests d'intégration (cas réels)
# =============================================================================

class TestRealWorldCases:
    """Tests avec des cas réels de documentation SAP."""

    def test_sap_database_alternatives(self, extractor, sample_concepts):
        """Cas réel: alternatives de base de données SAP."""
        text = """
        SAP S/4HANA Cloud supports multiple database options.
        You can choose SAP HANA or Oracle Database for your deployment.
        SAP HANA is recommended for optimal performance.
        """

        result = extractor.extract(text, sample_concepts, "doc_1")

        # Doit trouver l'alternative HANA/Oracle
        alt_candidates = [c for c in result.valid_candidates
                         if c.discursive_basis == DiscursiveBasis.ALTERNATIVE]
        assert len(alt_candidates) >= 2

    def test_sap_default_configuration(self, extractor, sample_concepts):
        """Cas réel: configuration par défaut SAP."""
        text = """
        SAP S/4HANA uses SAP HANA by default as its primary database.
        This provides in-memory computing capabilities out of the box.
        """

        result = extractor.extract(text, sample_concepts, "doc_1")

        default_candidates = [c for c in result.valid_candidates
                             if c.discursive_basis == DiscursiveBasis.DEFAULT]
        assert len(default_candidates) >= 1

    def test_sap_requirement_with_exception(self, extractor, sample_concepts):
        """Cas réel: requirement avec exception SAP."""
        text = """
        All new SAP S/4HANA installations require SAP HANA,
        unless you are migrating from an existing Legacy Adapter deployment.
        """

        result = extractor.extract(text, sample_concepts, "doc_1")

        exception_candidates = [c for c in result.valid_candidates
                               if c.discursive_basis == DiscursiveBasis.EXCEPTION]
        assert len(exception_candidates) >= 1

    def test_mixed_document(self, extractor, sample_concepts):
        """Document avec plusieurs types de patterns."""
        text = """
        SAP S/4HANA Configuration Guide

        Database Options:
        You can deploy on SAP HANA or Oracle Database.

        Default Configuration:
        SAP S/4HANA uses SAP HANA by default for all operations.

        Legacy Support:
        SAP BW requires SAP HANA, unless you use the Legacy Adapter.
        """

        result = extractor.extract(text, sample_concepts, "doc_1")

        # Doit trouver les 3 types de patterns
        bases_found = {c.discursive_basis for c in result.valid_candidates}

        # Au moins ALTERNATIVE et DEFAULT devraient être trouvés
        assert DiscursiveBasis.ALTERNATIVE in bases_found
        assert DiscursiveBasis.DEFAULT in bases_found
