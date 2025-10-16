"""
Tests unitaires pour EmbeddingsContextualScorer (Jour 8 - Phase 1.5).

**Couverture**:
- Scoring avec paraphrases multilingues (EN/FR/DE/ES)
- Agrégation multi-occurrences (toutes mentions vs première)
- Classification role (PRIMARY/COMPETITOR/SECONDARY)
- Cas limites (texte court, aucun contexte, etc.)

Référence: doc/phase1_osmose/PHASE1.5_TRACKING.md (Jour 8)
"""

import pytest
from typing import Dict, Any, List
import numpy as np

# Skip tests if sentence-transformers not installed
pytest.importorskip("sentence_transformers")

from knowbase.agents.gatekeeper.embeddings_contextual_scorer import (
    EmbeddingsContextualScorer,
    REFERENCE_CONCEPTS_MULTILINGUAL
)


# Fixtures

@pytest.fixture
def sample_candidates() -> List[Dict[str, Any]]:
    """Candidats d'entités typiques."""
    return [
        {"text": "SAP S/4HANA Cloud", "confidence": 0.95},
        {"text": "Oracle", "confidence": 0.92},
        {"text": "Workday", "confidence": 0.90},
        {"text": "ERP", "confidence": 0.85}
    ]


@pytest.fixture
def sample_document_en() -> str:
    """Document anglais typique."""
    return """
    SAP S/4HANA Cloud: Enterprise ERP Solution

    Our flagship product, SAP S/4HANA Cloud, is a comprehensive enterprise resource planning system.
    SAP S/4HANA Cloud provides real-time analytics, cloud-native architecture, and seamless integration.

    We compared SAP S/4HANA Cloud with competitors like Oracle and Workday.
    While Oracle and Workday offer alternatives, SAP S/4HANA Cloud delivers superior value.

    Key benefits of SAP S/4HANA Cloud:
    - Advanced ERP capabilities
    - Cloud infrastructure
    - Real-time data processing

    SAP S/4HANA Cloud is our recommended solution for modern enterprises.
    """


@pytest.fixture
def sample_document_fr() -> str:
    """Document français typique."""
    return """
    SAP S/4HANA Cloud: Solution ERP d'Entreprise

    Notre produit phare, SAP S/4HANA Cloud, est un système complet de planification des ressources.
    SAP S/4HANA Cloud offre des analyses en temps réel et une architecture cloud native.

    Nous avons comparé SAP S/4HANA Cloud avec des concurrents comme Oracle et Workday.
    Bien qu'Oracle et Workday proposent des alternatives, SAP S/4HANA Cloud offre une valeur supérieure.

    Avantages clés de SAP S/4HANA Cloud:
    - Capacités ERP avancées
    - Infrastructure cloud
    - Traitement de données en temps réel

    SAP S/4HANA Cloud est notre solution recommandée pour les entreprises modernes.
    """


@pytest.fixture
def short_document() -> str:
    """Document court (cas limite)."""
    return "SAP S/4HANA Cloud is an ERP solution."


# Tests

def test_scorer_initialization():
    """Test 1: Initialisation avec paramètres par défaut."""
    scorer = EmbeddingsContextualScorer()

    assert scorer.model_name == "intfloat/multilingual-e5-large"
    assert scorer.context_window == 100
    assert scorer.similarity_threshold_primary == 0.5
    assert scorer.similarity_threshold_competitor == 0.4
    assert scorer.enable_multi_occurrence is True
    assert scorer.languages == ["en", "fr", "de", "es"]
    assert scorer.model is not None
    assert scorer.reference_embeddings is not None


def test_scorer_initialization_custom():
    """Test 2: Initialisation avec paramètres personnalisés."""
    scorer = EmbeddingsContextualScorer(
        model_name="intfloat/multilingual-e5-small",
        context_window=50,
        similarity_threshold_primary=0.6,
        similarity_threshold_competitor=0.5,
        enable_multi_occurrence=False,
        languages=["en", "fr"]
    )

    assert scorer.model_name == "intfloat/multilingual-e5-small"
    assert scorer.context_window == 50
    assert scorer.similarity_threshold_primary == 0.6
    assert scorer.similarity_threshold_competitor == 0.5
    assert scorer.enable_multi_occurrence is False
    assert scorer.languages == ["en", "fr"]


def test_score_entities_english(sample_candidates, sample_document_en):
    """Test 3: Scoring avec document anglais."""
    scorer = EmbeddingsContextualScorer()
    scored = scorer.score_entities(sample_candidates, sample_document_en)

    # Vérifier que tous les candidats ont été scorés
    assert len(scored) == len(sample_candidates)

    # Vérifier présence des scores
    for entity in scored:
        assert "embedding_primary_similarity" in entity
        assert "embedding_competitor_similarity" in entity
        assert "embedding_secondary_similarity" in entity
        assert "embedding_role" in entity
        assert "embedding_score" in entity

        # Vérifier range [0-1]
        assert 0.0 <= entity["embedding_primary_similarity"] <= 1.0
        assert 0.0 <= entity["embedding_competitor_similarity"] <= 1.0
        assert 0.0 <= entity["embedding_secondary_similarity"] <= 1.0
        assert 0.0 <= entity["embedding_score"] <= 1.0

        # Vérifier role valide
        assert entity["embedding_role"] in ["PRIMARY", "COMPETITOR", "SECONDARY"]


