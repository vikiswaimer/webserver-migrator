# webserver-migrator

Инструменты аудита и миграции PHP-сайтов с Nginx на Ubuntu/Debian (bare-metal / PHP-FPM и Docker Compose) **без панелей управления**.

## Состав

| Скрипт | Назначение |
|--------|------------|
| `scripts/server_audit.sh` | Быстрый первичный аудит сервера (Bash) |
| `scripts/run_migration.py` | Интерактивный комбайн миграции (Python 3) |
| `scripts/migration_tool/` | Модульный пакет режимов и сервисов |

## Требования безопасности

1. Перед опасными действиями (rsync, остановка контейнеров) выводится **яркое предупреждение о Snapshot** и требуется ввод `YES`.
2. Все логи скриптов пишутся в `/tmp/` и дублируются в консоль.
3. Всегда выводятся **абсолютные пути** к файлам, конфигам, БД и логу скрипта.
4. Анализируются директивы `access_log` / `error_log` (в т.ч. кастомные пути вроде `/var/log/nginx-access/`) с проверкой существования каталогов на целевом сервере.

---

## Скрипт №1 — Bash-аудит

### Зависимости

Стандартные утилиты Ubuntu/Debian: `bash`, `grep`, `awk`, `find`, `df`, `tee`.  
Опционально: `nginx`, `php`, `docker`.

### Запуск

```bash
chmod +x scripts/server_audit.sh
sudo ./scripts/server_audit.sh
```

Лог: `/tmp/server_audit_YYYY-MM-DD_HH-MM-SS.log`

### Что собирает

- Docker: контейнеры, образы, статусы, абсолютные пути volumes
- Nginx: версия, модули, сайты из `sites-enabled` / `conf.d`
- PHP: версия CLI и список расширений (`php -m`)
- Пути `access_log` / `error_log` + проверка каталогов
- Свободное место на диске, корни `/var/www`, поиск `docker-compose.yml`

---

## Скрипт №2 — Python-комбайн миграции

### Установка зависимостей

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv rsync openssh-client

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Пакет `paramiko` нужен для SSH-проверок в режиме импорта (Pull).

### Запуск

```bash
# из корня репозитория
source .venv/bin/activate
python3 scripts/run_migration.py

# или как модуль
PYTHONPATH=scripts python3 -m migration_tool
```

Лог: `/tmp/migration_process_YYYY-MM-DD_HH-MM-SS.log`

### Режимы меню

1. **Локальный аудит** — Docker/bare-metal, логи Nginx, CMS (WordPress, Bitrix, Laravel, Joomla), Deep Scan `mysql_*`
2. **Экспорт (Push)** — Snapshot → YES → SSH нового сервера → опциональная остановка Docker → `rsync`
3. **Импорт (Pull)** — Snapshot → YES → SSH старого сервера (`paramiko`) → `rsync` → проверка каталогов логов → тест временной таблицы БД
4. **Готовность нового сервера** — модули PHP/Nginx, логи, тест БД, диск
5. **Выход**

---

## Рекомендуемый порядок миграции

1. На **старом** сервере: `server_audit.sh` → режим 1 комбайна → режим 2 (Push) **или**
2. На **новом** сервере: режим 3 (Pull) → режим 4 (готовность)
3. Создать отсутствующие каталоги логов (`sudo mkdir -p /var/log/nginx-access/` и т.п.)
4. Восстановить БД, поправить конфиги, поднять Nginx/PHP-FPM или `docker compose up`

## Важно

- Перед режимами 2 и 3 сделайте **Snapshot ВМ** на стороне хостинга.
- Скрипты не заменяют бэкап БД (`mysqldump`) — выгружайте базы отдельно.
- Разработчик не несёт ответственности за потерю данных при отсутствии снимка системы.
