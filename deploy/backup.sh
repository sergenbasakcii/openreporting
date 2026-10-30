#!/usr/bin/env bash
# Consistent OpenReporting backup: SQLite online backup and report archive, produced by the
# service user and streamed to root over a pipe (root never opens paths the service
# user can write, so a planted symlink cannot redirect root's file operations).
#
# The configured Fernet key/keyring is NOT copied by default: keep it in separate
# custody (password manager / offline media). Opt in with OPENREPORTING_BACKUP_INCLUDE_KEY=true.
# Set OPENREPORTING_BACKUP_GPG_RECIPIENT to encrypt every backup file with that public key.
#
# Run by openreporting-backup.service (root) or manually: sudo /opt/openreporting/app/deploy/backup.sh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=deploy/lib.sh
. "$SCRIPT_DIR/lib.sh"
require_root
umask 077

BACKUP_DIR="${OPENREPORTING_BACKUP_DIR:-$OPENREPORTING_BACKUPS}"
KEEP_DAYS="${OPENREPORTING_BACKUP_KEEP_DAYS:-14}"
DATA="${OPENREPORTING_DATA_DIR:-$OPENREPORTING_DATA}"
INCLUDE_KEY="${OPENREPORTING_BACKUP_INCLUDE_KEY:-false}"
GPG_RECIPIENT="${OPENREPORTING_BACKUP_GPG_RECIPIENT:-}"
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="$BACKUP_DIR/$STAMP"

install -d -m 0700 "$BACKUP_DIR"
install -d -m 0700 "$DEST"

# 1) SQLite: online, transactionally consistent copy made by the service user into a
#    private temporary file, integrity-checked, then streamed to stdout.
as_openreporting "$OPENREPORTING_VENV/bin/python" -c '
import os, shutil, sqlite3, sys, tempfile
from pathlib import Path
source = sys.argv[1]
with tempfile.TemporaryDirectory(dir=os.path.dirname(source), prefix=".backup-") as tmp:
    target = os.path.join(tmp, "state.sqlite3")
    src = sqlite3.connect(Path(source).resolve().as_uri() + "?mode=ro", uri=True, timeout=60)
    dst = sqlite3.connect(target)
    src.backup(dst)
    check = dst.execute("PRAGMA integrity_check").fetchone()[0]
    dst.close(); src.close()
    if check != "ok":
        sys.exit(3)
    with open(target, "rb") as handle:
        shutil.copyfileobj(handle, sys.stdout.buffer)' "$DATA/state.sqlite3" > "$DEST/state.sqlite3"
[ -s "$DEST/state.sqlite3" ] || die "Veritabanı yedeği boş"

# 2) Immutable report files and uploaded logos (tar does not follow symlinks).
assets=()
for asset in archive logos; do
  if [ -d "$DATA/$asset" ]; then assets+=("$asset"); fi
done
if [ "${#assets[@]}" -gt 0 ]; then
  as_openreporting tar -C "$DATA" -czf - "${assets[@]}" > "$DEST/archive.tar.gz"
fi

# 3) Configuration (root-owned files only).
cp -p "$OPENREPORTING_ENV" "$DEST/openreporting.env"
if [ "$INCLUDE_KEY" = "true" ]; then
  # Resolve the active raw key/keyring from service settings. Reading as the service
  # identity prevents a writable configured path/symlink from escalating root reads.
  as_openreporting "$OPENREPORTING_VENV/bin/python" -c '
from openreporting.config import Settings
from openreporting.secrets_store import key_path, read_keys
import sys
path = key_path(Settings.from_env())
read_keys(path)
with path.open("rb") as handle:
    content = handle.read(16385)
if len(content) > 16384:
    raise SystemExit("Invalid active key size")
sys.stdout.buffer.write(content)' > "$DEST/secret.key"
fi

# 4) Optional encryption at rest.
if [ -n "$GPG_RECIPIENT" ]; then
  command -v gpg >/dev/null || die "OPENREPORTING_BACKUP_GPG_RECIPIENT ayarlı ama gpg kurulu değil"
  for file in "$DEST"/*; do
    gpg --batch --yes --trust-model always --recipient "$GPG_RECIPIENT" --output "$file.gpg" --encrypt "$file"
    shred -u "$file" 2>/dev/null || rm -f "$file"
  done
fi

(cd "$DEST" && sha256sum ./* > SHA256SUMS)
chmod -R go-rwx "$DEST"

find "$BACKUP_DIR" -mindepth 1 -maxdepth 1 -type d -name '20*' -mtime +"$KEEP_DAYS" -exec rm -rf {} +
ok "Yedek: $DEST ($(du -sh "$DEST" | cut -f1))"
[ "$INCLUDE_KEY" = "true" ] || warn "Etkin anahtar/keyring yedeğe dahil edilmedi; ayrı ve güvenli emanette saklayın."
