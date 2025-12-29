"""
Tests pour le ConceptEmbeddingService et le matching multilingue.

Ces tests verifient:
1. Le contrat de representation (build_concept_embedding_text)
2. Le hash deterministe
3. Le statut du service (mode degrade)
4. Les tests de non-regression multilingue (FR/EN/DE/IT)
"""

import pytest
from datetime import datetime

from knowbase.semantic.concept_embedding_service import (
    build_concept_embedding_text,
    compute_embedding_hash,
    ConceptSemanticStatus,
    ConceptEmbeddingService,
    QDRANT_CONCEPTS_COLLECTION,
    EMBEDDING_VERSION,
    EMBEDDING_DIMENSION,
)


# =============================================================================
# TESTS DU CONTRAT DE REPRESENTATION
# =============================================================================

class TestBuildConceptEmbeddingText:
    """Tests pour le contrat de representation deterministe."""

    def test_minimal_concept(self):
        """Test avec uniquement le nom canonique."""
        text = build_concept_embedding_text("Data Erasure")
        assert text == "Data Erasure"

    def test_with_definition(self):
        """Test avec definition."""
        text = build_concept_embedding_text(
            "Data Erasure",
            unified_definition="The permanent removal of personal data."
        )
        assert text == "Data Erasure — The permanent removal of personal data."

    def test_with_summary(self):
        """Test avec summary."""
        text = build_concept_embedding_text(
            "Data Erasure",
            summary="A key GDPR right."
        )
        assert text == "Data Erasure — A key GDPR right."

    def test_with_definition_and_summary(self):
        """Test avec definition et summary."""
        text = build_concept_embedding_text(
            "Data Erasure",
            unified_definition="The permanent removal of personal data.",
            summary="A key GDPR right."
        )
        assert "Data Erasure — The permanent removal" in text
        assert "A key GDPR right" in text

    def test_with_surface_forms(self):
        """Test avec variantes/aliases multilingues."""
        text = build_concept_embedding_text(
            "Data Erasure",
            surface_forms=["effacement des donnees", "Datenlöschung", "cancellazione dati"]
        )
        assert "Data Erasure" in text
        assert "aliases:" in text
        assert "effacement des donnees" in text
        assert "Datenlöschung" in text
        assert "cancellazione dati" in text

    def test_surface_forms_sorted(self):
        """Les aliases doivent etre tries pour le determinisme."""
        text1 = build_concept_embedding_text(
            "GDPR",
            surface_forms=["RGPD", "DSGVO", "General Data Protection Regulation"]
        )
        text2 = build_concept_embedding_text(
            "GDPR",
            surface_forms=["General Data Protection Regulation", "DSGVO", "RGPD"]
        )
        # Les deux doivent etre identiques (ordre trie)
        assert text1 == text2

    def test_surface_forms_deduplicated(self):
        """Les aliases en double doivent etre supprimes."""
        text = build_concept_embedding_text(
            "GDPR",
            surface_forms=["RGPD", "RGPD", "DSGVO", "dsgvo"]
        )
        # Compte les occurrences
        assert text.count("RGPD") == 1
        assert text.count("DSGVO") == 1

    def test_canonical_name_excluded_from_aliases(self):
        """Le nom canonique ne doit pas apparaitre dans les aliases."""
        text = build_concept_embedding_text(
            "GDPR",
            surface_forms=["GDPR", "gdpr", "RGPD"]
        )
        # GDPR apparait une seule fois (au debut)
        assert text.startswith("GDPR")
        assert "aliases: RGPD" in text
        assert text.count("GDPR") == 1

    def test_truncation_definition(self):
        """La definition est tronquee a 500 chars."""
        long_def = "x" * 1000
        text = build_concept_embedding_text("Test", unified_definition=long_def)
        # 500 chars max pour la definition
        assert len(text) < 600  # canonical_name + separator + 500

    def test_truncation_aliases(self):
        """Maximum 10 aliases."""
        many_forms = [f"form_{i}" for i in range(20)]
        text = build_concept_embedding_text("Test", surface_forms=many_forms)
        # Compte les virgules dans aliases
        aliases_part = text.split("aliases:")[1] if "aliases:" in text else ""
        comma_count = aliases_part.count(",")
        assert comma_count <= 9  # 10 elements = 9 virgules max

    def test_empty_values_ignored(self):
        """Les valeurs vides sont ignorees."""
        text = build_concept_embedding_text(
            "Test",
            unified_definition="",
            summary="   ",
            surface_forms=["", "  ", None]
        )
        assert text == "Test"

    def test_determinism(self):
        """Le meme input doit toujours produire le meme output."""
        for _ in range(10):
            text = build_concept_embedding_text(
                "GDPR",
                unified_definition="EU data protection regulation",
                summary="Key privacy law",
                surface_forms=["RGPD", "DSGVO"]
            )
            assert "GDPR — EU data protection regulation — Key privacy law — aliases: DSGVO, RGPD" == text


