"""
Nettoyage et validation des slides PPTX.

Module extrait de pptx_pipeline.py pour réutilisabilité.
Gère : slides cachés, GIF animés, validation média.
"""

import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import List, Tuple, Optional
import logging

from PIL import Image


def get_hidden_slides(
    pptx_path: Path,
    logger: Optional[logging.Logger] = None
) -> List[int]:
    """
    Identifie les slides cachés dans un PPTX en analysant la structure XML.

    Args:
        pptx_path: Chemin vers le fichier PPTX
        logger: Logger optionnel

    Returns:
        List[int]: Liste des numéros de slides cachés (1-indexé)
    """
    try:
        from pptx import Presentation

        prs = Presentation(str(pptx_path))
        presentation_part = prs.part
        presentation_element = presentation_part._element

        hidden_slides = []
        slide_elements = presentation_element.findall(
            ".//{http://schemas.openxmlformats.org/presentationml/2006/main}sldId"
        )

        for i, sld_id in enumerate(slide_elements, start=1):
            show_attr = sld_id.get("show", "1")
            if show_attr == "0":
                hidden_slides.append(i)
                if logger:
                    logger.debug(f"🙈 Slide {i}: détecté comme caché (show='0')")

        if hidden_slides and logger:
            logger.info(f"🙈 {len(hidden_slides)} slides cachés détectés: {hidden_slides}")

        return hidden_slides

    except Exception as e:
        if logger:
            logger.warning(f"⚠️ Impossible de détecter les slides cachés: {e}")
        return []


