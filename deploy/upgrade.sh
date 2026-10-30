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

OLD="$("$OPENREPORTING_VENV/bin/python" -c 'import openreporting; print(openreporting.__version__)')"
log "Mevcut sürüm: $OLD — ön yedek alınıyor"
"$SCRIPT_DIR/backup.sh"

log "Servisler durduruluyor"
systemctl stop openreporting-worker.service openreporting-web.service

rollback() {
  warn "Yükseltme başarısız; önceki kod geri yükleniyor"
  if [ -d "$OPENREPORTING_HOME/app.prev" ]; then
    rm -rf "$OPENREPORTING_APP"; cp -a "$OPENREPORTING_HOME/app.prev" "$OPENREPORTING_APP"
    "$OPENREPORTING_VENV/bin/python" -m pip install --quiet --force-reinstall --no-deps "$OPENREPORTING_APP" || true
  fi
  warn "Şema yükseltildiyse veritabanını son yedekten geri yükleyin: $OPENREPORTING_BACKUPS (state.sqlite3)"
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
systemctl start openreporting-worker.service
trap - ERR
NEW="$("$OPENREPORTING_VENV/bin/python" -c 'import openreporting; print(openreporting.__version__)')"
ok "Yükseltme tamam: $OLD → $NEW"
as_openreporting "$OPENREPORTING_VENV/bin/openreporting" doctor || true
