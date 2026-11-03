"""Datasource plugin contract and shared helpers."""

import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime

from ..domain import DomainError
from ..safe_regex import compile_slashed, is_slashed


class DataSourceError(DomainError):
    pass


@dataclass
class QueryContext:
    start: datetime
    end: datetime
    interval_s: float
    max_points: int
    timezone: str = "UTC"
    anchor_ms: int = 0
    variables: dict = field(default_factory=dict)
    builtins: dict = field(default_factory=dict)
    user: str = ""
    max_series_points: int = 2_000_000

    @property
    def interval_ms(self):
        return int(self.interval_s * 1000)


@dataclass
class QueryResult:
    frames: list
    warnings: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)


class DataSource:
    """A configured datasource instance. Never exposes secrets to callers."""

    type = ""
    default_format = None  # variable formatting used for interpolation

    def __init__(self, record: dict, secure: dict, settings):
        self.record = record
        self.uid = record["uid"]
        self.name = record["name"]
        self.url = record.get("url", "")
        self.options = record.get("json_data") or {}
        self.secure = secure or {}
        self.settings = settings

    def query(self, target: dict, ctx: QueryContext) -> QueryResult:  # pragma: no cover - interface
        raise NotImplementedError

    def metric_find(self, query, ctx: QueryContext | None = None) -> list:
        return []

    def health(self) -> dict:  # pragma: no cover - interface
        raise NotImplementedError


class TTLCache:
    """Tiny thread-safe metadata cache (Zabbix groups/hosts/items)."""

    def __init__(self, ttl=60.0, size=512):
        self.ttl, self.size = ttl, size
        self._data = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            entry = self._data.get(key)
            if not entry or entry[0] < time.monotonic():
                self._data.pop(key, None)
                return None
            return entry[1]

    def put(self, key, value):
        with self._lock:
            if len(self._data) >= self.size:
                oldest = min(self._data.items(), key=lambda kv: kv[1][0])[0]
                self._data.pop(oldest, None)
            self._data[key] = (time.monotonic() + self.ttl, value)

    def clear(self):
        with self._lock:
            self._data.clear()


def compile_filter(text):
    """Grafana-Zabbix filter: ``/regex/flags`` or exact (case-sensitive) text.

    Empty, ``*`` and ``/.*/`` match everything. Returns a predicate.
    """
    text = (text or "").strip()
    if text in ("", "*", "/.*/"):
        return lambda value: True
    if is_slashed(text):
        pattern = compile_slashed(text)
        return lambda value: bool(pattern.search(str(value)))
    if "*" in text:
        pattern = re.compile("^" + ".*".join(re.escape(p) for p in text.split("*")) + "$")
        return lambda value: bool(pattern.match(str(value)))
    return lambda value: str(value) == text


def bucket_average(points, interval_ms, consolidate="avg", anchor_ms=0):
    """Down-sample sorted points to ``interval_ms`` buckets (no interpolation)."""
    if interval_ms <= 0 or len(points) < 2:
        return points
    output, current, values = [], None, []
    for ts, value in points:
        key = anchor_ms + (ts - anchor_ms) // interval_ms * interval_ms
        if current is None:
            current = key
        if key != current:
            output.append([current, _consolidate(values, consolidate)])
            current, values = key, []
        values.append(value)
    if current is not None:
        output.append([current, _consolidate(values, consolidate)])
    return output


def _consolidate(values, method):
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    if method == "min":
        return min(clean)
    if method == "max":
        return max(clean)
    if method == "sum":
        return sum(clean)
    if method == "count":
        return float(len(clean))
    if method == "last":
        return clean[-1]
    if method == "first":
        return clean[0]
    return sum(clean) / len(clean)
