"""Admin-UI settings layered over the environment file (schema 6 ``app_settings``).

The environment file stays the bootstrap source. A value saved in the admin UI overrides it
per field; resetting a scope returns every field of that scope to the environment value.
Secrets are Fernet-sealed and bound to their scope. Every web process and the worker
re-read the table when its revision changes (checked at most every CHECK_INTERVAL_S).
"""
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, replace

from .db import audit, connect, transaction, utcnow
from .secrets_store import SecretError, decrypt, encrypt

log = logging.getLogger(__name__)

PAYLOAD_TYPE = 'settings-v1'
CHECK_INTERVAL_S = 2.0
ROLES = ('admin', 'editor', 'viewer')
SCOPES = ('mail', 'ldap', 'security', 'limits', 'sources')
# A scope whose stored values cannot be opened or validated turns its integration off.
FAIL_CLOSED = {'mail': 'mail_enabled', 'ldap': 'ldap_enabled'}

# field -> (scope, kind, environment variable)
FIELDS = {
    'mail_enabled': ('mail', 'bool', 'OPENREPORTING_MAIL_ENABLED'),
    'smtp_host': ('mail', 'text', 'OPENREPORTING_SMTP_HOST'),
    'smtp_port': ('mail', 'int', 'OPENREPORTING_SMTP_PORT'),
    'smtp_security': ('mail', 'choice:starttls,tls', 'OPENREPORTING_SMTP_SECURITY'),
    'smtp_user': ('mail', 'text', 'OPENREPORTING_SMTP_USER'),
    'smtp_password': ('mail', 'secret', 'OPENREPORTING_SMTP_PASSWORD'),
    'smtp_from': ('mail', 'text', 'OPENREPORTING_SMTP_FROM'),
    'recipient_domains': ('mail', 'domains', 'OPENREPORTING_ALLOWED_RECIPIENT_DOMAINS'),
    'smtp_ca_pem': ('mail', 'pem', ''),
    'smtp_timeout': ('mail', 'int', 'OPENREPORTING_SMTP_TIMEOUT'),
    'smtp_local_hostname': ('mail', 'text', 'OPENREPORTING_SMTP_LOCAL_HOSTNAME'),
    'ldap_enabled': ('ldap', 'bool', 'OPENREPORTING_LDAP_ENABLED'),
    'ldap_url': ('ldap', 'text', 'OPENREPORTING_LDAP_URL'),
    'ldap_bind_dn': ('ldap', 'text', 'OPENREPORTING_LDAP_BIND_DN'),
    'ldap_bind_password': ('ldap', 'secret', 'OPENREPORTING_LDAP_BIND_PASSWORD'),
    'ldap_base_dn': ('ldap', 'text', 'OPENREPORTING_LDAP_BASE_DN'),
    'ldap_user_filter': ('ldap', 'text', 'OPENREPORTING_LDAP_USER_FILTER'),
    'ldap_id_attribute': ('ldap', 'text', 'OPENREPORTING_LDAP_ID_ATTRIBUTE'),
    'ldap_group_attribute': ('ldap', 'text', 'OPENREPORTING_LDAP_GROUP_ATTRIBUTE'),
    'ldap_group_roles': ('ldap', 'group-roles', 'OPENREPORTING_LDAP_GROUP_ROLES'),
    'ldap_ca_pem': ('ldap', 'pem', ''),
    'ldap_timeout': ('ldap', 'int', 'OPENREPORTING_LDAP_TIMEOUT'),
    'ldap_session_minutes': ('ldap', 'int', 'OPENREPORTING_LDAP_SESSION_MINUTES'),
    'session_hours': ('security', 'int', 'OPENREPORTING_SESSION_HOURS'),
    'mfa_required_roles': ('security', 'roles', 'OPENREPORTING_MFA_REQUIRED_ROLES'),
    'query_timeout_ms': ('limits', 'int', 'OPENREPORTING_QUERY_TIMEOUT_MS'),
    'max_rows': ('limits', 'int', 'OPENREPORTING_MAX_ROWS'),
    'query_concurrency': ('limits', 'int', 'OPENREPORTING_QUERY_CONCURRENCY'),
    'max_series_points': ('limits', 'int', 'OPENREPORTING_MAX_SERIES_POINTS'),
    'report_retention_days': ('limits', 'int', 'OPENREPORTING_REPORT_RETENTION_DAYS'),
    'allow_http_datasources': ('sources', 'bool', 'OPENREPORTING_ALLOW_HTTP_DATASOURCES'),
    'allow_loopback_datasources': ('sources', 'bool', 'OPENREPORTING_ALLOW_LOOPBACK_DATASOURCES'),
}
SECRETS = {name for name, (_, kind, _) in FIELDS.items() if kind == 'secret'}
LABELS = {
    'mail_enabled': 'E-posta gönderimi', 'smtp_host': 'SMTP sunucusu', 'smtp_port': 'Port', 'smtp_security': 'Bağlantı güvenliği',
    'smtp_user': 'Kullanıcı adı', 'smtp_password': 'Parola', 'smtp_from': 'Gönderen adresi', 'recipient_domains': 'İzinli alıcı alan adları',
    'smtp_ca_pem': 'CA sertifikası', 'smtp_timeout': 'Zaman aşımı', 'smtp_local_hostname': 'EHLO adı', 'ldap_enabled': 'LDAP ile giriş',
    'ldap_url': 'Sunucu adresi', 'ldap_bind_dn': 'Servis hesabı', 'ldap_bind_password': 'Servis hesabı parolası', 'ldap_base_dn': 'Arama tabanı',
    'ldap_user_filter': 'Kullanıcı filtresi', 'ldap_id_attribute': 'Kimlik özniteliği', 'ldap_group_attribute': 'Grup özniteliği',
    'ldap_group_roles': 'Grup → rol eşlemesi', 'ldap_ca_pem': 'CA sertifikası', 'ldap_timeout': 'Zaman aşımı',
    'ldap_session_minutes': 'LDAP oturum süresi', 'session_hours': 'Oturum süresi', 'mfa_required_roles': 'İki adımlı giriş zorunlu roller',
    'query_timeout_ms': 'Sorgu zaman aşımı', 'max_rows': 'En fazla satır', 'query_concurrency': 'Paralel sorgu',
    'max_series_points': 'Nokta bütçesi', 'report_retention_days': 'Arşiv saklama', 'allow_http_datasources': 'Şifresiz HTTP kaynakları',
    'allow_loopback_datasources': 'Yerel servis kaynakları',
}


# Validation messages are written for the environment file; the admin UI shows them in Turkish.
MESSAGES = {
    'CA certificate must be PEM text': 'CA sertifikası PEM metni olmalı (en fazla 64 KB)',
    'Invalid CA certificate PEM': 'CA sertifikası okunamadı; PEM metnini kontrol edin',
    'Invalid LDAP attribute name': 'Kimlik/grup özniteliği adı geçersiz',
    'Invalid LDAP timeout or session duration': 'LDAP zaman aşımı 1–60 sn, oturum süresi 5–240 dk olmalı',
    'Invalid LDAP_USER_FILTER syntax': 'Kullanıcı filtresinin sözdizimi geçersiz',
    'Invalid SMTP port or timeout': 'SMTP portu 1–65535, zaman aşımı 1–120 sn olmalı',
    'Invalid SMTP recipient domain allowlist': 'İzinli alıcı alan adları geçersiz (örn. example.com)',
    'Invalid SMTP_LOCAL_HOSTNAME': 'EHLO adı geçersiz',
    'Invalid query concurrency or point budget': 'Paralel sorgu 1–64, nokta bütçesi 10.000–50.000.000 olmalı',
    'Invalid query timeout': 'Sorgu zaman aşımı 1000–300000 ms olmalı',
    'Invalid report retention': 'Arşiv saklama 0–36500 gün olmalı',
    'Invalid session duration or max rows': 'Oturum süresi 1–168 saat, en fazla satır 1–1.000.000 olmalı',
    'LDAP requires bind DN, bind password and base DN': 'LDAP için servis hesabı, servis parolası ve arama tabanı gerekli',
    'LDAP_CA_FILE is unavailable': 'Sunucu dosyasındaki LDAP CA dosyası bulunamadı',
    'LDAP_GROUP_ROLES must map': 'En az bir grup → rol eşlemesi gerekli',
    'LDAP_URL must be': 'Sunucu adresi ldaps://sunucu:636 veya ldap://sunucu:389 biçiminde olmalı',
    'LDAP_USER_FILTER requires': 'Kullanıcı filtresinde {username} tam bir kez geçmeli',
    'Mail requires SMTP host, sender and domain allowlist': 'E-posta için SMTP sunucusu, gönderen adresi ve en az bir izinli alan adı gerekli',
    'SMTP requires verified TLS': 'SMTP için STARTTLS veya doğrudan TLS seçilmeli',
    'SMTP_CA_FILE is unavailable': 'Sunucu dosyasındaki SMTP CA dosyası bulunamadı',
    'SMTP_HOST must be': 'SMTP sunucusu bir ana bilgisayar adı veya IP adresi olmalı',
    'SMTP_SECURITY must be': 'Bağlantı güvenliği STARTTLS veya TLS olmalı',
    'SMTP_USER and SMTP_PASSWORD': 'Kullanıcı adı ve parola birlikte girilmeli (relay için ikisi de boş)',
    'Invalid e-mail address': 'Gönderen adresi geçerli bir e-posta adresi olmalı',
    'Invalid MFA required role policy': 'İki adımlı giriş rolleri yalnız Yönetici/Editör/İzleyici olabilir',
}


def message(exc):
    text = str(exc)
    return next((tr for key, tr in MESSAGES.items() if text.startswith(key)), text)


class SettingsConflict(Exception):
    """The scope changed since the caller read it."""


def scope_fields(scope):
    return [name for name, spec in FIELDS.items() if spec[0] == scope]


# ---------------------------------------------------------------- value conversion

def clean_value(name, value):
    """Validate one JSON value from the admin UI; returns the JSON form that is stored."""
    kind, label = FIELDS[name][1], LABELS[name]
    if kind == 'bool':
        if not isinstance(value, bool):
            raise ValueError(f'{label}: true/false bekleniyor')
        return value
    if kind == 'int':
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f'{label}: tam sayı bekleniyor')
        return value
    if kind == 'pem':
        if not isinstance(value, str) or len(value) > 65536:
            raise ValueError(f'{label}: PEM metni bekleniyor (en fazla 64 KB)')
        return value.strip()
    if kind == 'domains':
        if not isinstance(value, list) or len(value) > 100 or any(not isinstance(d, str) or len(d) > 253 for d in value):
            raise ValueError(f'{label}: alan adı listesi bekleniyor')
        return list(dict.fromkeys(d.strip().lower() for d in value if d.strip()))
    if kind == 'roles':
        if not isinstance(value, list) or any(r not in ROLES for r in value):
            raise ValueError(f'{label}: admin/editor/viewer listesi bekleniyor')
        return [r for r in ROLES if r in value]
    if kind == 'group-roles':
        if not isinstance(value, dict) or len(value) > 200 or any(
                not isinstance(k, str) or not k.strip() or len(k) > 1024 or v not in ROLES for k, v in value.items()):
            raise ValueError(f'{label}: grup DN → admin/editor/viewer eşlemesi bekleniyor')
        return {k.strip(): v for k, v in value.items()}
    if not isinstance(value, str) or len(value) > 1024 or re.search(r'[\x00-\x1f\x7f]', value):
        raise ValueError(f'{label}: tek satır metin bekleniyor (en fazla 1024 karakter)')
    if kind.startswith('choice:') and value not in kind[7:].split(','):
        raise ValueError(f'{label}: geçersiz seçim')
    return value.strip()


def _to_settings(name, value):
    kind = FIELDS[name][1]
    if kind in ('domains', 'roles'):
        return tuple(value)
    if kind == 'group-roles':
        return json.dumps(value, separators=(',', ':'))
    return value


def _to_view(settings, name):
    from .mail_transport import security_mode
    value = getattr(settings, name)
    kind = FIELDS[name][1]
    if name == 'smtp_security':
        mode = security_mode(settings)
        return mode if mode in ('starttls', 'tls') else 'starttls'
    if kind in ('domains', 'roles'):
        return list(value)
    if kind == 'group-roles':
        try:
            parsed = json.loads(value or '{}')
            return parsed if isinstance(parsed, dict) else {}
        except ValueError:
            return {}
    return value


# ---------------------------------------------------------------- storage

def _seal(settings, scope, secrets):
    values = {k: v for k, v in secrets.items() if v}
    return encrypt(settings, {'type': PAYLOAD_TYPE, 'scope': scope, 'values': values}) if values else ''


def valid_payload(data, scope):
    if (not isinstance(data, dict) or set(data) != {'type', 'scope', 'values'} or data['type'] != PAYLOAD_TYPE
            or data['scope'] != scope or not isinstance(data['values'], dict)
            or any(FIELDS.get(k, ('',))[0] != scope or k not in SECRETS or not isinstance(v, str) for k, v in data['values'].items())):
        raise ValueError('Invalid sealed settings record')
    return data['values']


def _open(settings, row):
    if not row or not row['secure_json']:
        return {}
    return valid_payload(decrypt(settings, row['secure_json']), row['scope'])


def _rows(db):
    return {r['scope']: dict(r) for r in db.execute(
        '''SELECT a.scope,a.values_json,a.secure_json,a.revision,a.updated_at,a.updated_by,u.username
           FROM app_settings a LEFT JOIN users u ON u.id=a.updated_by''')}


def _scope_changes(settings, row):
    values = json.loads(row['values_json'] or '{}')
    changes = {k: _to_settings(k, v) for k, v in values.items() if FIELDS.get(k, ('',))[0] == row['scope']}
    changes.update(_open(settings, row))
    return changes


def build(base, rows):
    """Apply stored scopes in order. A broken scope is skipped and its integration is disabled."""
    result, errors = base, {}
    for scope in SCOPES:
        row = rows.get(scope)
        if not row:
            continue
        try:
            result = replace(result, **_scope_changes(base, row)).validate()
        except (SecretError, ValueError, TypeError) as exc:
            errors[scope] = 'Kayıtlı ayar açılamadı veya geçersiz; bu bölüm devre dışı' if isinstance(exc, SecretError) else message(exc)
            log.error('Stored %s settings ignored: %s', scope, errors[scope])
            if scope in FAIL_CLOSED:
                result = replace(result, **{FAIL_CLOSED[scope]: False})
    return result, errors


@dataclass
class _Entry:
    base: object
    signature: int
    checked: float
    settings: object
    errors: dict


_lock = threading.Lock()
_cache = {}


def _key(base):
    return base.database_url or str(base.data_dir)


def invalidate(base):
    with _lock:
        _cache.pop(_key(base), None)


def effective(base):
    """Current settings for this process: environment + admin UI overrides."""
    key, now = _key(base), time.monotonic()
    with _lock:
        entry = _cache.get(key)
        if entry and entry.base is base and now - entry.checked < CHECK_INTERVAL_S:
            return entry.settings
    try:
        with connect(base) as db:
            signature = db.execute('SELECT COALESCE(MAX(revision),0) FROM app_settings').fetchone()[0]
            if entry and entry.base is base and entry.signature == signature:
                entry.checked = now
                return entry.settings
            settings, errors = build(base, _rows(db))
    except Exception:  # noqa: BLE001 - storage errors surface on the request's own DB access
        log.exception('Admin settings could not be read; using the last known settings')
        return entry.settings if entry and entry.base is base else base
    with _lock:
        _cache[key] = _Entry(base, signature, now, settings, errors)
    return settings


# ---------------------------------------------------------------- admin operations

def admin_view(base):
    with connect(base) as db:
        rows = _rows(db)
    settings, errors = build(base, rows)
    out = {}
    for scope in SCOPES:
        row = rows.get(scope) or {}
        stored = json.loads(row.get('values_json') or '{}')
        try:
            sealed = _open(base, row) if row else {}
        except (SecretError, ValueError):
            sealed = {}
        fields = {}
        for name in scope_fields(scope):
            source = 'ui' if name in stored or name in sealed else 'server'
            env = FIELDS[name][2]
            if name in SECRETS:
                fields[name] = {'set': bool(getattr(settings, name)), 'source': source, 'env': env}
            else:
                fields[name] = {'value': _to_view(settings, name), 'source': source, 'env': env}
        out[scope] = {'fields': fields, 'revision': row.get('revision', 0), 'updated_at': row.get('updated_at'),
                      'updated_by': row.get('username'), 'error': errors.get(scope)}
    return out


