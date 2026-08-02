#!/usr/bin/env python3
"""
migration_toolkit.py — один файл для аудита и миграции PHP/Nginx-сайтов.

Загрузка на ВМ и запуск:
    python3 migration_toolkit.py
    # или: pip3 install paramiko && python3 migration_toolkit.py

Требования безопасности:
    - Snapshot + подтверждение YES перед опасными действиями
    - Лог в /tmp/migration_process_[дата]_[время].log
    - Абсолютные пути в консоли и логе
    - Проверка каталогов access_log / error_log Nginx
"""

from __future__ import annotations

import getpass
import ipaddress
import logging
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

try:
    import paramiko
except ImportError:
    paramiko = None  # type: ignore


# =============================================================================
# Константы и цвета
# =============================================================================

VERSION = "1.1.0"

COLOR_RESET = "\033[0m"
COLOR_BOLD = "\033[1m"
COLOR_RED = "\033[1;31m"
COLOR_YELLOW = "\033[1;33m"
COLOR_GREEN = "\033[1;32m"
COLOR_CYAN = "\033[1;36m"

SNAPSHOT_TEXT = (
    "ВНИМАНИЕ! Перед продолжением ОБЯЗАТЕЛЬНО сделайте Snapshot "
    "(снимок системы) вашей виртуальной машины на стороне хостинга/облака! "
    "Разработчик не несет ответственности за потерю данных."
)

SNAPSHOT_BANNER = f"""
{COLOR_RED}{COLOR_BOLD}
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║  ВНИМАНИЕ! Перед продолжением ОБЯЗАТЕЛЬНО сделайте Snapshot                  ║
║  (снимок системы) вашей виртуальной машины на стороне хостинга/облака!       ║
║  Разработчик не несет ответственности за потерю данных.                      ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
{COLOR_RESET}"""

DEPRECATED_PHP = (
    "mysql_connect",
    "mysql_query",
    "mysql_select_db",
    "mysql_fetch_array",
    "mysql_real_escape_string",
    "create_function",
    "each",
)

COMMON_PHP_MODULES = (
    "curl",
    "gd",
    "intl",
    "json",
    "mbstring",
    "mysqli",
    "openssl",
    "pdo_mysql",
    "xml",
    "zip",
)

NGINX_LOG_RE = re.compile(
    r"^\s*(access_log|error_log)\s+(\S+)",
    re.IGNORECASE | re.MULTILINE,
)

DB_PATTERNS = {
    "db_name": [
        r"define\s*\(\s*['\"]DB_NAME['\"]\s*,\s*['\"]([^'\"]+)['\"]",
        r"['\"]database['\"]\s*=>\s*['\"]([^'\"]+)['\"]",
        r"['\"]dbname['\"]\s*=>\s*['\"]([^'\"]+)['\"]",
        r"public\s+\$db\s*=\s*['\"]([^'\"]+)['\"]",
        r"^\s*DB_DATABASE\s*=\s*(.+)$",
        r"\$DBName\s*=\s*['\"]([^'\"]+)['\"]",
    ],
    "db_user": [
        r"define\s*\(\s*['\"]DB_USER['\"]\s*,\s*['\"]([^'\"]+)['\"]",
        r"['\"]login['\"]\s*=>\s*['\"]([^'\"]+)['\"]",
        r"['\"]user['\"]\s*=>\s*['\"]([^'\"]+)['\"]",
        r"public\s+\$user\s*=\s*['\"]([^'\"]+)['\"]",
        r"^\s*DB_USERNAME\s*=\s*(.+)$",
        r"\$DBLogin\s*=\s*['\"]([^'\"]+)['\"]",
    ],
    "db_pass": [
        r"define\s*\(\s*['\"]DB_PASSWORD['\"]\s*,\s*['\"]([^'\"]*)['\"]",
        r"['\"]password['\"]\s*=>\s*['\"]([^'\"]*)['\"]",
        r"public\s+\$password\s*=\s*['\"]([^'\"]*)['\"]",
        r"^\s*DB_PASSWORD\s*=\s*(.*)$",
        r"\$DBPassword\s*=\s*['\"]([^'\"]*)['\"]",
    ],
    "db_host": [
        r"define\s*\(\s*['\"]DB_HOST['\"]\s*,\s*['\"]([^'\"]+)['\"]",
        r"['\"]host['\"]\s*=>\s*['\"]([^'\"]+)['\"]",
        r"public\s+\$host\s*=\s*['\"]([^'\"]+)['\"]",
        r"^\s*DB_HOST\s*=\s*(.+)$",
        r"\$DBHost\s*=\s*['\"]([^'\"]+)['\"]",
    ],
}

