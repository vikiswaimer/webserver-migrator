"""Локальные тесты доступности БД (MySQL/MariaDB)."""

from __future__ import annotations

import logging
import shutil
import subprocess
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class DbCredentials:
    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "root"
    password: str = ""
    database: str = "mysql"


class DatabaseService:
    """Проверка возможности CREATE/DROP временной таблицы."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def mysql_client_available(self) -> bool:
        return shutil.which("mysql") is not None

    def test_temp_table(self, credentials: DbCredentials) -> tuple[bool, str]:
        """
        Создать и удалить временную таблицу.

        Returns:
            (успех, сообщение)
        """
        if not self.mysql_client_available():
            return False, "Клиент mysql не найден в PATH"

        table_name = f"migrator_probe_{uuid.uuid4().hex[:10]}"
        sql = (
            f"CREATE TABLE `{table_name}` (id INT PRIMARY KEY); "
            f"DROP TABLE `{table_name}`;"
        )
        command = [
            "mysql",
            "-h",
            credentials.host,
            "-P",
            str(credentials.port),
            "-u",
            credentials.user,
            credentials.database,
            "-e",
            sql,
        ]

        env_password = credentials.password
        self._logger.info(
            "Тест БД: host=%s port=%s user=%s database=%s table=%s",
            credentials.host,
            credentials.port,
            credentials.user,
            credentials.database,
            table_name,
        )

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                env=self._build_env(env_password),
            )
        except OSError as exc:
            return False, f"Ошибка запуска mysql: {exc}"

        if result.returncode != 0:
            err = (result.stderr or result.stdout or "unknown error").strip()
            self._logger.error("Тест БД неуспешен: %s", err)
            return False, err

        msg = f"Временная таблица {table_name} создана и удалена успешно"
        self._logger.info(msg)
        return True, msg

    def _build_env(self, password: str) -> dict[str, str]:
        import os

        env = os.environ.copy()
        if password:
            env["MYSQL_PWD"] = password
        return env
