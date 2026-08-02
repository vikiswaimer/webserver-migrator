"""Обёртка над rsync для push/pull миграции."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path


class RsyncService:
    """Запуск rsync с явным выводом абсолютных путей."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def is_available(self) -> bool:
        return shutil.which("rsync") is not None

    def push(
        self,
        local_source: Path,
        remote_host: str,
        remote_user: str,
        remote_dest: str,
        ssh_port: int = 22,
        extra_args: list[str] | None = None,
    ) -> None:
        """Отправка данных со старого сервера на новый (Push)."""
        source = self._normalize_source(local_source)
        dest = f"{remote_user}@{remote_host}:{remote_dest}"
        self._logger.info("RSYNC PUSH")
        self._logger.info("  Откуда (абсолютный путь): %s", source)
        self._logger.info("  Куда:                     %s", dest)
        self._run(source, dest, ssh_port, extra_args)

    def pull(
        self,
        remote_host: str,
        remote_user: str,
        remote_source: str,
        local_dest: Path,
        ssh_port: int = 22,
        extra_args: list[str] | None = None,
    ) -> None:
        """Скачивание данных со старого сервера на новый (Pull)."""
        local_dest = Path(local_dest)
        if not local_dest.is_absolute():
            raise ValueError(
                f"Локальный путь назначения должен быть абсолютным: {local_dest}"
            )
        local_dest.mkdir(parents=True, exist_ok=True)

        source = f"{remote_user}@{remote_host}:{remote_source}"
        if not source.endswith("/"):
            # Копируем содержимое каталога, если путь — директория
            source = source.rstrip("/") + "/"

        dest = str(local_dest.resolve()) + "/"
        self._logger.info("RSYNC PULL")
        self._logger.info("  Откуда:                   %s", source)
        self._logger.info("  Куда (абсолютный путь):   %s", dest)
        self._run(source, dest, ssh_port, extra_args)

    def _normalize_source(self, local_source: Path) -> str:
        path = Path(local_source)
        if not path.is_absolute():
            raise ValueError(f"Исходный путь должен быть абсолютным: {path}")
        if not path.exists():
            raise FileNotFoundError(f"Исходный путь не существует: {path}")
        resolved = path.resolve()
        # Трейлинг-слеш копирует содержимое каталога
        return str(resolved) + ("/" if resolved.is_dir() else "")

    def _run(
        self,
        source: str,
        dest: str,
        ssh_port: int,
        extra_args: list[str] | None,
    ) -> None:
        if not self.is_available():
            raise RuntimeError(
                "rsync не найден. Установите: sudo apt-get install -y rsync"
            )

        command = [
            "rsync",
            "-aH",
            "--info=progress2",
            "-e",
            f"ssh -p {ssh_port} -o StrictHostKeyChecking=accept-new",
        ]
        if extra_args:
            command.extend(extra_args)
        command.extend([source, dest])

        self._logger.info("Команда: %s", " ".join(command))
        try:
            result = subprocess.run(command, check=False)
        except OSError as exc:
            raise RuntimeError(f"Не удалось запустить rsync: {exc}") from exc

        if result.returncode != 0:
            raise RuntimeError(
                f"rsync завершился с кодом {result.returncode}. "
                "Проверьте SSH-доступ, пути и свободное место."
            )
        self._logger.info("rsync успешно завершён")
