"""Режим 3: подключение и импорт данных (Pull на новом сервере)."""

from __future__ import annotations

import getpass
import logging
from pathlib import Path

from ..colors import print_error, print_header, print_info, print_ok, print_warn
from ..security import require_snapshot_confirmation
from ..services.database_service import DatabaseService, DbCredentials
from ..services.nginx_service import NginxService
from ..services.rsync_service import RsyncService
from ..services.ssh_service import SshConfig, SshService
from ..validators import (
    ask_validated,
    validate_absolute_path,
    validate_host,
    validate_non_empty,
    validate_port,
)


class ImportMode:
    """Pull-миграция: новый сервер забирает данные со старого."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._ssh = SshService(logger)
        self._rsync = RsyncService(logger)
        self._nginx = NginxService(logger)
        self._db = DatabaseService(logger)

    def run(self) -> None:
        print_header("Режим 3: Подключение и Импорт данных (Pull)")
        self._logger.info("Запущен режим импорта (pull)")

        require_snapshot_confirmation(self._logger)

        remote_host = ask_validated("IP или hostname СТАРОГО сервера", validate_host)
        remote_port = ask_validated("SSH-порт старого сервера", validate_port, default="22")
        remote_user = ask_validated(
            "SSH-пользователь на старом сервере",
            lambda v: validate_non_empty(v, "Пользователь"),
            default="root",
        )
        auth_mode = input(
            "Аутентификация: 1=SSH-ключ (по умолчанию), 2=пароль [1/2]: "
        ).strip() or "1"

        password: str | None = None
        key_filename: str | None = None
        if auth_mode == "2":
            password = getpass.getpass("SSH-пароль: ")
        else:
            key_raw = input(
                "Путь к приватному ключу (Enter = агент/default): "
            ).strip()
            if key_raw:
                key_filename = str(
                    validate_absolute_path(key_raw, must_exist=True)
                )

        remote_source = ask_validated(
            "Абсолютный путь сайта/volume на СТАРОМ сервере",
            lambda v: str(validate_absolute_path(v, must_exist=False)),
        )
        local_dest = ask_validated(
            "Абсолютный путь назначения на ЭТОМ (новом) сервере",
            lambda v: validate_absolute_path(v, must_exist=False),
            default="/var/www/migration_import",
        )

        print_info(
            f"Откуда: {remote_user}@{remote_host}:{remote_port}:{remote_source}"
        )
        print_info(f"Куда (абсолютный путь): {local_dest}")

        ssh_config = SshConfig(
            host=remote_host,
            port=remote_port,
            username=remote_user,
            password=password,
            key_filename=key_filename,
        )

        if not self._check_ssh(ssh_config, remote_source):
            return

        if not self._rsync.is_available():
            print_error("rsync не установлен на этой машине")
            return

        confirm = input("Запустить rsync pull? Введите YES: ").strip()
        if confirm != "YES":
            print_warn("Импорт отменён пользователем")
            return

        try:
            self._rsync.pull(
                remote_host=remote_host,
                remote_user=remote_user,
                remote_source=remote_source,
                local_dest=Path(local_dest),
                ssh_port=remote_port,
            )
            print_ok("Файлы успешно скачаны")
        except (RuntimeError, ValueError, OSError) as exc:
            print_error(f"Ошибка rsync pull: {exc}")
            self._logger.exception("Pull failed")
            return

        self._analyze_imported_nginx_logs(Path(local_dest))
        self._local_db_probe()

        print_ok("Импорт и пост-проверки завершены")

    def _check_ssh(self, config: SshConfig, remote_source: str) -> bool:
        print_header("Проверка SSH / rsync / диска на старом сервере")
        try:
            info = self._ssh.test_connection(config)
        except RuntimeError as exc:
            print_error(str(exc))
            self._logger.exception("SSH test failed")
            return False

        print_ok(f"uname: {info['uname']}")
        if info["rsync"] == "НЕ НАЙДЕН":
            print_error("На удалённом сервере rsync не найден")
            return False
        print_ok(f"Удалённый rsync: {info['rsync']}")
        print_info("Свободное место на удалённом сервере:")
        print(info["disk"])
        self._logger.info("Remote disk:\n%s", info["disk"])

        try:
            exists = self._ssh.remote_path_exists(config, remote_source)
        except RuntimeError as exc:
            print_error(str(exc))
            return False

        if not exists:
            print_error(f"Удалённый путь не существует: {remote_source}")
            return False
        print_ok(f"Удалённый путь существует: {remote_source}")
        return True

    def _analyze_imported_nginx_logs(self, import_root: Path) -> None:
        print_header("Анализ путей логов в скачанных конфигах Nginx")
        configs = self._nginx.discover_config_files(extra_roots=[import_root])
        # Плюс прямые совпадения внутри импорта
        for pattern in ("*.conf", "nginx.conf", "default.conf"):
            configs.extend(p.resolve() for p in import_root.rglob(pattern) if p.is_file())

        unique_configs = sorted(set(configs))
        print_info(f"Конфигов к анализу: {len(unique_configs)}")
        for conf in unique_configs:
            print_info(f"  config: {conf}")

        log_paths = self._nginx.extract_log_paths(unique_configs)
        if not log_paths:
            print_info("Директивы access_log/error_log не найдены в импорте")
            return

        missing = 0
        for item in log_paths:
            print_info(f"{item.directive}: файл={item.log_file}")
            print_info(f"  каталог={item.log_dir} | источник={item.source_config}")
            if item.directory_exists:
                print_ok(f"Каталог на НОВОМ сервере существует: {item.log_dir}")
            else:
                missing += 1
                print_warn(
                    f"Каталог на НОВОМ сервере ОТСУТСТВУЕТ: {item.log_dir}. "
                    f"Создайте вручную: sudo mkdir -p {item.log_dir} "
                    "&& sudo chown www-data:www-data "
                    f"{item.log_dir}"
                )

        if missing:
            print_warn(
                f"Отсутствующих каталогов логов: {missing}. "
                "Иначе Nginx выдаст ошибку конфигурации при старте."
            )
        else:
            print_ok("Все каталоги логов из импортированных конфигов существуют")

    def _local_db_probe(self) -> None:
        print_header("Локальный тест импорта БД (временная таблица)")
        answer = input("Выполнить тест CREATE/DROP таблицы в локальной БД? [y/N]: ").strip().lower()
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
            print_error(f"Тест БД неуспешен: {message}")
