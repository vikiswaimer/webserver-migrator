# webserver-migrator

Инструменты аудита и миграции PHP-сайтов с Nginx на Ubuntu/Debian (bare-metal / PHP-FPM и Docker Compose) **без панелей управления**.

## Состав

| Файл | Назначение |
|------|------------|
| `scripts/server_audit.sh` | Быстрый первичный аудит сервера (Bash) |
| `scripts/migration_toolkit.py` | **Один файл** — интерактивный комбайн миграции (Python 3) |

## Требования безопасности

1. Перед опасными действиями (rsync, tar-экспорт, остановка контейнеров) — **предупреждение о Snapshot** и ввод `YES`.
2. Логи скриптов пишутся в `/tmp/` и дублируются в консоль.
3. Всегда выводятся **абсолютные пути**.
4. Анализируются `access_log` / `error_log` (в т.ч. `/var/log/nginx-access/`) с проверкой каталогов на целевом сервере.

---

## Скрипт №1 — Bash-аудит

```bash
chmod +x scripts/server_audit.sh
sudo ./scripts/server_audit.sh
# лог: /tmp/server_audit_YYYY-MM-DD_HH-MM-SS.log
```

---

## Скрипт №2 — Python-комбайн (один файл)

Загрузите на ВМ один файл `migration_toolkit.py` и запустите:

```bash
# зависимости ОС
sudo apt-get update
sudo apt-get install -y python3 python3-pip rsync openssh-client

# для режима импорта (SSH-проверки)
pip3 install --user paramiko
# или: pip3 install -r requirements.txt

python3 migration_toolkit.py
# лог: /tmp/migration_process_YYYY-MM-DD_HH-MM-SS.log
```

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

## Важно

- Перед режимами с переносом сделайте **Snapshot ВМ**.
- Дамп БД (`mysqldump`) выполняйте отдельно — скрипт проверяет доступ, но не заменяет бэкап.
- Разработчик не несёт ответственности за потерю данных при отсутствии снимка системы.
