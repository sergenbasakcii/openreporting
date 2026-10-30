"""Directory trust boundaries, identity collision, role sync and local recovery."""
import json
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from openreporting import db, directory_auth as ldap, security
from openreporting.config import Settings
from openreporting.web import create_app


@pytest.fixture
def settings(tmp_path):
    return replace(Settings.from_env(), data_dir=tmp_path, secure_cookie=False, secret_key_file="", database_url="",
                   ldap_enabled=True, ldap_url="ldaps://directory.example.com:636", ldap_bind_dn="cn=reader,dc=example,dc=com",
                   ldap_bind_password="isolated-service-password", ldap_base_dn="dc=example,dc=com",
                   ldap_group_roles=json.dumps({"cn=readers,dc=example,dc=com": "viewer", "cn=editors,dc=example,dc=com": "editor"}))


def directory_fixture(monkeypatch, *, groups=None, entries=1, bind_code=0, search_code=0):
    state = SimpleNamespace(calls=[], filters=[])
    attrs = {"memberOf": groups if groups is not None else ["cn=readers,dc=example,dc=com"], "mail": ["reader@example.com"], "displayName": ["Directory reader"]}
    entry = {"type": "searchResEntry", "dn": "cn=reader,dc=example,dc=com", "raw_attributes": {"objectGUID": [b"stable-id"]}, "attributes": attrs}
    @contextmanager
    def connection(settings, username, password):
        state.calls.append((username, password))
        is_service = len(state.calls) % 2 == 1
        conn = SimpleNamespace(result={"result": 0 if is_service else bind_code}, response=[entry] * entries)
        conn.bind = lambda: is_service or bind_code == 0
        def search(base, query, **kwargs):
            state.filters.append((query, kwargs))
            conn.result = {"result": search_code}
            return entries > 0 and search_code == 0
        conn.search = search
        yield conn
    monkeypatch.setattr(ldap, "_connection", connection)
    return state


def test_ldap_escapes_input_requires_unique_identity_and_group(settings, monkeypatch):
    state = directory_fixture(monkeypatch)
    result = ldap.authenticate(settings, "reader*)(uid=*)", "directory-user-password")
    assert result.role == "viewer" and result.subject == b"stable-id".hex()
    assert r"reader\2a\29\28uid=\2a\29" in state.filters[0][0]
    assert state.filters[0][1]["size_limit"] == 2
    for count in (0, 2):
        directory_fixture(monkeypatch, entries=count)
        assert ldap.authenticate(settings, "reader", "password") is None
    directory_fixture(monkeypatch, groups=["cn=unmapped,dc=example,dc=com"])
    assert ldap.authenticate(settings, "reader", "password") is None
    directory_fixture(monkeypatch, bind_code=49)
    assert ldap.authenticate(settings, "reader", "wrong-password") is None
    directory_fixture(monkeypatch, search_code=4)
    with pytest.raises(ldap.DirectoryUnavailable):
        ldap.authenticate(settings, "reader", "password")


def test_no_empty_anonymous_bind_and_highest_mapped_role(settings, monkeypatch):
    state = directory_fixture(monkeypatch, groups=["CN=READERS,DC=EXAMPLE,DC=COM", "cn=editors,dc=example,dc=com"])
    assert ldap.authenticate(settings, "reader", "") is None
    assert state.calls == []
    assert ldap.authenticate(settings, "reader", "password").role == "editor"


def test_directory_provision_sync_and_no_password_fallback(settings, monkeypatch):
    app = create_app(settings)
    admin_id = security.create_user(settings, "admin1", "local-recovery-password-123", "admin")
    identity = ldap.Identity("stable-subject", "editor", "reader@example.com", "Reader")
    monkeypatch.setattr(ldap, "authenticate", lambda *args: identity)
    token, _, expiry = security.login(settings, "reader", "directory-password")
    assert 0 < (datetime.fromisoformat(expiry) - datetime.now(timezone.utc)).total_seconds() <= 3600
    with db.connect(settings) as conn:
        row = conn.execute("SELECT * FROM users WHERE username='reader'").fetchone()
        uid = row["id"]
        assert row["password_hash"] == "!ldap" and row["role"] == "editor"
        assert conn.execute("SELECT COUNT(*) FROM external_identities").fetchone()[0] == 1
    identity = replace(identity, role="viewer")
    security.login(settings, "reader", "directory-password")
    with db.connect(settings) as conn:
        assert conn.execute("SELECT 1 FROM sessions WHERE token_hash=?", (security.digest(token),)).fetchone() is None
        assert conn.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()[0] == "viewer"
    # Directory identities cannot take over a local username, even with a valid bind.
    with pytest.raises(HTTPException) as failure:
        security.login(settings, "admin1", "directory-password")
    assert failure.value.status_code == 401
    token, _, _ = security.login(settings, "admin1", "local-recovery-password-123")
    assert token and admin_id
    # Stable identity under another username is not silently duplicated/reassigned.
    with pytest.raises(HTTPException):
        security.login(settings, "renamed-reader", "directory-password")
    with TestClient(app, base_url="http://localhost") as http:
        response = http.post('/api/login', json={"username": "reader", "password": "directory-password"})
        assert response.status_code == 200
        headers = {"X-CSRF-Token": response.json()["csrf"]}
        assert http.get('/api/user').json()["auth_provider"] == "ldap"
        assert http.put('/api/user/password', json={"old_password": "x", "new_password": "an-arbitrary-password"}, headers=headers).status_code == 409
        # Viewer isolation remains intact for provisioned directory users.
        assert http.get('/api/users').status_code == 403


