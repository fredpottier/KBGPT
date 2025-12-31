"""
OSMOSE Burst Provider Switch - Basculement dynamique des providers LLM/Embeddings

Ce module coordonne l'activation/désactivation du mode Burst pour tous les providers :
- LLMRouter : bascule vers vLLM sur EC2 Spot
- EmbeddingManager : bascule vers TEI sur EC2 Spot

Utilisé par le BurstOrchestrator quand l'instance EC2 est prête.

Author: OSMOSE Burst Ingestion
Date: 2025-12
"""

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


def _convert_to_vllm_model_name(model_name: Optional[str]) -> str:
    """
    Convertit un nom de modèle HuggingFace vers le format vLLM.

    vLLM expose les modèles avec le préfixe /models/ et remplace / par --
    Ex: "Qwen/Qwen2.5-14B-Instruct-AWQ" -> "/models/Qwen--Qwen2.5-14B-Instruct-AWQ"
    """
    if not model_name:
        return "/models/Qwen--Qwen2.5-14B-Instruct-AWQ"

    # Si déjà au bon format, retourner tel quel
    if model_name.startswith("/models/"):
        return model_name

    # Convertir HuggingFace format vers vLLM format
    # "Qwen/Qwen2.5-14B-Instruct-AWQ" -> "Qwen--Qwen2.5-14B-Instruct-AWQ"
    converted = model_name.replace("/", "--")
    return f"/models/{converted}"


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
        vllm_model: Modèle vLLM à utiliser (défaut: Qwen/Qwen2.5-7B-Instruct)
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

    if result["llm_router"] and result["embedding_manager"]:
        logger.info("[BURST:SWITCH] ✅ All providers switched back to normal")
    else:
        logger.warning(f"[BURST:SWITCH] ⚠️ Partial deactivation: {result}")

    return result


# Configuration des limites en mode Burst (sans rate limiting cloud)
# ATTENTION: Valeurs calibrées pour éviter saturation TEI/vLLM sur g6.2xlarge
# 2024-12-30: Réduit embedding_batch_chars de 6000→4000 pour éviter 413 Payload Too Large
# 2024-12-31: batch_size=1 pour éviter 413 intermittent sur AMI Golden TEI
BURST_CONCURRENCY_CONFIG = {
    "max_concurrent_llm": 15,        # Appels LLM simultanés (réduit de 20 pour stabilité)
    "max_parallel_segments": 8,      # Segments traités en parallèle (réduit de 10)
    "max_concurrent_embeddings": 6,  # Workers embeddings parallèles
    "max_concurrent_batches": 10,    # Batches gatekeeper (réduit de 15)
    "embedding_batch_size": 1,       # 1 texte par requête (évite 413 intermittent)
    "embedding_batch_chars": 600,    # Max chars par requête
    "embedding_max_text_chars": 500,  # Max chars par texte (réduit pour AMI Golden TEI)
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
