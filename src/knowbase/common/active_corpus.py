"""Corpus actif global (tenant_id) — source de vérité unique en Redis.

Permet de basculer TOUT le système (chat + ingestion) d'un corpus à l'autre via
un seul bouton admin, sans refonte : le `tenant_id` est déjà câblé de bout en bout
(Neo4j = propriété + contrainte composite ; Qdrant = filtre payload `tenant_id` sur
une collection partagée). Voir `doc/ongoing/CH_CORPUS_SWITCH.md`.

Modèle : **UN** corpus actif pour toute l'instance (mono-opérateur / démos). Stocké
en Redis (clé `osmosis:active_corpus`). Défaut `"default"`. Fail-soft en lecture
(toute erreur → `"default"`), strict en écriture (Redis requis).

Note switch-safe : à l'ingestion, le corpus actif est **estampillé sur le job au
moment de l'enqueue** (folder_watcher) → les jobs en vol gardent leur tenant même
si l'on bascule le corpus actif pendant un import.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

ACTIVE_CORPUS_KEY = "osmosis:active_corpus"
DEFAULT_CORPUS = "default"


def _get_redis_client():
    """Import paresseux (évite de tirer `redis` au chargement du module / en test)."""
    from knowbase.common.clients.redis_client import get_redis_client
    return get_redis_client()


def get_active_corpus() -> str:
    """Renvoie le tenant_id du corpus actif (fail-soft → ``default``)."""
    try:
        rc = _get_redis_client()
        if rc and getattr(rc, "client", None) is not None:
            value = rc.client.get(ACTIVE_CORPUS_KEY)
            if value:
                return value if isinstance(value, str) else value.decode("utf-8")
    except Exception:  # noqa: BLE001 — jamais bloquant pour le chat
        logger.warning("[ACTIVE_CORPUS] lecture échouée → fallback 'default'", exc_info=True)
    return DEFAULT_CORPUS


def set_active_corpus(tenant_id: str) -> None:
    """Fixe le corpus actif. Lève si Redis est indisponible (action admin explicite)."""
    tenant_id = (tenant_id or "").strip()
    if not tenant_id:
        raise ValueError("tenant_id vide")
    rc = _get_redis_client()
    if not rc or getattr(rc, "client", None) is None:
        raise RuntimeError("Redis indisponible — impossible de fixer le corpus actif")
    rc.client.set(ACTIVE_CORPUS_KEY, tenant_id)
    logger.info("[ACTIVE_CORPUS] corpus actif fixé sur '%s'", tenant_id)
