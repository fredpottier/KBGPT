"""
Tests unitaires pour GraphCentralityScorer (Jour 7 - Phase 1.5).

**Couverture**:
- Scoring entités avec TF-IDF, Centrality, Salience
- Co-occurrence graph construction
- Fenêtre adaptive selon taille document
- Cas limites (graphe vide, texte court, etc.)

Référence: doc/phase1_osmose/PHASE1.5_TRACKING.md (Jour 7)
"""

import pytest
from typing import Dict, Any, List
import networkx as nx

from knowbase.agents.gatekeeper.graph_centrality_scorer import GraphCentralityScorer


# Fixtures

@pytest.fixture
def sample_candidates() -> List[Dict[str, Any]]:
    """Candidats d'entités typiques."""
    return [
        {"text": "SAP S/4HANA Cloud", "confidence": 0.95},
        {"text": "Oracle", "confidence": 0.92},
        {"text": "Workday", "confidence": 0.90},
        {"text": "ERP", "confidence": 0.85},
        {"text": "Cloud", "confidence": 0.80}
    ]


@pytest.fixture
def sample_document() -> str:
    """Document typique avec contexte."""
    return """
    SAP S/4HANA Cloud: The Future of ERP

    Our solution, SAP S/4HANA Cloud, is a comprehensive ERP system designed for modern enterprises.
    SAP S/4HANA Cloud leverages cloud infrastructure to provide scalability and flexibility.

    Unlike competitors such as Oracle and Workday, SAP S/4HANA Cloud offers deep integration
    with existing SAP landscapes. Oracle and Workday are mentioned here for comparison purposes only.

    Key benefits of SAP S/4HANA Cloud:
    - Real-time analytics with ERP integration
    - Cloud-native architecture
    - Seamless migration from on-premise SAP systems

    SAP S/4HANA Cloud is the ideal choice for organizations seeking a modern ERP platform.
    """


@pytest.fixture
def short_document() -> str:
    """Document court (cas limite)."""
    return "SAP S/4HANA Cloud is an ERP solution."


@pytest.fixture
def empty_candidates() -> List[Dict[str, Any]]:
    """Liste vide (cas limite)."""
    return []


# Tests

def test_scorer_initialization():
    """Test 1: Initialisation avec paramètres par défaut."""
    scorer = GraphCentralityScorer()

    assert scorer.min_centrality == 0.15
    assert scorer.enable_tf_idf is True
    assert scorer.enable_salience is True
    assert "pagerank" in scorer.centrality_weights
    assert "degree" in scorer.centrality_weights
    assert "betweenness" in scorer.centrality_weights


def test_scorer_initialization_custom():
    """Test 2: Initialisation avec paramètres personnalisés."""
    custom_weights = {"pagerank": 0.6, "degree": 0.3, "betweenness": 0.1}
    scorer = GraphCentralityScorer(
        min_centrality=0.2,
        centrality_weights=custom_weights,
        enable_tf_idf=False,
        enable_salience=True
    )

    assert scorer.min_centrality == 0.2
    assert scorer.enable_tf_idf is False
    assert scorer.enable_salience is True
    assert scorer.centrality_weights == custom_weights


def test_score_entities_basic(sample_candidates, sample_document):
    """Test 3: Scoring basique avec document typique."""
    scorer = GraphCentralityScorer()
    scored = scorer.score_entities(sample_candidates, sample_document)

    # Vérifier que tous les candidats ont été scorés
    assert len(scored) == len(sample_candidates)

    # Vérifier présence des scores
    for entity in scored:
        assert "tf_idf_score" in entity
        assert "centrality_score" in entity
        assert "salience_score" in entity
        assert "graph_score" in entity

        # Vérifier range [0-1]
        assert 0.0 <= entity["tf_idf_score"] <= 1.0
        assert 0.0 <= entity["centrality_score"] <= 1.0
        assert 0.0 <= entity["salience_score"] <= 1.0
        assert 0.0 <= entity["graph_score"] <= 1.0


