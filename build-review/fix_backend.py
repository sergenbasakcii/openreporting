"""Backend review fixes: interrupted delivery keeps finished files, strict numeric typing, PG BIGINT, int options."""
import re
from pathlib import Path


def rep(name, old, new, count=1):
    p = Path(name)
    t = p.read_text(encoding="utf-8")
    if t.count(old) < count:
        raise SystemExit(f"{name}: not found ({t.count(old)}x): {old[:70]!r}")
    p.write_bytes(t.replace(old, new, count).encode("utf-8"))


# 1. A crash during SMTP delivery must not make a finished report undownloadable.
rep("openreporting/reporting/service.py", '''        for row in rows:
            db.execute("""UPDATE dash_report_runs SET status='needs_review',
                          delivery_status=CASE WHEN delivery_status='sending' THEN 'unknown' ELSE delivery_status END,
                          error='Çalıştırma yarıda kaldı; manuel inceleme gerekli' WHERE id=?""", (row["id"],))
            audit(db, "worker", "report_run.interrupted", "dash_report_run", row["id"])''', '''        for row in rows:
            # Unfinished renders need review. A finished run (completed/partial) whose e-mail was in
            # flight keeps its status and files; only the delivery becomes 'unknown' (never resent).
            db.execute("""UPDATE dash_report_runs SET
                          status=CASE WHEN status='running' THEN 'needs_review' ELSE status END,
                          delivery_status=CASE WHEN delivery_status='sending' THEN 'unknown' ELSE delivery_status END,
                          error=CASE WHEN status='running' THEN 'Çalıştırma yarıda kaldı; manuel inceleme gerekli'
                                     ELSE 'E-posta gönderimi yarıda kaldı; teslim durumu bilinmiyor' END
                          WHERE id=?""", (row["id"],))
            audit(db, "worker", "report_run.interrupted", "dash_report_run", row["id"])''')

# 5. HTTP JSON/CSV: identifiers such as "007" or "0532..." stay text; only real numbers are numeric.
rep("openreporting/datasources/http_sources.py", "MAX_BYTES = 8_000_000\n", '''MAX_BYTES = 8_000_000
# Plain decimal without leading zeros (identifiers like "007", "0532..." and "1e3" stay text).
DECIMAL = re.compile(r"^-?(0|[1-9][0-9]*)(\\.[0-9]+)?$")


def _numeric(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return finite(value) is not None
    return isinstance(value, str) and bool(DECIMAL.match(value.strip()))
''')
rep("openreporting/datasources/http_sources.py", "import json\n", "import json\nimport re\n")
rep("openreporting/datasources/http_sources.py",
    "            numeric = bool(present) and all(not isinstance(v, (dict, list, bool)) and finite(v) is not None for v in present)",
    "            numeric = bool(present) and all(_numeric(v) for v in present)")

# 6. Non-numeric timeout/limit options are a validation error, not a crash.
p = Path("openreporting/datasources/__init__.py")
t = p.read_text(encoding="utf-8")
t2 = re.sub(r'int\(data\.get\("([a-z_]+)", (\d+)\)\)', r'_int(data, "\1", \2)', t)
if t2 == t:
    raise SystemExit("datasources: no int() options found")
t2 = t2.replace("def validate(kind, url, json_data, settings):", '''def _int(data, key, default):
    try:
        return int(data.get(key, default))
    except (TypeError, ValueError):
        raise DataSourceError(f"{key} bir tam sayı olmalı") from None


def validate(kind, url, json_data, settings):''', 1)
p.write_bytes(t2.encode("utf-8"))

# 7. PostgreSQL: later migrations use 64-bit integers like the bootstrap.
for n in (3, 4, 5):
    rep("openreporting/db.py", f"POSTGRES_MIGRATIONS[{n}] = MIGRATIONS[{n}]\n",
        f"POSTGRES_MIGRATIONS[{n}] = postgres_store.widen_integers(MIGRATIONS[{n}])\n")
rep("openreporting/postgres_store.py", "def bootstrap_statements(sqlite_initial_statements):", '''def widen_integers(statements):
    """SQLite INTEGER is 64-bit; use BIGINT so PostgreSQL columns keep the same range."""
    return tuple(re.sub(r"\\bINTEGER\\b", "BIGINT", statement) for statement in statements)


def bootstrap_statements(sqlite_initial_statements):''')
print("backend fixes applied")
