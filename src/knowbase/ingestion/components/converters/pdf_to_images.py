"""
Conversion PDF vers images PNG via PyMuPDF.

Module extrait de pptx_pipeline.py pour réutilisabilité.
"""

import io
from pathlib import Path
from typing import List, Optional, Any
import logging

import fitz  # PyMuPDF
from PIL import Image


def convert_pdf_to_images_pymupdf(
    pdf_path: str,
    dpi: int = 150,
    rq_job: Optional[Any] = None,
    logger: Optional[logging.Logger] = None
) -> List[Image.Image]:
    """
    Convertit un PDF en images PIL avec PyMuPDF (plus rapide que pdf2image).
    Compatible avec l'API de pdf2image convert_from_path.

    Args:
        pdf_path: Chemin vers le fichier PDF (string)
        dpi: Résolution des images (défaut: 150)
        rq_job: Job RQ pour les heartbeats (optionnel)
        logger: Logger optionnel

    Returns:
        List[PIL.Image]: Liste d'images PIL (comme convert_from_path)

    Note:
        Envoie des heartbeats RQ toutes les 30 pages si rq_job fourni
    """
    if logger:
        logger.info(f"🔄 Conversion PDF→Images PyMuPDF: {Path(pdf_path).name} (DPI: {dpi})")

    try:
        # Ouvrir le document PDF
        doc = fitz.open(pdf_path)
        total_pages = len(doc)

        if logger:
            logger.info(f"📄 {total_pages} pages détectées dans le PDF")

        # Facteur d'échelle basé sur le DPI (72 DPI = facteur 1.0)
        zoom_factor = dpi / 72.0
        mat = fitz.Matrix(zoom_factor, zoom_factor)

        images = []

        for page_num in range(total_pages):
            try:
                # Envoyer un heartbeat périodiquement (toutes les 30 pages)
                if rq_job and page_num % 30 == 0:
                    try:
                        # Essayer l'ancienne API d'abord
                        rq_job.heartbeat()
                        if logger:
                            logger.debug(f"Heartbeat envoyé - page {page_num + 1}/{total_pages}")
                    except TypeError:
                        # Nouvelle API RQ : heartbeat avec datetime et ttl
                        try:
                            from datetime import datetime, timezone
                            rq_job.heartbeat(
                                timestamp=datetime.now(timezone.utc), ttl=600
                            )
                            if logger:
                                logger.debug(f"Heartbeat envoyé (nouvelle API) - page {page_num + 1}/{total_pages}")
                        except Exception as e:
                            if logger:
                                logger.debug(f"Erreur heartbeat nouvelle API: {e}")
                    except Exception as e:
                        if logger:
                            logger.debug(f"Erreur heartbeat: {e}")

                page = doc[page_num]
                pix = page.get_pixmap(matrix=mat)

                # Convertir en PIL Image
                img_data = pix.tobytes("ppm")
                img = Image.open(io.BytesIO(img_data))

                images.append(img)

                # Libérer la mémoire du pixmap
                pix = None

            except Exception as e:
                if logger:
                    logger.error(f"❌ Erreur conversion page {page_num + 1}: {e}")
                continue

        doc.close()

        if logger:
            logger.info(f"✅ Conversion PyMuPDF terminée: {len(images)} images générées")

        return images

    except Exception as e:
        if logger:
            logger.error(f"❌ Erreur PyMuPDF: {e}")
        raise
