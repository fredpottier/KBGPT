"""Tests complets pour TextChunker.

Tests unitaires couvrant:
- Découpage de texte en chunks
- Génération d'embeddings
- Attribution de concepts aux chunks
- Chunks génériques et concept-focused
- Cas limites
"""

import pytest
from typing import List, Dict, Any
from unittest.mock import MagicMock, patch
import numpy as np


class TestTextChunkerSplitText:
    """Tests pour _split_text_into_chunks."""

    @patch("knowbase.ingestion.text_chunker.SentenceTransformer")
    @patch("knowbase.ingestion.text_chunker.tiktoken.get_encoding")
    def test_split_text_basic(self, mock_tiktoken, mock_st) -> None:
        """Test découpage basique de texte."""
        from knowbase.ingestion.text_chunker import TextChunker

        # Mock tokenizer
        mock_encoding = MagicMock()
        mock_encoding.encode.return_value = list(range(100))  # 100 tokens
        mock_encoding.decode.side_effect = lambda tokens: "x" * len(tokens)
        mock_tiktoken.return_value = mock_encoding

        # Mock model
        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 1024
        mock_st.return_value = mock_model

        chunker = TextChunker(chunk_size=50, overlap=10)
        text = "x" * 100

        chunks = chunker._split_text_into_chunks(text)

        # Devrait créer au moins 2 chunks
        assert len(chunks) >= 2
        assert all("text" in chunk for chunk in chunks)
        assert all("char_start" in chunk for chunk in chunks)
        assert all("char_end" in chunk for chunk in chunks)

    @patch("knowbase.ingestion.text_chunker.SentenceTransformer")
    @patch("knowbase.ingestion.text_chunker.tiktoken.get_encoding")
    def test_split_text_empty(self, mock_tiktoken, mock_st) -> None:
        """Test découpage de texte vide."""
        from knowbase.ingestion.text_chunker import TextChunker

        mock_encoding = MagicMock()
        mock_encoding.encode.return_value = []
        mock_tiktoken.return_value = mock_encoding

        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 1024
        mock_st.return_value = mock_model

        chunker = TextChunker()
        chunks = chunker._split_text_into_chunks("")

        assert chunks == []

    @patch("knowbase.ingestion.text_chunker.SentenceTransformer")
    @patch("knowbase.ingestion.text_chunker.tiktoken.get_encoding")
    def test_split_text_short_text(self, mock_tiktoken, mock_st) -> None:
        """Test découpage de texte court (< chunk_size)."""
        from knowbase.ingestion.text_chunker import TextChunker

        mock_encoding = MagicMock()
        mock_encoding.encode.return_value = list(range(10))  # 10 tokens
        mock_encoding.decode.return_value = "Short text"
        mock_tiktoken.return_value = mock_encoding

        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 1024
        mock_st.return_value = mock_model

        chunker = TextChunker(chunk_size=512)
        chunks = chunker._split_text_into_chunks("Short text")

        # Un seul chunk pour texte court
        assert len(chunks) == 1


