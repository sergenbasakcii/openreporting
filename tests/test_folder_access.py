"""Folder content boundaries across APIs, mutations, worker and archive.

Fixtures are disposable; no configured application data or external sources.
"""
from dataclasses import replace

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from openreporting import dashboards, db, folder_access, security
from openreporting.config import Settings
from openreporting.reporting import service
from openreporting.web import create_app

PASSWORD = "disposable-folder-test-password"


@pytest.fixture
def state(tmp_path):
    settings = replace(Settings.from_env(), data_dir=tmp_path, database_url='', secret_key_file='',
                       secure_cookie=False, ldap_enabled=False, mail_enabled=False,
                       mfa_required_roles=(), zabbix_url='', zabbix_token_file='')
    app = create_app(settings)
    actors = {role: {'id': security.create_user(settings, role, PASSWORD, role), 'role': role}
              for role in ('admin', 'editor', 'viewer')}
    owner = actors['admin']
    folder = dashboards.save_folder(settings, owner, 'Restricted content')
    other = dashboards.save_folder(settings, owner, 'Other content')
    for uid, fid in [('private', folder['uid']), ('public', None), ('other', other['uid'])]:
        dashboards.save(settings, owner, {'uid': uid, 'title': uid, 'tags': [uid], 'panels': [
            {'id': 1, 'type': 'timeseries', 'targets': [{'refId': 'A', 'scenario': 'sine',
                                                      'datasource': {'uid': 'testdata'}}]}]}, folder_uid=fid)
    report = service.save_report(settings, owner, {'name': 'Private report', 'dashboard_uid': 'private', 'formats': ['csv']})
    schedule = service.save_schedule(settings, owner, report['id'], {'enabled': True})
    with db.connect(settings) as conn, db.transaction(conn):
        conn.execute('INSERT INTO annotations VALUES(?,?,?,?,?,?,?,?,?)',
                     ('private-note', 'private', 1, 100, None, 'private note', '[]', db.utcnow(), owner['id']))
    return settings, app, actors, folder['uid'], other['uid'], report['id'], schedule['id']


def restrict(state, grants=(), restricted=True):
    settings, _, actors, uid, *_ = state
    revision = folder_access.policy(settings, actors['admin'], uid)['revision']
    return folder_access.replace_policy(settings, actors['admin'], uid,
                                        {'restricted': restricted, 'revision': revision, 'grants': list(grants)})


def signin(app, role):
    client = TestClient(app, base_url="http://127.0.0.1")
    response = client.post('/api/login', json={'username': role, 'password': PASSWORD})
    assert response.status_code == 200, response.text
    client.headers['X-CSRF-Token'] = response.json()['csrf']
    return client


def test_all_content_read_paths_hide_restricted_folder_and_limits(state):
    settings, app, actors, folder, _, rid, _ = state
    run = service.request_run(settings, actors['admin'], rid, {})['run_id']
    service.execute(settings, run)
    restrict(state)
    for role in ('viewer', 'editor'):
        with signin(app, role) as client:
            for url in (f'/api/dashboards/uid/private', '/api/dashboards/uid/private/versions',
                        '/api/dashboards/uid/private/versions/1', '/api/annotations?dashboardUID=private',
                        f'/api/dash-reports/{rid}', f'/api/dash-reports/{rid}/runs',
                        f'/api/dash-reports/{rid}/schedules', f'/api/report-runs/{run}/files/csv',
                        f'/api/report-runs/{run}/files/manifest'):
                assert client.get(url).status_code == 404, url
            assert {r['uid'] for r in client.get('/api/search').json()} == {'public', 'other'}
            assert {r['uid'] for r in client.get('/api/folders').json()} == {state[4]}
            assert {r['term'] for r in client.get('/api/dashboards/tags').json()} == {'public', 'other'}
            for url in ('/api/dash-reports', '/api/report-runs', '/api/report-schedules'):
                assert client.get(url).json() == [], url
    # A private row sorting first cannot consume the public search/run limit.
    assert len(dashboards.search(settings, actors['viewer'], limit=1)) == 1
    with pytest.raises(HTTPException):
        dashboards.get(settings, 'private')  # no implicit privileged service identity
    with pytest.raises(HTTPException):
        service.verified_file(settings, run, 'csv')


