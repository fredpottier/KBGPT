"""
OSMOSE Deprecation System
=========================

Système unifié pour marquer, documenter et tracer le code déprécié.

Usage:
------
Pour un module entier (appeler au début du fichier):

    from knowbase.common.deprecation import deprecated_module, DeprecationKind
    deprecated_module(
        kind=DeprecationKind.DEAD_CODE,
        reason="Module jamais intégré en production",
        alternative="knowbase.new_module"
    )

Pour une fonction ou classe spécifique:

    from knowbase.common.deprecation import deprecated, DeprecationKind

    @deprecated(
        kind=DeprecationKind.LEGACY_COMPAT,
        reason="Ancienne API maintenue pour compatibilité",
        removal_version="2.0.0",
        alternative="new_function()"
    )
    def old_function():
        ...

Kinds disponibles:
------------------
- DEAD_CODE: Code jamais appelé, peut être supprimé
- LEGACY_COMPAT: Maintenu pour compatibilité arrière
- EXPERIMENTAL: Non stabilisé, API peut changer
- PHASE_ABANDONED: Fonctionnalité/phase abandonnée
"""

from enum import Enum
from typing import Any, Callable, Optional, TypeVar
import functools
import inspect
import logging
import warnings

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


class DeprecationKind(str, Enum):
    """Types de dépréciation supportés."""

    DEAD_CODE = "DEAD_CODE"
    """Code jamais appelé en production, candidat à suppression immédiate."""

    LEGACY_COMPAT = "LEGACY_COMPAT"
    """Maintenu uniquement pour compatibilité arrière, éviter tout nouvel usage."""

    EXPERIMENTAL = "EXPERIMENTAL"
    """Code non stabilisé, l'API peut changer sans préavis."""

    PHASE_ABANDONED = "PHASE_ABANDONED"
    """Code lié à une phase/feature abandonnée du projet."""


class DeprecationInfo:
    """Informations de dépréciation attachées à un élément."""

    def __init__(
        self,
        kind: DeprecationKind,
        reason: str,
        removal_version: Optional[str] = None,
        alternative: Optional[str] = None,
        module: Optional[str] = None,
        qualname: Optional[str] = None,
    ):
        self.kind = kind
        self.reason = reason
        self.removal_version = removal_version
        self.alternative = alternative
        self.module = module
        self.qualname = qualname

    def to_dict(self) -> dict:
        """Convertit en dictionnaire pour sérialisation."""
        return {
            "kind": self.kind.value,
            "reason": self.reason,
            "removal_version": self.removal_version,
            "alternative": self.alternative,
            "module": self.module,
            "qualname": self.qualname,
        }

    def format_message(self) -> str:
        """Formate le message de warning."""
        parts = [f"[OSMOSE:DEPRECATED:{self.kind.value}]"]

        if self.qualname:
            parts.append(self.qualname)
        elif self.module:
            parts.append(self.module)

        parts.append("|")
        parts.append(self.reason)

        if self.alternative:
            parts.append(f"| Use: {self.alternative}")

        if self.removal_version:
            parts.append(f"| Removal: {self.removal_version}")

        return " ".join(parts)


def deprecated(
    kind: DeprecationKind,
    reason: str,
    removal_version: Optional[str] = None,
    alternative: Optional[str] = None,
) -> Callable[[F], F]:
    """
    Décorateur pour marquer une fonction ou classe comme dépréciée.

    Args:
        kind: Type de dépréciation (DEAD_CODE, LEGACY_COMPAT, etc.)
        reason: Raison de la dépréciation
        removal_version: Version prévue pour suppression (optionnel)
        alternative: Code alternatif à utiliser (optionnel)

    Returns:
        Décorateur qui wrap la fonction/classe

    Example:
        @deprecated(
            kind=DeprecationKind.DEAD_CODE,
            reason="Fonction jamais utilisée",
            alternative="new_function()"
        )
        def old_function():
            pass
    """

    def decorator(func: F) -> F:
        info = DeprecationInfo(
            kind=kind,
            reason=reason,
            removal_version=removal_version,
            alternative=alternative,
            module=func.__module__,
            qualname=func.__qualname__,
        )

        # Attacher l'info de dépréciation
        func._deprecated = True  # type: ignore
        func._deprecation_info = info  # type: ignore

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            warnings.warn(
                info.format_message(),
                DeprecationWarning,
                stacklevel=2,
            )
            return func(*args, **kwargs)

        # Propager les attributs de dépréciation au wrapper
        wrapper._deprecated = True  # type: ignore
        wrapper._deprecation_info = info  # type: ignore

        return wrapper  # type: ignore

    return decorator


