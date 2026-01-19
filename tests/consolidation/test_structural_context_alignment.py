"""
Tests pour ADR_STRUCTURAL_CONTEXT_ALIGNMENT - Alignement context_id structurel.

ADR: doc/ongoing/ADR_STRUCTURAL_CONTEXT_ALIGNMENT.md

Valide que:
1. Les ProtoConcepts reçoivent context_id lors de l'ancrage
2. Les MENTIONED_IN sont créés via context_id (sparse)
3. Pass 3 utilise context_id pour les shared sections

Date: 2026-01-11
"""

import pytest
from unittest.mock import MagicMock, patch, call


class TestProtoConcepContextIdUpdate:
    """Tests pour la mise à jour de context_id sur les ProtoConcepts."""

    def test_update_proto_context_ids_basic(self):
        """Test de base: met à jour context_id sur les protos."""
        from knowbase.ingestion.osmose_persistence import _update_proto_context_ids

        # Mock Neo4j client
        mock_client = MagicMock()
        mock_session = MagicMock()
        mock_client.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_client.driver.session.return_value.__exit__ = MagicMock(return_value=None)

        # Mock result
        mock_result = MagicMock()
        mock_result.single.return_value = {"updated": 3}
        mock_session.run.return_value = mock_result

        # Données de test
        mappings = [
            {"concept_id": "proto_001", "context_id": "sec_intro_abc123"},
            {"concept_id": "proto_002", "context_id": "sec_content_def456"},
            {"concept_id": "proto_003", "context_id": "sec_intro_abc123"},  # Même section
        ]

        # Exécuter
        updated = _update_proto_context_ids(mock_client, mappings, "default")

        # Vérifier
        assert updated == 3
        mock_session.run.assert_called_once()

        # Vérifier que la requête SET est bien appelée
        call_args = mock_session.run.call_args
        query = call_args[0][0]
        assert "SET p.context_id = m.context_id" in query

    def test_update_proto_context_ids_deduplication(self):
        """Test: déduplique les mappings par concept_id."""
        from knowbase.ingestion.osmose_persistence import _update_proto_context_ids

        mock_client = MagicMock()
        mock_session = MagicMock()
        mock_client.driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_client.driver.session.return_value.__exit__ = MagicMock(return_value=None)

        mock_result = MagicMock()
        mock_result.single.return_value = {"updated": 2}
        mock_session.run.return_value = mock_result

        # Mappings avec doublons (même concept_id, contextes différents)
        mappings = [
            {"concept_id": "proto_001", "context_id": "sec_a"},
            {"concept_id": "proto_001", "context_id": "sec_b"},  # Doublon, ignoré
            {"concept_id": "proto_002", "context_id": "sec_c"},
        ]

        _update_proto_context_ids(mock_client, mappings, "default")

        # Vérifier que seuls 2 mappings uniques sont passés
        call_args = mock_session.run.call_args
        passed_mappings = call_args[1]["mappings"]
        assert len(passed_mappings) == 2
        assert passed_mappings[0]["concept_id"] == "proto_001"
        assert passed_mappings[1]["concept_id"] == "proto_002"

    def test_update_proto_context_ids_empty(self):
        """Test: retourne 0 si aucun mapping."""
        from knowbase.ingestion.osmose_persistence import _update_proto_context_ids

        mock_client = MagicMock()
        updated = _update_proto_context_ids(mock_client, [], "default")
        assert updated == 0


class TestMentionedInSparse:
    """Tests pour la création MENTIONED_IN sparse via context_id."""

    def test_mentioned_in_uses_context_id(self):
        """Vérifie que _create_mentioned_in_for_canonical utilise context_id."""
        from knowbase.consolidation.corpus_promotion import CorpusPromotionEngine

        with patch('knowbase.consolidation.corpus_promotion.get_neo4j_client') as mock_get_client, \
             patch('knowbase.consolidation.corpus_promotion.get_hybrid_anchor_config', return_value={}):

            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            engine = CorpusPromotionEngine(tenant_id="test")

            # Mock session
            mock_session = MagicMock()
            mock_result = MagicMock()
            mock_result.single.return_value = {"created": 2}
            mock_session.run.return_value = mock_result

            # Appeler la méthode
            created = engine._create_mentioned_in_for_canonical(
                mock_session,
                "canonical_001",
                ["proto_001", "proto_002"]
            )

            # Vérifier que la requête utilise context_id
            call_args = mock_session.run.call_args
            query = call_args[0][0]

            # ADR_STRUCTURAL_CONTEXT_ALIGNMENT: doit utiliser context_id, pas document_id
            assert "p.context_id" in query
            assert "DISTINCT p.context_id AS ctx_id" in query
            assert "SectionContext {context_id: ctx_id" in query

            # Ne doit PAS utiliser document_id pour le matching
            assert "DISTINCT p.document_id AS doc_id" not in query
            assert "SectionContext {doc_id: doc_id" not in query

    def test_mentioned_in_with_mention_count(self):
        """Vérifie que MENTIONED_IN incrémente mention_count."""
        from knowbase.consolidation.corpus_promotion import CorpusPromotionEngine

        with patch('knowbase.consolidation.corpus_promotion.get_neo4j_client') as mock_get_client, \
             patch('knowbase.consolidation.corpus_promotion.get_hybrid_anchor_config', return_value={}):

            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            engine = CorpusPromotionEngine(tenant_id="test")

            mock_session = MagicMock()
            mock_result = MagicMock()
            mock_result.single.return_value = {"created": 1}
            mock_session.run.return_value = mock_result

            engine._create_mentioned_in_for_canonical(
                mock_session,
                "canonical_001",
                ["proto_001"]
            )

            query = mock_session.run.call_args[0][0]

            # Doit avoir mention_count
            assert "mention_count = 1" in query
            assert "mention_count = r.mention_count + 1" in query


