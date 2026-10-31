"""Operator preflight must fail safely without initialization or secret output."""
from contextlib import contextmanager
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from openreporting import cli, postgres_check
from openreporting.config import Settings


@pytest.mark.parametrize('host,encrypted,mode,expected', [
    ('/var/run/postgresql', False, 'prefer', 'local_socket'),
    ('db.example.com', True, 'verify-full', 'verified_tls'),
    ('db.example.com', False, 'verify-full', 'unverified_tcp'),
    ('db.example.com', True, 'verify-ca', 'unverified_tcp'),
    ('db.example.com', True, 'require', 'unverified_tcp'),
    ('db.example.com', True, 'prefer', 'unverified_tcp'),
])
def test_transport_requires_verified_identity_for_tcp(host, encrypted, mode, expected):
    db = SimpleNamespace(raw=SimpleNamespace(info=SimpleNamespace(host=host, get_parameters=lambda: {'sslmode': mode}),
                                            pgconn=SimpleNamespace(ssl_in_use=encrypted)))
    assert postgres_check._transport(db) == expected


@pytest.mark.parametrize('dsn', ['', 'postgresql://synthetic:do-not-print@db.example.com/app'])
def test_cli_never_initializes_creates_keys_or_exposes_connection_errors(tmp_path, monkeypatch, capsys, dsn):
    settings = replace(Settings.from_env(), data_dir=tmp_path / 'must-stay-absent', database_url=dsn)
    monkeypatch.setattr(cli.Settings, 'from_env', lambda: settings)
    monkeypatch.setattr(cli, 'init_db', lambda *a: pytest.fail('Preflight cannot initialize/migrate'))
    @contextmanager
    def unavailable(*args, **kwargs):
        raise RuntimeError('do-not-print db.example.com secret-key customer-name')
        yield  # contextmanager contract; the connection never succeeds
    monkeypatch.setattr(postgres_check, 'connect', unavailable)
    with pytest.raises(SystemExit) as result:
        cli.main(['check-postgres'])
    assert result.value.code == 2
    captured = capsys.readouterr()
    assert not captured.err
    assert json.loads(captured.out) == {'ok': False, 'production_ready': False,
                                       'error': 'inspection_failed' if dsn else 'postgres_required'}
    assert not settings.data_dir.exists()
