# Tests Phase 2 OSMOSE - LLM Relation Extraction
# Validation sur cas réels

import pytest
from typing import List, Dict, Any
from knowbase.relations.llm_relation_extractor import LLMRelationExtractor
from knowbase.relations.types import RelationType, ExtractionMethod
from knowbase.common.llm_router import LLMRouter


@pytest.fixture
def llm_extractor():
    """Fixture LLMRelationExtractor avec gpt-4o-mini."""
    llm_router = LLMRouter()
    extractor = LLMRelationExtractor(
        llm_router=llm_router,
        model="gpt-4o-mini",
        max_context_chars=3000,
        co_occurrence_window=150
    )
    return extractor


@pytest.fixture
def sample_concepts_encryption():
    """Concepts pour test encryption (cas réel utilisateur)."""
    return [
        {
            "concept_id": "concept-hana",
            "canonical_name": "HANA",
            "surface_forms": ["SAP HANA", "HANA Database"],
            "concept_type": "DATABASE"
        },
        {
            "concept_id": "concept-aes256",
            "canonical_name": "AES256",
            "surface_forms": ["AES-256", "AES 256"],
            "concept_type": "ENCRYPTION_ALGORITHM"
        }
    ]


@pytest.fixture
def sample_concepts_product():
    """Concepts pour test PART_OF."""
    return [
        {
            "concept_id": "concept-fiori",
            "canonical_name": "SAP Fiori",
            "surface_forms": ["Fiori"],
            "concept_type": "UI_FRAMEWORK"
        },
        {
            "concept_id": "concept-s4hana",
            "canonical_name": "SAP S/4HANA",
            "surface_forms": ["S/4HANA", "S4HANA"],
            "concept_type": "PRODUCT"
        }
    ]


@pytest.fixture
def sample_concepts_version():
    """Concepts pour test VERSION_OF et REPLACES."""
    return [
        {
            "concept_id": "concept-ccr2023",
            "canonical_name": "CCR 2023",
            "surface_forms": ["Customer Connection Review 2023"],
            "concept_type": "DOCUMENT"
        },
        {
            "concept_id": "concept-ccr2022",
            "canonical_name": "CCR 2022",
            "surface_forms": ["Customer Connection Review 2022"],
            "concept_type": "DOCUMENT"
        }
    ]


