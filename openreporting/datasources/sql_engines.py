"""SQL engines reached over HTTP: data lake (Trino / Presto / Starburst), Databricks SQL and ClickHouse.

All three share the PostgreSQL source's rules: one read statement (guard_sql), the time macros in the
engine's own dialect, the row budget, and the same frame conversion. No database drivers are needed.
"""

import base64
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

from ..frames import finite
from .base import DataSourceError, QueryResult
from .http_sources import HTTPSource, clean_header, validate_http_url
from .postgres import expand_macros, guard_sql, rows_to_frames

_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.@-]{0,127}$")
# Statement shapes that change data or metadata, checked outside string literals anywhere in the query
# (Spark SQL accepts "WITH ... INSERT", which a first-keyword check alone would let through). Shapes, not
# bare words, so columns and functions such as `update_time`, `load` or replace(...) keep working.
_WRITES = re.compile(
    r"\binsert\s+(into|overwrite)\b|\bupdate\s+[\w.`\"]+\s+set\b|\bdelete\s+from\b|\bmerge\s+into\b|\bcopy\s+into\b|"
    r"\b(create|drop|alter|truncate|undrop|replace)\s+(or\s+replace\s+)?(temporary\s+|temp\s+|external\s+|materialized\s+)?"
    r"(table|view|schema|database|catalog|function|index|dictionary|user|role|policy|connection|volume|share)\b|"
    r"\b(grant|revoke)\s+\w|\boptimize\s+(table\s+)?[\w.`]+|\b(attach|detach|rename|exchange)\s+(table|database|dictionary|tables)\b|"
    r"\bsystem\s+(drop|reload|stop|start|flush|sync|restart|kill|suspend|unfreeze)\b|\bkill\s+(query|mutation)\b|\bvacuum\s+\w|"
    r"\bmsck\s+repair\b|\bload\s+data\b|\b(cache|uncache)\s+(lazy\s+)?table\b|\bcall\s+[\w.]+\s*\(|"
    r"^\s*(set|reset|use)\b",
    re.I,
)
# ClickHouse: per-query SETTINGS would override the server caps; table functions reach files / URLs / hosts.
_CLICKHOUSE_DENY = re.compile(
    r"\bsettings\b|\b(url|file|s3|s3cluster|gcs|azureblobstorage|remote|remotesecure|cluster|clusterallreplicas|mysql|postgresql|"
    r"mongodb|redis|jdbc|odbc|hdfs|executable|input|sqlite|deltalake|iceberg|hudi)\s*\(",
    re.I,
)
_LITERAL_BS = re.compile(r"'(?:[^'\\]|\\.|'')*'|\"(?:[^\"\\]|\\.)*\"|`[^`]*`")
_LITERAL_STD = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"")


def guard_engine_sql(sql, dialect):
    """guard_sql plus dialect rules. Backslash-escaping dialects are re-scanned with their own literal rules."""
    body = guard_sql(sql)
    literal = _LITERAL_BS if dialect in ("clickhouse", "databricks") else _LITERAL_STD
    bare = literal.sub("''", body)
    if ";" in bare:
        raise DataSourceError("Tek bir SQL ifadesine izin verilir")
    if _WRITES.search(bare):
        raise DataSourceError("Yalnızca okuma sorgularına izin verilir (veri veya şema değiştiren komut bulundu)")
    if dialect == "clickhouse" and _CLICKHOUSE_DENY.search(bare):
        raise DataSourceError("ClickHouse sorgusunda SETTINGS ve tablo fonksiyonları (url, file, s3, remote …) kullanılamaz")
    return body


_WAREHOUSE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_TIMESTAMP = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?))?\s*(Z|UTC|[+-]\d{2}:?\d{2})?$")
_NUMERIC_TYPES = ("int", "bigint", "smallint", "tinyint", "integer", "double", "real", "float", "decimal", "long", "short", "byte", "uint", "number")
_TIME_TYPES = ("timestamp", "date", "datetime")


def _name(value, label, required=False, default=""):
    value = str(value or default).strip()
    if not value:
        if required:
            raise DataSourceError(f"{label} gerekli")
        return ""
    if not _NAME.match(value):
        raise DataSourceError(f"Geçersiz {label}: harf, rakam, _ . @ - kullanın")
    return value


