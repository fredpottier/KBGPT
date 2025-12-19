"""
🌊 OSMOSE Feature Flags Module

Gestion des feature flags pour déploiement progressif.

Phase 1.8: Configuration centralisée pour toutes les nouvelles fonctionnalités.

Usage:
    from knowbase.config.feature_flags import (
        is_feature_enabled,
        get_feature_config,
        FeatureFlags
    )

    # Vérifier si une feature est activée
    if is_feature_enabled("enable_hybrid_extraction"):
        ...

    # Obtenir configuration détaillée
    config = get_feature_config("low_quality_ner")
    threshold = config.get("entity_threshold", 3)
"""

from typing import Dict, Any, Optional
from pathlib import Path
import os
import yaml
import logging

logger = logging.getLogger(__name__)

# Singleton pour cache configuration
_feature_flags_cache: Optional[Dict] = None


def _load_feature_flags() -> Dict:
    """
    Charge le fichier feature_flags.yaml.

    Returns:
        Dict avec toute la configuration
    """
    global _feature_flags_cache

    if _feature_flags_cache is not None:
        return _feature_flags_cache

    config_path = Path("config/feature_flags.yaml")

    if not config_path.exists():
        logger.warning(
            f"[FeatureFlags] Config file not found: {config_path}. "
            "Using defaults."
        )
        _feature_flags_cache = {}
        return _feature_flags_cache

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            _feature_flags_cache = yaml.safe_load(f) or {}

        logger.info(
            f"[FeatureFlags] ✅ Loaded feature flags from {config_path}"
        )

    except Exception as e:
        logger.error(f"[FeatureFlags] Error loading config: {e}")
        _feature_flags_cache = {}

    return _feature_flags_cache


def _get_environment_overrides(flags: Dict) -> Dict:
    """
    Applique les overrides d'environnement.

    Args:
        flags: Configuration de base

    Returns:
        Configuration avec overrides appliqués
    """
    env = os.getenv("OSMOSE_ENV", "development")
    environments = flags.get("environments", {})

    if env in environments:
        overrides = environments[env]
        flags = _deep_merge(flags, overrides)
        logger.debug(f"[FeatureFlags] Applied overrides for env={env}")

    return flags


def _get_tenant_overrides(flags: Dict, tenant_id: str) -> Dict:
    """
    Applique les overrides tenant.

    Args:
        flags: Configuration de base
        tenant_id: ID tenant

    Returns:
        Configuration avec overrides appliqués
    """
    tenants = flags.get("tenants", {})

    if tenant_id in tenants:
        overrides = tenants[tenant_id]
        flags = _deep_merge(flags, overrides)
        logger.debug(f"[FeatureFlags] Applied overrides for tenant={tenant_id}")

    return flags


def _deep_merge(base: Dict, override: Dict) -> Dict:
    """
    Merge récursif de deux dicts.

    Args:
        base: Dict de base
        override: Dict de surcharge

    Returns:
        Dict fusionné
    """
    result = base.copy()

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value

    return result


def is_feature_enabled(
    feature_name: str,
    tenant_id: str = "default",
    default: bool = False
) -> bool:
    """
    Vérifie si une feature est activée.

    Args:
        feature_name: Nom de la feature (ex: "enable_hybrid_extraction")
        tenant_id: ID tenant pour overrides
        default: Valeur par défaut si non trouvée

    Returns:
        True si activée, False sinon
    """
    flags = _load_feature_flags()
    flags = _get_environment_overrides(flags)
    flags = _get_tenant_overrides(flags, tenant_id)

    # Chercher dans phase_1_8 d'abord
    phase_1_8 = flags.get("phase_1_8", {})

    # Vérifier master switch
    if not phase_1_8.get("enabled", True):
        logger.debug(f"[FeatureFlags] Phase 1.8 disabled globally")
        return False

    if feature_name in phase_1_8:
        value = phase_1_8[feature_name]
        if isinstance(value, bool):
            return value
        elif isinstance(value, dict):
            return value.get("enabled", default)

    # Chercher dans phases antérieures
    for phase_key in ["phase_1_5", "phase_1"]:
        phase = flags.get(phase_key, {})
        if feature_name in phase:
            return phase[feature_name]

    return default


def get_feature_config(
    config_name: str,
    tenant_id: str = "default"
) -> Dict[str, Any]:
    """
    Obtient la configuration détaillée d'une feature.

    Args:
        config_name: Nom de la config (ex: "low_quality_ner")
        tenant_id: ID tenant pour overrides

    Returns:
        Dict avec la configuration
    """
    flags = _load_feature_flags()
    flags = _get_environment_overrides(flags)
    flags = _get_tenant_overrides(flags, tenant_id)

    # Chercher dans phase_1_8
    phase_1_8 = flags.get("phase_1_8", {})

    if config_name in phase_1_8:
        value = phase_1_8[config_name]
        if isinstance(value, dict):
            return value

    return {}


def reload_feature_flags():
    """
    Force le rechargement du fichier de configuration.

    Utile après modification dynamique.
    """
    global _feature_flags_cache
    _feature_flags_cache = None
    _load_feature_flags()
    logger.info("[FeatureFlags] Configuration reloaded")


class FeatureFlags:
    """
    Classe wrapper pour accès orienté objet aux feature flags.

    Usage:
        flags = FeatureFlags(tenant_id="pharma_tenant")
        if flags.enable_hybrid_extraction:
            ...
    """

    def __init__(self, tenant_id: str = "default"):
        """
        Initialise le wrapper.

        Args:
            tenant_id: ID tenant pour overrides
        """
        self.tenant_id = tenant_id

    @property
    def enable_hybrid_extraction(self) -> bool:
        return is_feature_enabled("enable_hybrid_extraction", self.tenant_id)

    @property
    def enable_document_context(self) -> bool:
        return is_feature_enabled("enable_document_context", self.tenant_id)

    @property
    def enable_llm_judge_validation(self) -> bool:
        return is_feature_enabled("enable_llm_judge_validation", self.tenant_id)

    @property
    def enable_entity_ruler(self) -> bool:
        return is_feature_enabled("enable_entity_ruler", self.tenant_id)

    @property
    def enable_ontology_prefetch(self) -> bool:
        return is_feature_enabled("enable_ontology_prefetch", self.tenant_id)

    @property
    def enable_llm_relation_enrichment(self) -> bool:
        return is_feature_enabled("enable_llm_relation_enrichment", self.tenant_id)

    @property
    def enable_business_rules_engine(self) -> bool:
        return is_feature_enabled("enable_business_rules_engine", self.tenant_id)

    def get_config(self, config_name: str) -> Dict[str, Any]:
        """Obtient une configuration spécifique."""
        return get_feature_config(config_name, self.tenant_id)

    @property
    def low_quality_ner_config(self) -> Dict[str, Any]:
        """Configuration LOW_QUALITY_NER."""
        return self.get_config("low_quality_ner")

    @property
    def document_context_config(self) -> Dict[str, Any]:
        """Configuration document context."""
        return self.get_config("document_context")

    @property
    def llm_judge_config(self) -> Dict[str, Any]:
        """Configuration LLM-as-a-Judge."""
        return self.get_config("llm_judge")
