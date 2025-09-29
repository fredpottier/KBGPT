#!/usr/bin/env python3
"""
Script utilitaire pour lister les documents traités disponibles pour export

Usage: python list_documents.py [--detailed]

Exemples:
  python list_documents.py
  python list_documents.py --detailed
"""

import sys
from pathlib import Path
from datetime import datetime
import argparse

# Ajout du chemin pour importer les modules du projet
sys.path.insert(0, str(Path(__file__).parent.parent))

from knowbase.config.settings import get_settings

def list_documents(detailed: bool = False):
    """Liste les documents traités disponibles"""

    settings = get_settings()
    docs_done = Path(settings.presentations_dir)
    slides_dir = Path(settings.slides_dir)
    thumbnails_dir = Path(settings.thumbnails_dir)

    if not docs_done.exists():
        print("❌ Répertoire docs_done introuvable")
        return

    # Trouver tous les fichiers traités
    documents = []
    for file_path in docs_done.glob("*"):
        if file_path.is_file() and file_path.suffix in ['.pptx', '.pdf']:
            stem = file_path.stem

            # Compter les assets associés
            pdf_exists = (slides_dir / f"{stem}.pdf").exists()
            slides_count = len(list(slides_dir.glob(f"{stem}_slide_*")))
            thumbs_count = len(list(thumbnails_dir.glob(f"{stem}_slide_*")))

            doc_info = {
                'stem': stem,
                'file': file_path.name,
                'size_mb': file_path.stat().st_size / (1024 * 1024),
                'modified': datetime.fromtimestamp(file_path.stat().st_mtime),
                'has_pdf': pdf_exists,
                'slides_count': slides_count,
                'thumbs_count': thumbs_count
            }
            documents.append(doc_info)

    # Trier par date de modification (plus récent en premier)
    documents.sort(key=lambda x: x['modified'], reverse=True)

    if not documents:
        print("📭 Aucun document traité trouvé dans docs_done/")
        return

    print(f"📚 Documents traités disponibles ({len(documents)}):\n")

    for i, doc in enumerate(documents, 1):
        if detailed:
            print(f"{i:2d}. {doc['stem']}")
            print(f"     📄 Fichier: {doc['file']} ({doc['size_mb']:.1f} MB)")
            print(f"     📅 Modifié: {doc['modified'].strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"     🔗 Assets: PDF={doc['has_pdf']}, Slides={doc['slides_count']}, Thumbs={doc['thumbs_count']}")
            print()
        else:
            status = "✅" if doc['slides_count'] > 0 else "⚠️"
            print(f"{status} {doc['stem']}")

    if not detailed:
        print(f"\n💡 Utilisez --detailed pour plus d'informations")
        print(f"📤 Pour exporter: python scripts/export_document.py \"NOM_DU_DOCUMENT\"")

def main():
    parser = argparse.ArgumentParser(description="Liste les documents traités disponibles")
    parser.add_argument('--detailed', action='store_true', help='Affichage détaillé')

    args = parser.parse_args()

    try:
        list_documents(args.detailed)
    except Exception as e:
        print(f"❌ Erreur: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()