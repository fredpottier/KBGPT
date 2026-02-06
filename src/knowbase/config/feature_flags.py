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
        feature_name: Nom de la feature (ex: "enable_hybrid_extraction", "phase_2_hybrid_anchor")
        tenant_id: ID tenant pour overrides
        default: Valeur par défaut si non trouvée

    Returns:
        True si activée, False sinon
    """
    flags = _load_feature_flags()
    flags = _get_environment_overrides(flags)
    flags = _get_tenant_overrides(flags, tenant_id)

    # =========================================================================
    # Phase 2+ : Vérifier d'abord les sections de premier niveau (phase_2_*)
    # =========================================================================
    if feature_name in flags:
        value = flags[feature_name]
        if isinstance(value, bool):
            return value
        elif isinstance(value, dict):
            return value.get("enabled", default)

    # =========================================================================
    # Hybrid Intelligence : Chercher dans hybrid_intelligence (nouveau)
    # =========================================================================
    hybrid_intel = flags.get("hybrid_intelligence", {})
    if feature_name in hybrid_intel:
        value = hybrid_intel[feature_name]
        if isinstance(value, bool):
            return value
        elif isinstance(value, dict):
            return value.get("enabled", default)

    # =========================================================================
    # Legacy: Chercher dans phase_1_8 (compatibilité)
    # =========================================================================
    phase_1_8 = flags.get("phase_1_8", {})
    if phase_1_8.get("enabled", True) and feature_name in phase_1_8:
        value = phase_1_8[feature_name]
        if isinstance(value, bool):
            return value
        elif isinstance(value, dict):
            return value.get("enabled", default)

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

    # Chercher dans hybrid_intelligence (nouveau)
    hybrid_intel = flags.get("hybrid_intelligence", {})
    if config_name in hybrid_intel:
        value = hybrid_intel[config_name]
        if isinstance(value, dict):
            return value

    # Fallback: Chercher dans phase_1_8 (legacy)
    phase_1_8 = flags.get("phase_1_8", {})
    if config_name in phase_1_8:
        value = phase_1_8[config_name]
        if isinstance(value, dict):
            return value

    return {}


def get_hybrid_anchor_config(
    config_name: str,
    tenant_id: str = "default"
) -> Any:
    """
    Obtient une configuration du Hybrid Anchor Model (Phase 2).

    Args:
        config_name: Nom de la config (ex: "anchor_config", "pass2_mode")
        tenant_id: ID tenant pour overrides

    Returns:
        Valeur de configuration (dict, str, etc.)
    """
    flags = _load_feature_flags()
    flags = _get_environment_overrides(flags)
    flags = _get_tenant_overrides(flags, tenant_id)

    # Chercher dans phase_2_hybrid_anchor
    phase_2 = flags.get("phase_2_hybrid_anchor", {})

    if config_name in phase_2:
        return phase_2[config_name]

    return None


def get_stratified_v2_config(
    config_name: str,
    tenant_id: str = "default"
) -> Any:
    """
    Obtient une configuration du Stratified Pipeline V2.

    Args:
        config_name: Nom de la config (ex: "strict_promotion", "promotion_threshold")
        tenant_id: ID tenant pour overrides

    Returns:
        Valeur de configuration (bool, float, dict, etc.)
    """
    flags = _load_feature_flags()
    flags = _get_environment_overrides(flags)
    flags = _get_tenant_overrides(flags, tenant_id)

    # Chercher dans stratified_pipeline_v2
    stratified = flags.get("stratified_pipeline_v2", {})

    if config_name in stratified:
        return stratified[config_name]

    return None


def get_feature_flags(tenant_id: str = "default") -> Dict[str, Any]:
    """
    Retourne tous les feature flags avec overrides appliques.

    Args:
        tenant_id: ID tenant pour overrides

    Returns:
        Dict complet des feature flags
    """
    flags = _load_feature_flags()
    flags = _get_environment_overrides(flags)
    flags = _get_tenant_overrides(flags, tenant_id)
    return flags


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

    # =========================================================================
    # Phase 2 - Hybrid Anchor Model
    # =========================================================================

    @property
    def enable_hybrid_anchor_model(self) -> bool:
        """Active le Hybrid Anchor Model (Phase 2)."""
        return is_feature_enabled("phase_2_hybrid_anchor", self.tenant_id, default=True)

    @property
    def pass2_mode(self) -> str:
        """Mode d'exécution Pass 2: inline, background, ou scheduled."""
        return get_hybrid_anchor_config("pass2_mode", self.tenant_id) or "background"

    @property
    def anchor_config(self) -> Dict[str, Any]:
        """Configuration des anchors (fuzzy matching)."""
        return get_hybrid_anchor_config("anchor_config", self.tenant_id) or {
            "min_fuzzy_score": 85,
            "min_approximate_score": 70,
            "reject_below_score": 70
        }

    @property
    def promotion_config(self) -> Dict[str, Any]:
        """Configuration de promotion ProtoConcept → CanonicalConcept."""
        return get_hybrid_anchor_config("promotion_config", self.tenant_id) or {
            "min_proto_concepts_for_stable": 2,
            "min_anchor_sections_for_stable": 2,
            "allow_singleton_if_high_signal": True
        }

    @property
    def chunking_config(self) -> Dict[str, Any]:
        """Configuration du chunking document-centric."""
        return get_hybrid_anchor_config("chunking_config", self.tenant_id) or {
            "chunk_size_tokens": 256,
            "chunk_overlap_tokens": 64,
            "min_chunk_tokens": 50
        }
