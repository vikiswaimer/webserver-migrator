"""Режим 4: проверка готовности нового сервера (standalone)."""

from __future__ import annotations

import getpass
import logging
import shutil
from pathlib import Path

from ..colors import print_error, print_header, print_info, print_ok, print_warn
from ..services.database_service import DatabaseService, DbCredentials
from ..services.nginx_service import NginxService
from ..services.php_service import PhpService
from ..validators import (
    ask_validated,
    validate_host,
    validate_non_empty,
    validate_port,
)


# Базовый набор модулей, часто нужный PHP-сайтам
COMMON_PHP_MODULES = {
    "curl",
    "gd",
    "intl",
    "json",
    "mbstring",
    "mysqli",
    "openssl",
    "pdo_mysql",
    "xml",
    "zip",
}


class ReadinessMode:
    """Standalone-тест готовности нового сервера."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._php = PhpService(logger)
        self._nginx = NginxService(logger)
        self._db = DatabaseService(logger)

    def run(self) -> None:
        print_header("Режим 4: Проверка готовности нового сервера")
        self._logger.info("Запущен режим проверки готовности")

        self._check_binaries()
        self._check_php_modules()
        self._check_nginx_log_dirs()
        self._check_database()
        self._check_disk()

        print_ok("Проверка готовности завершена")

    def _check_binaries(self) -> None:
        print_header("Бинарники")
        for name in ("nginx", "php", "rsync", "mysql", "docker"):
            path = shutil.which(name)
            if path:
                print_ok(f"{name}: {path}")
            else:
                print_warn(f"{name}: не найден в PATH")

        if self._php.is_available():
            print_info(f"PHP version: {self._php.version()}")
        if self._nginx.is_available():
            print_info(self._nginx.version_info().splitlines()[0])

    def _check_php_modules(self) -> None:
        print_header("Модули PHP vs типовые требования")
        if not self._php.is_available():
            print_warn("PHP недоступен — сравнение модулей пропущено")
            return

        installed = {m.lower() for m in self._php.modules()}
        missing = sorted(COMMON_PHP_MODULES - installed)
        present = sorted(COMMON_PHP_MODULES & installed)

        for name in present:
            print_ok(f"PHP module: {name}")
        for name in missing:
            print_warn(f"PHP module отсутствует: {name}")

        custom = input(
            "Дополнительные модули через запятую (Enter = пропуск): "
        ).strip()
        if custom:
            required = {item.strip().lower() for item in custom.split(",") if item.strip()}
            for name in sorted(required):
                if name in installed:
                    print_ok(f"Доп. module: {name}")
                else:
                    print_error(f"Доп. module отсутствует: {name}")

    def _check_nginx_log_dirs(self) -> None:
        print_header("Каталоги логов Nginx на новом сервере")
        log_paths = self._nginx.extract_log_paths()
        if not log_paths:
            print_info(
                "Локальные конфиги Nginx без access_log/error_log "
                "или Nginx не настроен. Можно указать путь вручную."
            )
            manual = input(
                "Абсолютный путь каталога логов для проверки "
                "(Enter = пропуск): "
            ).strip()
            if manual:
                path = Path(manual)
                if not path.is_absolute():
                    print_error(f"Нужен абсолютный путь: {manual}")
                elif path.is_dir():
                    print_ok(f"Каталог существует: {path}")
                else:
                    print_warn(
                        f"Каталог отсутствует: {path}. "
                        f"sudo mkdir -p {path}"
                    )
            return

        for item in log_paths:
            if item.directory_exists:
                print_ok(f"{item.directive}: {item.log_dir}")
            else:
                print_warn(
                    f"{item.directive}: отсутствует {item.log_dir} "
                    f"(из {item.source_config})"
                )

    def _check_database(self) -> None:
        print_header("Тест импорта тестовой БД")
        answer = input("Выполнить CREATE/DROP временной таблицы? [y/N]: ").strip().lower()
        if answer not in {"y", "yes", "д", "да"}:
            print_info("Тест БД пропущен")
            return

        host = ask_validated("DB host", validate_host, default="127.0.0.1")
        port = ask_validated("DB port", validate_port, default="3306")
        user = ask_validated(
            "DB user",
            lambda v: validate_non_empty(v, "DB user"),
            default="root",
        )
        password = getpass.getpass("DB password (можно пусто): ")
        database = ask_validated(
            "DB name",
            lambda v: validate_non_empty(v, "DB name"),
            default="mysql",
        )

        ok, message = self._db.test_temp_table(
            DbCredentials(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
            )
        )
        if ok:
            print_ok(message)
        else:
            print_error(message)

    def _check_disk(self) -> None:
        print_header("Свободное место")
        import subprocess

        try:
            result = subprocess.run(
                ["df", "-hT", "/", "/var", "/tmp"],
                capture_output=True,
                text=True,
                check=False,
            )
            print(result.stdout or result.stderr)
            self._logger.info("df:\n%s", result.stdout or result.stderr)
        except OSError as exc:
            print_error(f"df недоступен: {exc}")
