"""
Système de routage automatique pour optimiser l'usage des modèles LLM
selon le type de tâche (vision, résumé long, métadonnées, enrichissement, etc.)
Configuration flexible via config/llm_models.yaml
"""
from __future__ import annotations

import json
import logging
import os
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml

from knowbase.config.settings import get_settings
from knowbase.common.clients import get_openai_client, get_async_openai_client, get_anthropic_client, is_anthropic_available
from knowbase.common.clients.gemini_client import get_gemini_client, is_gemini_available
from knowbase.common.cache import get_cache_manager
from knowbase.common.token_tracker import track_tokens

# Import conditionnel pour SageMaker
try:
    import boto3
    from botocore.exceptions import ClientError, NoCredentialsError
    SAGEMAKER_AVAILABLE = True
except ImportError:
    SAGEMAKER_AVAILABLE = False

logger = logging.getLogger(__name__)


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
    """Routeur intelligent pour les appels LLM selon le type de tâche."""

    def __init__(self, config_path: Optional[Path] = None):
        self.settings = get_settings()
        self._openai_client = None
        self._async_openai_client = None
        self._anthropic_client = None
        self._gemini_client = None
        self._sagemaker_client = None

        # Configuration dynamique
        self._config = self._load_config(config_path)
        self._available_providers = self._detect_available_providers()

        # Cache manager (optionnel par provider)
        cache_config = self._config.get("cache_config", {})
        self._cache_manager = get_cache_manager(cache_config)

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

        # Test Gemini (Google)
        try:
            providers["google"] = is_gemini_available()
            providers["gemini"] = providers["google"]  # Alias
            if providers["google"]:
                logger.debug("✓ Google Gemini provider disponible")
            else:
                logger.debug("✗ Google Gemini provider indisponible")
        except Exception as e:
            providers["google"] = False
            providers["gemini"] = False
            logger.debug(f"✗ Google Gemini provider indisponible: {e}")

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

        return providers

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
    def gemini_client(self):
        """Client Gemini paresseux."""
        if self._gemini_client is None:
            self._gemini_client = get_gemini_client()
        return self._gemini_client

    @property
    def sagemaker_client(self):
        """Client SageMaker paresseux."""
        if self._sagemaker_client is None and SAGEMAKER_AVAILABLE:
            self._sagemaker_client = boto3.client('sagemaker-runtime')
        return self._sagemaker_client

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
        elif model.startswith("gemini-"):
            return "google"
        elif model in ["llama3.1:70b", "qwen2.5:32b", "qwen2.5:7b", "llava:34b", "phi3:3.8b"]:
            return "sagemaker"
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

        logger.debug(f"[LLM_ROUTER] Task: {task_type.value}, Model: {model}, Provider: {provider}, Temp: {temperature}, Tokens: {max_tokens}")

        try:
            if provider == "openai":
                return self._call_openai(model, messages, temperature, max_tokens, task_type, **kwargs)
            elif provider == "anthropic":
                return self._call_anthropic(model, messages, temperature, max_tokens, task_type, **kwargs)
            elif provider in ["google", "gemini"]:
                return self._call_gemini(model, messages, temperature, max_tokens, task_type, **kwargs)
            elif provider == "sagemaker":
                return self._call_sagemaker(model, messages, temperature, max_tokens, task_type, **kwargs)
            else:
                raise ValueError(f"Provider {provider} non supporté")

        except Exception as e:
            logger.error(f"[LLM_ROUTER] Error with {model} ({provider}): {e}")
            # Fallback d'urgence vers le modèle par défaut
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

        logger.debug(f"[LLM_ROUTER:ASYNC] Task: {task_type.value}, Model: {model}, Provider: {provider}, Temp: {temperature}, Tokens: {max_tokens}")

        try:
            if provider == "openai":
                return await self._call_openai_async(model, messages, temperature, max_tokens, task_type, **kwargs)
            elif provider == "anthropic":
                # TODO: Implémenter version async pour Anthropic si nécessaire
                logger.warning("[LLM_ROUTER:ASYNC] Anthropic async not implemented, falling back to sync")
                return self._call_anthropic(model, messages, temperature, max_tokens, task_type, **kwargs)
            elif provider in ["google", "gemini"]:
                return await self._call_gemini_async(model, messages, temperature, max_tokens, task_type, **kwargs)
            elif provider == "sagemaker":
                # TODO: Implémenter version async pour SageMaker si nécessaire
                logger.warning("[LLM_ROUTER:ASYNC] SageMaker async not implemented, falling back to sync")
                return self._call_sagemaker(model, messages, temperature, max_tokens, task_type, **kwargs)
            else:
                raise ValueError(f"Provider {provider} non supporté")

        except Exception as e:
            logger.error(f"[LLM_ROUTER:ASYNC] Error with {model} ({provider}): {e}")
            # Fallback d'urgence vers le modèle par défaut
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

    def _call_gemini(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        task_type: TaskType,
        **kwargs
    ) -> str:
        """
        Appel vers Google Gemini avec support cache optionnel.

        Args:
            model: Nom du modèle Gemini
            messages: Messages au format OpenAI
            temperature: Température
            max_tokens: Max tokens output
            task_type: Type de tâche
            **kwargs: Arguments additionnels (cache_key, cache_content, etc.)

        Returns:
            Contenu de la réponse
        """
        # Convertir messages OpenAI → Gemini format
        system_instruction = None
        contents = []

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")

            if role == "system":
                system_instruction = content
            elif role == "user":
                # Gérer contenu multimodal (texte + images)
                if isinstance(content, list):
                    # Format multimodal vision
                    parts = []
                    for item in content:
                        if item.get("type") == "text":
                            parts.append(item.get("text"))
                        elif item.get("type") == "image_url":
                            # Gemini attend base64 directement
                            image_url = item.get("image_url", {}).get("url", "")
                            if image_url.startswith("data:image"):
                                # Extraire base64
                                import base64
                                image_data = image_url.split(",")[1]
                                parts.append({"mime_type": "image/png", "data": base64.b64decode(image_data)})
                    contents.append({"role": "user", "parts": parts})
                else:
                    # Format texte simple
                    contents.append({"role": "user", "parts": [content]})
            elif role == "assistant":
                contents.append({"role": "model", "parts": [content]})

        # Vérifier si cache activé et disponible
        cache_key = kwargs.get("cache_key")
        cache_content_data = kwargs.get("cache_content")

        cache_id = None
        if self._cache_manager.is_cache_enabled("google") and cache_content_data:
            # Tenter de cacher le contenu partagé
            cache_payload = {
                "model": f"models/{model}",
                "system_instruction": system_instruction,
                "contents": cache_content_data.get("contents", [])
            }

            ttl_hours = self._config.get("cache_config", {}).get("gemini", {}).get("default_ttl_hours", 1)
            cache_id = self._cache_manager.cache_for_provider(
                "google",
                cache_key,
                cache_payload,
                ttl_hours
            )

        # Obtenir modèle Gemini (avec ou sans cache)
        from knowbase.common.clients.gemini_client import get_gemini_model
        gemini_model = get_gemini_model(model, cache_id)

        # Configuration génération
        generation_config = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }

        # Appel Gemini
        response = gemini_model.generate_content(
            contents,
            generation_config=generation_config
        )

        # Log et tracking tokens
        if hasattr(response, "usage_metadata"):
            usage = response.usage_metadata
            prompt_tokens = usage.prompt_token_count
            completion_tokens = usage.candidates_token_count
            total_tokens = usage.total_token_count

            # Ajouter info si cache utilisé
            cached_tokens = getattr(usage, "cached_content_token_count", 0)
            cache_info = f" (cached: {cached_tokens})" if cached_tokens > 0 else ""

            logger.info(
                f"[TOKENS] {model} - Input: {prompt_tokens}, Output: {completion_tokens}, "
                f"Total: {total_tokens}{cache_info}"
            )

            # Tracking pour analyse des coûts
            track_tokens(model, task_type.value, prompt_tokens, completion_tokens)

        return response.text if response.text else ""

    async def _call_gemini_async(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        temperature: float,
        max_tokens: int,
        task_type: TaskType,
        **kwargs
    ) -> str:
        """
        Appel async vers Gemini.

        Note: Gemini SDK n'a pas de version async native, utilise sync dans thread pool.
        """
        # TODO: Implémenter vraie version async si Gemini SDK le supporte
        logger.debug("[LLM_ROUTER:ASYNC] Gemini async calling sync version")
        return self._call_gemini(model, messages, temperature, max_tokens, task_type, **kwargs)

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

    def _estimate_tokens(self, text: str) -> int:
        """Estimation grossière des tokens (~ 4 chars = 1 token)."""
        return max(1, len(text) // 4)


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