def remove_hidden_slides_inplace(
    pptx_path: Path,
    logger: Optional[logging.Logger] = None
) -> int:
    """
    Supprime directement les slides cachés du fichier PPTX uploadé.
    """
    try:
        from lxml import etree

        if logger:
            logger.info(f"🔍 Analyse des slides cachés dans {pptx_path.name}")

        with zipfile.ZipFile(pptx_path, "r") as zip_read:
            presentation_xml = zip_read.read("ppt/presentation.xml")

        root = etree.fromstring(presentation_xml)
        namespaces = {
            "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
            "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        }

        sld_id_lst = root.find(".//p:sldIdLst", namespaces)
        if sld_id_lst is None:
            return 0

        hidden_slides = []

        for i, sld_id in enumerate(sld_id_lst.findall("p:sldId", namespaces), 1):
            show_attr = sld_id.get("show", "1")
            if show_attr == "0":
                hidden_slides.append(i)

        if not hidden_slides:
            return 0

        if logger:
            logger.info(f"🗑️ Suppression de {len(hidden_slides)} slides cachés: {hidden_slides}")

        for sld_id in sld_id_lst.findall("p:sldId", namespaces):
            if sld_id.get("show") == "0":
                sld_id_lst.remove(sld_id)

        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as temp_file:
            temp_path = Path(temp_file.name)

        with zipfile.ZipFile(pptx_path, "r") as zip_read:
            with zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as zip_write:
                for item in zip_read.infolist():
                    content = zip_read.read(item.filename)

                    if item.filename == "ppt/presentation.xml":
                        content = etree.tostring(root, encoding="utf-8", xml_declaration=True)
                    elif item.filename.startswith("ppt/slides/slide") and item.filename.endswith(".xml"):
                        match = re.search(r"slide(\d+)\.xml", item.filename)
                        if match and int(match.group(1)) in hidden_slides:
                            continue
                    elif item.filename.startswith("ppt/slides/_rels/slide") and item.filename.endswith(".xml.rels"):
                        match = re.search(r"slide(\d+)\.xml\.rels", item.filename)
                        if match and int(match.group(1)) in hidden_slides:
                            continue

                    zip_write.writestr(item, content)

        shutil.move(str(temp_path), str(pptx_path))

        if logger:
            logger.info(f"✅ {len(hidden_slides)} slides cachés supprimés")
        return len(hidden_slides)

    except Exception as e:
        if logger:
            logger.error(f"❌ Erreur suppression slides cachés: {e}")
        return 0


def validate_pptx_media(
    pptx_path: Path,
    logger: Optional[logging.Logger] = None
) -> Tuple[bool, str]:
    """
    Valide les médias dans un PPTX avant conversion LibreOffice.
    Détecte les GIF animés volumineux qui causent des crashes.
    """
    try:
        with zipfile.ZipFile(pptx_path, 'r') as z:
            media_files = [f for f in z.namelist() if '/media/' in f]
            problematic_gifs = []

            for media_file in media_files:
                if media_file.lower().endswith('.gif'):
                    data = z.read(media_file)
                    size_mb = len(data) / (1024 * 1024)
                    is_animated = b'NETSCAPE2.0' in data

                    if size_mb > 5 or is_animated:
                        problematic_gifs.append({
                            'file': media_file,
                            'size_mb': size_mb,
                            'animated': is_animated
                        })

            if problematic_gifs:
                total_size = sum(g['size_mb'] for g in problematic_gifs)
                animated_count = sum(1 for g in problematic_gifs if g['animated'])
                reason = (
                    f"{len(problematic_gifs)} GIF(s) problématique(s) détecté(s) "
                    f"({total_size:.1f} MB total, {animated_count} animés)"
                )
                return True, reason

            return False, "OK - Aucun GIF problématique"

    except Exception as e:
        if logger:
            logger.warning(f"⚠️ Erreur validation médias PPTX: {e}")
        return False, "Validation skipped"


def strip_animated_gifs_from_pptx(
    pptx_path: Path,
    output_path: Path,
    logger: Optional[logging.Logger] = None
) -> Tuple[bool, str, int]:
    """
    Supprime/remplace les GIF animés d'un PPTX par des PNG (frame 0).
    """
    tmp_dir = None
    gif_converted_count = 0

    try:
        tmp_dir = tempfile.mkdtemp(prefix="pptx_strip_")

        with zipfile.ZipFile(pptx_path, 'r') as z:
            z.extractall(tmp_dir)

        media_dir = Path(tmp_dir) / "ppt" / "media"

        if not media_dir.exists():
            shutil.make_archive(str(output_path.with_suffix('')), 'zip', tmp_dir)
            shutil.move(str(output_path.with_suffix('.zip')), str(output_path))
            return True, "Aucun média à traiter", 0

        gif_replacements = {}

        for media_file in media_dir.iterdir():
            if media_file.suffix.lower() == '.gif':
                try:
                    img = Image.open(media_file)
                    img.seek(0)
                    png_path = media_file.with_suffix('.png')

                    if img.mode in ('P', 'LA'):
                        img = img.convert('RGBA')
                    elif img.mode == 'L':
                        img = img.convert('RGB')

                    img.save(png_path, 'PNG')
                    gif_replacements[media_file.name] = png_path.name
                    media_file.unlink()
                    gif_converted_count += 1

                    if logger:
                        logger.info(f"   ✅ {media_file.name} → {png_path.name}")

                except Exception as e:
                    if logger:
                        logger.warning(f"   ⚠️ Échec conversion {media_file.name}: {e}")

        if gif_replacements:
            if logger:
                logger.info(f"🔧 Mise à jour des relations XML ({len(gif_replacements)} références)")

            tmp_path = Path(tmp_dir)
            for rels_file in tmp_path.rglob('*.rels'):
                try:
                    content = rels_file.read_text(encoding='utf-8')
                    original_content = content

                    for gif_name, png_name in gif_replacements.items():
                        content = content.replace(f'/{gif_name}"', f'/{png_name}"')
                        content = content.replace(f'/{gif_name}\'', f'/{png_name}\'')
                        content = content.replace(f'="{gif_name}"', f'="{png_name}"')
                        content = content.replace(f'=\'{gif_name}\'', f'=\'{png_name}\'')

                    if content != original_content:
                        rels_file.write_text(content, encoding='utf-8')

                except Exception as e:
                    if logger:
                        logger.warning(f"   ⚠️ Échec mise à jour {rels_file.name}: {e}")

        shutil.make_archive(str(output_path.with_suffix('')), 'zip', tmp_dir)
        shutil.move(str(output_path.with_suffix('.zip')), str(output_path))

        message = f"{gif_converted_count} GIF(s) converti(s) en PNG" if gif_converted_count > 0 else "Aucun GIF détecté"
        return True, message, gif_converted_count

    except Exception as e:
        if logger:
            logger.error(f"❌ Erreur strip_animated_gifs_from_pptx: {e}")
        return False, f"Erreur: {str(e)}", 0

    finally:
        if tmp_dir and Path(tmp_dir).exists():
            try:
                shutil.rmtree(tmp_dir)
            except Exception:
                pass