# =============================================================================
# TESTS DU HASH DETERMINISTE
# =============================================================================

class TestComputeEmbeddingHash:
    """Tests pour le hash deterministe."""

    def test_hash_deterministic(self):
        """Le meme texte doit produire le meme hash."""
        text = "Data Erasure — effacement des données"
        hash1 = compute_embedding_hash(text)
        hash2 = compute_embedding_hash(text)
        assert hash1 == hash2

    def test_hash_length(self):
        """Le hash doit avoir 16 caracteres."""
        hash_val = compute_embedding_hash("test")
        assert len(hash_val) == 16

    def test_different_texts_different_hashes(self):
        """Des textes differents doivent produire des hashes differents."""
        hash1 = compute_embedding_hash("Data Erasure")
        hash2 = compute_embedding_hash("Data Retention")
        assert hash1 != hash2

    def test_unicode_handling(self):
        """Le hash doit gerer correctement l'unicode."""
        text_fr = "effacement des données"
        text_de = "Datenlöschung"
        text_it = "cancellazione dei dati"

        # Chacun doit produire un hash valide
        for text in [text_fr, text_de, text_it]:
            hash_val = compute_embedding_hash(text)
            assert len(hash_val) == 16
            assert hash_val.isalnum()


# =============================================================================
# TESTS DU STATUT SEMANTIC
# =============================================================================

class TestConceptSemanticStatus:
    """Tests pour le statut du service semantic."""

    def test_default_status(self):
        """Statut par defaut = non disponible."""
        status = ConceptSemanticStatus()
        assert not status.available
        assert not status.collection_exists
        assert status.concept_count == 0
        assert status.embedding_version == EMBEDDING_VERSION

    def test_status_to_dict(self):
        """Conversion en dictionnaire."""
        status = ConceptSemanticStatus(
            available=True,
            collection_exists=True,
            concept_count=100,
            last_sync="2024-01-01T00:00:00",
            message="100 concepts indexed"
        )
        d = status.to_dict()
        assert d["available"] is True
        assert d["concept_count"] == 100
        assert "2024-01-01" in d["last_sync"]


# =============================================================================
# TESTS DE NON-REGRESSION MULTILINGUE
# =============================================================================