def parse_time(value):
    """Engine timestamp text → aware datetime (UTC when the engine sends no zone); other values unchanged."""
    if not isinstance(value, str):
        return value
    match = _TIMESTAMP.match(value.strip())
    if not match:
        return value
    day, clock, zone = match.groups()
    text = f"{day}T{clock or '00:00:00'}"
    if "." in text:
        head, frac = text.split(".")
        text = f"{head}.{frac[:6]}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return value
    if zone and zone not in ("Z", "UTC"):
        offset = zone if ":" in zone else f"{zone[:3]}:{zone[3:]}"
        return datetime.fromisoformat(f"{text}{offset}")
    return parsed.replace(tzinfo=timezone.utc)


def kind_of(type_name):
    base = re.sub(r"^(nullable|lowcardinality)\((.*)\)$", r"\2", str(type_name or "").strip().lower())
    base = re.sub(r"^(nullable|lowcardinality)\((.*)\)$", r"\2", base)
    if base.startswith(_TIME_TYPES):
        return "time"
    if base.startswith(_NUMERIC_TYPES):
        return "number"
    return "string"


def convert_rows(columns, rows):
    """Typed values for rows_to_frames: datetimes for time columns, floats for numbers."""
    kinds = [kind_of(c["type"]) for c in columns]
    out = []
    for row in rows:
        converted = []
        for value, kind in zip(row, kinds):
            if value is None:
                converted.append(None)
            elif kind == "time":
                converted.append(parse_time(value) if isinstance(value, str) else value)
            elif kind == "number":
                converted.append(finite(value) if not isinstance(value, str) else finite(float(value)) if _is_number(value) else None)
            else:
                converted.append(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value)
        out.append(converted)
    return out


def _is_number(text):
    try:
        float(text)
        return True
    except ValueError:
        return False


def _common_http(url, data, settings):
    url = validate_http_url(url, settings.allow_http_datasources)
    timeout = max(3, min(int(data.get("timeout", 30) or 30), 120))
    return url, {"timeout": timeout}


class SQLEngine(HTTPSource):
    """Template: subclasses implement run(sql) -> (columns[{name,type}], rows) and dialect."""

    dialect = "postgres"
    default_format = "sqlstring"

    @property
    def row_limit(self):
        return int(self.settings.max_rows)

    def deadline(self):
        return time.monotonic() + float(self.options.get("timeout", 30)) * 4

    def check_rows(self, rows):
        if len(rows) > self.row_limit:
            raise DataSourceError(f"Satır sınırı ({self.row_limit}) aşıldı; sorguyu daraltın veya toplulaştırın")

    def query(self, target, ctx):
        body = guard_engine_sql(target.get("rawSql") or "", self.dialect)
        expanded = expand_macros(body, ctx.start, ctx.end, ctx.interval_s, self.dialect)
        columns, rows = self.run(expanded)
        frames = rows_to_frames([c["name"] for c in columns], convert_rows(columns, rows), target.get("format", "time_series"), target.get("refId", "A"))
        return QueryResult(frames, [] if rows else ["Sorgu satır döndürmedi (NO DATA)"], {"executedQueryString": expanded, "rows": len(rows)})

    def metric_find(self, query, ctx=None):
        text = query.get("rawSql") if isinstance(query, dict) else str(query or "")
        body = guard_engine_sql(text, self.dialect)
        if ctx is not None:
            body = expand_macros(body, ctx.start, ctx.end, ctx.interval_s, self.dialect)
        columns, rows = self.run(body)
        names = [c["name"].lower() for c in columns]
        text_i = names.index("__text") if "__text" in names else 0
        value_i = names.index("__value") if "__value" in names else text_i
        seen, values = set(), []
        for row in rows[:10000]:
            pair = (str(row[text_i]), str(row[value_i]))
            if pair not in seen:
                seen.add(pair)
                values.append({"text": pair[0], "value": pair[1]})
        return values

    def _json(self, text):
        try:
            payload = json.loads(text)
        except ValueError:
            raise DataSourceError("Kaynak geçerli JSON yanıtı döndürmedi") from None
        if not isinstance(payload, dict):
            raise DataSourceError("Kaynak beklenmeyen yanıt döndürdü")
        return payload


