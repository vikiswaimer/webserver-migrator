"""Определение CMS и извлечение параметров подключения к БД."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CmsDetection:
    cms_name: str
    root: Path
    evidence_files: list[Path] = field(default_factory=list)
    db_params: dict[str, str] = field(default_factory=dict)


class CmsService:
    """Эвристическое определение CMS и парсинг DB-конфигов."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def detect_in_directory(self, root: Path) -> CmsDetection | None:
        root = root.resolve()
        if not root.is_dir():
            return None

        detectors = (
            self._detect_wordpress,
            self._detect_bitrix,
            self._detect_laravel,
            self._detect_joomla,
        )
        for detector in detectors:
            result = detector(root)
            if result is not None:
                self._logger.info(
                    "CMS обнаружена: %s в %s",
                    result.cms_name,
                    result.root,
                )
                return result
        return None

    def scan_www(self, www_root: Path = Path("/var/www")) -> list[CmsDetection]:
        findings: list[CmsDetection] = []
        if not www_root.is_dir():
            self._logger.warning("Каталог сайтов отсутствует: %s", www_root)
            return findings

        # Проверяем сам корень и подкаталоги первого уровня
        candidates = [www_root, *sorted(p for p in www_root.iterdir() if p.is_dir())]
        for candidate in candidates:
            detected = self.detect_in_directory(candidate)
            if detected is not None:
                findings.append(detected)
        return findings

    def _detect_wordpress(self, root: Path) -> CmsDetection | None:
        config = root / "wp-config.php"
        if not config.is_file() and not (root / "wp-includes").is_dir():
            return None

        evidence = [p for p in (config, root / "wp-includes") if p.exists()]
        db_params: dict[str, str] = {}
        if config.is_file():
            db_params = self._parse_wp_config(config)
        return CmsDetection("WordPress", root, evidence, db_params)

    def _detect_bitrix(self, root: Path) -> CmsDetection | None:
        settings = root / "bitrix" / ".settings.php"
        dbconn = root / "bitrix" / "php_interface" / "dbconn.php"
        if not (root / "bitrix").is_dir():
            return None

        evidence = [p for p in (settings, dbconn, root / "bitrix") if p.exists()]
        db_params: dict[str, str] = {}
        if settings.is_file():
            db_params = self._parse_bitrix_settings(settings)
        elif dbconn.is_file():
            db_params = self._parse_bitrix_dbconn(dbconn)
        return CmsDetection("Bitrix", root, evidence, db_params)

    def _detect_laravel(self, root: Path) -> CmsDetection | None:
        artisan = root / "artisan"
        env_file = root / ".env"
        if not artisan.is_file() and not (root / "bootstrap" / "app.php").is_file():
            return None

        evidence = [
            p
            for p in (artisan, env_file, root / "bootstrap" / "app.php")
            if p.exists()
        ]
        db_params: dict[str, str] = {}
        if env_file.is_file():
            db_params = self._parse_dotenv_db(env_file)
        return CmsDetection("Laravel", root, evidence, db_params)

    def _detect_joomla(self, root: Path) -> CmsDetection | None:
        config = root / "configuration.php"
        if not config.is_file() and not (root / "libraries" / "joomla").is_dir():
            return None

        evidence = [
            p for p in (config, root / "libraries" / "joomla") if p.exists()
        ]
        db_params: dict[str, str] = {}
        if config.is_file():
            db_params = self._parse_joomla_config(config)
        return CmsDetection("Joomla", root, evidence, db_params)

    def _parse_wp_config(self, path: Path) -> dict[str, str]:
        text = self._safe_read(path)
        keys = {
            "DB_NAME": "database",
            "DB_USER": "user",
            "DB_PASSWORD": "password",
            "DB_HOST": "host",
            "DB_CHARSET": "charset",
        }
        result: dict[str, str] = {"source": str(path.resolve())}
        for const_name, alias in keys.items():
            match = re.search(
                rf"define\s*\(\s*['\"]{const_name}['\"]\s*,\s*['\"]([^'\"]*)['\"]",
                text,
                re.IGNORECASE,
            )
            if match:
                result[alias] = match.group(1)
        return result

    def _parse_bitrix_settings(self, path: Path) -> dict[str, str]:
        text = self._safe_read(path)
        result: dict[str, str] = {"source": str(path.resolve())}
        mapping = {
            "host": r"['\"]host['\"]\s*=>\s*['\"]([^'\"]*)['\"]",
            "database": r"['\"]database['\"]\s*=>\s*['\"]([^'\"]*)['\"]",
            "login": r"['\"]login['\"]\s*=>\s*['\"]([^'\"]*)['\"]",
            "password": r"['\"]password['\"]\s*=>\s*['\"]([^'\"]*)['\"]",
        }
        for key, pattern in mapping.items():
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                alias = "user" if key == "login" else key
                result[alias] = match.group(1)
        return result

    def _parse_bitrix_dbconn(self, path: Path) -> dict[str, str]:
        text = self._safe_read(path)
        result: dict[str, str] = {"source": str(path.resolve())}
        mapping = {
            "DBHost": "host",
            "DBLogin": "user",
            "DBPassword": "password",
            "DBName": "database",
        }
        for var_name, alias in mapping.items():
            match = re.search(
                rf"\${var_name}\s*=\s*['\"]([^'\"]*)['\"]",
                text,
            )
            if match:
                result[alias] = match.group(1)
        return result

    def _parse_dotenv_db(self, path: Path) -> dict[str, str]:
        text = self._safe_read(path)
        result: dict[str, str] = {"source": str(path.resolve())}
        mapping = {
            "DB_HOST": "host",
            "DB_PORT": "port",
            "DB_DATABASE": "database",
            "DB_USERNAME": "user",
            "DB_PASSWORD": "password",
            "DB_CONNECTION": "driver",
        }
        for env_key, alias in mapping.items():
            match = re.search(
                rf"^{env_key}\s*=\s*(.+)$",
                text,
                re.MULTILINE,
            )
            if match:
                value = match.group(1).strip().strip("\"'")
                result[alias] = value
        return result

    def _parse_joomla_config(self, path: Path) -> dict[str, str]:
        text = self._safe_read(path)
        result: dict[str, str] = {"source": str(path.resolve())}
        mapping = {
            "host": "host",
            "user": "user",
            "password": "password",
            "db": "database",
            "dbprefix": "prefix",
            "dbtype": "driver",
        }
        for prop, alias in mapping.items():
            match = re.search(
                rf"public\s+\${prop}\s*=\s*['\"]([^'\"]*)['\"]",
                text,
            )
            if match:
                result[alias] = match.group(1)
        return result

    def _safe_read(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            self._logger.warning("Не удалось прочитать %s: %s", path, exc)
            return ""
