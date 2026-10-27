#!/usr/bin/env bash
# Remove OpenReporting services and code. Data, configuration and backups are KEPT unless --purge is given.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/lib.sh
. "$SCRIPT_DIR/lib.sh"
require_root
PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1
systemctl disable --now openreporting-worker.service openreporting-web.service openreporting-backup.timer 2>/dev/null || true
rm -f /etc/systemd/system/openreporting-web.service /etc/systemd/system/openreporting-worker.service \
      /etc/systemd/system/openreporting-backup.service /etc/systemd/system/openreporting-backup.timer
systemctl daemon-reload
if [ -L /etc/nginx/sites-enabled/openreporting.conf ]; then
  rm -f /etc/nginx/sites-enabled/openreporting.conf /etc/nginx/sites-available/openreporting.conf
  if nginx -t >/dev/null 2>&1; then systemctl reload nginx || true; fi
fi
rm -rf "$OPENREPORTING_HOME"
if [ "$PURGE" -eq 1 ]; then
  rm -rf "$OPENREPORTING_DATA" "$OPENREPORTING_ETC"
  userdel "$OPENREPORTING_USER" 2>/dev/null || true
  warn "Veri ve yapılandırma silindi. Yedekler korunuyor: $OPENREPORTING_BACKUPS"
else
  ok "Servisler ve kod kaldırıldı. Veri ($OPENREPORTING_DATA), ayarlar ($OPENREPORTING_ETC) ve yedekler korunuyor."
fi
