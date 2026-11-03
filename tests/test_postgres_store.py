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
    Row,
    bootstrap_statements,
    connect,
    init_schema,
    parameter_sql,
    schema_version,
    transaction,
)


@pytest.mark.parametrize(
    "sql,expected,count",
    [
        ("SELECT ?, ?", "SELECT $1, $2", 2),
        ("SELECT '?' AS literal, ? AS value", "SELECT '?' AS literal, $1 AS value", 1),
        ('SELECT "?", ?', 'SELECT "?", $1', 1),
        ("SELECT 'it''s ?' , ?", "SELECT 'it''s ?' , $1", 1),
        (r"SELECT E'it\'s ?', ?", r"SELECT E'it\'s ?', $1", 1),
        ("SELECT $$? %s$$, $tag$?$tag$, ?", "SELECT $$? %s$$, $tag$?$tag$, $1", 1),
        ("SELECT ? -- ?\n, ? /* ? /* ? */ ? */", "SELECT $1 -- ?\n, $2 /* ? /* ? */ ? */", 2),
        ("SELECT 10 % 3, '90%', ?", "SELECT 10 % 3, '90%', $1", 1),
    ],
)
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
            assert db.execute("INSERT INTO adapter_probe VALUES (?,?)", (1, "literal ? % '")).rowcount == 1
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

        scoped_connection.dsn = psycopg.conninfo.make_conninfo(dsn, options=f"-csearch_path={name}")
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
            db.execute(
                """INSERT INTO annotations(id,time_ms,text,created_at,created_by)
                       VALUES (?,?,?,?,?)""",
                ("sample", 1790000000000, "Test", "test", "test"),
            )
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


def test_application_uses_postgres_for_login_dashboard_and_report_queue(postgres_schema, tmp_path):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from openreporting.config import Settings
    from openreporting.security import create_user
    from openreporting.web import create_app

    settings = replace(
        Settings.from_env(),
        data_dir=tmp_path,
        database_url=postgres_schema.dsn,
        secure_cookie=False,
        mail_enabled=False,
        provision_testdata=True,
        secret_key_file="",
        zabbix_url="",
        zabbix_token_file="",
    )
    app = create_app(settings)
    create_user(settings, "admin1", "an-admin-password-123", "admin")
    with TestClient(app, base_url="http://localhost") as http:
        for _ in range(2):
            assert http.post("/api/login", json={"username": "admin1", "password": "wrong"}).status_code == 401
        response = http.post("/api/login", json={"username": "admin1", "password": "an-admin-password-123"})
        assert response.status_code == 200, response.text
        headers = {"X-CSRF-Token": response.json()["csrf"]}
        source = http.post(
            "/api/datasources",
            json={"name": "HTTP fixture", "type": "httpjson", "url": "https://data.example.com/items", "secureJsonData": {"token": "synthetic-token"}},
            headers=headers,
        )
        assert source.status_code == 201, source.text
        sources = http.get("/api/datasources").json()
        assert any(item["type"] == "httpjson" for item in sources)
        assert "synthetic-token" not in str(sources)
        dashboard = {"uid": "pg-test", "title": "Postgres test", "panels": []}
        saved = http.post("/api/dashboards/db", json={"dashboard": dashboard}, headers=headers)
        assert saved.status_code == 200, saved.text
        report = http.post("/api/dash-reports", json={"name": "PG report", "dashboard_uid": "pg-test", "formats": ["csv"]}, headers=headers)
        assert report.status_code == 201, report.text
        run = http.post(f"/api/dash-reports/{report.json()['id']}/runs", json={}, headers=headers)
        assert run.status_code == 200, run.text
        assert http.get("/api/audit").status_code == 200
    assert not (tmp_path / "state.sqlite3").exists()
    with application_db.connect(settings) as db:
        assert application_db.schema_version(db) == application_db.CURRENT_VERSION
        assert application_db.verify_audit(db) == (True, None)
        assert db.execute("SELECT COUNT(*) FROM dash_report_runs").fetchone()[0] == 1
    with pytest.raises(RuntimeError, match="pg_dump"):
        application_db.backup_database(settings, tmp_path / "wrong.sqlite3")