def test_local_disable_outage_and_lockout(settings, monkeypatch):
    db.init_db(settings)
    identity = ldap.Identity("stable-subject", "viewer")
    monkeypatch.setattr(ldap, "authenticate", lambda *args: identity)
    security.login(settings, "reader", "password")
    with db.connect(settings) as conn, db.transaction(conn):
        conn.execute("UPDATE users SET active=0 WHERE username='reader'")
    with pytest.raises(HTTPException) as failure:
        security.login(settings, "reader", "password")
    assert failure.value.status_code == 401
    def outage(*args):
        raise ldap.DirectoryUnavailable("safe operational message")
    monkeypatch.setattr(ldap, "authenticate", outage)
    with pytest.raises(HTTPException) as failure:
        security.login(settings, "newreader", "password")
    assert failure.value.status_code == 503
    with db.connect(settings) as conn:
        assert conn.execute("SELECT 1 FROM users WHERE username='newreader'").fetchone() is None
        assert conn.execute("SELECT 1 FROM login_failures WHERE username='newreader'").fetchone() is None
    monkeypatch.setattr(ldap, "authenticate", lambda *args: None)
    for _ in range(5):
        with pytest.raises(HTTPException) as failure:
            security.login(settings, "unknownreader", "wrong")
        assert failure.value.status_code == 401
    with pytest.raises(HTTPException) as failure:
        security.login(settings, "unknownreader", "wrong")
    assert failure.value.status_code == 429


def test_external_password_and_role_admin_guards(settings, monkeypatch):
    app = create_app(settings)
    security.create_user(settings, "admin1", "local-recovery-password-123", "admin")
    monkeypatch.setattr(ldap, "authenticate", lambda *args: ldap.Identity("subject", "viewer"))
    security.login(settings, "reader", "password")
    with TestClient(app, base_url="http://localhost") as http:
        res = http.post('/api/login', json={"username":"admin1", "password":"local-recovery-password-123"})
        headers = {"X-CSRF-Token": res.json()["csrf"]}
        user = next(x for x in http.get('/api/users').json() if x['username'] == 'reader')
        assert http.patch(f"/api/users/{user['id']}", json={"role":"admin"}, headers=headers).status_code == 409
        assert http.post(f"/api/users/{user['id']}/password", json={"password":"a-local-backdoor-password"}, headers=headers).status_code == 409
        assert http.patch(f"/api/users/{user['id']}", json={"active":False}, headers=headers).status_code == 200
        assert http.post('/api/admin/integrations/ldap/check', json={}).status_code == 403
        monkeypatch.setattr(ldap, 'check_connection', lambda *args: 'verified')
        assert http.post('/api/admin/integrations/ldap/check', json={}, headers=headers).json()['ok'] is True
        assert 'isolated-service-password' not in http.get('/api/admin/integrations').text
    with db.connect(settings) as conn:
        assert db.verify_audit(conn) == (True, None)


def test_v2_to_v3_preserves_local_users(settings, monkeypatch):
    monkeypatch.setattr(db, "CURRENT_VERSION", 2)
    db.init_db(settings)
    uid = security.create_user(settings, "admin1", "local-recovery-password-123", "admin")
    monkeypatch.setattr(db, "CURRENT_VERSION", 3)
    db.init_db(settings)
    db.init_db(settings)
    with db.connect(settings) as conn:
        assert db.schema_version(conn) == 3
        assert conn.execute("SELECT id FROM users WHERE username='admin1'").fetchone()[0] == uid
        assert conn.execute("SELECT COUNT(*) FROM external_identities").fetchone()[0] == 0


def test_connection_never_binds_before_starttls(settings, monkeypatch):
    import ldap3
    import ssl
    events = []
    def server(host, **options):
        assert options['tls'].validate == ssl.CERT_REQUIRED
        assert options['tls'].valid_names == [host]
        assert options['connect_timeout'] == settings.ldap_timeout
        return object()
    def connection(server, **options):
        assert options['read_only'] and options['auto_referrals'] is False
        assert options['receive_timeout'] == settings.ldap_timeout
        return SimpleNamespace(closed=False, open=lambda:events.append('open'),
                               start_tls=lambda:events.append('tls') or False, unbind=lambda:events.append('close'))
    monkeypatch.setattr(ldap3, 'Server', server)
    monkeypatch.setattr(ldap3, 'Connection', connection)
    with pytest.raises(ldap.DirectoryUnavailable):
        ldap.check_connection(replace(settings, ldap_url='ldap://directory.example.com:389'))
    assert events == ['open','tls','close']


def test_disabled_ldap_invalidates_external_sessions_and_keeps_recovery_admin(settings, monkeypatch):
    app = create_app(settings)
    security.create_user(settings, 'admin1', 'local-recovery-password-123', 'admin')
    monkeypatch.setattr(ldap, 'authenticate', lambda *args:ldap.Identity('subject','admin'))
    with TestClient(app, base_url="http://localhost") as directory_http:
        assert directory_http.post('/api/login',json={'username':'reader','password':'password'}).status_code == 200
        with TestClient(app, base_url="http://localhost") as local_http:
            res = local_http.post('/api/login',json={'username':'admin1','password':'local-recovery-password-123'})
            headers = {'X-CSRF-Token':res.json()['csrf']}
            target = next(u for u in local_http.get('/api/users').json() if u['username']=='admin1')
            assert local_http.patch(f"/api/users/{target['id']}",json={'role':'viewer'},headers=headers).status_code == 409
        app.state.settings = replace(settings, ldap_enabled=False)
        assert directory_http.get('/api/user').status_code == 401
