#!/usr/bin/env bash
# Upgrade an existing OpenReporting installation from a new source tree (unpacked release or git checkout).
#   sudo ./deploy/upgrade.sh                 # from the directory containing this script
#   sudo ./deploy/upgrade.sh --wheelhouse /path/to/wheels   # offline
# A backup is taken first; the previous code stays in /opt/openreporting/app.prev for rollback.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=deploy/lib.sh
. "$SCRIPT_DIR/lib.sh"
# shellcheck source=deploy/platform.sh
. "$SCRIPT_DIR/platform.sh"
WHEELHOUSE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --wheelhouse) WHEELHOUSE="$(cd "$2" && pwd)"; shift 2 ;;
    *) die "Bilinmeyen seçenek: $1" ;;
  esac
done
require_root
load_platform
[ -x "$OPENREPORTING_VENV/bin/openreporting" ] || die "Mevcut kurulum bulunamadı; önce dağıtımın install betiğini çalıştırın"
[ "$SRC" != "$OPENREPORTING_APP" ] || die "Yeni sürümü ayrı bir dizinden çalıştırın (ör. /tmp/openreporting-1.x/deploy/upgrade.sh)"

env_value() { sed -n "s/^$1=//p" "$OPENREPORTING_ENV" | tail -1 | tr -d '"'"'"; }
set_env() {
  if grep -q "^$1=" "$OPENREPORTING_ENV"; then sed -i "s|^$1=.*|$1=$2|" "$OPENREPORTING_ENV"
  else printf '%s=%s\n' "$1" "$2" >> "$OPENREPORTING_ENV"; fi
}

# Since 1.1 requests are only accepted for known host names (Host header check). Older installs could
# leave OPENREPORTING_PUBLIC_URL empty and be reached by name or IP; fill both settings from the nginx
# site and this machine before anything changes, so the upgraded service does not reject every request.
if [ -z "$(env_value OPENREPORTING_PUBLIC_URL)" ]; then
  DOMAIN="$(sed -n 's/^[[:space:]]*server_name[[:space:]]\+\([^ ;]*\).*/\1/p' /etc/nginx/sites-available/openreporting.conf /etc/nginx/conf.d/openreporting.conf 2>/dev/null | head -1)"
  if [ -n "$DOMAIN" ] && [ "$DOMAIN" != "_" ]; then
    set_env OPENREPORTING_PUBLIC_URL "https://$DOMAIN"; log "OPENREPORTING_PUBLIC_URL=https://$DOMAIN ayarlandı"
  fi
fi
if [ -z "$(env_value OPENREPORTING_ALLOWED_HOSTS)" ]; then
  HOSTS="$(hostname -f 2>/dev/null || hostname),$(hostname -I 2>/dev/null | tr ' ' ',')"
  HOSTS="$(printf '%s' "$HOSTS" | tr -s ',' | sed 's/^,//; s/,$//')"
  set_env OPENREPORTING_ALLOWED_HOSTS "$HOSTS"; log "OPENREPORTING_ALLOWED_HOSTS=$HOSTS ayarlandı (gerekirse düzenleyin)"
fi

OLD="$("$OPENREPORTING_VENV/bin/python" -c 'import openreporting; print(openreporting.__version__)')"
log "Mevcut sürüm: $OLD — ön yedek alınıyor"
"$SCRIPT_DIR/backup.sh"
BACKUP_DIR="$(env_value OPENREPORTING_BACKUP_DIR)"; BACKUP_DIR="${BACKUP_DIR:-$OPENREPORTING_BACKUPS}"
PRE_BACKUP="$(find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name '20*' | sort | tail -1)"
db_version() {
  [ -f "$OPENREPORTING_DATA/state.sqlite3" ] || { echo none; return; }
  as_openreporting "$OPENREPORTING_VENV/bin/python" -c 'import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute("PRAGMA user_version").fetchone()[0])' "$OPENREPORTING_DATA/state.sqlite3"
}
OLD_DB_VERSION="$(db_version)"

log "Servisler durduruluyor"
systemctl stop openreporting-worker.service openreporting-web.service

rollback() {
  warn "Yükseltme başarısız; önceki kod geri yükleniyor"
  systemctl stop openreporting-worker.service openreporting-web.service || true
  if [ -d "$OPENREPORTING_HOME/app.prev" ]; then
    rm -rf "$OPENREPORTING_APP"; cp -a "$OPENREPORTING_HOME/app.prev" "$OPENREPORTING_APP"
    "$OPENREPORTING_VENV/bin/python" -m pip install --quiet --force-reinstall --no-deps "$OPENREPORTING_APP" || true
  fi
  # The old code refuses a newer schema; if this upgrade changed it, restore the pre-upgrade database.
  if [ "$(db_version)" != "$OLD_DB_VERSION" ]; then
    if [ -n "$PRE_BACKUP" ] && [ -s "$PRE_BACKUP/state.sqlite3" ]; then
      install -o "$OPENREPORTING_USER" -g "$OPENREPORTING_USER" -m 0640 "$PRE_BACKUP/state.sqlite3" "$OPENREPORTING_DATA/state.sqlite3"
      rm -f "$OPENREPORTING_DATA/state.sqlite3-wal" "$OPENREPORTING_DATA/state.sqlite3-shm"
      warn "Veritabanı yükseltme öncesi yedekten geri yüklendi: $PRE_BACKUP"
    else
      warn "Şema değişti ve şifrelenmemiş ön yedek bulunamadı; servisler başlatılmadı. Geri yükleme: docs/LINUX_DEPLOYMENT.md"
      exit 1
    fi
  fi
  systemctl start openreporting-web.service openreporting-worker.service || true
  exit 1
}
trap rollback ERR

sync_code "$SRC"
install_package "$WHEELHOUSE"
as_openreporting "$OPENREPORTING_VENV/bin/openreporting" init
install_service_units
systemctl daemon-reload
systemctl start openreporting-web.service
health_check || false
# The public host name must pass the new Host header check, not only 127.0.0.1.
PUBLIC_HOST="$(env_value OPENREPORTING_PUBLIC_URL | sed -E 's#^[a-z]+://##; s#[/:].*$##')"
if [ -n "$PUBLIC_HOST" ]; then
  curl -fsS --max-time 5 -H "Host: $PUBLIC_HOST" http://127.0.0.1:8810/api/health >/dev/null || false
fi
systemctl start openreporting-worker.service
trap - ERR
NEW="$("$OPENREPORTING_VENV/bin/python" -c 'import openreporting; print(openreporting.__version__)')"
ok "Yükseltme tamam: $OLD → $NEW"
as_openreporting "$OPENREPORTING_VENV/bin/openreporting" doctor || true
