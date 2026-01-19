"""
OSMOSE Linguistic Layer - Cache pour les décisions de coréférence Named↔Named

Ce module implémente le cache à deux niveaux pour les décisions de coréférence:
- Niveau 1 (Global): Paires normalisées, clé canonique indépendante de l'ordre
- Niveau 2 (Contextuel): Pour termes courts/ambigus, inclut le hash du contexte

Le cache permet d'éviter les appels LLM répétitifs pour les mêmes paires.

Ref: doc/ongoing/ADR_COREF_NAMED_NAMED_VALIDATION.md - Section Cache
"""

import json
import hashlib
import logging
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from knowbase.linguistic.coref_models import ReasonCode

logger = logging.getLogger(__name__)


@dataclass
class CachedCorefDecision:
    """Décision de coréférence cachée."""
    same_entity: bool
    reason_code: str
    reason_detail: str
    confidence: float
    source: str  # "gating", "llm", "manual"
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CachedCorefDecision":
        return cls(**data)


class CorefCache:
    """
    Cache pour les décisions de coréférence Named↔Named.

    Implémente deux niveaux de cache:
    1. Global: clé = normalize(A) || normalize(B) (ordre canonique)
    2. Contextuel: clé = global_key @ hash(context)[:8]

    Stockage: fichier JSON local (simple et portable).
    Pour un déploiement distribué, migrer vers Redis.
    """

    def __init__(
        self,
        cache_dir: Optional[str] = None,
        cache_file: str = "coref_decisions_cache.json",
        context_window: int = 100,
    ):
        """
        Initialise le cache.

        Args:
            cache_dir: Répertoire de stockage (défaut: data/coref_cache)
            cache_file: Nom du fichier cache
            context_window: Nombre de caractères de contexte à hasher
        """
        self.cache_dir = Path(cache_dir) if cache_dir else Path("data/coref_cache")
        self.cache_file = self.cache_dir / cache_file
        self.context_window = context_window

        # Créer le répertoire si nécessaire
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Charger le cache existant
        self._cache: Dict[str, CachedCorefDecision] = {}
        self._load_cache()

        logger.info(
            f"[CorefCache] Initialized: {len(self._cache)} entries, "
            f"file={self.cache_file}"
        )

    def _normalize(self, text: str) -> str:
        """Normalise le texte pour la clé de cache."""
        text = text.lower().strip()
        text = re.sub(r'[^\w\s]', '', text)
        text = re.sub(r'\s+', ' ', text)
        return text

    def _compute_global_key(self, surface_a: str, surface_b: str) -> str:
        """
        Calcule la clé globale canonique (indépendante de l'ordre).

        Args:
            surface_a: Surface de la première mention
            surface_b: Surface de la seconde mention

        Returns:
            Clé canonique "norm_a||norm_b" avec norm_a <= norm_b
        """
        norm_a = self._normalize(surface_a)
        norm_b = self._normalize(surface_b)

        # Ordre canonique (alphabétique)
        if norm_a <= norm_b:
            return f"{norm_a}||{norm_b}"
        return f"{norm_b}||{norm_a}"

    def _compute_context_hash(
        self,
        context_a: Optional[str],
        context_b: Optional[str],
    ) -> str:
        """Calcule le hash du contexte combiné."""
        ctx_combined = (context_a or "") + (context_b or "")
        # Prendre les N premiers caractères
        ctx_truncated = ctx_combined[:self.context_window * 2]
        return hashlib.md5(ctx_truncated.encode()).hexdigest()[:8]

    def _compute_contextual_key(
        self,
        surface_a: str,
        surface_b: str,
        context_a: Optional[str],
        context_b: Optional[str],
    ) -> str:
        """Calcule la clé contextuelle (global_key @ context_hash)."""
        global_key = self._compute_global_key(surface_a, surface_b)
        ctx_hash = self._compute_context_hash(context_a, context_b)
        return f"{global_key}@{ctx_hash}"

    def _is_short_term(self, surface: str) -> bool:
        """Vérifie si un terme est court/ambigu (nécessite cache contextuel)."""
        tokens = self._normalize(surface).split()
        return len(tokens) <= 2

    def _load_cache(self) -> None:
        """Charge le cache depuis le fichier."""
        if not self.cache_file.exists():
            return

        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            for key, value in data.items():
                self._cache[key] = CachedCorefDecision.from_dict(value)

            logger.debug(f"[CorefCache] Loaded {len(self._cache)} entries")

        except Exception as e:
            logger.warning(f"[CorefCache] Error loading cache: {e}")

    def _save_cache(self) -> None:
        """Sauvegarde le cache dans le fichier."""
        try:
            data = {key: val.to_dict() for key, val in self._cache.items()}

            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            logger.debug(f"[CorefCache] Saved {len(self._cache)} entries")

        except Exception as e:
            logger.error(f"[CorefCache] Error saving cache: {e}")

    def get(
        self,
        surface_a: str,
        surface_b: str,
        context_a: Optional[str] = None,
        context_b: Optional[str] = None,
    ) -> Optional[CachedCorefDecision]:
        """
        Récupère une décision depuis le cache.

        Pour les termes courts, vérifie d'abord le cache contextuel,
        puis le cache global en fallback.

        Args:
            surface_a: Surface de la première mention
            surface_b: Surface de la seconde mention
            context_a: Contexte de la première mention (optionnel)
            context_b: Contexte de la seconde mention (optionnel)

        Returns:
            CachedCorefDecision si trouvé, None sinon
        """
        # Pour les termes courts, essayer d'abord le cache contextuel
        if self._is_short_term(surface_a) or self._is_short_term(surface_b):
            if context_a or context_b:
                ctx_key = self._compute_contextual_key(
                    surface_a, surface_b, context_a, context_b
                )
                if ctx_key in self._cache:
                    logger.debug(f"[CorefCache] Contextual HIT: {ctx_key[:30]}...")
                    return self._cache[ctx_key]

        # Fallback sur cache global
        global_key = self._compute_global_key(surface_a, surface_b)
        if global_key in self._cache:
            logger.debug(f"[CorefCache] Global HIT: {global_key[:30]}...")
            return self._cache[global_key]

        logger.debug(f"[CorefCache] MISS: {global_key[:30]}...")
        return None

    def set(
        self,
        surface_a: str,
        surface_b: str,
        same_entity: bool,
        reason_code: ReasonCode,
        reason_detail: str,
        confidence: float,
        source: str,
        context_a: Optional[str] = None,
        context_b: Optional[str] = None,
        use_contextual: bool = False,
    ) -> None:
        """
        Stocke une décision dans le cache.

        Args:
            surface_a: Surface de la première mention
            surface_b: Surface de la seconde mention
            same_entity: True si même entité
            reason_code: Code de raison
            reason_detail: Détail de la raison
            confidence: Score de confiance
            source: Source de la décision ("gating", "llm", "manual")
            context_a: Contexte de la première mention
            context_b: Contexte de la seconde mention
            use_contextual: Forcer l'utilisation du cache contextuel
        """
        decision = CachedCorefDecision(
            same_entity=same_entity,
            reason_code=reason_code.value if isinstance(reason_code, ReasonCode) else reason_code,
            reason_detail=reason_detail,
            confidence=confidence,
            source=source,
            created_at=datetime.utcnow().isoformat() + "Z",
        )

        # Déterminer quelle clé utiliser
        if use_contextual or (
            (self._is_short_term(surface_a) or self._is_short_term(surface_b))
            and (context_a or context_b)
        ):
            key = self._compute_contextual_key(
                surface_a, surface_b, context_a, context_b
            )
            logger.debug(f"[CorefCache] SET contextual: {key[:30]}...")
        else:
            key = self._compute_global_key(surface_a, surface_b)
            logger.debug(f"[CorefCache] SET global: {key[:30]}...")

        self._cache[key] = decision
        self._save_cache()

    def invalidate(
        self,
        surface_a: str,
        surface_b: str,
    ) -> bool:
        """
        Invalide une entrée du cache global.

        Args:
            surface_a: Surface de la première mention
            surface_b: Surface de la seconde mention

        Returns:
            True si une entrée a été supprimée
        """
        key = self._compute_global_key(surface_a, surface_b)
        if key in self._cache:
            del self._cache[key]
            self._save_cache()
            logger.info(f"[CorefCache] Invalidated: {key[:30]}...")
            return True
        return False

    def clear(self) -> int:
        """
        Vide tout le cache.

        Returns:
            Nombre d'entrées supprimées
        """
        count = len(self._cache)
        self._cache.clear()
        self._save_cache()
        logger.info(f"[CorefCache] Cleared {count} entries")
        return count

    def stats(self) -> Dict[str, Any]:
        """Retourne des statistiques sur le cache."""
        global_count = sum(1 for k in self._cache if "@" not in k)
        contextual_count = sum(1 for k in self._cache if "@" in k)
        same_entity_count = sum(1 for v in self._cache.values() if v.same_entity)

        return {
            "total_entries": len(self._cache),
            "global_entries": global_count,
            "contextual_entries": contextual_count,
            "same_entity_ratio": same_entity_count / len(self._cache) if self._cache else 0,
            "sources": self._count_by_source(),
        }

    def _count_by_source(self) -> Dict[str, int]:
        """Compte les entrées par source."""
        counts: Dict[str, int] = {}
        for decision in self._cache.values():
            counts[decision.source] = counts.get(decision.source, 0) + 1
        return counts


# Singleton global (optionnel)
_global_cache: Optional[CorefCache] = None


def get_coref_cache(cache_dir: Optional[str] = None) -> CorefCache:
    """
    Retourne l'instance globale du cache (singleton pattern).

    Args:
        cache_dir: Répertoire de stockage (utilisé seulement à la première création)

    Returns:
        Instance de CorefCache
    """
    global _global_cache
    if _global_cache is None:
        _global_cache = CorefCache(cache_dir=cache_dir)
    return _global_cache


# Export
__all__ = [
    "CachedCorefDecision",
    "CorefCache",
    "get_coref_cache",
]
