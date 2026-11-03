"""One-way, offline copy of a SQLite application store into an empty PostgreSQL database.

Schema creation, copy and verification run in ONE PostgreSQL transaction: any failure leaves
the target exactly as empty as it was. The source is opened read-only and never modified.
Encrypted values are copied verbatim, so the new deployment must use the same key file.
"""

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from psycopg import sql

from . import postgres_store
from .db import CURRENT_VERSION, POSTGRES_MIGRATIONS, verify_audit

BATCH = 1000


class MigrationError(RuntimeError):
    """Refusal or verification failure; the message never contains row data or credentials."""


def _source(path):
    path = Path(path)
    if not path.is_file():
        raise MigrationError("Kaynak SQLite dosyası bulunamadı")
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
    db.row_factory = sqlite3.Row
    return db


def _check_source(db):
    from .sqlite_store import schema_version

    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise MigrationError("Kaynak veritabanı bütünlük kontrolünden geçmedi")
    if schema_version(db) != CURRENT_VERSION:
        raise MigrationError(f"Kaynak şema sürümü {CURRENT_VERSION} olmalı; önce bu sürümle bir kez açıp yükseltin")
    if not verify_audit(db)[0]:
        raise MigrationError("Kaynak denetim zinciri bozuk; taşıma yapılmadı")


def _tables(db):
    """Application tables ordered so that referenced tables are copied first."""
    names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name<>'schema_versions'")]
    deps = {n: {r["table"] for r in db.execute(f'PRAGMA foreign_key_list("{n}")')} - {n} for n in names}
    ordered = []
    while deps:
        ready = sorted(n for n, d in deps.items() if not d - set(ordered))
        if not ready:
            raise MigrationError("Tablolar arasında çözülemeyen bağımlılık var")
        ordered.extend(ready)
        for n in ready:
            del deps[n]
    return ordered


def _columns_sqlite(db, table):
    return [r["name"] for r in db.execute(f'PRAGMA table_info("{table}")')]


def _columns_pg(db, table):
    return {r[0] for r in db.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=?", (table,))}


def _digest(rows):
    """Order-independent, streaming content digest: row count plus the sum of row hashes mod 2^256.

    Collations differ between SQLite and PostgreSQL, so row order cannot be compared; nothing is
    held in memory beyond the running total.
    """
    count, total = 0, 0
    for row in rows:
        row_hash = hashlib.sha256(json.dumps(list(row), default=str, separators=(",", ":")).encode()).digest()
        total = (total + int.from_bytes(row_hash, "big")) % (1 << 256)
        count += 1
    return f"{count}:{total:064x}"


def _target_rows(dst, table, columns):
    """Read the copied table back through a server-side cursor (bounded memory)."""
    cursor = dst.raw.cursor(name=f"verify_{table}")
    cursor.itersize = BATCH
    cursor.execute(sql.SQL("SELECT {} FROM {}").format(sql.SQL(",").join(map(sql.Identifier, columns)), sql.Identifier(table)))
    try:
        yield from cursor
    finally:
        cursor.close()


def _target_is_empty(db):
    if postgres_store.schema_version(db) != 0:
        return False
    return db.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema=current_schema()").fetchone()[0] == 0


def migrate(source_path, dsn, *, services_stopped=False, timeout_ms=300000):
    if not services_stopped:
        raise MigrationError("Bakım gerekli: bütün web ve worker süreçlerini durdurup --services-stopped ile çalıştırın")
    if not dsn:
        raise MigrationError("Hedef için OPENREPORTING_DATABASE_URL tanımlı olmalı")
    summary = {}
    with closing(_source(source_path)) as src:
        src.execute("BEGIN")  # one consistent snapshot of the whole source
        _check_source(src)
        tables = _tables(src)
        with postgres_store.connect(dsn, timeout_ms=timeout_ms) as dst, postgres_store.transaction(dst):
            if not _target_is_empty(dst):
                raise MigrationError("Hedef PostgreSQL boş değil; mevcut veriyle birleştirme yapılmaz")
            postgres_store.init_schema(dst, POSTGRES_MIGRATIONS, CURRENT_VERSION)
            cursor = dst.raw.cursor()
            for table in tables:
                columns = _columns_sqlite(src, table)
                if set(columns) != _columns_pg(dst, table):
                    raise MigrationError(f"{table} tablosunun kolonları iki veritabanında farklı")
                insert = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                    sql.Identifier(table),
                    sql.SQL(",").join(map(sql.Identifier, columns)),
                    # The adapter's connections use server-side $n parameters (RawCursor).
                    sql.SQL(",").join(sql.SQL(f"${i}") for i in range(1, len(columns) + 1)),
                )
                select = 'SELECT {} FROM "{}"'.format(",".join(f'"{c}"' for c in columns), table)
                copied, rows = 0, src.execute(select)
                while batch := rows.fetchmany(BATCH):
                    cursor.executemany(insert, [tuple(r) for r in batch])
                    copied += len(batch)
                source_digest = _digest(src.execute(select))
                if source_digest.split(":")[0] != str(copied) or _digest(_target_rows(dst, table, columns)) != source_digest:
                    raise MigrationError(f"{table} tablosu doğrulanamadı; taşıma geri alındı")
                summary[table] = copied
            # Explicit ids were inserted into identity columns; continue numbering after them.
            for table, column in dst.execute("""SELECT table_name,column_name FROM information_schema.columns
                    WHERE table_schema=current_schema() AND is_identity='YES'""").fetchall():
                cursor.execute(
                    sql.SQL("SELECT setval(pg_get_serial_sequence({}, {}), COALESCE((SELECT max({}) FROM {}), 0) + 1, false)").format(
                        sql.Literal(table), sql.Literal(column), sql.Identifier(column), sql.Identifier(table)
                    )
                )
            ok, broken = verify_audit(dst)
            if not ok:
                raise MigrationError(f"Hedefte denetim zinciri doğrulanamadı (kayıt {broken}); taşıma geri alındı")
    return {"ok": True, "schema_version": CURRENT_VERSION, "tables": len(summary), "rows": summary}
