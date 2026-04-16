"""
OSMOSE Burst Provider Switch - Basculement dynamique des providers LLM/Embeddings

Ce module coordonne l'activation/désactivation du mode Burst pour tous les providers :
- LLMRouter : bascule vers vLLM sur EC2 Spot
- EmbeddingManager : bascule vers TEI sur EC2 Spot

IMPORTANT: L'état du burst est stocké dans Redis pour être partagé entre tous les
processus (app, worker, etc.). La clé Redis `osmose:burst:state` contient l'URL vLLM
active, permettant à tous les processus de router vers vLLM automatiquement.

Utilisé par le BurstOrchestrator quand l'instance EC2 est prête.

Author: OSMOSE Burst Ingestion
Date: 2025-12
"""

import json
import logging
import os
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# === Clés Redis pour l'état du burst (partagé entre tous les processus) ===
REDIS_BURST_STATE_KEY = "osmose:burst:state"

# === Fichier persistant sur le volume /data (survit aux rebuilds + évictions Redis) ===
BURST_STATE_FILE = os.path.join(os.getenv("KNOWBASE_DATA_DIR", "/data"), ".burst_state.json")


def _get_redis_client():
    """Récupère le client Redis."""
    try:
        from knowbase.common.clients.redis_client import get_redis_client
        return get_redis_client()
    except Exception as e:
        logger.warning(f"[BURST:REDIS] Cannot get Redis client: {e}")
        return None


def _save_burst_state_file(state: Dict[str, Any]) -> None:
    """Sauvegarde l'état burst dans un fichier sur le volume /data (persiste aux rebuilds)."""
    try:
        with open(BURST_STATE_FILE, "w") as f:
            json.dump(state, f)
        logger.debug(f"[BURST:FILE] State saved to {BURST_STATE_FILE}")
    except Exception as e:
        logger.warning(f"[BURST:FILE] Failed to save state file: {e}")


def _load_burst_state_file() -> Optional[Dict[str, Any]]:
    """Charge l'état burst depuis le fichier persistant."""
    try:
        if os.path.exists(BURST_STATE_FILE):
            with open(BURST_STATE_FILE, "r") as f:
                state = json.load(f)
            if state.get("active"):
                return state
    except Exception as e:
        logger.debug(f"[BURST:FILE] Failed to load state file: {e}")
    return None


def _quick_health_check(vllm_url: str, timeout: int = 3) -> bool:
    """Health check rapide avant de restaurer un état burst depuis le fichier."""
    try:
        import requests
        resp = requests.get(f"{vllm_url.rstrip('/')}/health", timeout=timeout)
        return resp.ok
    except Exception:
        return False


def _clear_burst_state_file() -> None:
    """Supprime le fichier d'état burst."""
    try:
        if os.path.exists(BURST_STATE_FILE):
            os.remove(BURST_STATE_FILE)
            logger.debug(f"[BURST:FILE] State file removed")
    except Exception as e:
        logger.warning(f"[BURST:FILE] Failed to remove state file: {e}")


def set_burst_state_in_redis(vllm_url: str, vllm_model: str, embeddings_url: str) -> bool:
    """
    Stocke l'état du burst dans Redis ET dans un fichier persistant.

    Double écriture : Redis (rapide, inter-process) + fichier /data (survit aux rebuilds).
    """
    state = {
        "active": True,
        "vllm_url": vllm_url,
        "vllm_model": vllm_model,
        "embeddings_url": embeddings_url
    }

    # Toujours sauver dans le fichier (backup)
    _save_burst_state_file(state)

    redis = _get_redis_client()
    if not redis:
        return False

    try:
        redis.client.set(REDIS_BURST_STATE_KEY, json.dumps(state))
        logger.info(f"[BURST:REDIS] State saved: vLLM={vllm_url}, model={vllm_model}")
        return True
    except Exception as e:
        logger.error(f"[BURST:REDIS] Failed to save state: {e}")
        return False


