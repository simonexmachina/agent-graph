"""Logging setup."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

MAX_LOG_BYTES = 1024 * 1024
LOG_BACKUP_COUNT = 7
_AGENTGRAPH_HANDLER = "_agentgraph_handler"


def configure_logging(level: str = "INFO", log_file: str | Path | None = None) -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Force-configure the root logger, overriding any handlers uvicorn already added.
    root = logging.getLogger()
    root.setLevel(log_level)

    if log_file is not None:
        path = Path(log_file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        candidate_handler = next(
            (candidate for candidate in root.handlers if getattr(candidate, _AGENTGRAPH_HANDLER, False)),
            None,
        )
        handler = candidate_handler if isinstance(candidate_handler, RotatingFileHandler) else None
        if handler is None:
            handler = RotatingFileHandler(
                path,
                maxBytes=MAX_LOG_BYTES,
                backupCount=LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
            setattr(handler, _AGENTGRAPH_HANDLER, True)
            root.addHandler(handler)
        elif Path(handler.baseFilename) != path:
            root.removeHandler(handler)
            handler.close()
            handler = RotatingFileHandler(
                path,
                maxBytes=MAX_LOG_BYTES,
                backupCount=LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
            setattr(handler, _AGENTGRAPH_HANDLER, True)
            root.addHandler(handler)
        handler.setLevel(log_level)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
                datefmt="%H:%M:%S",
            )
        )
    elif not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)-8s %(name)s  %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        root.addHandler(handler)
    else:
        for handler in root.handlers:
            handler.setLevel(log_level)

    # Quiet noisy third-party loggers regardless of level
    for noisy in (
        "httpx",
        "httpcore",
        "fastembed",
        "uvicorn.access",
        "googleapiclient.discovery_cache",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)
