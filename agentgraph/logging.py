"""Logging setup."""

from __future__ import annotations

import logging
import sys


def configure_logging(level: str = "INFO") -> None:
    log_level = getattr(logging, level.upper(), logging.INFO)

    # Force-configure the root logger, overriding any handlers uvicorn already added.
    root = logging.getLogger()
    root.setLevel(log_level)

    if not root.handlers:
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
