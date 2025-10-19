"""
🔄 Migration Qdrant: 768D → 1024D (multilingual-e5-base → multilingual-e5-large)

**Problème:**
- Collection 'knowbase' créée avec 768 dimensions (intfloat/multilingual-e5-base)
- OSMOSE V2.2 utilise 1024 dimensions (intfloat/multilingual-e5-large)
- Qdrant rejette les vecteurs: "expected dim: 768, got 1024"

**Solution:**
1. Backup collection existante (optionnel)
2. Supprimer collection 768D
3. Recréer collection 1024D
4. Réimporter documents (embeddings seront régénérés)

Version: V2.2
Date: 2025-10-19
"""

import sys
import logging
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, OptimizersConfigDiff

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate_qdrant_collection():
    """
    Migre la collection Qdrant de 768D à 1024D.
    """
    # Configuration
    QDRANT_URL = "http://localhost:6333"
    COLLECTION_NAME = "knowbase"
    NEW_VECTOR_SIZE = 1024

    logger.info("🔄 Migration Qdrant: 768D → 1024D")
    logger.info(f"   Collection: {COLLECTION_NAME}")
    logger.info(f"   New vector size: {NEW_VECTOR_SIZE}D")

    # Connexion Qdrant
    client = QdrantClient(url=QDRANT_URL)

    # 1. Vérifier collection existante
    try:
        collection_info = client.get_collection(COLLECTION_NAME)
        current_size = collection_info.config.params.vectors.size
        logger.info(f"✅ Collection existante trouvée: {current_size}D")

        if current_size == NEW_VECTOR_SIZE:
            logger.info(f"✅ Collection déjà à {NEW_VECTOR_SIZE}D, aucune migration nécessaire")
            return

        # Compter points existants
        count = client.count(COLLECTION_NAME).count
        logger.info(f"   Points existants: {count}")

        if count > 0:
            logger.warning(f"⚠️  {count} points seront PERDUS lors de la migration!")
            response = input("   Continuer? (yes/no): ")
            if response.lower() != "yes":
                logger.info("❌ Migration annulée")
                sys.exit(0)

    except Exception as e:
        logger.info(f"ℹ️  Collection n'existe pas encore ({e})")

    # 2. Supprimer collection existante
    try:
        logger.info(f"🗑️  Suppression collection {COLLECTION_NAME}...")
        client.delete_collection(COLLECTION_NAME)
        logger.info("✅ Collection supprimée")
    except Exception as e:
        logger.info(f"ℹ️  Aucune collection à supprimer ({e})")

    # 3. Recréer collection 1024D
    logger.info(f"🔨 Création collection {COLLECTION_NAME} avec {NEW_VECTOR_SIZE}D...")
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config=VectorParams(
            size=NEW_VECTOR_SIZE,
            distance=Distance.COSINE
        ),
        optimizers_config=OptimizersConfigDiff(
            indexing_threshold=10000
        ),
        on_disk_payload=True
    )
    logger.info("✅ Collection recréée avec succès!")

    # 4. Vérifier
    collection_info = client.get_collection(COLLECTION_NAME)
    new_size = collection_info.config.params.vectors.size
    logger.info(f"✅ Vérification: {new_size}D")

    logger.info("")
    logger.info("=" * 60)
    logger.info("✅ Migration Qdrant terminée avec succès!")
    logger.info("=" * 60)
    logger.info("")
    logger.info("📋 Prochaines étapes:")
    logger.info("   1. Redémarrer le worker: docker-compose restart ingestion-worker")
    logger.info("   2. Réimporter vos documents via http://localhost:3000/documents/import")
    logger.info("   3. Les embeddings seront régénérés avec le nouveau modèle 1024D")
    logger.info("")


if __name__ == "__main__":
    try:
        migrate_qdrant_collection()
    except KeyboardInterrupt:
        logger.info("\n❌ Migration interrompue par l'utilisateur")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Erreur migration: {e}", exc_info=True)
        sys.exit(1)
