#!/usr/bin/env python3
"""
Script d'import pour restaurer un document depuis un ZIP d'export

Usage:
  python import_document.py [ZIP_PATH] [--force] [--dry-run]
  python import_document.py [--force] [--dry-run]  # Traite tous les ZIP du répertoire courant

Exemples:
  # Import d'un fichier spécifique
  python import_document.py exports/document_export_20250927_143000.zip
  python import_document.py document_export.zip --force
  python import_document.py document_export.zip --dry-run

  # Import de tous les ZIP du répertoire courant
  python import_document.py --force
  python import_document.py --dry-run

Ce script restaure depuis un ZIP :
- Le fichier PPTX/PDF dans docs_done
- Le PDF généré (si applicable) dans slides
- Toutes les miniatures/slides
- Les chunks dans Qdrant
- Les métadonnées Redis

Options:
  --force    Écrase les fichiers existants
  --dry-run  Simule l'import sans rien modifier
"""

import json
import os
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import argparse

# Ajout du chemin pour importer les modules du projet
sys.path.insert(0, str(Path(__file__).parent.parent))

from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, Filter, FieldCondition, MatchValue
import redis

from knowbase.config.settings import get_settings
from knowbase.common.logging import setup_logging

# Configuration
settings = get_settings()
logger = setup_logging(settings.logs_dir, "import_debug.log")

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


def load_manifest(zip_path: Path) -> Dict:
    """Charge le manifeste depuis le ZIP"""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zipf:
            manifest_content = zipf.read('manifest.json').decode('utf-8')
            return json.loads(manifest_content)
    except Exception as e:
        raise ValueError(f"Impossible de lire le manifeste: {e}")


def check_conflicts(manifest: Dict, force: bool = False) -> List[str]:
    """Vérifie les conflits potentiels avant import"""
    conflicts = []
    filename_stem = manifest['filename_stem']

    # Vérifier fichier source
    source_file = manifest['source_file']
    target_source = DOCS_DONE / source_file
    if target_source.exists() and not force:
        conflicts.append(f"Fichier source existe: {target_source}")

    # Vérifier PDF généré
    if manifest['has_pdf']:
        pdf_file = f"{filename_stem}.pdf"
        target_pdf = SLIDES_DIR / pdf_file
        if target_pdf.exists() and not force:
            conflicts.append(f"PDF généré existe: {target_pdf}")

    # Vérifier slides/thumbnails
    for pattern in [f"{filename_stem}_slide_*"]:
        existing_slides = list(SLIDES_DIR.glob(pattern + ".jpg")) + list(SLIDES_DIR.glob(pattern + ".png"))
        existing_thumbs = list(THUMBNAILS_DIR.glob(pattern + ".jpg")) + list(THUMBNAILS_DIR.glob(pattern + ".png"))

        if (existing_slides or existing_thumbs) and not force:
            conflicts.append(f"Slides/thumbnails existent: {len(existing_slides)} slides, {len(existing_thumbs)} thumbnails")

    # Vérifier chunks Qdrant
    if manifest['qdrant_chunks_count'] > 0:
        try:
            client = get_qdrant_client()
            search_filter = Filter(
                must=[
                    FieldCondition(
                        key="document.source_name",
                        match=MatchValue(value=source_file)
                    )
                ]
            )

            response = client.scroll(
                collection_name=QDRANT_COLLECTION,
                scroll_filter=search_filter,
                limit=1
            )

            if response[0] and not force:
                conflicts.append(f"Chunks Qdrant existent pour {source_file}")

        except Exception as e:
            logger.warning(f"Impossible de vérifier Qdrant: {e}")

    return conflicts


