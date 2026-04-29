import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional


class LazyFlushingFileHandler(logging.Handler):
    """
    File handler lazy qui :
    1. Ne crée le fichier que lors du premier log réel (pas à l'initialisation)
    2. Flush immédiatement après chaque log
    """
    def __init__(self, filename: str, mode: str = 'a', encoding: str = 'utf-8'):
        super().__init__()
        self.filename = filename
        self.mode = mode
        self.encoding = encoding
        self._handler: Optional[logging.FileHandler] = None
        self._initialized = False

    def _ensure_handler(self):
        """Crée le FileHandler réel uniquement lors du premier log"""
        if not self._initialized:
            from pathlib import Path
            # Créer le répertoire parent si nécessaire
            Path(self.filename).parent.mkdir(parents=True, exist_ok=True)

            # Créer le vrai FileHandler
            self._handler = logging.FileHandler(
                self.filename,
                mode=self.mode,
                encoding=self.encoding
            )
            self._handler.setFormatter(self.formatter)
            self._handler.setLevel(self.level)
            self._initialized = True

    def emit(self, record):
        """Émet un log (crée le fichier à la première utilisation)"""
        self._ensure_handler()
        if self._handler:
            self._handler.emit(record)
            self._handler.flush()  # Flush après chaque log

    def close(self):
        """Ferme le handler"""
        if self._handler:
            self._handler.close()
        super().close()


class FlushingFileHandler(logging.FileHandler):
    """File handler qui flush immédiatement après chaque log (legacy, non-lazy)"""
    def emit(self, record):
        super().emit(record)
        self.flush()  # Flush après chaque log


# Cache global des loggers déjà initialisés (lazy initialization)
_LOGGER_CACHE: dict[str, logging.Logger] = {}


def get_logger(
    log_file_name: str,
    logs_dir: Optional[Path] = None,
    enable_console: bool = False
) -> logging.Logger:
    """
    Récupère un logger avec initialisation lazy (création uniquement à la première utilisation).

    Args:
        log_file_name: Nom du fichier de log (ex: "pdf_pipeline.log")
        logs_dir: Répertoire des logs (par défaut: déduit depuis settings)
        enable_console: Activer sortie console en plus du fichier

    Returns:
        Logger configuré et mis en cache

    Note:
        Le fichier de log est créé uniquement lors du premier appel à cette fonction,
        pas au moment de l'import du module.
    """
    # Utiliser log_file_name comme clé de cache
    cache_key = f"{log_file_name}:{enable_console}"

    # Si logger déjà créé, le retourner directement
    if cache_key in _LOGGER_CACHE:
        return _LOGGER_CACHE[cache_key]

    # Sinon, créer et configurer le logger
    if logs_dir is None:
        from knowbase.config.settings import get_settings
        logs_dir = get_settings().logs_dir

    logger_name = f"knowbase.{log_file_name.replace('.log', '')}"
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)

    # Éviter propagation au root logger
    logger.propagate = False

    # Créer répertoire si nécessaire
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / log_file_name

    # Supprimer handlers existants (si reconfiguration)
    if logger.hasHandlers():
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()

    # Console handler (optionnel)
    if enable_console:
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
        logger.addHandler(ch)

    # File handler avec auto-flush et création lazy
    fh_lazy = LazyFlushingFileHandler(str(log_file), mode='a', encoding="utf-8")
    fh_lazy.setLevel(logging.DEBUG)
    fh_lazy.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    logger.addHandler(fh_lazy)

    # Mettre en cache AVANT le premier log (sinon le fichier est créé immédiatement)
    _LOGGER_CACHE[cache_key] = logger

    # Premier log pour confirmer initialisation (fichier créé ici seulement)
    logger.debug(f"Logger initialized: {log_file_name}")

    return logger


