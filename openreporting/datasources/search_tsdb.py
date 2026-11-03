"""Search and time-series stores over HTTP: Elasticsearch / OpenSearch, InfluxDB (InfluxQL) and Graphite.

Requests are built by the server from validated fields: users never supply a URL or path, only an
index pattern / query text that is placed in the request body or a fixed query parameter.
"""

import base64
import json
import re
from urllib.parse import quote, urlencode

from ..frames import finite, table_frame, ts_frame
from .base import DataSourceError, QueryResult
from .http_sources import HTTPSource, clean_header, validate_http_url

_INDEX = re.compile(r"^[a-z0-9*][a-z0-9_.*,+-]{0,254}$")
_FIELD = re.compile(r"^[A-Za-z0-9_@][A-Za-z0-9_@.\-]{0,127}$")
_DB = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-/]{0,127}$")
METRICS = ("count", "avg", "sum", "min", "max", "cardinality")
LOG_LIMIT = 500


def _http(url, data, settings, *, timeout_max=60):
    url = validate_http_url(url, settings.allow_http_datasources)
    return url, {"timeout": max(3, min(int(data.get("timeout", 30) or 30), timeout_max))}


def _text(value, label, limit):
    value = str(value or "")
    if len(value) > limit or "\x00" in value:
        raise DataSourceError(f"{label} çok uzun veya geçersiz")
    return value


def _field(value, label, default=""):
    value = str(value or default).strip()
    if value and not _FIELD.match(value):
        raise DataSourceError(f"Geçersiz alan adı ({label}): {value}")
    return value


class _Auth(HTTPSource):
    """basic (user + password secret), bearer / apikey (token secret) or none."""

    auth_modes = ("none", "basic", "bearer")
    token_scheme = {"bearer": "Bearer"}

    def auth_headers(self):
        mode = self.options.get("auth_mode", "none")
        if mode == "basic" and self.secure.get("password"):
            raw = f"{clean_header(self.options.get('user', ''))}:{clean_header(self.secure['password'], 'parola')}".encode()
            return {"Authorization": "Basic " + base64.b64encode(raw).decode()}
        if mode in self.token_scheme and self.secure.get("token"):
            return {"Authorization": f"{self.token_scheme[mode]} {clean_header(self.secure['token'], 'erişim anahtarı')}"}
        return {}

    @classmethod
    def _auth_config(cls, data):
        mode = data.get("auth_mode") if data.get("auth_mode") in cls.auth_modes else "none"
        user = str(data.get("user") or "").strip()[:128]
        if mode == "basic" and not user:
            raise DataSourceError("Temel kimlik doğrulama için kullanıcı adı gerekli")
        return {"auth_mode": mode, "user": clean_header(user)}

    def _json(self, text):
        try:
            return json.loads(text)
        except ValueError:
            raise DataSourceError("Kaynak geçerli JSON yanıtı döndürmedi") from None


