"""
Utilitaires pour le traitement d'images.

Module extrait de pptx_pipeline.py pour réutilisabilité.
"""

import base64
from pathlib import Path


def encode_image_base64(path: Path) -> str:
    """
    Encode une image en base64 pour envoi à l'API Vision.

    Args:
        path: Chemin vers le fichier image

    Returns:
        String base64 de l'image

    Raises:
        FileNotFoundError: Si le fichier n'existe pas
        IOError: Si la lecture échoue
    """
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def normalize_public_url(url: str) -> str:
    """
    Normalise une URL publique pour les assets (slides, thumbnails).

    Transforme les chemins Windows locaux en URLs HTTP accessibles.

    Args:
        url: URL ou chemin local à normaliser

    Returns:
        URL normalisée

    Example:
        >>> normalize_public_url("C:/data/public/slides/abc.png")
        "http://localhost:8000/public/slides/abc.png"
    """
    url = url.replace("\\", "/")
    if "/public/" in url:
        url = "http://localhost:8000" + url.split("/public/")[-1]
        if not url.startswith("http://localhost:8000/public/"):
            url = "http://localhost:8000/public/" + url.split("/public/")[-1]
    return url
