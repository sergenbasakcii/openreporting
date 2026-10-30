"""Explicit offline credential rekeying; preparation never replaces the active key."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from .db import CURRENT_VERSION, audit, schema_version, transaction, verify_audit
from .secrets_store import KEYRING_FORMAT, MAX_KEYS, SecretError, key_id, key_path, read_keys


def _write_new(settings, output, keys):
    target = Path(output).absolute()
    if target.resolve()==key_path(settings).resolve():
        raise SecretError('Output must differ from the active key file')
    payload = {'format':KEYRING_FORMAT,'keys':[{'id':key_id(key),'key':key.decode('ascii')} for key in keys]}
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os,'O_BINARY',0) | getattr(os,'O_NOFOLLOW',0)
        with os.fdopen(os.open(target,flags,0o600),'wb') as handle:
            handle.write((json.dumps(payload,separators=(',',':'))+'\n').encode('ascii'))
            handle.flush();os.fsync(handle.fileno())
    except OSError:
        raise SecretError('Cannot create a new key file; existing outputs are never overwritten') from None
    return {'primary_id':key_id(keys[0]),'key_count':len(keys)}


def prepare_rotation(settings, output):
    keys = read_keys(key_path(settings))
    if len(keys)>=MAX_KEYS:
        raise SecretError('Key ring limit reached; retire verified old keys first')
    return _write_new(settings,output,[Fernet.generate_key(),*keys])


def _connection(settings, *, readonly=False):
    if settings.database_url:
        raise SecretError('Offline key rotation currently supports the production SQLite baseline only')
    # URI mode refuses a missing store instead of creating an empty replacement.
    db = sqlite3.connect(settings.db_path.resolve().as_uri()+('?mode=ro' if readonly else '?mode=rw'),uri=True,timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    return db


def _check_database(db):
    if schema_version(db)!=CURRENT_VERSION or not verify_audit(db)[0]:
        raise SecretError('Matching schema and valid audit chain are required')


def rekey_secrets(settings, *, services_stopped=False):
    if not services_stopped:
        raise SecretError('Offline maintenance is required: stop every web process and worker first')
    keys = read_keys(key_path(settings))
    if len(keys)<2:
        raise SecretError('A prepared key ring with retained previous keys is required')
    cipher = MultiFernet([Fernet(key) for key in keys])
    primary = Fernet(keys[0])
    try:
        with closing(_connection(settings)) as db, transaction(db):
            _check_database(db)
            changed = 0
            for row in db.execute("SELECT id,secure_json FROM datasources WHERE secure_json<>''").fetchall():
                token = row['secure_json'].encode('ascii')
                # Idempotent: don't rewrite tokens already on the primary key.
                try:
                    if not isinstance(json.loads(primary.decrypt(token)),dict):
                        raise ValueError('Invalid credential record')
                    continue
                except InvalidToken:
                    pass
                rotated = cipher.rotate(token)
                if not isinstance(json.loads(primary.decrypt(rotated)),dict):
                    raise ValueError('Invalid credential record')
                db.execute('UPDATE datasources SET secure_json=? WHERE id=?',(rotated.decode('ascii'),row['id']))
                changed += 1
            if changed:
                audit(db,'os-admin','secrets.rekeyed','keyring',key_id(keys[0]),{'sources':changed,'retained_key_ids':[key_id(k) for k in keys[1:]]})
        return {'primary_id':key_id(keys[0]),'sources_rekeyed':changed}
    except SecretError:
        raise
    except Exception:
        raise SecretError('Credential rekey failed; database transaction was rolled back') from None


def prepare_retirement(settings, output, *, services_stopped=False):
    if not services_stopped:
        raise SecretError('Offline maintenance is required before retiring keys')
    keys = read_keys(key_path(settings))
    primary = Fernet(keys[0])
    try:
        with closing(_connection(settings,readonly=True)) as db:
            db.execute('BEGIN')
            _check_database(db)
            for row in db.execute("SELECT secure_json FROM datasources WHERE secure_json<>''"):
                if not isinstance(json.loads(primary.decrypt(row[0].encode('ascii'))),dict):
                    raise ValueError('Invalid credential record')
    except SecretError:
        raise
    except Exception:
        raise SecretError('Old keys still required or database verification failed; no retirement file created') from None
    return _write_new(settings,output,[keys[0]])