class ElasticsearchDataSource(_Auth):
    """Elasticsearch / OpenSearch: date-histogram metrics (optionally split by a terms field) or raw logs."""

    type = "elasticsearch"
    default_format = "lucene"
    auth_modes = ("none", "basic", "bearer", "apikey")
    token_scheme = {"bearer": "Bearer", "apikey": "ApiKey"}

    @classmethod
    def validate_config(cls, url, data, settings):
        url, clean = _http(url, data, settings)
        clean.update(cls._auth_config(data))
        index = str(data.get("index") or "").strip()
        if index and not _INDEX.match(index):
            raise DataSourceError("Geçersiz indeks deseni (küçük harf, rakam, * , . _ - +)")
        clean["index"] = index
        clean["time_field"] = _field(data.get("time_field"), "zaman alanı", "@timestamp")
        clean["flavor"] = "opensearch" if data.get("flavor") == "opensearch" else "elasticsearch"
        return url, clean

    def _index(self, target):
        index = str(target.get("index") or self.options.get("index") or "").strip()
        if not index or not _INDEX.match(index) or ".." in index:
            raise DataSourceError("İndeks deseni gerekli (ör. logs-*)")
        return quote(index, safe=",*")

    def _filter(self, target, ctx):
        time_field = self.options.get("time_field") or "@timestamp"
        clauses = [{"range": {time_field: {"gte": int(ctx.start.timestamp() * 1000), "lte": int(ctx.end.timestamp() * 1000), "format": "epoch_millis"}}}]
        text = _text(target.get("query"), "Sorgu", 8000).strip()
        if text:
            clauses.append({"query_string": {"query": text, "analyze_wildcard": True}})
        return time_field, {"bool": {"filter": clauses}}

    def _search(self, target, body):
        text = self.fetch(f"/{self._index(target)}/_search", method="POST", body=json.dumps(body), headers={"Content-Type": "application/json"})
        payload = self._json(text)
        if not isinstance(payload, dict) or payload.get("error"):
            raise DataSourceError("Arama başarısız; indeks desenini ve sorgu sözdizimini kontrol edin")
        if (payload.get("_shards") or {}).get("failed"):
            raise DataSourceError("Bazı parçalar (shard) yanıt vermedi; sonuç eksik olacağı için gösterilmedi")
        return payload

    def query(self, target, ctx):
        if target.get("mode") == "logs":
            return self._logs(target, ctx)
        time_field, query = self._filter(target, ctx)
        metric = target.get("metric") if target.get("metric") in METRICS else "count"
        field = _field(target.get("field"), "metrik alanı")
        if metric != "count" and not field:
            raise DataSourceError("Bu metrik için alan adı gerekli")
        group_by = _field(target.get("groupBy"), "gruplama alanı")
        size = max(1, min(int(target.get("size") or 10), 50))
        histogram = {
            "date_histogram": {
                "field": time_field,
                "fixed_interval": f"{max(1, int(ctx.interval_s))}s",
                "min_doc_count": 0,
                "extended_bounds": {"min": int(ctx.start.timestamp() * 1000), "max": int(ctx.end.timestamp() * 1000)},
            }
        }
        if metric != "count":
            histogram["aggs"] = {"v": {metric: {"field": field}}}
        aggs = {"g": {"terms": {"field": group_by, "size": size}, "aggs": {"h": histogram}}} if group_by else {"h": histogram}
        payload = self._search(target, {"size": 0, "track_total_hits": False, "query": query, "aggs": aggs})
        aggregations = payload.get("aggregations") or {}
        groups = [(str(b.get("key")), b["h"]) for b in (aggregations.get("g") or {}).get("buckets", [])] if group_by else [(None, aggregations.get("h") or {})]
        frames, count, ref = [], 0, target.get("refId", "A")
        label = target.get("alias") or (metric if metric == "count" else f"{metric}({field})")
        for key, hist in groups:
            points = []
            for bucket in hist.get("buckets", []):
                value = bucket.get("doc_count") if metric == "count" else (bucket.get("v") or {}).get("value")
                points.append([int(bucket.get("key", 0)), finite(value)])
            count += len(points)
            if count > ctx.max_series_points:
                raise DataSourceError("Nokta bütçesi aşıldı; zaman aralığını veya grup sayısını azaltın")
            frames.append(
                ts_frame(f"{key} · {label}" if key is not None else str(label), points, labels={group_by: key} if key is not None else {}, ref_id=ref)
            )
        return QueryResult(frames, [] if frames else ["Sorgu veri döndürmedi (NO DATA)"])

    def _logs(self, target, ctx):
        time_field, query = self._filter(target, ctx)
        limit = min(LOG_LIMIT, int(self.settings.max_rows))
        payload = self._search(target, {"size": limit, "sort": [{time_field: {"order": "desc"}}], "query": query, "track_total_hits": False})
        hits = (payload.get("hits") or {}).get("hits") or []
        keys = []
        for hit in hits:
            for key in hit.get("_source") or {}:
                if key != time_field and key not in keys and len(keys) < 30:
                    keys.append(key)
        rows = []
        for hit in hits:
            source = hit.get("_source") or {}
            stamp = source.get(time_field)
            rows.append([_epoch(stamp)] + [_cell(source.get(k)) for k in keys])
        columns = [{"name": "time", "type": "time"}] + [{"name": k, "type": "string"} for k in keys]
        return QueryResult([table_frame(self.name, columns, rows, ref_id=target.get("refId", "A"))], [] if rows else ["Kayıt bulunamadı"])

    def metric_find(self, query, ctx=None):
        field = _field(query.get("field") if isinstance(query, dict) else query, "değişken alanı")
        if not field:
            return []
        target = query if isinstance(query, dict) else {}
        body = {"size": 0, "aggs": {"v": {"terms": {"field": field, "size": 500}}}}
        payload = self._search(target, body)
        return [{"text": str(b.get("key")), "value": str(b.get("key"))} for b in ((payload.get("aggregations") or {}).get("v") or {}).get("buckets", [])]

    def health(self):
        info = self._json(self.fetch("/"))
        version = ((info or {}).get("version") or {}).get("number", "?")
        distribution = ((info or {}).get("version") or {}).get("distribution", "elasticsearch")
        return {"status": "ok", "message": f"{distribution} {version} · küme {info.get('cluster_name', '?')}"}