def test_postgres_standby_worker_takes_over_when_active_session_ends(postgres_schema):
    import threading
    from openreporting import postgres_store

    events = []
    acquired = threading.Event()

    def standby():
        with postgres_store.exclusive_worker(postgres_schema.dsn, standby_poll_s=0.05, on_standby=lambda: events.append("standby")):
            acquired.set()

    with postgres_store.exclusive_worker(postgres_schema.dsn):
        thread = threading.Thread(target=standby, daemon=True)
        thread.start()
        assert not acquired.wait(0.4)
        assert events  # waited instead of failing or running alongside the active worker
    assert acquired.wait(5)
    thread.join(5)


def test_postgres_worker_lock_release_and_connection_loss(postgres_schema):
    from openreporting import postgres_store

    with postgres_store.exclusive_worker(postgres_schema.dsn) as guard:
        guard.ensure()
        with pytest.raises(RuntimeError, match="already active"):
            with postgres_store.exclusive_worker(postgres_schema.dsn):
                pass
        guard.db.raw.close()  # Simulate the dedicated ownership session dying.
        with pytest.raises(postgres_store.WorkerOwnershipLost):
            postgres_store.assert_worker_ownership()
    # A dead session releases its database lock. No reconnect happens for the old guard.
    with postgres_store.exclusive_worker(postgres_schema.dsn):
        postgres_store.assert_worker_ownership()
    with pytest.raises(RuntimeError, match="test interruption"):
        with postgres_store.exclusive_worker(postgres_schema.dsn):
            raise RuntimeError("test interruption")
    with postgres_store.exclusive_worker(postgres_schema.dsn):
        pass


def test_postgres_worker_generates_verified_report_without_replaying_uncertain_mail(postgres_schema, tmp_path):
    from dataclasses import replace
    from openreporting import dashboards, datasources
    from openreporting.config import Settings
    from openreporting.reporting import service
    from openreporting.security import create_user
    from openreporting.worker import run_forever

    settings = replace(
        Settings.from_env(), data_dir=tmp_path, database_url=postgres_schema.dsn, secret_key_file="", mail_enabled=False, zabbix_url="", zabbix_token_file=""
    )
    application_db.init_db(settings)
    datasources.provision(settings)
    user = {"id": create_user(settings, "admin1", "an-admin-password-123", "admin"), "role": "admin"}
    dashboards.save(
        settings,
        user,
        {
            "uid": "pg-worker",
            "title": "Worker test",
            "panels": [{"id": 1, "type": "timeseries", "title": "Test", "targets": [{"refId": "A", "datasource": {"uid": "testdata"}, "scenario": "sine"}]}],
        },
    )
    report = service.save_report(settings, user, {"name": "Worker test", "dashboard_uid": "pg-worker", "formats": ["csv"]})
    run_id = service.request_run(settings, user, report["id"], {})["run_id"]
    run_forever(settings, once=True)
    assert service.list_runs(settings, report["id"])[0]["status"] == "completed"
    path, _ = service.verified_file(settings, run_id, "csv")
    assert path.is_file() and path.stat().st_size > 0
    with application_db.connect(settings) as db, application_db.transaction(db):
        db.execute("UPDATE dash_report_runs SET delivery_status='sending' WHERE id=?", (run_id,))
    run_forever(settings, once=True)
    run = service.list_runs(settings, report["id"])[0]
    # The finished report stays downloadable; only the uncertain e-mail becomes unknown (never resent).
    assert (run["status"], run["delivery_status"]) == ("completed", "unknown")
    assert service.verified_file(settings, run_id, "csv")[0].is_file()
    assert service.claim(settings) is None
    assert not (tmp_path / "worker.lock").exists()


def test_postgres_directory_identity_and_role_sync(postgres_schema, tmp_path, monkeypatch):
    from dataclasses import replace
    from openreporting import directory_auth, security
    from openreporting.config import Settings

    settings = replace(Settings.from_env(), data_dir=tmp_path, database_url=postgres_schema.dsn, ldap_enabled=True)
    application_db.init_db(settings)
    identity = directory_auth.Identity("isolated-directory-id", "editor")
    monkeypatch.setattr(directory_auth, "authenticate", lambda *args: identity)
    token, _, _ = security.login(settings, "reader", "isolated-password")
    identity = replace(identity, role="viewer")
    security.login(settings, "reader", "isolated-password")
    with application_db.connect(settings) as db:
        assert db.execute("SELECT role FROM users WHERE username='reader'").fetchone()[0] == "viewer"
        assert db.execute("SELECT COUNT(*) FROM external_identities").fetchone()[0] == 1
        assert db.execute("SELECT 1 FROM sessions WHERE token_hash=?", (security.digest(token),)).fetchone() is None
        assert application_db.verify_audit(db) == (True, None)


