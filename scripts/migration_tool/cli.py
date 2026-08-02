"""Интерактивное главное меню миграционного комбайна."""

from __future__ import annotations

import logging
import sys
import traceback

from . import __version__
from .colors import Colors, colorize, print_error, print_header, print_info, print_ok
from .logging_setup import setup_logging
from .modes.export_mode import ExportMode
from .modes.import_mode import ImportMode
from .modes.local_audit import LocalAuditMode
from .modes.readiness import ReadinessMode


MENU = """
╔══════════════════════════════════════════════════════════════════╗
║          PHP / Nginx Migration Toolkit  v{version:<16}║
╠══════════════════════════════════════════════════════════════════╣
║  1. Локальный аудит окружения и сайтов (старый сервер)           ║
║  2. Подготовка и Экспорт данных (Push со старого сервера)        ║
║  3. Подключение и Импорт данных (Pull на новом сервере)          ║
║  4. Проверка готовности нового сервера (Standalone)              ║
║  5. Выход                                                        ║
╚══════════════════════════════════════════════════════════════════╝
""".format(version=__version__)


class MigrationCLI:
    """Точка входа интерактивного комбайна."""

    def __init__(self) -> None:
        self._logger: logging.Logger
        self._log_path = None

    def run(self) -> int:
        self._logger, self._log_path = setup_logging()
        self._logger.info("Migration toolkit v%s started", __version__)
        self._logger.info("Лог скрипта (абсолютный путь): %s", self._log_path)
        print_ok(f"Лог скрипта: {self._log_path}")

        # Фиксируем предупреждение о snapshot в начале лога (информационно).
        # Принудительный YES запрашивается в режимах 2 и 3 перед опасными действиями.
        self._logger.warning(
            "REMINDER: Перед опасными операциями (rsync, остановка контейнеров) "
            "будет запрошено подтверждение Snapshot (ввод YES)."
        )

        while True:
            print(colorize(MENU, Colors.CYAN))
            print_info(f"Текущий лог: {self._log_path}")
            try:
                choice = input("Выберите режим [1-5]: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                print_info("Выход по прерыванию ввода")
                self._logger.info("Exit via keyboard interrupt")
                return 0

            if choice == "1":
                self._safe_run("local_audit", LocalAuditMode(self._logger).run)
            elif choice == "2":
                self._safe_run("export", ExportMode(self._logger).run)
            elif choice == "3":
                self._safe_run("import", ImportMode(self._logger).run)
            elif choice == "4":
                self._safe_run("readiness", ReadinessMode(self._logger).run)
            elif choice == "5":
                print_header("Выход")
                print_ok(f"Лог сохранён: {self._log_path}")
                self._logger.info("User exited (mode 5)")
                return 0
            else:
                print_error("Некорректный выбор. Введите число от 1 до 5.")

    def _safe_run(self, mode_name: str, callback) -> None:
        self._logger.info("Entering mode: %s", mode_name)
        try:
            callback()
        except SystemExit:
            raise
        except RuntimeError as exc:
            print_error(str(exc))
            self._logger.error("Mode %s runtime error: %s", mode_name, exc)
        except Exception as exc:  # noqa: BLE001 — верхний уровень CLI
            print_error(f"Неожиданная ошибка в режиме {mode_name}: {exc}")
            self._logger.error(
                "Mode %s failed: %s\n%s",
                mode_name,
                exc,
                traceback.format_exc(),
            )
        finally:
            print_info(f"Лог скрипта: {self._log_path}")


def main(argv: list[str] | None = None) -> int:
    """Entry-point для console_scripts / python -m."""
    _ = argv  # зарезервировано под будущие флаги CLI
    try:
        return MigrationCLI().run()
    except SystemExit as exc:
        return int(exc.code or 0)
    except Exception as exc:  # noqa: BLE001
        print(f"[FATAL] {exc}", file=sys.stderr)
        return 1
