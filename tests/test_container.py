"""Container deployment boundaries that can be checked without Docker."""
from pathlib import Path

import pytest

from openreporting.cli import forwarded_allow_ips

ROOT = Path(__file__).resolve().parents[1]


def test_proxy_trust_defaults_to_loopback_and_accepts_exact_addresses():
    assert forwarded_allow_ips('') == '127.0.0.1,::1'
    assert forwarded_allow_ips(' 172.30.88.10 , 10.0.0.0/8 ') == '172.30.88.10,10.0.0.0/8'


@pytest.mark.parametrize('value', ['*', 'proxy.local', '172.30.88.10,*', '300.1.1.1'])
def test_proxy_trust_rejects_wildcards_and_names(value):
    with pytest.raises(ValueError):
        forwarded_allow_ips(value)


def test_compose_publishes_only_the_tls_proxy_and_pins_proxy_trust():
    compose = (ROOT / 'docker-compose.yml').read_text(encoding='utf-8')
    web = compose.split('\n  web:\n', 1)[1].split('\n  worker:\n', 1)[0]
    assert 'ports' not in web
    assert 'OPENREPORTING_FORWARDED_ALLOW_IPS: ${OPENREPORTING_PROXY_IP:-172.30.88.10}' in compose
    assert 'ipv4_address: "${OPENREPORTING_PROXY_IP:-172.30.88.10}"' in compose
    nginx = (ROOT / 'deploy/docker/nginx.conf').read_text(encoding='utf-8')
    assert 'location = /metrics { return 404; }' in nginx and 'X-Forwarded-Proto https' in nginx


def test_container_settings_hint_points_to_compose(monkeypatch):
    from openreporting.api.settings import _restart_hint
    monkeypatch.setenv('OPENREPORTING_CONTAINER', '1')
    assert _restart_hint()['env_file'].startswith('deploy/docker/openreporting.env')


def test_worker_health_reflects_heartbeat_age(tmp_path):
    from dataclasses import replace
    from datetime import datetime, timedelta, timezone
    from openreporting.cli import worker_health
    from openreporting.config import Settings
    from openreporting.db import connect, init_db, transaction
    settings = replace(Settings.from_env(), data_dir=tmp_path / 'data', database_url='', secret_key_file='')
    assert worker_health(settings, 120) == 1  # no store: never created by the probe
    assert not settings.db_path.exists()
    init_db(settings)
    assert worker_health(settings, 120) == 1  # worker never started
    with connect(settings) as db:
        columns = {r[1] for r in db.execute('PRAGMA table_info(worker_runtime)')}
    for age, expected in ((10, 0), (500, 1)):
        tick = (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat(timespec='seconds')
        values = {'singleton_id': 1, 'last_tick': tick}
        values.update({c: '' for c in columns - set(values)})
        with connect(settings) as db, transaction(db):
            db.execute('DELETE FROM worker_runtime')
            db.execute(f"INSERT INTO worker_runtime({','.join(values)}) VALUES({','.join('?' * len(values))})", tuple(values.values()))
        assert worker_health(settings, 120) == expected


def test_required_key_file_is_never_generated(tmp_path, monkeypatch):
    from dataclasses import replace
    from openreporting.config import Settings
    from openreporting.secrets_store import SecretError, encrypt, key_path, reset_cache
    settings = replace(Settings.from_env(), data_dir=tmp_path / 'data', database_url='', secret_key_file=str(tmp_path / 'missing.key'))
    monkeypatch.setenv('OPENREPORTING_REQUIRE_KEY_FILE', 'true')
    reset_cache()
    with pytest.raises(SecretError, match='önceden sağlanmalı'):
        encrypt(settings, {'token': 'value'})
    assert not key_path(settings).exists()
    reset_cache()
