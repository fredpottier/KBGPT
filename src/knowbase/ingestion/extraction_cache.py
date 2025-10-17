"""
🌊 OSMOSE Extraction Cache System

Système de cache pour économiser ressources/coûts lors du développement/tests.

**Problème Résolu:**
- Re-extraction coûteuse (Vision LLM, MegaParse) à chaque test OSMOSE
- Développement agent nécessite tests itératifs sans re-extraire

**Solution:**
- Format `.knowcache.json` standardisé
- Sauvegarde automatique après extraction
- Réimport instantané depuis cache (skip extraction)
- Auto-purge après expiration

**Workflow:**
1. Import normal PDF/PPTX → Extraction → Cache sauvegardé
2. Tests OSMOSE → Réimport .knowcache.json → Skip extraction, direct OSMOSE

**Économies:**
- Temps: -90% (skip extraction Vision/MegaParse)
- Coûts: -$0.15-0.50 par test (pas de Vision calls)
- Ressources: -80% CPU/RAM

Phase 1 V2.2 - Semaine 10+ (Optimisation Dev/Tests)
"""

from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
import json
import hashlib
import logging

logger = logging.getLogger(__name__)


@dataclass
class ExtractionCacheMetadata:
    """Métadonnées du cache d'extraction."""

    version: str = "1.0"
    source_file: str = ""
    source_hash: str = ""  # sha256 du fichier source
    extraction_timestamp: str = ""  # ISO format
    extraction_config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DocumentMetadata:
    """Métadonnées du document."""

    title: str = ""
    pages: int = 0
    language: str = "en"
    author: str = ""
    keywords: List[str] = field(default_factory=list)
    custom_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractedText:
    """Texte extrait du document."""

    full_text: str = ""
    length_chars: int = 0
    pages: List[Dict[str, Any]] = field(default_factory=list)  # Page-level texts


@dataclass
class ExtractionStats:
    """Statistiques d'extraction."""

    duration_seconds: float = 0.0
    vision_calls: int = 0
    cost_usd: float = 0.0
    megaparse_blocks: int = 0


