#!/usr/bin/env bash
# server_audit.sh — первичный аудит PHP/Nginx-сервера (bare-metal + Docker)
# Clean Code: функции, set -euo pipefail, переменные в кавычках

set -euo pipefail

# ---------------------------------------------------------------------------
# Константы и глобальные переменные
# ---------------------------------------------------------------------------
readonly script_name="$(basename "${0}")"
readonly script_dir="$(cd "$(dirname "${0}")" && pwd)"
readonly audit_date="$(date '+%Y-%m-%d')"
readonly audit_time="$(date '+%H-%M-%S')"
readonly log_file="/tmp/server_audit_${audit_date}_${audit_time}.log"

readonly color_reset='\033[0m'
readonly color_red='\033[1;31m'
readonly color_yellow='\033[1;33m'
readonly color_green='\033[1;32m'
readonly color_cyan='\033[1;36m'
readonly color_bold='\033[1m'

# ---------------------------------------------------------------------------
# Утилиты вывода и логирования
# ---------------------------------------------------------------------------
setup_logging() {
  # Дублируем stdout/stderr в лог через tee; сохраняем исходные дескрипторы
  exec > >(tee -a "${log_file}") 2>&1
  echo "Лог скрипта: ${log_file}"
  echo "Каталог скрипта: ${script_dir}"
  echo "Дата запуска: $(date '+%Y-%m-%d %H:%M:%S %z')"
  echo "Хост: $(hostname -f 2>/dev/null || hostname)"
  echo "Пользователь: $(whoami)"
  echo "Рабочая директория: $(pwd -P)"
  echo "------------------------------------------------------------"
}

print_header() {
  local title="${1}"
  echo ""
  echo -e "${color_cyan}${color_bold}======== ${title} ========${color_reset}"
}

print_ok() {
  echo -e "${color_green}[OK]${color_reset} ${*}"
}

print_warn() {
  echo -e "${color_yellow}[WARN]${color_reset} ${*}"
}

print_err() {
  echo -e "${color_red}[ERROR]${color_reset} ${*}"
}

print_info() {
  echo -e "${color_bold}[INFO]${color_reset} ${*}"
}

require_command() {
  local cmd="${1}"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    return 1
  fi
  return 0
}

