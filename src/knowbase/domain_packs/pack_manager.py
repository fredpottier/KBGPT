# src/knowbase/domain_packs/pack_manager.py
"""
PackManager — Gestion du cycle de vie Docker des Domain Packs.

Install (build image) → Activate (start container) → Deactivate (stop) → Uninstall (rm image).

Le Docker socket doit être monté dans le container app pour que
le PackManager puisse piloter les containers sidecar.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Optional

from knowbase.domain_packs.manifest import PackManifest, PackState

logger = logging.getLogger(__name__)

# Répertoire de stockage des packs installés
PACKS_DIR = Path("/data/packs")
DOCKER_NETWORK = "knowbase_network"


class PackManager:
    """
    Gère le cycle de vie Docker des Domain Packs.

    Install: extrait le .osmpack → build l'image Docker
    Activate: démarre le container sur le réseau knowbase
    Deactivate: arrête le container
    Uninstall: supprime l'image + les fichiers
    """

    def __init__(self, packs_dir: Path = PACKS_DIR):
        self.packs_dir = packs_dir
        self.packs_dir.mkdir(parents=True, exist_ok=True)

    def _container_name(self, pack_name: str) -> str:
        return f"osmose-pack-{pack_name}"

    def _image_name(self, pack_name: str) -> str:
        return f"osmose-pack-{pack_name}:latest"

    def _pack_dir(self, pack_name: str) -> Path:
        return self.packs_dir / pack_name

    # =========================================================================
    # Install
    # =========================================================================

    def install_from_zip(self, zip_path: Path) -> PackManifest:
        """
        Installe un pack depuis un fichier .osmpack (zip).

        1. Extrait le zip dans data/packs/<name>/
        2. Valide le manifest.json
        3. Build l'image Docker

        Returns:
            PackManifest du pack installé
        """
        # Extraire dans un dossier temporaire pour lire le manifest
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmpdir)

            tmp_path = Path(tmpdir)

            # Chercher le manifest (peut être à la racine ou dans un sous-dossier)
            manifest_path = tmp_path / "manifest.json"
            if not manifest_path.exists():
                # Chercher dans le premier sous-dossier
                subdirs = [d for d in tmp_path.iterdir() if d.is_dir()]
                if subdirs:
                    manifest_path = subdirs[0] / "manifest.json"
                    tmp_path = subdirs[0]

            if not manifest_path.exists():
                raise ValueError("manifest.json non trouvé dans le pack")

            manifest = PackManifest(**json.loads(manifest_path.read_text("utf-8")))

            # Copier vers le dossier permanent
            dest = self._pack_dir(manifest.name)
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(tmp_path, dest)

        logger.info(f"[PackManager] Pack '{manifest.name}' extrait dans {dest}")

        # Build l'image Docker
        self._build_image(manifest.name)

        return manifest

    def install_builtin(self, pack_name: str) -> Optional[PackManifest]:
        """
        Installe un pack intégré (déjà présent dans le code source).

        Copie les fichiers depuis src/knowbase/domain_packs/<name>/
        vers data/packs/<name>/ et build l'image.
        """
        # Chercher le pack dans les sources
        source_dir = Path(__file__).parent / pack_name
        manifest_path = source_dir / "manifest.json"

        if not manifest_path.exists():
            logger.debug(f"[PackManager] No builtin pack at {source_dir}")
            return None

        manifest = PackManifest(**json.loads(manifest_path.read_text("utf-8")))

        # Copier vers le dossier permanent
        dest = self._pack_dir(manifest.name)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(source_dir, dest)

        logger.info(f"[PackManager] Builtin pack '{manifest.name}' copied to {dest}")

        # Build l'image Docker
        self._build_image(manifest.name)

        return manifest

    def _build_image(self, pack_name: str) -> bool:
        """Build l'image Docker du pack."""
        pack_dir = self._pack_dir(pack_name)
        dockerfile = pack_dir / "Dockerfile"

        if not dockerfile.exists():
            logger.error(f"[PackManager] No Dockerfile in {pack_dir}")
            return False

        image_name = self._image_name(pack_name)
        cmd = ["docker", "build", "-t", image_name, str(pack_dir)]

        logger.info(f"[PackManager] Building image {image_name}...")
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600
            )
            if result.returncode != 0:
                logger.error(
                    f"[PackManager] Build failed: {result.stderr[:500]}"
                )
                return False
            logger.info(f"[PackManager] Image {image_name} built successfully")
            return True
        except subprocess.TimeoutExpired:
            logger.error(f"[PackManager] Build timeout for {image_name}")
            return False

    # =========================================================================
    # Activate / Deactivate
    # =========================================================================

    def activate(self, pack_name: str) -> bool:
        """Démarre le container du pack et attend le health check."""
        manifest = self.get_manifest(pack_name)
        if not manifest:
            logger.error(f"[PackManager] Pack '{pack_name}' not installed")
            return False

        container_name = self._container_name(pack_name)
        image_name = self._image_name(pack_name)

        # Arrêter et supprimer si existant
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True, timeout=30,
        )

        # Démarrer le container
        port = manifest.container.port
        mem = manifest.container.memory_limit
        cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "--network", DOCKER_NETWORK,
            "--memory", mem,
            "--restart", "unless-stopped",
            image_name,
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                logger.error(
                    f"[PackManager] Start failed: {result.stderr[:300]}"
                )
                return False
        except subprocess.TimeoutExpired:
            logger.error(f"[PackManager] Start timeout for {container_name}")
            return False

        logger.info(
            f"[PackManager] Container {container_name} started "
            f"(port {port}, mem {mem})"
        )

        # Health check (attendre jusqu'à 30s)
        return self._wait_healthy(pack_name, timeout_s=30)

    def deactivate(self, pack_name: str) -> bool:
        """Arrête le container du pack."""
        container_name = self._container_name(pack_name)

        try:
            result = subprocess.run(
                ["docker", "stop", container_name],
                capture_output=True, text=True, timeout=30,
            )
            subprocess.run(
                ["docker", "rm", container_name],
                capture_output=True, timeout=10,
            )
            logger.info(f"[PackManager] Container {container_name} stopped")
            return True
        except Exception as e:
            logger.error(f"[PackManager] Stop error: {e}")
            return False

    def _wait_healthy(self, pack_name: str, timeout_s: int = 30) -> bool:
        """Attend que le container réponde au health check."""
        import time
        import urllib.request

        manifest = self.get_manifest(pack_name)
        if not manifest:
            return False

        container_name = self._container_name(pack_name)
        health_url = (
            f"http://{container_name}:{manifest.container.port}"
            f"{manifest.container.health_endpoint}"
        )

        start = time.time()
        while time.time() - start < timeout_s:
            try:
                req = urllib.request.urlopen(health_url, timeout=2)
                if req.status == 200:
                    logger.info(
                        f"[PackManager] {container_name} healthy"
                    )
                    return True
            except Exception:
                pass
            time.sleep(1)

        logger.error(
            f"[PackManager] {container_name} did not become healthy "
            f"within {timeout_s}s"
        )
        return False

    # =========================================================================
    # Uninstall
    # =========================================================================

    def uninstall(self, pack_name: str) -> bool:
        """Supprime le container, l'image et les fichiers du pack."""
        container_name = self._container_name(pack_name)
        image_name = self._image_name(pack_name)

        # Stop + remove container
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True, timeout=30,
        )

        # Remove image
        subprocess.run(
            ["docker", "rmi", image_name],
            capture_output=True, timeout=30,
        )

        # Remove files
        pack_dir = self._pack_dir(pack_name)
        if pack_dir.exists():
            shutil.rmtree(pack_dir)

        logger.info(f"[PackManager] Pack '{pack_name}' uninstalled")
        return True

    # =========================================================================
    # Queries
    # =========================================================================

    def get_manifest(self, pack_name: str) -> Optional[PackManifest]:
        """Charge le manifest d'un pack installé."""
        manifest_path = self._pack_dir(pack_name) / "manifest.json"
        if not manifest_path.exists():
            return None
        try:
            return PackManifest(**json.loads(manifest_path.read_text("utf-8")))
        except Exception as e:
            logger.error(f"[PackManager] Invalid manifest for '{pack_name}': {e}")
            return None

    def list_installed(self) -> list[PackManifest]:
        """Liste tous les packs installés."""
        manifests = []
        if not self.packs_dir.exists():
            return manifests
        for d in self.packs_dir.iterdir():
            if d.is_dir():
                m = self.get_manifest(d.name)
                if m:
                    manifests.append(m)
        return manifests

    def get_state(self, pack_name: str) -> str:
        """Retourne l'état d'un pack."""
        if not self.get_manifest(pack_name):
            return PackState.NOT_INSTALLED

        container_name = self._container_name(pack_name)
        try:
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and "true" in result.stdout.lower():
                return PackState.ACTIVE
        except Exception:
            pass

        return PackState.INSTALLED

    def get_container_url(self, pack_name: str) -> Optional[str]:
        """Retourne l'URL interne du container pour les appels HTTP."""
        manifest = self.get_manifest(pack_name)
        if not manifest:
            return None
        container_name = self._container_name(pack_name)
        return f"http://{container_name}:{manifest.container.port}"


# Singleton
_manager_instance: Optional[PackManager] = None


def get_pack_manager() -> PackManager:
    """Retourne l'instance singleton du PackManager."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = PackManager()
    return _manager_instance


__all__ = ["PackManager", "get_pack_manager"]