class TrinoDataSource(SQLEngine):
    """Data lake query engine: Trino, Presto or Starburst over Hive / Iceberg / Delta Lake catalogs."""

    type = "trino"
    dialect = "trino"

    @classmethod
    def validate_config(cls, url, data, settings):
        url, clean = _common_http(url, data, settings)
        clean["user"] = _name(data.get("user"), "kullanıcı", default="openreporting")
        clean["catalog"] = _name(data.get("catalog"), "katalog")
        clean["schema"] = _name(data.get("schema"), "şema")
        clean["flavor"] = "presto" if data.get("flavor") == "presto" else "trino"
        return url, clean

    def auth_headers(self):
        user = clean_header(self.options.get("user") or "openreporting")
        password = self.secure.get("password")
        if password:
            raw = f"{user}:{clean_header(password, 'parola')}".encode()
            return {"Authorization": "Basic " + base64.b64encode(raw).decode()}
        return super().auth_headers()

    def _headers(self):
        prefix = "X-Presto-" if self.options.get("flavor") == "presto" else "X-Trino-"
        headers = {prefix + "User": clean_header(self.options.get("user") or "openreporting"), prefix + "Source": "openreporting", "Content-Type": "text/plain"}
        for key in ("catalog", "schema"):
            if self.options.get(key):
                headers[prefix + key.title()] = clean_header(self.options[key])
        return headers

    def run(self, sql):
        headers = self._headers()
        payload = self._json(self.fetch("/v1/statement", method="POST", body=sql, headers=headers))
        columns, rows, deadline = None, [], self.deadline()
        while True:
            if payload.get("error"):
                message = str((payload["error"] or {}).get("message") or "sorgu hatası")[:300]
                raise DataSourceError(f"Trino: {message}")
            columns = payload.get("columns") or columns
            rows.extend(payload.get("data") or [])
            if len(rows) > self.row_limit:
                self._cancel(payload.get("nextUri"), headers)
                self.check_rows(rows)
            next_uri = payload.get("nextUri")
            if not next_uri:
                break
            if time.monotonic() > deadline:
                self._cancel(next_uri, headers)
                raise DataSourceError("Sorgu zaman aşımına uğradı; zaman aralığını daraltın")
            payload = self._json(self.fetch(raw_path=self._statement_path(next_uri), headers=headers))
        columns = [{"name": c.get("name", f"c{i}"), "type": c.get("type", "varchar")} for i, c in enumerate(columns or [])]
        return columns, rows

    def _statement_path(self, next_uri):
        path = self.same_origin_path(next_uri)
        if not path.startswith("/v1/statement/") or ".." in path or "//" in path:
            raise DataSourceError("Trino beklenmeyen bir takip adresi döndürdü; izlenmedi")
        return path

    def _cancel(self, next_uri, headers):
        if not next_uri:
            return
        try:
            self.fetch(raw_path=self._statement_path(next_uri), method="DELETE", headers=headers, ok=(200, 204))
        except DataSourceError:
            pass  # best effort: the coordinator also abandons queries whose client went away

    def health(self):
        columns, rows = self.run("SELECT current_user, version()")
        user, version = (rows[0] + [None, None])[:2] if rows else (None, None)
        return {"status": "ok", "message": f"Trino/Presto {version or ''} · kullanıcı {user or '?'} · salt-okunur rol önerilir".strip()}


