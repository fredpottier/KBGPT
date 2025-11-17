"""
Conversion PPTX vers PDF via LibreOffice.

Module extrait de pptx_pipeline.py pour réutilisabilité.
"""

import os
import shutil
from pathlib import Path
from typing import Optional
import logging

from ..extractors.slide_cleaner import validate_pptx_media, strip_animated_gifs_from_pptx
from ..utils.subprocess_utils import run_cmd


def resolve_soffice_path() -> str:
    """
    Résout le chemin vers LibreOffice/soffice.

    Returns:
        str: Chemin absolu vers soffice
    """
    cand = os.getenv("SOFFICE_PATH", "").strip()
    if cand and Path(cand).exists():
        return cand
    found = shutil.which("soffice") or shutil.which("libreoffice")
    return found or "/usr/bin/soffice"


def convert_pptx_to_pdf(
    pptx_path: Path,
    output_dir: Path,
    logger: Optional[logging.Logger] = None,
    soffice_path: Optional[str] = None
) -> Optional[Path]:
    """
    Convertit un PPTX en PDF via LibreOffice.

    Args:
        pptx_path: Chemin vers le fichier PPTX
        output_dir: Répertoire de sortie pour le PDF
        logger: Logger optionnel
        soffice_path: Chemin vers soffice (auto-détecté si None)

    Returns:
        Path: Chemin vers le PDF généré, ou None si échec (fallback TEXT-ONLY)

    Note:
        Retourne None en cas d'échec pour activer le mode TEXT-ONLY
        (extraction sans Vision API)
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    if logger:
        logger.info(f"📄 Conversion PPTX→PDF: {pptx_path.name}")

    # Auto-détection du chemin soffice si non fourni
    if soffice_path is None:
        soffice_path = resolve_soffice_path()

    # Pré-validation: détecter GIF animés problématiques
    has_problematic_gifs, validation_reason = validate_pptx_media(pptx_path, logger)

    cleaned_pptx_path = None
    pptx_to_convert = pptx_path

    if has_problematic_gifs:
        if logger:
            logger.warning(f"⚠️ Prévalidation PPTX: {validation_reason}")
            logger.info("🎨 Nettoyage automatique : conversion GIF → PNG (frame 0)")

        cleaned_pptx_path = pptx_path.parent / f"{pptx_path.stem}_cleaned.pptx"

        success, strip_message, gif_count = strip_animated_gifs_from_pptx(
            pptx_path, cleaned_pptx_path, logger
        )

        if success and gif_count > 0:
            if logger:
                logger.info(f"✅ PPTX nettoyé créé : {strip_message}")
            pptx_to_convert = cleaned_pptx_path
        elif not success:
            if logger:
                logger.warning(f"⚠️ Échec nettoyage PPTX : {strip_message}")
                logger.info("📋 Fallback TEXT-ONLY activé")
            return None

    # Configuration environnement pour LibreOffice headless
    env = os.environ.copy()
    env.update({
        "HOME": "/tmp",
        "DISPLAY": "",
        "SAL_USE_VCLPLUGIN": "svp",
    })

    # Commande de conversion
    command = [
        soffice_path,
        "--headless",
        "--invisible",
        "--nodefault",
        "--nolockcheck",
        "--nologo",
        "--norestore",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir),
        str(pptx_to_convert),
    ]

    if logger:
        logger.debug(f"🔧 Commande LibreOffice: {' '.join(command)}")

    # Tentative de conversion (timeout 10 minutes)
    result = run_cmd(command, timeout=600, env=env)

    # Déterminer le chemin du PDF généré
    if cleaned_pptx_path:
        pdf_path_generated = output_dir / (cleaned_pptx_path.stem + ".pdf")
        pdf_path_final = output_dir / (pptx_path.stem + ".pdf")
    else:
        pdf_path_generated = output_dir / (pptx_path.stem + ".pdf")
        pdf_path_final = pdf_path_generated

    # Vérifier le succès
    if result.returncode != 0 or not pdf_path_generated.exists():
        # Cleanup
        if cleaned_pptx_path and cleaned_pptx_path.exists():
            try:
                cleaned_pptx_path.unlink()
            except Exception:
                pass

        if logger:
            logger.warning(f"⚠️ Échec conversion PPTX→PDF (fallback TEXT-ONLY)")
            logger.warning(f"   - Return code: {result.returncode}")
            logger.warning(f"   - PDF attendu: {pdf_path_generated} (existe: {pdf_path_generated.exists()})")
            logger.info("📋 Fallback automatique : extraction TEXTE uniquement")

        return None

    # Renommer le PDF si nécessaire
    if cleaned_pptx_path and pdf_path_generated != pdf_path_final:
        try:
            pdf_path_generated.rename(pdf_path_final)
            if logger:
                logger.debug(f"📝 PDF renommé : {pdf_path_generated.name} → {pdf_path_final.name}")
        except Exception:
            pdf_path_final = pdf_path_generated

    # Cleanup du PPTX nettoyé après conversion réussie
    if cleaned_pptx_path and cleaned_pptx_path.exists():
        try:
            cleaned_pptx_path.unlink()
        except Exception:
            pass

    if logger:
        logger.debug(f"✅ PDF créé: {pdf_path_final} (exists={pdf_path_final.exists()})")

    return pdf_path_final