def clear_burst_state_in_redis() -> bool:
    """
    Supprime l'état du burst dans Redis ET le fichier persistant.
    """
    _clear_burst_state_file()

    redis = _get_redis_client()
    if not redis:
        return False

    try:
        redis.client.delete(REDIS_BURST_STATE_KEY)
        logger.info("[BURST:REDIS] State cleared (burst deactivated)")
        return True
    except Exception as e:
        logger.error(f"[BURST:REDIS] Failed to clear state: {e}")
        return False


def get_burst_state_from_redis() -> Optional[Dict[str, Any]]:
    """
    Récupère l'état du burst depuis Redis, avec fallback fichier.

    Ordre : Redis (prioritaire) → fichier /data (fallback si Redis vide/évinçé).
    Si le fichier fournit l'état, on le re-sauve dans Redis pour les prochains appels.
    """
    redis = _get_redis_client()
    if redis:
        try:
            data = redis.client.get(REDIS_BURST_STATE_KEY)
            if data:
                state = json.loads(data)
                if state.get("active"):
                    return state
        except Exception as e:
            logger.debug(f"[BURST:REDIS] Failed to get state: {e}")

    # Fallback : fichier persistant — mais vérifier d'abord que l'instance est joignable
    file_state = _load_burst_state_file()
    if file_state:
        vllm_url = file_state.get("vllm_url")
        if vllm_url and _quick_health_check(vllm_url):
            logger.info(
                f"[BURST:FILE] Restored from file (Redis empty): "
                f"vLLM={vllm_url} — health OK"
            )
            # Re-sauver dans Redis pour les appels suivants
            if redis:
                try:
                    redis.client.set(REDIS_BURST_STATE_KEY, json.dumps(file_state))
                    logger.info("[BURST:FILE] Re-saved to Redis from file backup")
                except Exception:
                    pass
            return file_state
        else:
            # Instance unreachable — purger le fichier stale
            logger.warning(
                f"[BURST:FILE] File state found but vLLM unreachable ({vllm_url}). "
                f"Purging stale file."
            )
            _clear_burst_state_file()

    return None


def _detect_vllm_served_model(vllm_url: str, timeout: int = 5) -> Optional[str]:
    """
    Interroge le endpoint /v1/models pour obtenir le nom réel du modèle servi.

    Ceci évite les erreurs 404 dues à un mismatch entre le nom configuré
    (ex: "Qwen/Qwen2.5-14B-Instruct-AWQ") et le nom réellement servi (ex: "/model").
    """
    try:
        import requests
        resp = requests.get(f"{vllm_url.rstrip('/')}/v1/models", timeout=timeout)
        if resp.ok:
            data = resp.json()
            models = data.get("data", [])
            if models:
                served_name = models[0].get("id")
                logger.info(f"[BURST:DETECT] vLLM serves model as: '{served_name}'")
                return served_name
    except Exception as e:
        logger.warning(f"[BURST:DETECT] Failed to detect served model: {e}")
    return None


def _convert_to_vllm_model_name(model_name: Optional[str], vllm_url: Optional[str] = None) -> str:
    """
    Retourne le nom du modèle tel que servi par vLLM.

    Stratégie (par priorité) :
    1. Interroger /v1/models si vllm_url fourni (source de vérité)
    2. Sinon, convertir le nom passé en paramètre
    3. Défaut : "Qwen/Qwen2.5-14B-Instruct-AWQ"
    """
    # Priorité 1 : détection automatique depuis l'instance vLLM
    if vllm_url:
        detected = _detect_vllm_served_model(vllm_url)
        if detected:
            return detected

    if not model_name:
        return "Qwen/Qwen2.5-14B-Instruct-AWQ"

    # Si c'est un ancien chemin /models/, convertir vers le format HuggingFace
    if model_name.startswith("/models/"):
        # "/models/Qwen--Qwen2.5-14B-Instruct-AWQ" -> "Qwen/Qwen2.5-14B-Instruct-AWQ"
        stripped = model_name.replace("/models/", "", 1)
        return stripped.replace("--", "/", 1)

    return model_name


