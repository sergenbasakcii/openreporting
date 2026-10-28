"""PostgreSQL driver primitives and optional real-server contract tests."""
import os
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
import psycopg
from psycopg import sql

from openreporting import db as application_db
from openreporting.postgres_store import (
    Row, bootstrap_statements, connect, init_schema, parameter_sql, schema_version, transaction,
)


@pytest.mark.parametrize("sql,expected,count", [
    ("SELECT ?, ?", "SELECT $1, $2", 2),
    ("SELECT '?' AS literal, ? AS value", "SELECT '?' AS literal, $1 AS value", 1),
    ('SELECT "?", ?', 'SELECT "?", $1', 1),
    ("SELECT 'it''s ?' , ?", "SELECT 'it''s ?' , $1", 1),
    (r"SELECT E'it\'s ?', ?", r"SELECT E'it\'s ?', $1", 1),
    ("SELECT $$? %s$$, $tag$?$tag$, ?", "SELECT $$? %s$$, $tag$?$tag$, $1", 1),
    ("SELECT ? -- ?\n, ? /* ? /* ? */ ? */", "SELECT $1 -- ?\n, $2 /* ? /* ? */ ? */", 2),
    ("SELECT 10 % 3, '90%', ?", "SELECT 10 % 3, '90%', $1", 1),
])
def test_parameter_conversion_preserves_sql_literals(sql, expected, count):
    assert parameter_sql(sql) == (expected, count)


@pytest.mark.parametrize("sql", ["SELECT 'oops", 'SELECT "oops', "/* oops", "SELECT $$oops", "SELECT $1"])
def test_malformed_or_mixed_dialect_is_rejected(sql):
    with pytest.raises(ValueError):
        parameter_sql(sql)


def test_row_supports_existing_named_positional_and_dict_access():
    row = Row(("name", "count"), ("sample", 3))
    assert row["name"] == row[0] == "sample"
    assert row[-1] == 3
    assert dict(row) == {"name": "sample", "count": 3}
    assert tuple(row) == ("sample", 3)
    with pytest.raises(KeyError):
        row["missing"]


def test_real_postgres_contract():
    dsn = os.getenv("OPENREPORTING_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("Set OPENREPORTING_TEST_POSTGRES_DSN for isolated PostgreSQL tests")
    with connect(dsn) as db:
        with transaction(db):
            db.execute("CREATE TEMP TABLE adapter_probe(id INTEGER PRIMARY KEY, value TEXT)")
            assert db.execute("INSERT INTO adapter_probe VALUES (?,?)", (1, "literal ? % '" )).rowcount == 1
        row = db.execute("SELECT * FROM adapter_probe WHERE id=?", (1,)).fetchone()
        assert dict(row) == {"id": 1, "value": "literal ? % '"}
        assert row[0] == 1
        with pytest.raises(RuntimeError):
            with transaction(db):
                db.execute("INSERT INTO adapter_probe VALUES (?,?)", (2, "rollback"))
                raise RuntimeError("rollback")
        assert db.execute("SELECT COUNT(*) FROM adapter_probe").fetchone()[0] == 1
        with pytest.raises(ValueError, match="count mismatch"):
            db.execute("SELECT ?", ())
        assert db.execute("SELECT 10 % 3, '?' AS literal").fetchone()[0] == 1


@pytest.fixture
def postgres_schema():
    dsn = os.getenv("OPENREPORTING_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("Isolated PostgreSQL server is required")
    name = "openreporting_test_" + uuid4().hex
    with connect(dsn) as admin:
        admin.raw.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
        @contextmanager
        def scoped_connection():
            with connect(dsn) as db:
                db.execute("SELECT set_config('search_path', ?, false)", (name,))
                yield db
        try:
            yield scoped_connection
        finally:
            # Only this fixture's freshly generated schema is removed.
            admin.raw.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))


def migrations():
    return {1: bootstrap_statements(application_db.MIGRATIONS[1])}


def test_postgres_initial_schema_is_atomic_and_retryable(postgres_schema):
    steps = migrations()
    with postgres_schema() as db:
        with pytest.raises(psycopg.errors.UndefinedTable):
            init_schema(db, {1: (*steps[1], "INSERT INTO missing_table VALUES (1)")}, 1)
        assert schema_version(db) == 0
        assert db.execute("SELECT to_regclass('users')").fetchone()[0] is None
        init_schema(db, steps, 1)
        init_schema(db, steps, 1)
        assert schema_version(db) == 1
        assert db.execute("SELECT COUNT(*) FROM schema_versions").fetchone()[0] == 1
        with transaction(db):
            db.execute("""INSERT INTO annotations(id,time_ms,text,created_at,created_by)
                       VALUES (?,?,?,?,?)""", ("sample", 1790000000000, "Test", "test", "test"))
        assert db.execute("SELECT time_ms FROM annotations").fetchone()[0] == 1790000000000


def test_postgres_upgrade_preserves_data_on_failure_and_rejects_newer_schema(postgres_schema):
    with postgres_schema() as db:
        steps = migrations()
        init_schema(db, steps, 1)
        with transaction(db):
            application_db.audit(db, "test", "before.upgrade", "db", "state")
        steps[2] = ("CREATE TABLE probe(id BIGINT)", "INSERT INTO missing_table VALUES (1)")
        with pytest.raises(psycopg.errors.UndefinedTable):
            init_schema(db, steps, 2)
        assert schema_version(db) == 1
        assert db.execute("SELECT to_regclass('probe')").fetchone()[0] is None
        assert application_db.verify_audit(db) == (True, None)
        assert db.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == 1
        with pytest.raises(RuntimeError, match="Missing database migration"):
            init_schema(db, {1: steps[1]}, 2)
        steps[2] = ("CREATE TABLE probe(id BIGINT)",)
        init_schema(db, steps, 2)
        with pytest.raises(RuntimeError, match="newer database schema"):
            init_schema(db, steps, 1)
        db.execute("INSERT INTO schema_versions VALUES (?,?)", (4, "test"))
        with pytest.raises(RuntimeError, match="not contiguous"):
            init_schema(db, steps, 4)


def test_postgres_audit_is_append_only_and_foreign_keys_are_enforced(postgres_schema):
    with postgres_schema() as db:
        init_schema(db, migrations(), 1)
        with transaction(db):
            application_db.audit(db, "test", "audit.check", "db", "state")
        for statement in ("UPDATE audit SET actor='changed'", "DELETE FROM audit", "TRUNCATE audit"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with transaction(db):
                    db.execute(statement)
        assert application_db.verify_audit(db) == (True, None)
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            with transaction(db):
                db.execute("INSERT INTO dashboard_stars VALUES (?,?)", ("missing", "missing"))
        assert db.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == 1


def test_postgres_concurrent_bootstrap_and_audit_preserve_chain(postgres_schema):
    def initialise(_):
        with postgres_schema() as db:
            init_schema(db, migrations(), 1)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(initialise, range(8)))
    def append(index):
        with postgres_schema() as db, transaction(db):
            application_db.audit(db, "test", "concurrent.append", "db", str(index))
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(append, range(20)))
    with postgres_schema() as db:
        assert schema_version(db) == 1
        assert db.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == 20
        assert application_db.verify_audit(db) == (True, None)