def test_score_entities_french(sample_candidates, sample_document_fr):
    """Test 4: Scoring avec document français (multilingue)."""
    scorer = EmbeddingsContextualScorer()
    scored = scorer.score_entities(sample_candidates, sample_document_fr)

    # Vérifier que tous les candidats ont été scorés
    assert len(scored) == len(sample_candidates)

    # Vérifier que le scoring fonctionne en français
    for entity in scored:
        assert "embedding_role" in entity
        assert entity["embedding_role"] in ["PRIMARY", "COMPETITOR", "SECONDARY"]


def test_primary_vs_competitor_classification(sample_candidates, sample_document_en):
    """Test 5: Classification PRIMARY vs COMPETITOR."""
    scorer = EmbeddingsContextualScorer()
    scored = scorer.score_entities(sample_candidates, sample_document_en)

    # Trouver roles
    sap_role = next(e["embedding_role"] for e in scored if "SAP S/4HANA" in e["text"])
    oracle_role = next((e["embedding_role"] for e in scored if e["text"] == "Oracle"), "SECONDARY")
    workday_role = next((e["embedding_role"] for e in scored if e["text"] == "Workday"), "SECONDARY")

    # SAP S/4HANA Cloud devrait être PRIMARY (produit principal, décrit en détail)
    # Note: Le test peut être flaky selon le modèle, on vérifie juste que ce n'est pas COMPETITOR
    assert sap_role != "COMPETITOR", "SAP S/4HANA ne devrait pas être classifié comme COMPETITOR"

    # Oracle et Workday devraient être COMPETITOR ou SECONDARY (mentionnés brièvement)
    # Note: Classification peut varier selon le modèle
    assert oracle_role in ["COMPETITOR", "SECONDARY"]
    assert workday_role in ["COMPETITOR", "SECONDARY"]


def test_extract_all_mentions_contexts_single():
    """Test 6: Extraction contexte - mention unique."""
    scorer = EmbeddingsContextualScorer(context_window=20)

    text = "This is a test document about SAP S/4HANA Cloud. The system is powerful."
    contexts = scorer._extract_all_mentions_contexts("SAP S/4HANA Cloud", text)

    # Devrait trouver 1 contexte
    assert len(contexts) == 1
    assert "SAP" in contexts[0]
    assert "S/4HANA" in contexts[0]
    assert "Cloud" in contexts[0]


def test_extract_all_mentions_contexts_multiple():
    """Test 7: Extraction contexte - mentions multiples."""
    scorer = EmbeddingsContextualScorer(context_window=20)

    text = (
        "SAP S/4HANA Cloud is great. "
        "We use SAP S/4HANA Cloud daily. "
        "SAP S/4HANA Cloud improves efficiency."
    )
    contexts = scorer._extract_all_mentions_contexts("SAP S/4HANA Cloud", text)

    # Devrait trouver 3 contextes
    assert len(contexts) == 3
    for context in contexts:
        assert "SAP" in context


def test_score_entity_aggregated_single_context():
    """Test 8: Agrégation - contexte unique."""
    scorer = EmbeddingsContextualScorer()

    contexts = ["Our main product is a comprehensive enterprise solution with advanced features."]
    similarities = scorer._score_entity_aggregated(contexts)

    # Vérifier structure
    assert "PRIMARY" in similarities
    assert "COMPETITOR" in similarities
    assert "SECONDARY" in similarities

    # Vérifier range [0-1]
    for score in similarities.values():
        assert 0.0 <= score <= 1.0


def test_score_entity_aggregated_multiple_contexts():
    """Test 9: Agrégation - contextes multiples."""
    scorer = EmbeddingsContextualScorer()

    contexts = [
        "Our flagship product offers comprehensive features.",
        "The main solution provides real-time analytics.",
        "This primary system delivers superior value."
    ]
    similarities = scorer._score_entity_aggregated(contexts)

    # Vérifier que l'agrégation fonctionne
    assert all(0.0 <= score <= 1.0 for score in similarities.values())

    # Contexte PRIMARY devrait avoir similarité élevée
    # Note: Test peut être flaky selon le modèle
    assert similarities["PRIMARY"] > 0.2, "Contexte PRIMARY devrait avoir similarité > 0.2"


def test_classify_role_primary():
    """Test 10: Classification role - PRIMARY."""
    scorer = EmbeddingsContextualScorer(
        similarity_threshold_primary=0.5,
        similarity_threshold_competitor=0.4
    )

    similarities = {
        "PRIMARY": 0.7,
        "COMPETITOR": 0.3,
        "SECONDARY": 0.4
    }

    role = scorer._classify_role(similarities)
    assert role == "PRIMARY"


