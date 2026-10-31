"""Public API acceptance for credentials, session revocation and browser controls."""
from dataclasses import replace

from fastapi.testclient import TestClient
import pytest

from openreporting import cli,db,security
from openreporting.config import Settings
from openreporting.secrets_store import decrypt,key_path
from openreporting.web import create_app


@pytest.fixture
def state(tmp_path):
    settings = replace(Settings.from_env(),data_dir=tmp_path,database_url='',secret_key_file='',secure_cookie=True,
                       ldap_enabled=False,mail_enabled=False,zabbix_url='',zabbix_token_file='')
    app = create_app(settings)
    admin = security.create_user(settings,'admin1','isolated-admin-password','admin')
    viewer = security.create_user(settings,'viewer1','isolated-viewer-password','viewer')
    return settings,app,admin,viewer


def sign_in(client,username='admin1',password='isolated-admin-password'):
    response = client.post('/api/login',json={'username':username,'password':password})
    assert response.status_code==200
    return response,{'X-CSRF-Token':response.json()['csrf']}


def test_hashes_use_distinct_salts_and_reject_wrong_or_untrusted_parameters():
    first = security.password_hash('isolated-password-hash-test')
    second = security.password_hash('isolated-password-hash-test')
    assert first!=second and first.split('$')[4]!=second.split('$')[4]
    assert security.check_password('isolated-password-hash-test',first)
    assert not security.check_password('wrong-password',first)
    assert not security.check_password('isolated-password-hash-test',first.replace('$32768$','$1073741824$'))
    with pytest.raises(ValueError):security.password_hash('x'*13)
    assert security.check_password('x'*14,security.password_hash('x'*14))


def test_session_csrf_hash_storage_secure_cookie_and_security_headers(state):
    settings,app,_,_ = state
    with TestClient(app,base_url='https://localhost') as client:
        response,_ = sign_in(client)
        cookie = response.headers['set-cookie'].lower()
        assert all(value in cookie for value in ('httponly','secure','samesite=strict','path=/'))
        token = client.cookies.get('openreporting_session')
        csrf = response.json()['csrf']
        assert len(token)>=64 and len(csrf)>=43
        with db.connect(settings) as connection:
            row = connection.execute('SELECT token_hash,csrf_hash FROM sessions').fetchone()
            assert tuple(row)==(security.digest(token),security.digest(csrf))
            assert token not in tuple(row) and csrf not in tuple(row)
        for route in ('/','/api/user','/not-found'):
            headers = client.get(route).headers
            assert headers['x-frame-options']=='DENY' and headers['x-content-type-options']=='nosniff'
            csp = headers['content-security-policy']
            assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
            assert headers['referrer-policy']=='no-referrer' and 'max-age=' in headers['strict-transport-security']
        # HTTP transport must not receive the HTTPS-only session cookie.
        assert client.get('http://localhost/api/user').status_code==401


def test_csrf_refresh_rotates_old_token_and_logout_revokes_session(state):
    settings,app,_,_ = state
    with TestClient(app,base_url='https://localhost') as client:
        _,old = sign_in(client)
        assert client.post('/api/session/csrf').status_code==403
        refreshed = client.post('/api/session/csrf',headers={'Sec-Fetch-Site':'same-origin'})
        assert refreshed.status_code==200
        new = {'X-CSRF-Token':refreshed.json()['csrf']}
        assert new!=old
        assert client.post('/api/logout',headers=old).status_code==403
        assert client.get('/api/user').status_code==200
        assert client.post('/api/logout',headers=new).status_code==200
        assert client.get('/api/user').status_code==401
        with db.connect(settings) as connection:
            assert connection.execute('SELECT count(*) FROM sessions').fetchone()[0]==0


def test_admin_reset_revokes_every_old_session_and_weak_reset_is_nonmutating(state):
    settings,app,_,viewer = state
    with TestClient(app,base_url='https://localhost') as admin,TestClient(app,base_url='https://localhost') as first,TestClient(app,base_url='https://localhost') as second:
        _,headers = sign_in(admin)
        sign_in(first,'viewer1','isolated-viewer-password');sign_in(second,'viewer1','isolated-viewer-password')
        assert admin.post(f'/api/users/{viewer}/password',json={'password':'x'*13},headers=headers).status_code==422
        assert first.get('/api/user').status_code==200 and second.get('/api/user').status_code==200
        assert admin.post(f'/api/users/{viewer}/password',json={'password':'new-isolated-viewer-password'},headers=headers).status_code==200
        assert first.get('/api/user').status_code==401 and second.get('/api/user').status_code==401
        assert first.post('/api/login',json={'username':'viewer1','password':'isolated-viewer-password'}).status_code==401
        assert first.post('/api/login',json={'username':'viewer1','password':'new-isolated-viewer-password'}).status_code==200
        with db.connect(settings) as connection:
            assert connection.execute('SELECT count(*) FROM sessions WHERE user_id=?',(viewer,)).fetchone()[0]==1
            assert db.verify_audit(connection)==(True,None)


def test_source_credentials_are_encrypted_and_api_never_returns_the_value(state):
    settings,app,_,_ = state
    secret = 'isolated-fixture-bearer-value'
    with TestClient(app,base_url='https://localhost') as client:
        _,headers = sign_in(client)
        response = client.post('/api/datasources',headers=headers,json={'uid':'secured','name':'Secured fixture','type':'csv',
            'url':'https://source.example.test/read.csv','secureJsonData':{'token':secret}})
        assert response.status_code==201
        for route in ('/api/datasources','/api/datasources/secured'):
            response = client.get(route)
            assert response.status_code==200 and secret not in response.text and 'secure_json' not in response.text
        assert response.json()['secureJsonFields']['token'] is True
        with db.connect(settings) as connection:
            encoded = connection.execute("SELECT secure_json FROM datasources WHERE uid='secured'").fetchone()[0]
        assert secret not in encoded and decrypt(settings,encoded)=={'token':secret}
        assert key_path(settings).is_file() and key_path(settings)!=settings.db_path


def test_cli_reset_revokes_all_sessions_without_printing_password(state,monkeypatch,capsys):
    settings,app,_,viewer = state
    password = 'new-isolated-cli-password'
    monkeypatch.setattr(cli.Settings,'from_env',lambda:settings)
    monkeypatch.setattr(cli.getpass,'getpass',lambda prompt:password)
    with TestClient(app,base_url='https://localhost') as first,TestClient(app,base_url='https://localhost') as second:
        sign_in(first,'viewer1','isolated-viewer-password');sign_in(second,'viewer1','isolated-viewer-password')
        cli.main(['reset-password','viewer1'])
        output = capsys.readouterr()
        assert password not in output.out+output.err
        assert first.get('/api/user').status_code==401 and second.get('/api/user').status_code==401
        assert first.post('/api/login',json={'username':'viewer1','password':password}).status_code==200
        with db.connect(settings) as connection:
            assert connection.execute('SELECT count(*) FROM sessions WHERE user_id=?',(viewer,)).fetchone()[0]==1
            assert db.verify_audit(connection)==(True,None)
