from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from agentgraph.logging import LOG_BACKUP_COUNT, MAX_LOG_BYTES, configure_logging


def test_configure_logging_rotates_file(tmp_path: Path) -> None:
    path = tmp_path / "agentgraph.log"
    root = logging.getLogger()
    before = list(root.handlers)

    try:
        configure_logging("INFO", path)
        handler = next(
            candidate
            for candidate in root.handlers
            if getattr(candidate, "_agentgraph_handler", False)
        )
        assert isinstance(handler, RotatingFileHandler)
        assert handler.maxBytes == MAX_LOG_BYTES
        assert handler.backupCount == LOG_BACKUP_COUNT

        logger = logging.getLogger("test.logging")
        logger.info("x" * (MAX_LOG_BYTES - 100))
        logger.info("y" * 200)
        handler.flush()

        assert path.exists()
        assert path.with_name("agentgraph.log.1").exists()
    finally:
        for handler in list(root.handlers):
            if getattr(handler, "_agentgraph_handler", False):
                root.removeHandler(handler)
                handler.close()
        for handler in before:
            if handler not in root.handlers:
                root.addHandler(handler)
