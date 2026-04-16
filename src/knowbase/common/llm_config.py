"""
Configuration LLM par usage — Architecture 4 couches.

Couche 1 : UsageId       — ce que le systeme a besoin de faire
Couche 2 : UsageContract  — les contraintes de chaque usage (SLA, capabilities, degradation)
Couche 3 : RuntimeTarget  — ou executer (Ollama, DeepInfra, OpenAI, Burst vLLM, GPU direct)
Couche 4 : Binding actif  — le modele reellement affecte (configurable via admin UI)

ADR : doc/ongoing/ADR_LLM_CONFIGURATION_PAGE_V2.md
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# Couche 1 — Usages logiques
# ═══════════════════════════════════════════════════════════════════════════════


class UsageId(str, Enum):
    """Usages LLM granulaires. Chaque usage = une responsabilite homogene."""

    # Search (temps reel) — le choix est fait par search.py selon signal_policy
    SEARCH_SIMPLE = "search_simple"
    SEARCH_CROSSDOC = "search_crossdoc"
    SEARCH_TENSION = "search_tension"

    # Batch (ingestion / post-import)
    CLAIM_EXTRACTION = "claim_extraction"
    ENTITY_RESOLUTION = "entity_resolution"
    RELATION_EXTRACTION = "relation_extraction"
    CROSSDOC_REASONING = "crossdoc_reasoning"
    PERSPECTIVE_GENERATION = "perspective_generation"
    CANONICALIZATION = "canonicalization"

    # Dedies (pinned — jamais overrides)
    JUDGE_PRIMARY = "judge_primary"
    EMBEDDINGS = "embeddings"
    VISION_ANALYSIS = "vision_analysis"

    # Taches legeres
    CLASSIFICATION = "classification"
    ENRICHMENT = "enrichment"

    # V2+ (pas encore branches dans le code)
    # TRANSLATION = "translation"
    # ATLAS_GENERATION = "atlas_generation"


# ═══════════════════════════════════════════════════════════════════════════════
# Couche 3 — Runtimes concrets
# ═══════════════════════════════════════════════════════════════════════════════


class RuntimeTarget(str, Enum):
    """Runtimes concrets (pas de categories abstraites)."""
    OLLAMA_LOCAL = "ollama_local"       # Ollama sequentiel (CPU ou GPU partage)
    GPU_DIRECT = "gpu_direct"           # SentenceTransformers direct GPU (embeddings)
    DEEPINFRA = "deepinfra"             # API cloud DeepInfra (OpenAI-compatible)
    OPENAI = "openai"                   # API cloud OpenAI (vision GPT-4o)
    BURST_VLLM = "burst_vllm"          # vLLM sur EC2 Spot ou local (override temporaire)


class DegradationPolicy(str, Enum):
    """Politique de degradation explicite (pas de fallback implicite)."""
    FAIL = "fail"                       # Raise erreur, pas de fallback
    RETRY_THEN_FAIL = "retry_then_fail" # Retry 2x meme provider, puis raise
    FALLBACK_LOCAL = "fallback_local"   # Si cloud echoue → Ollama local
    FALLBACK_CLOUD = "fallback_cloud"   # Si local echoue → DeepInfra


class CompatibilityLevel(str, Enum):
    """Niveau de compatibilite runtime/contrat."""
    COMPATIBLE = "compatible"           # OK
    DEGRADED = "degraded"               # Autorise mais badge orange UI
    INCOMPATIBLE = "incompatible"       # Refuse (erreur 400)


# ═══════════════════════════════════════════════════════════════════════════════
# Matrice de compatibilite runtime
# ═══════════════════════════════════════════════════════════════════════════════

RUNTIME_CAPABILITIES: Dict[str, Dict[str, Any]] = {
    RuntimeTarget.OLLAMA_LOCAL: {
        "json_strict": False,       # Degenere parfois sur JSON structure
        "long_context": False,      # 4K-8K max pratique
        "parallel": False,          # Sequentiel
        "stable": True,
        "latency": "slow",
    },
    RuntimeTarget.GPU_DIRECT: {
        "json_strict": None,        # N/A (embeddings seulement)
        "long_context": None,
        "parallel": True,
        "stable": True,
        "latency": "fast",
    },
    RuntimeTarget.DEEPINFRA: {
        "json_strict": True,
        "long_context": True,
        "parallel": True,           # 200 concurrent calls
        "stable": True,
        "latency": "fast",
    },
    RuntimeTarget.OPENAI: {
        "json_strict": True,
        "long_context": True,
        "parallel": True,           # Rate limits
        "stable": True,
        "latency": "fast",
    },
    RuntimeTarget.BURST_VLLM: {
        "json_strict": True,        # Sans chunked prefill
        "long_context": True,
        "parallel": True,           # 16 sequences
        "stable": False,            # EC2 Spot evictions
        "latency": "fast",
    },
}


def check_compatibility(runtime: RuntimeTarget, contract: "UsageContract") -> CompatibilityLevel:
    """Verifie la compatibilite entre un runtime et un contrat d'usage."""
    caps = RUNTIME_CAPABILITIES.get(runtime, {})

    # Incompatible bloquant
    if contract.requires_structured_json and caps.get("json_strict") is False:
        return CompatibilityLevel.INCOMPATIBLE
    if contract.requires_long_context and caps.get("long_context") is False:
        return CompatibilityLevel.INCOMPATIBLE

    # Compatible degrade
    if contract.requires_structured_json and caps.get("json_strict") is None:
        return CompatibilityLevel.DEGRADED
    if contract.supports_parallelism and caps.get("parallel") is False:
        return CompatibilityLevel.DEGRADED

    return CompatibilityLevel.COMPATIBLE


