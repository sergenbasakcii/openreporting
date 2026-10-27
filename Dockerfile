# OpenReporting container image (alternative to the systemd install). Put TLS (nginx/traefik) in front of it.
FROM python:3.12-slim-bookworm AS build
WORKDIR /src
COPY pyproject.toml README.md ./
COPY openreporting ./openreporting
RUN pip wheel --no-cache-dir --wheel-dir /wheels .

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    OPENREPORTING_DATA_DIR=/var/lib/openreporting OPENREPORTING_COOKIE_SECURE=true OPENREPORTING_PROXY_HEADERS=true
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core tzdata ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --user-group --home-dir /var/lib/openreporting --shell /usr/sbin/nologin openreporting \
    && install -d -o openreporting -g openreporting -m 0750 /var/lib/openreporting \
    && install -d -o openreporting -g openreporting -m 0700 /run/openreporting-key
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels
USER openreporting
VOLUME ["/var/lib/openreporting"]
EXPOSE 8810
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8810/api/health', timeout=4).status == 200 else 1)"
# The web container binds all interfaces inside its network namespace; publish it only behind a TLS proxy.
CMD ["openreporting", "serve", "--host", "0.0.0.0", "--port", "8810", "--allow-remote", "--workers", "2"]
