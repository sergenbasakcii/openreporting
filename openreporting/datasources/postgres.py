"""PostgreSQL / TimescaleDB datasource with Grafana SQL macros.

Layers of protection for user-written SQL (the database role must still be
SELECT-only — this is defence in depth, not a substitute):

* lexical guard: one SELECT/WITH/VALUES statement, no E-strings or dollar quoting
  (constructs the scanner cannot track), no data-modifying CTE / SELECT INTO;
* the statement is wrapped as ``SELECT * FROM (...) LIMIT $1`` and sent with a
  bound parameter, i.e. the *extended* protocol, which the server refuses to
  run with more than one command; the row cap is enforced server-side;
* the session starts with ``default_transaction_read_only=on`` and
  ``statement_timeout`` via connection options, plus a READ ONLY transaction.
"""

import hashlib
import logging
import math
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ..frames import finite, table_frame, ts_frame
from ..timerange import parse_duration
from .base import DataSource, DataSourceError, QueryResult

log = logging.getLogger(__name__)

SSL_MODES = ("disable", "require", "verify-ca", "verify-full")
_MACRO = re.compile(
    r"\$__(timeFilter|timeGroupAlias|timeGroup|unixEpochFilter|unixEpochGroupAlias|"
    r"unixEpochGroup|timeFrom|timeTo|unixEpochFrom|unixEpochTo|interval_s|interval)\b(\(([^()]*)\))?"
)
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")
_WRITE_CTE = re.compile(r"\bas\s*\(\s*(insert|update|delete|merge)\b", re.I)


def _segments(sql):
    """Split SQL into (kind, text) runs: True = code, False = quoted, None = comment."""
    out, i, start, n = [], 0, 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch in ("'", '"'):
            if i > start:
                out.append((True, sql[start:i]))
            j = i + 1
            while j < n:
                if sql[j] == ch:
                    if j + 1 < n and sql[j + 1] == ch:  # doubled quote inside a literal
                        j += 2
                        continue
                    break
                j += 1
            out.append((False, sql[i : j + 1]))
            i = start = j + 1
        elif sql.startswith("--", i) or sql.startswith("/*", i):
            if i > start:
                out.append((True, sql[start:i]))
            if sql.startswith("--", i):
                found = sql.find("\n", i)
                j = n if found < 0 else found
            else:
                found = sql.find("*/", i + 2)
                j = n if found < 0 else found + 2
            out.append((None, " "))
            i = start = j
        else:
            i += 1
    if start < n:
        out.append((True, sql[start:]))
    return out


def strip_sql_comments(sql):
    return "".join(text for kind, text in _segments(sql) if kind is not None)


def _unquoted(sql):
    return "".join(text if kind else ("''" if kind is False else " ") for kind, text in _segments(sql))


def _special_literal(sql):
    """True when a string literal uses an E/U&/B/X prefix (escape rules we do not model)."""
    previous = ""
    for kind, text in _segments(sql):
        if kind is False and text.startswith("'") and re.search(r"(?:^|[^A-Za-z0-9_$])(?:[eE]|[uU]&|[bB]|[xX])$", previous):
            return True
        if kind is not None:
            previous = text if kind else "x"
    return False


def guard_sql(sql):
    """Reject anything except one read statement (writes also fail in READ ONLY)."""
    if not isinstance(sql, str) or not sql.strip():
        raise DataSourceError("SQL sorgusu boş")
    if len(sql) > 100_000:
        raise DataSourceError("SQL sorgusu çok uzun")
    if "\x00" in sql:
        raise DataSourceError("SQL sorgusunda geçersiz karakter")
    body = strip_sql_comments(sql).strip().rstrip(";").strip()
    bare = _unquoted(body)
    # Constructs the scanner above cannot follow are refused outright.
    if _special_literal(body) or re.search(r"\$[A-Za-z_0-9]*\$", bare):
        raise DataSourceError("E'...', U&'...' ve $$ tırnaklama desteklenmez; standart '...' kullanın")
    if ";" in bare:
        raise DataSourceError("Tek bir SQL ifadesine izin verilir")
    first = re.match(r"^[\s(]*(\w+)", bare)
    if not first or first.group(1).lower() not in ("select", "with", "values", "table"):
        raise DataSourceError("Yalnızca SELECT / WITH sorgularına izin verilir")
    # Writes are impossible inside the READ ONLY transaction; these checks give a clear message early.
    if _WRITE_CTE.search(bare):
        raise DataSourceError("Veri değiştiren CTE kullanılamaz")
    if re.search(r"\bselect\b[^()]*\binto\b", bare, re.I):
        raise DataSourceError("SELECT INTO kullanılamaz")
    return body