def setup_logging(
    logs_dir: Path,
    log_file_name: str,
    logger_name: str = "sap_ingest",
    enable_console: bool = True
) -> logging.Logger:
    """
    Configuration de logging avec création lazy du fichier.

    Le fichier de log n'est créé que lors du premier log effectif, pas à l'initialisation.
    Configure également le logger parent "knowbase" pour capturer les logs des sous-modules.
    """
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)

    # Supprimer handlers existants
    if logger.hasHandlers():
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()

    logger.propagate = False

    # Créer les handlers
    log_file = logs_dir / log_file_name
    formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")

    # Console handler (optionnel)
    console_handler = None
    if enable_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # File handler avec auto-flush et création LAZY
    fh_lazy = LazyFlushingFileHandler(str(log_file), mode='a', encoding="utf-8")
    fh_lazy.setLevel(logging.DEBUG)
    fh_lazy.setFormatter(formatter)
    logger.addHandler(fh_lazy)

    # ==================================================================
    # IMPORTANT: Configurer aussi le logger parent "knowbase" pour
    # capturer les logs des sous-modules (agents, semantic, relations, etc.)
    # ==================================================================
    knowbase_logger = logging.getLogger("knowbase")
    knowbase_logger.setLevel(logging.DEBUG)

    # Supprimer handlers existants du logger knowbase
    if knowbase_logger.hasHandlers():
        for handler in knowbase_logger.handlers[:]:
            knowbase_logger.removeHandler(handler)
            handler.close()

    knowbase_logger.propagate = False

    # Ajouter les mêmes handlers au logger knowbase
    if console_handler:
        knowbase_logger.addHandler(console_handler)
    knowbase_logger.addHandler(fh_lazy)

    return logger


# =============================================================================
# Persistance fichier rotatée pour le ROOT logger (incident 2026-04-27)
# =============================================================================
# Objectif: capturer TOUS les logs (uvicorn, RQ, sentence_transformers, etc.)
# dans des fichiers rotatés sur un volume host, pour survivre aux container
# recreate / reboots et permettre le forensic post-incident.
#
# Les helpers `get_logger` / `setup_logging` ci-dessus restent dédiés aux
# loggers nommés (knowbase.*) avec leur logique LazyFlushing existante.
# `setup_root_file_logging` est complémentaire et s'attache au root logger.

_ROOT_FILE_LOGGING_INITIALIZED = False


def setup_root_file_logging(
    service_name: Optional[str] = None,
    logs_dir: Optional[str] = None,
    max_bytes: int = 50 * 1024 * 1024,
    backup_count: int = 20,
    level: int = logging.INFO,
) -> Optional[Path]:
    """
    Attache un RotatingFileHandler au root logger pour persister tous les logs.

    A appeler une fois au demarrage de chaque entrypoint Python (worker, app).
    Idempotent: subsequent calls are no-ops.

    Args:
        service_name: Nom du service (ex: "worker", "worker-2", "app").
            Si None, lit la var env SERVICE_NAME, fallback "service".
        logs_dir: Repertoire des logs (defaut: env LOGS_DIR ou /app/logs).
        max_bytes: Taille max par fichier avant rotation (defaut: 50MB).
        backup_count: Nombre de fichiers archives (defaut: 20 = max 1GB).
        level: Niveau de log capture (defaut: INFO).

    Returns:
        Path du fichier de log actif, ou None si setup desactive/echec.
    """
    global _ROOT_FILE_LOGGING_INITIALIZED
    if _ROOT_FILE_LOGGING_INITIALIZED:
        return None

    if service_name is None:
        service_name = os.environ.get("SERVICE_NAME", "service")

    if logs_dir is None:
        logs_dir = os.environ.get("LOGS_DIR", "/app/logs")

    try:
        log_dir = Path(logs_dir) / service_name
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{service_name}.log"

        handler = RotatingFileHandler(
            str(log_file),
            mode="a",
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))

        root = logging.getLogger()
        # Eviter les doublons si l'init est appelee plusieurs fois
        for h in root.handlers:
            if isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", "") == str(log_file):
                _ROOT_FILE_LOGGING_INITIALIZED = True
                return log_file

        root.addHandler(handler)
        if root.level > level or root.level == logging.NOTSET:
            root.setLevel(level)

        _ROOT_FILE_LOGGING_INITIALIZED = True

        # Log de confirmation (capture par le handler lui-meme)
        logging.getLogger(__name__).info(
            f"[LOGGING] Root file logging enabled: {log_file} "
            f"(rotation: {max_bytes // (1024*1024)}MB x {backup_count})"
        )
        return log_file
    except Exception as e:
        # Ne jamais casser le startup pour un probleme de logs
        logging.getLogger(__name__).warning(
            f"[LOGGING] Failed to setup root file logging at {logs_dir}: {e}"
        )
        return None
