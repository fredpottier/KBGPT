"""
Système de routage automatique pour optimiser l'usage des modèles LLM
selon le type de tâche (vision, résumé long, métadonnées, enrichissement, etc.)
Configuration flexible via config/llm_models.yaml

IMPORTANT - Gate Redis pour vLLM:
Ce module vérifie automatiquement si vLLM est actif via Redis à chaque appel LLM.
Quand vLLM est actif (via page Burst ou Config), TOUS les appels non-vision sont
redirigés vers vLLM au lieu d'OpenAI, permettant des économies importantes.
"""
from __future__ import annotations

import json
import logging
import os
import time
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml

from knowbase.config.settings import get_settings
from knowbase.common.clients import get_openai_client, get_async_openai_client, get_anthropic_client, is_anthropic_available
from knowbase.common.token_tracker import track_tokens

# Import conditionnel pour SageMaker
try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError
    SAGEMAKER_AVAILABLE = True
except ImportError:
    SAGEMAKER_AVAILABLE = False

# Import conditionnel httpx pour vLLM client
try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

logger = logging.getLogger(__name__)


class VLLMUnavailableError(Exception):
    """
    Exception levée quand vLLM est configuré (burst mode) mais temporairement indisponible.

    Cette exception permet au code appelant de:
    - Suspendre le job en cours
    - Sauvegarder l'état (checkpoint)
    - Retenter plus tard quand vLLM sera de nouveau disponible

    Ne PAS attraper cette exception pour fallback vers OpenAI!
    """

    def __init__(self, vllm_url: str, message: str = "vLLM is temporarily unavailable"):
        self.vllm_url = vllm_url
        self.message = message
        super().__init__(f"{message}: {vllm_url}")


class TaskType(Enum):
    """Types de tâches LLM avec leurs modèles optimaux."""
    VISION = "vision"                    # Analyse d'images + texte
    METADATA_EXTRACTION = "metadata"     # Extraction de métadonnées JSON
    LONG_TEXT_SUMMARY = "long_summary"   # Résumés de textes volumineux
    SHORT_ENRICHMENT = "enrichment"      # Enrichissement de contenu court
    FAST_CLASSIFICATION = "classification" # Classification simple/rapide
    CANONICALIZATION = "canonicalization" # Normalisation de noms
    RFP_QUESTION_ANALYSIS = "rfp_question_analysis" # Analyse intelligente questions RFP
    TRANSLATION = "translation"           # Traduction de langues (tâche simple)
    KNOWLEDGE_EXTRACTION = "knowledge_extraction" # Extraction structurée concepts/facts/entities/relations