# ═══════════════════════════════════════════════════════════════════════════════
# Couche 2 — Contrats d'usage
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class UsageContract:
    """Contrat immutable pour un usage LLM."""
    usage_id: UsageId
    runtime: RuntimeTarget
    model: str

    # Parametres LLM
    temperature: float = 0.2
    max_tokens: int = 2000

    # SLA
    latency_target_ms: Optional[int] = None  # None = batch, pas de SLA
    is_batch: bool = False

    # Capabilities requises (validation a l'assignation)
    requires_structured_json: bool = False
    requires_long_context: bool = False
    supports_parallelism: bool = False

    # Degradation
    degradation_policy: DegradationPolicy = DegradationPolicy.FAIL
    fallback_targets: List[RuntimeTarget] = field(default_factory=list)

    # Burst
    burst_eligible: bool = False

    # Verrouillage
    pinned: bool = False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["usage_id"] = self.usage_id.value
        d["runtime"] = self.runtime.value
        d["degradation_policy"] = self.degradation_policy.value
        d["fallback_targets"] = [ft.value for ft in self.fallback_targets]
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "UsageContract":
        data = dict(data)
        data["usage_id"] = UsageId(data["usage_id"])
        data["runtime"] = RuntimeTarget(data["runtime"])
        data["degradation_policy"] = DegradationPolicy(data.get("degradation_policy", "fail"))
        data["fallback_targets"] = [RuntimeTarget(ft) for ft in data.get("fallback_targets", [])]
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ═══════════════════════════════════════════════════════════════════════════════
# Etat Embeddings (versionne, reserve des Phase 0)
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class EmbeddingState:
    """Etat du modele d'embeddings (versionne pour guard re-indexation)."""
    model: str = "intfloat/multilingual-e5-large"
    version: str = "v1"
    dimensions: int = 1024
    runtime: RuntimeTarget = RuntimeTarget.GPU_DIRECT
    status: str = "active"  # "active" | "pending_reindex_not_applied" | "pending_reindex_applied"

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "version": self.version,
            "dimensions": self.dimensions,
            "runtime": self.runtime.value,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EmbeddingState":
        data = dict(data)
        if "runtime" in data:
            data["runtime"] = RuntimeTarget(data["runtime"])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ═══════════════════════════════════════════════════════════════════════════════