def test_postgres_mfa_setup_replay_and_session_cascade(postgres_schema, tmp_path, monkeypatch):
    from dataclasses import replace
    import pyotp
    from openreporting import mfa, security
    from openreporting.config import Settings

    settings = replace(
        Settings.from_env(), data_dir=tmp_path, database_url=postgres_schema.dsn, secret_key_file="", ldap_enabled=False, mfa_required_roles=("admin",)
    )
    application_db.init_db(settings)
    uid = security.create_user(settings, "factorpg", "isolated-factor-pg-password")
    user = {"id": uid, "username": "factorpg", "role": "admin"}
    now = 1800000000
    monkeypatch.setattr(mfa, "now_seconds", lambda: now)
    security.login(settings, "factorpg", "isolated-factor-pg-password")
    started = mfa.start_setup(settings, user, "isolated-factor-pg-password")
    confirmed = mfa.confirm_setup(settings, user, "isolated-factor-pg-password", pyotp.TOTP(started["secret"]).at(now), started["setup_token"])
    with application_db.connect(settings) as conn:
        assert conn.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
    security.login(settings, "factorpg", "isolated-factor-pg-password", confirmed["recovery_codes"][0])
    with pytest.raises(Exception) as failed:
        security.login(settings, "factorpg", "isolated-factor-pg-password", confirmed["recovery_codes"][0])
    assert getattr(failed.value, "status_code", None) == 401
    with application_db.connect(settings) as conn, application_db.transaction(conn):
        assert conn.execute("SELECT count(*) FROM mfa_sessions").fetchone()[0] == 1
        conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
        assert conn.execute("SELECT count(*) FROM mfa_sessions").fetchone()[0] == 0
        assert application_db.verify_audit(conn) == (True, None)


def test_postgres_queued_report_respects_actor_revocation(postgres_schema, tmp_path, monkeypatch):
    from dataclasses import replace
    from openreporting import dashboards, datasources, security
    from openreporting.config import Settings
    from openreporting.reporting import service

    settings = replace(
        Settings.from_env(),
        data_dir=tmp_path,
        database_url=postgres_schema.dsn,
        secret_key_file="",
        mail_enabled=False,
        ldap_enabled=False,
        mfa_required_roles=(),
        zabbix_url="",
        zabbix_token_file="",
    )
    application_db.init_db(settings)
    datasources.provision(settings)
    user = {"id": security.create_user(settings, "revoked_owner", "isolated-pg-owner-password"), "role": "admin"}
    dashboards.save(
        settings,
        user,
        {
            "uid": "revoke-pg",
            "title": "Revocation fixture",
            "panels": [{"id": 1, "type": "stat", "targets": [{"refId": "A", "scenario": "sine", "datasource": {"uid": "testdata"}}]}],
        },
    )
    report = service.save_report(settings, user, {"name": "Revocation report", "dashboard_uid": "revoke-pg", "formats": ["csv"]})
    run = service.request_run(settings, user, report["id"], {})["run_id"]
    with application_db.connect(settings) as conn, application_db.transaction(conn):
        conn.execute("UPDATE users SET active=0 WHERE id=?", (user["id"],))
    monkeypatch.setattr(service, "build_outputs", lambda *a, **k: pytest.fail("Revoked PostgreSQL owner must not render"))
    service.execute(settings, run)
    assert service.list_runs(settings, report["id"])[0]["status"] == "blocked"
    with application_db.connect(settings) as conn:
        assert application_db.verify_audit(conn) == (True, None)


