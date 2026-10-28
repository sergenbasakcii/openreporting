"""PostgreSQL connection primitives; not yet enabled as an application backend.

Only application-owned SQL may use this adapter. Data source queries use their
own read-only driver and must never pass through the qmark conversion below.
"""
import re
from contextlib import contextmanager
from contextvars import ContextVar

import psycopg

# Serialize write transactions until finer row locking is introduced. This
# preserves SQLite's single-writer guarantee, including audit-chain appends.
WRITE_LOCK = 0x4F50454E525054
WORKER_LOCK = WRITE_LOCK + 1
_worker_guard = ContextVar("openreporting_worker_guard", default=None)


class WorkerOwnershipLost(RuntimeError):
    pass


class WorkerGuard:
    def __init__(self, db):
        self.db = db

    def ensure(self):
        try:
            self.db.raw.execute("SELECT 1").fetchone()
        except psycopg.Error:
            raise WorkerOwnershipLost("PostgreSQL worker ownership connection was lost; stopping") from None


def assert_worker_ownership():
    guard = _worker_guard.get()
    if guard is not None:
        guard.ensure()


@contextmanager
def exclusive_worker(dsn, *, timeout_ms=30000):
    with connect(dsn, timeout_ms=timeout_ms) as db:
        if not db.execute("SELECT pg_try_advisory_lock(?)", (WORKER_LOCK,)).fetchone()[0]:
            raise RuntimeError("A report worker is already active for this PostgreSQL database")
        guard = WorkerGuard(db)
        token = _worker_guard.set(guard)
        try:
            yield guard
        finally:
            _worker_guard.reset(token)
            # Closing the dedicated session releases the lock, even on errors.


class Row:
    """Named and positional access compatible with existing application callers."""
    def __init__(self, names, values):
        self._names = names
        self._values = tuple(values)
        self._indices = {name: i for i, name in enumerate(names)}

    def __getitem__(self, key):
        return self._values[self._indices[key]] if isinstance(key, str) else self._values[key]

    def keys(self):
        return self._names

    def __len__(self):
        return len(self._values)

    def __iter__(self):
        return iter(self._values)


def row_factory(cursor):
    names = tuple(column.name for column in cursor.description) if cursor.description else ()
    return lambda values: Row(names, values)


def parameter_sql(sql):
    """Convert internal qmarks to PostgreSQL $n, preserving quoted text/comments.

    Return SQL and parameter count. Native $n placeholders and JSON question-mark
    operators are outside this internal dialect; don't mix dialects.
    """
    output, index, count = [], 0, 0
    while index < len(sql):
        start = index
        char = sql[index]
        if sql.startswith("--", index):
            end = sql.find("\n", index)
            index = len(sql) if end < 0 else end + 1
        elif sql.startswith("/*", index):
            index += 2
            depth = 1
            while index < len(sql) and depth:
                if sql.startswith("/*", index):
                    depth += 1
                    index += 2
                elif sql.startswith("*/", index):
                    depth -= 1
                    index += 2
                else:
                    index += 1
            if depth:
                raise ValueError("Unterminated SQL comment")
        elif char in ("'", '"'):
            escaped = char == "'" and index > 0 and sql[index - 1] in "eE" and (index < 2 or not (sql[index - 2].isalnum() or sql[index - 2] == "_"))
            index += 1
            while index < len(sql):
                if escaped and sql[index] == "\\":
                    index += 2
                elif sql[index] == char:
                    index += 1
                    if index < len(sql) and sql[index] == char:
                        index += 1
                    else:
                        break
                else:
                    index += 1
            else:
                raise ValueError("Unterminated SQL quote")
        elif char == "$":
            match = re.match(r"\$(?:[A-Za-z_][A-Za-z_0-9]*)?\$", sql[index:])
            if not match:
                raise ValueError("Native PostgreSQL parameters are not supported here")
            delimiter = match.group()
            end = sql.find(delimiter, index + len(delimiter))
            if end < 0:
                raise ValueError("Unterminated SQL dollar quote")
            index = end + len(delimiter)
        elif char == "?":
            count += 1
            output.append(f"${count}")
            index += 1
            continue
        else:
            index += 1
        output.append(sql[start:index])
    return "".join(output), count


class Connection:
    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql, parameters=()):
        query, count = parameter_sql(sql)
        values = tuple(parameters)
        if count != len(values):
            raise ValueError("SQL parameter count mismatch")
        return self.raw.execute(query, values or None)

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()


@contextmanager
def connect(dsn, *, timeout_ms=30000):
    if type(timeout_ms) is not int or not 1000 <= timeout_ms <= 300000:
        raise ValueError("Invalid database timeout")
    raw = psycopg.connect(dsn, autocommit=True, connect_timeout=10,
                          cursor_factory=psycopg.RawCursor, row_factory=row_factory)
    try:
        raw.execute("SELECT set_config('statement_timeout', $1, false)", (str(timeout_ms),))
        raw.execute("SELECT set_config('lock_timeout', $1, false)", (str(timeout_ms),))
        yield Connection(raw)
    finally:
        raw.close()


@contextmanager
def transaction(db):
    # psycopg handles rollback on BaseException and nested savepoints.
    with db.raw.transaction():
        db.raw.execute("SELECT pg_advisory_xact_lock($1)", (WRITE_LOCK,))
        yield


def schema_version(db):
    if db.execute("SELECT to_regclass('schema_versions')").fetchone()[0] is None:
        return 0
    versions = [row[0] for row in db.execute("SELECT version FROM schema_versions ORDER BY version")]
    if any(version != expected for expected, version in enumerate(versions, 1)):
        raise RuntimeError("Database migration history is not contiguous")
    return versions[-1] if versions else 0


def bootstrap_statements(sqlite_initial_statements):
    """Adapt only the known v1 bootstrap; future PostgreSQL migrations are explicit.

    Keep existing time/JSON/ID text representations so migration and hash-chain
    verification do not silently reformat persisted values. Milliseconds and
    counters use BIGINT; SQLite INTEGER is also a signed 64-bit value.
    """
    statements = []
    for statement in sqlite_initial_statements:
        statement = statement.replace("INTEGER PRIMARY KEY AUTOINCREMENT",
                                      "BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY")
        statements.append(re.sub(r"\bINTEGER\b", "BIGINT", statement))
    statements.extend((
        """CREATE FUNCTION reject_audit_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Audit records are append-only' USING ERRCODE = '42501';
        END;
        $$""",
        """CREATE TRIGGER audit_append_only BEFORE UPDATE OR DELETE OR TRUNCATE ON audit
           FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_mutation()""",
    ))
    return tuple(statements)


def init_schema(db, migrations, current_version):
    """Apply versioned PostgreSQL DDL and metadata in one locked transaction."""
    from .db import utcnow
    with transaction(db):
        version = schema_version(db)
        if version > current_version:
            raise RuntimeError("This application cannot open a newer database schema")
        for target in range(version + 1, current_version + 1):
            statements = migrations.get(target)
            if statements is None:
                raise RuntimeError(f"Missing database migration: {target}")
            for statement in statements:
                db.execute(statement)
            db.execute("INSERT INTO schema_versions(version,applied_at) VALUES (?,?)", (target, utcnow()))