def activate_burst_providers(
    vllm_url: str,
    embeddings_url: str,
    vllm_model: Optional[str] = None,
    dual_logging: bool = False
) -> Dict[str, Any]:
    """
    Active les providers Burst pour le pipeline.

    Appelé par BurstOrchestrator quand l'instance EC2 Spot est prête.
    Bascule LLMRouter et EmbeddingManager vers les services distants.

    Args:
        vllm_url: URL du serveur vLLM (ex: http://ec2-xxx:8000)
        embeddings_url: URL du service embeddings (ex: http://ec2-xxx:8001)
        vllm_model: Modèle vLLM à utiliser (défaut: Qwen/Qwen2.5-14B-Instruct-AWQ)
        dual_logging: Si True, garde OpenAI + appelle vLLM en parallèle pour comparaison

    Returns:
        Dict avec le statut d'activation de chaque provider
    """
    from knowbase.common.llm_router import get_llm_router
    from knowbase.common.clients.embeddings import get_embedding_manager

    result = {
        "llm_router": False,
        "embedding_manager": False,
        "dual_logging": False,
        "vllm_url": vllm_url,
        "embeddings_url": embeddings_url,
        "errors": []
    }

    # Mode Dual-Logging: garder OpenAI + appeler vLLM en parallèle
    if dual_logging:
        try:
            from knowbase.common.dual_llm_logger import DualLLMLogger
            dual_logger = DualLLMLogger.get_instance()
            dual_logger.enable(vllm_url, vllm_model=_convert_to_vllm_model_name(vllm_model, vllm_url))
            result["dual_logging"] = True
            result["llm_router"] = True  # OpenAI reste actif
            logger.info(f"[BURST:SWITCH] 🔀 Dual-Logging enabled: OpenAI + vLLM ({vllm_url})")
        except Exception as e:
            result["errors"].append(f"DualLLMLogger: {e}")
            logger.error(f"[BURST:SWITCH] Failed to enable dual-logging: {e}")
    else:
        # Mode normal: bascule complète vers vLLM
        try:
            llm_router = get_llm_router()
            # Détecter le nom réel du modèle servi par vLLM
            vllm_model_name = _convert_to_vllm_model_name(vllm_model, vllm_url)
            llm_router.enable_burst_mode(vllm_url, model=vllm_model_name)
            result["llm_router"] = True
            logger.info(f"[BURST:SWITCH] LLMRouter → {vllm_url} (model: {vllm_model_name})")
        except Exception as e:
            result["errors"].append(f"LLMRouter: {e}")
            logger.error(f"[BURST:SWITCH] Failed to enable LLMRouter burst: {e}")

    # Activer EmbeddingManager
    try:
        embedding_manager = get_embedding_manager()
        embedding_manager.enable_burst_mode(embeddings_url)
        result["embedding_manager"] = True
        logger.info(f"[BURST:SWITCH] EmbeddingManager → {embeddings_url}")
    except Exception as e:
        result["errors"].append(f"EmbeddingManager: {e}")
        logger.error(f"[BURST:SWITCH] Failed to enable EmbeddingManager burst: {e}")

    if result["llm_router"] and result["embedding_manager"]:
        logger.info("[BURST:SWITCH] ✅ All providers switched to EC2 Spot")
        # Stocker l'état dans Redis pour partage inter-processus
        vllm_model_name = _convert_to_vllm_model_name(vllm_model, vllm_url)
        redis_saved = set_burst_state_in_redis(vllm_url, vllm_model_name, embeddings_url)
        result["redis_state"] = redis_saved
        if redis_saved:
            logger.info("[BURST:SWITCH] ✅ State saved to Redis (inter-process)")
        else:
            logger.warning("[BURST:SWITCH] ⚠️ Failed to save state to Redis")
    else:
        logger.warning(f"[BURST:SWITCH] ⚠️ Partial activation: {result}")

    return result