def test_score_entities_primary_vs_competitor(sample_candidates, sample_document):
    """Test 4: Distinguer produit principal (SAP S/4HANA Cloud) des concurrents (Oracle, Workday)."""
    scorer = GraphCentralityScorer()
    scored = scorer.score_entities(sample_candidates, sample_document)

    # Trouver scores
    sap_score = next(e["graph_score"] for e in scored if "SAP S/4HANA" in e["text"])
    oracle_score = next(e["graph_score"] for e in scored if e["text"] == "Oracle")
    workday_score = next(e["graph_score"] for e in scored if e["text"] == "Workday")

    # SAP S/4HANA Cloud doit avoir un score significativement plus élevé
    # (mentionné 5x, dans titre, central dans le document)
    assert sap_score > oracle_score, "SAP S/4HANA devrait scorer plus haut qu'Oracle"
    assert sap_score > workday_score, "SAP S/4HANA devrait scorer plus haut que Workday"

    # Oracle et Workday mentionnés ensemble 2x → scores similaires
    assert abs(oracle_score - workday_score) < 0.15, "Oracle et Workday devraient avoir des scores proches"


def test_score_entities_empty_candidates(sample_document):
    """Test 5: Liste de candidats vide (cas limite)."""
    scorer = GraphCentralityScorer()
    scored = scorer.score_entities([], sample_document)

    assert scored == []


def test_score_entities_short_text(sample_candidates, short_document):
    """Test 6: Document très court (<50 chars) → scores neutres."""
    scorer = GraphCentralityScorer()
    scored = scorer.score_entities(sample_candidates, short_document)

    # Tous les candidats doivent avoir un score par défaut (0.5)
    for entity in scored:
        assert entity["graph_score"] == 0.5, "Texte court devrait produire score neutre"


def test_build_cooccurrence_graph_basic(sample_candidates, sample_document):
    """Test 7: Construction du graphe de co-occurrence."""
    scorer = GraphCentralityScorer()
    graph = scorer._build_cooccurrence_graph(sample_candidates, sample_document)

    # Vérifier que le graphe contient les nœuds (normalisés)
    nodes = list(graph.nodes())
    assert len(nodes) > 0

    # Vérifier que des edges existent (co-occurrences détectées)
    assert graph.number_of_edges() > 0, "Des co-occurrences devraient être détectées"

    # Vérifier que "sap s/4hana cloud" et "erp" sont connectés (apparaissent ensemble)
    assert graph.has_node("sap s/4hana cloud") or graph.has_node("sap")
    assert graph.has_node("erp")


def test_calculate_tf_idf_basic(sample_candidates, sample_document):
    """Test 8: Calcul TF-IDF basique."""
    scorer = GraphCentralityScorer()
    tf_idf_scores = scorer._calculate_tf_idf(sample_candidates, sample_document)

    # Vérifier que des scores ont été calculés
    assert len(tf_idf_scores) > 0

    # Vérifier range [0-1]
    for score in tf_idf_scores.values():
        assert 0.0 <= score <= 1.0

    # Termes fréquents (SAP S/4HANA, ERP) devraient avoir scores élevés
    # Termes rares (Oracle, Workday) devraient avoir scores plus faibles
    # NOTE: TF-IDF favorise les termes spécifiques fréquents


def test_calculate_centrality_basic(sample_candidates, sample_document):
    """Test 9: Calcul centralité (PageRank, Degree, Betweenness)."""
    scorer = GraphCentralityScorer()
    graph = scorer._build_cooccurrence_graph(sample_candidates, sample_document)
    centrality_scores = scorer._calculate_centrality(graph)

    # Vérifier que des scores ont été calculés
    assert len(centrality_scores) > 0

    # Vérifier range [0-1]
    for score in centrality_scores.values():
        assert 0.0 <= score <= 1.0


def test_calculate_salience_basic(sample_candidates, sample_document):
    """Test 10: Calcul salience (position + fréquence)."""
    scorer = GraphCentralityScorer()
    salience_scores = scorer._calculate_salience(sample_candidates, sample_document)

    # Vérifier que des scores ont été calculés
    assert len(salience_scores) > 0

    # Vérifier range [0-1]
    for score in salience_scores.values():
        assert 0.0 <= score <= 1.0

    # SAP S/4HANA dans le titre → salience élevée
    sap_salience = salience_scores.get("sap s/4hana cloud", 0.0)
    assert sap_salience > 0.7, "Entité dans le titre devrait avoir salience élevée"


