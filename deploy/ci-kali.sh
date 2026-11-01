#!/usr/bin/env bash
# Disposable Kali rolling lab acceptance: real apt preflight/download/install, locked wheels and nginx HTTPS.
# Not a full VM/systemd boot test; Kali stays a test/lab target.
set -euo pipefail
if [ "${OPENREPORTING_KALI_CI:-}" != 1 ] || [ ! -f /.dockerenv ]; then echo 'Disposable Kali CI container required' >&2; exit 1; fi
SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export OPENREPORTING_INSTALL_LOG=/evidence/install.log
# shellcheck source=deploy/lib.sh
. "$SOURCE_ROOT/deploy/lib.sh"
# shellcheck source=deploy/platform.sh
. "$SOURCE_ROOT/deploy/platform.sh"
load_platform
if [ "$PLATFORM_ID" != kali ] || [ "$PLATFORM_FAMILY" != debian ]; then die 'Kali userspace required'; fi
: > "$INSTALL_LOG"
install_platform_packages 1 0
PY="$(find_python)"
rsync -a --exclude='.git/' --exclude='build/' "$SOURCE_ROOT/" /tmp/openreporting-source/
cd /tmp/openreporting-source
"$PY" -m venv /opt/openreporting/venv
PY=/opt/openreporting/venv/bin/python
"$PY" -m pip install --require-hashes --only-binary=:all: -r requirements-build.lock -r requirements-runtime.lock -r requirements-test.lock
"$PY" -m pip install --no-deps --no-build-isolation .
"$PY" -m pip check
"$PY" tools/check_runtime_lock.py
"$PY" -m pytest -q tests/test_deploy_platform.py tests/test_install_key_guard.py tests/test_mfa.py tests/test_security_acceptance.py

mkdir -p /etc/ssl/private
openssl req -x509 -newkey rsa:3072 -sha256 -days 1 -nodes -subj '/CN=localhost' \
  -addext 'subjectAltName=DNS:localhost,IP:127.0.0.1' \
  -keyout "$TLS_KEY_DEFAULT" -out "$TLS_CERT_DEFAULT" >/dev/null 2>&1
chmod 0600 "$TLS_KEY_DEFAULT"
sed -e 's#__DOMAIN__#localhost#g' -e "s#__CERT__#$TLS_CERT_DEFAULT#g" -e "s#__KEY__#$TLS_KEY_DEFAULT#g" \
  deploy/nginx/openreporting.conf > "$NGINX_SITE"
ln -sf "$NGINX_SITE" /etc/nginx/sites-enabled/openreporting.conf
rm -f /etc/nginx/sites-enabled/default
nginx -t
id openreporting >/dev/null 2>&1 || useradd --system --user-group --home-dir /var/lib/openreporting --no-create-home --shell /usr/sbin/nologin openreporting
install -d -o openreporting -g openreporting -m 0750 /var/lib/openreporting
export OPENREPORTING_DATA_DIR=/var/lib/openreporting OPENREPORTING_COOKIE_SECURE=true
export OPENREPORTING_PROXY_HEADERS=true OPENREPORTING_PUBLIC_URL=https://localhost
runuser -u openreporting -- "$PY" -m openreporting.cli init
runuser -u openreporting -- "$PY" -m openreporting.cli serve --host 127.0.0.1 --port 8810 > /evidence/web.log 2>&1 &
WEB_PID=$!
trap 'nginx -s quit >/dev/null 2>&1 || true; kill "$WEB_PID" 2>/dev/null || true; wait "$WEB_PID" 2>/dev/null || true' EXIT
nginx
health_check || die 'API did not start'
curl -fsS --cacert "$TLS_CERT_DEFAULT" https://localhost/api/health
grep -E '^### |Paket planı' "$INSTALL_LOG" > /evidence/stages.txt
"$PY" - <<'PYEOF'
import json,platform
from pathlib import Path
from importlib.metadata import version
record={'scope':'Kali rolling apt preflight/download/install, locked wheels, nginx HTTPS health in disposable container',
        'os':platform.freedesktop_os_release().get('PRETTY_NAME'),'python':platform.python_version(),
        'machine':platform.machine(),'systemd_pid1_verified':False,'full_vm_acceptance':'pending',
        'application':version('openreporting')}
Path('/evidence/kali.json').write_text(json.dumps(record,indent=2)+'\n')
PYEOF
