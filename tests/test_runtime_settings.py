"""Admin-UI runtime settings: precedence, sealed secrets, step-up, conflicts and fail-closed behaviour."""
from dataclasses import replace
import json

from fastapi.testclient import TestClient
import pytest

from openreporting import runtime_settings, security
from openreporting.config import Settings
from openreporting.db import connect, transaction, verify_audit
from openreporting.web import create_app

PASSWORD = 'isolated-settings-password'
MAIL = {'mail_enabled': True, 'smtp_host': 'smtp.example.com', 'smtp_port': 587, 'smtp_security': 'starttls',
        'smtp_user': 'reports', 'smtp_from': 'reports@example.com', 'recipient_domains': ['example.com']}


@pytest.fixture
def state(tmp_path):
    settings = replace(Settings.from_env(), data_dir=tmp_path / 'data', database_url='', secret_key_file='', secure_cookie=True,
                       ldap_enabled=False, mail_enabled=False, mfa_required_roles=(), zabbix_url='', zabbix_token_file='',
                       smtp_password='', smtp_user='', smtp_host='', smtp_from='', recipient_domains=())
    app = create_app(settings)
    security.create_user(settings, 'settingsadmin', PASSWORD, 'admin')
    security.create_user(settings, 'settingsviewer', PASSWORD, 'viewer')
    runtime_settings.invalidate(settings)
    return settings, app


def client_for(app, username='settingsadmin'):
    client = TestClient(app, base_url='https://localhost')
    signed = client.post('/api/login', json={'username': username, 'password': PASSWORD})
    assert signed.status_code == 200, signed.text
    client.headers['X-CSRF-Token'] = signed.json()['csrf']
    return client


def save(client, scope, values, secrets=None, revision=0, password=PASSWORD):
    return client.put(f'/api/admin/settings/{scope}', json={'revision': revision, 'values': values,
                                                            'secrets': secrets or {}, 'password': password})


def test_ui_value_overrides_environment_and_reset_restores_it(state):
    settings, app = state
    with client_for(app) as client:
        view = client.get('/api/admin/settings').json()
        assert view['scopes']['security']['fields']['session_hours'] == {'value': settings.session_hours, 'source': 'server',
                                                                       'env': 'OPENREPORTING_SESSION_HOURS'}
        saved = save(client, 'security', {'session_hours': 3})
        assert saved.status_code == 200, saved.text
        assert saved.json()['fields']['session_hours'] == {'value': 3, 'source': 'ui', 'env': 'OPENREPORTING_SESSION_HOURS'}
        assert runtime_settings.effective(settings).session_hours == 3
        reset = client.post('/api/admin/settings/security/reset', json={'revision': saved.json()['revision'], 'password': PASSWORD})
        assert reset.status_code == 200, reset.text
        assert runtime_settings.effective(settings).session_hours == settings.session_hours


def test_smtp_password_is_sealed_never_returned_and_kept_on_later_saves(state):
    settings, app = state
    with client_for(app) as client:
        saved = save(client, 'mail', MAIL, {'smtp_password': 'relay-secret-value'})
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body['fields']['smtp_password'] == {'set': True, 'source': 'ui', 'env': 'OPENREPORTING_SMTP_PASSWORD'}
        assert 'relay-secret-value' not in json.dumps(client.get('/api/admin/settings').json())
        # A later save without the secret keeps it.
        again = save(client, 'mail', {'smtp_timeout': 45}, {'smtp_password': None}, revision=body['revision'])
        assert again.status_code == 200, again.text
    current = runtime_settings.effective(settings)
    assert (current.mail_enabled, current.smtp_timeout, current.smtp_password) == (True, 45, 'relay-secret-value')
    with connect(settings) as db:
        row = db.execute("SELECT values_json,secure_json FROM app_settings WHERE scope='mail'").fetchone()
        audit_rows = [r[0] for r in db.execute("SELECT details FROM audit WHERE action='settings.updated'")]
        assert verify_audit(db)[0]
    assert 'relay-secret-value' not in row['values_json'] + row['secure_json'] + ''.join(audit_rows)


