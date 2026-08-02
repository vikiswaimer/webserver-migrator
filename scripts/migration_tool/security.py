"""Блок безопасности: подтверждение Snapshot перед опасными операциями."""

from __future__ import annotations

import logging
import sys

from .colors import Colors, colorize, print_error, print_ok

SNAPSHOT_WARNING = (
    "ВНИМАНИЕ! Перед продолжением ОБЯЗАТЕЛЬНО сделайте Snapshot "
    "(снимок системы) вашей виртуальной машины на стороне хостинга/облака! "
    "Разработчик не несет ответственности за потерю данных."
)

BANNER = f"""
{Colors.RED}{Colors.BOLD}
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║  ВНИМАНИЕ! Перед продолжением ОБЯЗАТЕЛЬНО сделайте Snapshot                  ║
║  (снимок системы) вашей виртуальной машины на стороне хостинга/облака!       ║
║  Разработчик не несет ответственности за потерю данных.                      ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
{Colors.RESET}"""


def require_snapshot_confirmation(logger: logging.Logger) -> None:
    """
    Вывести предупреждение и потребовать ввод YES.

    При отказе — немедленный выход с кодом 1.
    Факт предупреждения всегда пишется в лог.
    """
    print(BANNER)
    logger.warning("SNAPSHOT WARNING SHOWN: %s", SNAPSHOT_WARNING)
    logger.info("Ожидание подтверждения Snapshot (ожидается ввод: YES)")

    try:
        confirmation = input(
            colorize("Для продолжения введите YES (капсом): ", Colors.YELLOW)
        ).strip()
    except (EOFError, KeyboardInterrupt):
        logger.error("Ввод подтверждения Snapshot прерван пользователем")
        print_error("Ввод прерван. Завершение работы.")
        sys.exit(1)

    if confirmation != "YES":
        logger.error(
            "Snapshot confirmation DENIED (input=%r). Aborting.",
            confirmation,
        )
        print_error("Подтверждение не получено. Завершение работы.")
        sys.exit(1)

    logger.info("Snapshot confirmation ACCEPTED (YES)")
    print_ok("Подтверждение Snapshot получено (YES).")