CONFIG_FILENAMES = {
    "wp-config.php",
    "configuration.php",
    ".env",
    "config.php",
    ".settings.php",
    "dbconn.php",
}


# =============================================================================
# Вывод и логирование
# =============================================================================

LOGGER = logging.getLogger("migration_toolkit")
LOG_PATH: Optional[Path] = None


def color(text: str, code: str) -> str:
    return f"{code}{text}{COLOR_RESET}"


def print_ok(message: str) -> None:
    print(color(f"[OK] {message}", COLOR_GREEN))
    LOGGER.info(message)


def print_warn(message: str) -> None:
    print(color(f"[WARN] {message}", COLOR_YELLOW))
    LOGGER.warning(message)


def print_error(message: str) -> None:
    print(color(f"[ERROR] {message}", COLOR_RED))
    LOGGER.error(message)


def print_info(message: str) -> None:
    print(color(f"[INFO] {message}", COLOR_CYAN))
    LOGGER.info(message)


def print_header(title: str) -> None:
    line = "=" * 64
    print()
    print(color(line, COLOR_CYAN))
    print(color(f"  {title}", COLOR_BOLD + COLOR_CYAN))
    print(color(line, COLOR_CYAN))
    LOGGER.info("=== %s ===", title)


def setup_logging() -> Path:
    """Инициализация лога в /tmp/ + дублирование важных сообщений в консоль."""
    global LOG_PATH
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_path = Path(f"/tmp/migration_process_{stamp}.log").resolve()

    LOGGER.setLevel(logging.DEBUG)
    LOGGER.handlers.clear()
    LOGGER.propagate = False

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    LOGGER.addHandler(file_handler)

    LOG_PATH = log_path
    LOGGER.info("Лог скрипта: %s", log_path)
    LOGGER.warning("SNAPSHOT REMINDER: %s", SNAPSHOT_TEXT)
    return log_path


def clear_screen() -> None:
    os.system("clear" if os.name != "nt" else "cls")


# =============================================================================
# Безопасность и валидация
# =============================================================================

def require_snapshot_confirmation() -> None:
    """Блок Snapshot: без ввода YES скрипт завершает работу."""
    print(SNAPSHOT_BANNER)
    LOGGER.warning("SNAPSHOT WARNING SHOWN: %s", SNAPSHOT_TEXT)
    if LOG_PATH:
        print_info(f"Факт предупреждения зафиксирован в логе: {LOG_PATH}")

    try:
        answer = input(
            color("Для продолжения введите YES (капсом): ", COLOR_YELLOW)
        ).strip()
    except (EOFError, KeyboardInterrupt):
        print_error("Ввод прерван. Завершение работы.")
        sys.exit(1)

    if answer != "YES":
        LOGGER.error("Snapshot confirmation DENIED (input=%r)", answer)
        print_error("Подтверждение не получено. Завершение работы.")
        sys.exit(1)

    LOGGER.info("Snapshot confirmation ACCEPTED")
    print_ok("Подтверждение Snapshot получено (YES).")


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        value = input(f"{prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt) as exc:
        raise RuntimeError("Ввод прерван пользователем") from exc
    return value if value else default


def ask_yes(prompt: str) -> bool:
    return ask(f"{prompt} [y/N]", "n").lower() in {"y", "yes", "д", "да"}


def validate_host(value: str) -> str:
    host = value.strip()
    if not host:
        raise ValueError("Хост не может быть пустым")
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    if re.fullmatch(
        r"(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
        r"(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*",
        host,
    ):
        return host
    raise ValueError(f"Некорректный хост/IP: {host!r}")


def validate_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise ValueError(f"Порт должен быть числом: {value!r}") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"Порт вне диапазона 1–65535: {port}")
    return port


def validate_abs_path(value: str, must_exist: bool = False) -> Path:
    raw = value.strip()
    if not raw:
        raise ValueError("Путь не может быть пустым")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError(f"Нужен абсолютный путь, получено: {raw!r}")
    resolved = path.resolve() if path.exists() else path
    if must_exist and not resolved.exists():
        raise ValueError(f"Путь не существует: {resolved}")
    return resolved