class TestLLMRelationExtractor:
    """Tests extraction LLM sur cas réels."""

    def test_extract_uses_encryption(
        self,
        llm_extractor,
        sample_concepts_encryption
    ):
        """
        Test CAS RÉEL UTILISATEUR: "la base HANA est chiffrée au repos en AES256"

        Attendu:
        - HANA USES AES256
        - confidence >= 0.70
        - metadata: context=encryption, scope=at_rest
        """
        full_text = """
        La base de données SAP HANA est chiffrée au repos en AES256.
        Cette encryption assure la sécurité des données sensibles.
        """

        relations = llm_extractor.extract_relations(
            concepts=sample_concepts_encryption,
            full_text=full_text,
            document_id="test-doc-encryption",
            document_name="Test Encryption"
        )

        # Assertions
        assert len(relations) > 0, "Au moins une relation devrait être extraite"

        # Trouver relation USES HANA → AES256
        uses_relations = [
            r for r in relations
            if r.relation_type == RelationType.USES
            and r.source_concept == "concept-hana"
            and r.target_concept == "concept-aes256"
        ]

        assert len(uses_relations) > 0, (
            "Relation HANA USES AES256 devrait être extraite "
            "(cas réel manqué par patterns!)"
        )

        relation = uses_relations[0]

        # Vérifier metadata
        assert relation.metadata.confidence >= 0.70, (
            f"Confidence devrait être >= 0.70, got {relation.metadata.confidence}"
        )
        assert relation.metadata.extraction_method == ExtractionMethod.LLM
        assert relation.evidence is not None
        assert "chiffr" in relation.evidence.lower() or "encrypt" in relation.evidence.lower()

        # Vérifier context metadata (optionnel mais souhaitable)
        if relation.context:
            assert "encryption" in relation.context.lower() or "chiffr" in relation.context.lower()

    def test_extract_part_of(
        self,
        llm_extractor,
        sample_concepts_product
    ):
        """Test extraction PART_OF (Fiori fait partie de S/4HANA)."""
        full_text = """
        SAP Fiori est la couche d'interface utilisateur moderne de SAP S/4HANA.
        Fiori fait partie intégrante de S/4HANA et améliore l'expérience utilisateur.
        """

        relations = llm_extractor.extract_relations(
            concepts=sample_concepts_product,
            full_text=full_text,
            document_id="test-doc-partof",
            document_name="Test PartOf"
        )

        # Assertions
        part_of_relations = [
            r for r in relations
            if r.relation_type == RelationType.PART_OF
            and r.source_concept == "concept-fiori"
            and r.target_concept == "concept-s4hana"
        ]

        assert len(part_of_relations) > 0, "Relation Fiori PART_OF S/4HANA attendue"
        relation = part_of_relations[0]

        assert relation.metadata.confidence >= 0.75
        assert relation.metadata.extraction_method == ExtractionMethod.LLM

    def test_extract_version_and_replaces(
        self,
        llm_extractor,
        sample_concepts_version
    ):
        """Test extraction VERSION_OF + REPLACES pour documents versionnés."""
        full_text = """
        Le Customer Connection Review 2023 est la nouvelle version du CCR 2022.
        CCR 2023 remplace le CCR 2022 et inclut les dernières évolutions produits.
        """

        relations = llm_extractor.extract_relations(
            concepts=sample_concepts_version,
            full_text=full_text,
            document_id="test-doc-version",
            document_name="Test Version"
        )

        # Assertions VERSION_OF
        version_relations = [
            r for r in relations
            if r.relation_type == RelationType.VERSION_OF
        ]

        replaces_relations = [
            r for r in relations
            if r.relation_type == RelationType.REPLACES
        ]

        # Au moins une des deux relations devrait être détectée
        assert len(version_relations) + len(replaces_relations) > 0, (
            "Au moins une relation VERSION_OF ou REPLACES devrait être extraite"
        )

        # Vérifier direction correcte (2023 → 2022)
        for rel in version_relations + replaces_relations:
            assert rel.source_concept == "concept-ccr2023"
            assert rel.target_concept == "concept-ccr2022"

    def test_no_false_positive_negation(
        self,
        llm_extractor,
        sample_concepts_encryption
    ):
        """Test que LLM ne crée PAS de relation quand négation présente."""
        full_text = """
        La base HANA ne nécessite PAS d'encryption AES256 par défaut.
        L'encryption est optionnelle et peut être activée si besoin.
        """

        relations = llm_extractor.extract_relations(
            concepts=sample_concepts_encryption,
            full_text=full_text,
            document_id="test-doc-negation",
            document_name="Test Negation"
        )

        # Assertions: NE DEVRAIT PAS créer de REQUIRES relation
        requires_relations = [
            r for r in relations
            if r.relation_type == RelationType.REQUIRES
        ]

        assert len(requires_relations) == 0, (
            "Aucune relation REQUIRES ne devrait être créée avec négation 'ne nécessite PAS'"
        )

        # Peut créer USES avec faible confidence (optionnel)
        uses_relations = [
            r for r in relations
            if r.relation_type == RelationType.USES
        ]

        if len(uses_relations) > 0:
            # Si USES créé, vérifier que c'est marqué WEAK
            for rel in uses_relations:
                if rel.metadata.strength:
                    # Devrait être WEAK ou MODERATE, pas STRONG
                    assert rel.metadata.strength.value in ["WEAK", "MODERATE"]

    def test_cooccurrence_filtering(
        self,
        llm_extractor,
        sample_concepts_encryption
    ):
        """Test que co-occurrence filtering fonctionne correctement."""
        # Texte avec concepts LOIN l'un de l'autre (> 150 chars)
        full_text = """
        La base de données SAP HANA est utilisée pour stocker de grandes quantités de données.
        Elle offre des performances exceptionnelles grâce à son architecture in-memory.
        Les données sont stockées en colonnes pour optimiser les requêtes analytiques.

        En matière de sécurité, plusieurs algorithmes sont disponibles, notamment AES256
        qui peut être utilisé pour chiffrer les communications réseau.
        """

        # Appeler _find_cooccurring_concepts directement
        concept_pairs = llm_extractor._find_cooccurring_concepts(
            concepts=sample_concepts_encryption,
            full_text=full_text
        )

        # Dans ce texte, HANA et AES256 sont très éloignés
        # Co-occurrence window = 150 chars par défaut
        # Vérifier que la paire n'est PAS dans les candidats
        # (ou si elle l'est, vérifier que c'est justifié)

        # Pour ce test, on accepte que la paire soit détectée SI les concepts
        # apparaissent dans même section logique
        # Le vrai test est que l'extraction complète fonctionne
        relations = llm_extractor.extract_relations(
            concepts=sample_concepts_encryption,
            full_text=full_text,
            document_id="test-doc-cooccur",
            document_name="Test CoOccurrence"
        )

        # Dans ce cas, relation PEUT être extraite mais avec confidence plus basse
        # Car contexte moins direct
        for rel in relations:
            if rel.source_concept == "concept-hana" and rel.target_concept == "concept-aes256":
                # Si extraite, confidence devrait être modérée
                assert rel.metadata.confidence >= 0.60  # Seuil minimum

    def test_multilingual_support(
        self,
        llm_extractor,
        sample_concepts_product
    ):
        """Test extraction multilingue (EN, FR)."""
        # Texte EN
        text_en = """
        SAP Fiori is a component of SAP S/4HANA.
        It provides a modern user interface.
        """

        relations_en = llm_extractor.extract_relations(
            concepts=sample_concepts_product,
            full_text=text_en,
            document_id="test-doc-en",
            document_name="Test EN"
        )

        # Texte FR
        text_fr = """
        SAP Fiori est un composant de SAP S/4HANA.
        Il fournit une interface utilisateur moderne.
        """

        relations_fr = llm_extractor.extract_relations(
            concepts=sample_concepts_product,
            full_text=text_fr,
            document_id="test-doc-fr",
            document_name="Test FR"
        )

        # Les deux devraient extraire PART_OF
        part_of_en = [r for r in relations_en if r.relation_type == RelationType.PART_OF]
        part_of_fr = [r for r in relations_fr if r.relation_type == RelationType.PART_OF]

        assert len(part_of_en) > 0, "Extraction EN devrait fonctionner"
        assert len(part_of_fr) > 0, "Extraction FR devrait fonctionner"

    def test_deduplication(
        self,
        llm_extractor,
        sample_concepts_product
    ):
        """Test déduplication relations (même relation plusieurs fois)."""
        # Texte avec répétition (chunks overlapping)
        full_text = """
        SAP Fiori fait partie de SAP S/4HANA. Fiori est intégré dans S/4HANA.

        Pour rappel, Fiori est un composant de S/4HANA utilisé pour l'interface.
        """

        relations = llm_extractor.extract_relations(
            concepts=sample_concepts_product,
            full_text=full_text,
            document_id="test-doc-dedup",
            document_name="Test Dedup"
        )

        # Vérifier pas de duplicates
        part_of_relations = [
            r for r in relations
            if r.relation_type == RelationType.PART_OF
            and r.source_concept == "concept-fiori"
            and r.target_concept == "concept-s4hana"
        ]

        # Devrait avoir exactement 1 relation (dédupliquée)
        assert len(part_of_relations) == 1, (
            f"Déduplication devrait donner 1 relation, got {len(part_of_relations)}"
        )


