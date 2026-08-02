"""SSH-проверки через paramiko."""

from __future__ import annotations

import logging
from dataclasses import dataclass

try:
    import paramiko
except ImportError:  # pragma: no cover - зависимость ставится отдельно
    paramiko = None  # type: ignore


@dataclass(frozen=True)
class SshConfig:
    host: str
    port: int
    username: str
    password: str | None = None
    key_filename: str | None = None


class SshService:
    """Проверка связи, удалённых утилит и свободного места."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def ensure_paramiko(self) -> None:
        if paramiko is None:
            raise RuntimeError(
                "Модуль paramiko не установлен. "
                "Установите зависимости: pip install -r requirements.txt"
            )

    def connect(self, config: SshConfig) -> "paramiko.SSHClient":
        self.ensure_paramiko()
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._logger.info(
            "SSH подключение к %s@%s:%s",
            config.username,
            config.host,
            config.port,
        )
        try:
            client.connect(
                hostname=config.host,
                port=config.port,
                username=config.username,
                password=config.password,
                key_filename=config.key_filename,
                timeout=20,
                allow_agent=True,
                look_for_keys=True,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Не удалось подключиться по SSH к {config.host}:{config.port}: {exc}"
            ) from exc
        return client

    def test_connection(self, config: SshConfig) -> dict[str, str]:
        client = self.connect(config)
        try:
            uname = self._exec(client, "uname -a")
            rsync_path = self._exec(client, "command -v rsync || true")
            df_output = self._exec(client, "df -h / /tmp 2>/dev/null || df -h")
            return {
                "uname": uname.strip(),
                "rsync": rsync_path.strip() or "НЕ НАЙДЕН",
                "disk": df_output.strip(),
            }
        finally:
            client.close()

    def remote_path_exists(self, config: SshConfig, remote_path: str) -> bool:
        client = self.connect(config)
        try:
            output = self._exec(
                client,
                f'test -e "{remote_path}" && echo EXISTS || echo MISSING',
            )
            return "EXISTS" in output
        finally:
            client.close()

    def _exec(self, client: "paramiko.SSHClient", command: str) -> str:
        self._logger.debug("REMOTE CMD: %s", command)
        _stdin, stdout, stderr = client.exec_command(command, timeout=60)
        exit_status = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="ignore")
        err = stderr.read().decode("utf-8", errors="ignore")
        if exit_status != 0 and not out:
            self._logger.debug("REMOTE STDERR: %s", err.strip())
        return out
