# webserver-migrator

Инструменты аудита и миграции PHP-сайтов с Nginx на Ubuntu/Debian (bare-metal / PHP-FPM и Docker Compose) **без панелей управления**.

## Состав

| Файл | Назначение |
|------|------------|
| `scripts/server_audit.sh` | Быстрый первичный аудит сервера (Bash) |
| `scripts/migration_toolkit.py` | **Один файл** — интерактивный комбайн миграции (Python 3) |
| [`docs/phpinfo-migration-guide.md`](docs/phpinfo-migration-guide.md) | Гайд и чеклист phpinfo: паритет PHP до/после переноса, разбор сбоев |

## Требования безопасности

1. Перед опасными действиями (rsync, tar-экспорт, остановка контейнеров) — **предупреждение о Snapshot** и ввод `YES`.
2. Логи скриптов пишутся в `/tmp/` и дублируются в консоль.
3. Всегда выводятся **абсолютные пути**.
4. Анализируются `access_log` / `error_log` (в т.ч. `/var/log/nginx-access/`) с проверкой каталогов на целевом сервере.

---

## Скрипт №1 — Bash-аудит

Можно класть рядом с Python-комбайном — в `/tmp/` (разово) или `/opt/scripts/` (постоянно):

```bash
# разово (часто удалится после reboot)
cp scripts/server_audit.sh /tmp/
chmod +x /tmp/server_audit.sh
sudo /tmp/server_audit.sh

# постоянно
sudo mkdir -p /opt/scripts
sudo cp scripts/server_audit.sh /opt/scripts/
sudo chmod 755 /opt/scripts/server_audit.sh
sudo /opt/scripts/server_audit.sh

# лог: /tmp/server_audit_YYYY-MM-DD_HH-MM-SS.log
```

---

## Скрипт №2 — Python-комбайн (один файл)

Один файл `migration_toolkit.py`. Куда класть на ВМ — на ваш выбор:

| Путь | Когда использовать |
|------|--------------------|
| `/tmp/migration_toolkit.py` | Разовая миграция: после перезагрузки обычно удалится сам |
| `/opt/scripts/migration_toolkit.py` | Если инструмент нужен на сервере постоянно |

```bash
# зависимости ОС
sudo apt-get update
sudo apt-get install -y python3 python3-pip rsync openssh-client

# для режима импорта (SSH-проверки)
pip3 install --user paramiko

# --- вариант A: /tmp (временный) ---
cp migration_toolkit.py /tmp/
chmod +x /tmp/migration_toolkit.py
python3 /tmp/migration_toolkit.py

# --- вариант B: /opt/scripts (постоянный) ---
sudo mkdir -p /opt/scripts
sudo cp migration_toolkit.py /opt/scripts/
sudo chmod 755 /opt/scripts/migration_toolkit.py
python3 /opt/scripts/migration_toolkit.py

# лог процесса всегда: /tmp/migration_process_YYYY-MM-DD_HH-MM-SS.log
```

При старте скрипт сам показывает абсолютный путь и подсказывает, в каком режиме вы его запустили (`/tmp` или `/opt/scripts`).

### Меню

1. **Старый сервер** — аудит + экспорт (Push rsync или tar.gz в `/tmp/`)
2. **Новый сервер** — импорт (Pull) + проверка логов Nginx + тест БД
3. **Локальный аудит** — CMS, БД credentials, Deep Scan, без переноса
4. **Проверка готовности** — PHP/Nginx/диск/БД на этой машине
5. **Выход**

### Типичный сценарий

1. На старом сервере: пункт `1` → аудит → Push или tar.gz  
2. На новом сервере: пункт `2` → Pull → создать недостающие каталоги логов → тест БД  
3. Пункт `4` для финальной проверки модулей PHP/Nginx

### Дополнительно: phpinfo

Пункт `4` и `php -m` дают быстрый срез. Если нужно **сравнить окружения глубже** (ini-лимиты, CLI ≠ FPM, Docker) или разобрать сбой после cutover — см. [гайд phpinfo при миграции](docs/phpinfo-migration-guide.md) с чеклистом.

## Важно

- Перед режимами с переносом сделайте **Snapshot ВМ**.
- Дамп БД (`mysqldump`) выполняйте отдельно — скрипт проверяет доступ, но не заменяет бэкап.
- Разработчик не несёт ответственности за потерю данных при отсутствии снимка системы.