def _epoch(value):
    from .sql_engines import parse_time

    if isinstance(value, (int, float)):
        return int(value if value > 1e11 else value * 1000)
    parsed = parse_time(value) if isinstance(value, str) else None
    return int(parsed.timestamp() * 1000) if hasattr(parsed, "timestamp") else None


def _cell(value):
    if value is None:
        return None
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


class InfluxDBDataSource(_Auth):
    """InfluxDB 1.x / 2.x (v1 compatibility API) / 3.x with InfluxQL."""

    type = "influxdb"
    default_format = "influxregex"
    auth_modes = ("none", "basic", "token")
    token_scheme = {"token": "Token"}

    @classmethod
    def validate_config(cls, url, data, settings):
        url, clean = _http(url, data, settings)
        clean.update(cls._auth_config(data))
        database = str(data.get("database") or "").strip()
        if not _DB.match(database):
            raise DataSourceError("Veritabanı (bucket) adı gerekli")
        clean["database"] = database
        return url, clean

    @staticmethod
    def guard(text):
        text = _text(text, "InfluxQL", 16000).strip().rstrip(";").strip()
        bare = re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", "''", text)
        if not text:
            raise DataSourceError("InfluxQL sorgusu gerekli")
        if ";" in bare:
            raise DataSourceError("Tek bir InfluxQL ifadesine izin verilir")
        first = (re.match(r"^\s*(\w+)", bare) or [None, ""])[1].lower()
        if first not in ("select", "show"):
            raise DataSourceError("Yalnızca SELECT / SHOW sorgularına izin verilir")
        if re.search(r"\binto\b", bare, re.I):
            raise DataSourceError("SELECT INTO kullanılamaz")
        return text

    @staticmethod
    def expand(text, ctx):
        start, end = int(ctx.start.timestamp() * 1000), int(ctx.end.timestamp() * 1000)
        interval = f"{max(1, int(ctx.interval_s))}s"
        text = text.replace("$timeFilter", f"time >= {start}ms AND time <= {end}ms")
        return text.replace("$__interval", interval).replace("$interval", interval)

    def _run(self, text):
        params = {"db": self.options["database"], "q": text, "epoch": "ms"}
        payload = self._json(self.fetch("/query", params))
        results = (payload or {}).get("results") or [{}]
        if results[0].get("error"):
            raise DataSourceError(f"InfluxDB: {str(results[0]['error'])[:300]}")
        return results[0].get("series") or []

    def query(self, target, ctx):
        text = self.expand(self.guard(target.get("query")), ctx)
        frames, count, ref = [], 0, target.get("refId", "A")
        for series in self._run(text):
            columns = series.get("columns") or []
            if "time" not in columns:
                rows = [[_cell(v) if not isinstance(v, (int, float)) else v for v in row] for row in series.get("values") or []]
                frames.append(table_frame(series.get("name", self.name), [{"name": c, "type": "string"} for c in columns], rows, ref_id=ref))
                continue
            t = columns.index("time")
            tags = series.get("tags") or {}
            suffix = " ".join(f"{k}={v}" for k, v in tags.items())
            for i, column in enumerate(columns):
                if i == t:
                    continue
                points = [[int(row[t]), finite(row[i])] for row in series.get("values") or []]
                count += len(points)
                if count > ctx.max_series_points:
                    raise DataSourceError("Nokta bütçesi aşıldı; GROUP BY time() aralığını büyütün")
                name = target.get("alias") or f"{series.get('name')}.{column}"
                frames.append(ts_frame(f"{name} {suffix}".strip(), points, labels=tags, ref_id=ref))
        return QueryResult(frames, [] if frames else ["Sorgu veri döndürmedi (NO DATA)"], {"executedQueryString": text})

    def metric_find(self, query, ctx=None):
        text = self.guard(query.get("query") if isinstance(query, dict) else query)
        if ctx is not None:
            text = self.expand(text, ctx)
        values = []
        for series in self._run(text):
            columns = series.get("columns") or []
            index = columns.index("value") if "value" in columns else len(columns) - 1
            values += [{"text": str(row[index]), "value": str(row[index])} for row in series.get("values") or []]
        return values[:10000]

    def health(self):
        self.fetch("/ping", ok=(200, 204))
        self._run("SHOW MEASUREMENTS LIMIT 1")
        return {"status": "ok", "message": f"InfluxDB erişilebilir · veritabanı {self.options['database']}"}