class DatabricksDataSource(SQLEngine):
    """Databricks SQL warehouse (lakehouse) through the Statement Execution API."""

    type = "databricks"
    default_format = "sqlstring_escaped"
    dialect = "databricks"
    _PATH = "/api/2.0/sql/statements"

    @classmethod
    def validate_config(cls, url, data, settings):
        url, clean = _common_http(url, data, settings)
        warehouse = str(data.get("warehouse_id") or "").strip()
        if not _WAREHOUSE.match(warehouse):
            raise DataSourceError("SQL warehouse kimliği gerekli (Databricks → SQL Warehouses → Connection details)")
        clean["warehouse_id"] = warehouse
        clean["catalog"] = _name(data.get("catalog"), "katalog")
        clean["schema"] = _name(data.get("schema"), "şema")
        return url, clean

    def run(self, sql):
        request = {
            "statement": sql,
            "warehouse_id": self.options["warehouse_id"],
            "wait_timeout": "30s",
            "on_wait_timeout": "CONTINUE",
            "disposition": "INLINE",
            "format": "JSON_ARRAY",
            "row_limit": self.row_limit + 1,
        }
        for key in ("catalog", "schema"):
            if self.options.get(key):
                request[key] = self.options[key]
        headers = {"Content-Type": "application/json"}
        payload = self._json(self.fetch(self._PATH, method="POST", body=json.dumps(request), headers=headers))
        statement_id = str(payload.get("statement_id") or "")
        if not re.fullmatch(r"[A-Za-z0-9-]{1,80}", statement_id):
            raise DataSourceError("Databricks yanıtında ifade kimliği yok")
        deadline = self.deadline()
        while (payload.get("status") or {}).get("state") in ("PENDING", "RUNNING"):
            if time.monotonic() > deadline:
                self._cancel(statement_id)
                raise DataSourceError("Sorgu zaman aşımına uğradı; zaman aralığını daraltın")
            time.sleep(1)
            payload = self._json(self.fetch(f"{self._PATH}/{statement_id}"))
        status = payload.get("status") or {}
        if status.get("state") != "SUCCEEDED":
            message = str((status.get("error") or {}).get("message") or status.get("state") or "sorgu hatası")[:300]
            raise DataSourceError(f"Databricks: {message}")
        manifest = payload.get("manifest") or {}
        columns = [
            {"name": c.get("name", f"c{i}"), "type": c.get("type_name", "STRING")} for i, c in enumerate((manifest.get("schema") or {}).get("columns") or [])
        ]
        result = payload.get("result") or {}
        rows = list(result.get("data_array") or [])
        while result.get("next_chunk_internal_link"):
            self.check_rows(rows)
            link = str(result["next_chunk_internal_link"])
            if not re.fullmatch(rf"{re.escape(self._PATH)}/{re.escape(statement_id)}/result/chunks/\d+(\?[A-Za-z0-9_=&-]*)?", link):
                raise DataSourceError("Databricks beklenmeyen sonuç bağlantısı döndürdü")
            result = self._json(self.fetch(raw_path=link))
            rows.extend(result.get("data_array") or [])
        if manifest.get("truncated"):
            raise DataSourceError(f"Satır sınırı ({self.row_limit}) aşıldı; sorguyu daraltın veya toplulaştırın")
        self.check_rows(rows)
        return columns, rows

    def _cancel(self, statement_id):
        try:
            self.fetch(f"{self._PATH}/{statement_id}/cancel", method="POST", body="{}", headers={"Content-Type": "application/json"})
        except DataSourceError:
            pass

    def health(self):
        columns, rows = self.run("SELECT current_user(), current_version().dbsql_version")
        user, version = (list(rows[0]) + [None, None])[:2] if rows else (None, None)
        return {"status": "ok", "message": f"Databricks SQL {version or ''} · kullanıcı {user or '?'}".strip()}


class ClickHouseDataSource(SQLEngine):
    """ClickHouse over its HTTP interface; read-only is enforced by the server (readonly setting)."""

    type = "clickhouse"
    default_format = "sqlstring_escaped"
    dialect = "clickhouse"

    @classmethod
    def validate_config(cls, url, data, settings):
        url, clean = _common_http(url, data, settings)
        clean["user"] = _name(data.get("user"), "kullanıcı", default="default")
        clean["database"] = _name(data.get("database"), "veritabanı")
        # A user whose profile is already readonly=1 cannot receive settings; then rely on the profile.
        clean["readonly_profile"] = bool(data.get("readonly_profile"))
        return url, clean

    def auth_headers(self):
        headers = {"X-ClickHouse-User": clean_header(self.options.get("user") or "default")}
        if self.secure.get("password"):
            headers["X-ClickHouse-Key"] = clean_header(self.secure["password"], "parola")
        if self.options.get("database"):
            headers["X-ClickHouse-Database"] = clean_header(self.options["database"])
        return headers

    def run(self, sql):
        params = {"default_format": "JSONCompact"}
        if not self.options.get("readonly_profile"):
            params.update(
                readonly="2",
                max_result_rows=str(self.row_limit + 1),
                result_overflow_mode="throw",
                date_time_output_format="iso",
                output_format_json_quote_64bit_integers="0",
                max_execution_time=str(int(self.options.get("timeout", 30)) * 2),
            )
        text = self.fetch("/?" + urlencode(params), method="POST", body=sql, headers={"Content-Type": "text/plain; charset=utf-8"})
        payload = self._json(text)
        columns = [{"name": c.get("name", f"c{i}"), "type": c.get("type", "String")} for i, c in enumerate(payload.get("meta") or [])]
        rows = payload.get("data") or []
        self.check_rows(rows)
        return columns, rows

    def http_error(self, response):
        if response.status == 500 or response.status == 400:
            return "ClickHouse sorguyu reddetti; SQL sözdizimini, tablo adlarını ve salt-okunur yetkiyi kontrol edin"
        return super().http_error(response)

    def health(self):
        columns, rows = self.run("SELECT version(), currentUser(), getSetting('readonly')")
        version, user, readonly = (list(rows[0]) + [None] * 3)[:3] if rows else (None, None, None)
        return {"status": "ok", "message": f"ClickHouse {version} · kullanıcı {user} · readonly={readonly}"}
