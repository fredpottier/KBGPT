"""
Utilitaires pour l'exécution de commandes subprocess.

Module extrait de pptx_pipeline.py pour réutilisabilité.
"""

import subprocess
from typing import Optional, Dict


def run_cmd(
    cmd: list[str],
    timeout: int = 120,
    env: Optional[Dict[str, str]] = None
) -> subprocess.CompletedProcess:
    """
    Exécute une commande subprocess avec timeout.

    Args:
        cmd: Liste des arguments de la commande
        timeout: Timeout en secondes (défaut: 120s)
        env: Variables d'environnement optionnelles

    Returns:
        CompletedProcess avec stdout, stderr, returncode

    Raises:
        subprocess.TimeoutExpired: Si la commande dépasse le timeout
        subprocess.CalledProcessError: Si la commande échoue
    """
    return subprocess.run(
        cmd,
        env=env,
        timeout=timeout,
        check=False,  # Ne pas lever d'exception automatiquement
        capture_output=True,
        text=True
    )
