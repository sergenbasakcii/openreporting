"""Bounded process-local HTTP metrics and logs without request/identity contents."""

from collections import Counter
import copy
import json
import logging
import os
import threading
import time
import uuid

log = logging.getLogger("openreporting.http")
BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)
METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}


def logging_config():
    """Uvicorn applies this configuration in every spawned web process as well."""
    from uvicorn.config import LOGGING_CONFIG

    config = copy.deepcopy(LOGGING_CONFIG)
    config["formatters"]["httpjson"] = {"format": "%(message)s"}
    config["handlers"]["httpjson"] = {"class": "logging.StreamHandler", "formatter": "httpjson", "stream": "ext://sys.stderr"}
    config["loggers"]["openreporting.http"] = {"handlers": ["httpjson"], "level": "INFO", "propagate": False}
    return config


class HttpMetrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.inflight = 0
        self.counts = Counter()
        self.buckets = [0] * len(BUCKETS)
        self.duration_sum = 0.0
        self.total = 0
        self.incomplete = 0
        self.worker_id = f"{os.getpid()}-{uuid.uuid4().hex[:12]}"

    def begin(self):
        with self.lock:
            self.inflight += 1

    def finish(self, method, status, seconds, complete):
        with self.lock:
            self.inflight -= 1
            self.counts[(method, f"{status // 100}xx")] += 1
            self.total += 1
            self.duration_sum += seconds
            self.incomplete += int(not complete)
            for i, bound in enumerate(BUCKETS):
                self.buckets[i] += int(seconds <= bound)

    def exposition(self):
        with self.lock:
            worker = f'worker_id="{self.worker_id}"'
            lines = [
                "# TYPE openreporting_http_inflight gauge",
                f"openreporting_http_inflight{{{worker}}} {self.inflight}",
                "# TYPE openreporting_http_requests_total counter",
            ]
            for (method, status), count in sorted(self.counts.items()):
                lines.append(f'openreporting_http_requests_total{{{worker},method="{method}",status_class="{status}"}} {count}')
            lines.append("# TYPE openreporting_http_duration_seconds histogram")
            for bound, count in zip(BUCKETS, self.buckets):
                lines.append(f'openreporting_http_duration_seconds_bucket{{{worker},le="{bound:g}"}} {count}')
            lines += [
                f'openreporting_http_duration_seconds_bucket{{{worker},le="+Inf"}} {self.total}',
                f"openreporting_http_duration_seconds_count{{{worker}}} {self.total}",
                f"openreporting_http_duration_seconds_sum{{{worker}}} {self.duration_sum:.6f}",
                "# TYPE openreporting_http_incomplete_total counter",
                f"openreporting_http_incomplete_total{{{worker}}} {self.incomplete}",
            ]
            return "\n".join(lines) + "\n"


class HttpTelemetryMiddleware:
    def __init__(self, app, metrics):
        self.app = app
        self.metrics = metrics

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = uuid.uuid4().hex
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        method = scope.get("method", "")
        method = method if method in METHODS else "OTHER"
        status, size, complete = 500, 0, False
        started = time.perf_counter()
        self.metrics.begin()

        async def wrapped_send(message):
            nonlocal status, size, complete
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
                message = {**message, "headers": headers + [(b"x-request-id", request_id.encode("ascii"))]}
            elif message["type"] == "http.response.body":
                size += len(message.get("body", b""))
            await send(message)
            if message["type"] == "http.response.body":
                complete = not message.get("more_body", False)

        try:
            await self.app(scope, receive, wrapped_send)
        finally:
            seconds = max(0.0, time.perf_counter() - started)
            self.metrics.finish(method, status, seconds, complete)
            path = scope.get("path", "")
            if status >= 400 or not complete or (not path.startswith("/static/") and path not in {"/healthz", "/api/health", "/metrics"}):
                # Route templates are code, never the raw path, query, headers or body.
                route = getattr(scope.get("route"), "path", "unmatched")
                log.info(
                    json.dumps(
                        {
                            "event": "http_request",
                            "request_id": request_id,
                            "worker_id": self.metrics.worker_id,
                            "method": method,
                            "route": route,
                            "status": status,
                            "duration_ms": round(seconds * 1000, 3),
                            "response_bytes": size,
                            "complete": complete,
                        },
                        separators=(",", ":"),
                    )
                )
