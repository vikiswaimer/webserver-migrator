"""Режим 1: локальный аудит окружения и сайтов (старый сервер)."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from ..colors import print_error, print_header, print_info, print_ok, print_warn
from ..services.cms_service import CmsService
from ..services.docker_service import DockerService
from ..services.nginx_service import NginxService
from ..services.php_service import PhpService
from ..validators import ask_validated, validate_absolute_path


class LocalAuditMode:
    """Глубокий локальный аудит без изменения системы."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._docker = DockerService(logger)
        self._nginx = NginxService(logger)
        self._php = PhpService(logger)
        self._cms = CmsService(logger)

    def run(self) -> None:
        print_header("Режим 1: Локальный аудит окружения и сайтов")
        self._logger.info("Запущен режим локального аудита")

        self._audit_environment()
        self._audit_nginx_logs()
        self._audit_sites_and_compose()
        self._audit_cms()
        self._maybe_deep_scan()

        print_ok("Локальный аудит завершён")

    def _audit_environment(self) -> None:
        print_header("Окружение")
        if self._docker.is_available() and self._docker.daemon_reachable():
            print_ok(f"Docker доступен: {shutil.which('docker')}")
            containers = self._docker.list_running_containers()
            if not containers:
                print_info("Запущенных контейнеров нет")
            for container in containers:
                print_info(
                    f"Контейнер: {container.name} | образ={container.image} "
                    f"| статус={container.status} | id={container.container_id}"
                )
                for mount in container.mounts:
                    print_info(
                        f"  volume: type={mount['type']} "
                        f"src={mount['source']} dst={mount['destination']}"
                    )
        else:
            print_info("Docker недоступен — режим bare-metal / без контейнеров")

        if self._nginx.is_available():
            print_ok(f"Nginx: {shutil.which('nginx')}")
            print_info(self._nginx.version_info())
        else:
            print_info("Nginx не найден в PATH")

        if self._php.is_available():
            print_ok(f"PHP: {shutil.which('php')} → {self._php.version()}")
            modules = self._php.modules()
            print_info(f"Расширений PHP: {len(modules)}")
            self._logger.debug("PHP modules: %s", ", ".join(modules))
        else:
            print_info("PHP CLI не найден в PATH")

        self._disk_space()

    def _disk_space(self) -> None:
        print_header("Свободное место")
        try:
            import subprocess

            result = subprocess.run(
                ["df", "-hT", "/", "/var", "/tmp"],
                capture_output=True,
                text=True,
                check=False,
            )
            output = result.stdout or result.stderr
            print(output)
            self._logger.info("df output:\n%s", output)
        except OSError as exc:
            print_error(f"Не удалось выполнить df: {exc}")

    def _audit_nginx_logs(self) -> None:
        print_header("Пути логов Nginx (access_log / error_log)")
        log_paths = self._nginx.extract_log_paths()
        if not log_paths:
            print_info("Директивы логов в конфигах не найдены")
            return

        for item in log_paths:
            print_info(f"Директива: {item.directive}")
            print_info(f"  Файл лога:      {item.log_file}")
            print_info(f"  Каталог лога:   {item.log_dir}")
            print_info(f"  Источник:       {item.source_config}")
            if item.directory_exists:
                print_ok(f"Каталог существует: {item.log_dir}")
            else:
                print_warn(
                    f"Каталог НЕ существует: {item.log_dir}. "
                    f"Рекомендуется: sudo mkdir -p {item.log_dir}"
                )

    def _audit_sites_and_compose(self) -> None:
        print_header("Сайты и docker-compose")
        www = Path("/var/www")
        print_info(f"Проверяемый корень сайтов: {www.resolve() if www.exists() else www}")
        if www.is_dir():
            for child in sorted(www.iterdir()):
                print_info(f"  {child.resolve()}")
        else:
            print_warn(f"Каталог отсутствует: {www}")

        compose_files = self._docker.find_compose_files(www) if www.is_dir() else []
        # Дополнительно — текущий каталог пользователя /opt
        for extra in (Path("/opt"), Path.cwd()):
            if extra.is_dir():
                compose_files.extend(self._docker.find_compose_files(extra))

        unique = sorted(set(compose_files))
        if not unique:
            print_info("Файлы docker-compose не найдены")
        for compose in unique:
            print_ok(f"compose: {compose}")

    def _audit_cms(self) -> None:
        print_header("Определение CMS и параметры БД")
        findings = self._cms.scan_www(Path("/var/www"))
        if not findings:
            print_info("Известные CMS в /var/www не обнаружены")
            return

        for item in findings:
            print_ok(f"{item.cms_name} → {item.root}")
            for evidence in item.evidence_files:
                print_info(f"  evidence: {evidence.resolve()}")
            if item.db_params:
                # Пароль маскируем в консоли, в лог пишем факт наличия
                safe = {
                    key: ("***" if key == "password" else value)
                    for key, value in item.db_params.items()
                }
                print_info(f"  DB params: {safe}")
                self._logger.info(
                    "DB params for %s source=%s keys=%s",
                    item.root,
                    item.db_params.get("source"),
                    sorted(k for k in item.db_params if k != "password"),
                )

    def _maybe_deep_scan(self) -> None:
        print_header("Deep Scan PHP (устаревшие функции)")
        answer = input(
            "Запустить глубокое сканирование PHP на mysql_* и др.? [y/N]: "
        ).strip().lower()
        if answer not in {"y", "yes", "д", "да"}:
            print_info("Deep Scan пропущен")
            return

        root = ask_validated(
            "Абсолютный путь к корню сайта для сканирования",
            lambda v: validate_absolute_path(v, must_exist=True),
            default="/var/www",
        )
        print_info(f"Сканирование: {root}")
        hits = self._php.deep_scan(root)
        if not hits:
            print_ok("Устаревшие функции не найдены")
            return

        print_warn(f"Найдено совпадений: {len(hits)}")
        for hit in hits[:100]:
            print_warn(
                f"{hit.file_path}:{hit.line_number} "
                f"[{hit.function_name}] {hit.line_text}"
            )
        if len(hits) > 100:
            print_info(f"... и ещё {len(hits) - 100} (см. лог)")
            for hit in hits[100:]:
                self._logger.warning(
                    "%s:%s [%s] %s",
                    hit.file_path,
                    hit.line_number,
                    hit.function_name,
                    hit.line_text,
                )
