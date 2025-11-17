"""
Extraction de métadonnées depuis fichiers PPTX.

Module extrait de pptx_pipeline.py pour réutilisabilité.
"""

import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
import logging


def extract_pptx_metadata(
    pptx_path: Path,
    logger: Optional[logging.Logger] = None
) -> Dict[str, Any]:
    """
    Extrait les métadonnées depuis le fichier PPTX (docProps/core.xml + app.xml).

    Extrait notamment :
    - Date de modification (source_date)
    - Titre, créateur, version
    - Last modified by, reviewers (si disponibles)

    Args:
        pptx_path: Chemin vers le fichier PPTX
        logger: Logger optionnel pour les logs

    Returns:
        dict: Métadonnées extraites (titre, creator, source_date, version, etc.)

    Example:
        >>> metadata = extract_pptx_metadata(Path("presentation.pptx"))
        >>> print(metadata.get("title"))  # "SAP S/4HANA Overview"
    """
    try:
        metadata = {}

        with zipfile.ZipFile(pptx_path, "r") as pptx_zip:
            # === Extraction docProps/core.xml (métadonnées standard) ===
            if "docProps/core.xml" in pptx_zip.namelist():
                core_xml = pptx_zip.read("docProps/core.xml").decode("utf-8")
                root = ET.fromstring(core_xml)

                # Namespaces Office Open XML
                namespaces = {
                    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
                    "dc": "http://purl.org/dc/elements/1.1/",
                    "dcterms": "http://purl.org/dc/terms/",
                    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
                }

                # Date de modification (prioritaire pour source_date)
                modified_elem = root.find("dcterms:modified", namespaces)
                if modified_elem is not None and modified_elem.text:
                    try:
                        modified_str = modified_elem.text
                        modified_dt = datetime.fromisoformat(
                            modified_str.replace("Z", "+00:00")
                        )
                        metadata["source_date"] = modified_dt.strftime("%Y-%m-%d")
                        metadata["modified_at"] = modified_dt.isoformat()
                        if logger:
                            logger.info(
                                f"📅 Date de modification extraite: {metadata['source_date']}"
                            )
                    except Exception as e:
                        if logger:
                            logger.warning(f"Erreur parsing date modification: {e}")

                # Date de création
                created_elem = root.find("dcterms:created", namespaces)
                if created_elem is not None and created_elem.text:
                    try:
                        created_str = created_elem.text
                        created_dt = datetime.fromisoformat(
                            created_str.replace("Z", "+00:00")
                        )
                        metadata["created_at"] = created_dt.isoformat()
                        if logger:
                            logger.debug(
                                f"📅 Date de création extraite: {created_dt.strftime('%Y-%m-%d')}"
                            )
                    except Exception as e:
                        if logger:
                            logger.warning(f"Erreur parsing date création: {e}")

                # Titre
                title_elem = root.find("dc:title", namespaces)
                if title_elem is not None and title_elem.text:
                    metadata["title"] = title_elem.text.strip()
                    if logger:
                        logger.info(f"📄 Titre extrait: {metadata['title']}")

                # Créateur (auteur initial)
                creator_elem = root.find("dc:creator", namespaces)
                if creator_elem is not None and creator_elem.text:
                    metadata["creator"] = creator_elem.text.strip()
                    if logger:
                        logger.info(f"👤 Créateur extrait: {metadata['creator']}")

                # Last modified by (dernier modificateur)
                last_modified_by_elem = root.find("cp:lastModifiedBy", namespaces)
                if last_modified_by_elem is not None and last_modified_by_elem.text:
                    metadata["last_modified_by"] = last_modified_by_elem.text.strip()
                    if logger:
                        logger.debug(
                            f"👤 Dernier modificateur: {metadata['last_modified_by']}"
                        )

                # Version (si présente)
                version_elem = root.find("cp:version", namespaces)
                if version_elem is not None and version_elem.text:
                    metadata["version"] = version_elem.text.strip()
                    if logger:
                        logger.info(f"🔖 Version extraite: {metadata['version']}")

                # Révision (nombre de révisions)
                revision_elem = root.find("cp:revision", namespaces)
                if revision_elem is not None and revision_elem.text:
                    try:
                        metadata["revision"] = int(revision_elem.text)
                        if logger:
                            logger.debug(f"🔄 Révision: {metadata['revision']}")
                    except ValueError:
                        pass

                # Subject / Description
                subject_elem = root.find("dc:subject", namespaces)
                if subject_elem is not None and subject_elem.text:
                    metadata["subject"] = subject_elem.text.strip()
                    if logger:
                        logger.debug(f"📝 Sujet: {metadata['subject']}")

                description_elem = root.find("dc:description", namespaces)
                if description_elem is not None and description_elem.text:
                    metadata["description"] = description_elem.text.strip()
                    if logger:
                        logger.debug(
                            f"📝 Description extraite ({len(metadata['description'])} chars)"
                        )

            else:
                if logger:
                    logger.warning(f"Pas de métadonnées core.xml dans {pptx_path.name}")

            # === Extraction docProps/app.xml (propriétés application) ===
            if "docProps/app.xml" in pptx_zip.namelist():
                try:
                    app_xml = pptx_zip.read("docProps/app.xml").decode("utf-8")
                    app_root = ET.fromstring(app_xml)

                    # Namespace pour app.xml
                    app_ns = {
                        "vt": "http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes",
                        "ap": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties",
                    }

                    # Company (organisation)
                    company_elem = app_root.find("ap:Company", app_ns)
                    if company_elem is not None and company_elem.text:
                        metadata["company"] = company_elem.text.strip()
                        if logger:
                            logger.debug(f"🏢 Compagnie: {metadata['company']}")

                    # Manager (peut servir pour approver/reviewer)
                    manager_elem = app_root.find("ap:Manager", app_ns)
                    if manager_elem is not None and manager_elem.text:
                        metadata["manager"] = manager_elem.text.strip()
                        if logger:
                            logger.debug(f"👔 Manager: {metadata['manager']}")

                except Exception as e:
                    if logger:
                        logger.warning(f"Erreur parsing app.xml: {e}")

        # Fallback : Extraire version depuis filename si non trouvée dans metadata
        if "version" not in metadata:
            # Pattern: fichier_v1.0.pptx, fichier_version_1.2.pptx, etc.
            version_match = re.search(r"v(\d+\.\d+)", pptx_path.name, re.IGNORECASE)
            if version_match:
                metadata["version"] = version_match.group(1)
                if logger:
                    logger.info(f"🔖 Version extraite du filename: v{metadata['version']}")

        if logger:
            logger.info(
                f"✅ Métadonnées extraites: {len(metadata)} champs ({', '.join(metadata.keys())})"
            )

        return metadata

    except Exception as e:
        if logger:
            logger.warning(f"Erreur extraction métadonnées PPTX {pptx_path.name}: {e}")
        return {}