# Presets
# ═══════════════════════════════════════════════════════════════════════════════


def _build_defaults_balanced() -> Dict[str, UsageContract]:
    """Preset Balanced : search+batch = DeepInfra, lightweight = local."""
    return {
        # Search (temps reel)
        UsageId.SEARCH_SIMPLE: UsageContract(
            usage_id=UsageId.SEARCH_SIMPLE, runtime=RuntimeTarget.DEEPINFRA,
            model="Qwen/Qwen3-235B-A22B-Instruct-2507",
            temperature=0.3, max_tokens=2000, latency_target_ms=3000,
            degradation_policy=DegradationPolicy.RETRY_THEN_FAIL,
        ),
        UsageId.SEARCH_CROSSDOC: UsageContract(
            usage_id=UsageId.SEARCH_CROSSDOC, runtime=RuntimeTarget.DEEPINFRA,
            model="Qwen/Qwen3-235B-A22B-Instruct-2507",
            temperature=0.3, max_tokens=2000, latency_target_ms=5000,
            degradation_policy=DegradationPolicy.RETRY_THEN_FAIL,
        ),
        UsageId.SEARCH_TENSION: UsageContract(
            usage_id=UsageId.SEARCH_TENSION, runtime=RuntimeTarget.DEEPINFRA,
            model="Qwen/Qwen3-235B-A22B-Instruct-2507",
            temperature=0.3, max_tokens=2000, latency_target_ms=5000,
            degradation_policy=DegradationPolicy.RETRY_THEN_FAIL,
        ),
        # Batch (ingestion / post-import)
        UsageId.CLAIM_EXTRACTION: UsageContract(
            usage_id=UsageId.CLAIM_EXTRACTION, runtime=RuntimeTarget.DEEPINFRA,
            model="Qwen/Qwen2.5-72B-Instruct",
            temperature=0.0, max_tokens=2000, is_batch=True,
            requires_structured_json=True, supports_parallelism=True,
            burst_eligible=True,
        ),
        UsageId.ENTITY_RESOLUTION: UsageContract(
            usage_id=UsageId.ENTITY_RESOLUTION, runtime=RuntimeTarget.DEEPINFRA,
            model="Qwen/Qwen2.5-72B-Instruct",
            temperature=0.0, max_tokens=500, is_batch=True,
            requires_structured_json=True, burst_eligible=True,
        ),
        UsageId.RELATION_EXTRACTION: UsageContract(
            usage_id=UsageId.RELATION_EXTRACTION, runtime=RuntimeTarget.DEEPINFRA,
            model="Qwen/Qwen2.5-72B-Instruct",
            temperature=0.0, max_tokens=500, is_batch=True,
            requires_structured_json=True, burst_eligible=True,
        ),
        UsageId.CROSSDOC_REASONING: UsageContract(
            usage_id=UsageId.CROSSDOC_REASONING, runtime=RuntimeTarget.DEEPINFRA,
            model="Qwen/Qwen2.5-72B-Instruct",
            temperature=0.0, max_tokens=500, is_batch=True,
            requires_structured_json=True, burst_eligible=True,
        ),
        UsageId.PERSPECTIVE_GENERATION: UsageContract(
            usage_id=UsageId.PERSPECTIVE_GENERATION, runtime=RuntimeTarget.DEEPINFRA,
            model="Qwen/Qwen3-235B-A22B-Instruct-2507",
            temperature=0.2, max_tokens=300, is_batch=True,
            burst_eligible=True,
        ),
        UsageId.CANONICALIZATION: UsageContract(
            usage_id=UsageId.CANONICALIZATION, runtime=RuntimeTarget.DEEPINFRA,
            model="Qwen/Qwen2.5-72B-Instruct",
            temperature=0.0, max_tokens=200, is_batch=True,
            requires_structured_json=True, burst_eligible=True,
        ),
        # Dedies (pinned)
        UsageId.JUDGE_PRIMARY: UsageContract(
            usage_id=UsageId.JUDGE_PRIMARY, runtime=RuntimeTarget.OLLAMA_LOCAL,
            model="m-prometheus-14b",
            temperature=0.0, max_tokens=500,
            requires_structured_json=False,  # YES/NO evidence-based, pas de JSON complexe
            pinned=True,
        ),
        UsageId.VISION_ANALYSIS: UsageContract(
            usage_id=UsageId.VISION_ANALYSIS, runtime=RuntimeTarget.OPENAI,
            model="gpt-4o",
            temperature=0.2, max_tokens=4000,
            degradation_policy=DegradationPolicy.RETRY_THEN_FAIL, pinned=True,
        ),
        UsageId.EMBEDDINGS: UsageContract(
            usage_id=UsageId.EMBEDDINGS, runtime=RuntimeTarget.GPU_DIRECT,
            model="intfloat/multilingual-e5-large",
            pinned=True,
        ),
        # Taches legeres — DeepInfra aussi (Qwen3-14B, rapide et pas cher)
        UsageId.CLASSIFICATION: UsageContract(
            usage_id=UsageId.CLASSIFICATION, runtime=RuntimeTarget.DEEPINFRA,
            model="Qwen/Qwen3-14B",
            temperature=0.0, max_tokens=100,
            degradation_policy=DegradationPolicy.FALLBACK_LOCAL,
            fallback_targets=[RuntimeTarget.OLLAMA_LOCAL],
        ),
        UsageId.ENRICHMENT: UsageContract(
            usage_id=UsageId.ENRICHMENT, runtime=RuntimeTarget.DEEPINFRA,
            model="Qwen/Qwen3-14B",
            temperature=0.2, max_tokens=500,
            degradation_policy=DegradationPolicy.FALLBACK_LOCAL,
            fallback_targets=[RuntimeTarget.OLLAMA_LOCAL],
        ),
    }


