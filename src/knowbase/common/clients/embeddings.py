"""
Gestionnaire de modèles d'embedding avec déchargement automatique GPU.

Phase 2.x: Ajout du mécanisme de timeout pour libérer la mémoire GPU
après une période d'inactivité (utile en développement).

Mode Burst: Support pour basculer vers un service embeddings distant (EC2 Spot).
"""

from __future__ import annotations

import gc
import logging
import threading
import time
from typing import Optional, List, Dict, Any

import numpy as np
import requests

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

        # === Mode Burst ===
        self._burst_mode = False
        self._burst_endpoint: Optional[str] = None
        self._burst_timeout: int = 120  # Timeout HTTP en secondes (augmenté pour gros batches)

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
    ) -> np.ndarray:
        """
        Encode des phrases avec le modèle d'embedding.

        En mode Burst, utilise le service distant EC2 Spot.
        Sinon, utilise le modèle local.

        Args:
            sentences: Liste de phrases à encoder
            **kwargs: Arguments passés à model.encode() (ignorés en mode burst)

        Returns:
            Embeddings numpy array
        """
        # === Auto-détection Burst depuis Redis ===
        # Si le burst n'est pas activé en mémoire, vérifier Redis
        # (le burst peut avoir été activé par le script StreamDeck
        # ou une autre instance après le démarrage du worker)
        if not self._burst_mode:
            self._check_burst_from_redis()

        # === Mode Burst : utiliser le service distant ===
        if self._burst_mode and self._burst_endpoint:
            return self._encode_remote(sentences)

        # === Mode Normal : utiliser le modèle local ===
        model = self.get_model()

        with self._model_lock:
            self._last_access_time = time.time()

        return model.encode(sentences, **kwargs)

    def _encode_remote(
        self,
        sentences: List[str],
        max_batch_size: int = None,  # Auto-détecté selon config Burst
        max_batch_chars: int = None,  # Auto-détecté selon config Burst
        max_text_chars: int = 1500,
        max_concurrent: int = None,  # Auto-détecté selon config Burst
        max_retries: int = 3
    ) -> np.ndarray:
        """
        Encode les textes via le service embeddings distant (EC2 Spot).

        Utilise l'API Text Embeddings Inference (TEI) de HuggingFace.
        Batching adaptatif + requêtes parallèles pour performance optimale.

        Inclut un circuit breaker pour arrêter en cas d'échecs consécutifs.

        Args:
            sentences: Liste de textes à encoder
            max_batch_size: Nombre max de textes par batch (auto: 4 Burst, 8 local)
            max_batch_chars: Taille max en caractères par batch (auto: 6KB Burst, 12KB local)
            max_text_chars: Taille max par texte individuel (défaut: 1500)
            max_concurrent: Nombre max de requêtes parallèles (auto-détecté si None)
            max_retries: Nombre de tentatives en cas d'erreur (défaut: 3)

        Returns:
            Embeddings numpy array
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed, CancelledError

        # Auto-détection config selon mode Burst
        circuit_breaker_threshold = 5  # Défaut
        try:
            from knowbase.ingestion.burst.provider_switch import get_burst_concurrency_config
            config = get_burst_concurrency_config()
            if max_concurrent is None:
                max_concurrent = config.get("max_concurrent_embeddings", 6)
            if max_batch_size is None:
                max_batch_size = config.get("embedding_batch_size", 4)
            if max_batch_chars is None:
                max_batch_chars = config.get("embedding_batch_chars", 6000)
            # 2024-12-30: Lire aussi max_text_chars depuis config Burst
            config_max_text_chars = config.get("embedding_max_text_chars")
            if config_max_text_chars:
                max_text_chars = config_max_text_chars
            circuit_breaker_threshold = config.get("circuit_breaker_threshold", 5)
        except ImportError:
            if max_concurrent is None:
                max_concurrent = 6
            if max_batch_size is None:
                max_batch_size = 8
            if max_batch_chars is None:
                max_batch_chars = 12000

        if not sentences:
            return np.array([])

        # Tronquer les textes trop longs (TEI max_input_length ~512 tokens ≈ 1500 chars)
        truncated = [
            text[:max_text_chars] if len(text) > max_text_chars else text
            for text in sentences
        ]

        # Créer les batches avec limite de caractères
        batches = []
        current_batch = []
        current_chars = 0

        for text in truncated:
            text_len = len(text)
            if current_batch and (
                len(current_batch) >= max_batch_size or
                current_chars + text_len > max_batch_chars
            ):
                batches.append(current_batch)
                current_batch = []
                current_chars = 0
            current_batch.append(text)
            current_chars += text_len

        if current_batch:
            batches.append(current_batch)

        total_batches = len(batches)
        start_time = time.time()
        logger.info(
            f"[EMBEDDINGS:BURST] {len(truncated)} texts → {total_batches} batches "
            f"(size={max_batch_size}, chars={max_batch_chars}, concurrent={max_concurrent})"
        )

        # Circuit breaker state
        consecutive_failures = 0
        circuit_broken = False

        def _post_embed(batch: List[str]) -> np.ndarray:
            """Appel HTTP POST vers le endpoint /embed."""
            response = requests.post(
                f"{self._burst_endpoint}/embed",
                json={"inputs": batch},
                timeout=self._burst_timeout,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            return np.array(response.json())

        def _encode_with_split(batch: List[str], depth: int = 0) -> Optional[np.ndarray]:
            """
            Encode un batch, avec split adaptatif en cas de 413 Payload Too Large.

            Si le endpoint refuse le payload (413) :
            - batch > 1 texte : split en deux et retry récursivement (pas de limite de depth)
            - batch == 1 texte : truncation progressive (66%, 50%, 33%) puis skip
            """
            try:
                return _post_embed(batch)
            except requests.exceptions.HTTPError as e:
                if e.response is not None and e.response.status_code == 413:
                    if len(batch) > 1:
                        mid = len(batch) // 2
                        logger.warning(
                            f"[EMBEDDINGS:BURST] 413 Payload Too Large ({len(batch)} texts, "
                            f"~{sum(len(t) for t in batch)} chars) → split en 2 (depth={depth+1})"
                        )
                        left = _encode_with_split(batch[:mid], depth + 1)
                        right = _encode_with_split(batch[mid:], depth + 1)
                        # Gérer les None (textes skippés)
                        if left is None and right is None:
                            return None
                        if left is None:
                            return right
                        if right is None:
                            return left
                        return np.vstack([left, right])
                    else:
                        # Single text : truncation progressive
                        text = batch[0]
                        for pct in [66, 50, 33]:
                            cut_len = int(len(text) * pct / 100)
                            try:
                                logger.warning(
                                    f"[EMBEDDINGS:BURST] Single text 413 ({len(text)} chars) "
                                    f"→ truncating to {pct}% ({cut_len} chars)"
                                )
                                return _post_embed([text[:cut_len]])
                            except requests.exceptions.HTTPError as e2:
                                if e2.response is not None and e2.response.status_code == 413:
                                    continue
                                raise
                        # Toutes les truncations ont échoué — skip ce texte
                        logger.error(
                            f"[EMBEDDINGS:BURST] Text ({len(text)} chars) rejected by TEI "
                            f"even at 33% — skipping"
                        )
                        return None
                raise

        # Dimension des embeddings (détectée depuis le premier batch réussi)
        embedding_dim = [None]  # Mutable pour accès depuis closure

        def encode_batch_with_retry(batch_idx: int, batch: List[str]) -> tuple:
            """Encode un batch avec retry + split adaptatif en cas de 413."""
            nonlocal consecutive_failures, circuit_broken

            # Check circuit breaker before starting
            if circuit_broken:
                raise RuntimeError("Circuit breaker tripped - too many consecutive failures")

            last_error = None
            for attempt in range(max_retries):
                try:
                    result = _encode_with_split(batch)
                    if result is None:
                        # Tous les textes du batch ont été skippés (413 irrésoluble)
                        # Ne PAS compter comme échec systémique
                        logger.warning(
                            f"[EMBEDDINGS:BURST] Batch {batch_idx+1}: all {len(batch)} text(s) "
                            f"skipped (too large for TEI)"
                        )
                        return batch_idx, None
                    # Success - reset consecutive failures, capture dimension
                    consecutive_failures = 0
                    if embedding_dim[0] is None and result.ndim >= 2:
                        embedding_dim[0] = result.shape[1]
                    return batch_idx, result
                except requests.exceptions.HTTPError as e:
                    # 413 non-résolu : erreur déterministe, pas systémique
                    # Ne PAS incrémenter le circuit breaker
                    if e.response is not None and e.response.status_code == 413:
                        logger.warning(
                            f"[EMBEDDINGS:BURST] Batch {batch_idx+1}: 413 unresolved, skipping"
                        )
                        return batch_idx, None
                    last_error = e
                    break
                except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                    last_error = e
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 2  # Backoff: 2s, 4s, 6s
                        logger.warning(
                            f"[EMBEDDINGS:BURST] Batch {batch_idx+1} attempt {attempt+1} failed, "
                            f"retrying in {wait_time}s..."
                        )
                        time.sleep(wait_time)

            # All retries failed (non-413) - increment consecutive failures
            consecutive_failures += 1
            if consecutive_failures >= circuit_breaker_threshold:
                circuit_broken = True
                logger.error(
                    f"[EMBEDDINGS:BURST] Circuit breaker tripped after {consecutive_failures} "
                    f"consecutive failures"
                )
            raise last_error

        # Exécuter les batches en parallèle
        results = [None] * total_batches
        completed = 0
        errors = 0

        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            futures = {
                executor.submit(encode_batch_with_retry, idx, batch): idx
                for idx, batch in enumerate(batches)
            }

            for future in as_completed(futures):
                batch_idx = futures[future]
                try:
                    idx, embeddings = future.result()
                    results[idx] = embeddings
                    completed += 1

                    # Log progression tous les 10% ou 100 batches
                    if total_batches > 50 and completed % max(1, total_batches // 10) == 0:
                        elapsed = time.time() - start_time
                        rate = completed / elapsed if elapsed > 0 else 0
                        eta = (total_batches - completed) / rate if rate > 0 else 0
                        logger.info(
                            f"[EMBEDDINGS:BURST] Progress: {completed}/{total_batches} "
                            f"({100*completed//total_batches}%) - ETA: {eta:.0f}s"
                        )

                except RuntimeError as e:
                    if "Circuit breaker" in str(e):
                        # Cancel remaining futures
                        for f in futures:
                            f.cancel()
                        logger.error(f"[EMBEDDINGS:BURST] Aborting - circuit breaker active")
                        raise
                    errors += 1
                    raise
                except requests.exceptions.Timeout:
                    errors += 1
                    logger.error(
                        f"[EMBEDDINGS:BURST] Timeout on batch {batch_idx+1}/{total_batches} "
                        f"after {max_retries} retries (consecutive_failures={consecutive_failures})"
                    )
                    if circuit_broken:
                        # Cancel remaining futures
                        for f in futures:
                            f.cancel()
                        raise RuntimeError(f"Circuit breaker: {consecutive_failures} consecutive failures")
                    raise
                except requests.exceptions.ConnectionError as e:
                    errors += 1
                    logger.error(f"[EMBEDDINGS:BURST] Connection error on batch {batch_idx+1}: {e}")
                    if circuit_broken:
                        for f in futures:
                            f.cancel()
                        raise RuntimeError(f"Circuit breaker: {consecutive_failures} consecutive failures")
                    raise
                except CancelledError:
                    # Batch was cancelled due to circuit breaker
                    pass
                except Exception as e:
                    errors += 1
                    logger.error(f"[EMBEDDINGS:BURST] Error on batch {batch_idx+1}: {e}")
                    raise

        # Assembler les résultats — les batches None sont skippés (textes trop longs)
        valid_results = [r for r in results if r is not None]
        skipped_batches = sum(1 for r in results if r is None)

        if not valid_results:
            raise RuntimeError(
                f"[EMBEDDINGS:BURST] All {total_batches} batches failed — no embeddings produced"
            )

        if skipped_batches > 0:
            # Remplacer les None par des zero vectors pour maintenir l'alignement index
            dim = embedding_dim[0] or (valid_results[0].shape[1] if valid_results else 1024)
            skipped_texts = 0
            for i, r in enumerate(results):
                if r is None:
                    batch_len = len(batches[i])
                    results[i] = np.zeros((batch_len, dim))
                    skipped_texts += batch_len
            logger.warning(
                f"[EMBEDDINGS:BURST] {skipped_texts} texts skipped (413 too large) "
                f"→ zero vectors substituted"
            )

        embeddings = np.vstack(results) if results else np.array([])
        elapsed = time.time() - start_time
        logger.info(
            f"[EMBEDDINGS:BURST] Encoded {len(truncated)} texts → {embeddings.shape} "
            f"in {elapsed:.1f}s ({len(truncated)/elapsed:.0f} texts/s)"
            + (f" ({skipped_batches} batches skipped)" if skipped_batches else "")
        )
        return embeddings

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

    # =========================================================================
    # Mode Burst - Basculement vers EC2 Spot
    # =========================================================================

    def _check_burst_from_redis(self):
        """
        Vérifie si un burst est actif dans Redis et switch automatiquement.

        Appelé à chaque encode() quand le burst n'est pas activé en mémoire.
        Rate-limité à 1 check toutes les 30 secondes pour ne pas surcharger Redis.
        """
        now = time.time()
        if hasattr(self, '_last_burst_check') and now - self._last_burst_check < 30:
            return
        self._last_burst_check = now

        try:
            from knowbase.ingestion.burst.provider_switch import get_burst_state_from_redis
            state = get_burst_state_from_redis()
            if state and state.get("active") and state.get("embeddings_url"):
                embeddings_url = state["embeddings_url"]
                # Vérifier que le TEI est accessible avant de switch
                import requests
                try:
                    resp = requests.get(f"{embeddings_url}/health", timeout=3)
                    if resp.status_code == 200:
                        logger.info(
                            f"[EMBEDDINGS] Auto-detected burst from Redis → {embeddings_url}"
                        )
                        self.enable_burst_mode(embeddings_url)
                except Exception:
                    pass  # TEI pas accessible, rester en local
        except Exception:
            pass

    def enable_burst_mode(self, embeddings_url: str, timeout: int = 60):
        """
        Active le mode Burst : embeddings calculés sur EC2 Spot.

        En mode Burst :
        - Les appels encode() sont redirigés vers le service distant
        - Le modèle local est déchargé pour libérer le GPU

        Args:
            embeddings_url: URL du service embeddings (ex: http://ec2-xxx:8001)
            timeout: Timeout HTTP en secondes (défaut: 60)
        """
        self._burst_mode = True
        self._burst_endpoint = embeddings_url.rstrip("/")
        self._burst_timeout = timeout

        # Décharger le modèle local pour libérer le GPU
        self.unload_model()

        logger.info(f"[EMBEDDINGS] 🚀 Burst mode ENABLED → {embeddings_url}")

    def disable_burst_mode(self):
        """
        Désactive le mode Burst, retour au GPU local.
        Le modèle local sera rechargé au prochain appel encode().
        """
        if not self._burst_mode:
            logger.debug("[EMBEDDINGS] Burst mode already disabled")
            return

        self._burst_mode = False
        self._burst_endpoint = None

        logger.info("[EMBEDDINGS] ⏹️ Burst mode DISABLED → Local GPU")

    def is_burst_mode_active(self) -> bool:
        """Vérifie si le mode Burst est actif."""
        return self._burst_mode and self._burst_endpoint is not None

    def get_burst_status(self) -> Dict[str, Any]:
        """Retourne le statut du mode Burst."""
        return {
            "burst_mode": self._burst_mode,
            "burst_endpoint": self._burst_endpoint,
            "burst_timeout": self._burst_timeout if self._burst_mode else None
        }

    def get_max_text_chars(self) -> int:
        """
        Retourne la taille max de texte acceptée par l'encoder (burst ou local).

        Utilisé par le rechunker pour ajuster dynamiquement target_chars.
        Lit la config burst si disponible, sinon 1500 par défaut.
        """
        try:
            from knowbase.ingestion.burst.provider_switch import get_burst_concurrency_config
            config = get_burst_concurrency_config()
            return config.get("embedding_max_text_chars", 1500)
        except ImportError:
            return 1500

    def get_sentence_embedding_dimension(self) -> Optional[int]:
        """Retourne la dimension des embeddings (charge le modèle si nécessaire)."""
        # En mode burst, on ne peut pas connaître la dimension sans appeler le service
        if self._burst_mode:
            return None
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
