"""Small local probes; never query external sources or send mail for readiness."""
from .db import CURRENT_VERSION, schema_version


def database_ready(db):
    if schema_version(db) != CURRENT_VERSION:
        return False
    # SELECT 1 alone also succeeds for an accidentally replaced/empty SQLite file.
    db.execute("SELECT id FROM users LIMIT 1").fetchone()
    db.execute("SELECT token_hash FROM sessions LIMIT 1").fetchone()
    return True
