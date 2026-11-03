"""Datasource registry: persistence, validation, provisioning and instances."""

import json
import re

from ..db import audit, connect, transaction, utcnow
from ..domain import identity
from ..secrets_store import decrypt, encrypt
from ..timerange import parse_duration
from .base import DataSourceError, QueryContext, QueryResult  # noqa: F401 - re-exported
from .postgres import SSL_MODES, PostgresDataSource
from .testdata import SCENARIOS, TestDataSource
from .zabbix import ZabbixDataSource, validate_url

from .http_sources import PrometheusDataSource, LokiDataSource, JSONDataSource, CSVDataSource, validate_http_url

TYPES = {
    "prometheus": PrometheusDataSource,
    "loki": LokiDataSource,
    "httpjson": JSONDataSource,
    "csv": CSVDataSource,
    "zabbix": ZabbixDataSource,
    "postgres": PostgresDataSource,
    "testdata": TestDataSource,
}
TYPE_INFO = [
    {"type": "zabbix", "name": "Zabbix", "description": "Zabbix API: host grupları, hostlar, item'lar, history/trend, problemler", "secure_fields": ["token"]},
    {
        "type": "postgres",
        "name": "PostgreSQL / TimescaleDB",
        "description": "Salt-okunur SQL sorguları, Grafana makroları; TimescaleDB’deki Zabbix geçmişi",
        "secure_fields": ["password"],
    },
    {"type": "testdata", "name": "TestData (sentetik)", "description": "Gerçek olmayan, deterministik örnek veri ve Zabbix simülasyonu", "secure_fields": []},
]
TYPE_INFO += [
    {"type": kind, "name": name, "description": description, "secure_fields": ["token"]}
    for kind, name, description in [
        ("prometheus", "Prometheus / Mimir / VictoriaMetrics", "PromQL zaman serileri"),
        ("loki", "Loki", "LogQL log ve metrik sorguları"),
        ("httpjson", "HTTP JSON", "REST uç noktasından tablo"),
        ("csv", "HTTP CSV", "CSV uç noktasından tablo"),
    ]
]
SECURE_FIELDS = {t["type"]: t["secure_fields"] for t in TYPE_INFO}
_UID = re.compile(r"^[A-Za-z0-9_-]{2,40}$")
_TABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")


def _row(row):
    record = dict(row)
    record["json_data"] = json.loads(record.get("json_data") or "{}")
    return record


def public(record, settings=None):
    """Datasource as seen by the browser: secrets replaced by booleans."""
    configured = {}
    if record.get("secure_json") and settings is not None:
        try:
            configured = {k: True for k in decrypt(settings, record["secure_json"])}
        except Exception:  # noqa: BLE001 - surface as "not configured"
            configured = {}
    if record.get("json_data", {}).get("token_file"):
        configured["token"] = True
    data = {k: v for k, v in record["json_data"].items() if k != "token_file"}
    return {
        "uid": record["uid"],
        "name": record["name"],
        "type": record["type"],
        "url": record.get("url", ""),
        "jsonData": data,
        "secureJsonFields": configured,
        "isDefault": bool(record.get("is_default")),
        "readOnly": bool(record.get("provisioned")),
        "updated_at": record.get("updated_at"),
    }


def _pem(text):
    if not text:
        return ""
    if len(text) > 65536 or "-----BEGIN CERTIFICATE-----" not in text:
        raise DataSourceError("CA sertifikası PEM biçiminde olmalı (-----BEGIN CERTIFICATE-----)")
    return text.strip() + "\n"


def _int(data, key, default):
    try:
        return int(data.get(key, default))
    except (TypeError, ValueError):
        raise DataSourceError(f"{key} bir tam sayı olmalı") from None


