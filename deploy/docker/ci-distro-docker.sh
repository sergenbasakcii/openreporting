#!/usr/bin/env bash
# CI: inside a distribution container, install Docker exactly as kurulum.sh does on a fresh server (official repo).
set -e
command -v sed >/dev/null || true
mkdir -p /work && cp /repo/kurulum.sh /work/ && cd /work
if [ -n "${WITH_PODMAN:-}" ]; then dnf -y -q install podman >/dev/null 2>&1 && echo "podman preinstalled: $(rpm -q podman)"; fi
KURULUM_LIB=1 OR_EVET=1 . ./kurulum.sh
echo "family=$(os_family) id=$(osr ID) version=$(osr VERSION_ID)"
install_docker_packages > /tmp/install.log 2>&1 || { tail -30 /tmp/install.log; exit 1; }
docker --version
docker compose version
docker buildx version | head -1
command -v openssl git >/dev/null && echo "openssl+git ok"
[ -d /etc/cron.d ] && echo "cron.d ok"
if [ -n "${WITH_PODMAN:-}" ]; then rpm -q podman >/dev/null 2>&1 && { echo "podman still installed"; exit 1; } || echo "podman removed"; fi
echo RESULT_OK