def _column(arg):
    arg = arg.strip()
    if not _IDENT.match(arg) and not re.fullmatch(r'"[^"]+"(\."[^"]+")?', arg):
        raise DataSourceError(f"Makro argümanı geçerli bir sütun adı olmalı: {arg}")
    return arg


# Per-dialect SQL for the shared time macros. "{iso}" is an ISO-8601 UTC instant, "{c}" a validated
# column name and "{s}" a positive integer number of seconds.
DIALECTS = {
    "postgres": {"ts": "'{iso}'::timestamptz", "group": "to_timestamp(floor(extract(epoch from {c})/{s})*{s})", "interval": "'{s} seconds'::interval"},
    "trino": {"ts": "from_iso8601_timestamp('{iso}')", "group": "from_unixtime(floor(to_unixtime({c})/{s})*{s})", "interval": "INTERVAL '{s}' SECOND"},
    "clickhouse": {
        "ts": "parseDateTime64BestEffort('{iso}', 3, 'UTC')",
        "group": "toStartOfInterval({c}, INTERVAL {s} SECOND)",
        "interval": "INTERVAL {s} SECOND",
    },
    "databricks": {"ts": "to_timestamp('{iso}')", "group": "timestamp_seconds(floor(unix_timestamp({c})/{s})*{s})", "interval": "INTERVAL {s} SECONDS"},
}


def expand_macros(sql, start, end, interval_s, dialect="postgres"):
    d = DIALECTS[dialect]
    frm, to = start.timestamp(), end.timestamp()
    iso_from = start.astimezone(timezone.utc).isoformat()
    iso_to = end.astimezone(timezone.utc).isoformat()

    def interval_arg(text):
        text = (text or "").strip()
        if text in ("", "$__interval", "auto"):
            return max(1, int(interval_s))
        return max(1, int(parse_duration(text)))

    def replace(match):
        name, args = match.group(1), match.group(3)
        parts = [p.strip() for p in args.split(",")] if args is not None else []
        if name == "timeFilter":
            column = _column(parts[0] if parts else "time")
            return f"{column} BETWEEN {d['ts'].format(iso=iso_from)} AND {d['ts'].format(iso=iso_to)}"
        if name == "unixEpochFilter":
            column = _column(parts[0] if parts else "clock")
            return f"{column} >= {int(frm)} AND {column} < {int(math.ceil(to))}"
        if name in ("timeGroup", "timeGroupAlias"):
            column = _column(parts[0] if parts else "time")
            seconds = interval_arg(parts[1] if len(parts) > 1 else "")
            expr = d["group"].format(c=column, s=seconds)
            return expr + (' AS "time"' if name == "timeGroupAlias" else "")
        if name in ("unixEpochGroup", "unixEpochGroupAlias"):
            column = _column(parts[0] if parts else "clock")
            seconds = interval_arg(parts[1] if len(parts) > 1 else "")
            expr = f"(floor({column}/{seconds})*{seconds})"
            return expr + (' AS "time"' if name == "unixEpochGroupAlias" else "")
        if name == "timeFrom":
            return d["ts"].format(iso=iso_from)
        if name == "timeTo":
            return d["ts"].format(iso=iso_to)
        if name == "unixEpochFrom":
            return str(int(frm))
        if name == "unixEpochTo":
            return str(int(math.ceil(to)))
        if name == "interval_s":
            return str(max(1, int(interval_s)))
        return d["interval"].format(s=max(1, int(interval_s)))

    # Expand macros only in SQL code, never inside string literals produced by
    # variable interpolation (a value containing "$__timeFrom" stays literal).
    return "".join(_MACRO.sub(replace, text) if kind else text for kind, text in _segments(sql))


