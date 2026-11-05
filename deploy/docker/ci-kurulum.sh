#!/usr/bin/env bash
# CI: the one-command installer (kurulum.sh) on a fresh Ubuntu runner — unattended install,
# HTTPS reachable, admin can sign in, nightly backup scheduled, key copied, egress lock active,
# a second run changes nothing, "durum" and "yedek" work.
set -euo pipefail
[ "${OPENREPORTING_DOCKER_CI:-}" = 1 ] || { echo 'Disposable CI runner required' >&2; exit 1; }
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
SUBNET="$(ip -4 route show default | awk '{print $3}')/32"
export OR_EVET=1 OR_ADRES=localhost OR_HTTPS_PORT=8443 OR_YONETICI=ciadmin OR_PAROLA="$PASSWORD" OR_IC_AGLAR="$SUBNET"
trap 'sudo systemctl stop openreporting-cikis-kilidi.service 2>/dev/null || true; docker compose logs --no-color > build/kurulum-compose.log 2>&1 || true' EXIT
mkdir -p build
sudo -E ./kurulum.sh | tee build/kurulum-1.txt
grep -q 'Kurulum tamam' build/kurulum-1.txt
code() { curl -sk -o build/kurulum-last-body.txt -w '%{http_code}' "$@"; }
health="$(code https://localhost:8443/api/health)"; echo "health: $health"; [ "$health" = 200 ]
login="$(code -H 'Content-Type: application/json' -H 'Origin: https://localhost:8443'   -d "{\"username\":\"ciadmin\",\"password\":\"$PASSWORD\"}" https://localhost:8443/api/login)"
echo "login: $login"; [ "$login" = 200 ] || { cat build/kurulum-last-body.txt; exit 1; }
sudo test -s /root/openreporting-anahtar/secret.key
grep -q 'docker compose --profile backup run' /etc/cron.d/openreporting-yedek
systemctl is-active --quiet openreporting-cikis-kilidi.service
sudo bash deploy/docker/egress-lock.sh status | grep -q REJECT
# Second run: everything already in place, nothing is recreated.
sudo -E ./kurulum.sh | tee build/kurulum-2.txt
grep -q 'Var olan ayar dosyası korunuyor' build/kurulum-2.txt
grep -q 'Kullanıcılar zaten var' build/kurulum-2.txt
sudo ./kurulum.sh yedek > /dev/null
sudo ./kurulum.sh durum | tee build/kurulum-durum.txt
grep -q 'son yedek' build/kurulum-durum.txt
echo 'One-command installer passed'