def test_postgres_folder_grants_queries_worker_and_concurrent_revision(postgres_schema, tmp_path):
    from dataclasses import replace
    from fastapi import HTTPException
    from openreporting import dashboards, datasources, folder_access, security
    from openreporting.config import Settings
    from openreporting.reporting import service

    settings = replace(
        Settings.from_env(),
        data_dir=tmp_path,
        database_url=postgres_schema.dsn,
        secret_key_file="",
        ldap_enabled=False,
        mail_enabled=False,
        mfa_required_roles=(),
        zabbix_url="",
        zabbix_token_file="",
    )
    application_db.init_db(settings)
    datasources.provision(settings)
    admin = {"id": security.create_user(settings, "acl_owner", "isolated-pg-owner-password"), "role": "admin"}
    editor = {"id": security.create_user(settings, "acl_editor", "isolated-pg-editor-password", "editor"), "role": "editor"}
    folder = dashboards.save_folder(settings, admin, "PG restricted")["uid"]
    dashboards.save(
        settings,
        admin,
        {
            "uid": "pg-private",
            "title": "PG private",
            "panels": [{"id": 1, "type": "stat", "targets": [{"refId": "A", "scenario": "sine", "datasource": {"uid": "testdata"}}]}],
        },
        folder_uid=folder,
    )
    rid = service.save_report(settings, admin, {"name": "PG private report", "dashboard_uid": "pg-private", "formats": ["csv"]})["id"]
    body = {"restricted": True, "revision": 0, "grants": [{"user_id": editor["id"], "permission": "edit"}]}

    def replace_permissions():
        try:
            folder_access.replace_policy(settings, admin, folder, body)
            return 200
        except HTTPException as exc:
            return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: replace_permissions(), range(2))) == [200, 409]
    assert dashboards.search(settings, editor)[0]["uid"] == "pg-private"
    assert dashboards.folders(settings, editor)[0]["canEdit"]
    assert dashboards.tags(settings, editor) == []
    assert service.list_reports(settings, editor)[0]["id"] == rid
    run = service.request_run(settings, editor, rid, {})["run_id"]
    service.execute(settings, run)
    assert service.list_runs(settings, rid, user=editor)[0]["status"] == "completed"
    assert service.verified_file(settings, run, "csv", editor)[0].is_file()
    pending = service.request_run(settings, editor, rid, {})["run_id"]
    folder_access.replace_policy(settings, admin, folder, {**body, "revision": 1, "grants": []})
    assert dashboards.search(settings, editor) == []
    assert dashboards.folders(settings, editor) == []
    assert service.list_reports(settings, editor) == []
    assert service.list_runs(settings, user=editor) == []
    assert service.list_schedules(settings, user=editor) == []
    with pytest.raises(HTTPException):
        service.verified_file(settings, run, "csv", editor)
    service.execute(settings, pending)
    assert next(r for r in service.list_runs(settings, rid, user=admin) if r["id"] == pending)["status"] == "blocked"
    with application_db.connect(settings) as conn:
        assert application_db.verify_audit(conn) == (True, None)


def test_postgres_operator_preflight_snapshot_reports_without_mutation(postgres_schema, tmp_path):
    from dataclasses import replace
    from openreporting import postgres_check, security
    from openreporting.config import Settings

    settings = replace(Settings.from_env(), data_dir=tmp_path, database_url=postgres_schema.dsn, secret_key_file="", ldap_enabled=False, mfa_required_roles=())
    application_db.init_db(settings)
    security.create_user(settings, "preflight_owner", "isolated-preflight-password")
    with application_db.connect(settings) as conn:
        before = tuple(conn.execute("SELECT (SELECT count(*) FROM users),(SELECT count(*) FROM sessions),(SELECT count(*) FROM audit)").fetchone())
        transport = postgres_check._transport(conn)
    result = postgres_check.check(settings)
    assert result["mode"] == "read_only_repeatable_read" and result["production_ready"] is False
    assert result["transport"] == transport
    assert result["checks"]["secure_transport"] == (transport != "unverified_tcp")
    for key in (
        "schema_current",
        "read_only_snapshot",
        "primary_writable_default",
        "application_tables_readable",
        "audit_chain",
        "local_recovery_admin",
        "runtime_data_privileges",
    ):
        assert result["checks"][key], (key, result)
    with application_db.connect(settings) as conn:
        dangerous = conn.execute(
            "SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls FROM pg_roles WHERE rolname=current_user"
        ).fetchone()[0]
        if dangerous:
            assert not result["checks"]["least_privilege_role"] and not result["ok"]
        assert tuple(conn.execute("SELECT (SELECT count(*) FROM users),(SELECT count(*) FROM sessions),(SELECT count(*) FROM audit)").fetchone()) == before


