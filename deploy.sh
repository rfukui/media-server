#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-$SCRIPT_DIR/.env}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

: "${REMOTE_USER:?Missing REMOTE_USER in $ENV_FILE}"
: "${REMOTE_HOST:?Missing REMOTE_HOST in $ENV_FILE}"
: "${REMOTE_PASSWORD:?Missing REMOTE_PASSWORD in $ENV_FILE}"
: "${REMOTE_BASE_DIR:?Missing REMOTE_BASE_DIR in $ENV_FILE}"
: "${MEDIA_UID:?Missing MEDIA_UID in $ENV_FILE}"
: "${MEDIA_GID:?Missing MEDIA_GID in $ENV_FILE}"
: "${KNOWN_HOSTS_FILE:?Missing KNOWN_HOSTS_FILE in $ENV_FILE}"

REMOTE_SUDO_PASSWORD="${REMOTE_SUDO_PASSWORD:-$REMOTE_PASSWORD}"

SSH_OPTS=(
  -o StrictHostKeyChecking=accept-new
  -o UserKnownHostsFile="$KNOWN_HOSTS_FILE"
)

STACKS=(
  mediaserver
)

FILES=(
  "compose.yaml"
  "nginx/nginx.conf"
  "www/index.html"
  "stack.env"
  "dashboard/settings.yaml"
  "dashboard/services.yaml"
  "scripts/bootstrap_mediaserver.py"
)

usage() {
  cat <<'EOF'
Usage:
  ./deploy.sh [stack...]

Examples:
  ./deploy.sh
  ./deploy.sh mediaserver
  ./deploy.sh all

Behavior:
  - Always uploads the rendered project files to the remote host.
  - Starts only the stacks passed as arguments.
  - If no stack is passed, only uploads the files.
  - Does not delete old data or remove existing containers as part of normal deploy.
EOF
}

require_bin() {
  local bin="$1"
  if ! command -v "$bin" >/dev/null 2>&1; then
    echo "Missing required command: $bin" >&2
    exit 1
  fi
}

install_local_tool() {
  local tool="$1"
  local apt_pkg="${2:-$tool}"
  local yum_pkg="${3:-$tool}"
  local dnf_pkg="${4:-$tool}"
  local pacman_pkg="${5:-$tool}"

  if command -v "$tool" >/dev/null 2>&1; then
    return 0
  fi

  if command -v apt-get >/dev/null 2>&1; then
    echo "Installing $apt_pkg locally (apt)."
    sudo apt-get update
    sudo apt-get install -y "$apt_pkg"
    return
  fi

  if command -v dnf >/dev/null 2>&1; then
    echo "Installing $dnf_pkg locally (dnf)."
    sudo dnf install -y "$dnf_pkg"
    return
  fi

  if command -v yum >/dev/null 2>&1; then
    echo "Installing $yum_pkg locally (yum)."
    sudo yum install -y "$yum_pkg"
    return
  fi

  if command -v pacman >/dev/null 2>&1; then
    echo "Installing $pacman_pkg locally (pacman)."
    sudo pacman -Syu --noconfirm "$pacman_pkg"
    return
  fi

  echo "Missing $tool and no supported package manager found." >&2
  exit 1
}

ensure_local_dependencies() {
  install_local_tool "sshpass"
  install_local_tool "ssh"
  install_local_tool "scp"
  install_local_tool "python3"
}

remote_install_package() {
  local binary="$1"
  local pkg_apt="$2"
  local pkg_dnf="$3"
  local pkg_yum="$4"
  local pkg_pacman="$5"
  local pm

  remote "command -v '$binary' >/dev/null 2>&1 && exit 0"
  pm="$(remote 'if command -v apt-get >/dev/null 2>&1; then echo apt; elif command -v dnf >/dev/null 2>&1; then echo dnf; elif command -v yum >/dev/null 2>&1; then echo yum; elif command -v pacman >/dev/null 2>&1; then echo pacman; else echo unknown; fi')"

  case "$pm" in
    apt)
      remote_sudo "DEBIAN_FRONTEND=noninteractive apt-get update -o Acquire::https::Verify-Peer=false -o Acquire::https::Verify-Host=false"
      remote_sudo "DEBIAN_FRONTEND=noninteractive apt-get install -y $pkg_apt"
      ;;
    dnf)
      remote_sudo "dnf install -y $pkg_dnf"
      ;;
    yum)
      remote_sudo "yum install -y $pkg_yum"
      ;;
    pacman)
      remote_sudo "pacman -Syu --noconfirm $pkg_pacman"
      ;;
    *)
      echo "No supported package manager on remote host to install $binary." >&2
      return 1
      ;;
  esac
}

