#!/usr/bin/env python3
"""
Créer un fichier PPTX de test avec métadonnées pour valider l'extraction
"""

import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime

def create_minimal_pptx_with_metadata(output_path: Path):
    """Crée un PPTX minimal avec métadonnées pour tester l'extraction"""

    # Structure minimale d'un PPTX
    core_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
                   xmlns:dc="http://purl.org/dc/elements/1.1/"
                   xmlns:dcterms="http://purl.org/dc/terms/"
                   xmlns:dcmitype="http://purl.org/dc/dcmitype/"
                   xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
    <dc:creator>Test User</dc:creator>
    <dc:title>Test SAP Knowledge Base PPTX</dc:title>
    <dc:subject>Test d'extraction de métadonnées</dc:subject>
    <cp:keywords>SAP, Test, Metadata</cp:keywords>
    <dc:description>Fichier PPTX de test pour validation extraction automatique</dc:description>
    <cp:lastModifiedBy>Claude Code</cp:lastModifiedBy>
    <cp:revision>1</cp:revision>
    <dcterms:created xsi:type="dcterms:W3CDTF">2024-09-20T10:00:00Z</dcterms:created>
    <dcterms:modified xsi:type="dcterms:W3CDTF">2024-09-27T22:45:00Z</dcterms:modified>
    <cp:category>Test</cp:category>
</cp:coreProperties>"""

    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
    <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
    <Default Extension="xml" ContentType="application/xml"/>
    <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
    <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-presentationml.presentation.main+xml"/>
</Types>"""

    main_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
    <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
    <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""

    presentation_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
    <p:sldMasterIdLst/>
    <p:sldIdLst/>
    <p:sldSz cx="10000000" cy="7500000"/>
</p:presentation>"""

    try:
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            zipf.writestr('[Content_Types].xml', content_types)
            zipf.writestr('_rels/.rels', main_rels)
            zipf.writestr('docProps/core.xml', core_xml)
            zipf.writestr('ppt/presentation.xml', presentation_xml)

        print(f"OK PPTX de test cree: {output_path}")
        print(f"   Date de modification: 2024-09-27T22:45:00Z")
        print(f"   Titre: Test SAP Knowledge Base PPTX")
        return True

    except Exception as e:
        print(f"ERREUR creation PPTX: {e}")
        return False

def main():
    output_path = Path("C:/Project/SAP_KB/data/docs_in/test_metadata_extraction.pptx")

    print("Creation d'un fichier PPTX de test avec metadonnees...")
    print("=" * 60)

    # Créer le répertoire si nécessaire
    output_path.parent.mkdir(parents=True, exist_ok=True)

    success = create_minimal_pptx_with_metadata(output_path)

    if success:
        print(f"\nFichier pret pour test: {output_path}")
        print("   Utilisez ce fichier pour tester l'extraction automatique")
        print("   de source_date et eliminer la saisie manuelle.")
    else:
        print("\nEchec creation du fichier de test")

if __name__ == "__main__":
    main()