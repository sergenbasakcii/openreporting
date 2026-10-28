"""PostgreSQL driver primitives and optional real-server contract tests."""
import os

import pytest

from openreporting.postgres_store import Row, connect, parameter_sql, transaction


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
