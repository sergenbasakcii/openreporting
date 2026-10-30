#!/usr/bin/env bash
# Disposable official Oracle userspace acceptance; not a full VM/SELinux boot test.
set -euo pipefail
if [ "${OPENREPORTING_ORACLE_CI:-}" != 1 ] || [ ! -f /.dockerenv ]; then echo 'Disposable Oracle CI container required' >&2; exit 1; fi
SOURCE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=deploy/lib.sh
. "$SOURCE_ROOT/deploy/lib.sh"
# shellcheck source=deploy/platform.sh
. "$SOURCE_ROOT/deploy/platform.sh"
load_platform
[ "$PLATFORM_FAMILY" = oracle ] || die 'Oracle userspace required'
install_platform_packages 1 0
dnf install -y systemd
PY="$(find_python)"
rsync -a --exclude='.git/' --exclude='build/' "$SOURCE_ROOT/" /tmp/openreporting-source/
cd /tmp/openreporting-source
"$PY" -m venv /opt/openreporting/venv
PY=/opt/openreporting/venv/bin/python
"$PY" -m pip install --require-hashes --only-binary=:all: -r requirements-build.lock -r requirements-runtime.lock -r requirements-test.lock
"$PY" -m pip install --no-deps --no-build-isolation .
"$PY" -m pip check
"$PY" tools/check_runtime_lock.py
"$PY" tools/check_runtime_lock.py --scope build
"$PY" tools/check_runtime_lock.py --scope test
"$PY" -m pytest -q tests/test_deploy_platform.py tests/test_install_key_guard.py tests/test_portable.py tests/test_mfa.py tests/test_security_acceptance.py

id openreporting >/dev/null 2>&1 || useradd --system --user-group --home-dir /var/lib/openreporting --no-create-home --shell /sbin/nologin openreporting
install -d -o openreporting -g openreporting -m 0750 /var/lib/openreporting
ln -s /tmp/openreporting-source /opt/openreporting/app
chmod 0755 deploy/*.sh
mkdir -p build/units
VERSION="$(systemctl --version | awk 'NR==1 {print $2}')"
for file in deploy/systemd/openreporting-*.service deploy/systemd/openreporting-*.timer; do
  render_unit "$file" "$VERSION" > "build/units/$(basename "$file")"
done
systemd-analyze verify build/units/*.service build/units/*.timer

mkdir -p /etc/pki/tls/certs /etc/pki/tls/private
openssl req -x509 -newkey rsa:3072 -sha256 -days 1 -nodes -subj '/CN=localhost' \
  -addext 'subjectAltName=DNS:localhost,IP:127.0.0.1' \
  -keyout /etc/pki/tls/private/openreporting.key -out /etc/pki/tls/certs/openreporting.crt >/dev/null 2>&1
chmod 0600 /etc/pki/tls/private/openreporting.key
sed -e 's#__DOMAIN__#localhost#g' -e 's#__CERT__#/etc/pki/tls/certs/openreporting.crt#g' \
  -e 's#__KEY__#/etc/pki/tls/private/openreporting.key#g' deploy/nginx/openreporting.conf > "$NGINX_SITE"
nginx -t
export OPENREPORTING_DATA_DIR=/var/lib/openreporting OPENREPORTING_COOKIE_SECURE=true
export OPENREPORTING_PROXY_HEADERS=true OPENREPORTING_PUBLIC_URL=https://localhost OPENREPORTING_MFA_REQUIRED_ROLES=admin
export OPENREPORTING_LDAP_ENABLED=false OPENREPORTING_MAIL_ENABLED=false
runuser -u openreporting -- "$PY" -m openreporting.cli serve --host 127.0.0.1 --port 8810 > build/web.log 2>&1 &
WEB_PID=$!
trap 'nginx -s quit >/dev/null 2>&1 || true; kill "$WEB_PID" 2>/dev/null || true; wait "$WEB_PID" 2>/dev/null || true' EXIT
nginx
runuser -u openreporting -- "$PY" tools/oracle_http_acceptance.py
"$PY" - <<'EOF'
import json,platform
from pathlib import Path
from importlib.metadata import version
record={'scope':'Oracle userspace/package/unit parser/nginx HTTPS/API/worker contract in disposable container',
        'os':platform.freedesktop_os_release().get('PRETTY_NAME'),'python':platform.python_version(),
        'machine':platform.machine(),'kernel':platform.release(),'systemd_pid1_verified':False,
        'selinux_enforcing_verified':False,'full_vm_acceptance':'pending','application':version('openreporting')}
Path('/evidence/oracle-linux.json').write_text(json.dumps(record,indent=2)+'\n')
EOF