def deactivate_burst_providers() -> Dict[str, Any]:
    """
    Désactive les providers Burst, retour au mode normal.

    Appelé quand le batch est terminé, sur erreur, ou après interruption Spot.

    Returns:
        Dict avec le statut de désactivation de chaque provider
    """
    from knowbase.common.llm_router import get_llm_router
    from knowbase.common.clients.embeddings import get_embedding_manager

    result = {
        "llm_router": False,
        "embedding_manager": False,
        "dual_logging": False,
        "errors": []
    }

    # Désactiver Dual-Logging si actif
    try:
        from knowbase.common.dual_llm_logger import DualLLMLogger
        dual_logger = DualLLMLogger.get_instance()
        if dual_logger.is_enabled():
            dual_logger.disable()
            result["dual_logging"] = True
            logger.info("[BURST:SWITCH] 🔀 Dual-Logging disabled")
    except Exception as e:
        result["errors"].append(f"DualLLMLogger: {e}")
        logger.error(f"[BURST:SWITCH] Failed to disable dual-logging: {e}")

    # Désactiver LLMRouter
    try:
        llm_router = get_llm_router()
        llm_router.disable_burst_mode()
        result["llm_router"] = True
        logger.info("[BURST:SWITCH] LLMRouter → Normal mode")
    except Exception as e:
        result["errors"].append(f"LLMRouter: {e}")
        logger.error(f"[BURST:SWITCH] Failed to disable LLMRouter burst: {e}")

    # Désactiver EmbeddingManager
    try:
        embedding_manager = get_embedding_manager()
        embedding_manager.disable_burst_mode()
        result["embedding_manager"] = True
        logger.info("[BURST:SWITCH] EmbeddingManager → Normal mode")
    except Exception as e:
        result["errors"].append(f"EmbeddingManager: {e}")
        logger.error(f"[BURST:SWITCH] Failed to disable EmbeddingManager burst: {e}")

    # Effacer l'état dans Redis (inter-processus)
    redis_cleared = clear_burst_state_in_redis()
    result["redis_state_cleared"] = redis_cleared
    if redis_cleared:
        logger.info("[BURST:SWITCH] ✅ Redis state cleared (inter-process)")

    if result["llm_router"] and result["embedding_manager"]:
        logger.info("[BURST:SWITCH] ✅ All providers switched back to normal")
    else:
        logger.warning(f"[BURST:SWITCH] ⚠️ Partial deactivation: {result}")

    return result


# Configuration des limites en mode Burst (sans rate limiting cloud)
# ATTENTION: Valeurs calibrées pour éviter saturation TEI/vLLM sur g6.2xlarge
# 2024-12-30: Réduit embedding_batch_chars de 6000→4000 pour éviter 413 Payload Too Large
# 2024-12-31: batch_size=1 pour éviter 413 intermittent sur AMI Golden TEI
# 2026-02-01: Limites relevées (TEI recréé avec --max-input-length 512 --max-client-batch-size 32)
BURST_CONCURRENCY_CONFIG = {
    "max_concurrent_llm": 15,        # Appels LLM simultanés (réduit de 20 pour stabilité)
    "max_parallel_segments": 8,      # Segments traités en parallèle (réduit de 10)
    "max_concurrent_embeddings": 6,  # Workers embeddings parallèles
    "max_concurrent_batches": 10,    # Batches gatekeeper (réduit de 15)
    "embedding_batch_size": 8,       # 8 textes par requête (TEI max-client-batch-size=32)
    "embedding_batch_chars": 12000,  # Max chars par requête (~8 × 1500)
    "embedding_max_text_chars": 1500,  # Max chars par texte (512 tokens e5-large ≈ 1500 chars)
    "circuit_breaker_threshold": 5,  # Arrêt après N échecs consécutifs
    "rate_limits": {
        "SMALL": 10000,  # Pas de limite réelle
        "BIG": 10000,
        "VISION": 1000
    }
}


def is_burst_mode_active() -> bool:
    """
    Vérifie rapidement si le mode Burst est actif.

    Utilisé par les composants pour ajuster dynamiquement leurs limites.

    Returns:
        True si LLM ou Embeddings sont en mode Burst
    """
    try:
        from knowbase.common.llm_router import get_llm_router
        llm_router = get_llm_router()
        if llm_router.get_burst_status().get("burst_mode", False):
            return True
    except Exception:
        pass

    try:
        from knowbase.common.clients.embeddings import get_embedding_manager
        emb_manager = get_embedding_manager()
        if emb_manager.get_burst_status().get("burst_mode", False):
            return True
    except Exception:
        pass

    return False


