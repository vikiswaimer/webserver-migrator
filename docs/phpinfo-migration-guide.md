# Гайд: phpinfo при миграции PHP-сайтов

Дополнение к [webserver-migrator](../README.md): что ещё открыть и изучить **до переноса** или когда после cutover «что-то не работает».

Тулкит уже снимает упрощённый срез через CLI (`php -v`, `php -m`) в пункте «Проверка готовности» и в `scripts/server_audit.sh`. **phpinfo глубже**: не только список модулей, но и критичные `ini`-директивы, разные конфиги CLI vs FPM и реальные пути.

---

## Что такое phpinfo

`phpinfo()` — встроенная функция PHP, которая выводит полную конфигурацию интерпретатора: версию, SAPI (CLI / FPM / Apache), загруженные модули, значения `php.ini`, пути, лимиты, переменные окружения.

Это **снимок окружения**, а не «здоровье сайта». При переносе цель — добиться **паритета**: новый сервер должен уметь запускать тот же код с теми же (или совместимыми) настройками.

---

## Как снять phpinfo безопасно

### CLI (предпочтительно для миграции)

```bash
# полный HTML-отчёт
php -i > /tmp/phpinfo-old.html

# текстовый (удобно diff)
php -i | tee /tmp/phpinfo-old.txt

# точечно без всего дампа
php -r "echo PHP_VERSION, PHP_EOL;"
php -m
php -i | grep -E 'memory_limit|upload_max|post_max|max_execution|date.timezone|disable_functions|open_basedir|session.save_path'
```

### PHP-FPM (важно: CLI ≠ FPM)

Сайт крутится под FPM, а `php -i` смотрит CLI. Конфиги могут отличаться.

```bash
# какой pool / ini использует FPM
ps aux | grep php-fpm
# типичные пути:
# /etc/php/8.x/fpm/php.ini
# /etc/php/8.x/fpm/pool.d/www.conf

# снимок через тот же бинарник FPM (если доступен)
php-fpm8.2 -i 2>/dev/null | head   # версия зависит от ОС
```

Веб-файл `phpinfo.php` с `<?php phpinfo();` — только временно, по IP/basic auth, и **сразу удалить**. Он светит пути, модули, env (иногда секреты).

### Docker

```bash
docker compose exec php php -i > /tmp/phpinfo-container.txt
# или имя сервиса из compose
```

Сравнивать нужно **контейнерное** PHP, не host CLI.

---

## Зачем phpinfo при переносе

```mermaid
flowchart LR
  oldSrv[Старый сервер]
  snap[Снимок phpinfo / php -i]
  newSrv[Новый сервер]
  diff[Сравнение паритета]
  fix[Доустановить модули / выровнять ini]
  cutover[Перенос кода и БД]
  oldSrv --> snap
  newSrv --> snap
  snap --> diff
  diff --> fix
  fix --> cutover
```

1. **До экспорта** — зафиксировать эталон старого окружения.
2. **На новом сервере до импорта** — проверить готовность (версия, модули, лимиты).
3. **После импорта** — убедиться, что сайт видит то же окружение (особенно FPM/Docker).
4. **При багах после cutover** — быстрый diff «было / стало».

Связь с тулкитом: пункт меню `4) Проверка готовности` и `COMMON_PHP_MODULES` в `scripts/migration_toolkit.py` — минимальный чеклист модулей. phpinfo дополняет его ini-лимитами и FPM-спецификой.

---

## На что смотреть в первую очередь

### 1. Версия и SAPI

| Поле | Почему важно |
|------|----------------|
| `PHP Version` | 7.4 → 8.x ломает `mysql_*`, `each`, типы; Deep Scan тулкита как раз ищет устаревшие функции |
| `Server API` | `FPM/FastCGI` vs `Command Line Interface` — разные ini |
| Architecture | x86_64 vs aarch64 — редко, но ломает нативные расширения |

Правило: **минор можно поднять осторожно; мажор — только после проверки кода**.

### 2. Загруженные модули (`Loaded Modules`)

Критичные для большинства CMS (совпадает с `COMMON_PHP_MODULES` тулкита):

- `curl`, `gd`/`imagick`, `intl`, `mbstring`, `mysqli` / `pdo_mysql`, `openssl`, `xml`, `zip`
- часто ещё: `bcmath`, `exif`, `fileinfo`, `opcache`, `redis`/`memcached`, `soap`, `sodium`

Нет модуля на новом сервере → белый экран, «Call to undefined function…», падение Composer/WP-плагинов.

### 3. Директивы, которые чаще всего ломают перенос

| Директива | Риск при занижении / отличии |
|-----------|------------------------------|
| `memory_limit` | Fatal на тяжёлых админках, импортах |
| `upload_max_filesize` / `post_max_size` | Не грузятся медиа (`post_max` ≥ `upload_max`) |
| `max_execution_time` / `max_input_time` | Таймауты миграций, кронов, импортов |
| `max_input_vars` | Ломаются большие формы (меню WP, ACF) |
| `date.timezone` | Сдвиг дат, кроны «не в тот час» |
| `disable_functions` | На новом хосте часто жёстче: нет `exec`/`shell_exec`/`proc_open` |
| `open_basedir` | 403/open_basedir restriction на пути вне jail |
| `session.save_path` / handler | Логауты, «не логинится админка» |
| `display_errors` / `error_reporting` | На проде лучше off; для отладки после переноса временно полезно |
| `opcache.enable` | Старый код после деплоя «не обновляется» без reset |
| `allow_url_fopen` / `allow_url_include` | Интеграции и (реже) уязвимости |

