"""Инициализация логирования в /tmp/ и консоль."""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path


def build_log_path() -> Path:
    """Сформировать абсолютный путь к лог-файлу в /tmp/."""
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return Path(f"/tmp/migration_process_{stamp}.log").resolve()


def setup_logging(log_path: Path | None = None) -> tuple[logging.Logger, Path]:
    """
    Настроить root-логгер: файл (DEBUG) + консоль (INFO).

    Returns:
        Кортеж (logger, абсолютный путь к логу).
    """
    if log_path is None:
        log_path = build_log_path()

    log_path = log_path.resolve()
    logger = logging.getLogger("migration_tool")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    logger.propagate = False

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(message)s"))

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    logger.debug("Логирование инициализировано")
    logger.info("Лог скрипта: %s", log_path)
    return logger, log_path