def test_postgres_preflight_really_rejects_writes_and_never_upgrades(postgres_schema, tmp_path, monkeypatch):
    from dataclasses import replace
    from openreporting import postgres_check
    from openreporting.config import Settings

    settings = replace(Settings.from_env(), data_dir=tmp_path, database_url=postgres_schema.dsn, secret_key_file="")
    with monkeypatch.context() as patch:
        patch.setattr(application_db, "CURRENT_VERSION", 4)
        application_db.init_db(settings)
    result = postgres_check.check(settings)
    assert not result["ok"] and not result["checks"]["schema_current"]
    assert not result["checks"]["application_tables_readable"]
    with application_db.connect(settings) as conn:
        assert application_db.schema_version(conn) == 4

    def attempted_write(conn):
        conn.execute("INSERT INTO login_failures(username,count,last_at) VALUES('must-not-exist',1,'test')")
        pytest.fail("PostgreSQL must enforce READ ONLY even for the schema owner")

    monkeypatch.setattr(postgres_check, "_inspect", attempted_write)
    assert postgres_check.check(settings) == {"ok": False, "production_ready": False, "error": "inspection_failed"}
    with application_db.connect(settings) as conn:
        assert conn.execute("SELECT count(*) FROM login_failures WHERE username='must-not-exist'").fetchone()[0] == 0
        assert application_db.schema_version(conn) == 4


def test_postgres_preflight_detects_privileged_membership_in_a_limited_login(postgres_schema, tmp_path):
    from dataclasses import replace
    from openreporting import postgres_check
    from openreporting.config import Settings

    settings = replace(Settings.from_env(), data_dir=tmp_path, database_url=postgres_schema.dsn, secret_key_file="")
    application_db.init_db(settings)
    role = "pgcheck_" + uuid4().hex
    with application_db.connect(settings) as conn:
        if not conn.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user").fetchone()[0]:
            pytest.skip("Isolated role contract needs its own privileged CI server")
        schema = conn.execute("SELECT current_schema()").fetchone()[0]
        conn.raw.execute(sql.SQL("CREATE ROLE {} LOGIN PASSWORD 'isolated-preflight-role-password'").format(sql.Identifier(role)))
        try:
            for grant in (
                "GRANT USAGE ON SCHEMA {} TO {}",
                "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA {} TO {}",
                "GRANT USAGE ON ALL SEQUENCES IN SCHEMA {} TO {}",
            ):
                conn.raw.execute(sql.SQL(grant).format(sql.Identifier(schema), sql.Identifier(role)))
            limited = replace(
                settings, database_url=psycopg.conninfo.make_conninfo(postgres_schema.dsn, user=role, password="isolated-preflight-role-password")
            )
            result = postgres_check.check(limited)
            assert result["checks"]["least_privilege_role"], result
            assert result["checks"]["runtime_data_privileges"], result
            conn.raw.execute(sql.SQL("GRANT pg_read_all_data TO {}").format(sql.Identifier(role)))
            assert not postgres_check.check(limited)["checks"]["least_privilege_role"]
        finally:
            # This freshly generated role owns no objects: revoke only its fixture grants.
            for revoke in (
                "REVOKE ALL ON ALL SEQUENCES IN SCHEMA {} FROM {}",
                "REVOKE ALL ON ALL TABLES IN SCHEMA {} FROM {}",
                "REVOKE ALL ON SCHEMA {} FROM {}",
            ):
                conn.raw.execute(sql.SQL(revoke).format(sql.Identifier(schema), sql.Identifier(role)))
            conn.raw.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role)))