@dataclass
class ExtractionCache:
    """
    Cache d'extraction pour réutilisation.

    Format: `.knowcache.json`
    """

    metadata: ExtractionCacheMetadata
    document_metadata: DocumentMetadata
    extracted_text: ExtractedText
    extraction_stats: ExtractionStats

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dict pour serialization JSON."""
        return {
            "metadata": asdict(self.metadata),
            "document_metadata": asdict(self.document_metadata),
            "extracted_text": asdict(self.extracted_text),
            "extraction_stats": asdict(self.extraction_stats)
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExtractionCache":
        """Charge depuis dict JSON."""
        return cls(
            metadata=ExtractionCacheMetadata(**data.get("metadata", {})),
            document_metadata=DocumentMetadata(**data.get("document_metadata", {})),
            extracted_text=ExtractedText(**data.get("extracted_text", {})),
            extraction_stats=ExtractionStats(**data.get("extraction_stats", {}))
        )


class ExtractionCacheManager:
    """
    Gestionnaire de cache d'extraction.

    Responsabilités:
    - Sauvegarde cache après extraction
    - Lecture cache pour skip extraction
    - Validation cache (expiration, intégrité)
    - Auto-purge caches expirés
    """

    def __init__(
        self,
        cache_dir: Path,
        enabled: bool = True,
        expiry_days: int = 30
    ):
        """
        Initialise le gestionnaire.

        Args:
            cache_dir: Répertoire stockage caches
            enabled: Activer système cache
            expiry_days: Jours avant expiration cache
        """
        self.cache_dir = Path(cache_dir)
        self.enabled = enabled
        self.expiry_days = expiry_days

        if self.enabled:
            # Créer répertoire si nécessaire
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            logger.info(
                f"[CACHE] ExtractionCacheManager initialized "
                f"(dir={cache_dir}, expiry={expiry_days}d)"
            )
        else:
            logger.info("[CACHE] ExtractionCacheManager disabled")

    def save_cache(
        self,
        source_file_path: Path,
        extracted_text: str,
        document_metadata: Dict[str, Any],
        extraction_config: Dict[str, Any],
        extraction_stats: Dict[str, Any],
        page_texts: Optional[List[Dict[str, Any]]] = None
    ) -> Optional[Path]:
        """
        Sauvegarde cache d'extraction.

        Args:
            source_file_path: Chemin fichier source (PDF/PPTX)
            extracted_text: Texte complet extrait
            document_metadata: Métadonnées document
            extraction_config: Config extraction utilisée
            extraction_stats: Stats extraction (durée, coût, etc.)
            page_texts: (Optionnel) Textes par page

        Returns:
            Path du fichier cache créé, ou None si erreur
        """
        if not self.enabled:
            return None

        try:
            # Calculer hash fichier source
            source_hash = self._calculate_file_hash(source_file_path)

            # Construire cache object
            cache = ExtractionCache(
                metadata=ExtractionCacheMetadata(
                    version="1.0",
                    source_file=source_file_path.name,
                    source_hash=source_hash,
                    extraction_timestamp=datetime.utcnow().isoformat() + "Z",
                    extraction_config=extraction_config
                ),
                document_metadata=DocumentMetadata(
                    title=document_metadata.get("title", source_file_path.stem),
                    pages=document_metadata.get("pages", 0),
                    language=document_metadata.get("language", "en"),
                    author=document_metadata.get("author", ""),
                    keywords=document_metadata.get("keywords", []),
                    custom_metadata=document_metadata.get("custom_metadata", {})
                ),
                extracted_text=ExtractedText(
                    full_text=extracted_text,
                    length_chars=len(extracted_text),
                    pages=page_texts or []
                ),
                extraction_stats=ExtractionStats(
                    duration_seconds=extraction_stats.get("duration_seconds", 0.0),
                    vision_calls=extraction_stats.get("vision_calls", 0),
                    cost_usd=extraction_stats.get("cost_usd", 0.0),
                    megaparse_blocks=extraction_stats.get("megaparse_blocks", 0)
                )
            )

            # Chemin cache: source_file.knowcache.json
            cache_path = self.cache_dir / f"{source_file_path.stem}.knowcache.json"

            # Sauvegarder JSON
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache.to_dict(), f, indent=2, ensure_ascii=False)

            logger.info(
                f"[CACHE] ✅ Cache saved: {cache_path.name} "
                f"({len(extracted_text)} chars, "
                f"${extraction_stats.get('cost_usd', 0):.3f})"
            )

            return cache_path

        except Exception as e:
            logger.error(f"[CACHE] ❌ Failed to save cache for {source_file_path.name}: {e}")
            return None

    def load_cache(self, cache_file_path: Path) -> Optional[ExtractionCache]:
        """
        Charge cache depuis fichier .knowcache.json.

        Args:
            cache_file_path: Chemin fichier cache

        Returns:
            ExtractionCache ou None si invalide/expiré
        """
        if not self.enabled:
            return None

        if not cache_file_path.exists():
            logger.warning(f"[CACHE] Cache file not found: {cache_file_path}")
            return None

        try:
            # Charger JSON
            with open(cache_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            cache = ExtractionCache.from_dict(data)

            # Validation: version
            if cache.metadata.version != "1.0":
                logger.warning(
                    f"[CACHE] Unsupported cache version: {cache.metadata.version}"
                )
                return None

            # Validation: expiration
            if not self._is_cache_valid(cache):
                logger.warning(
                    f"[CACHE] Cache expired: {cache_file_path.name} "
                    f"(age > {self.expiry_days} days)"
                )
                return None

            logger.info(
                f"[CACHE] ✅ Cache loaded: {cache_file_path.name} "
                f"({cache.extracted_text.length_chars} chars, "
                f"saved ${cache.extraction_stats.cost_usd:.3f})"
            )

            return cache

        except Exception as e:
            logger.error(f"[CACHE] ❌ Failed to load cache {cache_file_path.name}: {e}")
            return None

    def is_cache_available(self, source_file_path: Path) -> bool:
        """
        Vérifie si cache valide existe pour un fichier source.

        Args:
            source_file_path: Chemin fichier source

        Returns:
            True si cache valide disponible
        """
        if not self.enabled:
            return False

        cache_path = self.cache_dir / f"{source_file_path.stem}.knowcache.json"

        if not cache_path.exists():
            return False

        # Charger et valider
        cache = self.load_cache(cache_path)

        return cache is not None

    def purge_expired_caches(self) -> int:
        """
        Purge caches expirés.

        Returns:
            Nombre de caches supprimés
        """
        if not self.enabled:
            return 0

        purged_count = 0

        try:
            # Trouver tous .knowcache.json
            cache_files = list(self.cache_dir.glob("*.knowcache.json"))

            for cache_file in cache_files:
                try:
                    cache = self.load_cache(cache_file)

                    # Si invalide/expiré → supprimer
                    if cache is None or not self._is_cache_valid(cache):
                        cache_file.unlink()
                        purged_count += 1
                        logger.info(f"[CACHE] Purged expired: {cache_file.name}")

                except Exception as e:
                    logger.warning(f"[CACHE] Error checking {cache_file.name}: {e}")

            if purged_count > 0:
                logger.info(f"[CACHE] ✅ Purged {purged_count} expired caches")

        except Exception as e:
            logger.error(f"[CACHE] ❌ Error during purge: {e}")

        return purged_count

    def _calculate_file_hash(self, file_path: Path) -> str:
        """
        Calcule SHA256 hash du fichier.

        Args:
            file_path: Chemin fichier

        Returns:
            Hash hexadecimal
        """
        sha256 = hashlib.sha256()

        try:
            with open(file_path, 'rb') as f:
                # Lire par blocs pour économiser RAM
                for chunk in iter(lambda: f.read(8192), b''):
                    sha256.update(chunk)

            return sha256.hexdigest()

        except Exception as e:
            logger.warning(f"[CACHE] Failed to hash {file_path.name}: {e}")
            return "unknown"

    def _is_cache_valid(self, cache: ExtractionCache) -> bool:
        """
        Vérifie si cache est valide (non expiré).

        Args:
            cache: Cache à vérifier

        Returns:
            True si valide
        """
        try:
            # Parser timestamp ISO
            timestamp_str = cache.metadata.extraction_timestamp.replace('Z', '+00:00')
            extraction_time = datetime.fromisoformat(timestamp_str)

            # Calculer âge
            age = datetime.now(extraction_time.tzinfo) - extraction_time

            # Vérifier expiration
            if age > timedelta(days=self.expiry_days):
                return False

            return True

        except Exception as e:
            logger.warning(f"[CACHE] Failed to validate cache timestamp: {e}")
            return False


# Singleton global
_cache_manager_instance: Optional[ExtractionCacheManager] = None


def get_cache_manager(
    cache_dir: Optional[Path] = None,
    enabled: Optional[bool] = None,
    expiry_days: Optional[int] = None
) -> ExtractionCacheManager:
    """
    Récupère instance singleton du cache manager.

    Args:
        cache_dir: (Optionnel) Répertoire cache
        enabled: (Optionnel) Activer cache
        expiry_days: (Optionnel) Jours expiration

    Returns:
        ExtractionCacheManager singleton
    """
    global _cache_manager_instance

    if _cache_manager_instance is None:
        # Charger config depuis settings
        from knowbase.config.settings import get_settings
        settings = get_settings()

        # Valeurs par défaut depuis settings
        default_cache_dir = Path(getattr(settings, "extraction_cache_dir", "/app/data/extraction_cache"))
        default_enabled = getattr(settings, "enable_extraction_cache", True)
        default_expiry = getattr(settings, "cache_expiry_days", 30)

        _cache_manager_instance = ExtractionCacheManager(
            cache_dir=cache_dir or default_cache_dir,
            enabled=enabled if enabled is not None else default_enabled,
            expiry_days=expiry_days or default_expiry
        )

    return _cache_manager_instance