def ask_validated(
    prompt: str,
    validator: Callable[[str], object],
    default: str = "",
):
    while True:
        raw = ask(prompt, default)
        try:
            return validator(raw)
        except ValueError as exc:
            print_error(str(exc))


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def abs_path_str(path: Path | str) -> str:
    path_obj = Path(path).expanduser()
    if path_obj.exists():
        return str(path_obj.resolve())
    return str(path_obj if path_obj.is_absolute() else Path.cwd() / path_obj)


# =============================================================================
# Системные проверки
# =============================================================================

def show_disk_space(target: str = "/") -> None:
    print_header("Свободное место на диске")
    try:
        result = subprocess.run(
            ["df", "-hT", target, "/var", "/tmp"],
            capture_output=True,
            text=True,
            check=False,
        )
        output = (result.stdout or result.stderr).strip()
        print(output)
        LOGGER.debug("df:\n%s", output)
    except OSError as exc:
        print_error(f"Не удалось выполнить df: {exc}")


def check_local_tools() -> None:
    print_header("Локальные утилиты")
    for name in ("rsync", "ssh", "nginx", "php", "mysql", "mysqldump", "docker"):
        path = shutil.which(name)
        if path:
            print_ok(f"{name}: {abs_path_str(path)}")
        else:
            print_warn(f"{name}: не найден в PATH")