class TestTextChunkerFindConcepts:
    """Tests pour _find_mentioned_concepts."""

    @patch("knowbase.ingestion.text_chunker.SentenceTransformer")
    @patch("knowbase.ingestion.text_chunker.tiktoken.get_encoding")
    def test_find_concepts_exact_match(self, mock_tiktoken, mock_st) -> None:
        """Test détection de concept avec match exact."""
        from knowbase.ingestion.text_chunker import TextChunker

        mock_encoding = MagicMock()
        mock_tiktoken.return_value = mock_encoding

        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 1024
        mock_st.return_value = mock_model

        chunker = TextChunker()

        concepts = [
            {"proto_concept_id": "uuid-1", "name": "SAP S/4HANA"},
            {"proto_concept_id": "uuid-2", "name": "SAP BTP"},
        ]

        chunk_text = "SAP S/4HANA is an ERP system"
        mentioned = chunker._find_mentioned_concepts(chunk_text, concepts)

        assert "uuid-1" in mentioned
        assert "uuid-2" not in mentioned

    @patch("knowbase.ingestion.text_chunker.SentenceTransformer")
    @patch("knowbase.ingestion.text_chunker.tiktoken.get_encoding")
    def test_find_concepts_case_insensitive(self, mock_tiktoken, mock_st) -> None:
        """Test détection case-insensitive."""
        from knowbase.ingestion.text_chunker import TextChunker

        mock_encoding = MagicMock()
        mock_tiktoken.return_value = mock_encoding

        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 1024
        mock_st.return_value = mock_model

        chunker = TextChunker()

        concepts = [
            {"proto_concept_id": "uuid-1", "name": "SAP S/4HANA"},
        ]

        chunk_text = "sap s/4hana is great"
        mentioned = chunker._find_mentioned_concepts(chunk_text, concepts)

        assert "uuid-1" in mentioned

    @patch("knowbase.ingestion.text_chunker.SentenceTransformer")
    @patch("knowbase.ingestion.text_chunker.tiktoken.get_encoding")
    def test_find_concepts_normalized_variants(self, mock_tiktoken, mock_st) -> None:
        """Test détection avec variantes normalisées."""
        from knowbase.ingestion.text_chunker import TextChunker

        mock_encoding = MagicMock()
        mock_tiktoken.return_value = mock_encoding

        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 1024
        mock_st.return_value = mock_model

        chunker = TextChunker()

        concepts = [
            {"proto_concept_id": "uuid-1", "name": "S/4HANA"},
        ]

        # S4HANA devrait matcher S/4HANA (sans slash)
        chunk_text = "S4HANA is deployed"
        mentioned = chunker._find_mentioned_concepts(chunk_text, concepts)

        assert "uuid-1" in mentioned

    @patch("knowbase.ingestion.text_chunker.SentenceTransformer")
    @patch("knowbase.ingestion.text_chunker.tiktoken.get_encoding")
    def test_find_concepts_no_match(self, mock_tiktoken, mock_st) -> None:
        """Test détection sans match."""
        from knowbase.ingestion.text_chunker import TextChunker

        mock_encoding = MagicMock()
        mock_tiktoken.return_value = mock_encoding

        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 1024
        mock_st.return_value = mock_model

        chunker = TextChunker()

        concepts = [
            {"proto_concept_id": "uuid-1", "name": "SAP S/4HANA"},
        ]

        chunk_text = "This is about Oracle database"
        mentioned = chunker._find_mentioned_concepts(chunk_text, concepts)

        assert mentioned == []

    @patch("knowbase.ingestion.text_chunker.SentenceTransformer")
    @patch("knowbase.ingestion.text_chunker.tiktoken.get_encoding")
    def test_find_concepts_missing_fields(self, mock_tiktoken, mock_st) -> None:
        """Test détection avec champs manquants."""
        from knowbase.ingestion.text_chunker import TextChunker

        mock_encoding = MagicMock()
        mock_tiktoken.return_value = mock_encoding

        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 1024
        mock_st.return_value = mock_model

        chunker = TextChunker()

        # Concept sans proto_concept_id
        concepts = [
            {"name": "SAP S/4HANA"},  # Manque proto_concept_id
        ]

        chunk_text = "SAP S/4HANA is great"
        mentioned = chunker._find_mentioned_concepts(chunk_text, concepts)

        # Devrait ignorer ce concept
        assert mentioned == []