def get_burst_concurrency_config() -> Dict[str, Any]:
    """
    Retourne la configuration de concurrence appropriée.

    Si Burst actif: limites élevées (pas de rate limiting)
    Sinon: limites normales (protection rate limiting cloud)

    Returns:
        Dict avec les limites de concurrence
    """
    if is_burst_mode_active():
        logger.debug("[BURST:CONFIG] Mode Burst actif - concurrence élevée")
        return BURST_CONCURRENCY_CONFIG
    else:
        return {
            "max_concurrent_llm": 5,
            "max_parallel_segments": 5,
            "max_concurrent_embeddings": 6,
            "max_concurrent_batches": 5,
            "rate_limits": {
                "SMALL": 500,
                "BIG": 100,
                "VISION": 50
            }
        }


def get_burst_providers_status() -> Dict[str, Any]:
    """
    Retourne le statut actuel des providers.

    Returns:
        Dict avec le statut de chaque provider (burst_mode, endpoints, etc.)
    """
    from knowbase.common.llm_router import get_llm_router
    from knowbase.common.clients.embeddings import get_embedding_manager

    try:
        llm_router = get_llm_router()
        llm_status = llm_router.get_burst_status()
    except Exception as e:
        llm_status = {"error": str(e)}

    try:
        embedding_manager = get_embedding_manager()
        emb_status = embedding_manager.get_burst_status()
    except Exception as e:
        emb_status = {"error": str(e)}

    return {
        "llm_router": llm_status,
        "embedding_manager": emb_status,
        "any_burst_active": (
            llm_status.get("burst_mode", False) or
            emb_status.get("burst_mode", False)
        )
    }


def check_burst_providers_health(
    vllm_url: str,
    embeddings_url: str,
    timeout: int = 10
) -> Dict[str, Any]:
    """
    Vérifie la santé des services Burst avant activation.

    Args:
        vllm_url: URL du serveur vLLM
        embeddings_url: URL du service embeddings
        timeout: Timeout HTTP en secondes

    Returns:
        Dict avec le statut de santé de chaque service
    """
    import requests

    result = {
        "vllm_healthy": False,
        "embeddings_healthy": False,
        "vllm_url": vllm_url,
        "embeddings_url": embeddings_url,
        "errors": []
    }

    # Check vLLM health
    try:
        vllm_health_url = f"{vllm_url.rstrip('/')}/health"
        resp = requests.get(vllm_health_url, timeout=timeout)
        result["vllm_healthy"] = resp.ok
        if resp.ok:
            logger.debug(f"[BURST:HEALTH] vLLM OK: {vllm_health_url}")
        else:
            result["errors"].append(f"vLLM status: {resp.status_code}")
    except requests.exceptions.RequestException as e:
        result["errors"].append(f"vLLM: {e}")
        logger.debug(f"[BURST:HEALTH] vLLM failed: {e}")

    # Check embeddings health
    try:
        emb_health_url = f"{embeddings_url.rstrip('/')}/health"
        resp = requests.get(emb_health_url, timeout=timeout)
        result["embeddings_healthy"] = resp.ok
        if resp.ok:
            logger.debug(f"[BURST:HEALTH] Embeddings OK: {emb_health_url}")
        else:
            result["errors"].append(f"Embeddings status: {resp.status_code}")
    except requests.exceptions.RequestException as e:
        result["errors"].append(f"Embeddings: {e}")
        logger.debug(f"[BURST:HEALTH] Embeddings failed: {e}")

    result["all_healthy"] = result["vllm_healthy"] and result["embeddings_healthy"]

    return result


