#!/usr/bin/env python3
"""
Test de l'extraction automatique des métadonnées PPTX
"""

import sys
from pathlib import Path

# Ajout du chemin pour importer les modules du projet
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.knowbase.ingestion.pipelines.pptx_pipeline import extract_pptx_metadata

def test_extraction(pptx_path: Path):
    """Test la fonction d'extraction de métadonnées"""

    print(f"🧪 Test extraction métadonnées: {pptx_path.name}")
    print("=" * 50)

    if not pptx_path.exists():
        print(f"❌ Fichier non trouvé: {pptx_path}")
        return False

    try:
        metadata = extract_pptx_metadata(pptx_path)

        print(f"📊 Métadonnées extraites: {len(metadata)} champs")
        for key, value in metadata.items():
            print(f"   ✅ {key}: {value}")

        if 'source_date' in metadata:
            print(f"\n🎯 SUCCESS: source_date auto-extrait = {metadata['source_date']}")
            print("   → Plus besoin de saisie manuelle dans le frontend !")
            return True
        else:
            print("⚠️  source_date non trouvé dans les métadonnées")
            return False

    except Exception as e:
        print(f"❌ Erreur test: {e}")
        return False

def main():
    if len(sys.argv) < 2:
        print("Usage: python test_pptx_metadata_extraction.py FICHIER.pptx")
        print("\nCe script teste l'extraction automatique des métadonnées PPTX")
        print("notamment la source_date pour éliminer la saisie manuelle.")
        sys.exit(1)

    pptx_path = Path(sys.argv[1])
    success = test_extraction(pptx_path)

    if success:
        print("\n🎉 Test réussi - L'extraction automatique fonctionne !")
    else:
        print("\n❌ Test échoué - Vérifier le fichier PPTX")

if __name__ == "__main__":
    main()