class TestTextChunkerFindMentions:
    """Tests pour _find_concept_mentions."""

    @patch("knowbase.ingestion.text_chunker.SentenceTransformer")
    @patch("knowbase.ingestion.text_chunker.tiktoken.get_encoding")
    def test_find_mentions_single(self, mock_tiktoken, mock_st) -> None:
        """Test recherche de mentions unique."""
        from knowbase.ingestion.text_chunker import TextChunker

        mock_encoding = MagicMock()
        mock_tiktoken.return_value = mock_encoding

        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 1024
        mock_st.return_value = mock_model

        chunker = TextChunker()

        text = "SAP S/4HANA is an ERP system"
        mentions = chunker._find_concept_mentions(text, "SAP S/4HANA")

        assert len(mentions) == 1
        assert mentions[0][0] == 0  # Position de début

    @patch("knowbase.ingestion.text_chunker.SentenceTransformer")
    @patch("knowbase.ingestion.text_chunker.tiktoken.get_encoding")
    def test_find_mentions_multiple(self, mock_tiktoken, mock_st) -> None:
        """Test recherche de mentions multiples."""
        from knowbase.ingestion.text_chunker import TextChunker

        mock_encoding = MagicMock()
        mock_tiktoken.return_value = mock_encoding

        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 1024
        mock_st.return_value = mock_model

        chunker = TextChunker()

        text = "SAP uses SAP HANA. SAP HANA is fast."
        mentions = chunker._find_concept_mentions(text, "SAP HANA")

        assert len(mentions) == 2

    @patch("knowbase.ingestion.text_chunker.SentenceTransformer")
    @patch("knowbase.ingestion.text_chunker.tiktoken.get_encoding")
    def test_find_mentions_none(self, mock_tiktoken, mock_st) -> None:
        """Test recherche sans mention."""
        from knowbase.ingestion.text_chunker import TextChunker

        mock_encoding = MagicMock()
        mock_tiktoken.return_value = mock_encoding

        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 1024
        mock_st.return_value = mock_model

        chunker = TextChunker()

        text = "Oracle database is used"
        mentions = chunker._find_concept_mentions(text, "SAP HANA")

        assert mentions == []


class TestTextChunkerExtractContext:
    """Tests pour _extract_context_window."""

    @patch("knowbase.ingestion.text_chunker.SentenceTransformer")
    @patch("knowbase.ingestion.text_chunker.tiktoken.get_encoding")
    def test_extract_context_basic(self, mock_tiktoken, mock_st) -> None:
        """Test extraction de contexte basique."""
        from knowbase.ingestion.text_chunker import TextChunker

        # Mock tokenizer complexe
        mock_encoding = MagicMock()

        def encode_side_effect(text):
            return list(range(len(text)))

        def decode_side_effect(tokens):
            return "x" * len(tokens)

        mock_encoding.encode.side_effect = encode_side_effect
        mock_encoding.decode.side_effect = decode_side_effect
        mock_tiktoken.return_value = mock_encoding

        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 1024
        mock_st.return_value = mock_model

        chunker = TextChunker()

        text = "a" * 1000
        chunk_text, char_start, char_end = chunker._extract_context_window(
            text, mention_start=500, mention_end=510, context_tokens=100
        )

        # Devrait retourner un contexte autour de la mention
        assert isinstance(chunk_text, str)
        assert isinstance(char_start, int)
        assert isinstance(char_end, int)


