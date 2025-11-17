"""
Calcul de checksum SHA256 pour détection de duplicatas.

Module extrait de pptx_pipeline.py pour réutilisabilité.
"""

import hashlib
from pathlib import Path
from typing import Optional
import logging


def calculate_checksum(
    file_path: Path,
    logger: Optional[logging.Logger] = None
) -> str:
    """
    Calcule le checksum SHA256 d'un fichier pour détecter les duplicatas.

    Args:
        file_path: Chemin vers le fichier
        logger: Logger optionnel pour les logs

    Returns:
        Checksum SHA256 en hexadécimal (64 caractères)

    Raises:
        FileNotFoundError: Si le fichier n'existe pas
        IOError: Si la lecture échoue

    Example:
        >>> checksum = calculate_checksum(Path("/data/docs_in/presentation.pptx"))
        >>> print(checksum)  # "a3d5f6e8b9c1d2e3f4..."
    """
    if logger:
        logger.debug(f"🔐 Calcul checksum SHA256: {file_path.name}")

    sha256_hash = hashlib.sha256()

    try:
        with open(file_path, "rb") as f:
            # Lire par chunks de 4096 bytes pour économiser la mémoire
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)

        checksum = sha256_hash.hexdigest()

        if logger:
            logger.info(f"✅ Checksum calculé: {checksum[:16]}... ({file_path.name})")

        return checksum

    except Exception as e:
        if logger:
            logger.error(f"❌ Erreur calcul checksum pour {file_path.name}: {e}")
        raise