def check_instance_health_with_spot(
    instance_ip: str,
    health_port: int = 8080,
    timeout: int = 5
) -> Dict[str, Any]:
    """
    Vérifie la santé de l'instance via le health endpoint unifié.
    Inclut la détection d'interruption Spot.

    Args:
        instance_ip: IP de l'instance EC2
        health_port: Port du health endpoint (défaut 8080)
        timeout: Timeout HTTP en secondes

    Returns:
        Dict avec:
        - healthy: bool (vllm ET embeddings OK)
        - vllm_healthy: bool
        - embeddings_healthy: bool
        - spot_interruption: None ou {"action": "terminate", "time": "..."}
    """
    import requests

    result = {
        "healthy": False,
        "vllm_healthy": False,
        "embeddings_healthy": False,
        "spot_interruption": None,
        "error": None
    }

    try:
        health_url = f"http://{instance_ip}:{health_port}/"
        resp = requests.get(health_url, timeout=timeout)

        if resp.ok:
            data = resp.json()
            result["healthy"] = data.get("healthy", False)
            result["vllm_healthy"] = data.get("vllm", {}).get("healthy", False)
            result["embeddings_healthy"] = data.get("embeddings", {}).get("healthy", False)
            result["spot_interruption"] = data.get("spot_interruption")

            if result["spot_interruption"]:
                logger.warning(
                    f"[BURST:HEALTH] ⚠️ SPOT INTERRUPTION DETECTED: {result['spot_interruption']}"
                )
        else:
            result["error"] = f"Health endpoint returned {resp.status_code}"

    except requests.exceptions.RequestException as e:
        result["error"] = str(e)
        logger.debug(f"[BURST:HEALTH] Health check failed: {e}")

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Burst Local — vLLM sur GPU local (mode Full Local)
# ═══════════════════════════════════════════════════════════════════════════════

VLLM_LOCAL_CONTAINER = "osmose-vllm-local"
VLLM_LOCAL_PORT = 8001  # Port different du port app (8000)
VLLM_LOCAL_URL = f"http://localhost:{VLLM_LOCAL_PORT}"


def _unload_all_ollama_models() -> int:
    """Decharge TOUS les modeles Ollama de la VRAM pour liberer le GPU.

    Appelle GET /api/ps pour lister les modeles charges, puis POST /api/generate
    avec keep_alive=0 pour chacun. Retourne le nombre de modeles decharges.
    """
    import requests as _requests

    ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
    unloaded = 0

    try:
        # Lister les modeles en VRAM
        resp = _requests.get(f"{ollama_url}/api/ps", timeout=5)
        if resp.status_code != 200:
            logger.warning(f"[BURST:LOCAL] Cannot list Ollama models: HTTP {resp.status_code}")
            return 0

        models = resp.json().get("models", [])
        if not models:
            logger.info("[BURST:LOCAL] No Ollama models loaded in VRAM — GPU already free")
            return 0

        # Decharger chaque modele
        for m in models:
            model_name = m.get("name", "")
            if not model_name:
                continue
            try:
                logger.info(f"[BURST:LOCAL] Unloading Ollama model: {model_name}")
                _requests.post(
                    f"{ollama_url}/api/generate",
                    json={"model": model_name, "keep_alive": 0},
                    timeout=10,
                )
                unloaded += 1
            except Exception as e:
                logger.warning(f"[BURST:LOCAL] Failed to unload {model_name}: {e}")

        logger.info(f"[BURST:LOCAL] Unloaded {unloaded}/{len(models)} Ollama models — VRAM freed")

    except Exception as e:
        logger.warning(f"[BURST:LOCAL] Ollama unload failed: {e}")

    return unloaded


