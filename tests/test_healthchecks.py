"""A failed state store or audit check must never look healthy to an operator."""
import sqlite3
from contextlib import contextmanager
from dataclasses import replace

import psycopg
import pytest
from fastapi.testclient import TestClient

from openreporting import healthchecks, security, web
from openreporting.api import system
from openreporting.config import Settings


@pytest.fixture
def client(tmp_path):
    settings = replace(Settings.from_env(), data_dir=tmp_path, database_url='', secret_key_file='', secure_cookie=False,
                       ldap_enabled=False, mail_enabled=False, zabbix_url='', zabbix_token_file='')
    app = web.create_app(settings)
    security.create_user(settings, 'admin1', 'isolated-health-password', 'admin')
    with TestClient(app) as http:
        yield http


def sign_in(client):
    response = client.post('/api/login', json={'username':'admin1','password':'isolated-health-password'})
    assert response.status_code == 200


def unavailable(error):
    @contextmanager
    def connect(*args):
        raise error('sensitive-database-address-and-password')
        yield
    return connect


def test_live_health_and_authenticated_readiness_have_distinct_contracts(client):
    assert client.get('/healthz').json() == {'status':'up'}
    assert client.get('/api/health').status_code == 200
    assert client.get('/readyz').status_code == 401
    sign_in(client)
    ready = client.get('/readyz')
    assert ready.status_code == 200 and ready.json()['audit_chain_valid'] is True
    assert ready.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('error',[sqlite3.OperationalError,psycopg.OperationalError,OSError])
def test_database_failure_returns_503_without_disclosing_details(client,monkeypatch,error):
    monkeypatch.setattr(system,'connect',unavailable(error))
    response = client.get('/api/health')
    assert response.status_code == 503 and response.json()['database'] == 'failing'
    assert 'sensitive' not in response.text
    assert client.get('/healthz').status_code == 200


def test_schema_mismatch_is_unhealthy_even_when_select_one_succeeds(client,monkeypatch):
    monkeypatch.setattr(healthchecks,'schema_version',lambda db:0)
    assert client.get('/api/health').status_code == 503
    sign_in(client)
    assert client.get('/readyz').status_code == 503


def test_audit_chain_failure_blocks_readiness_but_not_liveness(client,monkeypatch):
    sign_in(client)
    monkeypatch.setattr(web,'verify_audit',lambda db:(False,42))
    response = client.get('/readyz')
    assert response.status_code == 503 and response.json()['audit_broken_id'] == 42
    assert client.get('/healthz').status_code == 200


@pytest.mark.parametrize('error',[sqlite3.OperationalError,psycopg.OperationalError,OSError])
def test_session_storage_failure_is_503_instead_of_uncaught_500(client,monkeypatch,error):
    sign_in(client)
    monkeypatch.setattr(security,'connect',unavailable(error))
    response = client.get('/readyz')
    assert response.status_code == 503 and 'sensitive' not in response.text
    assert client.get('/api/user').status_code == 503
