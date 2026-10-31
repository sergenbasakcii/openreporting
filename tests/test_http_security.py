"""Host/rebinding and browser-origin boundaries, including local IPv6 and proxies."""
from dataclasses import replace

from fastapi.testclient import TestClient
import pytest

from openreporting.config import Settings
from openreporting import db, security
from openreporting.web import create_app


@pytest.fixture
def settings(tmp_path):
    return replace(Settings.from_env(),data_dir=tmp_path,database_url='',secret_key_file='',public_url='',
                   allowed_hosts=(),secure_cookie=False,ldap_enabled=False,mail_enabled=False,zabbix_url='',zabbix_token_file='')


@pytest.mark.parametrize('host',['attacker.example.com','localhost.attacker.example.com','testserver','[invalid','user@localhost'])
def test_unknown_or_malformed_host_is_rejected_without_redirect(settings,host):
    with TestClient(create_app(settings),base_url='http://localhost') as http:
        response = http.get('/api/health',headers={'Host':host})
        assert response.status_code==400 and 'location' not in response.headers
        assert response.headers['x-content-type-options']=='nosniff'


@pytest.mark.parametrize('url',['http://localhost','http://127.0.0.1:8811','http://[::1]:8811'])
def test_default_local_hosts_are_explicit_and_ipv6_compatible(settings,url):
    with TestClient(create_app(settings),base_url=url) as http:
        assert http.get('/api/health').status_code==200


def test_public_host_and_explicit_alias_are_allowed(settings):
    settings = replace(settings,public_url='https://reports.example.com',secure_cookie=True,allowed_hosts=('alias.example.com',))
    with TestClient(create_app(settings),base_url='https://reports.example.com') as http:
        assert http.get('/api/health').status_code==200
        assert http.get('/api/health',headers={'Host':'alias.example.com'}).status_code==200
        assert http.get('/api/health',headers={'Host':'reports.example.com.attacker.example.com'}).status_code==400
        assert http.get('/api/health',headers=[('Host','reports.example.com'),('Host','attacker.example.com')]).status_code==400
    expanded = replace(settings,public_url='https://[0:0:0:0:0:0:0:1]:8811')
    with TestClient(create_app(expanded),base_url='https://[0:0:0:0:0:0:0:1]:8811') as http:
        assert http.get('/api/health').status_code==200


@pytest.mark.parametrize('origin',['https://attacker.example.com','http://localhost:8812','https://localhost:8811','null','http://user:secret@localhost:8811'])
def test_cross_origin_login_cannot_create_account_session_or_failed_attempt(settings,origin):
    with TestClient(create_app(settings),base_url='http://localhost:8811') as http:
        response = http.post('/api/login',json={'username':'reader','password':'wrong'},headers={'Origin':origin})
        assert response.status_code==403 and 'set-cookie' not in response.headers
        assert 'secret' not in response.text
    with db.connect(settings) as connection:
        assert connection.execute('SELECT COUNT(*) FROM login_failures').fetchone()[0]==0


def test_same_origin_and_api_clients_work_but_cross_site_signal_is_rejected(settings):
    app=create_app(settings)
    security.create_user(settings,'admin1','isolated-origin-password','admin')
    security.create_user(settings,'viewer1','isolated-viewer-password','viewer')
    with TestClient(app,base_url='http://localhost') as http:
        body={'username':'admin1','password':'isolated-origin-password'}
        assert http.post('/api/login',json=body,headers={'Origin':'http://LOCALHOST:80'}).status_code==200
        assert http.post('/api/login',json=body).status_code==200
        assert http.post('/api/login',json=body,headers={'Sec-Fetch-Site':'cross-site'}).status_code==403
        assert http.post('/api/login',json=body,headers=[('Origin','http://localhost'),('Origin','http://attacker.example.com')]).status_code==403
        assert http.options('/api/login',headers={'Origin':'http://attacker.example.com','Access-Control-Request-Method':'POST'}).headers.get('access-control-allow-origin') is None
        response=http.post('/api/login',json={'username':'viewer1','password':'isolated-viewer-password'})
        assert response.status_code==200 and http.get('/readyz').status_code==403


@pytest.mark.parametrize('setting,value',[
    ('OPENREPORTING_ALLOWED_HOSTS','*'),('OPENREPORTING_ALLOWED_HOSTS','*.example.com'),('OPENREPORTING_ALLOWED_HOSTS','https://example.com'),
    ('OPENREPORTING_ALLOWED_HOSTS','example.com:8811'),('OPENREPORTING_PUBLIC_URL','https://user:secret@example.com'),
    ('OPENREPORTING_PUBLIC_URL','https://example.com/prefix'),('OPENREPORTING_PUBLIC_URL','http://example.com'),
    ('OPENREPORTING_PUBLIC_URL','https://example.com:0'),('OPENREPORTING_PUBLIC_URL','https://example.com?secret=hidden'),
])
def test_unsafe_host_and_public_url_configuration_fails_without_secret_echo(monkeypatch,setting,value):
    monkeypatch.setenv(setting,value)
    monkeypatch.setenv('OPENREPORTING_COOKIE_SECURE','true')
    with pytest.raises(ValueError) as error:
        Settings.from_env()
    assert 'secret' not in str(error.value) and 'hidden' not in str(error.value)
