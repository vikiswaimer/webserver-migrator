"""Валидация пользовательского ввода: IP, хосты, порты, пути."""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path


HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
    r"(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$"
)


def validate_host(value: str) -> str:
    """Проверить IP или hostname. Вернуть очищенное значение."""
    host = value.strip()
    if not host:
        raise ValueError("Хост не может быть пустым")

    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass

    if HOSTNAME_RE.match(host):
        return host

    raise ValueError(f"Некорректный хост или IP: {host!r}")


def validate_port(value: str | int) -> int:
    """Проверить TCP-порт (1–65535)."""
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Порт должен быть числом: {value!r}") from exc

    if not 1 <= port <= 65535:
        raise ValueError(f"Порт вне диапазона 1–65535: {port}")
    return port


def validate_absolute_path(value: str, must_exist: bool = False) -> Path:
    """Проверить, что путь абсолютный; опционально — существует."""
    raw = value.strip()
    if not raw:
        raise ValueError("Путь не может быть пустым")

    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError(f"Требуется абсолютный путь, получено: {raw!r}")

    resolved = path.resolve() if path.exists() else path
    if must_exist and not resolved.exists():
        raise ValueError(f"Путь не существует: {resolved}")
    return resolved


def validate_non_empty(value: str, field_name: str = "Значение") -> str:
    """Проверить непустую строку."""
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} не может быть пустым")
    return cleaned


def ask_validated(prompt: str, validator, default: str | None = None):
    """
    Запросить ввод до успешной валидации.

    validator — callable(str) -> Any, бросает ValueError при ошибке.
    """
    while True:
        suffix = f" [{default}]" if default is not None else ""
        try:
            raw = input(f"{prompt}{suffix}: ").strip()
        except (EOFError, KeyboardInterrupt) as exc:
            raise RuntimeError("Ввод прерван пользователем") from exc

        if not raw and default is not None:
            raw = default

        try:
            return validator(raw)
        except ValueError as exc:
            print(f"  Ошибка валидации: {exc}")
