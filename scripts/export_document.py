#!/usr/bin/env python3
"""
Script d'export pour sauvegarder un document traité en ZIP

Usage: python export_document.py FILENAME_STEM [OUTPUT_DIR]

Exemples:
  python export_document.py "S4H_Business_Scope_BusinessAI-2023FPS2_FPS3_V1__20250927_100114"
  python export_document.py "SAP_BTP_-_Security_and_Compliance__20250926_163141" /path/to/exports/

Ce script crée un ZIP contenant :
- Le fichier PPTX/PDF original traité
- Le PDF généré (si PPTX)
- Toutes les miniatures/slides
- L'export JSON des chunks Qdrant
- Les métadonnées Redis (statut d'import)
"""

import json
import os
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# Ajout du chemin pour importer les modules du projet
sys.path.insert(0, str(Path(__file__).parent.parent))

from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue
import redis

from knowbase.config.settings import get_settings
from knowbase.common.logging import setup_logging

# Configuration
settings = get_settings()
logger = setup_logging(settings.logs_dir, "export_debug.log")

DOCS_DONE = Path(settings.presentations_dir)
SLIDES_DIR = Path(settings.slides_dir)
THUMBNAILS_DIR = Path(settings.thumbnails_dir)
QDRANT_COLLECTION = settings.qdrant_collection


def get_redis_client():
    """Connexion Redis"""
    # Utiliser le nom de service Docker au lieu de localhost
    redis_host = os.getenv('REDIS_HOST', 'redis')
    return redis.Redis(host=redis_host, port=6379, db=1, decode_responses=True)


def get_qdrant_client():
    """Connexion Qdrant"""
    # Utiliser le nom de service Docker au lieu de localhost
    qdrant_host = os.getenv('QDRANT_HOST', 'qdrant')
    return QdrantClient(host=qdrant_host, port=6333)


def find_document_files(filename_stem: str) -> Dict[str, Optional[Path]]:
    """Trouve tous les fichiers associés à un document"""
    files = {
        'source': None,
        'pdf': None,
        'slides': [],
        'thumbnails': []
    }

    # Chercher le fichier source (PPTX ou PDF)
    for ext in ['.pptx', '.pdf']:
        source_path = DOCS_DONE / f"{filename_stem}{ext}"
        if source_path.exists():
            files['source'] = source_path
            logger.info(f"✅ Fichier source trouvé: {source_path}")
            break

    if not files['source']:
        logger.error(f"❌ Aucun fichier source trouvé pour {filename_stem}")
        return files

    # Chercher le PDF généré (si source = PPTX)
    if files['source'].suffix == '.pptx':
        pdf_path = SLIDES_DIR / f"{filename_stem}.pdf"
        if pdf_path.exists():
            files['pdf'] = pdf_path
            logger.info(f"✅ PDF généré trouvé: {pdf_path}")

    # Chercher les slides/thumbnails
    for pattern in [f"{filename_stem}_slide_*.jpg", f"{filename_stem}_slide_*.png"]:
        files['slides'].extend(SLIDES_DIR.glob(pattern))
        files['thumbnails'].extend(THUMBNAILS_DIR.glob(pattern))

    logger.info(f"✅ Trouvé {len(files['slides'])} slides et {len(files['thumbnails'])} thumbnails")
    return files


def export_qdrant_chunks(filename_stem: str) -> List[Dict]:
    """Exporte les chunks Qdrant associés au document"""
    try:
        client = get_qdrant_client()

        # Rechercher tous les points avec ce source_name
        search_filter = Filter(
            must=[
                FieldCondition(
                    key="document.source_name",
                    match=MatchValue(value=f"{filename_stem}.pptx")
                )
            ]
        )

        # Alternative pour PDF
        search_filter_pdf = Filter(
            must=[
                FieldCondition(
                    key="document.source_name",
                    match=MatchValue(value=f"{filename_stem}.pdf")
                )
            ]
        )

        chunks = []
        for filter_obj in [search_filter, search_filter_pdf]:
            try:
                response = client.scroll(
                    collection_name=QDRANT_COLLECTION,
                    scroll_filter=filter_obj,
                    limit=1000,  # Ajuster si nécessaire
                    with_vectors=True  # IMPORTANT: récupérer les vecteurs
                )

                if response[0]:  # Si des points trouvés
                    for point in response[0]:
                        chunks.append({
                            'id': point.id,
                            'vector': point.vector,
                            'payload': point.payload
                        })
                    break  # Sortir dès qu'on trouve des chunks

            except Exception as e:
                logger.debug(f"Tentative de recherche échouée: {e}")
                continue

        logger.info(f"✅ Exporté {len(chunks)} chunks Qdrant")
        return chunks

    except Exception as e:
        logger.error(f"❌ Erreur export Qdrant: {e}")
        return []