def test_uid_tampering_mutations_queries_and_old_new_destinations(state):
    settings, app, actors, folder, _, rid, sid = state
    restrict(state)
    model = {'uid': 'private', 'title': 'Overwrite denied', 'panels': []}
    with signin(app, 'editor') as client:
        requests = [
            ('post', '/api/dashboards/db', {'dashboard': model, 'overwrite': True}),
            ('post', '/api/dashboards/import', {'dashboard': model, 'overwrite': True}),
            ('post', '/api/dashboards/db', {'dashboard': {**model, 'uid': 'public'}, 'folderUid': folder}),
            ('post', '/api/dashboards/uid/private/restore', {'version': 1}),
            ('post', '/api/user/stars/dashboard/private', {}),
            ('post', '/api/annotations', {'dashboardUID': 'private', 'time': 1, 'text': 'denied'}),
            ('post', '/api/dashboards/variables/resolve', {'uid': 'private', 'dashboard': model}),
            ('post', '/api/ds/query', {'dashboardUid': 'private', 'targets': [{'refId': 'A'}]}),
            ('put', f'/api/folders/{folder}', {'title': 'unauthorized rename'}),
            ('put', f'/api/folders/{folder}', {'title': 'Other content'}),
            ('post', '/api/dash-reports', {'name': 'Denied report', 'dashboard_uid': 'private'}),
            ('put', f'/api/dash-reports/{rid}', {'name': 'Retarget attempt', 'dashboard_uid': 'public'}),
            ('post', f'/api/dash-reports/{rid}/runs', {}),
            ('post', f'/api/dash-reports/{rid}/schedules', {}),
            ('put', f'/api/dash-reports/{rid}/schedules/{sid}', {}),
            ('post', '/api/dash-reports/preview', {'name': 'Denied preview', 'dashboard_uid': 'private'}),
            ('post', '/api/dashboards/export', {'dashboard_uid': 'private', 'format': 'csv'}),
        ]
        for method, url, body in requests:
            response = getattr(client, method)(url, json=body)
            assert response.status_code == 404, (url, response.status_code, response.text)
        hidden = client.put('/api/user/preferences', json={'home_dashboard_uid': 'private'})
        missing = client.put('/api/user/preferences', json={'home_dashboard_uid': 'no-such-dashboard'})
        assert (hidden.status_code, hidden.json()) == (missing.status_code, missing.json()) == (422, missing.json())
        for url in ('/api/dashboards/uid/private', f'/api/folders/{folder}',
                    '/api/annotations/private-note', f'/api/dash-reports/{rid}', f'/api/report-schedules/{sid}'):
            assert client.delete(url).status_code == 404, url
    with signin(app, 'viewer') as client:
        for url, body in [('/api/ds/query', {'dashboardUid': 'private', 'panelId': 1, 'targets': [{'refId': 'A'}]}),
                          ('/api/dashboards/variables/resolve', {'uid': 'private'})]:
            assert client.post(url, json=body).status_code == 404
    assert dashboards.get(settings, 'private', actors['admin'])['dashboard']['title'] == 'private'


def test_explicit_grants_admin_recovery_role_ceiling_and_optimistic_policy(state):
    settings, app, actors, folder, *_ = state
    grant = lambda role, permission: {'user_id': actors[role]['id'], 'permission': permission}
    restrict(state, [grant('editor', 'view'), grant('viewer', 'edit')])
    for role in ('editor', 'viewer'):
        result = dashboards.get(settings, 'private', actors[role])
        assert not result['meta']['canEdit'] and not result['meta']['canSave']
        with pytest.raises(HTTPException):
            dashboards.save(settings, actors[role], result['dashboard'], folder_uid=folder)
    restrict(state, [grant('editor', 'edit')])
    model = dashboards.get(settings, 'private', actors['editor'])['dashboard']
    assert dashboards.get(settings, 'private', actors['editor'])['meta']['canEdit']
    dashboards.save(settings, actors['editor'], model, folder_uid=folder)
    assert dashboards.get(settings, 'private', actors['admin'])['meta']['canEdit']
    with signin(app, 'editor') as client:
        assert client.get(f'/api/folders/{folder}/permissions').status_code == 403
        assert client.put(f'/api/folders/{folder}/permissions', json={'restricted': False, 'revision': 2}).status_code == 403
    with signin(app, 'admin') as client:
        policy = client.get(f'/api/folders/{folder}/permissions').json()
        assert client.put(f'/api/folders/{folder}/permissions', json={'restricted': False, 'revision': 0}).status_code == 409
        # Unknown/duplicate grants roll back revision and existing grants.
        for grants in ([{'user_id': 'missing', 'permission': 'view'}], [grant('editor', 'view')] * 2):
            response = client.put(f'/api/folders/{folder}/permissions', json={**policy, 'grants': grants})
            assert response.status_code == 422
        assert client.get(f'/api/folders/{folder}/permissions').json() == policy
    with TestClient(app, base_url="http://127.0.0.1") as client:
        client.post('/api/login', json={'username': 'admin', 'password': PASSWORD})
        assert client.put(f'/api/folders/{folder}/permissions', json={'restricted': False, 'revision': 2}).status_code == 403


@pytest.mark.parametrize('moment', ['before', 'during', 'collect'])
def test_worker_revalidates_grants_and_discards_revoked_render(state, monkeypatch, moment):
    settings, _, actors, folder, _, rid, _ = state
    restrict(state, [{'user_id': actors['editor']['id'], 'permission': 'edit'}])
    run = service.request_run(settings, actors['editor'], rid, {})['run_id']
    if moment == 'before':
        restrict(state)
        monkeypatch.setattr(service, 'build_outputs', lambda *a, **k: pytest.fail('Must not query'))
    elif moment == 'collect':
        original_collect = service.collect
        def collect(*args, **kwargs):
            result = original_collect(*args, **kwargs)
            restrict(state)
            return result
        monkeypatch.setattr(service, 'collect', collect)
    else:
        original = service.build_outputs
        def render(*args, **kwargs):
            result = original(*args, **kwargs)
            restrict(state)
            return result
        monkeypatch.setattr(service, 'build_outputs', render)
    service.execute(settings, run)
    result = service.list_runs(settings, rid, user=actors['admin'])[0]
    assert result['status'] == 'blocked' and result['delivery_status'] == 'blocked_revalidation'
    assert result['files'] == {} and list(settings.archive_dir.iterdir()) == []