class TestMultilingualEmbeddingText:
    """
    Tests de non-regression pour le matching multilingue.

    Ces tests verifient que les concepts avec surface_forms multilingues
    produisent un texte d'embedding qui contient toutes les variantes.
    """

    # Cas de test: concepts avec leurs variantes multilingues connues
    MULTILINGUAL_CONCEPTS = [
        {
            "canonical_name": "Data Erasure",
            "unified_definition": "The right to have personal data deleted",
            "surface_forms": [
                "effacement des donnees",  # FR
                "droit a l'oubli",          # FR (Right to be forgotten)
                "Datenlöschung",            # DE
                "Recht auf Vergessenwerden", # DE
                "cancellazione dei dati",   # IT
                "diritto all'oblio",        # IT
            ],
        },
        {
            "canonical_name": "GDPR",
            "unified_definition": "General Data Protection Regulation",
            "surface_forms": [
                "RGPD",                     # FR/ES/PT
                "DSGVO",                    # DE
                "reglement general",        # FR
                "Datenschutz-Grundverordnung", # DE
            ],
        },
        {
            "canonical_name": "Ransomware",
            "unified_definition": "Malware that encrypts data and demands ransom",
            "surface_forms": [
                "rancongiciel",             # FR
                "logiciel de rancon",       # FR
                "Erpressungstrojaner",      # DE
            ],
        },
        {
            "canonical_name": "Cloud Computing",
            "unified_definition": "On-demand delivery of IT resources over the internet",
            "surface_forms": [
                "informatique en nuage",    # FR
                "infonuagique",             # FR (Quebec)
                "Cloud-Computing",          # DE
                "cloud informatico",        # IT
            ],
        },
    ]

    @pytest.mark.parametrize("concept", MULTILINGUAL_CONCEPTS)
    def test_multilingual_surface_forms_included(self, concept):
        """
        Verifie que toutes les variantes multilingues sont dans le texte.

        C'est critique pour le matching cross-lingue: si une forme n'est pas
        dans le texte d'embedding, elle ne sera pas trouvee.
        """
        text = build_concept_embedding_text(
            canonical_name=concept["canonical_name"],
            unified_definition=concept["unified_definition"],
            surface_forms=concept["surface_forms"],
        )

        # Le nom canonique doit etre present
        assert concept["canonical_name"] in text

        # Chaque surface form doit etre presente (normalisee)
        for form in concept["surface_forms"]:
            form_clean = form.strip()
            if form_clean.lower() != concept["canonical_name"].lower():
                assert form_clean in text, f"Missing surface form: {form_clean}"

    def test_french_question_matches_english_concept(self):
        """
        Scenario cle: question FR doit matcher concept EN.

        Si un utilisateur demande "Qu'est-ce que l'effacement des donnees?",
        le concept "Data Erasure" doit etre trouve grace a la surface form FR.
        """
        text = build_concept_embedding_text(
            canonical_name="Data Erasure",
            unified_definition="The right to have personal data deleted",
            surface_forms=["effacement des donnees", "droit a l'oubli"],
        )

        # Le texte d'embedding doit contenir "effacement"
        assert "effacement" in text.lower()

        # Et "donnees"
        assert "donnees" in text.lower()

    def test_german_question_matches_english_concept(self):
        """
        Scenario: question DE doit matcher concept EN.
        """
        text = build_concept_embedding_text(
            canonical_name="GDPR",
            unified_definition="General Data Protection Regulation",
            surface_forms=["DSGVO", "Datenschutz-Grundverordnung"],
        )

        assert "DSGVO" in text
        assert "Datenschutz" in text


# =============================================================================
# TESTS D'INTEGRATION (requires infrastructure)
# =============================================================================

@pytest.mark.integration
class TestConceptEmbeddingServiceIntegration:
    """
    Tests d'integration pour le ConceptEmbeddingService.

    Necessitent Qdrant et Neo4j actifs.
    """

    def test_ensure_collection_exists(self):
        """La collection doit etre creee si elle n'existe pas."""
        service = ConceptEmbeddingService()
        result = service.ensure_collection_exists()
        assert result is True

    def test_get_status_without_sync(self):
        """Statut avant sync = collection existe mais 0 concepts."""
        service = ConceptEmbeddingService()
        service.ensure_collection_exists()
        status = service.get_status("test_tenant")

        assert status.collection_exists is True
        # Peut avoir 0 concepts si pas encore sync
        assert isinstance(status.concept_count, int)

    def test_sync_concepts_idempotent(self):
        """
        Le sync doit etre idempotent.

        Deux syncs consecutifs doivent donner le meme resultat
        (tous les concepts 'unchanged' la 2eme fois).
        """
        service = ConceptEmbeddingService()
        service.ensure_collection_exists()

        # Premier sync
        result1 = service.sync_concepts(tenant_id="default", incremental=False)

        # Deuxieme sync (sans changements)
        result2 = service.sync_concepts(tenant_id="default", incremental=False)

        # La 2eme fois, tous les concepts devraient etre unchanged
        # (sauf si la base Neo4j a change entre temps)
        if result1.total > 0 and result2.total > 0:
            assert result2.unchanged == result2.total, (
                f"Sync not idempotent: {result2.created} created, {result2.updated} updated"
            )


# =============================================================================
# TESTS DES CONSTANTES
# =============================================================================

class TestConstants:
    """Verifie les constantes du service."""

    def test_collection_name(self):
        """Le nom de collection doit etre stable."""
        assert QDRANT_CONCEPTS_COLLECTION == "osmos_concepts"

    def test_embedding_version(self):
        """La version d'embedding doit etre stable."""
        assert EMBEDDING_VERSION.startswith("concept_v")

    def test_embedding_dimension(self):
        """Dimension pour multilingual-e5-large = 1024."""
        assert EMBEDDING_DIMENSION == 1024