def validate(kind, url, json_data, settings):
    if kind not in TYPES:
        raise DataSourceError("Unsupported datasource type")
    data = dict(json_data or {})
    clean = {}
    if data.get("time_interval"):
        parse_duration(data["time_interval"])
        clean["time_interval"] = str(data["time_interval"])
    if kind == "zabbix":
        validate_url(url, getattr(settings, "allow_http_datasources", False))
        clean["auth_mode"] = data.get("auth_mode", "bearer") if data.get("auth_mode") in ("bearer", "body") else "bearer"
        for key, default in (("trends_from", "7d"), ("trends_range", "4d")):
            clean[key] = str(data.get(key) or default)
            parse_duration(clean[key])
        clean["cache_ttl"] = max(0, min(_int(data, "cache_ttl", 60), 3600))
        clean["timeout"] = max(3, min(_int(data, "timeout", 30), 300))
        clean["max_items"] = max(1, min(_int(data, "max_items", 500), 20000))
        clean["ca_pem"] = _pem(data.get("ca_pem", ""))
        clean["history_source"] = "sql" if data.get("history_source") == "sql" else "api"
        if clean["history_source"] == "sql":
            if not data.get("sql_datasource_uid"):
                raise DataSourceError("SQL history için bağlı PostgreSQL veri kaynağı seçin")
            clean["sql_datasource_uid"] = str(data["sql_datasource_uid"])
            for key, default in (
                ("history_table_float", "history"),
                ("history_table_uint", "history_uint"),
                ("trends_table_float", "trends"),
                ("trends_table_uint", "trends_uint"),
            ):
                value = str(data.get(key) or default)
                if not _TABLE.match(value):
                    raise DataSourceError(f"Geçersiz tablo adı: {value}")
                clean[key] = value
    elif kind in ("prometheus", "loki", "httpjson", "csv"):
        url = validate_http_url(url, settings.allow_http_datasources)
        clean["timeout"] = max(3, min(_int(data, "timeout", 30), 60))
        clean["ca_pem"] = _pem(data.get("ca_pem", ""))
        clean["root"] = str(data.get("root") or "")[:200]
    elif kind == "postgres":
        for key in ("host", "database", "user"):
            value = str(data.get(key, "")).strip()
            if not value or len(value) > 255 or any(ord(c) < 32 for c in value):
                raise DataSourceError(f"PostgreSQL {key} gerekli")
            clean[key] = value
        clean["port"] = max(1, min(int(data.get("port", 5432) or 5432), 65535))
        clean["sslmode"] = data.get("sslmode", "verify-full")
        if clean["sslmode"] not in SSL_MODES:
            raise DataSourceError("Geçersiz sslmode")
        clean["ca_pem"] = _pem(data.get("ca_pem", ""))
        clean["timeout_ms"] = max(1000, min(_int(data, "timeout_ms", 30000), 300000))
        clean["max_rows"] = max(1, min(_int(data, "max_rows", 200000), 1_000_000))
        url = f"{clean['host']}:{clean['port']}/{clean['database']}"
    else:
        url = ""
    return url, clean


def instance(settings, record, *, transport=None, registry_db=None):
    secure = decrypt(settings, record.get("secure_json", ""))
    kind = TYPES[record["type"]]
    if record["type"] == "zabbix":
        return kind(record, secure, settings, transport=transport, resolver=lambda uid: get(settings, uid) if uid else None)
    return kind(record, secure, settings)


def load(settings, uid_or_name=None):
    with connect(settings) as db:
        if uid_or_name:
            row = db.execute("SELECT * FROM datasources WHERE uid=? OR name=?", (uid_or_name, uid_or_name)).fetchone()
        else:
            row = db.execute("SELECT * FROM datasources ORDER BY is_default DESC, created_at LIMIT 1").fetchone()
    return _row(row) if row else None


def get(settings, uid_or_name=None, *, transport=None):
    record = load(settings, uid_or_name)
    if record is None:
        raise DataSourceError(f"Veri kaynağı bulunamadı: {uid_or_name or 'varsayılan'}")
    return instance(settings, record, transport=transport)


def list_all(settings):
    with connect(settings) as db:
        rows = db.execute("SELECT * FROM datasources ORDER BY LOWER(name),uid").fetchall()
    return [public(_row(r), settings) for r in rows]


# Connection target fields; changing any of them invalidates stored credentials.
DESTINATION_KEYS = ("host", "port", "sslmode", "ca_pem", "auth_mode")


