#!/usr/bin/env bash
# Run any OpenReporting CLI command as the service user with the production environment.
#   sudo /opt/openreporting/app/deploy/openreporting-admin.sh create-user sergen --role admin
#   sudo /opt/openreporting/app/deploy/openreporting-admin.sh reset-password sergen
#   sudo /opt/openreporting/app/deploy/openreporting-admin.sh doctor
#   sudo /opt/openreporting/app/deploy/openreporting-admin.sh export-dashboards /var/lib/openreporting/export
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/lib.sh
. "$SCRIPT_DIR/lib.sh"
require_root
[ $# -gt 0 ] || die "Kullanım: openreporting-admin.sh <komut> [argümanlar]   (openreporting --help)"
if [ -t 0 ]; then
  as_openreporting_tty "$OPENREPORTING_VENV/bin/openreporting" "$@"
else
  as_openreporting "$OPENREPORTING_VENV/bin/openreporting" "$@"
fi
