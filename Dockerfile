# OpenReporting container image. Run it with docker-compose.yml (web + worker + nginx TLS proxy); see docs/DOCKER.md.
FROM python:3.12-slim-bookworm AS build
WORKDIR /src
COPY pyproject.toml README.md requirements-runtime.lock requirements-build.lock ./
COPY openreporting ./openreporting
RUN pip install --no-cache-dir --require-hashes --only-binary=:all: -r requirements-build.lock \
    && pip download --no-cache-dir --require-hashes --only-binary=:all: --dest /wheels -r requirements-runtime.lock \
    && pip wheel --no-cache-dir --no-deps --no-build-isolation --wheel-dir /wheels .

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OPENREPORTING_CONTAINER=1 \
    OPENREPORTING_DATA_DIR=/var/lib/openreporting OPENREPORTING_COOKIE_SECURE=true OPENREPORTING_PROXY_HEADERS=true
# Fixed UID/GID 10001 so operators can prepare bind-mounted backup directories on the host.
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core tzdata ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 openreporting \
    && useradd --system --uid 10001 --gid 10001 --home-dir /var/lib/openreporting --shell /usr/sbin/nologin openreporting \
    && install -d -o openreporting -g openreporting -m 0750 /var/lib/openreporting \
    && install -d -o openreporting -g openreporting -m 0700 /run/openreporting-key /backups
COPY --from=build /wheels /wheels
COPY requirements-runtime.lock /tmp/requirements-runtime.lock
RUN pip install --no-cache-dir --no-index --find-links /wheels --require-hashes --only-binary=:all: -r /tmp/requirements-runtime.lock \
    && pip install --no-cache-dir --no-index --no-deps /wheels/openreporting-*.whl \
    && pip check && rm -rf /wheels /tmp/requirements-runtime.lock
COPY --chmod=0755 deploy/docker/backup.sh /usr/local/bin/openreporting-backup
USER openreporting
VOLUME ["/var/lib/openreporting"]
EXPOSE 8810
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8810/api/health', timeout=4).status == 200 else 1)"
# The web container binds all interfaces inside its network namespace; publish it only behind a TLS proxy.
CMD ["openreporting", "serve", "--host", "0.0.0.0", "--port", "8810", "--allow-remote", "--workers", "2"]
