"""Small local probes; never query external sources or send mail for readiness."""
from .db import CURRENT_VERSION, schema_version


def database_ready(db):
    if schema_version(db) != CURRENT_VERSION:
        return False
    # SELECT 1 alone also succeeds for an accidentally replaced/empty SQLite file.
    db.execute("SELECT id FROM users LIMIT 1").fetchone()
    db.execute("SELECT token_hash FROM sessions LIMIT 1").fetchone()
    db.execute('SELECT user_id FROM user_mfa LIMIT 1').fetchone()
    db.execute('SELECT token_hash FROM mfa_sessions LIMIT 1').fetchone()
    db.execute('SELECT folder_id FROM folder_policy LIMIT 1').fetchone()
    db.execute('SELECT folder_id FROM folder_user_grants LIMIT 1').fetchone()
    return True