def test_authorized_worker_archive_viewer_export_and_revocation(state):
    settings, app, actors, folder, _, rid, sid = state
    grants = [{'user_id': actors[role]['id'], 'permission': 'edit' if role == 'editor' else 'view'}
              for role in ('editor', 'viewer')]
    restrict(state, grants)
    assert service.list_schedules(settings, rid, actors['admin'])[0]['enabled'] == 0
    run = service.request_run(settings, actors['editor'], rid, {})['run_id']
    service.execute(settings, run)
    assert service.list_runs(settings, rid, user=actors['admin'])[0]['status'] == 'completed'
    with signin(app, 'viewer') as client:
        assert client.get(f'/api/report-runs/{run}/files/csv').status_code == 200
        assert client.post('/api/dashboards/export', json={'dashboard_uid': 'private', 'format': 'csv'}).status_code == 200
        assert client.put('/api/user/preferences', json={'home_dashboard_uid': 'private'}).status_code == 200
        restrict(state)
        assert client.get('/api/user').json()['preferences']['home_dashboard_uid'] is None
        assert client.get(f'/api/report-runs/{run}/files/csv').status_code == 404
    # Prevent historical private artifacts becoming public by retargeting the report.
    with pytest.raises(service.ReportError, match='Arşivi'):
        service.save_report(settings, actors['admin'], {'name': 'Retarget', 'dashboard_uid': 'public'}, rid)


def test_schema4_upgrade_preserves_content_identity_and_defaults_shared(tmp_path, monkeypatch):
    settings = replace(Settings.from_env(), data_dir=tmp_path, database_url='', secret_key_file='',
                       ldap_enabled=False, mfa_required_roles=())
    with monkeypatch.context() as patch:
        patch.setattr(db, 'CURRENT_VERSION', 4)
        db.init_db(settings)
        user = {'id': security.create_user(settings, 'upgrade', PASSWORD, 'admin'), 'role': 'admin'}
        folder = dashboards.save_folder(settings, user, 'Existing folder')
        # Version-four data is inserted without consulting version-five policy tables.
        with db.connect(settings) as conn, db.transaction(conn):
            before = tuple(conn.execute('SELECT * FROM users').fetchone())
            conn.execute('INSERT INTO sessions VALUES(?,?,?,?,?)', ('old-token', user['id'], 'old-csrf', '2100-01-01', db.utcnow()))
    db.init_db(settings)
    with db.connect(settings) as conn:
        assert db.schema_version(conn) == db.CURRENT_VERSION
        assert tuple(conn.execute('SELECT * FROM users').fetchone()) == before
        assert conn.execute('SELECT token_hash FROM sessions').fetchone()[0] == 'old-token'
        assert conn.execute('SELECT count(*) FROM folder_policy').fetchone()[0] == 0
        assert db.verify_audit(conn) == (True, None)
    assert dashboards.folders(settings, user)[0]['uid'] == folder['uid']


def test_two_independent_restricted_folders_require_both_move_permissions(state):
    settings, _, actors, first, second, *_ = state
    restrict(state, [{'user_id': actors['editor']['id'], 'permission': 'edit'}])
    folder_access.replace_policy(settings, actors['admin'], second, {'restricted': True, 'revision': 0,
        'grants': [{'user_id': actors['viewer']['id'], 'permission': 'view'}]})
    assert {d['uid'] for d in dashboards.search(settings, actors['editor'])} == {'public', 'private'}
    assert {d['uid'] for d in dashboards.search(settings, actors['viewer'])} == {'public', 'other'}
    model = dashboards.get(settings, 'private', actors['editor'])['dashboard']
    with pytest.raises(HTTPException):
        dashboards.save(settings, actors['editor'], model, folder_uid=second, overwrite=True)
    assert dashboards.get(settings, 'private', actors['admin'])['meta']['folderUid'] == first
    # Moving content to shared explicitly requires source edit; authorized moves remain supported.
    dashboards.save(settings, actors['editor'], model, folder_uid=None)
    assert dashboards.get(settings, 'private', actors['viewer'])['meta']['folderUid'] is None
    with db.connect(settings) as conn:
        assert db.verify_audit(conn) == (True, None)


def test_deleted_private_dashboard_uid_cannot_reveal_orphaned_notes(state):
    settings, app, actors, folder, _, rid, _ = state
    restrict(state)
    service.delete_report(settings, actors['admin'], rid)
    dashboards.delete(settings, actors['admin'], 'private')
    dashboards.save(settings, actors['editor'], {'uid': 'private', 'title': 'New shared dashboard', 'panels': []})
    with signin(app, 'viewer') as client:
        assert client.get('/api/annotations?dashboardUID=private').json() == []
