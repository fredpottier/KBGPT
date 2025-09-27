#!/usr/bin/env python3
"""
Démonstration de l'extraction des métadonnées PPTX
Montre comment extraire la date de modification pour éliminer la saisie manuelle
"""

from datetime import datetime
import xml.etree.ElementTree as ET

# Exemple de contenu typique de docProps/core.xml dans un fichier PPTX
EXEMPLE_CORE_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
                   xmlns:dc="http://purl.org/dc/elements/1.1/"
                   xmlns:dcterms="http://purl.org/dc/terms/"
                   xmlns:dcmitype="http://purl.org/dc/dcmitype/"
                   xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
    <dc:creator>Jean Dupont</dc:creator>
    <dc:title>Présentation SAP S/4HANA</dc:title>
    <dc:subject>Migration SAP</dc:subject>
    <cp:keywords>SAP, S/4HANA, Migration, ERP</cp:keywords>
    <dc:description>Guide de migration vers SAP S/4HANA</dc:description>
    <cp:lastModifiedBy>Marie Martin</cp:lastModifiedBy>
    <cp:revision>5</cp:revision>
    <dcterms:created xsi:type="dcterms:W3CDTF">2024-09-15T10:30:00Z</dcterms:created>
    <dcterms:modified xsi:type="dcterms:W3CDTF">2024-09-20T14:45:30Z</dcterms:modified>
    <cp:category>Documentation</cp:category>
</cp:coreProperties>"""

def extract_pptx_modification_date(core_xml_content: str) -> dict:
    """
    Extrait les informations de date depuis le XML de métadonnées PPTX

    Returns:
        dict: Informations extraites incluant la date de modification
    """
    try:
        root = ET.fromstring(core_xml_content)

        # Namespaces Office Open XML
        namespaces = {
            'cp': 'http://schemas.openxmlformats.org/package/2006/metadata/core-properties',
            'dc': 'http://purl.org/dc/elements/1.1/',
            'dcterms': 'http://purl.org/dc/terms/',
            'dcmitype': 'http://purl.org/dc/dcmitype/',
            'xsi': 'http://www.w3.org/2001/XMLSchema-instance'
        }

        # Extraction des informations clés
        metadata = {}

        # Date de modification (celle qui nous intéresse pour le frontend)
        modified_elem = root.find('dcterms:modified', namespaces)
        if modified_elem is not None:
            modified_str = modified_elem.text
            # Conversion ISO → datetime Python
            modified_dt = datetime.fromisoformat(modified_str.replace('Z', '+00:00'))
            metadata['modified_date'] = modified_dt
            metadata['modified_date_str'] = modified_dt.strftime('%Y-%m-%d')  # Format pour le frontend
            metadata['modified_date_display'] = modified_dt.strftime('%d/%m/%Y à %H:%M')

        # Autres dates utiles
        created_elem = root.find('dcterms:created', namespaces)
        if created_elem is not None:
            created_str = created_elem.text
            created_dt = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
            metadata['created_date'] = created_dt

        # Informations supplémentaires
        title_elem = root.find('dc:title', namespaces)
        if title_elem is not None:
            metadata['title'] = title_elem.text

        creator_elem = root.find('dc:creator', namespaces)
        if creator_elem is not None:
            metadata['creator'] = creator_elem.text

        last_modified_by_elem = root.find('cp:lastModifiedBy', namespaces)
        if last_modified_by_elem is not None:
            metadata['last_modified_by'] = last_modified_by_elem.text

        revision_elem = root.find('cp:revision', namespaces)
        if revision_elem is not None:
            metadata['revision'] = revision_elem.text

        return metadata

    except Exception as e:
        print(f"ERREUR extraction metadonnees: {e}")
        return {}

def demo_metadata_extraction():
    """Démonstration de l'extraction de métadonnées"""

    print("DEMONSTRATION - Extraction metadonnees PPTX")
    print("=" * 60)

    print("XML de metadonnees exemple (docProps/core.xml):")
    print("-" * 40)
    for i, line in enumerate(EXEMPLE_CORE_XML.split('\n')[1:8], 1):  # Premières lignes
        print(f"{i:2}| {line}")
    print("   | ...")

    print("\nExtraction des informations:")
    print("-" * 40)

    metadata = extract_pptx_modification_date(EXEMPLE_CORE_XML)

    if metadata:
        print(f"OK Titre: {metadata.get('title', 'N/A')}")
        print(f"OK Createur: {metadata.get('creator', 'N/A')}")
        print(f"OK Derniere modification par: {metadata.get('last_modified_by', 'N/A')}")
        print(f"OK Revision: {metadata.get('revision', 'N/A')}")
        print(f"OK Date de creation: {metadata.get('created_date', 'N/A')}")

        print(f"\nDATE DE MODIFICATION CIBLE:")
        print(f"   Date brute: {metadata.get('modified_date', 'N/A')}")
        print(f"   Format frontend: {metadata.get('modified_date_str', 'N/A')}")
        print(f"   Affichage utilisateur: {metadata.get('modified_date_display', 'N/A')}")

    print("\n" + "=" * 60)
    print("IMPLEMENTATION RECOMMANDEE:")
    print("   1. Ajouter fonction extract_pptx_metadata() dans pptx_pipeline.py")
    print("   2. Extraire date avant processing MegaParse")
    print("   3. Inclure dans job_metadata pour transmission au frontend")
    print("   4. Frontend: pre-remplir champ date si disponible")
    print("   5. Fallback: demander date manuellement si extraction echoue")

    print("\nINTEGRATION DANS LE PIPELINE:")
    print("   OK Etape 1: Ouvrir PPTX comme ZIP")
    print("   OK Etape 2: Lire docProps/core.xml")
    print("   OK Etape 3: Extraire dcterms:modified")
    print("   OK Etape 4: Convertir en format date frontend")
    print("   OK Etape 5: Passer a l'interface utilisateur")

    print("\nAVANTAGES:")
    print("   - Elimination saisie manuelle date (gain UX)")
    print("   - Date precise et fiable")
    print("   - Pas d'impact performance (lecture ZIP rapide)")
    print("   - Compatible tous fichiers PPTX standards")

if __name__ == "__main__":
    demo_metadata_extraction()