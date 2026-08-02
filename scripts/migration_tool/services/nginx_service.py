"""Анализ конфигураций Nginx и путей к логам."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


LOG_DIRECTIVE_RE = re.compile(
    r"^\s*(access_log|error_log)\s+(\S+)",
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class LogPathInfo:
    directive: str
    log_file: Path
    log_dir: Path
    source_config: Path
    directory_exists: bool


class NginxService:
    """Проверка Nginx и разбор access_log / error_log."""

    DEFAULT_CONFIG_DIRS = (
        Path("/etc/nginx/sites-enabled"),
        Path("/etc/nginx/conf.d"),
        Path("/etc/nginx/sites-available"),
    )

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def is_available(self) -> bool:
        return shutil.which("nginx") is not None

    def version_info(self) -> str:
        if not self.is_available():
            return "nginx не найден в PATH"
        result = subprocess.run(
            ["nginx", "-V"],
            capture_output=True,
            text=True,
            check=False,
        )
        # nginx пишет версию в stderr
        return (result.stderr or result.stdout or "").strip()

    def discover_config_files(
        self,
        extra_roots: list[Path] | None = None,
    ) -> list[Path]:
        files: list[Path] = []
        main_conf = Path("/etc/nginx/nginx.conf")
        if main_conf.is_file():
            files.append(main_conf.resolve())

        for directory in self.DEFAULT_CONFIG_DIRS:
            if directory.is_dir():
                for item in sorted(directory.iterdir()):
                    if item.is_file() or item.is_symlink():
                        try:
                            files.append(item.resolve())
                        except OSError:
                            files.append(item.absolute())

        roots = extra_roots or []
        for root in roots:
            if not root.is_dir():
                continue
            for pattern in ("nginx.conf", "*.nginx.conf", "default.conf"):
                for path in root.rglob(pattern):
                    if path.is_file():
                        try:
                            rel_depth = len(path.relative_to(root).parts)
                        except ValueError:
                            continue
                        if rel_depth <= 6:
                            files.append(path.resolve())

        # Уникальные пути с сохранением порядка
        seen: set[Path] = set()
        unique: list[Path] = []
        for path in files:
            if path not in seen:
                seen.add(path)
                unique.append(path)
        return unique

    def extract_log_paths(
        self,
        config_files: list[Path] | None = None,
    ) -> list[LogPathInfo]:
        if config_files is None:
            config_files = self.discover_config_files(
                extra_roots=[Path("/var/www")],
            )

        results: list[LogPathInfo] = []
        seen_files: set[Path] = set()

        for config_file in config_files:
            try:
                text = config_file.read_text(encoding="utf-8", errors="ignore")
            except OSError as exc:
                self._logger.warning(
                    "Не удалось прочитать конфиг %s: %s",
                    config_file,
                    exc,
                )
                continue

            for match in LOG_DIRECTIVE_RE.finditer(text):
                directive = match.group(1).lower()
                raw_path = match.group(2).rstrip(";")
                if raw_path.lower() == "off":
                    continue
                if not raw_path.startswith("/"):
                    continue

                log_file = Path(raw_path)
                if log_file in seen_files:
                    continue
                seen_files.add(log_file)

                log_dir = log_file.parent
                results.append(
                    LogPathInfo(
                        directive=directive,
                        log_file=log_file,
                        log_dir=log_dir,
                        source_config=config_file.resolve(),
                        directory_exists=log_dir.is_dir(),
                    )
                )
                self._logger.debug(
                    "Найден %s → %s (из %s)",
                    directive,
                    log_file,
                    config_file,
                )

        return results

    def check_log_directories(
        self,
        log_paths: list[LogPathInfo] | None = None,
    ) -> list[LogPathInfo]:
        """Вернуть записи, у которых каталог логов отсутствует."""
        if log_paths is None:
            log_paths = self.extract_log_paths()
        return [item for item in log_paths if not item.directory_exists]