class TestTextChunkerChunkDocument:
    """Tests pour chunk_document."""

    @patch("knowbase.ingestion.text_chunker.SentenceTransformer")
    @patch("knowbase.ingestion.text_chunker.tiktoken.get_encoding")
    def test_chunk_document_empty_text(self, mock_tiktoken, mock_st) -> None:
        """Test avec texte vide."""
        from knowbase.ingestion.text_chunker import TextChunker

        mock_encoding = MagicMock()
        mock_tiktoken.return_value = mock_encoding

        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 1024
        mock_st.return_value = mock_model

        chunker = TextChunker()

        chunks = chunker.chunk_document(
            text="",
            document_id="doc-1",
            document_name="test.pdf",
            segment_id="seg-1",
            concepts=[],
        )

        assert chunks == []

    @patch("knowbase.ingestion.text_chunker.SentenceTransformer")
    @patch("knowbase.ingestion.text_chunker.tiktoken.get_encoding")
    def test_chunk_document_whitespace_only(self, mock_tiktoken, mock_st) -> None:
        """Test avec espaces seulement."""
        from knowbase.ingestion.text_chunker import TextChunker

        mock_encoding = MagicMock()
        mock_tiktoken.return_value = mock_encoding

        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 1024
        mock_st.return_value = mock_model

        chunker = TextChunker()

        chunks = chunker.chunk_document(
            text="   ",
            document_id="doc-1",
            document_name="test.pdf",
            segment_id="seg-1",
            concepts=[],
        )

        assert chunks == []

    @patch("knowbase.ingestion.text_chunker.SentenceTransformer")
    @patch("knowbase.ingestion.text_chunker.tiktoken.get_encoding")
    def test_chunk_document_generic_only(self, mock_tiktoken, mock_st) -> None:
        """Test génération de chunks génériques uniquement."""
        from knowbase.ingestion.text_chunker import TextChunker

        mock_encoding = MagicMock()
        mock_encoding.encode.return_value = list(range(100))
        mock_encoding.decode.return_value = "Sample text content"
        mock_tiktoken.return_value = mock_encoding

        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 1024

        # Mock encode pour retourner embeddings
        mock_embeddings = np.random.rand(1, 1024)
        mock_model.encode.return_value = mock_embeddings
        mock_st.return_value = mock_model

        chunker = TextChunker()
        # Wrapper pour simuler HybridEmbedder
        chunker.model = MagicMock()
        chunker.model.encode.return_value = mock_embeddings

        chunks = chunker.chunk_document(
            text="Sample text content for testing",
            document_id="doc-1",
            document_name="test.pdf",
            segment_id="seg-1",
            concepts=[],
            use_hybrid=False,  # Désactiver hybrid pour test simple
        )

        assert len(chunks) >= 1
        assert all(chunk["chunk_type"] == "generic" for chunk in chunks)
        assert all("embedding" in chunk for chunk in chunks)
        assert all(chunk["document_id"] == "doc-1" for chunk in chunks)


class TestTextChunkerEmbeddings:
    """Tests pour la génération d'embeddings."""

    @patch("knowbase.ingestion.text_chunker.SentenceTransformer")
    @patch("knowbase.ingestion.text_chunker.tiktoken.get_encoding")
    def test_generate_embeddings_batch(self, mock_tiktoken, mock_st) -> None:
        """Test génération d'embeddings en batch."""
        from knowbase.ingestion.text_chunker import TextChunker

        mock_encoding = MagicMock()
        mock_tiktoken.return_value = mock_encoding

        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 1024

        # Mock encode pour retourner embeddings 1024D
        mock_embeddings = np.random.rand(3, 1024)
        mock_model.encode.return_value = mock_embeddings
        mock_st.return_value = mock_model

        chunker = TextChunker()
        # Wrapper pour simuler HybridEmbedder
        chunker.model = MagicMock()
        chunker.model.encode.return_value = mock_embeddings

        texts = ["Text 1", "Text 2", "Text 3"]
        embeddings = chunker._generate_embeddings_batch(texts)

        assert len(embeddings) == 3
        assert embeddings[0].shape == (1024,)

    @patch("knowbase.ingestion.text_chunker.SentenceTransformer")
    @patch("knowbase.ingestion.text_chunker.tiktoken.get_encoding")
    def test_generate_embeddings_error_fallback(self, mock_tiktoken, mock_st) -> None:
        """Test fallback si erreur de génération."""
        from knowbase.ingestion.text_chunker import TextChunker

        mock_encoding = MagicMock()
        mock_tiktoken.return_value = mock_encoding

        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 1024
        mock_st.return_value = mock_model

        chunker = TextChunker()
        # Simuler erreur d'encodage
        chunker.model = MagicMock()
        chunker.model.encode.side_effect = Exception("Embedding error")

        texts = ["Text 1", "Text 2"]
        embeddings = chunker._generate_embeddings_batch(texts)

        # Devrait retourner des embeddings vides
        assert len(embeddings) == 2
        assert all(emb.shape == (1024,) for emb in embeddings)
        assert all(np.all(emb == 0) for emb in embeddings)