class LLMRouter:
    """
    Routeur intelligent pour les appels LLM selon le type de tâche.

    Supporte le mode Burst pour déporter les appels LLM vers EC2 Spot.
    En mode Burst, toutes les tâches texte sont redirigées vers vLLM distant,
    sauf Vision qui reste sur GPT-4o.
    """

    def __init__(self, config_path: Optional[Path] = None):
        self.settings = get_settings()
        self._openai_client = None
        self._async_openai_client = None
        self._anthropic_client = None
        self._sagemaker_client = None
        self._vllm_client = None
        self._async_vllm_client = None
        # === Mode Burst ===
        self._burst_mode = False
        self._burst_endpoint: Optional[str] = None
        self._burst_vllm_client = None
        self._burst_async_vllm_client = None
        self._burst_model: str = "Qwen/Qwen2.5-14B-Instruct-AWQ"  # Nom réel du modèle (pour logs)
        self._burst_vllm_served_model: str = "Qwen/Qwen2.5-14B-Instruct-AWQ"  # Nom exposé par vLLM (served_model_name)
        self._vllm_max_context: int = 16384  # Limite contexte vLLM (16K Qwen2.5, 32K Qwen3)

        # === Gate Redis pour vLLM (partage inter-processus) ===
        self._redis_burst_cache: Optional[Dict[str, Any]] = None
        self._redis_burst_cache_time: float = 0
        self._redis_burst_cache_ttl: float = 5.0  # Cache TTL en secondes

        # Configuration dynamique
        self._config = self._load_config(config_path)
        self._available_providers = self._detect_available_providers()

    def _load_config(self, config_path: Optional[Path] = None) -> Dict[str, Any]:
        """Charge la configuration des modèles depuis le fichier YAML."""
        if config_path is None:
            # Utilise le chemin par défaut
            from knowbase.config.paths import PROJECT_ROOT
            config_path = PROJECT_ROOT / "config" / "llm_models.yaml"

        try:
            with config_path.open("r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            logger.info(f"✓ Configuration LLM chargée depuis {config_path}")
            return config
        except Exception as e:
            logger.warning(f"⚠ Impossible de charger {config_path}: {e}")
            # Configuration par défaut si le fichier n'existe pas
            return {
                "task_models": {
                    "vision": "gpt-4o",
                    "metadata": "gpt-4o",
                    "long_summary": "gpt-4o",
                    "enrichment": "gpt-4o-mini",
                    "classification": "gpt-4o-mini",
                    "canonicalization": "gpt-4o-mini"
                },
                "default_model": "gpt-4o"
            }

    def _detect_available_providers(self) -> Dict[str, bool]:
        """Détecte quels providers LLM sont disponibles."""
        providers = {}

        # Test OpenAI
        try:
            get_openai_client()
            providers["openai"] = True
            logger.debug("✓ OpenAI provider disponible")
        except Exception as e:
            providers["openai"] = False
            logger.debug(f"✗ OpenAI provider indisponible: {e}")

        # Test Anthropic
        try:
            providers["anthropic"] = is_anthropic_available()
            if providers["anthropic"]:
                logger.debug("✓ Anthropic provider disponible")
            else:
                logger.debug("✗ Anthropic provider indisponible")
        except Exception as e:
            providers["anthropic"] = False
            logger.debug(f"✗ Anthropic provider indisponible: {e}")

        # Test SageMaker
        try:
            if SAGEMAKER_AVAILABLE:
                # Test basique de disponibilité AWS credentials
                boto3.Session().get_credentials()
                providers["sagemaker"] = True
                logger.debug("✓ SageMaker provider disponible")
            else:
                providers["sagemaker"] = False
                logger.debug("✗ SageMaker provider indisponible (boto3 non installé)")
        except (NoCredentialsError, Exception) as e:
            providers["sagemaker"] = False
            logger.debug(f"✗ SageMaker provider indisponible: {e}")

        # Test vLLM (EC2 burst mode)
        vllm_url = os.getenv("VLLM_URL", "").strip()
        if vllm_url:
            try:
                # Test de connectivité basique vers vLLM
                if HTTPX_AVAILABLE:
                    with httpx.Client(timeout=5.0) as client:
                        response = client.get(f"{vllm_url}/health")
                        if response.status_code == 200:
                            providers["vllm"] = True
                            logger.info(f"✓ vLLM provider disponible ({vllm_url})")
                        else:
                            providers["vllm"] = False
                            logger.debug(f"✗ vLLM health check failed: {response.status_code}")
                else:
                    # httpx non disponible, on suppose que vLLM est ok si URL configurée
                    providers["vllm"] = True
                    logger.debug(f"✓ vLLM provider configuré (URL: {vllm_url}, no health check)")
            except Exception as e:
                providers["vllm"] = False
                logger.debug(f"✗ vLLM provider indisponible: {e}")
        else:
            providers["vllm"] = False
            logger.debug("✗ vLLM provider non configuré (VLLM_URL manquant)")

        # Test Ollama (inférence locale)
        ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434").strip()
        try:
            if HTTPX_AVAILABLE:
                with httpx.Client(timeout=3.0) as client:
                    response = client.get(f"{ollama_url}/api/tags")
                    if response.status_code == 200:
                        providers["ollama"] = True
                        logger.info(f"✓ Ollama provider disponible ({ollama_url})")
                    else:
                        providers["ollama"] = False
                        logger.debug(f"✗ Ollama health check failed: {response.status_code}")
            else:
                providers["ollama"] = False
        except Exception as e:
            providers["ollama"] = False
            logger.debug(f"✗ Ollama provider indisponible: {e}")

        return providers

    # =========================================================================
    # Mode Burst - Basculement dynamique vers EC2 Spot
    # =========================================================================

    def enable_burst_mode(self, vllm_url: str, model: Optional[str] = None, max_context: Optional[int] = None):
        """
        Active le mode Burst : redirige les appels LLM vers EC2 Spot.

        En mode Burst :
        - Toutes les tâches texte (metadata, summary, enrichment, etc.) → vLLM distant
        - Les tâches VISION restent sur GPT-4o (gating préserve les coûts)

        Args:
            vllm_url: URL du serveur vLLM (ex: http://ec2-xxx:8000)
            model: Modèle vLLM à utiliser (défaut: Qwen/Qwen2.5-14B-Instruct-AWQ)
            max_context: Limite de contexte vLLM (défaut: 16384 pour Qwen2.5, 32768 pour Qwen3)
        """
        from openai import OpenAI, AsyncOpenAI

        self._burst_mode = True
        self._burst_endpoint = vllm_url.rstrip("/")
        self._burst_model = model or "Qwen/Qwen2.5-14B-Instruct-AWQ"
        self._burst_vllm_served_model = self._burst_model  # vLLM sert le modèle sous son vrai nom

        # Contexte dynamique selon le modèle
        if max_context:
            self._vllm_max_context = max_context
        elif self._is_qwen3:
            self._vllm_max_context = 32768
        else:
            self._vllm_max_context = 16384

        # Créer clients vLLM dédiés au mode burst
        self._burst_vllm_client = OpenAI(
            api_key="EMPTY",  # vLLM n'utilise pas d'API key
            base_url=f"{self._burst_endpoint}/v1"
        )
        self._burst_async_vllm_client = AsyncOpenAI(
            api_key="EMPTY",
            base_url=f"{self._burst_endpoint}/v1"
        )

        logger.info(f"[LLM_ROUTER] 🚀 Burst mode ENABLED → {vllm_url} (model: {self._burst_model}, is_qwen3={self._is_qwen3})")

    def disable_burst_mode(self):
        """
        Désactive le mode Burst, retour aux providers normaux.
        """
        if not self._burst_mode:
            logger.debug("[LLM_ROUTER] Burst mode already disabled")
            return

        self._burst_mode = False
        self._burst_endpoint = None
        self._burst_vllm_client = None
        self._burst_async_vllm_client = None

        logger.info("[LLM_ROUTER] ⏹️ Burst mode DISABLED → Normal providers")

    def is_burst_mode_active(self) -> bool:
        """Vérifie si le mode Burst est actif."""
        return self._burst_mode and self._burst_vllm_client is not None

    def get_burst_status(self) -> Dict[str, Any]:
        """Retourne le statut du mode Burst."""
        return {
            "burst_mode": self._burst_mode,
            "burst_endpoint": self._burst_endpoint,
            "burst_model": self._burst_model if self._burst_mode else None,
            "client_ready": self._burst_vllm_client is not None
        }

    @property
    def _is_qwen3(self) -> bool:
        """Détecte si le modèle burst actif est Qwen3."""
        for name in (self._burst_vllm_served_model, self._burst_model):
            if name and "qwen3" in name.lower():
                return True
        return False

    # =========================================================================
    # Gate Redis - Vérification dynamique vLLM (inter-processus)
    # =========================================================================

    def _get_vllm_state_from_redis(self) -> Optional[Dict[str, Any]]:
        """
        Récupère l'état vLLM depuis Redis avec cache et health check.

        Cette méthode est la "gate" qui permet à tous les processus de savoir
        si vLLM est actif, avec vérification périodique de santé.

        IMPORTANT: Ne désactive PAS automatiquement le burst mode quand vLLM est down.
        Au lieu de ça, retourne l'état avec un flag "healthy" pour permettre au
        code appelant de décider (suspendre le job, retenter, etc.)

        Cache:
        - Redis state: TTL 5 secondes (évite de spammer Redis)
        - Health check: TTL 30 secondes (évite de spammer vLLM)

        Returns:
            Dict avec vllm_url, vllm_model, healthy si vLLM configuré, None si pas de burst
        """
        now = time.time()

        # Vérifier le cache
        if self._redis_burst_cache is not None:
            cache_age = now - self._redis_burst_cache_time
            if cache_age < self._redis_burst_cache_ttl:
                if self._redis_burst_cache.get("active"):
                    return self._redis_burst_cache
                return None

        # Cache expiré, vérifier Redis
        try:
            from knowbase.ingestion.burst.provider_switch import get_burst_state_from_redis
            state = get_burst_state_from_redis()

            if state and state.get("active"):
                # vLLM censé être actif, vérifier health (cache 30s)
                vllm_url = state.get("vllm_url")
                is_healthy = vllm_url and self._check_vllm_health(vllm_url)

                # Ajouter le flag healthy à l'état
                state["healthy"] = is_healthy

                if is_healthy:
                    # vLLM actif et healthy
                    logger.debug(f"[LLM_ROUTER:GATE] vLLM healthy: {vllm_url}")
                else:
                    # vLLM configuré mais DOWN — vérifier si l'instance Spot a été réclamée
                    spot_terminated = self._check_spot_instance_terminated(vllm_url)
                    if spot_terminated:
                        # Instance définitivement terminée → purger le burst state
                        logger.error(
                            f"[LLM_ROUTER:GATE] EC2 Spot instance TERMINATED for {vllm_url}. "
                            f"Purging burst state."
                        )
                        try:
                            from knowbase.ingestion.burst.provider_switch import clear_burst_state_in_redis
                            clear_burst_state_in_redis()
                        except Exception as purge_err:
                            logger.error(f"[LLM_ROUTER:GATE] Failed to purge burst state: {purge_err}")
                        state["healthy"] = False
                        state["active"] = False
                        state["spot_terminated"] = True
                        self._redis_burst_cache = state
                        self._redis_burst_cache_time = now
                        return state
                    else:
                        logger.warning(
                            f"[LLM_ROUTER:GATE] vLLM configured but DOWN: {vllm_url}. "
                            f"Instance still exists — may recover. Raising for job suspension."
                        )

                self._redis_burst_cache = state
                self._redis_burst_cache_time = now
                return state
            else:
                # Pas de vLLM actif dans Redis
                self._redis_burst_cache = {"active": False}
                self._redis_burst_cache_time = now
                return None

        except Exception as e:
            logger.debug(f"[LLM_ROUTER:GATE] Error checking Redis: {e}")
            self._redis_burst_cache = {"active": False}
            self._redis_burst_cache_time = now
            return None

    def _check_vllm_health(self, vllm_url: str) -> bool:
        """
        Vérifie si vLLM est accessible avec cache.

        Health check avec cache de 30 secondes pour éviter de spammer.
        """
        # Utiliser un attribut pour le cache health
        if not hasattr(self, "_vllm_health_cache"):
            self._vllm_health_cache: Dict[str, tuple] = {}  # {url: (is_healthy, timestamp)}

        now = time.time()
        health_ttl = 30.0  # 30 secondes de cache pour le health check

        # Vérifier le cache
        if vllm_url in self._vllm_health_cache:
            is_healthy, check_time = self._vllm_health_cache[vllm_url]
            if now - check_time < health_ttl:
                return is_healthy

        # Cache expiré, faire le health check
        try:
            if HTTPX_AVAILABLE:
                with httpx.Client(timeout=3.0) as client:
                    response = client.get(f"{vllm_url}/health")
                    is_healthy = response.status_code == 200
            else:
                # Pas de httpx, supposer healthy si URL configurée
                is_healthy = True

            self._vllm_health_cache[vllm_url] = (is_healthy, now)

            if is_healthy:
                logger.debug(f"[LLM_ROUTER:GATE] vLLM health OK: {vllm_url}")
            else:
                logger.warning(f"[LLM_ROUTER:GATE] vLLM health FAILED: {vllm_url}")

            return is_healthy

        except Exception as e:
            logger.warning(f"[LLM_ROUTER:GATE] vLLM health check error: {e}")
            self._vllm_health_cache[vllm_url] = (False, now)
            return False

    def _check_spot_instance_terminated(self, vllm_url: str) -> bool:
        """
        Vérifie via AWS CLI si l'instance Spot associée au vLLM a été terminée.

        Extrait l'IP du vllm_url, cherche l'instance EC2 correspondante,
        et retourne True si elle est dans l'état 'terminated' ou introuvable.

        Cache de 60 secondes pour éviter de spammer l'API AWS.
        """
        import re
        import subprocess

        if not hasattr(self, "_spot_check_cache"):
            self._spot_check_cache: Dict[str, tuple] = {}

        now = time.time()
        spot_check_ttl = 60.0

        if vllm_url in self._spot_check_cache:
            is_terminated, check_time = self._spot_check_cache[vllm_url]
            if now - check_time < spot_check_ttl:
                return is_terminated

        # Extraire l'IP du vllm_url
        ip_match = re.search(r"(\d+\.\d+\.\d+\.\d+)", vllm_url)
        if not ip_match:
            self._spot_check_cache[vllm_url] = (False, now)
            return False

        ip = ip_match.group(1)

        try:
            result = subprocess.run(
                [
                    "aws", "ec2", "describe-instances",
                    "--region", "eu-central-1",
                    "--filters", f"Name=ip-address,Values={ip}",
                    "--query", "Reservations[].Instances[].State.Name",
                    "--output", "text",
                ],
                capture_output=True, text=True, timeout=10,
            )

            state_text = result.stdout.strip()

            if not state_text:
                # Aucune instance trouvée avec cette IP → probablement terminée et IP libérée
                # Chercher par IP privée aussi
                result2 = subprocess.run(
                    [
                        "aws", "ec2", "describe-instances",
                        "--region", "eu-central-1",
                        "--filters",
                        "Name=instance-state-name,Values=running,stopped,stopping,pending",
                        "Name=network-interface.association.public-ip,Values=" + ip,
                        "--query", "Reservations[].Instances[].State.Name",
                        "--output", "text",
                    ],
                    capture_output=True, text=True, timeout=10,
                )
                if not result2.stdout.strip():
                    logger.warning(
                        f"[LLM_ROUTER:SPOT] No EC2 instance found for IP {ip} — "
                        f"Spot instance likely terminated/reclaimed."
                    )
                    self._spot_check_cache[vllm_url] = (True, now)
                    return True

            if state_text in ("terminated", "shutting-down"):
                logger.warning(
                    f"[LLM_ROUTER:SPOT] EC2 instance at {ip} is '{state_text}' — "
                    f"Spot reclaimed by AWS."
                )
                self._spot_check_cache[vllm_url] = (True, now)
                return True

            # Instance existe mais dans un autre état (stopped, running, etc.)
            logger.info(f"[LLM_ROUTER:SPOT] EC2 instance at {ip} state='{state_text}'")
            self._spot_check_cache[vllm_url] = (False, now)
            return False

        except Exception as e:
            logger.debug(f"[LLM_ROUTER:SPOT] AWS CLI check failed: {e}")
            self._spot_check_cache[vllm_url] = (False, now)
            return False

    def _ensure_burst_client_for_redis_state(self, state: Dict[str, Any]) -> bool:
        """
        S'assure que les clients burst sont initialisés pour l'état Redis.

        Appelé quand on détecte vLLM actif via Redis mais que le processus
        local n'a pas encore les clients initialisés.
        """
        vllm_url = state.get("vllm_url")
        vllm_model = state.get("vllm_model")

        if not vllm_url:
            return False

        # Si déjà initialisé avec la même URL, OK
        if self._burst_mode and self._burst_endpoint == vllm_url and self._burst_vllm_client:
            return True

        # Initialiser les clients
        try:
            from openai import OpenAI, AsyncOpenAI

            self._burst_mode = True
            self._burst_endpoint = vllm_url.rstrip("/")
            self._burst_model = vllm_model or "Qwen/Qwen2.5-14B-Instruct-AWQ"
            self._burst_vllm_served_model = self._burst_model  # vLLM sert le modèle sous son vrai nom

            # Contexte dynamique selon le modèle détecté
            self._vllm_max_context = 32768 if self._is_qwen3 else 16384

            self._burst_vllm_client = OpenAI(
                api_key="EMPTY",
                base_url=f"{self._burst_endpoint}/v1"
            )
            self._burst_async_vllm_client = AsyncOpenAI(
                api_key="EMPTY",
                base_url=f"{self._burst_endpoint}/v1"
            )

            logger.info(f"[LLM_ROUTER:GATE] Auto-enabled burst from Redis: {vllm_url} (model: {self._burst_model})")
            return True

        except Exception as e:
            logger.error(f"[LLM_ROUTER:GATE] Failed to init burst client: {e}")
            return False

    @property
    def openai_client(self):
        """Client OpenAI paresseux."""
        if self._openai_client is None:
            self._openai_client = get_openai_client()
        return self._openai_client

    @property
    def async_openai_client(self):
        """Client OpenAI async paresseux pour appels parallèles."""
        if self._async_openai_client is None:
            self._async_openai_client = get_async_openai_client()
        return self._async_openai_client

    @property
    def anthropic_client(self):
        """Client Anthropic paresseux."""
        if self._anthropic_client is None:
            self._anthropic_client = get_anthropic_client()
        return self._anthropic_client

    @property
    def sagemaker_client(self):
        """Client SageMaker paresseux."""
        if self._sagemaker_client is None and SAGEMAKER_AVAILABLE:
            self._sagemaker_client = boto3.client('sagemaker-runtime')
        return self._sagemaker_client

    @property
    def vllm_client(self):
        """Client vLLM paresseux (API OpenAI-compatible)."""
        if self._vllm_client is None:
            vllm_url = os.getenv("VLLM_URL", "").strip()
            if not vllm_url:
                raise ValueError("VLLM_URL not configured")
            # vLLM expose une API OpenAI-compatible, on utilise le client OpenAI
            from openai import OpenAI
            self._vllm_client = OpenAI(
                api_key="EMPTY",  # vLLM n'utilise pas d'API key
                base_url=f"{vllm_url}/v1"
            )
        return self._vllm_client

    @property
    def async_vllm_client(self):
        """Client vLLM async paresseux."""
        if self._async_vllm_client is None:
            vllm_url = os.getenv("VLLM_URL", "").strip()
            if not vllm_url:
                raise ValueError("VLLM_URL not configured")
            from openai import AsyncOpenAI
            self._async_vllm_client = AsyncOpenAI(
                api_key="EMPTY",
                base_url=f"{vllm_url}/v1"
            )
        return self._async_vllm_client

    def _get_provider_for_model(self, model: str) -> str:
        """Détecte automatiquement le provider d'un modèle."""
        # Vérification dans la config d'abord
        providers = self._config.get("providers", {})
        for provider_name, provider_config in providers.items():
            models = provider_config.get("models", [])
            if model in models:
                return provider_name

        # Détection par nom si pas dans la config
        if model.startswith(("gpt-", "o1-")):
            return "openai"
        elif model.startswith("claude-"):
            return "anthropic"
        elif model in ["llama3.1:70b", "qwen2.5:32b", "qwen2.5:7b", "llava:34b", "phi3:3.8b"]:
            return "sagemaker"
        # Ollama models (format "name:tag" sans "/" — ex: qwen3.5:9b-q8_0, gemma3:4b)
        elif ":" in model and "/" not in model and not model.startswith(("gpt-", "o1-", "claude-")):
            return "ollama"
        # vLLM models (Qwen, Llama served via vLLM on EC2)
        elif model.startswith(("Qwen/", "meta-llama/", "mistralai/")):
            return "vllm"
        elif "vllm:" in model:
            # Syntaxe explicite: "vllm:Qwen/Qwen3-14B-AWQ"
            return "vllm"
        else:
            # Fallback vers OpenAI par défaut
            return "openai"

    def _get_model_for_task(self, task_type: TaskType) -> str:
        """Détermine le modèle selon la configuration."""
        task_name = task_type.value
        task_models = self._config.get("task_models", {})

        # Modèle configuré pour cette tâche
        model = task_models.get(task_name)

        if model and self._is_model_available(model):
            return model

        # Essayer les fallbacks
        fallbacks = self._config.get("fallback_strategy", {}).get(task_name, [])
        for fallback_model in fallbacks:
            if self._is_model_available(fallback_model):
                logger.info(f"🔄 Fallback {task_name}: {model} → {fallback_model}")
                return fallback_model

        # Dernier recours : modèle par défaut
        default = self._config.get("default_model", "gpt-4o")
        logger.warning(f"⚠ Utilisation du modèle par défaut pour {task_name}: {default}")
        return default

    def _is_model_available(self, model: str) -> bool:
        """Vérifie si un modèle est disponible."""
        provider = self._get_provider_for_model(model)
        return self._available_providers.get(provider, False)

    def complete(
        self,
        task_type: TaskType,
        messages: List[Dict[str, Any]],
        temperature: float = None,
        max_tokens: int = None,
        **kwargs
    ) -> str:
        """
        Effectue un appel LLM en routant vers le modèle optimal.

        Args:
            task_type: Type de tâche pour choisir le modèle
            messages: Messages au format standard
            temperature: Température (0.0 à 1.0). Si None, utilise les paramètres du YAML
            max_tokens: Limite de tokens de réponse. Si None, utilise les paramètres du YAML
            **kwargs: Arguments supplémentaires

        Returns:
            Contenu de la réponse du modèle
        """
        model = self._get_model_for_task(task_type)
        provider = self._get_provider_for_model(model)

        # Utilise les paramètres du YAML si non spécifiés
        task_name = task_type.value
        task_params = self._config.get("task_parameters", {}).get(task_name, {})

        if temperature is None:
            temperature = task_params.get("temperature", 0.2)
        if max_tokens is None:
            max_tokens = task_params.get("max_tokens", 1024)

        logger.debug(f"[LLM_ROUTER] Task: {task_type.value}, Default: {model}/{provider}, Temp: {temperature}, Tokens: {max_tokens}")

        try:
            # === Gate Redis : vérifier si vLLM actif via Redis (inter-processus) ===
            # Cette gate permet au worker de savoir que vLLM est actif même si
            # enable_burst_mode() a été appelé dans un autre processus (app)
            if task_type != TaskType.VISION:  # Vision reste TOUJOURS sur GPT-4o
                redis_state = self._get_vllm_state_from_redis()
                logger.debug(f"[LLM_ROUTER:GATE] Redis check: found={redis_state is not None}, local_burst={self._burst_mode}")

                if redis_state:
                    # vLLM configuré via Redis
                    vllm_url = redis_state.get("vllm_url", "unknown")
                    is_healthy = redis_state.get("healthy", False)

                    # Si vLLM configuré mais DOWN → lever exception pour suspension
                    if not is_healthy:
                        logger.error(
                            f"[LLM_ROUTER:GATE] ❌ vLLM configured but DOWN: {vllm_url}. "
                            f"Raising VLLMUnavailableError for job suspension."
                        )
                        raise VLLMUnavailableError(vllm_url, "vLLM health check failed")

                    # vLLM healthy, s'assurer que les clients sont initialisés
                    init_ok = self._ensure_burst_client_for_redis_state(redis_state)
                    logger.info(f"[LLM_ROUTER:GATE] Burst init from Redis: ok={init_ok}, endpoint={self._burst_endpoint}")

                    if init_ok:
                        logger.info(f"[LLM_ROUTER:GATE] ✅ Routing to vLLM: {self._burst_endpoint}")
                        return self._call_burst_vllm(messages, temperature, max_tokens, task_type, **kwargs)
                    else:
                        # Init failed mais vLLM était healthy - erreur inattendue
                        raise VLLMUnavailableError(vllm_url, "Failed to initialize burst client")

            # === Mode Burst local : rediriger vers EC2 Spot (sauf Vision) ===
            if self._burst_mode and self._burst_vllm_client:
                # Vision reste TOUJOURS sur GPT-4o (avec gating)
                if task_type == TaskType.VISION:
                    logger.info(f"[LLM_ROUTER:BURST] Vision task → GPT-4o (preserved)")
                    return self._call_openai(model, messages, temperature, max_tokens, task_type, **kwargs)
                else:
                    logger.info(f"[LLM_ROUTER:BURST] ✅ Text task → {self._burst_endpoint} ({self._burst_model})")
                    return self._call_burst_vllm(messages, temperature, max_tokens, task_type, **kwargs)

            # === Mode Normal (pas de burst) ===
            # ATTENTION: On arrive ici seulement si burst mode n'est PAS actif
            logger.info(f"[LLM_ROUTER] No burst mode - routing to {provider} (model={model})")
            if provider == "openai":
                return self._call_openai(model, messages, temperature, max_tokens, task_type, **kwargs)
            elif provider == "anthropic":
                return self._call_anthropic(model, messages, temperature, max_tokens, task_type, **kwargs)
            elif provider == "ollama":
                return self._call_ollama(model, messages, temperature, max_tokens, task_type, **kwargs)
            elif provider == "sagemaker":
                return self._call_sagemaker(model, messages, temperature, max_tokens, task_type, **kwargs)
            elif provider == "vllm":
                return self._call_vllm(model, messages, temperature, max_tokens, task_type, **kwargs)
            else:
                raise ValueError(f"Provider {provider} non supporté")

        except Exception as e:
            logger.error(f"[LLM_ROUTER] Error with {model} ({provider}): {e}")

            # IMPORTANT: Pas de fallback OpenAI si burst mode actif
            # On laisse l'erreur remonter pour que le job puisse être suspendu/repris
            # Vérifier AUSSI Redis (pas seulement le flag mémoire locale)
            # car après un restart de conteneur, _burst_mode est False en mémoire
            # mais la clé Redis osmose:burst:state peut encore être active.
            redis_burst_active = False
            if not self._burst_mode:
                try:
                    from knowbase.ingestion.burst.provider_switch import get_burst_state_from_redis
                    rs = get_burst_state_from_redis()
                    redis_burst_active = bool(rs and rs.get("active"))
                except Exception:
                    pass

            if self._burst_mode or redis_burst_active:
                logger.error(
                    f"[LLM_ROUTER:BURST] ❌ vLLM call failed, NO fallback to OpenAI. "
                    f"(local_burst={self._burst_mode}, redis_burst={redis_burst_active}) "
                    f"Error: {e}"
                )
                raise

            # Fallback d'urgence UNIQUEMENT si pas en burst mode (ni local ni Redis)
            default_model = self._config.get("default_model", "gpt-4o")
            if model != default_model:
                logger.info(f"[LLM_ROUTER] Fallback emergency to {default_model}")
                return self._call_openai(default_model, messages, temperature, max_tokens, task_type, **kwargs)
            raise

    async def acomplete(
        self,
        task_type: TaskType,
        messages: List[Dict[str, Any]],
        temperature: float = None,
        max_tokens: int = None,
        **kwargs
    ) -> str:
        """
        Effectue un appel LLM async en routant vers le modèle optimal.
        Version async pour permettre la parallélisation des appels.

        Args:
            task_type: Type de tâche pour choisir le modèle
            messages: Messages au format standard
            temperature: Température (0.0 à 1.0). Si None, utilise les paramètres du YAML
            max_tokens: Limite de tokens de réponse. Si None, utilise les paramètres du YAML
            **kwargs: Arguments supplémentaires

        Returns:
            Contenu de la réponse du modèle
        """
        model = self._get_model_for_task(task_type)
        provider = self._get_provider_for_model(model)

        # Utilise les paramètres du YAML si non spécifiés
        task_name = task_type.value
        task_params = self._config.get("task_parameters", {}).get(task_name, {})

        if temperature is None:
            temperature = task_params.get("temperature", 0.2)
        if max_tokens is None:
            max_tokens = task_params.get("max_tokens", 1024)

        logger.debug(f"[LLM_ROUTER:ASYNC] Task: {task_type.value}, Default: {model}/{provider}, Temp: {temperature}, Tokens: {max_tokens}")

        try:
            # === Gate Redis : vérifier si vLLM actif via Redis (inter-processus) ===
            # Cette gate permet au worker de savoir que vLLM est actif même si
            # enable_burst_mode() a été appelé dans un autre processus (app)
            if task_type != TaskType.VISION:  # Vision reste TOUJOURS sur GPT-4o
                redis_state = self._get_vllm_state_from_redis()
                logger.debug(f"[LLM_ROUTER:GATE] Redis check: found={redis_state is not None}, local_burst={self._burst_mode}")

                if redis_state:
                    # vLLM configuré via Redis
                    vllm_url = redis_state.get("vllm_url", "unknown")
                    is_healthy = redis_state.get("healthy", False)

                    # Si vLLM configuré mais DOWN → lever exception pour suspension
                    if not is_healthy:
                        logger.error(
                            f"[LLM_ROUTER:GATE:ASYNC] ❌ vLLM configured but DOWN: {vllm_url}. "
                            f"Raising VLLMUnavailableError for job suspension."
                        )
                        raise VLLMUnavailableError(vllm_url, "vLLM health check failed")

                    # vLLM healthy, s'assurer que les clients sont initialisés
                    init_ok = self._ensure_burst_client_for_redis_state(redis_state)
                    logger.info(f"[LLM_ROUTER:GATE] Burst init from Redis: ok={init_ok}, endpoint={self._burst_endpoint}")

                    if init_ok:
                        logger.info(f"[LLM_ROUTER:GATE:ASYNC] ✅ Routing to vLLM: {self._burst_endpoint}")
                        return await self._call_burst_vllm_async(messages, temperature, max_tokens, task_type, **kwargs)
                    else:
                        # Init failed mais vLLM était healthy - erreur inattendue
                        raise VLLMUnavailableError(vllm_url, "Failed to initialize burst client")

            # === Mode Burst local : rediriger vers EC2 Spot (sauf Vision) ===
            if self._burst_mode and self._burst_async_vllm_client:
                # Vision reste TOUJOURS sur GPT-4o (avec gating)
                if task_type == TaskType.VISION:
                    logger.info(f"[LLM_ROUTER:ASYNC:BURST] Vision task → GPT-4o (preserved)")
                    return await self._call_openai_async(model, messages, temperature, max_tokens, task_type, **kwargs)
                else:
                    logger.info(f"[LLM_ROUTER:ASYNC:BURST] ✅ Text task → {self._burst_endpoint} ({self._burst_model})")
                    return await self._call_burst_vllm_async(messages, temperature, max_tokens, task_type, **kwargs)

            # === Mode Normal (pas de burst) ===
            # ATTENTION: On arrive ici seulement si burst mode n'est PAS actif
            logger.info(f"[LLM_ROUTER:ASYNC] No burst mode - routing to {provider} (model={model})")
            if provider == "openai":
                return await self._call_openai_async(model, messages, temperature, max_tokens, task_type, **kwargs)
            elif provider == "anthropic":
                # TODO: Implémenter version async pour Anthropic si nécessaire
                logger.warning("[LLM_ROUTER:ASYNC] Anthropic async not implemented, falling back to sync")
                return self._call_anthropic(model, messages, temperature, max_tokens, task_type, **kwargs)
            elif provider == "ollama":
                return await self._call_ollama_async(model, messages, temperature, max_tokens, task_type, **kwargs)
            elif provider == "sagemaker":
                # TODO: Implémenter version async pour SageMaker si nécessaire
                logger.warning("[LLM_ROUTER:ASYNC] SageMaker async not implemented, falling back to sync")
                return self._call_sagemaker(model, messages, temperature, max_tokens, task_type, **kwargs)
            elif provider == "vllm":
                return await self._call_vllm_async(model, messages, temperature, max_tokens, task_type, **kwargs)
            else:
                raise ValueError(f"Provider {provider} non supporté")

        except Exception as e:
            logger.error(f"[LLM_ROUTER:ASYNC] Error with {model} ({provider}): {e}")

            # IMPORTANT: Pas de fallback OpenAI si burst mode actif
            # On laisse l'erreur remonter pour que le job puisse être suspendu/repris
            # Vérifier AUSSI Redis (pas seulement le flag mémoire locale)
            # car après un restart de conteneur, _burst_mode est False en mémoire
            # mais la clé Redis osmose:burst:state peut encore être active.
            redis_burst_active = False
            if not self._burst_mode:
                try:
                    from knowbase.ingestion.burst.provider_switch import get_burst_state_from_redis
                    rs = get_burst_state_from_redis()
                    redis_burst_active = bool(rs and rs.get("active"))
                except Exception:
                    pass

            if self._burst_mode or redis_burst_active:
                logger.error(
                    f"[LLM_ROUTER:ASYNC:BURST] ❌ vLLM call failed, NO fallback to OpenAI. "
                    f"(local_burst={self._burst_mode}, redis_burst={redis_burst_active}) "
                    f"Error: {e}"
                )
                raise

            # Fallback d'urgence UNIQUEMENT si pas en burst mode (ni local ni Redis)
            default_model = self._config.get("default_model", "gpt-4o")
            if model != default_model:
                logger.info(f"[LLM_ROUTER:ASYNC] Fallback emergency to {default_model}")
                return await self._call_openai_async(default_model, messages, temperature, max_tokens, task_type, **kwargs)
            raise

    def _call_openai(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        task_type: TaskType,
        **kwargs
    ) -> str:
        """Appel vers OpenAI."""
        # Filtrer les paramètres internes qui ne doivent pas être passés à l'API
        api_kwargs = {k: v for k, v in kwargs.items() if k not in ['model_preference']}

        response = self.openai_client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **api_kwargs
        )

        # Log et tracking des métriques de tokens
        if response.usage:
            prompt_tokens = response.usage.prompt_tokens
            completion_tokens = response.usage.completion_tokens
            total_tokens = response.usage.total_tokens
            logger.info(f"[TOKENS] {model} - Input: {prompt_tokens}, Output: {completion_tokens}, Total: {total_tokens}")

            # Tracking pour analyse des coûts
            track_tokens(model, task_type.value, prompt_tokens, completion_tokens)

        return response.choices[0].message.content or ""

    async def _call_openai_async(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        task_type: TaskType,
        **kwargs
    ) -> str:
        """Appel async vers OpenAI pour parallélisation."""
        # Filtrer les paramètres internes qui ne doivent pas être passés à l'API
        api_kwargs = {k: v for k, v in kwargs.items() if k not in ['model_preference']}

        response = await self.async_openai_client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **api_kwargs
        )

        # Log et tracking des métriques de tokens
        if response.usage:
            prompt_tokens = response.usage.prompt_tokens
            completion_tokens = response.usage.completion_tokens
            total_tokens = response.usage.total_tokens
            logger.info(f"[TOKENS:ASYNC] {model} - Input: {prompt_tokens}, Output: {completion_tokens}, Total: {total_tokens}")

            # Tracking pour analyse des coûts
            track_tokens(model, task_type.value, prompt_tokens, completion_tokens)

        return response.choices[0].message.content or ""

    def _call_anthropic(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        task_type: TaskType,
        **kwargs
    ) -> str:
        """Appel vers Anthropic Claude."""
        # Filtrer les paramètres internes qui ne doivent pas être passés à l'API
        api_kwargs = {k: v for k, v in kwargs.items() if k not in ['model_preference']}

        # Conversion du format OpenAI vers Anthropic
        system_message = ""
        user_messages = []

        for msg in messages:
            if msg.get("role") == "system":
                system_message = msg.get("content", "")
            else:
                user_messages.append(msg)

        # Appel Anthropic
        response = self.anthropic_client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_message,
            messages=user_messages,
            **api_kwargs
        )

        # Log et tracking des métriques de tokens
        if response.usage:
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            total_tokens = input_tokens + output_tokens
            logger.info(f"[TOKENS] {model} - Input: {input_tokens}, Output: {output_tokens}, Total: {total_tokens}")

            # Tracking pour analyse des coûts
            track_tokens(model, task_type.value, input_tokens, output_tokens)

        return response.content[0].text if response.content else ""

    def _call_sagemaker(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        task_type: TaskType,
        **kwargs
    ) -> str:
        """Appel vers SageMaker Endpoint."""
        if not SAGEMAKER_AVAILABLE:
            raise ValueError("Boto3 non disponible pour SageMaker")

        # Mapping modèle -> endpoint name (à configurer selon vos déploiements)
        endpoint_mapping = self._config.get("sagemaker_endpoints", {})
        endpoint_name = endpoint_mapping.get(model)

        if not endpoint_name:
            raise ValueError(f"Endpoint SageMaker non configuré pour {model}")

        # Formatage des messages selon le modèle
        if model.startswith("llama"):
            # Format Llama
            prompt = self._format_llama_prompt(messages)
        elif model.startswith("qwen"):
            # Format Qwen
            prompt = self._format_qwen_prompt(messages)
        elif model.startswith("llava"):
            # Format LLaVA (vision)
            prompt = self._format_llava_prompt(messages)
        else:
            # Format générique
            prompt = self._format_generic_prompt(messages)

        # Payload SageMaker
        payload = {
            "inputs": prompt,
            "parameters": {
                "temperature": temperature,
                "max_new_tokens": max_tokens,
                "do_sample": True if temperature > 0 else False,
            }
        }

        try:
            # Appel SageMaker
            response = self.sagemaker_client.invoke_endpoint(
                EndpointName=endpoint_name,
                ContentType="application/json",
                Body=json.dumps(payload)
            )

            # Parse response
            result = json.loads(response['Body'].read().decode())

            # Extraction du texte généré (format dépend du modèle)
            generated_text = self._extract_sagemaker_response(result, model)

            # Estimation des tokens (SageMaker ne fournit pas toujours les métriques)
            input_tokens = self._estimate_tokens(prompt)
            output_tokens = self._estimate_tokens(generated_text)

            logger.info(f"[TOKENS] {model} - Input: {input_tokens}, Output: {output_tokens}, Total: {input_tokens + output_tokens}")

            # Tracking pour analyse des coûts
            track_tokens(model, task_type.value, input_tokens, output_tokens)

            return generated_text

        except Exception as e:
            logger.error(f"[SAGEMAKER] Error calling {endpoint_name}: {e}")
            raise

    def _format_llama_prompt(self, messages: List[Dict[str, Any]]) -> str:
        """Format les messages pour Llama."""
        prompt_parts = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "system":
                prompt_parts.append(f"<<SYS>>\n{content}\n<</SYS>>")
            elif role == "user":
                prompt_parts.append(f"[INST] {content} [/INST]")
            elif role == "assistant":
                prompt_parts.append(content)

        return "\n".join(prompt_parts)

    def _format_qwen_prompt(self, messages: List[Dict[str, Any]]) -> str:
        """Format les messages pour Qwen."""
        prompt_parts = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "system":
                prompt_parts.append(f"<|im_start|>system\n{content}<|im_end|>")
            elif role == "user":
                prompt_parts.append(f"<|im_start|>user\n{content}<|im_end|>")
            elif role == "assistant":
                prompt_parts.append(f"<|im_start|>assistant\n{content}<|im_end|>")

        prompt_parts.append("<|im_start|>assistant\n")
        return "\n".join(prompt_parts)

    def _format_llava_prompt(self, messages: List[Dict[str, Any]]) -> str:
        """Format les messages pour LLaVA (vision)."""
        # LLaVA gère les images dans le contenu
        prompt_parts = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "user":
                prompt_parts.append(f"USER: {content}")
            elif role == "assistant":
                prompt_parts.append(f"ASSISTANT: {content}")

        prompt_parts.append("ASSISTANT:")
        return "\n".join(prompt_parts)

    def _format_generic_prompt(self, messages: List[Dict[str, Any]]) -> str:
        """Format générique pour autres modèles."""
        prompt_parts = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            prompt_parts.append(f"{role.upper()}: {content}")

        return "\n".join(prompt_parts)

    def _extract_sagemaker_response(self, result: Dict[str, Any], model: str) -> str:
        """Extrait la réponse du format SageMaker selon le modèle."""
        if "generated_text" in result:
            return result["generated_text"]
        elif "outputs" in result:
            return result["outputs"]
        elif isinstance(result, list) and len(result) > 0:
            return result[0].get("generated_text", "")
        else:
            logger.warning(f"Format de réponse SageMaker inattendu pour {model}: {result}")
            return str(result)

    def _call_vllm(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        task_type: TaskType,
        **kwargs
    ) -> str:
        """
        Appel vers vLLM (API OpenAI-compatible).

        vLLM expose une API compatible OpenAI, donc on utilise le client OpenAI
        avec une base_url différente pointant vers le serveur vLLM.
        """
        # Nettoyer le nom du modèle si préfixé par "vllm:"
        actual_model = model.replace("vllm:", "") if model.startswith("vllm:") else model

        # Filtrer les paramètres internes
        api_kwargs = {k: v for k, v in kwargs.items() if k not in ['model_preference']}

        # Retirer response_format si le modèle ne le supporte pas
        # (certains modèles vLLM ne supportent pas le JSON mode)
        if 'response_format' in api_kwargs:
            # vLLM supporte response_format pour certains modèles Qwen
            if not any(x in actual_model.lower() for x in ['qwen', 'mistral']):
                api_kwargs.pop('response_format', None)
                logger.debug(f"[vLLM] Removed response_format for model {actual_model}")

        try:
            response = self.vllm_client.chat.completions.create(
                model=actual_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **api_kwargs
            )

            # Log et tracking des métriques de tokens
            if response.usage:
                prompt_tokens = response.usage.prompt_tokens
                completion_tokens = response.usage.completion_tokens
                total_tokens = response.usage.total_tokens
                logger.info(f"[TOKENS:vLLM] {actual_model} - Input: {prompt_tokens}, Output: {completion_tokens}, Total: {total_tokens}")

                # Tracking pour analyse des coûts (vLLM = coût compute, pas API)
                track_tokens(f"vllm/{actual_model}", task_type.value, prompt_tokens, completion_tokens)

            return response.choices[0].message.content or ""

        except Exception as e:
            logger.error(f"[vLLM] Error calling {actual_model}: {e}")
            raise

    async def _call_vllm_async(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        task_type: TaskType,
        **kwargs
    ) -> str:
        """
        Appel async vers vLLM pour parallélisation.
        """
        # Nettoyer le nom du modèle
        actual_model = model.replace("vllm:", "") if model.startswith("vllm:") else model

        # Filtrer les paramètres internes
        api_kwargs = {k: v for k, v in kwargs.items() if k not in ['model_preference']}

        # Retirer response_format si non supporté
        if 'response_format' in api_kwargs:
            if not any(x in actual_model.lower() for x in ['qwen', 'mistral']):
                api_kwargs.pop('response_format', None)

        try:
            response = await self.async_vllm_client.chat.completions.create(
                model=actual_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **api_kwargs
            )

            # Log et tracking
            if response.usage:
                prompt_tokens = response.usage.prompt_tokens
                completion_tokens = response.usage.completion_tokens
                total_tokens = response.usage.total_tokens
                logger.info(f"[TOKENS:vLLM:ASYNC] {actual_model} - Input: {prompt_tokens}, Output: {completion_tokens}, Total: {total_tokens}")

                track_tokens(f"vllm/{actual_model}", task_type.value, prompt_tokens, completion_tokens)

            return response.choices[0].message.content or ""

        except Exception as e:
            logger.error(f"[vLLM:ASYNC] Error calling {actual_model}: {e}")
            raise

    # =========================================================================
    # Méthodes Ollama - Inférence locale (API native /api/chat)
    # =========================================================================
    #
    # IMPORTANT: On utilise l'API native Ollama (/api/chat) et NON l'API
    # OpenAI-compatible (/v1). Raison: l'API /v1 d'Ollama ne supporte pas
    # "think": false — le modèle Qwen3.5 produit du thinking caché dans un
    # champ "reasoning", laissant "content" vide. Seule l'API native permet
    # de désactiver le thinking proprement.

    def _call_ollama(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        task_type: TaskType,
        **kwargs
    ) -> str:
        """Appel vers Ollama via API native /api/chat (think: false)."""
        ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        }

        if not HTTPX_AVAILABLE:
            raise RuntimeError("httpx required for Ollama native API")

        start = time.time()
        with httpx.Client(timeout=120.0) as client:
            response = client.post(f"{ollama_url}/api/chat", json=payload)
            response.raise_for_status()

        result = response.json()
        content = result.get("message", {}).get("content", "")
        elapsed = time.time() - start

        # Métriques tokens (API native)
        prompt_tokens = result.get("prompt_eval_count", 0)
        completion_tokens = result.get("eval_count", 0)
        total_tokens = prompt_tokens + completion_tokens
        logger.info(
            f"[TOKENS:OLLAMA] {model} - Input: {prompt_tokens}, Output: {completion_tokens}, "
            f"Total: {total_tokens}, Time: {elapsed:.1f}s"
        )

        track_tokens(f"ollama/{model}", task_type.value, prompt_tokens, completion_tokens)

        return content

    async def _call_ollama_async(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        task_type: TaskType,
        **kwargs
    ) -> str:
        """Appel async vers Ollama via API native /api/chat (think: false)."""
        ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        }

        if not HTTPX_AVAILABLE:
            raise RuntimeError("httpx required for Ollama native API")

        start = time.time()
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(f"{ollama_url}/api/chat", json=payload)
            response.raise_for_status()

        result = response.json()
        content = result.get("message", {}).get("content", "")
        elapsed = time.time() - start

        # Métriques tokens (API native)
        prompt_tokens = result.get("prompt_eval_count", 0)
        completion_tokens = result.get("eval_count", 0)
        total_tokens = prompt_tokens + completion_tokens
        logger.info(
            f"[TOKENS:OLLAMA:ASYNC] {model} - Input: {prompt_tokens}, Output: {completion_tokens}, "
            f"Total: {total_tokens}, Time: {elapsed:.1f}s"
        )

        track_tokens(f"ollama/{model}", task_type.value, prompt_tokens, completion_tokens)

        return content

    # =========================================================================
    # Méthodes Burst Mode - Appels vers EC2 Spot vLLM
    # =========================================================================

    def _call_burst_vllm(
        self,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        task_type: TaskType,
        **kwargs
    ) -> str:
        """
        Appel vers vLLM en mode Burst (EC2 Spot).

        Utilise le client burst dédié et le modèle configuré pour le burst.

        Supporte les structured outputs via:
        - json_schema: Dict avec le JSON schema pour guided generation
        - guided_json: Alias pour json_schema (legacy vLLM)
        """
        if not self._burst_vllm_client:
            raise RuntimeError("Burst mode client not initialized")

        # Limite de contexte dynamique (16K Qwen2.5, 32K Qwen3)
        # vLLM max_model_len = TOTAL tokens (input + output)
        # On doit réserver max_tokens pour la completion + marge sécurité 20%
        VLLM_MAX_CONTEXT = self._vllm_max_context
        SAFETY_MARGIN = 0.20  # 20% de marge car estimation tokens imprécise
        max_input_tokens = int((VLLM_MAX_CONTEXT - max_tokens) * (1 - SAFETY_MARGIN))
        max_input_tokens = max(1000, min(max_input_tokens, VLLM_MAX_CONTEXT - 2000))

        # Tronquer les messages si trop longs
        messages = self._truncate_messages_for_context(messages, max_input_tokens)

        # Filtrer les paramètres internes
        api_kwargs = {k: v for k, v in kwargs.items() if k not in ['model_preference', 'json_schema', 'guided_json', 'enable_thinking']}

        # === THINKING MODE (Qwen3 uniquement) ===
        # Qwen3 a le thinking ON par défaut, Qwen2.5 n'a pas de thinking mode.
        # Le bloc ci-dessous ne s'active que si _is_qwen3 est True.
        if self._is_qwen3:
            enable_thinking = kwargs.get('enable_thinking', False)
            has_json_schema = bool(kwargs.get('json_schema') or kwargs.get('guided_json'))

            api_kwargs.setdefault('extra_body', {})
            if enable_thinking and not has_json_schema:
                api_kwargs['extra_body']['chat_template_kwargs'] = {"enable_thinking": True}
                if temperature < 0.6:
                    temperature = 0.6
                logger.info(
                    f"[BURST:vLLM] Thinking mode ENABLED for {task_type.value} "
                    f"(parser=qwen3, temp={temperature})"
                )
            else:
                api_kwargs['extra_body']['chat_template_kwargs'] = {"enable_thinking": False}
                messages = self._append_nothink_directive(messages)
                if enable_thinking and has_json_schema:
                    logger.warning(
                        f"[BURST:vLLM] Thinking mode SKIPPED for {task_type.value} "
                        f"— incompatible avec JSON schema"
                    )

        # === STRUCTURED OUTPUTS (Volet C) ===
        # Support pour vLLM JSON schema enforcement
        json_schema = kwargs.get('json_schema') or kwargs.get('guided_json')
        if json_schema and any(x in self._burst_model.lower() for x in ['qwen', 'mistral']):
            # Utiliser le nouveau format response_format avec json_schema
            api_kwargs['response_format'] = {
                "type": "json_schema",
                "json_schema": {
                    "name": task_type.value,
                    "strict": True,
                    "schema": json_schema
                }
            }
            logger.debug(f"[BURST:vLLM] Using structured output with JSON schema for {task_type.value}")
        elif 'response_format' in api_kwargs:
            # Retirer response_format si non supporté par le modèle
            if not any(x in self._burst_model.lower() for x in ['qwen', 'mistral']):
                api_kwargs.pop('response_format', None)
                logger.debug(f"[BURST:vLLM] Removed response_format for model {self._burst_model}")

        response = self._burst_vllm_client.chat.completions.create(
            model=self._burst_vllm_served_model,  # Nom du modèle servi par vLLM
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **api_kwargs
        )

        # Log et tracking des métriques de tokens
        if response.usage:
            prompt_tokens = response.usage.prompt_tokens
            completion_tokens = response.usage.completion_tokens
            total_tokens = response.usage.total_tokens
            logger.info(f"[TOKENS:BURST:vLLM] {self._burst_model} - Input: {prompt_tokens}, Output: {completion_tokens}, Total: {total_tokens}")

            # Tracking pour analyse des coûts (burst = coût EC2 Spot, pas API)
            track_tokens(f"burst/{self._burst_model}", task_type.value, prompt_tokens, completion_tokens)

        content = response.choices[0].message.content or ""

        # Strip <think> tags si présents (Qwen3 thinking mode uniquement)
        if self._is_qwen3 and '<think>' in content:
            import re as _re
            think_match = _re.search(r'<think>(.*?)</think>', content, _re.DOTALL)
            if think_match:
                reasoning_content = think_match.group(1)
                content = _re.sub(r'<think>.*?</think>', '', content, flags=_re.DOTALL).strip()
                logger.info(f"[BURST:vLLM:THINKING] reasoning length: {len(reasoning_content)} chars, stripped from content")
            elif '<think>' in content and '</think>' not in content:
                think_start = content.index('<think>')
                truncated_reasoning = content[think_start + 7:]
                content = content[:think_start].strip()
                logger.warning(
                    f"[BURST:vLLM:THINKING] TRUNCATED thinking detected "
                    f"({len(truncated_reasoning)} chars), stripped from content"
                )

        return content

    async def _call_burst_vllm_async(
        self,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        task_type: TaskType,
        **kwargs
    ) -> str:
        """
        Appel async vers vLLM en mode Burst (EC2 Spot).

        Supporte les structured outputs via:
        - json_schema: Dict avec le JSON schema pour guided generation
        - guided_json: Alias pour json_schema (legacy vLLM)
        """
        if not self._burst_async_vllm_client:
            raise RuntimeError("Burst mode async client not initialized")

        # Limite de contexte dynamique (16K Qwen2.5, 32K Qwen3)
        # vLLM max_model_len = TOTAL tokens (input + output)
        # On doit réserver max_tokens pour la completion + marge sécurité 20%
        VLLM_MAX_CONTEXT = self._vllm_max_context
        SAFETY_MARGIN = 0.20  # 20% de marge car estimation tokens imprécise
        max_input_tokens = int((VLLM_MAX_CONTEXT - max_tokens) * (1 - SAFETY_MARGIN))
        max_input_tokens = max(1000, min(max_input_tokens, VLLM_MAX_CONTEXT - 2000))

        # Tronquer les messages si trop longs
        messages = self._truncate_messages_for_context(messages, max_input_tokens)

        # Filtrer les paramètres internes
        api_kwargs = {k: v for k, v in kwargs.items() if k not in ['model_preference', 'json_schema', 'guided_json', 'enable_thinking']}

        # === THINKING MODE (Qwen3 uniquement) ===
        # Qwen3 a le thinking ON par défaut, Qwen2.5 n'a pas de thinking mode.
        if self._is_qwen3:
            enable_thinking = kwargs.get('enable_thinking', False)
            has_json_schema = bool(kwargs.get('json_schema') or kwargs.get('guided_json'))

            api_kwargs.setdefault('extra_body', {})
            if enable_thinking and not has_json_schema:
                api_kwargs['extra_body']['chat_template_kwargs'] = {"enable_thinking": True}
                if temperature < 0.6:
                    temperature = 0.6
                logger.info(
                    f"[BURST:vLLM:ASYNC] Thinking mode ENABLED for {task_type.value} "
                    f"(parser=qwen3, temp={temperature})"
                )
            else:
                api_kwargs['extra_body']['chat_template_kwargs'] = {"enable_thinking": False}
                messages = self._append_nothink_directive(messages)
                if enable_thinking and has_json_schema:
                    logger.warning(
                        f"[BURST:vLLM:ASYNC] Thinking mode SKIPPED for {task_type.value} "
                        f"— incompatible avec JSON schema"
                    )

        # === STRUCTURED OUTPUTS (Volet C) ===
        # Support pour vLLM JSON schema enforcement
        json_schema = kwargs.get('json_schema') or kwargs.get('guided_json')
        if json_schema and any(x in self._burst_model.lower() for x in ['qwen', 'mistral']):
            # Utiliser le nouveau format response_format avec json_schema
            api_kwargs['response_format'] = {
                "type": "json_schema",
                "json_schema": {
                    "name": task_type.value,
                    "strict": True,
                    "schema": json_schema
                }
            }
            logger.debug(f"[BURST:vLLM:ASYNC] Using structured output with JSON schema for {task_type.value}")
        elif 'response_format' in api_kwargs:
            # Retirer response_format si non supporté
            if not any(x in self._burst_model.lower() for x in ['qwen', 'mistral']):
                api_kwargs.pop('response_format', None)

        response = await self._burst_async_vllm_client.chat.completions.create(
            model=self._burst_vllm_served_model,  # Nom du modèle servi par vLLM
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **api_kwargs
        )

        # Log et tracking
        if response.usage:
            prompt_tokens = response.usage.prompt_tokens
            completion_tokens = response.usage.completion_tokens
            total_tokens = response.usage.total_tokens
            logger.info(f"[TOKENS:BURST:vLLM:ASYNC] {self._burst_model} - Input: {prompt_tokens}, Output: {completion_tokens}, Total: {total_tokens}")

            track_tokens(f"burst/{self._burst_model}", task_type.value, prompt_tokens, completion_tokens)

        content = response.choices[0].message.content or ""

        # Strip <think> tags si présents (Qwen3 thinking mode uniquement)
        if self._is_qwen3 and '<think>' in content:
            import re as _re
            think_match = _re.search(r'<think>(.*?)</think>', content, _re.DOTALL)
            if think_match:
                reasoning_content = think_match.group(1)
                content = _re.sub(r'<think>.*?</think>', '', content, flags=_re.DOTALL).strip()
                logger.info(f"[BURST:vLLM:ASYNC:THINKING] reasoning length: {len(reasoning_content)} chars, stripped from content")
            elif '<think>' in content and '</think>' not in content:
                think_start = content.index('<think>')
                truncated_reasoning = content[think_start + 7:]
                content = content[:think_start].strip()
                logger.warning(
                    f"[BURST:vLLM:ASYNC:THINKING] TRUNCATED thinking detected "
                    f"({len(truncated_reasoning)} chars), stripped from content"
                )

        return content

    @staticmethod
    def _append_nothink_directive(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Ajoute /nothink au dernier message user pour désactiver le thinking Qwen3.

        Contournement d'un bug vLLM batching : chat_template_kwargs est parfois
        ignoré sous charge concurrente, mais /nothink dans le message est traité
        de manière fiable par le template Qwen3.
        """
        messages = [m.copy() for m in messages]
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if not content.rstrip().endswith("/nothink"):
                    msg["content"] = content.rstrip() + " /nothink"
                break
        return messages

    def _estimate_tokens(self, text: str) -> int:
        """Estimation grossière des tokens (~ 4 chars = 1 token)."""
        return max(1, len(text) // 4)

    def _truncate_messages_for_context(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: int
    ) -> List[Dict[str, Any]]:
        """
        Tronque les messages pour respecter la limite de contexte.

        Stratégie:
        1. Préserver le system message (premier)
        2. Préserver le dernier user message
        3. Tronquer le contenu des messages intermédiaires si nécessaire

        Args:
            messages: Liste des messages
            max_tokens: Limite de tokens d'entrée

        Returns:
            Messages tronqués si nécessaire
        """
        if not messages:
            return messages

        # Estimer le total actuel
        total_tokens = sum(
            self._estimate_tokens(m.get("content", ""))
            for m in messages
        )

        if total_tokens <= max_tokens:
            return messages

        logger.warning(
            f"[BURST:TRUNCATE] Input too long ({total_tokens} tokens), "
            f"truncating to {max_tokens} tokens"
        )

        # Copie pour ne pas modifier l'original
        truncated = []

        # Garder le system message intact si présent
        system_msg = None
        other_msgs = []

        for msg in messages:
            if msg.get("role") == "system":
                system_msg = msg.copy()
            else:
                other_msgs.append(msg.copy())

        # Budget tokens disponible
        system_tokens = self._estimate_tokens(system_msg.get("content", "")) if system_msg else 0
        remaining_budget = max_tokens - system_tokens

        # Si le system message est déjà trop long, le tronquer
        if system_msg and system_tokens > max_tokens * 0.3:
            max_system_chars = int(max_tokens * 0.3 * 4)  # 30% max pour system
            content = system_msg.get("content", "")
            if len(content) > max_system_chars:
                system_msg["content"] = content[:max_system_chars] + "\n[...truncated...]"
                system_tokens = self._estimate_tokens(system_msg["content"])
                remaining_budget = max_tokens - system_tokens

        # Tronquer les autres messages (en gardant le dernier user message prioritaire)
        if other_msgs:
            # Dernier message = prioritaire
            last_msg = other_msgs[-1]
            last_tokens = self._estimate_tokens(last_msg.get("content", ""))

            # Si le dernier message est trop long, le tronquer
            if last_tokens > remaining_budget * 0.7:
                max_chars = int(remaining_budget * 0.7 * 4)
                content = last_msg.get("content", "")
                last_msg["content"] = content[:max_chars] + "\n[...truncated...]"
                last_tokens = self._estimate_tokens(last_msg["content"])

            # Distribuer le reste du budget aux messages précédents
            budget_for_others = remaining_budget - last_tokens

            processed_others = []
            for msg in other_msgs[:-1]:
                msg_tokens = self._estimate_tokens(msg.get("content", ""))
                if budget_for_others <= 0:
                    # Plus de budget, skip ce message
                    continue
                if msg_tokens <= budget_for_others:
                    processed_others.append(msg)
                    budget_for_others -= msg_tokens
                else:
                    # Tronquer partiellement
                    max_chars = int(budget_for_others * 4)
                    if max_chars > 100:  # Seulement si ça vaut le coup
                        content = msg.get("content", "")
                        msg["content"] = content[:max_chars] + "\n[...truncated...]"
                        processed_others.append(msg)
                    budget_for_others = 0

            other_msgs = processed_others + [last_msg]

        # Reconstruire la liste
        if system_msg:
            truncated.append(system_msg)
        truncated.extend(other_msgs)

        new_total = sum(self._estimate_tokens(m.get("content", "")) for m in truncated)
        logger.info(f"[BURST:TRUNCATE] Reduced from {total_tokens} to {new_total} tokens")

        return truncated


# Instance globale du routeur
_router_instance: Optional[LLMRouter] = None


def get_llm_router() -> LLMRouter:
    """Obtient l'instance singleton du routeur LLM."""
    global _router_instance
    if _router_instance is None:
        _router_instance = LLMRouter()
    return _router_instance


# Fonctions de convenance pour chaque type de tâche
def complete_vision_task(
    messages: List[Dict[str, Any]],
    temperature: float = 0.2,
    max_tokens: int = 4000
) -> str:
    """Effectue une tâche d'analyse visuelle avec limite étendue pour multi-concepts."""
    return get_llm_router().complete(TaskType.VISION, messages, temperature, max_tokens)


def complete_metadata_extraction(
    messages: List[Dict[str, Any]],
    temperature: float = 0.1,
    max_tokens: int = 2000
) -> str:
    """Effectue une extraction de métadonnées."""
    return get_llm_router().complete(TaskType.METADATA_EXTRACTION, messages, temperature, max_tokens)


def complete_long_summary(
    messages: List[Dict[str, Any]],
    temperature: float = 0.1,
    max_tokens: int = 8000
) -> str:
    """Effectue un résumé de texte long."""
    return get_llm_router().complete(TaskType.LONG_TEXT_SUMMARY, messages, temperature, max_tokens)


def complete_enrichment(
    messages: List[Dict[str, Any]],
    temperature: float = 0.3,
    max_tokens: int = 1000
) -> str:
    """Effectue un enrichissement de contenu court."""
    return get_llm_router().complete(TaskType.SHORT_ENRICHMENT, messages, temperature, max_tokens)


def complete_fast_classification(
    messages: List[Dict[str, Any]],
    temperature: float = 0.0,
    max_tokens: int = 100
) -> str:
    """Effectue une classification rapide."""
    return get_llm_router().complete(TaskType.FAST_CLASSIFICATION, messages, temperature, max_tokens)


def complete_canonicalization(
    messages: List[Dict[str, Any]],
    temperature: float = 0.0,
    max_tokens: int = 800  # Augmenté de 400 à 800 pour JSON complet avec reasoning + marge
) -> str:
    """
    Effectue une canonicalisation de nom.

    Fix 2025-10-20: Augmenter max_tokens à 800 et forcer response_format JSON
    pour éliminer les JSON truncation errors qui causent circuit breaker OPEN.
    """
    return get_llm_router().complete(
        TaskType.CANONICALIZATION,
        messages,
        temperature,
        max_tokens,
        response_format={"type": "json_object"}  # Force JSON mode OpenAI
    )


# ============================================================================
# STRUCTURED OUTPUTS - Fonctions pour vLLM JSON Schema (Volet C)
# ============================================================================

def complete_knowledge_extraction(
    messages: List[Dict[str, Any]],
    temperature: float = 0.2,
    max_tokens: int = 2000,
    json_schema: Optional[Dict[str, Any]] = None
) -> str:
    """
    Effectue une extraction de connaissances avec support JSON schema.

    Args:
        messages: Messages pour le LLM
        temperature: Température (défaut: 0.2)
        max_tokens: Tokens max (défaut: 2000)
        json_schema: Schema JSON pour structured output (optionnel)

    Returns:
        Réponse JSON du LLM
    """
    kwargs = {}
    if json_schema:
        kwargs['json_schema'] = json_schema
    else:
        kwargs['response_format'] = {"type": "json_object"}

    return get_llm_router().complete(
        TaskType.KNOWLEDGE_EXTRACTION,
        messages,
        temperature,
        max_tokens,
        **kwargs
    )


async def complete_knowledge_extraction_async(
    messages: List[Dict[str, Any]],
    temperature: float = 0.2,
    max_tokens: int = 2000,
    json_schema: Optional[Dict[str, Any]] = None
) -> str:
    """
    Version async de complete_knowledge_extraction.
    """
    kwargs = {}
    if json_schema:
        kwargs['json_schema'] = json_schema
    else:
        kwargs['response_format'] = {"type": "json_object"}

    return await get_llm_router().complete_async(
        TaskType.KNOWLEDGE_EXTRACTION,
        messages,
        temperature,
        max_tokens,
        **kwargs
    )


def complete_with_schema(
    task_type: TaskType,
    messages: List[Dict[str, Any]],
    json_schema: Dict[str, Any],
    temperature: float = 0.2,
    max_tokens: int = 2000
) -> str:
    """
    Effectue une completion avec JSON schema enforcement.

    Cette fonction utilise les structured outputs de vLLM pour garantir
    que la réponse est un JSON valide conforme au schema.

    Args:
        task_type: Type de tâche LLM
        messages: Messages pour le LLM
        json_schema: Schema JSON (format Pydantic model_json_schema())
        temperature: Température
        max_tokens: Tokens max

    Returns:
        Réponse JSON validée

    Example:
        from knowbase.stratified.pass1.llm_schemas import AssertionExtractionResponse

        schema = AssertionExtractionResponse.model_json_schema()
        result = complete_with_schema(
            TaskType.KNOWLEDGE_EXTRACTION,
            messages,
            json_schema=schema,
            max_tokens=2000
        )
    """
    return get_llm_router().complete(
        task_type,
        messages,
        temperature,
        max_tokens,
        json_schema=json_schema
    )


async def complete_with_schema_async(
    task_type: TaskType,
    messages: List[Dict[str, Any]],
    json_schema: Dict[str, Any],
    temperature: float = 0.2,
    max_tokens: int = 2000
) -> str:
    """
    Version async de complete_with_schema.
    """
    return await get_llm_router().complete_async(
        task_type,
        messages,
        temperature,
        max_tokens,
        json_schema=json_schema
    )