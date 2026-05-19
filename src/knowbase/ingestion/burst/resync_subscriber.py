"""Burst resync pub/sub subscriber — bascule du worker sur la nouvelle IP AWS.

CH-BURST.REL (19/05/2026) — Compagnon de aws_truth_service.py.

Quand le backend détecte un `ip_mismatch` (spot interruption + respawn AWS auto)
et appelle /api/burst/auto-resync, un événement Redis pub/sub est publié sur le
channel REDIS_RESYNC_CHANNEL avec la nouvelle URL vLLM.

Ce module fournit un subscriber qui :
  1. S'abonne au channel en thread daemon dès l'import (ou via start_subscriber())
  2. À chaque message reçu : re-active les burst providers avec la nouvelle URL
     via activate_burst_providers() — c'est ce qui pousse la nouvelle URL au
     LLM_Router singleton du process worker.
  3. Le prochain call LLM utilise donc la nouvelle IP, sans attendre la fin du
     timeout en cours (le timeout fait juste finir l'appel courant en erreur,
     le retry/next call bascule sur la nouvelle IP).

À lancer depuis worker.py au démarrage (après _restore_burst_state).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from typing import Optional

logger = logging.getLogger(__name__)


_subscriber_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()


def _handle_resync_event(payload: dict) -> None:
    """Re-active les burst providers avec la nouvelle URL."""
    try:
        new_vllm_url = payload.get("vllm_url")
        new_instance_id = payload.get("instance_id")
        reason = payload.get("reason", "unknown")

        if not new_vllm_url:
            logger.warning(
                f"[BURST:SUB] Resync event sans vllm_url (payload={payload})"
            )
            return

        logger.info(
            f"[BURST:SUB] Resync event reçu : new_url={new_vllm_url}, "
            f"instance_id={new_instance_id}, reason={reason}"
        )

        # Reconfigurer les providers avec la nouvelle URL.
        # activate_burst_providers re-crée les clients OpenAI dans LLM_Router avec
        # la nouvelle base_url, donc tous les calls LLM suivants pointent dessus.
        from knowbase.ingestion.burst.provider_switch import activate_burst_providers

        # Récupérer l'URL embeddings depuis Redis state (mise à jour par
        # auto_resync_to_aws avant la publication de l'event)
        try:
            from knowbase.ingestion.burst.provider_switch import get_burst_state_from_redis

            state = get_burst_state_from_redis()
            embeddings_url = state.get("embeddings_url") if state else None
            vllm_model = state.get("vllm_model") if state else None
        except Exception as e:
            logger.debug(f"[BURST:SUB] Could not read Redis state: {e}")
            embeddings_url = None
            vllm_model = None

        result = activate_burst_providers(
            vllm_url=new_vllm_url,
            embeddings_url=embeddings_url,
            vllm_model=vllm_model,
        )
        logger.info(
            f"[BURST:SUB] Providers re-configurés : llm_router={result.get('llm_router')}, "
            f"embeddings={result.get('embedding_manager')}"
        )
    except Exception as e:
        logger.exception(f"[BURST:SUB] Failed to handle resync event: {e}")


def _subscriber_loop() -> None:
    """Boucle principale du subscriber (tourne dans un thread daemon)."""
    from knowbase.ingestion.burst.aws_truth_service import REDIS_RESYNC_CHANNEL

    backoff_seconds = 5
    while not _stop_event.is_set():
        try:
            import redis as _redis

            redis_host = os.getenv("REDIS_HOST", "redis")
            redis_port = int(os.getenv("REDIS_PORT", "6379"))
            redis_password = os.getenv("REDIS_PASSWORD") or None
            rc = _redis.Redis(
                host=redis_host,
                port=redis_port,
                password=redis_password,
                decode_responses=True,
            )
            pubsub = rc.pubsub()
            pubsub.subscribe(REDIS_RESYNC_CHANNEL)
            logger.info(
                f"[BURST:SUB] Subscribed to '{REDIS_RESYNC_CHANNEL}' "
                f"(host={redis_host}:{redis_port})"
            )
            backoff_seconds = 5  # reset on successful subscribe

            for message in pubsub.listen():
                if _stop_event.is_set():
                    break
                if message.get("type") != "message":
                    continue
                try:
                    payload = json.loads(message.get("data", "{}"))
                    _handle_resync_event(payload)
                except json.JSONDecodeError as e:
                    logger.warning(
                        f"[BURST:SUB] Malformed pub/sub message: {e} "
                        f"(data={message.get('data')!r})"
                    )

            try:
                pubsub.close()
                rc.close()
            except Exception:
                pass
        except Exception as e:
            logger.warning(
                f"[BURST:SUB] Subscriber crashed: {e} — restart in {backoff_seconds}s"
            )
            if _stop_event.wait(backoff_seconds):
                break
            backoff_seconds = min(backoff_seconds * 2, 60)  # exponential backoff


def start_subscriber() -> None:
    """Lance le subscriber en thread daemon. Idempotent : safe à appeler 2x.

    À appeler depuis worker.py au démarrage. Non-bloquant.
    """
    global _subscriber_thread

    if _subscriber_thread is not None and _subscriber_thread.is_alive():
        logger.debug("[BURST:SUB] Subscriber already running, skipping start")
        return

    _stop_event.clear()
    _subscriber_thread = threading.Thread(
        target=_subscriber_loop,
        name="burst-resync-subscriber",
        daemon=True,
    )
    _subscriber_thread.start()
    logger.info("[BURST:SUB] Resync subscriber thread started (daemon)")


def stop_subscriber() -> None:
    """Arrête le subscriber proprement. À appeler au shutdown du worker si besoin."""
    _stop_event.set()
    logger.info("[BURST:SUB] Stop event set — subscriber will exit on next iteration")