def docker_available() -> bool:
    if not command_exists("docker"):
        return False
    result = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def list_docker_containers() -> list[dict[str, str]]:
    if not docker_available():
        return []
    result = subprocess.run(
        ["docker", "ps", "--format", "{{.ID}}\t{{.Names}}\t{{.Image}}\t{{.Status}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    containers: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        container_id, name, image, status = parts[:4]
        mounts_result = subprocess.run(
            [
                "docker",
                "inspect",
                "-f",
                "{{range .Mounts}}{{.Type}}|{{.Source}}|{{.Destination}};{{end}}",
                container_id,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        mounts: list[str] = []
        for item in mounts_result.stdout.strip().split(";"):
            if not item:
                continue
            m_type, src, dst = (item.split("|") + ["", "", ""])[:3]
            mounts.append(f"type={m_type} src={abs_path_str(src) if src else '-'} dst={dst}")
        containers.append(
            {
                "id": container_id,
                "name": name,
                "image": image,
                "status": status,
                "mounts": " || ".join(mounts),
            }
        )
    return containers


def maybe_stop_docker_containers() -> None:
    containers = list_docker_containers()
    if not containers:
        print_info("Запущенных Docker-контейнеров нет (или Docker недоступен).")
        return

    print_header("Запущенные Docker-контейнеры")
    for item in containers:
        print_info(
            f"{item['name']} | {item['image']} | {item['status']} | id={item['id']}"
        )
        if item["mounts"]:
            print_info(f"  volumes: {item['mounts']}")

    print_warn(
        "Перед rsync рекомендуется остановить контейнеры, "
        "чтобы не повредить файлы БД."
    )
    answer = ask("Остановить все запущенные контейнеры? Введите YES", "")
    if answer != "YES":
        print_warn("Контейнеры оставлены запущенными.")
        return

    ids = [item["id"] for item in containers]
    LOGGER.warning("Stopping containers: %s", ", ".join(ids))
    result = subprocess.run(
        ["docker", "stop", *ids],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        print_ok("Контейнеры остановлены.")
    else:
        print_error(f"Не удалось остановить контейнеры: {result.stderr.strip()}")


# =============================================================================
# Nginx: логи и конфиги
# =============================================================================

def discover_nginx_configs(extra_roots: Optional[list[Path]] = None) -> list[Path]:
    files: list[Path] = []
    main_conf = Path("/etc/nginx/nginx.conf")
    if main_conf.is_file():
        files.append(main_conf.resolve())

    for directory in (
        Path("/etc/nginx/sites-enabled"),
        Path("/etc/nginx/conf.d"),
        Path("/etc/nginx/sites-available"),
    ):
        if not directory.is_dir():
            continue
        for item in sorted(directory.iterdir()):
            if item.is_file() or item.is_symlink():
                try:
                    files.append(item.resolve())
                except OSError:
                    files.append(item.absolute())

    for root in extra_roots or []:
        if not root.is_dir():
            continue
        for pattern in ("*.conf", "nginx.conf", "default.conf"):
            for path in root.rglob(pattern):
                if path.is_file():
                    files.append(path.resolve())

    unique: list[Path] = []
    seen: set[Path] = set()
    for path in files:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return unique


def analyze_nginx_log_paths(extra_roots: Optional[list[Path]] = None) -> None:
    """Найти access_log/error_log и проверить существование каталогов."""
    print_header("Анализ путей логов Nginx (access_log / error_log)")
    configs = discover_nginx_configs(extra_roots)
    if not configs:
        print_info("Конфиги Nginx не найдены.")
        return

    print_info(f"Конфигов к анализу: {len(configs)}")
    for conf in configs:
        print_info(f"  config: {abs_path_str(conf)}")

    seen_logs: set[Path] = set()
    missing = 0
    found = 0

    for conf in configs:
        try:
            text = conf.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            print_warn(f"Не удалось прочитать {abs_path_str(conf)}: {exc}")
            continue

        for match in NGINX_LOG_RE.finditer(text):
            directive = match.group(1).lower()
            raw_path = match.group(2).rstrip(";").split()[0]
            if raw_path.lower() == "off" or not raw_path.startswith("/"):
                continue

            log_file = Path(raw_path)
            if log_file in seen_logs:
                continue
            seen_logs.add(log_file)
            found += 1

            log_dir = log_file.parent
            print_info(f"Директива: {directive}")
            print_info(f"  Файл лога:    {abs_path_str(log_file)}")
            print_info(f"  Каталог лога: {abs_path_str(log_dir)}")
            print_info(f"  Источник:     {abs_path_str(conf)}")

            if log_dir.is_dir():
                print_ok(f"Каталог существует: {abs_path_str(log_dir)}")
            else:
                missing += 1
                print(
                    color(
                        "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n"
                        f"! ПРЕДУПРЕЖДЕНИЕ: каталог логов НЕ существует:\n"
                        f"!   {abs_path_str(log_dir)}\n"
                        f"! Nginx может не стартовать, пока каталог не создан.\n"
                        f"! Рекомендуется: sudo mkdir -p {abs_path_str(log_dir)}\n"
                        "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!",
                        COLOR_YELLOW,
                    )
                )
                LOGGER.warning("Missing nginx log dir: %s", log_dir)

    if found == 0:
        print_info("Директивы access_log/error_log не найдены.")
    elif missing:
        print_warn(f"Отсутствующих каталогов логов: {missing}")
    else:
        print_ok("Все обнаруженные каталоги логов существуют.")


# =============================================================================
# CMS / Deep Scan / БД
# =============================================================================

def detect_cms(site_path: Path) -> str:
    names = {item.name for item in site_path.iterdir()} if site_path.is_dir() else set()
    if "wp-config.php" in names or (site_path / "wp-includes").is_dir():
        return "WordPress"
    if "configuration.php" in names or (site_path / "libraries" / "joomla").is_dir():
        return "Joomla"
    if "artisan" in names or (site_path / "bootstrap" / "app.php").is_file():
        return "Laravel"
    if "bitrix" in names or (site_path / "bitrix").is_dir():
        return "1C-Битрикс"
    return "Самописный / неизвестно"


def extract_db_credentials(site_path: Path) -> dict[str, Optional[str]]:
    creds: dict[str, Optional[str]] = {
        "db_name": None,
        "db_user": None,
        "db_pass": None,
        "db_host": "localhost",
        "source": None,
    }

    for root, dirs, files in os.walk(site_path):
        dirs[:] = [d for d in dirs if d not in {"vendor", "node_modules", ".git", "cache"}]
        for filename in files:
            if filename not in CONFIG_FILENAMES:
                continue
            file_path = Path(root) / filename
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            for key, patterns in DB_PATTERNS.items():
                if creds[key] and key != "db_host":
                    continue
                for pattern in patterns:
                    match = re.search(pattern, content, re.IGNORECASE | re.MULTILINE)
                    if match:
                        value = match.group(1).strip().strip("\"'")
                        if key == "db_host" and creds["db_host"] != "localhost" and creds["db_host"]:
                            continue
                        creds[key] = value
                        creds["source"] = abs_path_str(file_path)
                        break
    return creds


def deep_scan_php(site_path: Path) -> int:
    print_header("Deep Scan: устаревшие PHP-функции")
    print_info(f"Корень сканирования: {abs_path_str(site_path)}")
    found = 0
    skip = {"vendor", "node_modules", ".git", "cache", "uploads", "tmp", "temp"}

    for root, dirs, files in os.walk(site_path):
        dirs[:] = [d for d in dirs if d not in skip]
        for filename in files:
            if not filename.endswith(".php"):
                continue
            file_path = Path(root) / filename
            try:
                lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            for line_no, line in enumerate(lines, start=1):
                for func in DEPRECATED_PHP:
                    if re.search(rf"\b{re.escape(func)}\s*\(", line):
                        found += 1
                        msg = (
                            f"{abs_path_str(file_path)}:{line_no} "
                            f"[{func}] {line.strip()[:160]}"
                        )
                        print_warn(msg)
    print_info(f"Deep Scan завершён. Найдено совпадений: {found}")
    return found


def scan_site(site_path: Path, deep_scan: bool = False) -> dict[str, Optional[str]]:
    print_header(f"Сканирование сайта: {abs_path_str(site_path)}")
    if not site_path.exists():
        print_error(f"Путь не существует: {abs_path_str(site_path)}")
        return {
            "db_name": None,
            "db_user": None,
            "db_pass": None,
            "db_host": None,
            "source": None,
        }

    cms = detect_cms(site_path)
    print_ok(f"Движок: {cms}")

    compose_hits = []
    for name in (
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
    ):
        for path in site_path.rglob(name):
            compose_hits.append(abs_path_str(path))
    if compose_hits:
        print_ok("Найдены docker-compose файлы:")
        for path in sorted(set(compose_hits))[:30]:
            print_info(f"  {path}")

    print_info("Поиск доступов к БД в конфигурационных файлах...")
    creds = extract_db_credentials(site_path)
    if creds.get("db_name"):
        print_ok(
            f"БД: name={creds['db_name']}, user={creds['db_user']}, "
            f"host={creds['db_host']}"
        )
        if creds.get("source"):
            print_info(f"Источник credentials: {creds['source']}")
    else:
        print_warn("Доступы к БД в файлах не обнаружены.")

    if deep_scan:
        deep_scan_php(site_path)

    analyze_nginx_log_paths(extra_roots=[site_path, Path("/var/www")])
    return creds


def test_mysql_import(
    db_name: str,
    db_user: str,
    db_pass: str = "",
    db_host: str = "127.0.0.1",
    db_port: int = 3306,
) -> bool:
    print_header("Тест импорта в локальную БД (CREATE/DROP таблицы)")
    if not command_exists("mysql"):
        print_error("Клиент mysql не найден в PATH.")
        return False
    if not db_name or not db_user:
        print_error("Недостаточно данных БД для теста.")
        return False

    table = f"migration_test_{uuid.uuid4().hex[:8]}"
    sql = f"CREATE TABLE `{table}` (id INT PRIMARY KEY); DROP TABLE `{table}`;"
    env = os.environ.copy()
    if db_pass:
        env["MYSQL_PWD"] = db_pass

    cmd = [
        "mysql",
        "-h",
        db_host,
        "-P",
        str(db_port),
        "-u",
        db_user,
        db_name,
        "-e",
        sql,
    ]
    print_info(
        f"Подключение: host={db_host} port={db_port} user={db_user} database={db_name}"
    )
    LOGGER.debug("mysql test table=%s", table)

    result = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
    if result.returncode == 0:
        print_ok(f"Временная таблица {table} создана и удалена успешно.")
        return True

    err = (result.stderr or result.stdout or "unknown error").strip()
    print_error(f"Тест импорта неуспешен: {err}")
    print_warn("Убедитесь, что БД создана и у пользователя есть права WRITE.")
    return False


# =============================================================================
# SSH / rsync
# =============================================================================

def get_ssh_inputs() -> tuple[str, str, int, str]:
    print_header("Данные SSH")
    host = ask_validated("IP или hostname удалённого сервера", validate_host)
    user = ask("Пользователь SSH", "root")
    if not user:
        raise ValueError("Пользователь SSH не может быть пустым")
    port = ask_validated("Порт SSH", validate_port, "22")
    password = getpass.getpass("Пароль (пусто, если вход по ключу): ")
    return host, user, port, password


def ssh_connect(host: str, user: str, port: int, password: str = ""):
    if paramiko is None:
        raise RuntimeError(
            "Для SSH-тестов нужен paramiko. Установите: pip3 install paramiko"
        )
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print_info(f"SSH подключение: {user}@{host}:{port}")
    try:
        client.connect(
            hostname=host,
            port=port,
            username=user,
            password=password or None,
            timeout=20,
            allow_agent=True,
            look_for_keys=True,
        )
    except Exception as exc:
        raise RuntimeError(f"SSH-подключение не удалось: {exc}") from exc
    return client


def remote_exec(client, command: str) -> str:
    LOGGER.debug("REMOTE: %s", command)
    _stdin, stdout, stderr = client.exec_command(command, timeout=60)
    out = stdout.read().decode("utf-8", errors="ignore")
    err = stderr.read().decode("utf-8", errors="ignore")
    if err.strip():
        LOGGER.debug("REMOTE STDERR: %s", err.strip())
    return out


def run_remote_pre_tests(client, remote_path: str) -> bool:
    print_header("Предварительные тесты удалённого сервера")
    uname = remote_exec(client, "uname -a").strip()
    print_ok(f"uname: {uname}")

    free = remote_exec(client, "df -h / | tail -n 1").strip()
    print_info(f"Диск (/): {free}")

    rsync_path = remote_exec(client, "command -v rsync || true").strip()
    if rsync_path:
        print_ok(f"rsync на удалённом сервере: {rsync_path}")
    else:
        print_error("rsync отсутствует на удалённой машине.")
        return False

    exists = remote_exec(
        client,
        f'test -e "{remote_path}" && echo EXISTS || echo MISSING',
    ).strip()
    if "EXISTS" not in exists:
        print_error(f"Удалённый путь не существует: {remote_path}")
        return False
    print_ok(f"Удалённый путь существует: {remote_path}")
    return True


def run_rsync(
    user: str,
    host: str,
    port: int,
    remote_path: str,
    local_path: Path,
    direction: str,
) -> bool:
    """direction: pull (старый → новый) или push (локальный → удалённый)."""
    if not command_exists("rsync"):
        print_error("Локально не найден rsync. Установите: sudo apt-get install -y rsync")
        return False

    local_abs = abs_path_str(local_path)
    remote_abs = remote_path if remote_path.startswith("/") else f"/{remote_path}"

    print_header(f"RSYNC ({direction.upper()})")
    if direction == "pull":
        source = f"{user}@{host}:{remote_abs.rstrip('/')}/"
        dest = local_abs.rstrip("/") + "/"
        Path(dest).mkdir(parents=True, exist_ok=True)
    else:
        source = local_abs.rstrip("/") + ("/" if Path(local_abs).is_dir() else "")
        dest = f"{user}@{host}:{remote_abs.rstrip('/')}/"

    print_info(f"Откуда: {source}")
    print_info(f"Куда:   {dest}")
    LOGGER.info("RSYNC %s from=%s to=%s", direction, source, dest)

    cmd = [
        "rsync",
        "-aH",
        "--info=progress2",
        "-e",
        f"ssh -p {port} -o StrictHostKeyChecking=accept-new",
        source,
        dest,
    ]
    print_info("Команда: " + " ".join(cmd))
    result = subprocess.run(cmd, check=False)
    if result.returncode == 0:
        print_ok("Синхронизация rsync успешно завершена.")
        return True
    print_error(f"rsync завершился с кодом {result.returncode}.")
    return False


def make_local_archive(site_path: Path) -> Optional[Path]:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive = Path(f"/tmp/site_export_{site_path.name}_{stamp}.tar.gz").resolve()
    print_header("Локальный архив tar.gz")
    print_info(f"Источник: {abs_path_str(site_path)}")
    print_info(f"Архив:    {archive}")
    cmd = ["tar", "-czf", str(archive), "-C", str(site_path.parent), site_path.name]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode == 0:
        print_ok(f"Архив создан: {archive}")
        return archive
    print_error(f"Не удалось создать архив: {result.stderr.strip()}")
    return None


# =============================================================================
# Режимы меню
# =============================================================================

def mode_old_server() -> None:
    """Режим: скрипт запущен на СТАРОМ сервере (аудит + экспорт)."""
    clear_screen()
    print_header("Режим: СТАРЫЙ сервер (аудит / экспорт)")

    local_path = ask_validated(
        "Абсолютный путь к сайту на этом сервере",
        lambda v: validate_abs_path(v, must_exist=True),
        "/var/www",
    )
    print_info(f"Рабочий путь сайта: {abs_path_str(local_path)}")

    print("\nТип сканирования:")
    print("  1) Быстрый аудит (CMS + БД + логи Nginx)")
    print("  2) Глубокий аудит (+ Deep Scan PHP mysql_*)")
    scan_choice = ask("Выбор", "1")

    show_disk_space("/")
    check_local_tools()
    if docker_available():
        containers = list_docker_containers()
        print_header("Docker")
        if not containers:
            print_info("Запущенных контейнеров нет.")
        for item in containers:
            print_info(
                f"{item['name']} | {item['image']} | {item['status']}"
            )
            if item["mounts"]:
                print_info(f"  {item['mounts']}")

    scan_site(Path(local_path), deep_scan=(scan_choice == "2"))

    print_header("Передача данных")
    print("  1) Никуда не передавать — только локальный tar.gz в /tmp/")
    print("  2) Протолкнуть файлы через rsync на НОВЫЙ сервер (Push)")
    print("  3) Вернуться в меню без передачи")
    transfer = ask("Выбор", "3")

    if transfer == "1":
        require_snapshot_confirmation()
        make_local_archive(Path(local_path))
        return

    if transfer != "2":
        print_info("Передача пропущена.")
        return

    require_snapshot_confirmation()
    maybe_stop_docker_containers()

    host, user, port, _password = get_ssh_inputs()
    remote_path = ask_validated(
        "Абсолютный путь назначения на НОВОМ сервере",
        lambda v: str(validate_abs_path(v, must_exist=False)),
    )
    print_info(f"Откуда (этот сервер): {abs_path_str(local_path)}")
    print_info(f"Куда (новый сервер):  {user}@{host}:{remote_path}")

    confirm = ask("Запустить rsync push? Введите YES", "")
    if confirm != "YES":
        print_warn("Экспорт отменён.")
        return

    run_rsync(user, host, port, remote_path, Path(local_path), direction="push")


def mode_new_server() -> None:
    """Режим: скрипт запущен на НОВОМ сервере (импорт + проверки)."""
    clear_screen()
    print_header("Режим: НОВЫЙ сервер (импорт)")

    require_snapshot_confirmation()

    local_path = ask_validated(
        "Куда положить сайт на ЭТОМ (новом) сервере",
        lambda v: validate_abs_path(v, must_exist=False),
        "/var/www/migration_import",
    )
    print_info(f"Локальный путь назначения: {abs_path_str(local_path)}")

    host, user, port, password = get_ssh_inputs()
    remote_path = ask_validated(
        "Абсолютный путь сайта на СТАРОМ сервере",
        lambda v: str(validate_abs_path(v, must_exist=False)),
    )

    client = None
    try:
        client = ssh_connect(host, user, port, password)
        if not run_remote_pre_tests(client, remote_path):
            return
    except RuntimeError as exc:
        print_error(str(exc))
        return
    finally:
        if client is not None:
            client.close()

    show_disk_space("/")
    print_info(f"Откуда: {user}@{host}:{remote_path}")
    print_info(f"Куда:   {abs_path_str(local_path)}")

    confirm = ask("Запустить rsync pull? Введите YES", "")
    if confirm != "YES":
        print_warn("Импорт отменён.")
        return

    ok = run_rsync(user, host, port, remote_path, Path(local_path), direction="pull")
    if not ok:
        return

    # После скачивания — CMS, Deep Scan (опционально) и проверка каталогов логов
    scan_site(
        Path(local_path),
        deep_scan=ask_yes("Запустить Deep Scan PHP после импорта?"),
    )

    if ask_yes("Выполнить тест CREATE/DROP таблицы в локальной БД?"):
        creds = extract_db_credentials(Path(local_path))
        db_name = ask("DB name", creds.get("db_name") or "")
        db_user = ask("DB user", creds.get("db_user") or "root")
        db_host = ask("DB host", creds.get("db_host") or "127.0.0.1")
        db_port = ask_validated("DB port", validate_port, "3306")
        db_pass = getpass.getpass("DB password (можно пусто): ")
        test_mysql_import(db_name, db_user, db_pass, db_host, db_port)


def mode_readiness() -> None:
    """Standalone-проверка готовности текущего сервера."""
    clear_screen()
    print_header("Проверка готовности сервера")
    check_local_tools()
    show_disk_space("/")

    if command_exists("php"):
        version = subprocess.run(
            ["php", "-v"],
            capture_output=True,
            text=True,
            check=False,
        )
        print_ok((version.stdout or "").splitlines()[0] if version.stdout else "PHP найден")
        modules_raw = subprocess.run(
            ["php", "-m"],
            capture_output=True,
            text=True,
            check=False,
        )
        installed = {
            line.strip().lower()
            for line in (modules_raw.stdout or "").splitlines()
            if line.strip() and not line.startswith("[")
        }
        print_header("Типовые модули PHP")
        for name in COMMON_PHP_MODULES:
            if name in installed:
                print_ok(f"module: {name}")
            else:
                print_warn(f"module отсутствует: {name}")
    else:
        print_warn("PHP CLI не найден.")

    if command_exists("nginx"):
        nginx_v = subprocess.run(
            ["nginx", "-V"],
            capture_output=True,
            text=True,
            check=False,
        )
        info = (nginx_v.stderr or nginx_v.stdout or "").strip().splitlines()
        if info:
            print_ok(info[0])
    analyze_nginx_log_paths(extra_roots=[Path("/var/www")])

    if ask_yes("Выполнить тест CREATE/DROP таблицы в локальной БД?"):
        db_name = ask("DB name", "mysql")
        db_user = ask("DB user", "root")
        db_host = ask("DB host", "127.0.0.1")
        db_port = ask_validated("DB port", validate_port, "3306")
        db_pass = getpass.getpass("DB password (можно пусто): ")
        test_mysql_import(db_name, db_user, db_pass, db_host, db_port)


def mode_local_audit_only() -> None:
    """Только локальный аудит без транспорта."""
    clear_screen()
    print_header("Локальный аудит (без переноса)")
    site_path = ask_validated(
        "Абсолютный путь к сайту / корню www",
        lambda v: validate_abs_path(v, must_exist=True),
        "/var/www",
    )
    deep = ask_yes("Включить Deep Scan PHP?")
    show_disk_space("/")
    check_local_tools()
    if docker_available():
        for item in list_docker_containers():
            print_info(
                f"Docker: {item['name']} | {item['image']} | {item['status']}"
            )
            if item["mounts"]:
                print_info(f"  {item['mounts']}")
    scan_site(Path(site_path), deep_scan=deep)


# =============================================================================
# Главное меню
# =============================================================================

def print_menu() -> None:
    print(
        color(
            f"""
╔══════════════════════════════════════════════════════════════╗
║         PHP / Nginx Migration Toolkit  v{VERSION:<18}║
╠══════════════════════════════════════════════════════════════╣
║  Где запущен этот скрипт и что нужно сделать?                ║
║                                                              ║
║  1) Я на СТАРОМ сервере  — аудит + экспорт (Push / tar.gz)   ║
║  2) Я на НОВОМ сервере   — импорт (Pull) + проверки логов    ║
║  3) Локальный аудит      — только осмотр, без переноса       ║
║  4) Проверка готовности  — PHP/Nginx/БД/диск на этой машине  ║
║  5) Выход                                                    ║
╚══════════════════════════════════════════════════════════════╝
""",
            COLOR_CYAN,
        )
    )
    if LOG_PATH:
        print_info(f"Лог скрипта: {LOG_PATH}")


def main() -> int:
    log_path = setup_logging()
    clear_screen()
    print_ok(f"Лог скрипта: {log_path}")
    print_info(f"Скрипт: {abs_path_str(Path(__file__))}")
    print_info(f"Рабочая директория: {abs_path_str(Path.cwd())}")

    while True:
        print_menu()
        try:
            choice = ask("Выберите вариант (1-5)", "")
        except RuntimeError:
            print()
            print_info("Выход.")
            return 0

        try:
            if choice == "1":
                mode_old_server()
            elif choice == "2":
                mode_new_server()
            elif choice == "3":
                mode_local_audit_only()
            elif choice == "4":
                mode_readiness()
            elif choice == "5":
                print_header("Выход")
                print_ok(f"Лог сохранён: {log_path}")
                return 0
            else:
                print_error("Некорректный выбор. Введите число от 1 до 5.")
                continue
        except RuntimeError as exc:
            print_error(str(exc))
            LOGGER.exception("Runtime error")
        except Exception as exc:  # noqa: BLE001 — верхний уровень меню
            print_error(f"Неожиданная ошибка: {exc}")
            LOGGER.exception("Unexpected error")

        print_info(f"Лог скрипта: {log_path}")
        try:
            ask("Enter — вернуться в меню", "")
        except RuntimeError:
            print_info("Выход.")
            return 0


if __name__ == "__main__":
    sys.exit(main())