remote_bootstrap_dependencies() {
  echo "Ensuring remote dependencies."

  if remote "command -v docker >/dev/null 2>&1 && docker --version >/dev/null 2>&1"; then
    echo "Docker already installed on remote."
  else
    remote_install_package "docker" "docker.io docker-compose-plugin" "docker" "docker" "docker docker-compose"
  fi

  if remote "docker compose version >/dev/null 2>&1"; then
    echo "Docker compose plugin already available on remote."
  elif remote "command -v docker-compose >/dev/null 2>&1 && docker-compose version >/dev/null 2>&1"; then
    echo "docker-compose already available on remote."
  else
    remote_install_package "docker-compose" "docker-compose-plugin" "docker-compose-plugin" "docker-compose-plugin" "docker-compose"
  fi

  if ! remote "command -v python3 >/dev/null 2>&1"; then
    remote_install_package "python3" "python3" "python3" "python3" "python"
  fi
}

contains() {
  local needle="$1"
  shift
  local item
  for item in "$@"; do
    if [[ "$item" == "$needle" ]]; then
      return 0
    fi
  done
  return 1
}

remote() {
  sshpass -p "$REMOTE_PASSWORD" ssh "${SSH_OPTS[@]}" "$REMOTE_USER@$REMOTE_HOST" "$@"
}

remote_sudo() {
  local cmd="$1"
  local quoted_cmd
  quoted_cmd="$(printf '%q' "$cmd")"
  remote "printf '%s\n' \"$REMOTE_SUDO_PASSWORD\" | sudo -S -p '' bash -lc $quoted_cmd"
}