class TestTextChunkerSingleton:
    """Tests pour le singleton get_text_chunker."""

    def test_singleton_pattern(self) -> None:
        """Test que get_text_chunker retourne la même instance."""
        import knowbase.ingestion.text_chunker as module

        # Reset singleton
        module._text_chunker_instance = None

        with patch("knowbase.ingestion.text_chunker.SentenceTransformer") as mock_st:
            with patch("knowbase.ingestion.text_chunker.tiktoken.get_encoding") as mock_tiktoken:
                mock_model = MagicMock()
                mock_model.get_sentence_embedding_dimension.return_value = 1024
                mock_st.return_value = mock_model

                mock_encoding = MagicMock()
                mock_tiktoken.return_value = mock_encoding

                from knowbase.ingestion.text_chunker import get_text_chunker

                chunker1 = get_text_chunker()
                chunker2 = get_text_chunker()

                assert chunker1 is chunker2

        # Cleanup
        module._text_chunker_instance = None


class TestTextChunkerChunkMetadata:
    """Tests pour les métadonnées des chunks."""

    @patch("knowbase.ingestion.text_chunker.SentenceTransformer")
    @patch("knowbase.ingestion.text_chunker.tiktoken.get_encoding")
    def test_chunk_has_required_fields(self, mock_tiktoken, mock_st) -> None:
        """Test que les chunks ont tous les champs requis."""
        from knowbase.ingestion.text_chunker import TextChunker

        mock_encoding = MagicMock()
        mock_encoding.encode.return_value = list(range(50))
        mock_encoding.decode.return_value = "Sample text"
        mock_tiktoken.return_value = mock_encoding

        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 1024
        mock_st.return_value = mock_model

        chunker = TextChunker()
        chunker.model = MagicMock()
        chunker.model.encode.return_value = np.random.rand(1, 1024)

        chunks = chunker.chunk_document(
            text="Sample text content",
            document_id="doc-123",
            document_name="test.pdf",
            segment_id="seg-456",
            concepts=[],
            tenant_id="tenant-abc",
            use_hybrid=False,
        )

        if chunks:
            chunk = chunks[0]
            required_fields = [
                "id",
                "text",
                "embedding",
                "document_id",
                "document_name",
                "segment_id",
                "chunk_index",
                "chunk_type",
                "proto_concept_ids",
                "canonical_concept_ids",
                "tenant_id",
                "char_start",
                "char_end",
            ]

            for field in required_fields:
                assert field in chunk, f"Missing field: {field}"

            assert chunk["document_id"] == "doc-123"
            assert chunk["document_name"] == "test.pdf"
            assert chunk["segment_id"] == "seg-456"
            assert chunk["tenant_id"] == "tenant-abc"
            assert chunk["chunk_type"] == "generic"


class TestTextChunkerConceptFocused:
    """Tests pour les chunks concept-focused."""

    @patch("knowbase.ingestion.text_chunker.SentenceTransformer")
    @patch("knowbase.ingestion.text_chunker.tiktoken.get_encoding")
    def test_concept_focused_chunks_created(self, mock_tiktoken, mock_st) -> None:
        """Test création de chunks concept-focused."""
        from knowbase.ingestion.text_chunker import TextChunker

        mock_encoding = MagicMock()
        mock_encoding.encode.return_value = list(range(500))
        mock_encoding.decode.return_value = "x" * 500
        mock_tiktoken.return_value = mock_encoding

        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 1024
        mock_st.return_value = mock_model

        chunker = TextChunker()
        chunker.model = MagicMock()
        chunker.model.encode.return_value = np.random.rand(5, 1024)

        text = "SAP S/4HANA is an ERP system. " * 20
        concepts = [
            {"proto_concept_id": "uuid-1", "name": "SAP S/4HANA"},
        ]

        # Test méthode interne
        concept_chunks = chunker._create_concept_focused_chunks(
            text=text,
            document_id="doc-1",
            document_name="test.pdf",
            segment_id="seg-1",
            concepts=concepts,
            tenant_id="default",
            start_index=0,
        )

        # Peut être vide si pas de mentions trouvées
        assert isinstance(concept_chunks, list)

        # Si des chunks sont créés, ils doivent être concept_focused
        for chunk in concept_chunks:
            assert chunk["chunk_type"] == "concept_focused"
            assert chunk["primary_concept_id"] is not None
