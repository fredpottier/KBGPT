"""
DualLLMLogger - Middleware pour comparer les réponses OpenAI et vLLM en parallèle.

Ce middleware permet de tracer les réponses des deux providers pour une même requête,
facilitant le benchmarking de qualité avant migration vers vLLM en mode Burst.

Usage:
    from knowbase.common.dual_llm_logger import DualLLMLogger

    # Activer le dual-logging
    dual_logger = DualLLMLogger.get_instance()
    dual_logger.enable(vllm_url="http://ec2-xxx:8000", output_file="dual_log.jsonl")

    # Les appels LLMRouter seront automatiquement interceptés
    # Les réponses des deux providers sont loguées, OpenAI est retournée

    # Désactiver
    dual_logger.disable()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI, OpenAI

from knowbase.common.llm_router import LLMRouter, TaskType

logger = logging.getLogger(__name__)


class DualLLMLogger:
    """
    Middleware pour tracer les réponses OpenAI et vLLM en parallèle.

    Singleton pour permettre un contrôle global du dual-logging.
    """

    _instance: Optional[DualLLMLogger] = None

    def __init__(self):
        self._enabled = False
        self._vllm_url: Optional[str] = None
        self._vllm_model: str = "/models/Qwen--Qwen3-14B-AWQ"
        self._output_file: Optional[Path] = None
        self._vllm_client: Optional[OpenAI] = None
        self._async_vllm_client: Optional[AsyncOpenAI] = None
        self._stats = {
            "total_calls": 0,
            "openai_success": 0,
            "vllm_success": 0,
            "openai_errors": 0,
            "vllm_errors": 0,
            "openai_total_time": 0.0,
            "vllm_total_time": 0.0
        }

    @classmethod
    def get_instance(cls) -> DualLLMLogger:
        """Retourne l'instance singleton."""
        if cls._instance is None:
            cls._instance = DualLLMLogger()
        return cls._instance

    def enable(
        self,
        vllm_url: str,
        output_file: Optional[str] = None,
        vllm_model: str = "/models/Qwen--Qwen3-14B-AWQ"
    ):
        """
        Active le dual-logging.

        Args:
            vllm_url: URL du serveur vLLM (ex: http://ec2-xxx:8000)
            output_file: Fichier de sortie JSONL (défaut: data/dual_llm_log_{timestamp}.jsonl)
            vllm_model: Modèle vLLM à utiliser
        """
        self._enabled = True
        self._vllm_url = vllm_url.rstrip("/")
        self._vllm_model = vllm_model

        # Créer clients vLLM
        self._vllm_client = OpenAI(
            api_key="EMPTY",
            base_url=f"{self._vllm_url}/v1"
        )
        self._async_vllm_client = AsyncOpenAI(
            api_key="EMPTY",
            base_url=f"{self._vllm_url}/v1"
        )

        # Fichier de sortie
        if output_file is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            from knowbase.config.paths import DATA_DIR
            output_file = DATA_DIR / f"dual_llm_log_{timestamp}.jsonl"

        self._output_file = Path(output_file)
        self._output_file.parent.mkdir(parents=True, exist_ok=True)

        # Reset stats
        self._stats = {
            "total_calls": 0,
            "openai_success": 0,
            "vllm_success": 0,
            "openai_errors": 0,
            "vllm_errors": 0,
            "openai_total_time": 0.0,
            "vllm_total_time": 0.0
        }

        logger.info(f"[DUAL_LOG] ✅ Enabled → vLLM: {vllm_url}, Output: {self._output_file}")

    def disable(self):
        """Désactive le dual-logging et affiche les statistiques."""
        if not self._enabled:
            return

        self._enabled = False
        self._vllm_client = None
        self._async_vllm_client = None

        # Afficher statistiques
        stats = self.get_stats()
        logger.info(f"[DUAL_LOG] ⏹️ Disabled - Stats: {json.dumps(stats, indent=2)}")

        # Écrire résumé dans le fichier
        if self._output_file and self._output_file.exists():
            with open(self._output_file, "a", encoding="utf-8") as f:
                f.write(json.dumps({"type": "summary", "stats": stats}) + "\n")

    def is_enabled(self) -> bool:
        """Vérifie si le dual-logging est actif."""
        return self._enabled and self._vllm_client is not None

    def get_stats(self) -> Dict[str, Any]:
        """Retourne les statistiques du dual-logging."""
        total = self._stats["total_calls"]
        openai_avg = self._stats["openai_total_time"] / max(1, self._stats["openai_success"])
        vllm_avg = self._stats["vllm_total_time"] / max(1, self._stats["vllm_success"])

        return {
            "total_calls": total,
            "openai": {
                "success": self._stats["openai_success"],
                "errors": self._stats["openai_errors"],
                "avg_time_s": round(openai_avg, 2)
            },
            "vllm": {
                "success": self._stats["vllm_success"],
                "errors": self._stats["vllm_errors"],
                "avg_time_s": round(vllm_avg, 2)
            },
            "output_file": str(self._output_file) if self._output_file else None
        }

    def _log_comparison(
        self,
        task_type: TaskType,
        messages: List[Dict[str, Any]],
        openai_result: Dict[str, Any],
        vllm_result: Dict[str, Any]
    ):
        """Écrit une comparaison dans le fichier de log."""
        if not self._output_file:
            return

        entry = {
            "timestamp": datetime.now().isoformat(),
            "task_type": task_type.value,
            "prompt_preview": self._truncate_messages(messages),
            "openai": openai_result,
            "vllm": vllm_result
        }

        with open(self._output_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _truncate_messages(self, messages: List[Dict[str, Any]], max_len: int = 500) -> str:
        """Tronque les messages pour le log."""
        text = str(messages)
        if len(text) > max_len:
            return text[:max_len] + "..."
        return text

    async def dual_call_async(
        self,
        llm_router: LLMRouter,
        task_type: TaskType,
        messages: List[Dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 2048,
        **kwargs
    ) -> str:
        """
        Effectue un appel dual en parallèle: OpenAI + vLLM.

        Retourne la réponse OpenAI (production), log les deux réponses.

        Args:
            llm_router: Instance LLMRouter pour OpenAI
            task_type: Type de tâche
            messages: Messages au format standard
            temperature: Température LLM
            max_tokens: Limite tokens

        Returns:
            Réponse OpenAI (comportement production préservé)
        """
        if not self.is_enabled():
            # Fallback sur appel normal si pas activé
            return await llm_router.acomplete(task_type, messages, temperature, max_tokens, **kwargs)

        self._stats["total_calls"] += 1

        # Préparer les tâches parallèles
        openai_result = {"success": False, "response": None, "error": None, "time_s": 0}
        vllm_result = {"success": False, "response": None, "error": None, "time_s": 0}

        async def call_openai():
            start = time.time()
            try:
                response = await llm_router._call_openai_async(
                    llm_router._get_model_for_task(task_type),
                    messages,
                    temperature,
                    max_tokens,
                    task_type,
                    **kwargs
                )
                openai_result["success"] = True
                openai_result["response"] = response
                openai_result["time_s"] = round(time.time() - start, 2)
                self._stats["openai_success"] += 1
                self._stats["openai_total_time"] += openai_result["time_s"]
            except Exception as e:
                openai_result["error"] = str(e)
                openai_result["time_s"] = round(time.time() - start, 2)
                self._stats["openai_errors"] += 1
                logger.error(f"[DUAL_LOG] OpenAI error: {e}")

        async def call_vllm():
            start = time.time()
            try:
                response = await self._async_vllm_client.chat.completions.create(
                    model=self._vllm_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                vllm_result["success"] = True
                vllm_result["response"] = response.choices[0].message.content or ""
                vllm_result["time_s"] = round(time.time() - start, 2)
                self._stats["vllm_success"] += 1
                self._stats["vllm_total_time"] += vllm_result["time_s"]
            except Exception as e:
                vllm_result["error"] = str(e)
                vllm_result["time_s"] = round(time.time() - start, 2)
                self._stats["vllm_errors"] += 1
                logger.error(f"[DUAL_LOG] vLLM error: {e}")

        # Exécuter en parallèle
        await asyncio.gather(call_openai(), call_vllm())

        # Logger la comparaison
        self._log_comparison(task_type, messages, openai_result, vllm_result)

        # Log résumé
        logger.info(
            f"[DUAL_LOG] #{self._stats['total_calls']} {task_type.value} - "
            f"OpenAI: {openai_result['time_s']}s, vLLM: {vllm_result['time_s']}s"
        )

        # Retourner OpenAI (comportement production)
        if openai_result["success"]:
            return openai_result["response"]
        elif vllm_result["success"]:
            logger.warning("[DUAL_LOG] OpenAI failed, using vLLM response")
            return vllm_result["response"]
        else:
            raise RuntimeError(f"Both providers failed: OpenAI={openai_result['error']}, vLLM={vllm_result['error']}")

    def dual_call(
        self,
        llm_router: LLMRouter,
        task_type: TaskType,
        messages: List[Dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 2048,
        **kwargs
    ) -> str:
        """
        Version synchrone de dual_call.

        Note: Moins efficace que la version async car les appels sont séquentiels.
        """
        if not self.is_enabled():
            return llm_router.complete(task_type, messages, temperature, max_tokens, **kwargs)

        self._stats["total_calls"] += 1

        openai_result = {"success": False, "response": None, "error": None, "time_s": 0}
        vllm_result = {"success": False, "response": None, "error": None, "time_s": 0}

        # Appel OpenAI
        start = time.time()
        try:
            model = llm_router._get_model_for_task(task_type)
            response = llm_router._call_openai(model, messages, temperature, max_tokens, task_type, **kwargs)
            openai_result["success"] = True
            openai_result["response"] = response
            openai_result["time_s"] = round(time.time() - start, 2)
            self._stats["openai_success"] += 1
            self._stats["openai_total_time"] += openai_result["time_s"]
        except Exception as e:
            openai_result["error"] = str(e)
            openai_result["time_s"] = round(time.time() - start, 2)
            self._stats["openai_errors"] += 1

        # Appel vLLM
        start = time.time()
        try:
            response = self._vllm_client.chat.completions.create(
                model=self._vllm_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens
            )
            vllm_result["success"] = True
            vllm_result["response"] = response.choices[0].message.content or ""
            vllm_result["time_s"] = round(time.time() - start, 2)
            self._stats["vllm_success"] += 1
            self._stats["vllm_total_time"] += vllm_result["time_s"]
        except Exception as e:
            vllm_result["error"] = str(e)
            vllm_result["time_s"] = round(time.time() - start, 2)
            self._stats["vllm_errors"] += 1

        # Logger
        self._log_comparison(task_type, messages, openai_result, vllm_result)

        logger.info(
            f"[DUAL_LOG] #{self._stats['total_calls']} {task_type.value} - "
            f"OpenAI: {openai_result['time_s']}s, vLLM: {vllm_result['time_s']}s"
        )

        if openai_result["success"]:
            return openai_result["response"]
        elif vllm_result["success"]:
            logger.warning("[DUAL_LOG] OpenAI failed, using vLLM response")
            return vllm_result["response"]
        else:
            raise RuntimeError(f"Both providers failed")


# Fonction helper pour activer rapidement le dual-logging
def enable_dual_logging(vllm_url: str, output_file: Optional[str] = None) -> DualLLMLogger:
    """
    Active le dual-logging de manière simple.

    Example:
        enable_dual_logging("http://ec2-xxx:8000")
    """
    dual_logger = DualLLMLogger.get_instance()
    dual_logger.enable(vllm_url, output_file)
    return dual_logger


def disable_dual_logging():
    """Désactive le dual-logging."""
    DualLLMLogger.get_instance().disable()
