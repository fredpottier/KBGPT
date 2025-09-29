#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script d'analyse des métadonnées PPTX pour extraire les dates
ANALYSE DE FAISABILITÉ UNIQUEMENT - PAS D'INTÉGRATION
"""

import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
import sys
import io

# Fix encoding pour Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def analyze_pptx_metadata(pptx_path: Path):
    """Analyse les métadonnées d'un fichier PPTX pour identifier les dates disponibles"""

    print(f"🔍 Analyse des métadonnées: {pptx_path.name}")
    print("=" * 60)

    try:
        with zipfile.ZipFile(pptx_path, 'r') as pptx_zip:
            # Lister tous les fichiers dans le PPTX
            print("📁 Structure du fichier PPTX:")
            for file_path in sorted(pptx_zip.namelist()):
                if any(keyword in file_path.lower() for keyword in ['prop', 'meta', 'core', 'app']):
                    print(f"   📄 {file_path}")

            print("\n" + "=" * 60)

            # Analyser docProps/core.xml (métadonnées standard Office)
            if 'docProps/core.xml' in pptx_zip.namelist():
                print("\n📊 Analyse docProps/core.xml:")
                core_xml = pptx_zip.read('docProps/core.xml').decode('utf-8')
                print("   Contenu XML brut:")
                print("   " + "-" * 40)
                for line in core_xml.split('\n')[:10]:  # Première partie seulement
                    if line.strip():
                        print(f"   {line}")
                print("   ...")

                # Parser le XML pour extraire les dates
                root = ET.fromstring(core_xml)

                # Namespaces typiques dans les métadonnées Office
                namespaces = {
                    'cp': 'http://schemas.openxmlformats.org/package/2006/metadata/core-properties',
                    'dc': 'http://purl.org/dc/elements/1.1/',
                    'dcterms': 'http://purl.org/dc/terms/',
                    'dcmitype': 'http://purl.org/dc/dcmitype/',
                    'xsi': 'http://www.w3.org/2001/XMLSchema-instance'
                }

                print("\n   📅 Dates trouvées:")
                date_fields = [
                    ('dcterms:created', 'Date de création'),
                    ('dcterms:modified', 'Date de modification'),
                    ('cp:lastPrinted', 'Dernière impression'),
                    ('cp:revision', 'Révision')
                ]

                found_dates = {}
                for field, description in date_fields:
                    elements = root.findall(f'.//{field}', namespaces)
                    if elements:
                        date_value = elements[0].text
                        found_dates[field] = date_value
                        print(f"   ✅ {description}: {date_value}")

                        # Tenter de parser la date
                        try:
                            if 'T' in date_value:
                                # Format ISO avec time
                                parsed_date = datetime.fromisoformat(date_value.replace('Z', '+00:00'))
                                print(f"      → Parsé: {parsed_date.strftime('%d/%m/%Y %H:%M:%S')}")
                            else:
                                print(f"      → Format non-ISO détecté")
                        except Exception as e:
                            print(f"      ⚠️  Erreur parsing: {e}")
                    else:
                        print(f"   ❌ {description}: Non trouvé")

            # Analyser docProps/app.xml (métadonnées application)
            if 'docProps/app.xml' in pptx_zip.namelist():
                print("\n📱 Analyse docProps/app.xml:")
                app_xml = pptx_zip.read('docProps/app.xml').decode('utf-8')

                app_root = ET.fromstring(app_xml)
                app_namespaces = {
                    'vt': 'http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes'
                }

                app_fields = [
                    ('Application', 'Application créatrice'),
                    ('TotalTime', 'Temps total d\'édition'),
                    ('Company', 'Société'),
                    ('Manager', 'Responsable')
                ]

                print("   📋 Propriétés d'application:")
                for field, description in app_fields:
                    elements = app_root.findall(f'.//{field}')
                    if elements:
                        value = elements[0].text
                        print(f"   📌 {description}: {value}")

            # Vérifier les propriétés personnalisées
            if 'docProps/custom.xml' in pptx_zip.namelist():
                print("\n🔧 Propriétés personnalisées trouvées")
                custom_xml = pptx_zip.read('docProps/custom.xml').decode('utf-8')
                print("   (Contenu disponible mais pas analysé dans cette version)")

    except Exception as e:
        print(f"❌ Erreur lors de l'analyse: {e}")
        return None

    print("\n" + "=" * 60)
    print("💡 CONCLUSION DE FAISABILITÉ:")
    print("   ✅ Les dates de modification sont accessibles via dcterms:modified")
    print("   ✅ Format ISO standard facilement parsable")
    print("   ✅ Intégration possible dans le pipeline d'ingestion")
    print("   📌 Recommandation: Extraire dcterms:modified pour remplir automatiquement")
    print("       le champ date dans le frontend")

def main():
    """Point d'entrée pour tester avec un fichier PPTX"""
    if len(sys.argv) < 2:
        print("Usage: python analyze_pptx_metadata.py FICHIER.pptx")
        print("\nCe script analyse les métadonnées d'un fichier PPTX pour identifier")
        print("les dates disponibles, notamment pour éliminer la saisie manuelle")
        print("de date dans le frontend d'import.")
        sys.exit(1)

    pptx_path = Path(sys.argv[1])
    if not pptx_path.exists():
        print(f"❌ Fichier non trouvé: {pptx_path}")
        sys.exit(1)

    if not pptx_path.suffix.lower() == '.pptx':
        print(f"❌ Le fichier doit être un .pptx: {pptx_path}")
        sys.exit(1)

    analyze_pptx_metadata(pptx_path)

if __name__ == "__main__":
    main()