def test_adaptive_window_size():
    """Test 11: Fenêtre adaptive selon taille document."""
    scorer = GraphCentralityScorer()

    # Document court (<1000 chars) → window=30
    assert scorer._get_adaptive_window_size(500) == 30

    # Document moyen (<5000 chars) → window=50
    assert scorer._get_adaptive_window_size(3000) == 50

    # Document long (<20000 chars) → window=75
    assert scorer._get_adaptive_window_size(10000) == 75

    # Document très long (>20000 chars) → window=100
    assert scorer._get_adaptive_window_size(50000) == 100


def test_score_entities_without_tf_idf(sample_candidates, sample_document):
    """Test 12: Scoring sans TF-IDF (désactivé)."""
    scorer = GraphCentralityScorer(enable_tf_idf=False)
    scored = scorer.score_entities(sample_candidates, sample_document)

    # Vérifier que les scores TF-IDF sont absents ou neutres
    for entity in scored:
        # TF-IDF désactivé → devrait être 0.5 (défaut neutre)
        assert entity.get("tf_idf_score", 0.5) == 0.5


def test_score_entities_without_salience(sample_candidates, sample_document):
    """Test 13: Scoring sans salience (désactivé)."""
    scorer = GraphCentralityScorer(enable_salience=False)
    scored = scorer.score_entities(sample_candidates, sample_document)

    # Vérifier que les scores salience sont absents ou neutres
    for entity in scored:
        # Salience désactivé → devrait être 0.5 (défaut neutre)
        assert entity.get("salience_score", 0.5) == 0.5


# Tests d'intégration

def test_end_to_end_scoring_realistic():
    """Test 14: Scénario réaliste bout-en-bout."""
    # Document RFP réaliste
    document = """
    Request for Proposal: Enterprise ERP System

    Our organization seeks a modern ERP solution to replace our legacy systems.
    We are evaluating SAP S/4HANA Cloud as our primary candidate.

    SAP S/4HANA Cloud offers comprehensive ERP capabilities including:
    - Financial management
    - Supply chain optimization
    - Human capital management

    We have also considered alternatives such as Oracle ERP Cloud and Workday,
    but SAP S/4HANA Cloud aligns better with our existing SAP landscape.

    Key requirements:
    1. Cloud-native architecture (SAP S/4HANA Cloud meets this)
    2. Real-time analytics (SAP S/4HANA Cloud provides this)
    3. Seamless integration with SAP BTP

    SAP S/4HANA Cloud is our recommended solution for this ERP transformation.
    """

    candidates = [
        {"text": "SAP S/4HANA Cloud", "confidence": 0.95},
        {"text": "Oracle ERP Cloud", "confidence": 0.92},
        {"text": "Workday", "confidence": 0.90},
        {"text": "ERP", "confidence": 0.88},
        {"text": "SAP BTP", "confidence": 0.85}
    ]

    scorer = GraphCentralityScorer(min_centrality=0.15)
    scored = scorer.score_entities(candidates, document)

    # Vérifier hiérarchie attendue
    sap_s4_score = next(e["graph_score"] for e in scored if "SAP S/4HANA" in e["text"])
    oracle_score = next(e["graph_score"] for e in scored if "Oracle" in e["text"])
    workday_score = next(e["graph_score"] for e in scored if e["text"] == "Workday")
    erp_score = next(e["graph_score"] for e in scored if e["text"] == "ERP")

    # Assertions hiérarchie
    assert sap_s4_score > oracle_score, "SAP S/4HANA (primary) > Oracle (competitor)"
    assert sap_s4_score > workday_score, "SAP S/4HANA (primary) > Workday (competitor)"
    assert sap_s4_score > 0.6, "SAP S/4HANA devrait avoir un score élevé (>0.6)"

    # ERP est un terme générique mais fréquent → score moyen
    assert 0.3 < erp_score < 0.8

    print(f"\n[TEST] Scores finaux:")
    for entity in sorted(scored, key=lambda e: e["graph_score"], reverse=True):
        print(f"  {entity['text']}: {entity['graph_score']:.3f} "
              f"(tfidf={entity['tf_idf_score']:.2f}, "
              f"cent={entity['centrality_score']:.2f}, "
              f"sal={entity['salience_score']:.2f})")
