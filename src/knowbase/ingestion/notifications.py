"""
Module notifications conflits critiques.

Envoie webhooks (Slack, Teams, email) pour alerter équipe gouvernance
des conflits facts détectés post-ingestion.
"""

from __future__ import annotations

import os
from typing import List, Dict, Any, Optional

import httpx

from knowbase.common.logging import setup_logging
from knowbase.config.settings import get_settings

settings = get_settings()
logger = setup_logging(settings.logs_dir, "notifications.log")


async def notify_critical_conflicts(
    conflicts: List[Dict[str, Any]],
    webhook_url: Optional[str] = None,
    threshold_pct: float = 0.05,
    max_conflicts_displayed: int = 5,
) -> bool:
    """
    Notifie conflits critiques via webhook (Slack, Teams, etc.).

    Args:
        conflicts: Liste conflits détectés (format dict)
        webhook_url: URL webhook (défaut: CONFLICT_WEBHOOK_URL env)
        threshold_pct: Seuil notification (défaut: 5%)
        max_conflicts_displayed: Max conflits affichés message (défaut: 5)

    Returns:
        bool: True si notification envoyée avec succès
    """

    # Récupérer webhook URL depuis env si non fourni
    if webhook_url is None:
        webhook_url = os.getenv("CONFLICT_WEBHOOK_URL")

    if not webhook_url:
        logger.debug("✅ Webhook URL non configurée, skip notification")
        return False

    # Filtrer conflits critiques
    critical = [
        c for c in conflicts
        if c.get("value_diff_pct", 0) > threshold_pct
    ]

    if not critical:
        logger.debug("✅ Aucun conflit critique, skip notification")
        return False

    # Format message Slack
    message = _format_slack_message(
        critical_conflicts=critical,
        threshold_pct=threshold_pct,
        max_displayed=max_conflicts_displayed,
    )

    # Envoi webhook avec retry
    return await _send_webhook_with_retry(
        webhook_url=webhook_url,
        message=message,
        max_retries=3,
    )


def _format_slack_message(
    critical_conflicts: List[Dict[str, Any]],
    threshold_pct: float,
    max_displayed: int = 5,
) -> Dict[str, Any]:
    """
    Formate message Slack/Teams pour conflits critiques.

    Args:
        critical_conflicts: Conflits critiques (> seuil)
        threshold_pct: Seuil affiché dans message
        max_displayed: Max conflits affichés

    Returns:
        Dict: Message Slack format blocks
    """

    total = len(critical_conflicts)
    displayed = critical_conflicts[:max_displayed]

    message = {
        "text": f"🚨 {total} conflit{'s' if total > 1 else ''} critique{'s' if total > 1 else ''} détecté{'s' if total > 1 else ''}",
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🚨 {total} Conflit{'s' if total > 1 else ''} Critique{'s' if total > 1 else ''} Facts",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*{total} conflit{'s' if total > 1 else ''} détecté{'s' if total > 1 else ''}* "
                        f"avec différence de valeur > *{threshold_pct * 100}%*\n\n"
                        f"_Action requise: Vérifier et approuver/rejeter facts proposés_"
                    )
                }
            },
            {"type": "divider"}
        ]
    }

    # Ajouter conflits
    for i, conflict in enumerate(displayed, 1):
        proposed = conflict.get("fact_proposed", {})
        approved = conflict.get("fact_approved", {})
        diff_pct = conflict.get("value_diff_pct", 0) * 100

        conflict_type = conflict.get("conflict_type", "UNKNOWN")
        emoji_type = {
            "CONTRADICTS": "⚠️",
            "OVERRIDES": "🔄",
            "OUTDATED": "⏰",
            "DUPLICATE": "📋"
        }.get(conflict_type, "❓")

        message["blocks"].append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"{emoji_type} *Conflit {i}/{total}* - `{conflict_type}`\n"
                    f"*Subject*: {proposed.get('subject', 'N/A')}\n"
                    f"*Propriété*: `{proposed.get('predicate', 'N/A')}`\n\n"
                    f"• Proposé: *{proposed.get('value', 'N/A')}{proposed.get('unit', '')}*\n"
                    f"• Approuvé: *{approved.get('value', 'N/A')}{approved.get('unit', '')}*\n"
                    f"• Différence: *{diff_pct:.1f}%*"
                )
            }
        })

    # Ajouter notice si plus de conflits
    if total > max_displayed:
        message["blocks"].append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"_... et {total - max_displayed} autre{'s' if total - max_displayed > 1 else ''} conflit{'s' if total - max_displayed > 1 else ''}_"
                }
            ]
        })

    # Ajouter bouton action (si UI admin disponible)
    admin_url = os.getenv("ADMIN_FACTS_URL", "http://localhost:3000/admin/facts")
    message["blocks"].extend([
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "🔍 Voir dans Admin UI",
                        "emoji": True
                    },
                    "url": admin_url,
                    "style": "primary"
                }
            ]
        }
    ])

    return message


async def _send_webhook_with_retry(
    webhook_url: str,
    message: Dict[str, Any],
    max_retries: int = 3,
    timeout: float = 10.0,
) -> bool:
    """
    Envoie webhook avec retry automatique.

    Args:
        webhook_url: URL webhook destination
        message: Payload JSON message
        max_retries: Nombre tentatives max
        timeout: Timeout requête (secondes)

    Returns:
        bool: True si envoi réussi
    """

    async with httpx.AsyncClient() as client:
        for attempt in range(1, max_retries + 1):
            try:
                logger.debug(
                    f"📤 Envoi webhook (tentative {attempt}/{max_retries})..."
                )

                response = await client.post(
                    webhook_url,
                    json=message,
                    timeout=timeout,
                )

                if response.status_code in [200, 201, 202, 204]:
                    logger.info(
                        f"✅ Webhook notification envoyée "
                        f"(status {response.status_code})"
                    )
                    return True

                logger.warning(
                    f"⚠️ Webhook réponse inattendue: {response.status_code} - "
                    f"{response.text[:200]}"
                )

            except httpx.TimeoutException:
                logger.warning(
                    f"⏱️ Webhook timeout (tentative {attempt}/{max_retries})"
                )
            except httpx.RequestError as e:
                logger.warning(
                    f"⚠️ Webhook erreur réseau (tentative {attempt}/{max_retries}): {e}"
                )
            except Exception as e:
                logger.error(
                    f"❌ Webhook erreur inattendue (tentative {attempt}/{max_retries}): {e}"
                )

            # Attendre avant retry (exponential backoff)
            if attempt < max_retries:
                import asyncio
                wait_time = 2 ** attempt  # 2s, 4s, 8s
                logger.debug(f"⏳ Retry dans {wait_time}s...")
                await asyncio.sleep(wait_time)

    logger.error(
        f"❌ Webhook notification échouée après {max_retries} tentatives"
    )
    return False


async def notify_conflicts_email(
    conflicts: List[Dict[str, Any]],
    recipients: List[str],
    smtp_config: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Notifie conflits par email (optionnel).

    Args:
        conflicts: Conflits critiques
        recipients: Liste emails destinataires
        smtp_config: Config SMTP (host, port, user, password)

    Returns:
        bool: True si email envoyé
    """

    # TODO: Implémenter envoi email si requis
    logger.debug("📧 Notification email non implémentée (utiliser webhook)")
    return False


__all__ = [
    "notify_critical_conflicts",
    "notify_conflicts_email",
]
