"""
Gestionnaire de modèles d'embedding avec déchargement automatique GPU.

Phase 2.x: Ajout du mécanisme de timeout pour libérer la mémoire GPU
après une période d'inactivité (utile en développement).
"""

from __future__ import annotations

import gc
import logging
import threading
import time
from typing import Optional, List

from knowbase.config.settings import get_settings

logger = logging.getLogger(__name__)

# Configuration du timeout (en secondes)
# Peut être surchargé via variable d'environnement GPU_UNLOAD_TIMEOUT_MINUTES
DEFAULT_UNLOAD_TIMEOUT_MINUTES = 10


class EmbeddingModelManager:
    """
    Gestionnaire singleton pour le modèle d'embedding avec déchargement automatique.

    Fonctionnalités:
    - Chargement lazy du modèle
    - Déchargement automatique après X minutes d'inactivité
    - Méthode manuelle pour forcer le déchargement
    - Thread-safe
    """

    _instance: Optional["EmbeddingModelManager"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._model = None
        self._model_name: Optional[str] = None
        self._device: Optional[str] = None
        self._last_access_time: float = 0
        self._model_lock = threading.Lock()
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_monitor = threading.Event()

        # Timeout configurable (défaut: 10 minutes)
        settings = get_settings()
        timeout_env = getattr(settings, 'gpu_unload_timeout_minutes', None)
        self._timeout_seconds = (timeout_env or DEFAULT_UNLOAD_TIMEOUT_MINUTES) * 60

        self._initialized = True
        logger.info(
            f"[EMBEDDINGS] Manager initialized "
            f"(auto-unload after {self._timeout_seconds // 60} min inactivity)"
        )

    def get_model(
        self,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
        cache_folder: Optional[str] = None,
    ):
        """
        Récupère le modèle d'embedding, le charge si nécessaire.

        Args:
            model_name: Nom du modèle (défaut: settings.embeddings_model)
            device: Device cible (cuda, cpu, etc.)
            cache_folder: Dossier de cache pour les modèles

        Returns:
            SentenceTransformer model
        """
        from sentence_transformers import SentenceTransformer

        settings = get_settings()
        name = model_name or settings.embeddings_model

        with self._model_lock:
            # Mettre à jour le temps d'accès
            self._last_access_time = time.time()

            # Si le modèle est déjà chargé avec les mêmes paramètres
            if self._model is not None and self._model_name == name:
                return self._model

            # Décharger l'ancien modèle si différent
            if self._model is not None and self._model_name != name:
                self._unload_model_internal()

            # Charger le nouveau modèle
            logger.info(f"[EMBEDDINGS] Loading model: {name}")
            start_time = time.time()

            kwargs: dict[str, object] = {}
            if device is not None:
                kwargs["device"] = device
            if cache_folder is not None:
                kwargs["cache_folder"] = cache_folder

            self._model = SentenceTransformer(name, **kwargs)
            self._model_name = name
            self._device = device

            load_time = time.time() - start_time
            logger.info(f"[EMBEDDINGS] Model loaded in {load_time:.1f}s")

            # Démarrer le thread de surveillance si pas déjà actif
            self._start_monitor()

            return self._model

    def encode(
        self,
        sentences: List[str],
        **kwargs
    ):
        """
        Encode des phrases avec le modèle d'embedding.

        Args:
            sentences: Liste de phrases à encoder
            **kwargs: Arguments passés à model.encode()

        Returns:
            Embeddings numpy array
        """
        model = self.get_model()

        with self._model_lock:
            self._last_access_time = time.time()

        return model.encode(sentences, **kwargs)

    def unload_model(self):
        """
        Force le déchargement du modèle et libère la mémoire GPU.
        Peut être appelé manuellement.
        """
        with self._model_lock:
            self._unload_model_internal()

    def _unload_model_internal(self):
        """Décharge le modèle (appelé avec le lock déjà acquis)."""
        if self._model is None:
            return

        logger.info(f"[EMBEDDINGS] Unloading model: {self._model_name}")

        # Supprimer la référence au modèle
        model_name = self._model_name
        self._model = None
        self._model_name = None
        self._device = None

        # Forcer le garbage collection
        gc.collect()

        # Libérer le cache CUDA si disponible
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
                logger.info("[EMBEDDINGS] GPU memory cache cleared")
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"[EMBEDDINGS] Error clearing GPU cache: {e}")

        logger.info(f"[EMBEDDINGS] Model {model_name} unloaded")

    def _start_monitor(self):
        """Démarre le thread de surveillance pour le déchargement automatique."""
        if self._monitor_thread is not None and self._monitor_thread.is_alive():
            return

        self._stop_monitor.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="EmbeddingModelMonitor"
        )
        self._monitor_thread.start()
        logger.debug("[EMBEDDINGS] Monitor thread started")

    def _monitor_loop(self):
        """Boucle de surveillance pour le déchargement automatique."""
        check_interval = 30  # Vérifier toutes les 30 secondes

        while not self._stop_monitor.is_set():
            time.sleep(check_interval)

            with self._model_lock:
                if self._model is None:
                    # Pas de modèle chargé, arrêter la surveillance
                    logger.debug("[EMBEDDINGS] No model loaded, stopping monitor")
                    break

                idle_time = time.time() - self._last_access_time

                if idle_time >= self._timeout_seconds:
                    logger.info(
                        f"[EMBEDDINGS] Model idle for {idle_time / 60:.1f} min, "
                        f"auto-unloading..."
                    )
                    self._unload_model_internal()
                    break

    def stop_monitor(self):
        """Arrête le thread de surveillance."""
        self._stop_monitor.set()
        if self._monitor_thread is not None:
            self._monitor_thread.join(timeout=5)

    def get_status(self) -> dict:
        """Retourne le statut actuel du gestionnaire."""
        with self._model_lock:
            if self._model is None:
                return {
                    "model_loaded": False,
                    "model_name": None,
                    "device": None,
                    "idle_seconds": None,
                    "timeout_seconds": self._timeout_seconds
                }

            return {
                "model_loaded": True,
                "model_name": self._model_name,
                "device": self._device or "auto",
                "idle_seconds": int(time.time() - self._last_access_time),
                "timeout_seconds": self._timeout_seconds
            }

    def get_sentence_embedding_dimension(self) -> Optional[int]:
        """Retourne la dimension des embeddings (charge le modèle si nécessaire)."""
        model = self.get_model()
        return model.get_sentence_embedding_dimension()


# Instance singleton
_manager: Optional[EmbeddingModelManager] = None


def get_embedding_manager() -> EmbeddingModelManager:
    """Récupère le gestionnaire singleton."""
    global _manager
    if _manager is None:
        _manager = EmbeddingModelManager()
    return _manager


def get_sentence_transformer(
    model_name: Optional[str] = None,
    device: Optional[str] = None,
    cache_folder: Optional[str] = None,
):
    """
    Fonction de compatibilité avec l'ancienne API.

    Utilise maintenant le gestionnaire avec déchargement automatique.
    """
    manager = get_embedding_manager()
    return manager.get_model(
        model_name=model_name,
        device=device,
        cache_folder=cache_folder
    )


def unload_embedding_model():
    """Force le déchargement du modèle d'embedding."""
    manager = get_embedding_manager()
    manager.unload_model()


def get_embedding_status() -> dict:
    """Retourne le statut du modèle d'embedding."""
    manager = get_embedding_manager()
    return manager.get_status()
