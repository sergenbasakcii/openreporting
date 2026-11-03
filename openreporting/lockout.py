"""Failed-authentication counters and lockout policy (sign-in and in-session step-up).

Kept apart from ``security`` so second-factor code can share it without import cycles.
"""

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from .db import audit, utcnow
from . import messages

# Failure counters (login_failures.username holds the counter key):
#  - username + client: 5 attempts per 15 minutes. An attacker can only lock out their own address.
#  - username alone: 50 attempts, slowing distributed guessing without letting one client lock a user out.
#  - username + "step-up": re-authentication inside a session; only the session holder can trip it.
PAIR_LIMIT = 5
USER_LIMIT = 50
LOCK_WINDOW = timedelta(minutes=15)
_SEP = "\x1f"  # unit separator: cannot occur in usernames or addresses


def failure_keys(username, client=None, *, step_up=False):
    if step_up:
        return ((f"{username}{_SEP}step-up", PAIR_LIMIT),)
    return ((f"{username}{_SEP}{client or 'unknown'}", PAIR_LIMIT), (username, USER_LIMIT))


def gate(db, keys):
    for key, limit in keys:
        failures = db.execute("SELECT count,last_at FROM login_failures WHERE username=?", (key,)).fetchone()
        if not failures:
            continue
        if datetime.now(timezone.utc) - datetime.fromisoformat(failures["last_at"]) >= LOCK_WINDOW:
            db.execute("DELETE FROM login_failures WHERE username=?", (key,))
        elif failures["count"] >= limit:
            raise HTTPException(429, messages.TOO_MANY_ATTEMPTS)


def record_failure(db, keys, client=None):
    cutoff = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
    db.execute("DELETE FROM login_failures WHERE last_at < ?", (cutoff,))
    for key, _ in keys:
        db.execute(
            "INSERT INTO login_failures(username,count,last_at) VALUES(?,1,?) ON CONFLICT(username) DO UPDATE SET count=login_failures.count+1,last_at=excluded.last_at",
            (key, utcnow()),
        )
    # Audit failures in aggregate per client: the first one, then every 50th, bounds audit growth.
    source = f"{_SEP}client{_SEP}{client or 'unknown'}"
    db.execute(
        "INSERT INTO login_failures(username,count,last_at) VALUES(?,1,?) ON CONFLICT(username) DO UPDATE SET count=login_failures.count+1,last_at=excluded.last_at",
        (source, utcnow()),
    )
    count = db.execute("SELECT count FROM login_failures WHERE username=?", (source,)).fetchone()[0]
    if count == 1 or count % 50 == 0:
        audit(db, "anonymous", "auth.failed", "login", "redacted", {"failures_from_client": count})


def clear_failures(db, keys):
    for key, _ in keys:
        db.execute("DELETE FROM login_failures WHERE username=?", (key,))