def start_local_vllm(
    model: str = "Qwen/Qwen2.5-14B-Instruct-AWQ",
    gpu_utilization: float = 0.75,
    max_model_len: int = 8192,
    max_num_seqs: int = 16,
) -> Dict[str, Any]:
    """Lance un container Docker vLLM local sur le GPU.

    Pre-requis :
    - Docker accessible depuis le container (docker.sock monte)
    - GPU NVIDIA disponible (--gpus all)

    Etapes :
    1. Verifier mode Full Local
    2. Decharger TOUS les modeles Ollama (liberer la VRAM)
    3. Arreter un eventuel container vLLM existant
    4. Lancer le container vLLM
    5. Attendre health check
    6. Activer le burst via provider_switch

    Returns:
        {"success": bool, "container_id": str, "url": str, "ollama_unloaded": int, "error": str}
    """
    import subprocess
    import time

    result: Dict[str, Any] = {
        "success": False, "container_id": None, "url": VLLM_LOCAL_URL,
        "ollama_unloaded": 0, "error": None,
    }

    # 1. Verifier que le mode est Full Local
    try:
        from knowbase.common.llm_router import get_llm_router, LlmMode
        mode = get_llm_router()._get_llm_mode()
        if mode != LlmMode.FULL_LOCAL:
            result["error"] = f"Burst local requires Full Local mode (current: {mode.value})"
            return result
    except Exception as e:
        result["error"] = f"Cannot check LLM mode: {e}"
        return result

    # 2. Decharger TOUS les modeles Ollama pour liberer la VRAM
    result["ollama_unloaded"] = _unload_all_ollama_models()
    if result["ollama_unloaded"] > 0:
        logger.info(f"[BURST:LOCAL] Waiting 5s for Ollama to release VRAM...")
        time.sleep(5)

    # 2b. Decharger le modele d'embeddings du worker (e5-large) pour liberer la VRAM
    try:
        from knowbase.common.clients.embeddings import get_embedding_manager
        emb = get_embedding_manager()
        if hasattr(emb, 'unload_model'):
            emb.unload_model()
            logger.info("[BURST:LOCAL] Embedding model unloaded from GPU")
            time.sleep(2)
        elif hasattr(emb, '_model') and emb._model is not None:
            import gc, torch
            emb._model = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            logger.info("[BURST:LOCAL] Embedding model forcefully unloaded + CUDA cache cleared")
            time.sleep(2)
    except Exception as e:
        logger.warning(f"[BURST:LOCAL] Could not unload embedding model: {e}")

    # 3. Arreter un eventuel container vLLM local existant
    try:
        subprocess.run(
            ["docker", "rm", "-f", VLLM_LOCAL_CONTAINER],
            capture_output=True, timeout=10,
        )
    except Exception:
        pass

    quantization = "awq_marlin" if "AWQ" in model else "auto"

    # Volume HuggingFace cache : le chemin hote doit etre en format Docker.
    # Depuis un container Docker Desktop Windows, le chemin hote C:\Users\X
    # est accessible via /c/Users/X ou //c/Users/X.
    hf_cache_host = os.getenv("HF_CACHE_HOST_PATH", "/c/Users/fredp/.cache/huggingface")

    # Reseau Docker : meme reseau que le worker pour que le health check
    # fonctionne via le nom de container (pas host.docker.internal)
    docker_network = os.getenv("DOCKER_NETWORK", "knowbase_network")

    cmd = [
        "docker", "run", "-d",
        "--name", VLLM_LOCAL_CONTAINER,
        "--gpus", "all",
        "--network", docker_network,
        "-p", f"{VLLM_LOCAL_PORT}:8000",
        "--shm-size", "2g",
        "-v", f"{hf_cache_host}:/root/.cache/huggingface",
        "vllm/vllm-openai:v0.9.2",
        "--model", model,
        "--quantization", quantization,
        "--gpu-memory-utilization", str(gpu_utilization),
        "--max-model-len", str(max_model_len),
        "--max-num-seqs", str(max_num_seqs),
        # IMPORTANT: chunked prefill corrompt la generation JSON structuree
        # de Qwen2.5-14B-AWQ dans vLLM v0.9+ (0 claims extraites avec,
        # 34 claims sans sur le meme doc). Desactiver jusqu'a fix upstream.
        "--no-enable-chunked-prefill",
    ]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            result["error"] = f"Docker run failed: {proc.stderr[:300]}"
            return result
        result["container_id"] = proc.stdout.strip()[:12]
        logger.info(f"[BURST:LOCAL] Container started: {result['container_id']}")
    except Exception as e:
        result["error"] = f"Docker run exception: {e}"
        return result

    # 4. Attendre que vLLM soit healthy
    health_url = f"http://{VLLM_LOCAL_CONTAINER}:8000"
    max_wait = 72  # 72 x 5s = 360s
    logger.info(f"[BURST:LOCAL] Waiting for vLLM health at {health_url} (max {max_wait*5}s)...")
    for i in range(max_wait):
        time.sleep(5)
        # Verifier que le container tourne encore
        try:
            check = subprocess.run(
                ["docker", "inspect", "--format={{.State.Running}}", VLLM_LOCAL_CONTAINER],
                capture_output=True, text=True, timeout=5,
            )
            if check.stdout.strip() != "true":
                # Container crash — lire les logs avant d'abandonner
                logs = subprocess.run(
                    ["docker", "logs", "--tail", "20", VLLM_LOCAL_CONTAINER],
                    capture_output=True, text=True, timeout=10,
                )
                result["error"] = f"vLLM container crashed: {logs.stderr[-300:] if logs.stderr else logs.stdout[-300:]}"
                logger.error(f"[BURST:LOCAL] Container crashed at {(i+1)*5}s: {result['error']}")
                return result
        except Exception:
            pass

        if _quick_health_check(health_url, timeout=5):
            logger.info(f"[BURST:LOCAL] vLLM healthy after {(i+1)*5}s")
            result["success"] = True
            break

        if (i + 1) % 12 == 0:  # Log toutes les 60s
            logger.info(f"[BURST:LOCAL] Still waiting... {(i+1)*5}s elapsed")
    else:
        # Timeout — ne PAS supprimer le container (garder pour debug)
        result["error"] = f"vLLM did not become healthy within {max_wait*5}s (container kept for debug: docker logs {VLLM_LOCAL_CONTAINER})"
        logger.error(f"[BURST:LOCAL] Timeout — container kept alive for inspection")
        return result

    # 5. Activer le burst via le provider_switch standard
    activation = activate_burst_providers(
        vllm_url=f"http://{VLLM_LOCAL_CONTAINER}:8000",
        embeddings_url="",  # Embeddings en CPU local, pas de TEI
        vllm_model=model,
    )
    if not activation.get("llm_router"):
        result["error"] = f"Burst activation failed: {activation.get('errors', [])}"
        result["success"] = False
        stop_local_vllm()
        return result

    # 6. Marquer le provider comme "local" dans Redis
    r = _get_redis_client()
    if r:
        try:
            state_raw = r.get(REDIS_BURST_STATE_KEY)
            if state_raw:
                state = json.loads(state_raw)
                state["provider"] = "local"
                r.setex(REDIS_BURST_STATE_KEY, 86400, json.dumps(state))
        except Exception:
            pass

    logger.info(f"[BURST:LOCAL] vLLM local ACTIVE: {model} on port {VLLM_LOCAL_PORT}")
    return result