def _epoch_ms(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return int(value.timestamp() * 1000)
    number = finite(value)
    if number is None:
        return None
    return int(number * 1000) if number < 1e11 else int(number)


def rows_to_frames(columns, rows, fmt, ref_id):
    names = [c.lower() for c in columns]
    if fmt == "table" or "time" not in names:
        types = []
        for index, _ in enumerate(columns):
            sample = next((r[index] for r in rows if r[index] is not None), None)
            types.append(
                "time"
                if isinstance(sample, datetime)
                else "number"
                if isinstance(sample, (int, float)) or (sample is not None and finite(sample) is not None and not isinstance(sample, str))
                else "string"
            )
        table_rows = []
        for row in rows:
            converted = []
            for value, kind in zip(row, types):
                if kind == "time":
                    converted.append(_epoch_ms(value))
                elif kind == "number":
                    converted.append(finite(value))
                else:
                    converted.append(None if value is None else str(value))
            table_rows.append(converted)
        return [table_frame("Sorgu sonucu", [{"name": c, "type": t} for c, t in zip(columns, types)], table_rows, ref_id=ref_id)]
    time_index = names.index("time")
    metric_index = names.index("metric") if "metric" in names else None
    value_indexes = [i for i in range(len(columns)) if i not in (time_index, metric_index)]
    series = {}
    for row in rows:
        ts = _epoch_ms(row[time_index])
        if ts is None:
            continue
        for index in value_indexes:
            label = str(row[metric_index]) if metric_index is not None else columns[index]
            if metric_index is not None and len(value_indexes) > 1:
                label = f"{label} {columns[index]}"
            series.setdefault(label, []).append([ts, finite(row[index])])
    frames = []
    for name, points in series.items():
        points.sort(key=lambda p: p[0])
        frames.append(ts_frame(name, points, labels={"metric": name}, ref_id=ref_id))
    return frames


class PostgresDataSource(DataSource):
    type = "postgres"
    default_format = "sqlstring"

    def __init__(self, record, secure, settings, **_):
        super().__init__(record, secure, settings)
        self.timeout_ms = int(self.options.get("timeout_ms", getattr(settings, "query_timeout_ms", 30000)))
        self.max_rows = int(self.options.get("max_rows", getattr(settings, "max_rows", 200000)))

    def _conninfo(self):
        from psycopg import conninfo

        options = self.options
        sslmode = options.get("sslmode", "verify-full")
        if sslmode not in SSL_MODES:
            raise DataSourceError("Invalid sslmode")
        params = {
            "host": options.get("host", ""),
            "port": int(options.get("port", 5432) or 5432),
            "dbname": options.get("database", ""),
            "user": options.get("user", ""),
            "sslmode": sslmode,
            "connect_timeout": 10,
            "application_name": "openreporting-readonly",
        }
        if not params["host"] or not params["dbname"] or not params["user"]:
            raise DataSourceError("PostgreSQL host, database and user are required")
        if self.secure.get("password"):
            params["password"] = self.secure["password"]
        params["options"] = (
            f"-c statement_timeout={self.timeout_ms} -c default_transaction_read_only=on "
            f"-c idle_in_transaction_session_timeout={max(self.timeout_ms * 2, 60000)}"
        )
        if options.get("ca_pem"):
            cert_dir = Path(self.settings.data_dir) / "certs"
            cert_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = cert_dir / f"{self.uid}.pem"
            if not path.exists() or path.read_text(encoding="utf8") != options["ca_pem"]:
                with tempfile.NamedTemporaryFile("w", dir=cert_dir, delete=False, encoding="utf8") as handle:
                    handle.write(options["ca_pem"])
                Path(handle.name).replace(path)
            params["sslrootcert"] = str(path)
        return conninfo.make_conninfo(**params)

    def _connect(self):
        import psycopg

        try:
            connection = psycopg.connect(self._conninfo())
        except psycopg.Error as exc:
            log.warning("PostgreSQL connect failed for datasource %s: %s", self.uid, exc)
            raise DataSourceError("PostgreSQL bağlantısı kurulamadı (ayrıntı sunucu günlüğünde)") from exc
        connection.read_only = True
        return connection

    def execute(self, sql, params=()):
        """Run an internal, parameterised query (extended protocol) with the row cap."""
        import psycopg

        with self._connect() as connection:
            with connection.cursor() as cursor:
                try:
                    cursor.execute(sql, params)
                    columns = [c.name for c in cursor.description or []]
                    rows = cursor.fetchmany(self.max_rows + 1)
                except psycopg.Error as exc:
                    raise DataSourceError(f"SQL hatası: {str(exc).splitlines()[0]}") from exc
        if len(rows) > self.max_rows:
            raise DataSourceError(f"Sorgu {self.max_rows} satır sınırını aştı; eksik sonuç üretilmez")
        return columns, rows

    def execute_user_sql(self, sql, user=""):
        """User SQL wrapped with a server-side LIMIT and sent with a bound parameter.

        The bound parameter forces the extended query protocol, so PostgreSQL itself
        rejects any attempt to smuggle a second statement past the lexical guard.
        """
        body = guard_sql(sql)
        log.info("SQL query datasource=%s user=%s sha256=%s", self.uid, user or "-", hashlib.sha256(body.encode()).hexdigest()[:16])
        wrapped = "SELECT * FROM (\n" + body.replace("%", "%%") + "\n) AS openreporting_q LIMIT %s"
        return self.execute(wrapped, (self.max_rows + 1,))

    # Fixed aggregate expressions; trend sum/count use num so SQL and API paths agree.
    HISTORY_MODES = {
        "history_avg": "AVG(value::double precision)",
        "history_min": "MIN(value::double precision)",
        "history_max": "MAX(value::double precision)",
        "history_sum": "SUM(value::double precision)",
        "history_count": "COUNT(value)::double precision",
        # Fixed expressions (no user input): honour last/first/median instead of averaging them.
        "history_last": "(ARRAY_AGG(value::double precision ORDER BY clock DESC))[1]",
        "history_first": "(ARRAY_AGG(value::double precision ORDER BY clock ASC))[1]",
        "history_median": "PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY value::double precision)",
        "trend_avg": "SUM(value_avg::double precision * num) / NULLIF(SUM(num), 0)",
        "trend_min": "MIN(value_min::double precision)",
        "trend_max": "MAX(value_max::double precision)",
        "trend_sum": "SUM(value_avg::double precision * num)",
        "trend_count": "SUM(num)::double precision",
    }

    def bucketed_history(self, table, mode, itemids, start, end, bucket, anchor=0):
        from psycopg import sql as pgsql

        if not _IDENT.match(table):
            raise DataSourceError("Invalid history table configuration")
        expression = self.HISTORY_MODES.get(mode)
        if expression is None:
            raise DataSourceError("Invalid aggregate")
        query = pgsql.SQL(
            "SELECT itemid, %s + ((clock - %s) / %s) * %s AS t, {} FROM {} WHERE itemid = ANY(%s) AND clock >= %s AND clock < %s GROUP BY 1, 2 ORDER BY 1, 2"
        ).format(pgsql.SQL(expression), pgsql.Identifier(*table.split(".")))
        _, rows = self.execute(query, (anchor, anchor, bucket, bucket, list(itemids), start, end))
        return rows

    def query(self, target, ctx):
        raw = target.get("rawSql") or ""
        body = guard_sql(raw)
        expanded = expand_macros(body, ctx.start, ctx.end, ctx.interval_s)
        columns, rows = self.execute_user_sql(expanded, ctx.user)
        frames = rows_to_frames(columns, rows, target.get("format", "time_series"), target.get("refId", "A"))
        return QueryResult(frames, [] if rows else ["Sorgu satır döndürmedi (NO DATA)"], {"executedQueryString": expanded, "rows": len(rows)})

    def metric_find(self, query, ctx=None):
        text = query.get("rawSql") if isinstance(query, dict) else str(query or "")
        body = guard_sql(text)
        if ctx is not None:
            body = expand_macros(body, ctx.start, ctx.end, ctx.interval_s)
        columns, rows = self.execute_user_sql(body, ctx.user if ctx is not None else "")
        names = [c.lower() for c in columns]
        text_i = names.index("__text") if "__text" in names else 0
        value_i = names.index("__value") if "__value" in names else text_i
        seen, values = set(), []
        for row in rows[:10000]:
            text_value, value = str(row[text_i]), str(row[value_i])
            if (text_value, value) not in seen:
                seen.add((text_value, value))
                values.append({"text": text_value, "value": value})
        return values

    def health(self):
        columns, rows = self.execute("SELECT version(), current_user, current_setting('transaction_read_only')")
        version, user, read_only = rows[0]
        return {"status": "ok", "message": f"{str(version).split(',')[0]} · kullanıcı {user} · salt-okunur oturum: {read_only}"}
