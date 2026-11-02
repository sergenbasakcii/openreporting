#!/bin/sh
# Consistent OpenReporting backup inside the container (docker compose --profile backup run --rm backup).
# Writes /backups/YYYYMMDD-HHMMSS/{state.sqlite3,archive.tar.gz,openreporting.env,SHA256SUMS[,secret.key]}
# in the same layout as deploy/backup.sh, so `openreporting verify-backup` checks it unchanged.
set -eu
umask 077
DATA="${OPENREPORTING_DATA_DIR:-/var/lib/openreporting}"
ROOT="${OPENREPORTING_BACKUP_DIR:-/backups}"
KEEP_DAYS="${OPENREPORTING_BACKUP_KEEP_DAYS:-14}"
ENV_COPY="${OPENREPORTING_ENV_COPY:-/run/openreporting.env}"
case "$KEEP_DAYS" in ''|*[!0-9]*) echo "OPENREPORTING_BACKUP_KEEP_DAYS must be a number" >&2; exit 2 ;; esac
[ -w "$ROOT" ] || { echo "Backup directory $ROOT is not writable by uid $(id -u); see docs/DOCKER.md" >&2; exit 2; }
[ -f "$ENV_COPY" ] || { echo "Settings file $ENV_COPY is not mounted" >&2; exit 2; }

DEST="$ROOT/$(date -u +%Y%m%d-%H%M%S)"
mkdir "$DEST"
# A failed run must not leave a dated directory that looks like a complete backup.
trap 'rc=$?; [ "$rc" -eq 0 ] || rm -rf "$DEST"' EXIT
openreporting backup "$DEST/state.sqlite3"
set --
for asset in archive logos; do
  [ -d "$DATA/$asset" ] && set -- "$@" "$asset"
done
if [ "$#" -gt 0 ]; then tar -C "$DATA" -czf "$DEST/archive.tar.gz" "$@"; else tar -czf "$DEST/archive.tar.gz" -T /dev/null; fi
cp "$ENV_COPY" "$DEST/openreporting.env"
files="state.sqlite3 archive.tar.gz openreporting.env"
if [ "${OPENREPORTING_BACKUP_INCLUDE_KEY:-false}" = "true" ]; then
  python -c 'import shutil,sys
from openreporting.config import Settings
from openreporting.secrets_store import key_path, read_keys
path = key_path(Settings.from_env()); read_keys(path); shutil.copyfile(path, sys.argv[1])' "$DEST/secret.key"
  files="$files secret.key"
fi
(cd "$DEST" && for f in $files; do sha256sum "$f" | sed 's#  #  ./#'; done > SHA256SUMS)
find "$ROOT" -mindepth 1 -maxdepth 1 -type d -name '20*' -mtime +"$KEEP_DAYS" -exec rm -rf {} +
echo "Backup written: $DEST"