def deprecated_class(
    kind: DeprecationKind,
    reason: str,
    removal_version: Optional[str] = None,
    alternative: Optional[str] = None,
) -> Callable[[type], type]:
    """
    Décorateur pour marquer une classe comme dépréciée.

    Émet un warning lors de l'instanciation de la classe.

    Example:
        @deprecated_class(
            kind=DeprecationKind.PHASE_ABANDONED,
            reason="Classe Phase 1 abandonnée",
            alternative="NewClass"
        )
        class OldClass:
            pass
    """

    def decorator(cls: type) -> type:
        info = DeprecationInfo(
            kind=kind,
            reason=reason,
            removal_version=removal_version,
            alternative=alternative,
            module=cls.__module__,
            qualname=cls.__qualname__,
        )

        # Sauvegarder l'__init__ original
        original_init = cls.__init__

        @functools.wraps(original_init)
        def new_init(self: Any, *args: Any, **kwargs: Any) -> None:
            warnings.warn(
                info.format_message(),
                DeprecationWarning,
                stacklevel=2,
            )
            original_init(self, *args, **kwargs)

        cls.__init__ = new_init  # type: ignore
        cls._deprecated = True  # type: ignore
        cls._deprecation_info = info  # type: ignore

        return cls

    return decorator


# Registry global des modules dépréciés (pour l'audit)
_deprecated_modules: dict[str, DeprecationInfo] = {}


def deprecated_module(
    kind: DeprecationKind,
    reason: str,
    removal_version: Optional[str] = None,
    alternative: Optional[str] = None,
) -> None:
    """
    Marque un module entier comme déprécié.

    Doit être appelé au début du fichier, juste après les imports.
    Émet un warning à l'import du module.

    Args:
        kind: Type de dépréciation
        reason: Raison de la dépréciation
        removal_version: Version prévue pour suppression
        alternative: Module alternatif à utiliser

    Example:
        # Au début de old_module.py
        from knowbase.common.deprecation import deprecated_module, DeprecationKind

        deprecated_module(
            kind=DeprecationKind.DEAD_CODE,
            reason="Module jamais utilisé en production",
            alternative="knowbase.new_module"
        )
    """
    frame = inspect.currentframe()
    if frame and frame.f_back:
        module_name = frame.f_back.f_globals.get("__name__", "unknown")
        module_file = frame.f_back.f_globals.get("__file__", "unknown")
    else:
        module_name = "unknown"
        module_file = "unknown"

    info = DeprecationInfo(
        kind=kind,
        reason=reason,
        removal_version=removal_version,
        alternative=alternative,
        module=module_name,
    )

    # Enregistrer dans le registry
    _deprecated_modules[module_name] = info

    # Logger pour traçabilité
    logger.debug(
        f"Deprecated module loaded: {module_name} ({module_file}) - {kind.value}"
    )

    # Émettre le warning
    warnings.warn(
        info.format_message(),
        DeprecationWarning,
        stacklevel=2,
    )


def get_deprecated_modules() -> dict[str, DeprecationInfo]:
    """
    Retourne le registry des modules dépréciés chargés.

    Utile pour l'audit runtime des modules dépréciés importés.
    """
    return _deprecated_modules.copy()


def is_deprecated(obj: Any) -> bool:
    """
    Vérifie si un objet (fonction, classe, module) est marqué comme déprécié.

    Args:
        obj: L'objet à vérifier

    Returns:
        True si l'objet a l'attribut _deprecated = True
    """
    return getattr(obj, "_deprecated", False)


def get_deprecation_info(obj: Any) -> Optional[DeprecationInfo]:
    """
    Récupère les informations de dépréciation d'un objet.

    Args:
        obj: L'objet dont on veut les infos

    Returns:
        DeprecationInfo si l'objet est déprécié, None sinon
    """
    if is_deprecated(obj):
        return getattr(obj, "_deprecation_info", None)
    return None