class GraphiteDataSource(_Auth):
    """Graphite / Grafana-compatible render API (also Graphite-web on VictoriaMetrics, Carbonapi)."""

    type = "graphite"
    default_format = "glob"

    @classmethod
    def validate_config(cls, url, data, settings):
        url, clean = _http(url, data, settings)
        clean.update(cls._auth_config(data))
        return url, clean

    def query(self, target, ctx):
        lines = [line.strip() for line in _text(target.get("target"), "Graphite hedefi", 8000).splitlines() if line.strip()]
        if not lines or len(lines) > 20:
            raise DataSourceError("1-20 Graphite hedefi yazın (her satıra bir tane)")
        params = [
            ("from", str(int(ctx.start.timestamp()))),
            ("until", str(int(ctx.end.timestamp()))),
            ("format", "json"),
            ("maxDataPoints", str(int(ctx.max_points or 1000))),
        ]
        params += [("target", line) for line in lines]
        payload = self._json(self.fetch("/render?" + urlencode(params)))
        if not isinstance(payload, list):
            raise DataSourceError("Graphite beklenmeyen yanıt döndürdü")
        frames, count, ref = [], 0, target.get("refId", "A")
        for series in payload:
            points = [[int(ts) * 1000, finite(value)] for value, ts in series.get("datapoints") or [] if ts is not None]
            count += len(points)
            if count > ctx.max_series_points:
                raise DataSourceError("Nokta bütçesi aşıldı; zaman aralığını daraltın")
            frames.append(ts_frame(str(target.get("alias") or series.get("target", "")), points, labels=series.get("tags") or {}, ref_id=ref))
        return QueryResult(frames, [] if frames else ["Sorgu veri döndürmedi (NO DATA)"])

    def metric_find(self, query, ctx=None):
        text = _text(query.get("query") if isinstance(query, dict) else query, "Graphite sorgusu", 2000).strip() or "*"
        payload = self._json(self.fetch("/metrics/find", {"query": text}))
        return [{"text": str(n.get("text")), "value": str(n.get("id", n.get("text")))} for n in payload or []][:10000]

    def health(self):
        self._json(self.fetch("/metrics/find", {"query": "*"}))
        return {"status": "ok", "message": "Graphite render API erişilebilir"}
