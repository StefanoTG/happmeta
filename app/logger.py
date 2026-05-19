"""Central logging setup for SubProxy."""
from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path


def setup_logger(name: str = "subproxy", log_file: str | None = None,
                 level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger
