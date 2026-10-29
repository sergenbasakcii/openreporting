"""Read-only LDAP/Active Directory authentication over verified LDAPS/StartTLS."""
import json
import re
import ssl
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


class DirectoryUnavailable(Exception):
    """Sanitized operational error; never include server responses or credentials."""


@dataclass(frozen=True)
class Identity:
    subject: str
    role: str
    email: str = ""
    display_name: str = ""


def group_roles(settings):
    try:
        value = json.loads(settings.ldap_group_roles)
        if not isinstance(value, dict) or not value or any(not isinstance(k, str) or not k.strip() or v not in {"admin", "editor", "viewer"} for k, v in value.items()):
            raise ValueError
        return {k.strip().casefold(): v for k, v in value.items()}
    except (ValueError, TypeError):
        raise ValueError("LDAP_GROUP_ROLES must map group DNs to admin/editor/viewer") from None


def validate_settings(settings):
    if not settings.ldap_enabled:
        return
    try:
        url = urlsplit(settings.ldap_url)
        valid = url.scheme in {"ldaps", "ldap"} and url.hostname and not url.username and not url.password and url.path in {"", "/"} and not url.query and not url.fragment and (url.port is None or 1 <= url.port <= 65535)
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("LDAP_URL must be ldaps://host:636 or ldap://host:389 (mandatory StartTLS)")
    if not settings.ldap_bind_dn or not settings.ldap_bind_password or not settings.ldap_base_dn:
        raise ValueError("LDAP requires bind DN, bind password and base DN")
    if settings.ldap_user_filter.count("{username}") != 1 or "{" in settings.ldap_user_filter.replace("{username}", "") or "}" in settings.ldap_user_filter.replace("{username}", ""):
        raise ValueError("LDAP_USER_FILTER requires exactly one {username} placeholder")
    try:
        from ldap3.operation.search import parse_filter
        parse_filter(settings.ldap_user_filter.replace("{username}", "check"), None, False, False, None, False)
    except Exception:
        raise ValueError("Invalid LDAP_USER_FILTER syntax") from None
    for attr in (settings.ldap_id_attribute, settings.ldap_group_attribute):
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]*", attr):
            raise ValueError("Invalid LDAP attribute name")
    if not 1 <= settings.ldap_timeout <= 60 or not 5 <= settings.ldap_session_minutes <= 240:
        raise ValueError("Invalid LDAP timeout or session duration")
    if settings.ldap_ca_file and not Path(settings.ldap_ca_file).is_file():
        raise ValueError("LDAP_CA_FILE is unavailable")
    group_roles(settings)


@contextmanager
def _connection(settings, user, password):
    import ldap3
    url = urlsplit(settings.ldap_url)
    tls = ldap3.Tls(validate=ssl.CERT_REQUIRED, version=ssl.PROTOCOL_TLS_CLIENT,
                    ca_certs_file=settings.ldap_ca_file or None, valid_names=[url.hostname], sni=url.hostname,
                    ssl_options=[ssl.OP_NO_TLSv1, ssl.OP_NO_TLSv1_1])
    server = ldap3.Server(url.hostname, port=url.port or (636 if url.scheme == "ldaps" else 389),
                         use_ssl=url.scheme == "ldaps", tls=tls, connect_timeout=settings.ldap_timeout, get_info=ldap3.NONE)
    conn = ldap3.Connection(server, user=user, password=password, authentication=ldap3.SIMPLE,
                            read_only=True, auto_referrals=False, receive_timeout=settings.ldap_timeout,
                            check_names=False, raise_exceptions=False)
    try:
        conn.open()
        if conn.closed or (url.scheme == "ldap" and not conn.start_tls()):
            raise DirectoryUnavailable("LDAP güvenli bağlantısı kurulamadı")
        yield conn
    finally:
        conn.unbind()


def _values(attributes, name):
    value = next((v for k, v in attributes.items() if k.casefold() == name.casefold()), [])
    return value if isinstance(value, list) else [value]


def _text(attributes, name, limit):
    values = _values(attributes, name)
    return str(values[0])[:limit] if values else ""


def authenticate(settings, username, password):
    if not settings.ldap_enabled or not password or not username or len(username) > 80 or any(ord(c) < 32 for c in username):
        return None  # Empty passwords must never produce an anonymous bind.
    import ldap3
    from ldap3.utils.conv import escape_filter_chars
    try:
        with _connection(settings, settings.ldap_bind_dn, settings.ldap_bind_password) as service:
            if not service.bind():
                raise DirectoryUnavailable("LDAP servis hesabı bağlanamadı")
            service.search(settings.ldap_base_dn, settings.ldap_user_filter.replace("{username}", escape_filter_chars(username)),
                                search_scope=ldap3.SUBTREE, attributes=[settings.ldap_id_attribute, settings.ldap_group_attribute, "mail", "displayName"],
                                size_limit=2, time_limit=settings.ldap_timeout)
            if service.result.get("result") != 0:
                raise DirectoryUnavailable("LDAP kullanıcı araması tamamlanamadı")
            entries = [r for r in service.response if r.get("type") == "searchResEntry"]
            if len(entries) != 1:
                return None
            entry = entries[0]
            raw = _values(entry.get("raw_attributes", {}), settings.ldap_id_attribute)
            if len(raw) != 1 or not raw[0]:
                raise DirectoryUnavailable("LDAP kalıcı kullanıcı kimliği bulunamadı")
            subject = bytes(raw[0]).hex()
            if len(subject) > 1024:
                raise DirectoryUnavailable("LDAP kullanıcı kimliği geçersiz")
            attrs = entry.get("attributes", {})
            mapping = group_roles(settings)
            matches = {mapping[str(g).strip().casefold()] for g in _values(attrs, settings.ldap_group_attribute) if str(g).strip().casefold() in mapping}
            role = next((r for r in ("admin", "editor", "viewer") if r in matches), None)
            if not role:
                return None
            with _connection(settings, entry["dn"], password) as account:
                if not account.bind():
                    if account.result.get("result") == 49:
                        return None
                    raise DirectoryUnavailable("LDAP kullanıcı doğrulaması tamamlanamadı")
            email = _text(attrs, "mail", 254)
            if not re.fullmatch(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", email):
                email = ""
            return Identity(subject, role, email, _text(attrs, "displayName", 120))
    except DirectoryUnavailable:
        raise
    except Exception:
        raise DirectoryUnavailable("LDAP erişimi başarısız; TLS, DNS ve servis ayarlarını kontrol edin") from None


def check_connection(settings):
    if not settings.ldap_enabled:
        raise DirectoryUnavailable("LDAP kapalı")
    try:
        with _connection(settings, settings.ldap_bind_dn, settings.ldap_bind_password) as conn:
            if not conn.bind():
                raise DirectoryUnavailable("LDAP servis hesabı bağlanamadı")
            import ldap3
            if not conn.search(settings.ldap_base_dn, "(objectClass=*)", search_scope=ldap3.BASE, attributes=["objectClass"], size_limit=1, time_limit=settings.ldap_timeout):
                raise DirectoryUnavailable("LDAP arama tabanı okunamadı")
        return "TLS, servis hesabı ve arama tabanı doğrulandı"
    except DirectoryUnavailable:
        raise
    except Exception:
        raise DirectoryUnavailable("LDAP bağlantısı doğrulanamadı; TLS, DNS ve servis ayarlarını kontrol edin") from None