def stop_local_vllm() -> Dict[str, Any]:
    """Arrete le container vLLM local et restaure le mode normal."""
    import subprocess

    result: Dict[str, Any] = {"success": False, "error": None}

    # 1. Desactiver le burst
    try:
        deactivate_burst_providers()
    except Exception as e:
        logger.warning(f"[BURST:LOCAL] Deactivation warning: {e}")

    # 2. Arreter le container
    try:
        proc = subprocess.run(
            ["docker", "rm", "-f", VLLM_LOCAL_CONTAINER],
            capture_output=True, text=True, timeout=15,
        )
        if proc.returncode == 0:
            logger.info("[BURST:LOCAL] Container stopped and removed")
            result["success"] = True
        else:
            result["error"] = f"Docker rm failed: {proc.stderr[:200]}"
    except Exception as e:
        result["error"] = f"Docker rm exception: {e}"

    logger.info("[BURST:LOCAL] vLLM local STOPPED — Ollama can resume")
    return result


def is_local_vllm_running() -> bool:
    """Verifie si le container vLLM local tourne."""
    import subprocess
    try:
        proc = subprocess.run(
            ["docker", "inspect", "--format={{.State.Running}}", VLLM_LOCAL_CONTAINER],
            capture_output=True, text=True, timeout=5,
        )
        return proc.stdout.strip() == "true"
    except Exception:
        return False