def save(settings, actor, body, uid=None):
    kind = body.get("type")
    name = str(body.get("name", "")).strip()
    if not 2 <= len(name) <= 100 or any(ord(c) < 32 for c in name):
        raise DataSourceError("Veri kaynağı adı 2-100 karakter olmalı")
    url, json_data = validate(kind, str(body.get("url", "")).strip(), body.get("jsonData") or {}, settings)
    secure_in = {k: v for k, v in (body.get("secureJsonData") or {}).items() if k in SECURE_FIELDS.get(kind, []) and isinstance(v, str)}
    now = utcnow()
    with connect(settings) as db, transaction(db):
        if uid:
            row = db.execute("SELECT * FROM datasources WHERE uid=?", (uid,)).fetchone()
            if not row:
                raise DataSourceError("Veri kaynağı bulunamadı")
            if row["provisioned"]:
                raise DataSourceError("Ortam dosyasından tanımlı (provisioned) veri kaynağı arayüzden değiştirilemez")
            if row["type"] != kind:
                raise DataSourceError("Veri kaynağı türü değiştirilemez")
            secure = decrypt(settings, row["secure_json"])
            for key in body.get("secureJsonReset") or []:
                secure.pop(key, None)
            # Stored credentials are bound to their destination: a new address needs them re-entered,
            # otherwise an edited URL/host would send the old token or password to that address.
            old_data = json.loads(row["json_data"] or "{}")
            moved = url != row["url"] or any(json_data.get(k) != old_data.get(k) for k in DESTINATION_KEYS)
            kept = [k for k in secure if not secure_in.get(k)]
            if moved and kept:
                raise DataSourceError("Adres değiştiği için kayıtlı kimlik bilgisi (token/parola) yeniden girilmeli")
            secure.update({k: v for k, v in secure_in.items() if v})
            if db.execute("SELECT 1 FROM datasources WHERE name=? AND uid<>?", (name, uid)).fetchone():
                raise DataSourceError("Bu adla başka bir veri kaynağı var")
            db.execute(
                """UPDATE datasources SET name=?,url=?,json_data=?,secure_json=?,updated_at=?,updated_by=?
                          WHERE uid=?""",
                (name, url, json.dumps(json_data), encrypt(settings, secure), now, actor, uid),
            )
            target_uid = uid
            action = "datasource.updated"
        else:
            target_uid = str(body.get("uid") or identity().split("-")[0])
            if not _UID.match(target_uid):
                raise DataSourceError("Geçersiz uid")
            if db.execute("SELECT 1 FROM datasources WHERE uid=? OR name=?", (target_uid, name)).fetchone():
                raise DataSourceError("Bu ad veya uid zaten kullanılıyor")
            first = db.execute("SELECT COUNT(*) FROM datasources").fetchone()[0] == 0
            db.execute(
                """INSERT INTO datasources(id,uid,name,type,url,json_data,secure_json,is_default,provisioned,
                          created_at,updated_at,updated_by) VALUES(?,?,?,?,?,?,?,?,0,?,?,?)""",
                (
                    identity(),
                    target_uid,
                    name,
                    kind,
                    url,
                    json.dumps(json_data),
                    encrypt(settings, secure_in),
                    int(first or bool(body.get("isDefault"))),
                    now,
                    now,
                    actor,
                ),
            )
            action = "datasource.created"
        if body.get("isDefault"):
            db.execute("UPDATE datasources SET is_default=CASE WHEN uid=? THEN 1 ELSE 0 END", (target_uid,))
        audit(db, actor, action, "datasource", target_uid, {"type": kind, "name": name, "secrets_changed": sorted(secure_in)})
    return target_uid


def delete(settings, actor, uid):
    with connect(settings) as db, transaction(db):
        row = db.execute("SELECT * FROM datasources WHERE uid=?", (uid,)).fetchone()
        if not row:
            raise DataSourceError("Veri kaynağı bulunamadı")
        if row["provisioned"]:
            raise DataSourceError("Provisioned veri kaynağı silinemez")
        db.execute("DELETE FROM datasources WHERE uid=?", (uid,))
        if row["is_default"]:
            db.execute("UPDATE datasources SET is_default=1 WHERE uid=(SELECT uid FROM datasources ORDER BY created_at LIMIT 1)")
        audit(db, actor, "datasource.deleted", "datasource", uid, {"name": row["name"]})


def provision(settings):
    """Mirror environment configuration as read-only datasources (idempotent)."""
    wanted = []
    if settings.zabbix_url and settings.zabbix_token_file:
        wanted.append(
            (
                "zabbix-env",
                "Zabbix (ortam ayarı)",
                "zabbix",
                settings.zabbix_url,
                {
                    "auth_mode": "bearer",
                    "trends_from": "7d",
                    "trends_range": "4d",
                    "cache_ttl": 60,
                    "timeout": 30,
                    "max_items": 500,
                    "token_file": settings.zabbix_token_file,
                    "history_source": "api",
                    "ca_pem": _read_ca(settings.zabbix_ca_file),
                },
            )
        )
    if settings.provision_testdata:
        wanted.append(("testdata", "TestData (sentetik)", "testdata", "", {}))
    now = utcnow()
    with connect(settings) as db, transaction(db):
        for uid, name, kind, url, data in wanted:
            row = db.execute("SELECT uid FROM datasources WHERE uid=?", (uid,)).fetchone()
            if row:
                db.execute("UPDATE datasources SET url=?,json_data=?,updated_at=? WHERE uid=? AND provisioned=1", (url, json.dumps(data), now, uid))
                continue
            if db.execute("SELECT 1 FROM datasources WHERE name=?", (name,)).fetchone():
                continue
            first = db.execute("SELECT COUNT(*) FROM datasources").fetchone()[0] == 0
            db.execute(
                """INSERT INTO datasources(id,uid,name,type,url,json_data,secure_json,is_default,provisioned,
                          created_at,updated_at,updated_by) VALUES(?,?,?,?,?,?,'',?,1,?,?,'provisioning')""",
                (identity(), uid, name, kind, url, json.dumps(data), int(first), now, now),
            )
        # A real Zabbix should be default over the synthetic source.
        if any(w[0] == "zabbix-env" for w in wanted):
            default = db.execute("SELECT type FROM datasources WHERE is_default=1").fetchone()
            if default is None or default["type"] == "testdata":
                db.execute("UPDATE datasources SET is_default=CASE WHEN uid='zabbix-env' THEN 1 ELSE 0 END")


def _read_ca(path):
    if not path:
        return ""
    try:
        with open(path, encoding="utf8") as handle:
            return handle.read()
    except OSError:
        return ""


def scenarios():
    return [{"value": k, "label": v} for k, v in SCENARIOS.items()]