def extract_files(zip_path: Path, manifest: Dict, dry_run: bool = False) -> Dict[str, int]:
    """Extrait les fichiers depuis le ZIP"""
    stats = {'files_extracted': 0, 'files_skipped': 0}

    with zipfile.ZipFile(zip_path, 'r') as zipf:

        # Extraire le fichier source
        source_files = [f for f in zipf.namelist() if f.startswith('source/')]
        for file_path in source_files:
            target_path = DOCS_DONE / Path(file_path).name
            if dry_run:
                logger.info(f"[DRY-RUN] Extrairait: {file_path} → {target_path}")
            else:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with zipf.open(file_path) as src, open(target_path, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
                logger.info(f"✅ Extrait: {target_path}")
            stats['files_extracted'] += 1

        # Extraire le PDF généré
        pdf_files = [f for f in zipf.namelist() if f.startswith('pdf/')]
        for file_path in pdf_files:
            target_path = SLIDES_DIR / Path(file_path).name
            if dry_run:
                logger.info(f"[DRY-RUN] Extrairait: {file_path} → {target_path}")
            else:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with zipf.open(file_path) as src, open(target_path, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
                logger.info(f"✅ Extrait: {target_path}")
            stats['files_extracted'] += 1

        # Extraire les slides
        slide_files = [f for f in zipf.namelist() if f.startswith('slides/')]
        for file_path in slide_files:
            target_path = SLIDES_DIR / Path(file_path).name
            if dry_run:
                logger.info(f"[DRY-RUN] Extrairait: {file_path} → {target_path}")
            else:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with zipf.open(file_path) as src, open(target_path, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
            stats['files_extracted'] += 1

        # Extraire les thumbnails
        thumb_files = [f for f in zipf.namelist() if f.startswith('thumbnails/')]
        for file_path in thumb_files:
            target_path = THUMBNAILS_DIR / Path(file_path).name
            if dry_run:
                logger.info(f"[DRY-RUN] Extrairait: {file_path} → {target_path}")
            else:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with zipf.open(file_path) as src, open(target_path, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
            stats['files_extracted'] += 1

    return stats


def import_qdrant_chunks(zip_path: Path, dry_run: bool = False) -> int:
    """Importe les chunks dans Qdrant"""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zipf:
            if 'qdrant_chunks.json' not in zipf.namelist():
                logger.info("Aucun chunk Qdrant à importer")
                return 0

            chunks_content = zipf.read('qdrant_chunks.json').decode('utf-8')
            chunks_data = json.loads(chunks_content)

        if dry_run:
            logger.info(f"[DRY-RUN] Importerait {len(chunks_data)} chunks Qdrant")
            return len(chunks_data)

        # Convertir en PointStruct
        points = []
        for chunk in chunks_data:
            point = PointStruct(
                id=chunk['id'],
                vector=chunk['vector'],
                payload=chunk['payload']
            )
            points.append(point)

        # Insérer par batchs
        batch_size = 100
        total_inserted = 0

        client = get_qdrant_client()

        for i in range(0, len(points), batch_size):
            batch = points[i:i+batch_size]
            try:
                client.upsert(
                    collection_name=QDRANT_COLLECTION,
                    points=batch
                )
                total_inserted += len(batch)
                logger.info(f"✅ Inséré batch {i//batch_size + 1}: {len(batch)} chunks")

            except Exception as e:
                logger.error(f"❌ Erreur batch {i//batch_size + 1}: {e}")

        logger.info(f"✅ Total chunks Qdrant importés: {total_inserted}")
        return total_inserted

    except Exception as e:
        logger.error(f"❌ Erreur import Qdrant: {e}")
        return 0


def import_redis_metadata(zip_path: Path, dry_run: bool = False) -> int:
    """Importe les métadonnées dans Redis"""
    try:
        with zipfile.ZipFile(zip_path, 'r') as zipf:
            if 'redis_metadata.json' not in zipf.namelist():
                logger.info("Aucune métadonnée Redis à importer")
                return 0

            redis_content = zipf.read('redis_metadata.json').decode('utf-8')
            redis_data = json.loads(redis_content)

        if dry_run:
            logger.info(f"[DRY-RUN] Importerait {len(redis_data)} clés Redis")
            return len(redis_data)

        client = get_redis_client()
        imported_count = 0

        for key, value in redis_data.items():
            try:
                # Vérifier si c'est une donnée structurée avec type Redis
                if isinstance(value, dict) and '_redis_type' in value:
                    redis_type = value['_redis_type']
                    data = value['_data']

                    if redis_type == 'hash':
                        # Restaurer un hash
                        if isinstance(data, dict):
                            client.hset(key, mapping=data)
                            imported_count += 1
                            logger.debug(f"✅ Hash Redis importé: {key}")

                    elif redis_type == 'list':
                        # Restaurer une liste
                        if isinstance(data, list):
                            if data:  # Ne pas créer de liste vide
                                client.lpush(key, *reversed(data))  # Reversed pour maintenir l'ordre
                                imported_count += 1
                                logger.debug(f"✅ Liste Redis importée: {key}")

                    elif redis_type == 'set':
                        # Restaurer un set
                        if isinstance(data, list):
                            if data:  # Ne pas créer de set vide
                                client.sadd(key, *data)
                                imported_count += 1
                                logger.debug(f"✅ Set Redis importé: {key}")

                    elif redis_type == 'stream':
                        # Pour les streams, on ne peut pas restaurer facilement
                        # On ignore pour l'instant (les streams RQ se recréent automatiquement)
                        logger.info(f"⚠️ Stream Redis ignoré (se recrée automatiquement): {key}")

                    else:
                        logger.warning(f"⚠️ Type Redis non supporté pour import: {redis_type}")

                else:
                    # Donnée simple (string)
                    if isinstance(value, (dict, list)):
                        value_str = json.dumps(value, ensure_ascii=False)
                    else:
                        value_str = str(value)

                    client.set(key, value_str)
                    imported_count += 1
                    logger.debug(f"✅ String Redis importée: {key}")

            except Exception as e:
                logger.error(f"❌ Erreur clé Redis {key}: {e}")

        logger.info(f"✅ Total clés Redis importées: {imported_count}")
        return imported_count

    except Exception as e:
        logger.error(f"❌ Erreur import Redis: {e}")
        return 0


def import_document(zip_path: Path, force: bool = False, dry_run: bool = False) -> Dict:
    """Importe complètement un document depuis le ZIP"""

    logger.info(f"🚀 Import document depuis: {zip_path}")

    # Vérifier que le ZIP existe
    if not zip_path.exists():
        raise FileNotFoundError(f"ZIP introuvable: {zip_path}")

    # Charger le manifeste
    manifest = load_manifest(zip_path)
    logger.info(f"📋 Manifeste chargé: {manifest['filename_stem']}")

    # Vérifier les conflits
    conflicts = check_conflicts(manifest, force)
    if conflicts and not force:
        logger.error("❌ Conflits détectés:")
        for conflict in conflicts:
            logger.error(f"   - {conflict}")
        raise ValueError("Conflits détectés. Utilisez --force pour écraser.")

    if conflicts and force:
        logger.warning("⚠️ Conflits détectés mais --force activé:")
        for conflict in conflicts:
            logger.warning(f"   - {conflict}")

    # Extraire les fichiers
    file_stats = extract_files(zip_path, manifest, dry_run)

    # Importer Qdrant
    qdrant_count = import_qdrant_chunks(zip_path, dry_run)

    # Importer Redis
    redis_count = import_redis_metadata(zip_path, dry_run)

    # Résumé
    result = {
        'manifest': manifest,
        'files_extracted': file_stats['files_extracted'],
        'qdrant_chunks_imported': qdrant_count,
        'redis_keys_imported': redis_count,
        'dry_run': dry_run
    }

    return result


def find_zip_files(directory: Path = None) -> List[Path]:
    """Trouve tous les fichiers ZIP dans un répertoire"""
    if directory is None:
        directory = Path.cwd()

    zip_files = list(directory.glob("*.zip"))
    # Filtrer les fichiers qui ressemblent à des exports (optionnel)
    export_zips = [f for f in zip_files if 'export' in f.name.lower()]

    if export_zips:
        return sorted(export_zips)
    return sorted(zip_files)


def import_multiple_documents(zip_files: List[Path], force: bool = False, dry_run: bool = False) -> Dict:
    """Importe plusieurs documents depuis une liste de ZIP"""

    total_stats = {
        'total_files': len(zip_files),
        'successful_imports': 0,
        'failed_imports': 0,
        'total_files_extracted': 0,
        'total_qdrant_chunks': 0,
        'total_redis_keys': 0,
        'results': []
    }

    print(f"🚀 Import de {len(zip_files)} fichiers ZIP...")
    print("=" * 60)

    for i, zip_path in enumerate(zip_files, 1):
        print(f"\n📦 [{i}/{len(zip_files)}] Traitement: {zip_path.name}")
        print("-" * 40)

        try:
            result = import_document(zip_path, force, dry_run)

            # Statistiques
            total_stats['successful_imports'] += 1
            total_stats['total_files_extracted'] += result['files_extracted']
            total_stats['total_qdrant_chunks'] += result['qdrant_chunks_imported']
            total_stats['total_redis_keys'] += result['redis_keys_imported']

            # Résultat
            mode = "[DRY-RUN] " if dry_run else ""
            print(f"✅ {mode}Import réussi:")
            print(f"   📄 Document: {result['manifest']['filename_stem']}")
            print(f"   📁 Fichiers: {result['files_extracted']}")
            print(f"   📊 Chunks Qdrant: {result['qdrant_chunks_imported']}")
            print(f"   🔧 Clés Redis: {result['redis_keys_imported']}")

            total_stats['results'].append({
                'zip_file': zip_path.name,
                'success': True,
                'result': result
            })

        except Exception as e:
            total_stats['failed_imports'] += 1
            logger.error(f"❌ Erreur import {zip_path.name}: {e}")
            print(f"❌ Erreur: {e}")

            total_stats['results'].append({
                'zip_file': zip_path.name,
                'success': False,
                'error': str(e)
            })

            # Continuer avec le fichier suivant
            continue

    return total_stats


def main():
    parser = argparse.ArgumentParser(
        description="Importe un ou plusieurs documents depuis des ZIP d'export",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  # Import d'un fichier spécifique
  python import_document.py exports/document_export_20250927_143000.zip
  python import_document.py document_export.zip --force
  python import_document.py document_export.zip --dry-run

  # Import de tous les ZIP du répertoire courant
  python import_document.py --force
  python import_document.py --dry-run
        """
    )

    parser.add_argument('zip_path', nargs='?', help='Chemin vers le ZIP d\'export (optionnel)')
    parser.add_argument('--force', action='store_true', help='Écrase les fichiers existants')
    parser.add_argument('--dry-run', action='store_true', help='Simule l\'import sans rien modifier')

    args = parser.parse_args()

    try:
        if args.zip_path:
            # Mode fichier unique
            zip_path = Path(args.zip_path)
            result = import_document(zip_path, args.force, args.dry_run)

            # Afficher le résumé
            mode = "[DRY-RUN] " if args.dry_run else ""
            print(f"\n🎯 {mode}Import réussi:")
            print(f"   📁 ZIP: {zip_path}")
            print(f"   📄 Document: {result['manifest']['filename_stem']}")
            print(f"   📁 Fichiers extraits: {result['files_extracted']}")
            print(f"   📊 Chunks Qdrant: {result['qdrant_chunks_imported']}")
            print(f"   🔧 Clés Redis: {result['redis_keys_imported']}")

            if args.dry_run:
                print(f"\n💡 Simulation terminée. Utilisez sans --dry-run pour importer réellement.")
            else:
                print(f"\n✅ Import terminé avec succès!")

        else:
            # Mode multiple - traiter tous les ZIP du répertoire courant
            zip_files = find_zip_files()

            if not zip_files:
                print("📭 Aucun fichier ZIP trouvé dans le répertoire courant")
                return

            print(f"📋 Fichiers ZIP trouvés:")
            for i, zip_file in enumerate(zip_files, 1):
                print(f"   {i:2d}. {zip_file.name}")

            # Demander confirmation si pas en dry-run
            if not args.dry_run and not args.force:
                response = input(f"\n❓ Importer ces {len(zip_files)} fichiers ? [y/N]: ")
                if response.lower() not in ['y', 'yes', 'o', 'oui']:
                    print("🚫 Import annulé")
                    return

            # Importer tous les fichiers
            total_stats = import_multiple_documents(zip_files, args.force, args.dry_run)

            # Résumé final
            print("\n" + "=" * 60)
            mode = "[DRY-RUN] " if args.dry_run else ""
            print(f"📊 {mode}Résumé final:")
            print(f"   📦 Total fichiers ZIP: {total_stats['total_files']}")
            print(f"   ✅ Imports réussis: {total_stats['successful_imports']}")
            print(f"   ❌ Imports échoués: {total_stats['failed_imports']}")
            print(f"   📁 Total fichiers extraits: {total_stats['total_files_extracted']}")
            print(f"   📊 Total chunks Qdrant: {total_stats['total_qdrant_chunks']}")
            print(f"   🔧 Total clés Redis: {total_stats['total_redis_keys']}")

            if total_stats['failed_imports'] > 0:
                print(f"\n⚠️ Fichiers échoués:")
                for result in total_stats['results']:
                    if not result['success']:
                        print(f"   - {result['zip_file']}: {result['error']}")

            if args.dry_run:
                print(f"\n💡 Simulation terminée. Utilisez sans --dry-run pour importer réellement.")
            else:
                print(f"\n✅ Import multiple terminé!")

    except Exception as e:
        logger.error(f"❌ Erreur lors de l'import: {e}")
        print(f"\n❌ Erreur: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()