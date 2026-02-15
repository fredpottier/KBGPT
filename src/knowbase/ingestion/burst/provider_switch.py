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
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# === Clés Redis pour l'état du burst (partagé entre tous les processus) ===
REDIS_BURST_STATE_KEY = "osmose:burst:state"


def _get_redis_client():
    """Récupère le client Redis."""
    try:
        from knowbase.common.clients.redis_client import get_redis_client
        return get_redis_client()
    except Exception as e:
        logger.warning(f"[BURST:REDIS] Cannot get Redis client: {e}")
        return None


def set_burst_state_in_redis(vllm_url: str, vllm_model: str, embeddings_url: str) -> bool:
    """
    Stocke l'état du burst dans Redis pour partage inter-processus.

    Cette fonction est appelée quand le burst est activé, permettant à tous les
    processus (worker, app, etc.) de savoir que vLLM est disponible.
    """
    redis = _get_redis_client()
    if not redis:
        return False

    try:
        state = {
            "active": True,
            "vllm_url": vllm_url,
            "vllm_model": vllm_model,
            "embeddings_url": embeddings_url
        }
        # RedisClient wraps the redis client, access via .client
        redis.client.set(REDIS_BURST_STATE_KEY, json.dumps(state))
        logger.info(f"[BURST:REDIS] State saved: vLLM={vllm_url}, model={vllm_model}")
        return True
    except Exception as e:
        logger.error(f"[BURST:REDIS] Failed to save state: {e}")
        return False


def clear_burst_state_in_redis() -> bool:
    """
    Supprime l'état du burst dans Redis (désactivation).
    """
    redis = _get_redis_client()
    if not redis:
        return False

    try:
        # RedisClient wraps the redis client, access via .client
        redis.client.delete(REDIS_BURST_STATE_KEY)
        logger.info("[BURST:REDIS] State cleared (burst deactivated)")
        return True
    except Exception as e:
        logger.error(f"[BURST:REDIS] Failed to clear state: {e}")
        return False


def get_burst_state_from_redis() -> Optional[Dict[str, Any]]:
    """
    Récupère l'état du burst depuis Redis.

    Utilisé par LLMRouter pour vérifier si vLLM est actif.

    Returns:
        Dict avec vllm_url, vllm_model, embeddings_url si actif, None sinon
    """
    redis = _get_redis_client()
    if not redis:
        return None

    try:
        # RedisClient wraps the redis client, access via .client
        data = redis.client.get(REDIS_BURST_STATE_KEY)
        if data:
            state = json.loads(data)
            if state.get("active"):
                return state
        return None
    except Exception as e:
        logger.debug(f"[BURST:REDIS] Failed to get state: {e}")
        return None


def _convert_to_vllm_model_name(model_name: Optional[str]) -> str:
    """
    Retourne le nom du modèle tel que servi par vLLM.

    Avec Golden AMI v9+, vLLM sert le modèle sous son nom HuggingFace natif
    (ex: "Qwen/Qwen3-14B-AWQ"), pas sous le chemin volume Docker.
    """
    if not model_name:
        return "Qwen/Qwen3-14B-AWQ"

    # Si c'est un ancien chemin /models/, convertir vers le format HuggingFace
    if model_name.startswith("/models/"):
        # "/models/Qwen--Qwen3-14B-AWQ" -> "Qwen/Qwen3-14B-AWQ"
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
        vllm_model: Modèle vLLM à utiliser (défaut: Qwen/Qwen3-14B-AWQ)
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
            dual_logger.enable(vllm_url, vllm_model=_convert_to_vllm_model_name(vllm_model))
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
            # Convertir le nom du modèle au format vLLM
            vllm_model_name = _convert_to_vllm_model_name(vllm_model)
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
        vllm_model_name = _convert_to_vllm_model_name(vllm_model)
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
