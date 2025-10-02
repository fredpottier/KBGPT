import logging
from pathlib import Path


class FlushingFileHandler(logging.FileHandler):
    """File handler qui flush immédiatement après chaque log"""
    def emit(self, record):
        super().emit(record)
        self.flush()  # Flush après chaque log


def setup_logging(
    logs_dir: Path, log_file_name: str, logger_name: str = "sap_ingest"
) -> logging.Logger:
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)  # <-- Niveau DEBUG

    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / log_file_name

    # IMPORTANT: Supprimer tous les handlers existants pour forcer reconfiguration
    # (nécessaire pour workers RQ qui peuvent avoir un logger pré-existant)
    if logger.hasHandlers():
        for handler in logger.handlers[:]:  # Copie de la liste pour éviter modification pendant itération
            logger.removeHandler(handler)
            handler.close()

    # Désactiver la propagation au logger root pour éviter double émission
    logger.propagate = False

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    logger.addHandler(ch)

    # File handler avec auto-flush
    fh_flushing = FlushingFileHandler(str(log_file), encoding="utf-8", mode='a')
    fh_flushing.setLevel(logging.DEBUG)
    fh_flushing.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    logger.addHandler(fh_flushing)

    logger.info(f"📝 Logging to file: {log_file}")
    return logger