def test_invalid_combination_is_rejected_and_nothing_is_stored(state):
    settings, app = state
    with client_for(app) as client:
        response = save(client, 'mail', {**MAIL, 'smtp_user': 'reports'})  # user without password
        assert response.status_code == 422
        assert save(client, 'limits', {'query_concurrency': 0}).status_code == 422
        assert save(client, 'security', {'mfa_required_roles': ['root']}).status_code == 422
        assert save(client, 'mail', {'unknown_field': 1}).status_code == 422
        assert save(client, 'mail', {'smtp_password': 'in-values'}).status_code == 422
    with connect(settings) as db:
        assert db.execute('SELECT COUNT(*) FROM app_settings').fetchone()[0] == 0


def test_save_requires_current_password_admin_role_and_fresh_revision(state):
    settings, app = state
    with client_for(app) as client:
        assert save(client, 'security', {'session_hours': 4}, password='wrong-password-value').status_code == 403
        first = save(client, 'security', {'session_hours': 4})
        assert first.status_code == 200
        assert save(client, 'security', {'session_hours': 5}, revision=0).status_code == 409
    with client_for(app, 'settingsviewer') as viewer:
        assert viewer.get('/api/admin/settings').status_code == 403
        assert save(viewer, 'security', {'session_hours': 1}).status_code == 403


def test_policy_change_applies_to_existing_sessions_without_restart(state):
    settings, app = state
    with client_for(app) as client:
        assert save(client, 'security', {'mfa_required_roles': ['viewer']}).status_code == 200
    with TestClient(app, base_url='https://localhost') as viewer:
        signed = viewer.post('/api/login', json={'username': 'settingsviewer', 'password': PASSWORD})
        assert signed.status_code == 200
        assert viewer.get('/api/session').json()['mfa_enrollment_required'] is True


def test_unreadable_sealed_secret_disables_the_integration(state):
    settings, app = state
    with client_for(app) as client:
        assert save(client, 'mail', MAIL, {'smtp_password': 'relay-secret-value'}).status_code == 200
    with connect(settings) as db, transaction(db):
        db.execute("UPDATE app_settings SET secure_json='corrupt-token', revision=revision+1 WHERE scope='mail'")
    runtime_settings.invalidate(settings)
    current = runtime_settings.effective(settings)
    assert current.mail_enabled is False
    with client_for(app) as client:
        assert client.get('/api/admin/settings').json()['scopes']['mail']['error']


def test_connection_test_uses_unsaved_values_and_stores_nothing(state, monkeypatch):
    settings, app = state
    seen = {}
    from openreporting import mail_transport
    monkeypatch.setattr(mail_transport, 'check_connection', lambda s: seen.setdefault('s', s) and 'ok')
    with client_for(app) as client:
        assert client.post('/api/admin/settings/mail/test', json={'values': MAIL, 'secrets': {}, 'password': 'wrong-password-value'}).status_code == 403
        response = client.post('/api/admin/settings/mail/test', json={'values': {**MAIL, 'mail_enabled': False},
                                                                      'secrets': {'smtp_password': 'try-only'}, 'password': PASSWORD})
        assert response.json()['ok'] is True
        assert client.post('/api/admin/settings/security/test', json={'password': PASSWORD}).status_code == 404
    assert seen['s'].mail_enabled and seen['s'].smtp_password == 'try-only'
    with connect(settings) as db:
        assert db.execute('SELECT COUNT(*) FROM app_settings').fetchone()[0] == 0


