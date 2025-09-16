import logging
from pathlib import Path


def setup_logging(
    logs_dir: Path, log_file_name: str, logger_name: str = "sap_ingest"
) -> logging.Logger:
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)  # <-- Niveau DEBUG

    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / log_file_name

    # Clear existing handlers
    logger.handlers = []

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    logger.addHandler(ch)

    # File handler
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)  # <-- Niveau DEBUG pour le fichier
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    logger.addHandler(fh)

    logger.info(f"📝 Logging to file: {log_file}")
    return logger
