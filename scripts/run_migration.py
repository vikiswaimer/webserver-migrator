#!/usr/bin/env python3
"""Лаунчер миграционного комбайна (удобная точка входа)."""

from __future__ import annotations

import sys
from pathlib import Path

# Позволяет запускать скрипт напрямую: python3 scripts/run_migration.py
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from migration_tool.cli import main  # noqa: E402


if __name__ == "__main__":
    sys.exit(main())