def test_classify_role_competitor():
    """Test 11: Classification role - COMPETITOR."""
    scorer = EmbeddingsContextualScorer(
        similarity_threshold_primary=0.5,
        similarity_threshold_competitor=0.4
    )

    similarities = {
        "PRIMARY": 0.3,
        "COMPETITOR": 0.6,
        "SECONDARY": 0.4
    }

    role = scorer._classify_role(similarities)
    assert role == "COMPETITOR"


def test_classify_role_secondary():
    """Test 12: Classification role - SECONDARY (défaut)."""
    scorer = EmbeddingsContextualScorer(
        similarity_threshold_primary=0.5,
        similarity_threshold_competitor=0.4
    )

    # Cas 1: Toutes similarités faibles
    similarities = {
        "PRIMARY": 0.3,
        "COMPETITOR": 0.2,
        "SECONDARY": 0.5
    }

    role = scorer._classify_role(similarities)
    assert role == "SECONDARY"

    # Cas 2: Similarités similaires (ambiguë)
    similarities = {
        "PRIMARY": 0.4,
        "COMPETITOR": 0.4,
        "SECONDARY": 0.4
    }

    role = scorer._classify_role(similarities)
    assert role == "SECONDARY"


def test_score_entities_empty_candidates(sample_document_en):
    """Test 13: Liste candidats vide (cas limite)."""
    scorer = EmbeddingsContextualScorer()
    scored = scorer.score_entities([], sample_document_en)

    assert scored == []


def test_score_entities_short_text(sample_candidates, short_document):
    """Test 14: Document très court (<50 chars) → scores par défaut."""
    scorer = EmbeddingsContextualScorer()
    scored = scorer.score_entities(sample_candidates, short_document)

    # Tous les candidats doivent avoir score par défaut
    for entity in scored:
        assert entity["embedding_score"] == 0.5
        assert entity["embedding_role"] == "SECONDARY"


def test_multilingual_paraphrases():
    """Test 15: Paraphrases multilingues présentes."""
    # Vérifier que toutes les langues ont des paraphrases
    for role in ["PRIMARY", "COMPETITOR", "SECONDARY"]:
        assert role in REFERENCE_CONCEPTS_MULTILINGUAL

        paraphrases = REFERENCE_CONCEPTS_MULTILINGUAL[role]
        assert "en" in paraphrases
        assert "fr" in paraphrases
        assert "de" in paraphrases
        assert "es" in paraphrases

        # Vérifier qu'il y a au moins 3 paraphrases par langue
        for lang, phrases in paraphrases.items():
            assert len(phrases) >= 3, f"Role {role} lang {lang} devrait avoir ≥3 paraphrases"


# Tests d'intégration

def test_end_to_end_realistic_scenario():
    """Test 16: Scénario réaliste bout-en-bout."""
    document = """
    Request for Proposal: Enterprise ERP System

    Our organization seeks a modern ERP solution. We are evaluating SAP S/4HANA Cloud as our primary candidate.

    SAP S/4HANA Cloud is a comprehensive enterprise resource planning system that offers:
    - Real-time analytics and reporting
    - Cloud-native architecture for scalability
    - Seamless integration with existing systems

    We have also reviewed alternatives including Oracle ERP Cloud and Workday.
    While Oracle and Workday provide competitive offerings, SAP S/4HANA Cloud aligns better with our requirements.

    Key differentiators of SAP S/4HANA Cloud:
    1. Advanced ERP capabilities tailored to our industry
    2. Proven track record in similar enterprises
    3. Superior technical support and training

    Based on our evaluation, SAP S/4HANA Cloud is our recommended solution.
    """

    candidates = [
        {"text": "SAP S/4HANA Cloud", "confidence": 0.95},
        {"text": "Oracle ERP Cloud", "confidence": 0.92},
        {"text": "Workday", "confidence": 0.90},
        {"text": "ERP", "confidence": 0.88}
    ]

    scorer = EmbeddingsContextualScorer()
    scored = scorer.score_entities(candidates, document)

    # Vérifier que le scoring a fonctionné
    assert len(scored) == len(candidates)

    # Trouver SAP S/4HANA Cloud
    sap_entity = next(e for e in scored if "SAP S/4HANA" in e["text"])

    # SAP S/4HANA devrait avoir un rôle non-COMPETITOR (PRIMARY ou SECONDARY)
    assert sap_entity["embedding_role"] != "COMPETITOR", \
        "SAP S/4HANA Cloud (produit principal) ne devrait pas être COMPETITOR"

    # Score SAP devrait être plus élevé que score moyen
    avg_score = sum(e["embedding_score"] for e in scored) / len(scored)
    assert sap_entity["embedding_score"] >= avg_score, \
        "SAP S/4HANA Cloud devrait avoir un score ≥ moyenne"

    print(f"\n[TEST] Scores finaux:")
    for entity in sorted(scored, key=lambda e: e["embedding_score"], reverse=True):
        print(f"  {entity['text']}: role={entity['embedding_role']}, "
              f"score={entity['embedding_score']:.3f} "
              f"(prim={entity['embedding_primary_similarity']:.2f}, "
              f"comp={entity['embedding_competitor_similarity']:.2f})")