def _sqlite_state(tmp_path):
    """A small but complete SQLite store: users, factor, sealed secrets, dashboard, report run, settings."""
    from dataclasses import replace
    from openreporting import dashboards, datasources, runtime_settings, security
    from openreporting.config import Settings
    from openreporting.reporting import service
    from openreporting.secrets_store import encrypt, reset_cache

    reset_cache()
    settings = replace(
        Settings.from_env(),
        data_dir=tmp_path / "sqlite",
        database_url="",
        secret_key_file=str(tmp_path / "shared.key"),
        ldap_enabled=False,
        mail_enabled=False,
        mfa_required_roles=(),
        zabbix_url="",
        zabbix_token_file="",
    )
    application_db.init_db(settings)
    datasources.provision(settings)
    user = {"id": security.create_user(settings, "migrator", "isolated-migration-password", "admin"), "role": "admin"}
    with application_db.connect(settings) as connection, application_db.transaction(connection):
        connection.execute("UPDATE datasources SET secure_json=? WHERE uid='testdata'", (encrypt(settings, {"token": "migrated-secret"}),))
        application_db.audit(connection, "test", "source.secret_seeded", "datasource", "testdata")
    dashboards.save(
        settings,
        user,
        {
            "uid": "migrated",
            "title": "Migrated dashboard",
            "panels": [{"id": 1, "type": "timeseries", "targets": [{"refId": "A", "datasource": {"uid": "testdata"}, "scenario": "sine"}]}],
        },
    )
    report = service.save_report(settings, user, {"name": "Migrated report", "dashboard_uid": "migrated", "formats": ["csv"]})
    run_id = service.request_run(settings, user, report["id"], {})["run_id"]
    assert service.claim(settings) == run_id
    service.execute(settings, run_id)
    runtime_settings.save(
        settings,
        "mail",
        {"mail_enabled": True, "smtp_host": "smtp.example.com", "smtp_from": "r@example.com", "recipient_domains": ["example.com"], "smtp_user": "relay"},
        {"smtp_password": "migrated-relay-secret"},
        0,
        user["id"],
    )
    return settings, user, run_id


def test_sqlite_store_migrates_verified_into_empty_postgres(postgres_schema, tmp_path):
    from dataclasses import replace
    from openreporting import pg_migrate, runtime_settings, security
    from openreporting.reporting import service
    from openreporting.secrets_store import decrypt, reset_cache

    source, user, run_id = _sqlite_state(tmp_path)
    with application_db.connect(source) as connection:
        expected = {t: connection.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in pg_migrate._tables(connection)}
    with pytest.raises(pg_migrate.MigrationError, match="--services-stopped"):
        pg_migrate.migrate(source.db_path, postgres_schema.dsn)
    result = pg_migrate.migrate(source.db_path, postgres_schema.dsn, services_stopped=True)
    assert result["ok"] and result["rows"] == expected
    target = replace(source, database_url=postgres_schema.dsn, data_dir=tmp_path / "pg-data")
    target.data_dir.mkdir()
    reset_cache()
    runtime_settings.invalidate(target)
    with application_db.connect(target) as connection:
        assert application_db.verify_audit(connection)[0]
        secure = connection.execute("SELECT secure_json FROM datasources WHERE uid='testdata'").fetchone()[0]
        assert decrypt(target, secure) == {"token": "migrated-secret"}
        before = connection.execute("SELECT max(id) FROM audit").fetchone()[0]
        sealed = connection.execute("SELECT secure_json FROM app_settings WHERE scope='mail'").fetchone()[0]
    # The fixture DSN is a key/value conninfo (not a URL), so read the sealed scope directly.
    assert runtime_settings.valid_payload(decrypt(target, sealed), "mail") == {"smtp_password": "migrated-relay-secret"}
    token, _, _ = security.login(target, "migrator", "isolated-migration-password")
    assert token
    assert any(r["id"] == run_id and r["status"] == "completed" for r in service.list_runs(target, None, user=user))
    with application_db.connect(target) as connection, application_db.transaction(connection):
        latest = connection.execute("SELECT max(id) FROM audit").fetchone()[0]
        assert latest >= before  # sign-in above appended its own audit entry
        application_db.audit(connection, "test", "after.migration", "test", "x")
        assert connection.execute("SELECT max(id) FROM audit").fetchone()[0] == latest + 1  # identity continues
    with pytest.raises(pg_migrate.MigrationError, match="boş değil"):
        pg_migrate.migrate(source.db_path, postgres_schema.dsn, services_stopped=True)


def test_failed_verification_leaves_postgres_target_empty(postgres_schema, tmp_path, monkeypatch):
    from openreporting import pg_migrate

    source, _, _ = _sqlite_state(tmp_path)
    original = pg_migrate._digest
    calls = []

    def corrupt(rows):
        calls.append(1)
        return original(rows) + ("x" if len(calls) == 6 else "")

    monkeypatch.setattr(pg_migrate, "_digest", corrupt)
    with pytest.raises(pg_migrate.MigrationError, match="geri alındı"):
        pg_migrate.migrate(source.db_path, postgres_schema.dsn, services_stopped=True)
    with postgres_schema() as connection:
        assert pg_migrate._target_is_empty(connection)
