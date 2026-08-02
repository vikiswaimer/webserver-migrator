"""Режим 2: подготовка и экспорт данных (Push со старого сервера)."""

from __future__ import annotations

import logging
from pathlib import Path

from ..colors import print_error, print_header, print_info, print_ok, print_warn
from ..security import require_snapshot_confirmation
from ..services.docker_service import DockerService
from ..services.rsync_service import RsyncService
from ..validators import (
    ask_validated,
    validate_absolute_path,
    validate_host,
    validate_non_empty,
    validate_port,
)


class ExportMode:
    """Push-миграция: старый сервер → новый через rsync."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger
        self._docker = DockerService(logger)
        self._rsync = RsyncService(logger)

    def run(self) -> None:
        print_header("Режим 2: Подготовка и Экспорт данных (Push)")
        self._logger.info("Запущен режим экспорта (push)")

        require_snapshot_confirmation(self._logger)

        source = ask_validated(
            "Абсолютный путь источника на ЭТОМ (старом) сервере",
            lambda v: validate_absolute_path(v, must_exist=True),
        )
        remote_host = ask_validated("IP или hostname НОВОГО сервера", validate_host)
        remote_port = ask_validated("SSH-порт нового сервера", validate_port, default="22")
        remote_user = ask_validated(
            "SSH-пользователь на новом сервере",
            lambda v: validate_non_empty(v, "Пользователь"),
            default="root",
        )
        remote_dest = ask_validated(
            "Абсолютный путь назначения на НОВОМ сервере",
            lambda v: str(validate_absolute_path(v, must_exist=False)),
        )

        print_info(f"Источник (абсолютный путь): {source}")
        print_info(
            f"Назначение: {remote_user}@{remote_host}:{remote_port}:{remote_dest}"
        )
        self._logger.info(
            "Export paths: from=%s to=%s@%s:%s",
            source,
            remote_user,
            remote_host,
            remote_dest,
        )

        self._maybe_stop_docker()

        if not self._rsync.is_available():
            print_error("rsync не установлен на этой машине")
            return

        confirm = input("Запустить rsync push? Введите YES для подтверждения: ").strip()
        if confirm != "YES":
            print_warn("Экспорт отменён пользователем")
            self._logger.warning("Export aborted by user")
            return

        try:
            self._rsync.push(
                local_source=Path(source),
                remote_host=remote_host,
                remote_user=remote_user,
                remote_dest=remote_dest,
                ssh_port=remote_port,
            )
            print_ok("Экспорт завершён успешно")
        except (RuntimeError, FileNotFoundError, ValueError, OSError) as exc:
            print_error(f"Ошибка экспорта: {exc}")
            self._logger.exception("Export failed")

    def _maybe_stop_docker(self) -> None:
        if not self._docker.is_available() or not self._docker.daemon_reachable():
            print_info("Docker недоступен — остановка контейнеров пропущена")
            return

        containers = self._docker.list_running_containers()
        if not containers:
            print_info("Нет запущенных контейнеров")
            return

        print_warn("Обнаружены запущенные контейнеры:")
        for container in containers:
            print_info(f"  {container.name} ({container.container_id}) — {container.image}")

        answer = input(
            "Остановить контейнеры перед rsync (рекомендуется для целостности БД)? "
            "Введите YES: "
        ).strip()
        if answer != "YES":
            print_warn("Контейнеры оставлены запущенными")
            self._logger.warning("User declined container stop before export")
            return

        # Повторное предупреждение Snapshot уже было; остановка — опасная операция,
        # подтверждаем ещё раз явно через YES выше.
        try:
            ids = [c.container_id for c in containers]
            self._docker.stop_containers(ids)
            print_ok("Контейнеры остановлены")
        except RuntimeError as exc:
            print_error(f"Не удалось остановить контейнеры: {exc}")
            self._logger.exception("Failed to stop containers")
            proceed = input("Продолжить экспорт несмотря на ошибку? [y/N]: ").strip().lower()
            if proceed not in {"y", "yes", "д", "да"}:
                raise RuntimeError("Экспорт прерван из-за ошибки остановки Docker") from exc
