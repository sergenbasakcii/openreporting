"""Read-only operational preflight, never an initializer or production approval."""
import re

from .db import CURRENT_VERSION, SCHEMA, schema_version, verify_audit
from .postgres_store import connect

TABLES = tuple(re.findall(r'CREATE TABLE IF NOT EXISTS ([a-z_]+)\(', SCHEMA)) + (
    'external_identities', 'user_mfa', 'mfa_sessions', 'folder_policy', 'folder_user_grants')


def _transport(db):
    # Local sockets have an OS permission boundary; TCP must verify CA AND host.
    if db.raw.info.host.startswith('/'):
        return 'local_socket'
    if db.raw.pgconn.ssl_in_use and db.raw.info.get_parameters().get('sslmode') == 'verify-full':
        return 'verified_tls'
    return 'unverified_tcp'


def _inspect(db):
    checks = {
        'read_only_snapshot': db.execute('SHOW transaction_read_only').fetchone()[0] == 'on',
        'primary_writable_default': bool(db.execute("""SELECT NOT pg_is_in_recovery()
            AND current_setting('default_transaction_read_only')='off'""").fetchone()[0]),
        'least_privilege_role': bool(db.execute("""SELECT bool_and(NOT rolsuper AND NOT rolcreaterole
            AND NOT rolcreatedb AND NOT rolreplication AND NOT rolbypassrls
            AND rolname NOT IN ('pg_read_all_data','pg_write_all_data','pg_read_server_files',
                'pg_write_server_files','pg_execute_server_program','pg_signal_backend',
                'pg_checkpoint','pg_create_subscription','pg_maintain')) FROM pg_roles
            WHERE rolname IN (current_user,session_user) OR pg_has_role(session_user,oid,'MEMBER')""").fetchone()[0]),
    }
    transport = _transport(db)
    checks['secure_transport'] = transport != 'unverified_tcp'
    checks['schema_current'] = schema_version(db) == CURRENT_VERSION
    readable = True
    writable = True
    for table in TABLES:
        row = db.execute("""SELECT c.relkind IN ('r','p') AS real_table,
            has_table_privilege(current_user,c.oid,'SELECT') AS readable
            FROM pg_class c WHERE c.oid=to_regclass(?)""", (table,)).fetchone()
        readable = readable and bool(row and row['real_table'] and row['readable'])
        privileges = () if table == 'schema_versions' else ('INSERT',) if table == 'audit' else ('INSERT', 'UPDATE', 'DELETE')
        if not row:
            writable = False
            continue
        for privilege in privileges:
            permitted = db.execute('SELECT has_table_privilege(current_user,to_regclass(?),?)', (table, privilege)).fetchone()[0]
            writable = writable and bool(permitted)
    checks['application_tables_readable'] = readable
    if readable:
        writable = writable and bool(db.execute("SELECT has_sequence_privilege(current_user,pg_get_serial_sequence('audit','id'),'USAGE')").fetchone()[0])
        checks['audit_chain'] = verify_audit(db)[0]
        checks['local_recovery_admin'] = bool(db.execute("""SELECT 1 FROM users u WHERE role='admin' AND active=1
            AND NOT EXISTS(SELECT 1 FROM external_identities e WHERE e.user_id=u.id) LIMIT 1""").fetchone())
    else:
        checks['audit_chain'] = False
        checks['local_recovery_admin'] = False
    checks['runtime_data_privileges'] = readable and writable
    return {'ok': all(checks.values()), 'production_ready': False, 'mode': 'read_only_repeatable_read',
            'checks': checks, 'transport': transport}


def check(settings):
    """Return redacted findings; never create directories, keys, tables or sessions."""
    if not settings.database_url:
        return {'ok': False, 'production_ready': False, 'error': 'postgres_required'}
    try:
        with connect(settings.database_url, timeout_ms=settings.query_timeout_ms) as db:
            with db.raw.transaction():
                db.raw.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                return _inspect(db)
    except Exception:  # Driver errors may contain hosts, names, credentials or SQL.
        return {'ok': False, 'production_ready': False, 'error': 'inspection_failed'}