def _candidate(base, rows, scope, values, secrets, *, current_row):
    """Effective settings if ``scope`` were stored with these values (strictly validated)."""
    unknown = set(values) - set(scope_fields(scope))
    unknown |= set(secrets) - (SECRETS & set(scope_fields(scope)))
    if unknown or set(values) & SECRETS:
        raise ValueError('Bilinmeyen ayar alanı: ' + ', '.join(sorted(unknown | (set(values) & SECRETS))))
    stored = json.loads((current_row or {}).get('values_json') or '{}')
    try:
        sealed = _open(base, current_row) if current_row else {}
    except (SecretError, ValueError):
        missing = [n for n in SECRETS & set(scope_fields(scope)) if secrets.get(n) is None and n in stored]
        if missing:
            raise ValueError('Kayıtlı parola çözülemedi; parolayı yeniden girin') from None
        sealed = {}
    stored.update({k: clean_value(k, v) for k, v in values.items()})
    for name, secret in secrets.items():
        if secret is None:
            continue
        if not isinstance(secret, str) or len(secret) > 4096 or '\x00' in secret:
            raise ValueError(f'{LABELS[name]}: geçersiz parola değeri')
        if secret:
            sealed[name] = secret
            stored.pop(name, None)
        else:  # explicit empty secret (e.g. TLS relay without authentication)
            sealed.pop(name, None)
            stored[name] = ''
    others = {k: v for k, v in rows.items() if k != scope}
    effective_others, _ = build(base, others)
    changes = {k: _to_settings(k, v) for k, v in stored.items()}
    changes.update(sealed)
    return replace(effective_others, **changes).validate(), stored, sealed


def save(base, scope, values, secrets, expected_revision, actor):
    if scope not in SCOPES:
        raise KeyError(scope)
    with connect(base) as db, transaction(db):
        rows = _rows(db)
        row = rows.get(scope)
        if (row['revision'] if row else 0) != expected_revision:
            raise SettingsConflict
        _, stored, sealed = _candidate(base, rows, scope, values, secrets, current_row=row)
        revision = db.execute('SELECT COALESCE(MAX(revision),0) FROM app_settings').fetchone()[0] + 1
        _write(db, scope, json.dumps(stored, sort_keys=True), _seal(base, scope, sealed), revision, actor)
        audit(db, actor, 'settings.updated', 'settings', scope,
              {'fields': sorted(values), 'secrets_changed': sorted(k for k, v in secrets.items() if v is not None)})
    invalidate(base)
    return revision


def reset(base, scope, expected_revision, actor):
    if scope not in SCOPES:
        raise KeyError(scope)
    with connect(base) as db, transaction(db):
        rows = _rows(db)
        row = rows.get(scope)
        if (row['revision'] if row else 0) != expected_revision:
            raise SettingsConflict
        build(base, {k: v for k, v in rows.items() if k != scope})[0].validate()
        revision = db.execute('SELECT COALESCE(MAX(revision),0) FROM app_settings').fetchone()[0] + 1
        _write(db, scope, '{}', '', revision, actor)
        audit(db, actor, 'settings.reset', 'settings', scope, {})
    invalidate(base)
    return revision


def _write(db, scope, values_json, secure_json, revision, actor):
    db.execute('''INSERT INTO app_settings(scope,values_json,secure_json,revision,updated_at,updated_by) VALUES(?,?,?,?,?,?)
                  ON CONFLICT(scope) DO UPDATE SET values_json=excluded.values_json,secure_json=excluded.secure_json,
                  revision=excluded.revision,updated_at=excluded.updated_at,updated_by=excluded.updated_by''',
               (scope, values_json, secure_json, revision, utcnow(), actor))


def test_candidate(base, scope, values, secrets):
    """Settings to try a connection with, without storing anything; the integration is forced on."""
    with connect(base) as db:
        rows = _rows(db)
    flag = FAIL_CLOSED[scope]
    candidate, _, _ = _candidate(base, rows, scope, {**values, flag: True}, secrets, current_row=rows.get(scope))
    return candidate
