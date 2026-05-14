"""
JARVIS Cloud — Logging Configuration

Sets up structured logging for the entire application.
Logs go to both stdout (for Railway/Docker) and a file (for local debug).
"""

import logging
import sys
from pathlib import Path

from app.config import get_config


def setup_logging() -> logging.Logger:
    """
    Configure root logger based on config settings.
    Returns the configured 'jarvis' logger.
    """
    cfg = get_config()

    # Ensure log directory exists
    log_dir = Path(cfg.project_root) / cfg.log_dir
    log_dir.mkdir(parents=True, exist_ok=True)

    # Format: timestamp | level | module | message
    log_format = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    formatter = logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S")

    # Console handler (stdout — Railway captures this)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)

    # File handler (local debug log)
    log_file = log_dir / "jarvis.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)

    # Configure the 'jarvis' logger
    logger = logging.getLogger("jarvis")
    logger.setLevel(cfg.log_level)
    logger.addHandler(console)
    logger.addHandler(file_handler)
    logger.propagate = False

    return logger
