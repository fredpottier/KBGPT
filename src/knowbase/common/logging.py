import logging
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
    """
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)

    # Supprimer handlers existants
    if logger.hasHandlers():
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()

    logger.propagate = False

    # Console handler (optionnel)
    if enable_console:
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
        logger.addHandler(ch)

    # File handler avec auto-flush et création LAZY
    # Le fichier ne sera créé qu'au premier log
    log_file = logs_dir / log_file_name
    fh_lazy = LazyFlushingFileHandler(str(log_file), mode='a', encoding="utf-8")
    fh_lazy.setLevel(logging.DEBUG)
    fh_lazy.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    logger.addHandler(fh_lazy)

    # IMPORTANT: Ne pas logger ici pour éviter création immédiate du fichier
    # Le fichier sera créé uniquement lors du premier usage réel

    return logger