def _build_defaults_eco() -> Dict[str, UsageContract]:
    """Preset Eco : tout local (Ollama qwen2.5:14b), $0/mois.

    Note : certains usages sont en mode degrade (JSON strict non garanti
    sur Ollama). Le preset Eco est autorise mais affiche un badge degrade
    dans l'UI pour ces usages.
    """
    defaults = _build_defaults_balanced()
    local_model = "qwen2.5:14b"
    for uid, contract in defaults.items():
        if not contract.pinned:
            contract.runtime = RuntimeTarget.OLLAMA_LOCAL
            contract.model = local_model
            contract.burst_eligible = False
            contract.supports_parallelism = False
            contract.fallback_targets = []
            contract.degradation_policy = DegradationPolicy.FAIL
            # En mode Eco, on accepte le mode degrade pour JSON strict
            # (Ollama qwen2.5:14b fonctionne mais avec un taux d'echec plus eleve)
    return defaults


def _build_defaults_max_quality() -> Dict[str, UsageContract]:
    """Preset Max Quality : DeepInfra 235B partout sauf vision/juge/embeddings."""
    defaults = _build_defaults_balanced()
    for uid, contract in defaults.items():
        if not contract.pinned and contract.runtime == RuntimeTarget.OLLAMA_LOCAL:
            contract.runtime = RuntimeTarget.DEEPINFRA
            contract.model = "Qwen/Qwen3-235B-A22B-Instruct-2507"
            contract.degradation_policy = DegradationPolicy.RETRY_THEN_FAIL
            contract.fallback_targets = []
    return defaults


PRESETS = {
    "eco": _build_defaults_eco,
    "balanced": _build_defaults_balanced,
    "max_quality": _build_defaults_max_quality,
}


# ═══════════════════════════════════════════════════════════════════════════════
# Couche 4 — UsageConfigStore (PostgreSQL → Redis → memoire)
# ═══════════════════════════════════════════════════════════════════════════════