absolute_path() {
  local path="${1}"
  if [[ -d "${path}" ]]; then
    (cd "${path}" && pwd -P)
  elif [[ -e "${path}" ]]; then
    local dir
    dir="$(cd "$(dirname "${path}")" && pwd -P)"
    echo "${dir}/$(basename "${path}")"
  else
    # Путь ещё не существует — нормализуем относительно CWD
    if [[ "${path}" = /* ]]; then
      echo "${path}"
    else
      echo "$(pwd -P)/${path}"
    fi
  fi
}

# ---------------------------------------------------------------------------
# Блок безопасности: предупреждение о Snapshot
# ---------------------------------------------------------------------------
require_snapshot_confirmation() {
  echo ""
  echo -e "${color_red}${color_bold}"
  cat <<'EOF'
╔══════════════════════════════════════════════════════════════════════════════╗
║                                                                              ║
║  ВНИМАНИЕ! Перед продолжением ОБЯЗАТЕЛЬНО сделайте Snapshot                  ║
║  (снимок системы) вашей виртуальной машины на стороне хостинга/облака!       ║
║  Разработчик не несет ответственности за потерю данных.                      ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
EOF
  echo -e "${color_reset}"

  echo "Факт предупреждения о Snapshot зафиксирован в логе: ${log_file}"
  echo ""
  read -r -p "Для продолжения введите YES (капсом): " confirmation

  if [[ "${confirmation}" != "YES" ]]; then
    print_err "Подтверждение не получено. Завершение работы."
    echo "Snapshot confirmation: DENIED (input='${confirmation}')" >>"${log_file}" 2>/dev/null || true
    exit 1
  fi

  print_ok "Подтверждение Snapshot получено (YES)."
  echo "Snapshot confirmation: ACCEPTED at $(date '+%Y-%m-%d %H:%M:%S')"
}

# ---------------------------------------------------------------------------
# Проверки окружения
# ---------------------------------------------------------------------------
check_disk_space() {
  print_header "Свободное место на диске"
  if require_command df; then
    df -hT / /var /tmp /home 2>/dev/null || df -hT
  else
    print_err "Утилита df не найдена."
  fi
}

check_docker() {
  print_header "Проверка Docker"

  if ! require_command docker; then
    print_info "Docker не установлен (command -v docker → не найден)."
    return 0
  fi

  print_ok "Docker найден: $(command -v docker)"
  if docker version >/dev/null 2>&1; then
    docker version --format 'Client: {{.Client.Version}} | Server: {{.Server.Version}}' 2>/dev/null \
      || docker version
  else
    print_warn "Docker установлен, но демон недоступен текущему пользователю."
    return 0
  fi

  echo ""
  print_info "Запущенные контейнеры (имя | образ | статус | ID):"
  if ! docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.ID}}' 2>/dev/null; then
    print_warn "Не удалось получить список контейнеров."
    return 0
  fi

  echo ""
  print_info "Volumes / bind-mounts контейнеров (абсолютные пути на хосте):"
  local container_id
  local container_name
  while IFS= read -r container_id; do
    [[ -z "${container_id}" ]] && continue
    container_name="$(docker inspect -f '{{.Name}}' "${container_id}" 2>/dev/null | sed 's#^/##')"
    echo "--- Контейнер: ${container_name} (${container_id}) ---"
    docker inspect -f '{{range .Mounts}}Type={{.Type}} Src={{.Source}} Dst={{.Destination}} Mode={{.Mode}}{{println}}{{end}}' \
      "${container_id}" 2>/dev/null || print_warn "Не удалось прочитать mounts для ${container_id}"
  done < <(docker ps -q 2>/dev/null || true)

  if require_command docker-compose || docker compose version >/dev/null 2>&1; then
    print_ok "Docker Compose доступен."
  else
    print_info "Docker Compose не обнаружен."
  fi
}

check_nginx() {
  print_header "Nginx (классическое окружение)"

  if ! require_command nginx; then
    print_info "Nginx не найден в PATH (возможно, только в Docker)."
    return 0
  fi

  local nginx_bin
  nginx_bin="$(command -v nginx)"
  print_ok "Бинарник Nginx: ${nginx_bin}"
  nginx -v 2>&1 || true
  echo ""
  print_info "Собранные модули (nginx -V):"
  nginx -V 2>&1 || true

  echo ""
  print_info "Активные конфигурации сайтов:"
  local conf_dir
  for conf_dir in /etc/nginx/sites-enabled /etc/nginx/conf.d; do
    if [[ -d "${conf_dir}" ]]; then
      local abs_conf_dir
      abs_conf_dir="$(absolute_path "${conf_dir}")"
      print_ok "Каталог конфигураций: ${abs_conf_dir}"
      local conf_file
      while IFS= read -r -d '' conf_file; do
        echo "  - $(absolute_path "${conf_file}")"
      done < <(find "${abs_conf_dir}" -maxdepth 1 \( -type f -o -type l \) -print0 2>/dev/null | sort -z)
    else
      print_info "Каталог отсутствует: ${conf_dir}"
    fi
  done

  if [[ -f /etc/nginx/nginx.conf ]]; then
    print_ok "Главный конфиг: $(absolute_path /etc/nginx/nginx.conf)"
  fi
}

check_php() {
  print_header "PHP CLI (классическое окружение)"

  if ! require_command php; then
    print_info "PHP CLI не найден в PATH (возможно, только в Docker/FPM)."
    return 0
  fi

  local php_bin
  php_bin="$(command -v php)"
  print_ok "Бинарник PHP: ${php_bin}"
  php -v || true
  echo ""
  print_info "Загруженные расширения (php -m):"
  php -m || true

  if require_command php-fpm || require_command php-fpm8.3 || require_command php-fpm8.2 \
    || require_command php-fpm8.1 || require_command php-fpm8.0 || require_command php-fpm7.4; then
    print_ok "PHP-FPM обнаружен в системе."
  else
    print_info "Бинарник php-fpm в PATH не найден (может работать как systemd-сервис)."
  fi
}

# ---------------------------------------------------------------------------
# Анализ access_log / error_log в конфигах Nginx
# ---------------------------------------------------------------------------
collect_nginx_config_files() {
  local -a candidates=()
  local conf_dir
  local conf_file

  if [[ -f /etc/nginx/nginx.conf ]]; then
    candidates+=("/etc/nginx/nginx.conf")
  fi

  for conf_dir in /etc/nginx/sites-enabled /etc/nginx/conf.d /etc/nginx/sites-available; do
    if [[ -d "${conf_dir}" ]]; then
      while IFS= read -r -d '' conf_file; do
        candidates+=("${conf_file}")
      done < <(find "${conf_dir}" -type f -o -type l -print0 2>/dev/null)
    fi
  done

  # Также ищем docker-compose рядом с типичными путями сайтов
  if [[ -d /var/www ]]; then
    while IFS= read -r -d '' conf_file; do
      candidates+=("${conf_file}")
    done < <(find /var/www -maxdepth 4 \( -name 'nginx.conf' -o -name '*.nginx.conf' -o -name 'default.conf' \) -print0 2>/dev/null || true)
  fi

  printf '%s\n' "${candidates[@]:-}"
}

extract_log_paths_from_file() {
  local conf_file="${1}"
  # Ищем access_log / error_log; пропускаем off и пустые
  grep -E '^\s*(access_log|error_log)\s+' "${conf_file}" 2>/dev/null \
    | sed -E 's/#.*$//' \
    | awk '{print $1, $2}' \
    | while read -r directive path; do
        [[ -z "${path:-}" ]] && continue
        [[ "${path}" == "off" ]] && continue
        # Убрать точку с запятой и параметры формата
        path="${path%;}"
        path="${path%%;*}"
        [[ "${path}" != /* ]] && continue
        echo "${directive}|${path}|${conf_file}"
      done || true
}

analyze_nginx_log_paths() {
  print_header "Анализ путей access_log / error_log Nginx"

  local conf_file
  local line
  local directive
  local log_path
  local source_file
  local log_dir
  local rest
  local found_any=0
  local missing_dirs=0

  local -A seen_paths=()

  while IFS= read -r conf_file; do
    [[ -z "${conf_file}" ]] && continue
    [[ ! -r "${conf_file}" ]] && continue

    while IFS= read -r line; do
      [[ -z "${line}" ]] && continue
      found_any=1
      directive="${line%%|*}"
      rest="${line#*|}"
      log_path="${rest%%|*}"
      source_file="${rest#*|}"

      if [[ -n "${seen_paths[${log_path}]:-}" ]]; then
        continue
      fi
      seen_paths["${log_path}"]=1

      log_dir="$(dirname "${log_path}")"
      echo "Директива: ${directive}"
      echo "  Файл лога (абсолютный путь): ${log_path}"
      echo "  Каталог лога:                ${log_dir}"
      echo "  Источник конфига:            $(absolute_path "${source_file}")"

      if [[ -d "${log_dir}" ]]; then
        print_ok "Каталог существует: ${log_dir}"
      else
        missing_dirs=$((missing_dirs + 1))
        echo -e "${color_yellow}${color_bold}"
        echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        echo "! ПРЕДУПРЕЖДЕНИЕ: каталог логов НЕ существует:"
        echo "!   ${log_dir}"
        echo "! Nginx может не стартовать, пока каталог не создан."
        echo "! Рекомендуется: sudo mkdir -p ${log_dir}"
        echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        echo -e "${color_reset}"
      fi
      echo ""
    done < <(extract_log_paths_from_file "${conf_file}")
  done < <(collect_nginx_config_files)

  # Docker env: ищем переменные с путями логов
  if require_command docker && docker ps -q >/dev/null 2>&1; then
    print_info "Проверка env-переменных Docker на пути логов..."
    local container_id
    while IFS= read -r container_id; do
      [[ -z "${container_id}" ]] && continue
      docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "${container_id}" 2>/dev/null \
        | grep -Ei '^(ACCESS_LOG|ERROR_LOG|NGINX_.*LOG)=' \
        | while IFS= read -r env_line; do
            echo "  Контейнер ${container_id}: ${env_line}"
            local env_path="${env_line#*=}"
            if [[ "${env_path}" == /* ]]; then
              local env_dir
              env_dir="$(dirname "${env_path}")"
              if [[ ! -d "${env_dir}" ]]; then
                print_warn "Каталог из Docker env отсутствует на хосте: ${env_dir}"
              fi
            fi
          done || true
    done < <(docker ps -q 2>/dev/null || true)
  fi

  if [[ "${found_any}" -eq 0 ]]; then
    print_info "Директивы access_log/error_log в доступных конфигах не найдены."
  elif [[ "${missing_dirs}" -gt 0 ]]; then
    print_warn "Обнаружено отсутствующих каталогов логов: ${missing_dirs}"
  else
    print_ok "Все обнаруженные каталоги логов существуют."
  fi
}

check_www_roots() {
  print_header "Типичные корни сайтов"

  local www_dir
  for www_dir in /var/www /srv/www /home; do
    if [[ -d "${www_dir}" ]]; then
      print_ok "Каталог: $(absolute_path "${www_dir}")"
      ls -la "${www_dir}" 2>/dev/null | head -n 30 || true
    else
      print_info "Отсутствует: ${www_dir}"
    fi
  done

  if [[ -d /var/www ]]; then
    print_info "Поиск docker-compose.yml под /var/www (глубина ≤ 4):"
    find /var/www -maxdepth 4 \( -name 'docker-compose.yml' -o -name 'docker-compose.yaml' -o -name 'compose.yml' -o -name 'compose.yaml' \) -print 2>/dev/null \
      | while IFS= read -r compose_file; do
          echo "  - $(absolute_path "${compose_file}")"
        done || true
  fi
}

# ---------------------------------------------------------------------------
# Главная точка входа
# ---------------------------------------------------------------------------
main() {
  setup_logging
  require_snapshot_confirmation

  print_header "Старт аудита сервера"
  print_info "Скрипт: $(absolute_path "${script_dir}/${script_name}")"
  print_info "Лог:     ${log_file}"

  check_disk_space
  check_docker
  check_nginx
  check_php
  analyze_nginx_log_paths
  check_www_roots

  print_header "Аудит завершён"
  print_ok "Полный лог сохранён: ${log_file}"
}

main "${@}"