def export_redis_metadata(filename_stem: str) -> Dict:
    """Exporte les métadonnées Redis associées au document"""
    try:
        client = get_redis_client()

        # Chercher les clés liées au document
        pattern_keys = [
            f"*{filename_stem}*",
            f"*import*{filename_stem}*",
            f"*job*{filename_stem}*"
        ]

        metadata = {}
        for pattern in pattern_keys:
            keys = client.keys(pattern)
            for key in keys:
                try:
                    # Déterminer le type de la clé
                    key_type = client.type(key).decode('utf-8') if isinstance(client.type(key), bytes) else client.type(key)

                    if key_type == 'string':
                        value = client.get(key)
                        if value:
                            try:
                                metadata[key] = json.loads(value)
                            except:
                                metadata[key] = value

                    elif key_type == 'hash':
                        # Pour les hash (comme rq:job:*)
                        hash_data = client.hgetall(key)
                        if hash_data:
                            # Convertir bytes en string si nécessaire
                            cleaned_hash = {}
                            for k, v in hash_data.items():
                                key_str = k.decode('utf-8') if isinstance(k, bytes) else k
                                val_str = v.decode('utf-8') if isinstance(v, bytes) else v
                                cleaned_hash[key_str] = val_str
                            metadata[key] = {
                                '_redis_type': 'hash',
                                '_data': cleaned_hash
                            }

                    elif key_type == 'stream':
                        # Pour les streams (comme rq:results:*)
                        try:
                            stream_data = client.xrange(key, count=100)  # Limiter à 100 entrées
                            if stream_data:
                                metadata[key] = {
                                    '_redis_type': 'stream',
                                    '_data': str(stream_data)  # Sérialiser simplement
                                }
                        except Exception as e:
                            logger.warning(f"Erreur lecture stream {key}: {e}")

                    elif key_type == 'list':
                        # Pour les listes
                        list_data = client.lrange(key, 0, -1)
                        if list_data:
                            cleaned_list = [item.decode('utf-8') if isinstance(item, bytes) else item for item in list_data]
                            metadata[key] = {
                                '_redis_type': 'list',
                                '_data': cleaned_list
                            }

                    elif key_type == 'set':
                        # Pour les sets
                        set_data = client.smembers(key)
                        if set_data:
                            cleaned_set = [item.decode('utf-8') if isinstance(item, bytes) else item for item in set_data]
                            metadata[key] = {
                                '_redis_type': 'set',
                                '_data': cleaned_set
                            }
                    else:
                        logger.warning(f"Type Redis non supporté pour {key}: {key_type}")

                except Exception as e:
                    logger.warning(f"Impossible de lire la clé Redis {key}: {e}")

        logger.info(f"✅ Exporté {len(metadata)} entrées Redis")
        return metadata

    except Exception as e:
        logger.error(f"❌ Erreur export Redis: {e}")
        return {}


def create_export_zip(filename_stem: str, output_dir: Optional[str] = None) -> Path:
    """Crée le ZIP d'export complet"""

    if output_dir:
        export_dir = Path(output_dir)
    else:
        export_dir = Path.cwd() / "exports"

    export_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"{filename_stem}_export_{timestamp}.zip"
    zip_path = export_dir / zip_name

    logger.info(f"🚀 Création du ZIP d'export: {zip_path}")

    # Trouver tous les fichiers
    files = find_document_files(filename_stem)

    if not files['source']:
        raise FileNotFoundError(f"Aucun fichier source trouvé pour {filename_stem}")

    # Exporter les données
    qdrant_chunks = export_qdrant_chunks(filename_stem)
    redis_metadata = export_redis_metadata(filename_stem)

    # Créer le manifeste
    manifest = {
        'filename_stem': filename_stem,
        'export_timestamp': timestamp,
        'source_file': files['source'].name,
        'source_type': files['source'].suffix.lstrip('.'),
        'has_pdf': files['pdf'] is not None,
        'slides_count': len(files['slides']),
        'thumbnails_count': len(files['thumbnails']),
        'qdrant_chunks_count': len(qdrant_chunks),
        'redis_keys_count': len(redis_metadata),
        'export_version': '1.0'
    }

    # Créer le ZIP
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:

        # Ajouter le manifeste
        zipf.writestr('manifest.json', json.dumps(manifest, indent=2, ensure_ascii=False))

        # Ajouter le fichier source
        zipf.write(files['source'], f"source/{files['source'].name}")

        # Ajouter le PDF généré (si existe)
        if files['pdf']:
            zipf.write(files['pdf'], f"pdf/{files['pdf'].name}")

        # Ajouter les slides
        for slide_file in files['slides']:
            zipf.write(slide_file, f"slides/{slide_file.name}")

        # Ajouter les thumbnails
        for thumb_file in files['thumbnails']:
            zipf.write(thumb_file, f"thumbnails/{thumb_file.name}")

        # Ajouter les chunks Qdrant
        if qdrant_chunks:
            zipf.writestr('qdrant_chunks.json', json.dumps(qdrant_chunks, indent=2, ensure_ascii=False))

        # Ajouter les métadonnées Redis
        if redis_metadata:
            zipf.writestr('redis_metadata.json', json.dumps(redis_metadata, indent=2, ensure_ascii=False))

    file_size = zip_path.stat().st_size / (1024 * 1024)  # MB
    logger.info(f"✅ Export terminé: {zip_path} ({file_size:.1f} MB)")

    # Afficher le résumé
    print(f"\n🎯 Export réussi:")
    print(f"   📁 ZIP: {zip_path}")
    print(f"   📄 Fichier source: {files['source'].name}")
    print(f"   🖼️  Slides: {len(files['slides'])}")
    print(f"   🔍 Thumbnails: {len(files['thumbnails'])}")
    print(f"   📊 Chunks Qdrant: {len(qdrant_chunks)}")
    print(f"   🔧 Clés Redis: {len(redis_metadata)}")
    print(f"   💾 Taille: {file_size:.1f} MB")

    return zip_path


def main():
    if len(sys.argv) < 2:
        print("Usage: python export_document.py FILENAME_STEM [OUTPUT_DIR]")
        print("\nExemples:")
        print('  python export_document.py "S4H_Business_Scope_BusinessAI-2023FPS2_FPS3_V1__20250927_100114"')
        print('  python export_document.py "SAP_BTP_-_Security_and_Compliance__20250926_163141" /path/to/exports/')
        sys.exit(1)

    filename_stem = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else None

    try:
        zip_path = create_export_zip(filename_stem, output_dir)
        print(f"\n✅ Export terminé avec succès: {zip_path}")

    except Exception as e:
        logger.error(f"❌ Erreur lors de l'export: {e}")
        print(f"\n❌ Erreur: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()