#!/usr/bin/env bash
# CI acceptance for docker-compose.yml on a disposable runner: build, TLS proxy, proxy trust,
# secure cookie, MFA over HTTPS, worker heartbeat, restart persistence, backup + verification, and
# operation with no outbound network at all (deploy/docker/egress-lock.sh).
set -euo pipefail
[ "${OPENREPORTING_DOCKER_CI:-}" = 1 ] || { echo 'Disposable CI runner required' >&2; exit 1; }
cd "$(dirname "${BASH_SOURCE[0]}")/../.."
EVIDENCE="${EVIDENCE:-build/docker}"
mkdir -p "$EVIDENCE"
BASE=https://localhost:8443

cp deploy/docker/openreporting.env.example deploy/docker/openreporting.env
sed -i "s#^OPENREPORTING_PUBLIC_URL=.*#OPENREPORTING_PUBLIC_URL=$BASE#" deploy/docker/openreporting.env
# The fixture admin exercises business APIs; mandatory enrollment is covered by the MFA browser job.
sed -i 's#^OPENREPORTING_MFA_REQUIRED_ROLES=.*#OPENREPORTING_MFA_REQUIRED_ROLES=#' deploy/docker/openreporting.env
printf 'OPENREPORTING_HTTP_PORT=8080\nOPENREPORTING_HTTPS_PORT=8443\nOPENREPORTING_BIND=127.0.0.1\n' > .env
openssl req -x509 -newkey rsa:3072 -sha256 -days 1 -nodes -subj '/CN=localhost' \
  -addext 'subjectAltName=DNS:localhost' -keyout deploy/docker/certs/key.pem -out deploy/docker/certs/cert.pem 2>/dev/null
sudo chown root:101 deploy/docker/certs/key.pem && sudo chmod 0640 deploy/docker/certs/key.pem
sudo install -d -o 10001 -g 10001 -m 0700 backups
trap 'docker compose logs --no-color > "$EVIDENCE/compose.log" 2>&1 || true' EXIT

docker compose up -d --build --wait
docker compose ps
PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
docker compose exec -T -e FIXTURE_PASSWORD="$PASSWORD" web python -c \
  'import os; from openreporting.config import Settings; from openreporting.security import create_user; create_user(Settings.from_env(), "dockeradmin", os.environ["FIXTURE_PASSWORD"], "admin")'

CURL=(curl -fsS --cacert deploy/docker/certs/cert.pem)
[ "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/)" = 301 ]
"${CURL[@]}" "$BASE/api/health" | grep -q '"ok"\|"status"'
[ "$(curl -s -o /dev/null -w '%{http_code}' --cacert deploy/docker/certs/cert.pem "$BASE/metrics")" = 404 ]

login() {
  "${CURL[@]}" -D "$EVIDENCE/login-headers.txt" -c "$EVIDENCE/jar" -H 'Content-Type: application/json' -H "Origin: $BASE" \
    -d "{\"username\":\"dockeradmin\",\"password\":\"$PASSWORD\"}" "$BASE/api/login" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["csrf"])'
}
CSRF="$(login)"
grep -qi '^set-cookie: openreporting_session=.*; *secure' "$EVIDENCE/login-headers.txt"
# MFA setup is refused over plain HTTP; success proves the proxy's X-Forwarded-Proto is trusted.
"${CURL[@]}" -b "$EVIDENCE/jar" -H 'Content-Type: application/json' -H "Origin: $BASE" -H "X-CSRF-Token: $CSRF" \
  -d "{\"password\":\"$PASSWORD\"}" "$BASE/api/user/mfa/setup" | python3 -c 'import json,sys; assert json.load(sys.stdin)["qr"].startswith("data:image/svg+xml")'

worker_state() {
  "${CURL[@]}" -b "$EVIDENCE/jar" "$BASE/api/admin/stats" | python3 -c 'import json,sys; print(json.load(sys.stdin)["worker"]["state"])'
}
for _ in $(seq 1 30); do [ "$(worker_state)" = up ] && break; sleep 2; done
[ "$(worker_state)" = up ]

docker compose restart web worker
docker compose up -d --wait
CSRF="$(login)"
[ -n "$CSRF" ]

docker compose --profile backup run --rm backup | tee "$EVIDENCE/backup.txt"
DIR="$(sed -n 's#^Backup written: /backups/##p' "$EVIDENCE/backup.txt")"
docker compose --profile backup run --rm --entrypoint openreporting backup \
  verify-backup "/backups/$DIR" --key-file /run/openreporting-key/secret.key | tee "$EVIDENCE/verify.json"
grep -q '"ok": *true' "$EVIDENCE/verify.json"
docker image inspect "openreporting:local" --format '{{.Size}}' > "$EVIDENCE/image-size-bytes.txt"

# Offline operation after installation: the host firewall rejects every new connection the containers
# open towards anything outside their own subnet (deploy/docker/egress-lock.sh). The product must still
# sign in, query, render a PDF, run the worker and back up.
sudo bash deploy/docker/egress-lock.sh apply
trap 'sudo bash deploy/docker/egress-lock.sh remove || true; docker compose logs --no-color > "$EVIDENCE/compose.log" 2>&1 || true' EXIT
docker compose exec -T web python - <<'PY'
import socket
for host, port in (("1.1.1.1", 443), ("8.8.8.8", 53), ("140.82.112.3", 443)):
    try:
        socket.create_connection((host, port), timeout=4).close()
    except OSError:
        continue
    raise SystemExit(f"egress is open: {host}:{port}")
print("no egress from web")
PY
docker compose restart web worker
docker compose up -d --wait
CSRF="$(login)"
JSON=(-b "$EVIDENCE/jar" -H 'Content-Type: application/json' -H "Origin: $BASE" -H "X-CSRF-Token: $CSRF")
"${CURL[@]}" "${JSON[@]}" -d '{"targets":[{"refId":"A","scenario":"sine","datasource":{"uid":"testdata"}}],"range":{"from":"now-1h","to":"now"},"compare":"previous"}' \
  "$BASE/api/ds/query" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["frames"] and "A__prev" in d["results"], d'
"${CURL[@]}" "${JSON[@]}" -d '{"dashboard":{"uid":"offline","title":"Offline","smart":{"orientation":"portrait","watermark":"GİZLİ"},"panels":[{"id":1,"type":"narrative","title":"Özet","datasource":{"uid":"testdata"},"targets":[{"refId":"A","scenario":"sine","datasource":{"uid":"testdata"}}],"smartPos":{"page":0,"x":0,"y":0,"w":24,"h":6}}]},"overwrite":true}' \
  "$BASE/api/dashboards/db" > /dev/null
"${CURL[@]}" "${JSON[@]}" -d '{"dashboard_uid":"offline","time_range":{"from":"now-1h","to":"now"},"timezone":"UTC","variables":{},"format":"pdf"}' \
  -o "$EVIDENCE/offline.pdf" "$BASE/api/dashboards/export"
head -c 4 "$EVIDENCE/offline.pdf" | grep -q '%PDF'
for _ in $(seq 1 30); do [ "$(worker_state)" = up ] && break; sleep 2; done
[ "$(worker_state)" = up ]
docker compose --profile backup run --rm backup > "$EVIDENCE/backup-offline.txt"
sudo bash deploy/docker/egress-lock.sh remove
echo 'Offline (no egress) operation passed'
docker compose down
echo 'Docker compose acceptance passed'
