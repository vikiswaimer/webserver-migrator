"""ANSI-цвета для консольного вывода."""

from __future__ import annotations


class Colors:
    """Набор ANSI escape-кодов."""

    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[1;31m"
    YELLOW = "\033[1;33m"
    GREEN = "\033[1;32m"
    CYAN = "\033[1;36m"
    MAGENTA = "\033[1;35m"
    WHITE = "\033[1;37m"


def colorize(text: str, color: str) -> str:
    """Обернуть текст цветом."""
    return f"{color}{text}{Colors.RESET}"


def print_ok(message: str) -> None:
    print(colorize(f"[OK] {message}", Colors.GREEN))


def print_warn(message: str) -> None:
    print(colorize(f"[WARN] {message}", Colors.YELLOW))


def print_error(message: str) -> None:
    print(colorize(f"[ERROR] {message}", Colors.RED))


def print_info(message: str) -> None:
    print(colorize(f"[INFO] {message}", Colors.CYAN))


def print_header(title: str) -> None:
    line = "=" * 70
    print()
    print(colorize(line, Colors.CYAN))
    print(colorize(f"  {title}", Colors.BOLD + Colors.CYAN))
    print(colorize(line, Colors.CYAN))