### 4. Пути и файловая раскладка

- `Loaded Configuration File` — какой именно `php.ini`
- `Scan this dir for additional .ini` — дропы в `conf.d/`
- `extension_dir`, `doc_root`, `error_log`
- `$_SERVER`-пути в веб-phpinfo vs реальный document root Nginx

После переноса пути `/var/www/old` → `/var/www/new` часто требуют правки `open_basedir`, pool `chdir`, volume в Docker.

### 5. CLI vs FPM vs Docker — типичная ловушка

- Аудит через `php -m` показывает CLI; сайту нужен **FPM**-набор модулей (`php8.2-fpm` + пакеты `php8.2-*`).
- В Docker host-PHP может отсутствовать — эталон только из контейнера.
- Несколько версий рядом (`php7.4-fpm` + `php8.2-fpm`): Nginx `fastcgi_pass` должен указывать на нужный сокет.

---

## Практический процесс сравнения

1. На старом: `php -i > /tmp/phpinfo-old.txt` (+ при FPM — снимок FPM/ini).
2. На новом: то же → `phpinfo-new.txt`.
3. Diff:

```bash
diff -u /tmp/phpinfo-old.txt /tmp/phpinfo-new.txt | less
# или точечно:
comm -3 <(php -m | sort) <(ssh new 'php -m' | sort)
```

4. Закрыть разрывы: `apt install php8.x-xxx`, правка `/etc/php/8.x/fpm/php.ini`, `systemctl reload php8.x-fpm`.
5. Повторить пункт готовности тулкита (меню `4`).
6. Смоук-тест сайта: логин, загрузка файла, кроны, страницы с картинками/PDF.

---

## Чеклист phpinfo при миграции

### До переноса (старый сервер)

- [ ] Снят текстовый `php -i` (и отдельно FPM/Docker, если сайт не на CLI)
- [ ] Зафиксированы `PHP Version` и `Server API`
- [ ] Сохранён список модулей (`php -m`)
- [ ] Записаны: `memory_limit`, `upload_max_filesize`, `post_max_size`, `max_execution_time`, `max_input_vars`, `date.timezone`
- [ ] Проверены `disable_functions`, `open_basedir`
- [ ] Известен путь к `php.ini` и pool FPM / имя Docker-сервиса
- [ ] Для CMS: нужные расширения под плагины (imagick, redis, soap, ionCube/Zend — если есть)

### Подготовка нового сервера

- [ ] Версия PHP совместима (лучше та же major.minor или проверенный апгрейд)
- [ ] Установлены все модули со старого списка (минимум — набор из readiness тулкита)
- [ ] Ini-лимиты ≥ старых (или осознанно выше)
- [ ] Timezone совпадает
- [ ] `disable_functions` не блокирует то, чем пользуется сайт
- [ ] `open_basedir` / права / document root согласованы с новым путём
- [ ] FPM pool: user/group = владелец файлов сайта; сокет совпадает с Nginx
- [ ] Opcache включён на проде; понятно, как сбрасывать после деплоя

### После переноса кода/БД

- [ ] Повторный `php -i` / readiness — паритет подтверждён
- [ ] Веб-SAPI (FPM), не только CLI, проверен
- [ ] Загрузка файлов работает (лимиты + права на `uploads`)
- [ ] Сессии/логин админки работают
- [ ] Нет Fatal/Warning в `error_log` Nginx/PHP по модулям
- [ ] Временный `phpinfo.php` удалён, если создавался
- [ ] Deep Scan тулкита (устаревшие `mysql_*`) — если PHP мажорно новее

### Красные флаги (остановить cutover)

- [ ] Мажор PHP выше, код со старыми API не проверен
- [ ] Нет `mysqli`/`pdo_mysql` при MySQL-сайте
- [ ] Нет `mbstring`/`curl`/`xml` на WordPress/Laravel
- [ ] `memory_limit=128M` при сайте, жившем на `512M`+
- [ ] Жёсткий `open_basedir`, не покрывающий путь сайта
- [ ] Сравнивали только host CLI, а сайт в Docker/другом FPM

---

## Краткие команды «на каждый день»

```bash
# эталон
php -v && php -m
php -i | grep -E 'Loaded Configuration|memory_limit|upload_max|post_max|max_execution|max_input_vars|date.timezone|disable_functions|open_basedir'

# пакеты Debian/Ubuntu под FPM-версию
# пример: php8.2-curl php8.2-gd php8.2-intl php8.2-mbstring php8.2-mysql php8.2-xml php8.2-zip

sudo systemctl reload php8.2-fpm
```

---

## Итог

**phpinfo / `php -i` — эталон окружения для паритета при переносе.** Смотреть версию, SAPI, модули, лимиты и пути; обязательно сравнивать тот SAPI, которым реально отдаётся сайт (FPM/Docker). Тулкит даёт быстрый срез модулей; phpinfo нужен, когда после переноса «всё установили, а сайт падает» — почти всегда расхождение ini или CLI≠FPM.