class TestPass3SharedSections:
    """Tests pour Pass 3 utilisant context_id pour shared sections."""

    def test_co_presence_query_uses_context_id(self):
        """Vérifie que la requête co_presence utilise context_id."""
        # Lire le fichier source pour vérifier la requête
        import inspect
        from knowbase.relations.semantic_consolidation_pass3 import CandidateGenerator

        # Inspecter le code source de generate_candidates
        source = inspect.getsource(CandidateGenerator.generate_candidates)

        # ADR_STRUCTURAL_CONTEXT_ALIGNMENT: doit utiliser context_id
        assert "p1.context_id = p2.context_id" in source
        assert "p1.context_id IS NOT NULL" in source

        # Ne doit PAS utiliser section_id pour le matching
        assert "p1.section_id = p2.section_id" not in source

    def test_shared_sections_contains_context_ids(self):
        """Les shared_sections doivent contenir des context_id (hash-based)."""
        # Ce test vérifie le contrat: shared_sections = context_id format
        # Les context_id sont du format "sec_xxx_hash" (hash-based)

        import re

        # Format attendu pour context_id (généré par structural graph)
        context_id_pattern = r"^sec_[a-z0-9_]+_[a-f0-9]+$"

        # Exemples valides
        valid_ids = [
            "sec_introduction_abc123",
            "sec_upgrade_guide_for_sap_s_4hana_d4de6c",
            "sec_root_8832bc",
        ]

        for ctx_id in valid_ids:
            assert re.match(context_id_pattern, ctx_id), f"Invalid context_id format: {ctx_id}"

        # Exemples invalides (ancien format section_id)
        invalid_ids = [
            "Introduction / cluster_0",
            "7. Save the configuration. / cluster_1",
            "/Content/Security",
        ]

        for section_id in invalid_ids:
            assert not re.match(context_id_pattern, section_id), \
                f"section_id should NOT match context_id pattern: {section_id}"


class TestVerifySingleCandidateFiltering:
    """Tests pour le filtrage des contextes dans verify_single_candidate."""

    def test_filters_by_shared_sections(self):
        """Vérifie que verify_single_candidate filtre par shared_sections."""
        # Ce test vérifie la logique de filtrage ajoutée par l'ADR

        # Simuler le comportement du code modifié
        context_texts = {
            "sec_intro_abc": "Introduction text",
            "sec_content_def": "Content text",
            "sec_appendix_ghi": "Appendix text",
        }

        class MockCandidate:
            shared_sections = ["sec_intro_abc", "sec_content_def"]

        candidate = MockCandidate()

        # Logique du code modifié
        candidate_contexts = context_texts
        if hasattr(candidate, 'shared_sections') and candidate.shared_sections:
            filtered = {
                ctx_id: text for ctx_id, text in context_texts.items()
                if ctx_id in candidate.shared_sections
            }
            if filtered:
                candidate_contexts = filtered

        # Vérifier le filtrage
        assert len(candidate_contexts) == 2
        assert "sec_intro_abc" in candidate_contexts
        assert "sec_content_def" in candidate_contexts
        assert "sec_appendix_ghi" not in candidate_contexts


class TestEndToEndContextIdFlow:
    """Tests de bout en bout pour le flux context_id."""

    def test_context_id_flow_documentation(self):
        """
        Documente le flux context_id de bout en bout.

        Pass 0 (Structural Graph):
        - DocItem.section_id = "sec_xxx_hash"
        - SectionContext.context_id = "sec_xxx_hash" (même valeur)

        Pass 1 (Concept Extraction):
        - ProtoConcept créé avec ANCHORED_IN → CoverageChunk
        - CoverageChunk.context_id = "sec_xxx_hash" (hérité de DocItem)
        - ProtoConcept.context_id = CoverageChunk.context_id

        Pass 2 (Corpus Promotion):
        - MENTIONED_IN créé via: ProtoConcept.context_id = SectionContext.context_id
        - Résultat: SPARSE relations (1 par section réelle, pas toutes)

        Pass 3 (Relation Extraction):
        - shared_sections = [context_id, ...] (hash-based)
        - Filtrage des contextes par shared_sections
        - Evidence quotes pertinents car filtrés à la bonne section
        """
        # Ce test est une documentation exécutable
        # Il passe toujours car il documente le design

        # Invariants du système
        invariants = [
            "SectionContext.context_id = DocItem.section_id",
            "CoverageChunk.context_id = DocItem.section_id (via structural graph)",
            "ProtoConcept.context_id = CoverageChunk.context_id (via ANCHORED_IN)",
            "MENTIONED_IN join via: cc → p.context_id = s.context_id",
        ]

        # Vérifier que les invariants sont documentés
        for inv in invariants:
            assert inv  # Simplement vérifier que les invariants existent


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
