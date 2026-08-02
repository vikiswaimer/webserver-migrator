"""Проверка PHP CLI и глубокое сканирование устаревших функций."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


DEPRECATED_PATTERNS = (
    (re.compile(r"\bmysql_connect\s*\("), "mysql_connect"),
    (re.compile(r"\bmysql_query\s*\("), "mysql_query"),
    (re.compile(r"\bmysql_fetch_array\s*\("), "mysql_fetch_array"),
    (re.compile(r"\bmysql_select_db\s*\("), "mysql_select_db"),
    (re.compile(r"\bmysql_real_escape_string\s*\("), "mysql_real_escape_string"),
    (re.compile(r"\beach\s*\("), "each()"),
    (re.compile(r"\bcreate_function\s*\("), "create_function"),
    (re.compile(r"\bsplit\s*\("), "split()"),
    (re.compile(r"\bereg(i)?(_replace|_match)?\s*\("), "ereg*"),
)


@dataclass(frozen=True)
class DeprecatedHit:
    file_path: Path
    line_number: int
    function_name: str
    line_text: str


class PhpService:
    """Информация о PHP и deep-scan исходников."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def is_available(self) -> bool:
        return shutil.which("php") is not None

    def version(self) -> str:
        if not self.is_available():
            return "php не найден в PATH"
        result = subprocess.run(
            ["php", "-v"],
            capture_output=True,
            text=True,
            check=False,
        )
        return (result.stdout or result.stderr or "").strip().splitlines()[0]

    def modules(self) -> list[str]:
        if not self.is_available():
            return []
        result = subprocess.run(
            ["php", "-m"],
            capture_output=True,
            text=True,
            check=False,
        )
        modules: list[str] = []
        for line in (result.stdout or "").splitlines():
            line = line.strip()
            if not line or line.startswith("["):
                continue
            modules.append(line)
        return modules

    def deep_scan(
        self,
        root: Path,
        max_files: int = 5000,
    ) -> list[DeprecatedHit]:
        """Сканировать PHP-файлы на устаревшие функции."""
        hits: list[DeprecatedHit] = []
        if not root.is_dir():
            self._logger.warning("Deep Scan: каталог не существует: %s", root)
            return hits

        scanned = 0
        skip_dirs = {
            "vendor",
            "node_modules",
            ".git",
            "cache",
            "tmp",
            "temp",
            "uploads",
        }

        for path in root.rglob("*.php"):
            if any(part in skip_dirs for part in path.parts):
                continue
            scanned += 1
            if scanned > max_files:
                self._logger.warning(
                    "Deep Scan: достигнут лимит файлов (%s)",
                    max_files,
                )
                break

            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError as exc:
                self._logger.debug("Не удалось прочитать %s: %s", path, exc)
                continue

            for line_number, line in enumerate(text.splitlines(), start=1):
                for pattern, name in DEPRECATED_PATTERNS:
                    if pattern.search(line):
                        hits.append(
                            DeprecatedHit(
                                file_path=path.resolve(),
                                line_number=line_number,
                                function_name=name,
                                line_text=line.strip()[:200],
                            )
                        )
        self._logger.info(
            "Deep Scan завершён: файлов=%s, совпадений=%s, корень=%s",
            scanned,
            len(hits),
            root.resolve(),
        )
        return hits
