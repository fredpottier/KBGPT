from __future__ import annotations

import logging
from pathlib import Path

from knowbase.common.logging import setup_logging


def test_setup_logging_creates_console_and_file_handlers(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    logger = setup_logging(log_dir, "test.log", "knowbase.test")

    try:
        assert log_dir.exists()
        log_file = log_dir / "test.log"
        assert log_file.exists()

        handler_types = {type(handler) for handler in logger.handlers}
        assert logging.StreamHandler in handler_types
        assert logging.FileHandler in handler_types
    finally:
        for handler in list(logger.handlers):
            handler.close()
            logger.removeHandler(handler)
