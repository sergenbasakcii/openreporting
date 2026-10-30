#!/usr/bin/env bash
# Shared helpers for OpenReporting deployment scripts (sourced, not executed).
# shellcheck disable=SC2034  # constants are used by the scripts that source this file

OPENREPORTING_USER=openreporting
OPENREPORTING_HOME=/opt/openreporting
OPENREPORTING_APP="$OPENREPORTING_HOME/app"
OPENREPORTING_VENV="$OPENREPORTING_HOME/venv"
OPENREPORTING_DATA=/var/lib/openreporting
OPENREPORTING_ETC=/etc/openreporting
OPENREPORTING_ENV="$OPENREPORTING_ETC/openreporting.env"
OPENREPORTING_BACKUPS=/var/backups/openreporting

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m ok\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m !!\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31mERR\033[0m %s\n' "$*" >&2; exit 1; }

require_root() {
  [ "$(id -u)" -eq 0 ] || die "Bu betik root olarak çalıştırılmalı (sudo)."
}

# Run a OpenReporting command as the service user with the service environment.
as_openreporting() {
  systemd-run --quiet --wait --pipe --collect \
    -p User="$OPENREPORTING_USER" -p Group="$OPENREPORTING_USER" \
    -p EnvironmentFile="$OPENREPORTING_ENV" -p WorkingDirectory="$OPENREPORTING_DATA" \
    -p UMask=0027 "$@"
}

# Interactive variant (password prompts need a terminal).
as_openreporting_tty() {
  systemd-run --quiet --wait --pty --collect \
    -p User="$OPENREPORTING_USER" -p Group="$OPENREPORTING_USER" \
    -p EnvironmentFile="$OPENREPORTING_ENV" -p WorkingDirectory="$OPENREPORTING_DATA" \
    -p UMask=0027 "$@"
}

python_ok() {
  "$1" -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 11) else 1)' 2>/dev/null
}

find_python() {
  local candidate
  for candidate in "${OPENREPORTING_PYTHON:-}" python3.13 python3.12 python3.11 python3; do
    [ -n "$candidate" ] || continue
    if command -v "$candidate" >/dev/null 2>&1 && python_ok "$(command -v "$candidate")"; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

health_check() {
  local _
  for _ in $(seq 1 30); do
    if curl -fsS --max-time 3 http://127.0.0.1:8810/api/health >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

sync_code() {
  local src="$1"
  install -d -o root -g root -m 0755 "$OPENREPORTING_HOME"
  if [ -d "$OPENREPORTING_APP" ]; then
    rm -rf "$OPENREPORTING_HOME/app.prev"
    cp -a "$OPENREPORTING_APP" "$OPENREPORTING_HOME/app.prev"
  fi
  install -d -o root -g root -m 0755 "$OPENREPORTING_APP"
  rsync -a --delete \
    --exclude '.git/' --exclude '.venv/' --exclude 'venv/' --exclude 'build/' --exclude '__pycache__/' \
    --exclude '*.pyc' --exclude '.pytest_cache/' --exclude '*.egg-info/' --exclude 'windows/Settings.local.ps1' \
    "$src/" "$OPENREPORTING_APP/"
  chown -R root:root "$OPENREPORTING_APP"
  chmod -R u=rwX,go=rX "$OPENREPORTING_APP"
  chmod 0755 "$OPENREPORTING_APP"/deploy/*.sh
}

install_package() {
  local wheelhouse="${1:-}"
  "$OPENREPORTING_VENV/bin/python" -m pip install --quiet --upgrade pip wheel setuptools ${wheelhouse:+--no-index --find-links "$wheelhouse"}
  "$OPENREPORTING_VENV/bin/python" -m pip install --quiet --require-hashes --only-binary=:all: ${wheelhouse:+--no-index --find-links "$wheelhouse"} -r "$OPENREPORTING_APP/requirements-runtime.lock"
  "$OPENREPORTING_VENV/bin/python" -m pip install --quiet --upgrade --no-deps ${wheelhouse:+--no-index --find-links "$wheelhouse"} "$OPENREPORTING_APP"
  "$OPENREPORTING_VENV/bin/python" -m pip check
}
