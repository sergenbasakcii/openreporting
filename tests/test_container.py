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