remote_target_path() {
  local file="$1"
  case "$file" in
    compose.yaml|stack.env)
      printf "%s/%s" "$REMOTE_BASE_DIR" "$file"
      ;;
    nginx/*|www/*|dashboard/*|scripts/*)
      printf "%s/%s" "$REMOTE_BASE_DIR" "$file"
      ;;
    *)
      echo "Unsupported file mapping: $file" >&2
      exit 1
      ;;
  esac
}

render_file() {
  local src="$1"
  local dst="$2"

  python3 - "$src" "$dst" <<'PY'
import os
import re
import sys
from pathlib import Path

src_path = Path(sys.argv[1])
dst_path = Path(sys.argv[2])
text = src_path.read_text(encoding="utf-8")

pattern = re.compile(r"\{\{([A-Z0-9_]+)\}\}")

def replace(match: re.Match[str]) -> str:
    key = match.group(1)
    value = os.environ.get(key)
    if value is None:
        raise SystemExit(f"Missing template variable {key} while rendering {src_path}")
    return value

rendered = pattern.sub(replace, text)
dst_path.write_text(rendered, encoding="utf-8")
PY
}

copy_file() {
  local file="$1"
  local remote_path
  local remote_dir
  local rendered_file

  remote_path="$(remote_target_path "$file")"
  remote_dir="$(dirname "$remote_path")"
  rendered_file="$(mktemp)"

  remote "mkdir -p \"$remote_dir\""
  render_file "$file" "$rendered_file"
  sshpass -p "$REMOTE_PASSWORD" scp "${SSH_OPTS[@]}" "$rendered_file" "$REMOTE_USER@$REMOTE_HOST:$remote_path"
  remote "chmod 644 \"$remote_path\""
  rm -f "$rendered_file"
}

prepare_mediaserver() {
  remote_sudo "install -d -o '$REMOTE_USER' -g '$REMOTE_USER' -m 755 \
    '$REMOTE_BASE_DIR' \
    '$REMOTE_BASE_DIR/nginx' \
    '$REMOTE_BASE_DIR/www' \
    '$REMOTE_BASE_DIR/scripts' \
    '$REMOTE_BASE_DIR/dashboard' \
    '$REMOTE_BASE_DIR/portainer' \
    '$REMOTE_BASE_DIR/yatch' \
    '$REMOTE_BASE_DIR/pihole' \
    '$REMOTE_BASE_DIR/pihole/pihole' \
    '$REMOTE_BASE_DIR/pihole/dnsmasq.d'"

  remote_sudo "install -d -o '$MEDIA_UID' -g '$MEDIA_GID' -m 775 \
    '$REMOTE_BASE_DIR/mediaserver' \
    '$REMOTE_BASE_DIR/mediaserver/downloads' \
    '$REMOTE_BASE_DIR/mediaserver/downloads/completed' \
    '$REMOTE_BASE_DIR/mediaserver/downloads/completed/radarr' \
    '$REMOTE_BASE_DIR/mediaserver/downloads/completed/sonarr' \
    '$REMOTE_BASE_DIR/mediaserver/downloads/completed/tv-sonarr' \
    '$REMOTE_BASE_DIR/mediaserver/downloads/incomplete' \
    '$REMOTE_BASE_DIR/mediaserver/media' \
    '$REMOTE_BASE_DIR/mediaserver/media/movies' \
    '$REMOTE_BASE_DIR/mediaserver/media/tv' \
    '$REMOTE_BASE_DIR/mediaserver/tools' \
    '$REMOTE_BASE_DIR/mediaserver/tools/watch' \
    '$REMOTE_BASE_DIR/mediaserver/tools/transmission' \
    '$REMOTE_BASE_DIR/mediaserver/tools/lidarr' \
    '$REMOTE_BASE_DIR/mediaserver/tools/radarr' \
    '$REMOTE_BASE_DIR/mediaserver/tools/sonarr' \
    '$REMOTE_BASE_DIR/mediaserver/tools/prowlarr' \
    '$REMOTE_BASE_DIR/mediaserver/tools/jellyseerr' \
    '$REMOTE_BASE_DIR/mediaserver/tools/jellyfin' \
    '$REMOTE_BASE_DIR/mediaserver/tools/jellyfin/cache' \
    '$REMOTE_BASE_DIR/mediaserver/tools/jellyfin/cache/transcodes'"

  remote_sudo "chmod 1777 '$REMOTE_BASE_DIR/mediaserver/tools/jellyfin/cache/transcodes'"
}

prepare_stack() {
  local stack="$1"
  case "$stack" in
    mediaserver)
      prepare_mediaserver
      ;;
  esac
}

deploy_files() {
  local stack
  for stack in "${STACKS[@]}"; do
    prepare_stack "$stack"
  done

  local file
  for file in "${FILES[@]}"; do
    copy_file "$file"
  done
}

validate_stacks() {
  local stack
  for stack in "$@"; do
    if ! contains "$stack" "${STACKS[@]}"; then
      echo "Unknown stack: $stack" >&2
      usage
      exit 1
    fi
  done
}

start_mediaserver() {
  remote "cd '$REMOTE_BASE_DIR' && docker compose up -d --remove-orphans"
  remote "cd '$REMOTE_BASE_DIR' && docker compose restart homepage jellyfin jellyseerr lidarr radarr sonarr prowlarr nginx"
  remote "cd '$REMOTE_BASE_DIR' && python3 scripts/bootstrap_mediaserver.py"
  remote "cd '$REMOTE_BASE_DIR' && docker compose restart jellyseerr homepage"
}

start_stack() {
  local stack="$1"
  case "$stack" in
    mediaserver)
      start_mediaserver
      ;;
  esac
}

main() {
  ensure_local_dependencies
  require_bin sshpass
  require_bin ssh
  require_bin scp
  require_bin python3

  if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
  fi

  local selected=("$@")
  if [[ "${1:-}" == "all" ]]; then
    selected=("${STACKS[@]}")
  fi

  validate_stacks "${selected[@]}"
  remote_bootstrap_dependencies

  echo "Uploading changed files to $REMOTE_USER@$REMOTE_HOST:$REMOTE_BASE_DIR ..."
  deploy_files

  if (( ${#selected[@]} == 0 )); then
    echo "Files uploaded. No stack was started."
    exit 0
  fi

  local stack
  for stack in "${selected[@]}"; do
    echo "Starting $stack ..."
    start_stack "$stack"
  done

  echo "Deploy complete."
}

main "$@"
