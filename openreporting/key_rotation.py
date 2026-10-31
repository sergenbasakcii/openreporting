"""Explicit offline credential rekeying; preparation never replaces the active key."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from .db import CURRENT_VERSION, audit, schema_version, transaction, verify_audit
from .secrets_store import KEYRING_FORMAT, MAX_KEYS, SecretError, key_id, key_path, read_keys

LOCATIONS = (('datasources','id','secure_json'),('user_mfa','user_id','secret_json'))


def _valid_payload(payload,table,identity):
    data = json.loads(payload)
    if not isinstance(data,dict):
        raise ValueError('Invalid credential record')
    if table=='user_mfa':
        import re
        if set(data)!={'type','user_id','secret'} or data['type']!='mfa-totp-v1' or data['user_id']!=identity or not isinstance(data['secret'],str) or not re.fullmatch('[A-Z2-7]{32}',data['secret']):
            raise ValueError('Invalid bound factor')


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
            changed = {}
            for table,identity,column in LOCATIONS:
                changed[table] = 0
                for row in db.execute(f"SELECT {identity},{column} FROM {table} WHERE {column}<>''").fetchall():
                    token = row[column].encode('ascii')
                    try:
                        _valid_payload(primary.decrypt(token),table,row[identity])
                        continue
                    except InvalidToken:
                        pass
                    rotated = cipher.rotate(token)
                    _valid_payload(primary.decrypt(rotated),table,row[identity])
                    db.execute(f'UPDATE {table} SET {column}=? WHERE {identity}=?',(rotated.decode('ascii'),row[identity]))
                    changed[table] += 1
            if sum(changed.values()):
                audit(db,'os-admin','secrets.rekeyed','keyring',key_id(keys[0]),{'sources':changed['datasources'],'factors':changed['user_mfa'],'retained_key_ids':[key_id(k) for k in keys[1:]]})
        return {'primary_id':key_id(keys[0]),'sources_rekeyed':changed['datasources'],'mfa_secrets_rekeyed':changed['user_mfa']}
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
            for table,identity,column in LOCATIONS:
                for row in db.execute(f"SELECT {identity},{column} FROM {table} WHERE {column}<>''"):
                    _valid_payload(primary.decrypt(row[column].encode('ascii')),table,row[identity])
    except SecretError:
        raise
    except Exception:
        raise SecretError('Old keys still required or database verification failed; no retirement file created') from None
    return _write_new(settings,output,[keys[0]])
