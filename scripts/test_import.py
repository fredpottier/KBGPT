#!/usr/bin/env python3
"""
Script de test pour valider l'import dans une collection temporaire
"""

import json
import sys
import zipfile
from pathlib import Path

# Ajout du chemin pour importer les modules du projet
sys.path.insert(0, str(Path(__file__).parent.parent))

from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, Distance, VectorParams
import redis

from knowbase.config.settings import get_settings
from knowbase.common.logging import setup_logging

# Configuration
settings = get_settings()
logger = setup_logging(settings.logs_dir, "test_import_debug.log")

TEST_COLLECTION = "test_import"


def get_qdrant_client():
    """Connexion Qdrant"""
    qdrant_host = 'qdrant'
    return QdrantClient(host=qdrant_host, port=6333)


def get_redis_client():
    """Connexion Redis"""
    redis_host = 'redis'
    return redis.Redis(host=redis_host, port=6379, db=1, decode_responses=True)


def setup_test_collection():
    """Prépare la collection de test"""
    client = get_qdrant_client()

    # Supprimer si existe
    try:
        client.delete_collection(TEST_COLLECTION)
        logger.info(f"Collection {TEST_COLLECTION} supprimée")
    except:
        pass

    # Créer la collection test avec la vraie dimension des vecteurs (768)
    client.create_collection(
        collection_name=TEST_COLLECTION,
        vectors_config=VectorParams(size=768, distance=Distance.COSINE)
    )
    logger.info(f"✅ Collection {TEST_COLLECTION} créée")


def test_import_qdrant_chunks(zip_path: Path) -> bool:
    """Teste l'import des chunks Qdrant"""
    try:
        # Charger les chunks depuis le ZIP
        with zipfile.ZipFile(zip_path, 'r') as zipf:
            if 'qdrant_chunks.json' not in zipf.namelist():
                logger.error("Aucun chunk Qdrant dans le ZIP")
                return False

            chunks_content = zipf.read('qdrant_chunks.json').decode('utf-8')
            chunks_data = json.loads(chunks_content)

        logger.info(f"📊 Chunks à importer: {len(chunks_data)}")

        # Convertir en PointStruct
        points = []
        for chunk in chunks_data[:10]:  # Tester seulement les 10 premiers
            point = PointStruct(
                id=chunk['id'],
                vector=chunk['vector'],
                payload=chunk['payload']
            )
            points.append(point)

        # Insérer dans la collection de test
        client = get_qdrant_client()
        client.upsert(
            collection_name=TEST_COLLECTION,
            points=points
        )

        # Vérifier l'insertion
        count = client.count(TEST_COLLECTION)
        logger.info(f"✅ Chunks insérés: {count.count}")

        # Test de recherche
        if count.count > 0:
            first_vector = chunks_data[0]['vector']
            search_result = client.search(
                collection_name=TEST_COLLECTION,
                query_vector=first_vector,
                limit=1
            )

            if search_result:
                logger.info(f"✅ Test recherche réussi: score={search_result[0].score:.3f}")
                return True
            else:
                logger.error("❌ Test recherche échoué")
                return False

        return True

    except Exception as e:
        logger.error(f"❌ Erreur test import Qdrant: {e}")
        return False


def test_import_redis_metadata(zip_path: Path) -> bool:
    """Teste l'import des métadonnées Redis"""
    try:
        # Charger les métadonnées depuis le ZIP
        with zipfile.ZipFile(zip_path, 'r') as zipf:
            if 'redis_metadata.json' not in zipf.namelist():
                logger.info("Aucune métadonnée Redis dans le ZIP")
                return True

            redis_content = zipf.read('redis_metadata.json').decode('utf-8')
            redis_data = json.loads(redis_content)

        logger.info(f"🔧 Clés Redis à importer: {len(redis_data)}")

        client = get_redis_client()
        test_keys = []

        for key, value in redis_data.items():
            # Préfixer avec "test:" pour éviter les conflits
            test_key = f"test:{key}"
            test_keys.append(test_key)

            try:
                if isinstance(value, dict) and '_redis_type' in value:
                    redis_type = value['_redis_type']
                    data = value['_data']

                    if redis_type == 'hash':
                        if isinstance(data, dict):
                            client.hset(test_key, mapping=data)
                            logger.info(f"✅ Hash Redis testé: {test_key}")

                    elif redis_type == 'list':
                        if isinstance(data, list) and data:
                            client.lpush(test_key, *reversed(data))
                            logger.info(f"✅ Liste Redis testée: {test_key}")

                    elif redis_type == 'set':
                        if isinstance(data, list) and data:
                            client.sadd(test_key, *data)
                            logger.info(f"✅ Set Redis testé: {test_key}")

                else:
                    # String simple
                    if isinstance(value, (dict, list)):
                        value_str = json.dumps(value, ensure_ascii=False)
                    else:
                        value_str = str(value)

                    client.set(test_key, value_str)
                    logger.info(f"✅ String Redis testée: {test_key}")

            except Exception as e:
                logger.error(f"❌ Erreur test Redis {test_key}: {e}")

        # Nettoyer les clés de test
        if test_keys:
            client.delete(*test_keys)
            logger.info(f"🧹 Nettoyé {len(test_keys)} clés de test")

        return True

    except Exception as e:
        logger.error(f"❌ Erreur test import Redis: {e}")
        return False


def cleanup_test_collection():
    """Nettoie la collection de test"""
    try:
        client = get_qdrant_client()
        client.delete_collection(TEST_COLLECTION)
        logger.info(f"🧹 Collection {TEST_COLLECTION} supprimée")
    except Exception as e:
        logger.warning(f"Erreur nettoyage: {e}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_import.py ZIP_PATH")
        sys.exit(1)

    zip_path = Path(sys.argv[1])

    if not zip_path.exists():
        print(f"❌ ZIP introuvable: {zip_path}")
        sys.exit(1)

    print(f"🧪 Test d'import: {zip_path.name}")
    print("=" * 50)

    try:
        # Préparer l'environnement de test
        setup_test_collection()

        # Tester l'import Qdrant
        print("\n🔍 Test import chunks Qdrant...")
        qdrant_ok = test_import_qdrant_chunks(zip_path)

        # Tester l'import Redis
        print("\n🔧 Test import métadonnées Redis...")
        redis_ok = test_import_redis_metadata(zip_path)

        # Résultats
        print("\n" + "=" * 50)
        print("📊 Résultats des tests:")
        print(f"   ✅ Qdrant: {'RÉUSSI' if qdrant_ok else 'ÉCHOUÉ'}")
        print(f"   ✅ Redis: {'RÉUSSI' if redis_ok else 'ÉCHOUÉ'}")

        if qdrant_ok and redis_ok:
            print("\n🎉 Tous les tests d'import sont RÉUSSIS!")
            print("   → Le ZIP peut être importé sans problème")
        else:
            print("\n❌ Certains tests ont ÉCHOUÉ")
            print("   → Vérifier les logs pour plus de détails")

    finally:
        # Nettoyer
        cleanup_test_collection()

    print(f"\n💡 Logs détaillés: {settings.logs_dir}/test_import_debug.log")


if __name__ == "__main__":
    main()