"""Fail startup for unsafe integration configuration and never echo secrets."""

from dataclasses import replace

import pytest

from openreporting.config import Settings
from openreporting import directory_auth, mail_transport


def test_mounted_secrets_are_redacted_and_ambiguous_sources_rejected(monkeypatch, tmp_path):
    secret = tmp_path / "password"
    secret.write_text("isolated-file-secret\n", encoding="utf8")
    for name in ("OPENREPORTING_SMTP_PASSWORD", "OPENREPORTING_LDAP_BIND_PASSWORD"):
        monkeypatch.setenv(name + "_FILE", str(secret))
    settings = Settings.from_env()
    assert settings.smtp_password == settings.ldap_bind_password == "isolated-file-secret"
    assert "isolated-file-secret" not in repr(settings)
    monkeypatch.setenv("OPENREPORTING_SMTP_PASSWORD", "isolated-inline-secret")
    with pytest.raises(ValueError) as error:
        Settings.from_env()
    assert "isolated-inline-secret" not in str(error.value)


@pytest.mark.parametrize(
    "overrides",
    [
        {"smtp_security": "none"},
        {"smtp_security": "invalid"},
        {"smtp_port": 0},
        {"smtp_timeout": 0},
        {"smtp_user": "reporter", "smtp_password": ""},
        {"smtp_from": "x\r\nBcc:other@example.com"},
        {"smtp_host": "smtp://host.example.com"},
        {"recipient_domains": ("*.example.com",)},
        {"smtp_ca_file": "does-not-exist.pem"},
    ],
)
def test_invalid_smtp_fails_before_connection(overrides):
    settings = replace(
        Settings.from_env(), mail_enabled=True, smtp_host="smtp.example.com", smtp_from="reports@example.com", recipient_domains=("example.com",)
    )
    with pytest.raises(ValueError):
        mail_transport.validate_settings(replace(settings, **overrides))


@pytest.mark.parametrize(
    "overrides",
    [
        {"ldap_url": "http://example.com"},
        {"ldap_url": "ldaps://user:secret@example.com"},
        {"ldap_url": "ldap://example.com:0"},
        {"ldap_user_filter": "(uid={username}{username})"},
        {"ldap_user_filter": "not-a-filter{username}"},
        {"ldap_id_attribute": "objectGUID,mail"},
        {"ldap_group_roles": "{}"},
        {"ldap_group_roles": '{"group":"superuser"}'},
        {"ldap_bind_password": ""},
        {"ldap_session_minutes": 0},
        {"ldap_ca_file": "missing.pem"},
    ],
)
def test_invalid_ldap_fails_before_connection(overrides):
    settings = replace(
        Settings.from_env(),
        ldap_enabled=True,
        ldap_url="ldaps://directory.example.com",
        ldap_bind_dn="cn=reader,dc=example,dc=com",
        ldap_bind_password="isolated-password",
        ldap_base_dn="dc=example,dc=com",
        ldap_group_roles='{"cn=readers,dc=example,dc=com":"viewer"}',
    )
    with pytest.raises(ValueError):
        directory_auth.validate_settings(replace(settings, **overrides))
