#!/usr/bin/env python3
"""
Test script pour vérifier que les embeddings 1024D sont correctement
générés et insérés dans Qdrant.

Usage:
    docker-compose exec app python scripts/test_embeddings_1024d.py
"""

import sys
import logging
from pathlib import Path

# Ajouter src au path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from knowbase.common.clients.qdrant_client import upsert_chunks

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_model_dimension():
    """Test 1: Vérifier dimension du modèle"""
    logger.info("=" * 60)
    logger.info("TEST 1: Dimension modèle multilingual-e5-large")
    logger.info("=" * 60)

    model = SentenceTransformer('intfloat/multilingual-e5-large')
    dim = model.get_sentence_embedding_dimension()

    logger.info(f"✅ Model dimension: {dim}")

    # Test encode
    test_text = "SAP S/4HANA est une solution ERP cloud"
    embedding = model.encode(test_text, convert_to_numpy=True)

    logger.info(f"✅ Embedding shape: {embedding.shape}")
    logger.info(f"✅ Embedding dimension: {len(embedding)}")

    assert dim == 1024, f"Expected 1024D, got {dim}D"
    assert len(embedding) == 1024, f"Expected 1024D embedding, got {len(embedding)}D"

    logger.info("✅ TEST 1 PASSED: Model generates 1024D embeddings\n")
    return model


def test_qdrant_collections():
    """Test 2: Vérifier configuration collections Qdrant"""
    logger.info("=" * 60)
    logger.info("TEST 2: Configuration collections Qdrant")
    logger.info("=" * 60)

    client = QdrantClient(host='qdrant', port=6333)

    collections_to_check = ['knowbase', 'rfp_qa']

    for col_name in collections_to_check:
        try:
            col_info = client.get_collection(collection_name=col_name)
            vector_size = col_info.config.params.vectors.size

            logger.info(f"✅ Collection '{col_name}':")
            logger.info(f"   - Vector size: {vector_size}D")
            logger.info(f"   - Distance: {col_info.config.params.vectors.distance}")
            logger.info(f"   - Points count: {col_info.points_count}")

            assert vector_size == 1024, f"Expected 1024D, got {vector_size}D for {col_name}"

        except Exception as e:
            logger.error(f"❌ Error checking {col_name}: {e}")
            raise

    logger.info("✅ TEST 2 PASSED: All collections configured for 1024D\n")


def test_chunk_insertion(model):
    """Test 3: Tester insertion de chunks réels"""
    logger.info("=" * 60)
    logger.info("TEST 3: Insertion chunks avec embeddings 1024D")
    logger.info("=" * 60)

    # Créer chunks de test
    test_chunks = [
        {
            "text": "SAP S/4HANA est une solution ERP cloud moderne basée sur HANA",
            "document_id": "test-doc-001",
            "document_name": "Test Document.pdf",
            "segment_id": "seg-test-1",
            "chunk_index": 0,
            "proto_concept_ids": ["proto-test-sap", "proto-test-hana"],
            "canonical_concept_ids": [],
            "char_start": 0,
            "char_end": 62,
            "created_at": "2025-01-19T00:00:00Z"
        },
        {
            "text": "Le module FI (Financial Accounting) gère la comptabilité générale",
            "document_id": "test-doc-001",
            "document_name": "Test Document.pdf",
            "segment_id": "seg-test-1",
            "chunk_index": 1,
            "proto_concept_ids": ["proto-test-fi"],
            "canonical_concept_ids": [],
            "char_start": 62,
            "char_end": 128,
            "created_at": "2025-01-19T00:00:00Z"
        }
    ]

    # Générer embeddings 1024D
    logger.info(f"Generating embeddings for {len(test_chunks)} chunks...")
    texts = [chunk["text"] for chunk in test_chunks]
    embeddings = model.encode(texts, convert_to_numpy=True)

    logger.info(f"✅ Generated {len(embeddings)} embeddings")
    logger.info(f"   - Shape: {embeddings.shape}")

    assert embeddings.shape[1] == 1024, f"Expected 1024D embeddings, got {embeddings.shape[1]}D"

    # Ajouter embeddings aux chunks
    for chunk, embedding in zip(test_chunks, embeddings):
        chunk["embedding"] = embedding.tolist()

    # Insérer dans Qdrant
    logger.info(f"Inserting {len(test_chunks)} chunks into Qdrant...")
    chunk_ids = upsert_chunks(
        chunks=test_chunks,
        collection_name="knowbase",
        tenant_id="test"
    )

    logger.info(f"✅ Inserted {len(chunk_ids)} chunks")
    logger.info(f"   - Chunk IDs: {chunk_ids}")

    assert len(chunk_ids) == len(test_chunks), "Not all chunks were inserted"

    # Vérifier que les chunks sont bien dans Qdrant
    client = QdrantClient(host='qdrant', port=6333)

    for chunk_id in chunk_ids:
        point = client.retrieve(
            collection_name="knowbase",
            ids=[chunk_id],
            with_vectors=True
        )

        if point:
            vector = point[0].vector
            logger.info(f"✅ Chunk {chunk_id}: vector dimension = {len(vector)}D")
            assert len(vector) == 1024, f"Expected 1024D vector, got {len(vector)}D"
        else:
            logger.error(f"❌ Chunk {chunk_id} not found in Qdrant")
            raise AssertionError(f"Chunk {chunk_id} not found")

    logger.info("✅ TEST 3 PASSED: Chunks inserted successfully with 1024D embeddings\n")

    # Nettoyer les chunks de test
    logger.info("Cleaning up test chunks...")
    try:
        client.delete(
            collection_name="knowbase",
            points_selector=chunk_ids
        )
        logger.info(f"✅ Deleted {len(chunk_ids)} test chunks")
    except Exception as e:
        logger.warning(f"⚠️  Could not clean up test chunks: {e}")


def main():
    """Exécuter tous les tests"""
    logger.info("\n" + "=" * 60)
    logger.info("TESTS EMBEDDINGS 1024D - DÉBUT")
    logger.info("=" * 60 + "\n")

    try:
        # Test 1: Dimension modèle
        model = test_model_dimension()

        # Test 2: Collections Qdrant
        test_qdrant_collections()

        # Test 3: Insertion chunks
        test_chunk_insertion(model)

        logger.info("=" * 60)
        logger.info("✅ TOUS LES TESTS PASSÉS")
        logger.info("=" * 60)
        logger.info("")
        logger.info("📊 Résumé:")
        logger.info("  - Modèle multilingual-e5-large: 1024D ✅")
        logger.info("  - Collections Qdrant (knowbase, rfp_qa): 1024D ✅")
        logger.info("  - Insertion chunks avec embeddings 1024D: ✅")
        logger.info("")
        logger.info("🎯 Le système est prêt pour Phase 2 OSMOSE")
        logger.info("")

        return 0

    except Exception as e:
        logger.error("\n" + "=" * 60)
        logger.error("❌ TESTS ÉCHOUÉS")
        logger.error("=" * 60)
        logger.error(f"Erreur: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