_REDIS_KEY = "osmose:usage_config"
_DB_KEY = "usage_config"
_EMBEDDING_DB_KEY = "embedding_state"


class UsageConfigStore:
    """Lit/ecrit la configuration par usage depuis PostgreSQL avec cache Redis.

    Note : SystemSetting = solution transitoire. Si la frequence de modification
    ou les besoins d'audit augmentent → migration vers table dediee.
    """

    _cache: Optional[Dict[str, UsageContract]] = None
    _cache_time: float = 0
    _cache_ttl: float = 5.0

    def get_config(self, usage_id: UsageId) -> UsageContract:
        """Retourne le contrat actif pour un usage."""
        configs = self.get_all_configs()
        if usage_id in configs:
            return configs[usage_id]
        # Fallback sur les defaults
        defaults = _build_defaults_balanced()
        return defaults.get(usage_id, defaults[UsageId.CLASSIFICATION])

    def get_all_configs(self) -> Dict[UsageId, UsageContract]:
        """Retourne toutes les configs (cache memoire → Redis → PostgreSQL → defaults)."""
        now = time.time()

        # 1. Cache memoire
        if self._cache is not None and (now - self._cache_time) < self._cache_ttl:
            return self._cache

        # 2. Redis
        try:
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            import redis as redis_lib
            r = redis_lib.from_url(redis_url, decode_responses=True, socket_timeout=1)
            cached = r.get(_REDIS_KEY)
            if cached:
                data = json.loads(cached)
                configs = {UsageId(k): UsageContract.from_dict(v) for k, v in data.items()}
                self._cache = configs
                self._cache_time = now
                return configs
        except Exception as e:
            logger.debug(f"[UsageConfigStore] Redis read failed: {e}")

        # 3. PostgreSQL
        try:
            configs = self._read_from_db()
            if configs:
                self._cache = configs
                self._cache_time = now
                self._write_to_redis(configs)
                return configs
        except Exception as e:
            logger.debug(f"[UsageConfigStore] DB read failed: {e}")

        # 4. Defaults
        defaults = _build_defaults_balanced()
        self._cache = defaults
        self._cache_time = now
        return defaults

    def set_config(self, usage_id: UsageId, updates: dict, updated_by: str = "admin") -> UsageContract:
        """Met a jour la config d'un usage. Valide le contrat avant persistence."""
        configs = self.get_all_configs()
        current = configs.get(usage_id)
        if not current:
            raise ValueError(f"Usage inconnu: {usage_id}")

        if current.pinned and ("runtime" in updates or "model" in updates):
            raise ValueError(f"Usage {usage_id.value} est pinned — runtime/model non modifiable")

        # Appliquer les updates
        contract_dict = current.to_dict()
        contract_dict.update(updates)
        new_contract = UsageContract.from_dict(contract_dict)

        # Valider la compatibilite
        compat = check_compatibility(new_contract.runtime, new_contract)
        if compat == CompatibilityLevel.INCOMPATIBLE:
            caps = RUNTIME_CAPABILITIES.get(new_contract.runtime, {})
            raise ValueError(
                f"Runtime {new_contract.runtime.value} incompatible avec le contrat "
                f"{usage_id.value} (json_strict={caps.get('json_strict')}, "
                f"requires={new_contract.requires_structured_json})"
            )

        configs[usage_id] = new_contract
        self._write_to_db(configs, updated_by)
        self._write_to_redis(configs)
        self.invalidate_cache()
        logger.info(f"[UsageConfigStore] {usage_id.value} updated by {updated_by}: {updates}")
        return new_contract

    def apply_preset(self, preset: str, updated_by: str = "admin") -> Dict[UsageId, UsageContract]:
        """Applique un preset (eco/balanced/max_quality)."""
        builder = PRESETS.get(preset)
        if not builder:
            raise ValueError(f"Preset inconnu: {preset}. Valides: {list(PRESETS.keys())}")

        configs = builder()
        self._write_to_db(configs, updated_by)
        self._write_to_redis(configs)
        self.invalidate_cache()
        logger.info(f"[UsageConfigStore] Preset '{preset}' applied by {updated_by}")
        return configs

    def snapshot(self) -> dict:
        """Snapshot fige pour benchmark/job reports. Inclut EmbeddingState."""
        configs = self.get_all_configs()
        emb = self.get_embedding_state()
        return {
            "configs": {uid.value: c.to_dict() for uid, c in configs.items()},
            "embedding_state": emb.to_dict(),
            "preset": self._detect_active_preset(configs),
        }

    def get_embedding_state(self) -> EmbeddingState:
        """Retourne l'etat courant des embeddings."""
        try:
            from knowbase.db.base import SessionLocal
            from knowbase.db.models import SystemSetting
            db = SessionLocal()
            try:
                setting = db.query(SystemSetting).filter(
                    SystemSetting.key == _EMBEDDING_DB_KEY
                ).first()
                if setting:
                    return EmbeddingState.from_dict(json.loads(setting.value))
            finally:
                db.close()
        except Exception:
            pass
        return EmbeddingState()

    def invalidate_cache(self):
        """Invalide tous les caches."""
        self._cache = None
        self._cache_time = 0
        try:
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            import redis as redis_lib
            r = redis_lib.from_url(redis_url, decode_responses=True, socket_timeout=1)
            r.delete(_REDIS_KEY)
        except Exception:
            pass

    def _detect_active_preset(self, configs: Dict[UsageId, UsageContract]) -> Optional[str]:
        """Detecte quel preset correspond a la config actuelle."""
        for preset_name, builder in PRESETS.items():
            preset_configs = builder()
            match = True
            for uid, contract in preset_configs.items():
                current = configs.get(uid)
                if not current or current.runtime != contract.runtime or current.model != contract.model:
                    match = False
                    break
            if match:
                return preset_name
        return "custom"

    def _read_from_db(self) -> Optional[Dict[UsageId, UsageContract]]:
        from knowbase.db.base import SessionLocal
        from knowbase.db.models import SystemSetting
        db = SessionLocal()
        try:
            setting = db.query(SystemSetting).filter(
                SystemSetting.key == _DB_KEY
            ).first()
            if setting:
                data = json.loads(setting.value)
                return {UsageId(k): UsageContract.from_dict(v) for k, v in data.items()}
        finally:
            db.close()
        return None

    def _write_to_db(self, configs: Dict[UsageId, UsageContract], updated_by: str):
        from knowbase.db.base import SessionLocal
        from knowbase.db.models import SystemSetting
        from datetime import datetime, timezone

        data = {uid.value: c.to_dict() for uid, c in configs.items()}
        value_json = json.dumps(data, ensure_ascii=False)

        db = SessionLocal()
        try:
            setting = db.query(SystemSetting).filter(
                SystemSetting.key == _DB_KEY
            ).first()
            if setting:
                setting.value = value_json
                setting.updated_at = datetime.now(timezone.utc)
                setting.updated_by = updated_by
            else:
                setting = SystemSetting(
                    key=_DB_KEY,
                    value=value_json,
                    updated_by=updated_by,
                )
                db.add(setting)
            db.commit()
        finally:
            db.close()

    def _write_to_redis(self, configs: Dict[UsageId, UsageContract]):
        try:
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            import redis as redis_lib
            r = redis_lib.from_url(redis_url, decode_responses=True, socket_timeout=1)
            data = {uid.value: c.to_dict() for uid, c in configs.items()}
            r.setex(_REDIS_KEY, 30, json.dumps(data, ensure_ascii=False))
        except Exception:
            pass


# Singleton
_store: Optional[UsageConfigStore] = None


def get_usage_config_store() -> UsageConfigStore:
    global _store
    if _store is None:
        _store = UsageConfigStore()
    return _store
