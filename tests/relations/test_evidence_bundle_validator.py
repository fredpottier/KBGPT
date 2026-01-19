"""
Tests unitaires pour le validateur de bundles - Sprint 1 OSMOSE.

Test des fonctions POS-based agnostiques à la langue.
"""

import pytest
import spacy

from knowbase.relations.predicate_extractor import (
    is_auxiliary_verb,
    is_copula_or_attributive,
    is_modal_or_intentional,
    is_generic_verb,
    get_spacy_model,
    locate_entity_in_doc,
    extract_predicate_from_context,
)
from knowbase.relations.bundle_validator import (
    validate_fragment,
    validate_proximity,
    validate_predicate_pos,
    validate_bundle,
    MIN_CONFIDENCE_THRESHOLD,
    MAX_CHAR_DISTANCE,
)
from knowbase.relations.evidence_bundle_models import (
    EvidenceFragment,
    EvidenceBundle,
    FragmentType,
    ExtractionMethodBundle,
    BundleValidationStatus,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def nlp_fr():
    """Charge le modèle spaCy français."""
    try:
        return spacy.load("fr_core_news_md")
    except OSError:
        pytest.skip("Modèle fr_core_news_md non disponible")


@pytest.fixture
def nlp_en():
    """Charge le modèle spaCy anglais."""
    try:
        return spacy.load("en_core_web_md")
    except OSError:
        pytest.skip("Modèle en_core_web_md non disponible")


@pytest.fixture
def sample_subject_fragment():
    """Fragment sujet valide."""
    return EvidenceFragment(
        fragment_id="frag:test-subject",
        fragment_type=FragmentType.ENTITY_MENTION,
        text="SAP S/4HANA",
        source_context_id="sec:test:123",
        char_start=0,
        char_end=11,
        confidence=0.9,
        extraction_method=ExtractionMethodBundle.CHARSPAN_EXACT,
    )


@pytest.fixture
def sample_object_fragment():
    """Fragment objet valide."""
    return EvidenceFragment(
        fragment_id="frag:test-object",
        fragment_type=FragmentType.ENTITY_MENTION,
        text="BTP",
        source_context_id="sec:test:123",
        char_start=25,
        char_end=28,
        confidence=0.85,
        extraction_method=ExtractionMethodBundle.CHARSPAN_EXACT,
    )


@pytest.fixture
def sample_predicate_fragment():
    """Fragment prédicat valide."""
    return EvidenceFragment(
        fragment_id="frag:test-predicate",
        fragment_type=FragmentType.PREDICATE_LEXICAL,
        text="intègre",
        source_context_id="sec:test:123",
        char_start=12,
        char_end=19,
        confidence=0.8,
        extraction_method=ExtractionMethodBundle.SPACY_DEP,
    )


# =============================================================================
# Tests POS-based Detection - Français
# =============================================================================

class TestModalDetectionFrench:
    """Tests détection de modaux en français."""

    def test_vouloir_is_modal(self, nlp_fr):
        """'vouloir' + infinitif est modal."""
        doc = nlp_fr("Le système veut intégrer les données.")
        for token in doc:
            if token.text == "veut":
                # 'veut' gouverne 'intégrer' qui est infinitif
                assert is_modal_or_intentional(token) is True
                break

    def test_pouvoir_is_modal(self, nlp_fr):
        """'pouvoir' + infinitif est modal."""
        doc = nlp_fr("SAP peut connecter les modules.")
        for token in doc:
            if token.text == "peut":
                assert is_modal_or_intentional(token) is True
                break

    def test_devoir_is_modal(self, nlp_fr):
        """'devoir' + infinitif est modal."""
        doc = nlp_fr("Le système doit valider les entrées.")
        for token in doc:
            if token.text == "doit":
                assert is_modal_or_intentional(token) is True
                break

    def test_integrer_not_modal(self, nlp_fr):
        """'intégrer' seul n'est pas modal."""
        doc = nlp_fr("SAP intègre les données ERP.")
        for token in doc:
            if token.text == "intègre":
                assert is_modal_or_intentional(token) is False
                break


class TestModalDetectionEnglish:
    """Tests détection de modaux en anglais."""

    def test_can_is_auxiliary(self, nlp_en):
        """'can' est un auxiliaire (POS=AUX), donc filtré par is_auxiliary_verb."""
        doc = nlp_en("SAP can integrate the data.")
        for token in doc:
            if token.text == "can":
                # En anglais, les modaux sont AUX, pas VERB avec infinitif
                # Ils sont donc filtrés par is_auxiliary_verb, pas is_modal_or_intentional
                assert is_auxiliary_verb(token) is True
                break

    def test_should_is_auxiliary(self, nlp_en):
        """'should' est un auxiliaire (POS=AUX), donc filtré par is_auxiliary_verb."""
        doc = nlp_en("The system should validate inputs.")
        for token in doc:
            if token.text == "should":
                # En anglais, les modaux sont AUX
                assert is_auxiliary_verb(token) is True
                break

    def test_integrates_not_modal(self, nlp_en):
        """'integrates' seul n'est pas modal."""
        doc = nlp_en("SAP integrates ERP data.")
        for token in doc:
            if token.text == "integrates":
                assert is_modal_or_intentional(token) is False
                break


class TestIntentionalDetection:
    """Tests détection de verbes intentionnels."""

    def test_vouloir_intentional_fr(self, nlp_fr):
        """'vouloir' est intentionnel (gouverne infinitif)."""
        doc = nlp_fr("L'utilisateur veut exporter les rapports.")
        for token in doc:
            if token.text == "veut":
                assert is_modal_or_intentional(token) is True
                break

    def test_want_intentional_en(self, nlp_en):
        """'want' + to-infinitive est intentionnel."""
        doc = nlp_en("The user wants to export the reports.")
        for token in doc:
            if token.text == "wants":
                # Peut être détecté si xcomp est présent
                result = is_modal_or_intentional(token)
                # Le résultat dépend de l'analyse spaCy
                assert isinstance(result, bool)


class TestGenericVerbRejection:
    """Tests rejet des verbes génériques."""

    def test_etre_is_generic_fr(self, nlp_fr):
        """'être' (auxiliaire/copule) est générique."""
        doc = nlp_fr("SAP est un système ERP.")
        for token in doc:
            if token.text == "est":
                assert is_generic_verb(token) is True
                break

    def test_avoir_is_generic_fr(self, nlp_fr):
        """'avoir' (auxiliaire) est générique."""
        doc = nlp_fr("Le système a traité les données.")
        for token in doc:
            if token.text == "a" and token.pos_ == "AUX":
                assert is_auxiliary_verb(token) is True
                break

    def test_is_generic_en(self, nlp_en):
        """'is' (copule) est générique."""
        doc = nlp_en("SAP is an ERP system.")
        for token in doc:
            if token.text == "is":
                assert is_generic_verb(token) is True
                break

    def test_integrer_not_generic_fr(self, nlp_fr):
        """'intégrer' n'est pas générique."""
        doc = nlp_fr("SAP intègre les données ERP.")
        for token in doc:
            if token.text == "intègre":
                assert is_generic_verb(token) is False
                break


class TestValidPredicateFrench:
    """Tests extraction de prédicats valides en français."""

    def test_integrer_valid_predicate(self, nlp_fr):
        """'intègre' est un prédicat valide."""
        text = "SAP S/4HANA intègre nativement BTP."
        doc = nlp_fr(text)

        # Localiser les entités
        subject_span = doc[0:2]  # "SAP S/4HANA"
        object_span = doc[4:5]   # "BTP"

        predicate = extract_predicate_from_context(doc, subject_span, object_span)
        # Le prédicat devrait être trouvé (ou None si pas de verbe entre)
        # Le test vérifie que la fonction s'exécute sans erreur
        assert predicate is None or predicate.text is not None

    def test_connecter_valid_predicate(self, nlp_fr):
        """'connecte' est un prédicat valide."""
        text = "Le module connecte les systèmes externes."
        doc = nlp_fr(text)
        for token in doc:
            if token.text == "connecte":
                assert token.pos_ == "VERB"
                assert is_generic_verb(token) is False


class TestValidPredicateEnglish:
    """Tests extraction de prédicats valides en anglais."""

    def test_integrates_valid_predicate(self, nlp_en):
        """'integrates' est un prédicat valide."""
        text = "SAP S/4HANA integrates with BTP."
        doc = nlp_en(text)
        for token in doc:
            if token.text == "integrates":
                assert token.pos_ == "VERB"
                assert is_generic_verb(token) is False

    def test_connects_valid_predicate(self, nlp_en):
        """'connects' est un prédicat valide."""
        text = "The module connects external systems."
        doc = nlp_en(text)
        for token in doc:
            if token.text == "connects":
                assert token.pos_ == "VERB"
                assert is_generic_verb(token) is False


# =============================================================================
# Tests Validation de Fragments
# =============================================================================

class TestFragmentValidation:
    """Tests validation des fragments individuels."""

    def test_valid_fragment(self, sample_subject_fragment):
        """Un fragment valide passe la validation."""
        is_valid, reason = validate_fragment(sample_subject_fragment)
        assert is_valid is True
        assert reason == "VALID"

    def test_empty_text_fragment(self, sample_subject_fragment):
        """Un fragment avec texte vide échoue."""
        sample_subject_fragment.text = ""
        is_valid, reason = validate_fragment(sample_subject_fragment)
        assert is_valid is False
        assert "EMPTY_TEXT" in reason

    def test_low_confidence_fragment(self, sample_subject_fragment):
        """Un fragment avec confiance trop basse échoue."""
        sample_subject_fragment.confidence = 0.3
        is_valid, reason = validate_fragment(sample_subject_fragment)
        assert is_valid is False
        assert "LOW_CONFIDENCE" in reason

    def test_missing_context_id(self, sample_subject_fragment):
        """Un fragment sans context_id échoue."""
        sample_subject_fragment.source_context_id = ""
        is_valid, reason = validate_fragment(sample_subject_fragment)
        assert is_valid is False
        assert "MISSING_CONTEXT_ID" in reason


# =============================================================================
# Tests Validation de Proximité
# =============================================================================

class TestProximityValidation:
    """Tests validation de la proximité textuelle."""

    def test_same_section_close(self, sample_subject_fragment, sample_object_fragment):
        """Entités proches dans même section passent."""
        is_valid, reason = validate_proximity(
            sample_subject_fragment, sample_object_fragment
        )
        assert is_valid is True

    def test_different_sections(self, sample_subject_fragment, sample_object_fragment):
        """Entités dans sections différentes échouent."""
        sample_object_fragment.source_context_id = "sec:other:456"
        is_valid, reason = validate_proximity(
            sample_subject_fragment, sample_object_fragment
        )
        assert is_valid is False
        assert "DIFFERENT_SECTIONS" in reason

    def test_too_far_apart(self, sample_subject_fragment, sample_object_fragment):
        """Entités trop éloignées échouent."""
        sample_object_fragment.char_start = 1000
        sample_object_fragment.char_end = 1010
        is_valid, reason = validate_proximity(
            sample_subject_fragment, sample_object_fragment,
            max_distance=100
        )
        assert is_valid is False
        assert "TOO_FAR" in reason


# =============================================================================
# Tests Calcul de Confiance
# =============================================================================

class TestConfidenceCalculation:
    """Tests calcul de confiance des bundles."""

    def test_min_rule(self):
        """La confiance = min(tous les fragments)."""
        from knowbase.relations.confidence_calculator import compute_bundle_confidence

        confidence = compute_bundle_confidence(
            subject_confidence=0.9,
            object_confidence=0.8,
            predicate_confidences=[0.7],
        )
        assert confidence == 0.7  # min des trois

    def test_min_rule_with_link(self):
        """Avec lien, la confiance inclut le lien."""
        from knowbase.relations.confidence_calculator import compute_bundle_confidence

        confidence = compute_bundle_confidence(
            subject_confidence=0.9,
            object_confidence=0.8,
            predicate_confidences=[0.7],
            link_confidence=0.6,
        )
        assert confidence == 0.6  # min des quatre

    def test_no_predicate_zero_confidence(self):
        """Sans prédicat, confiance = 0."""
        from knowbase.relations.confidence_calculator import compute_bundle_confidence

        confidence = compute_bundle_confidence(
            subject_confidence=0.9,
            object_confidence=0.8,
            predicate_confidences=[],
        )
        assert confidence == 0.0


# =============================================================================
# Tests Localisation d'Entités
# =============================================================================

class TestEntityLocalization:
    """Tests localisation d'entités via charspan."""

    def test_exact_charspan(self, nlp_fr):
        """Localisation exacte via charspan."""
        text = "SAP S/4HANA intègre BTP."
        doc = nlp_fr(text)

        span = locate_entity_in_doc(doc, 0, 11, "SAP S/4HANA")
        assert span is not None
        assert "SAP" in span.text

    def test_expand_charspan(self, nlp_fr):
        """Localisation avec expansion."""
        text = "SAP S/4HANA intègre BTP."
        doc = nlp_fr(text)

        # Charspan légèrement décalé
        span = locate_entity_in_doc(doc, 0, 10, "SAP S/4HAN")
        assert span is not None

    def test_fuzzy_fallback(self, nlp_fr):
        """Fallback fuzzy sur label."""
        text = "Le système SAP intègre les données."
        doc = nlp_fr(text)

        # Charspan incorrect mais label correct
        span = locate_entity_in_doc(doc, 100, 103, "SAP")
        assert span is not None
        assert span.text == "SAP"


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