def test_admin_can_reset_another_users_factor_but_not_their_own(state):
    settings, app = state
    with connect(settings) as db, transaction(db):
        viewer_id = db.execute("SELECT id FROM users WHERE username='settingsviewer'").fetchone()[0]
        admin_id = db.execute("SELECT id FROM users WHERE username='settingsadmin'").fetchone()[0]
        db.execute("INSERT INTO user_mfa(user_id,secret_json,enabled,updated_at) VALUES(?,'x',1,'2026-01-01T00:00:00+00:00')", (viewer_id,))
    with client_for(app) as client:
        listed = {u['username']: u['mfa_enabled'] for u in client.get('/api/users').json()}
        assert listed == {'settingsadmin': 0, 'settingsviewer': 1}
        body = {'reason': 'lost-device', 'password': PASSWORD}
        assert client.post(f'/api/users/{admin_id}/mfa/reset', json=body).status_code == 409
        assert client.post(f'/api/users/{viewer_id}/mfa/reset', json={**body, 'reason': 'whim'}).status_code == 422
        assert client.post(f'/api/users/{viewer_id}/mfa/reset', json=body).status_code == 200
        assert client.post(f'/api/users/{viewer_id}/mfa/reset', json=body).status_code == 409
    with connect(settings) as db:
        assert db.execute("SELECT COUNT(*) FROM audit WHERE action='mfa.reset_by_admin'").fetchone()[0] == 1


def test_sealed_settings_are_rekeyed_and_verified_in_backups(state, tmp_path):
    from openreporting.backup_verify import verify_backup
    from openreporting.key_rotation import prepare_rotation, rekey_secrets
    from openreporting.secrets_store import key_path, reset_cache
    import os
    import shutil
    settings, app = state
    with client_for(app) as client:
        assert save(client, 'mail', MAIL, {'smtp_password': 'relay-secret-value'}).status_code == 200
    ring = tmp_path / 'ring.json'
    prepare_rotation(settings, ring)
    shutil.copyfile(ring, key_path(settings))
    os.chmod(key_path(settings), 0o600)
    reset_cache()
    result = rekey_secrets(settings, services_stopped=True)
    assert result['settings_secrets_rekeyed'] == 1
    runtime_settings.invalidate(settings)
    assert runtime_settings.effective(settings).smtp_password == 'relay-secret-value'
    target = tmp_path / 'backup'
    target.mkdir()
    from openreporting.db import backup_database
    import hashlib
    import tarfile
    backup_database(settings, target / 'state.sqlite3')
    with tarfile.open(target / 'archive.tar.gz', 'w:gz') as archive:
        archive.add(settings.archive_dir, arcname='archive')
    (target / 'openreporting.env').write_text('OPENREPORTING_MAIL_ENABLED=false\n')
    lines = [hashlib.sha256(p.read_bytes()).hexdigest() + '  ./' + p.name for p in sorted(target.iterdir())]
    (target / 'SHA256SUMS').write_text('\n'.join(lines) + '\n', encoding='ascii')
    assert verify_backup(target, key_file=key_path(settings))['encrypted_settings'] == 1


def test_stored_password_is_never_sent_to_a_changed_destination(state):
    # Pointing SMTP/LDAP at another host must not reuse the stored secret (credential exfiltration).
    settings, app = state
    with client_for(app) as client:
        saved = save(client, 'mail', MAIL, {'smtp_password': 'relay-secret-value'}).json()
        moved = {**MAIL, 'smtp_host': 'attacker.example.net'}
        test = client.post('/api/admin/settings/mail/test', json={'values': moved, 'secrets': {}, 'password': PASSWORD})
        assert test.status_code == 422 and 'yeniden girilmeli' in test.json()['detail']
        assert save(client, 'mail', {'smtp_host': 'attacker.example.net'}, revision=saved['revision']).status_code == 422
        # Unchanged destination keeps the stored secret; a new destination with a new secret is fine.
        assert save(client, 'mail', {'smtp_port': 465, 'smtp_security': 'tls'}, {'smtp_password': 'new-relay-secret'},
                    revision=saved['revision']).status_code == 200


def test_password_change_uses_the_shared_lockout(state):
    settings, app = state
    with client_for(app) as client:
        body = {'old_password': 'wrong-password-value', 'new_password': 'another-strong-password'}
        for _ in range(security.PAIR_LIMIT):
            assert client.put('/api/user/password', json=body).status_code == 403
        assert client.put('/api/user/password', json={**body, 'old_password': PASSWORD}).status_code == 429