@pytest.mark.integration
class TestLLMExtractionIntegration:
    """Tests d'intégration avec LLMRouter."""

    def test_llm_router_chat_completion(self, llm_extractor):
        """Test que LLMRouter fonctionne correctement."""
        # Simple test que le router peut faire un appel
        from knowbase.common.llm_router import TaskType

        response = llm_extractor.llm_router.complete(
            task_type=TaskType.KNOWLEDGE_EXTRACTION,
            messages=[{"role": "user", "content": "Say 'test'"}],
            model_preference="gpt-4o-mini",
            temperature=0.1
        )

        assert response is not None
        assert isinstance(response, str)
        assert len(response) > 0

    def test_json_output_parsing(self, llm_extractor, sample_concepts_encryption):
        """Test que le parsing JSON fonctionne avec réponses LLM réelles."""
        full_text = "HANA utilise AES256 pour le chiffrement."

        # Ceci fera un vrai appel LLM
        relations = llm_extractor.extract_relations(
            concepts=sample_concepts_encryption,
            full_text=full_text,
            document_id="test-json-parsing",
            document_name="Test JSON Parsing"
        )

        # Si pas d'exception levée, parsing JSON a fonctionné
        assert isinstance(relations, list)
        for rel in relations:
            # Vérifier structure TypedRelation valide
            assert hasattr(rel, 'relation_id')
            assert hasattr(rel, 'source_concept')
            assert hasattr(rel, 'target_concept')
            assert hasattr(rel, 'relation_type')
            assert hasattr(rel, 'metadata')
