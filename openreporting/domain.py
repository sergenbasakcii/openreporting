"""Shared domain helpers: errors, identifiers, canonical hashing, time parsing, recipient checks."""
import hashlib
import json
import re
import uuid
from datetime import datetime, timezone


class DomainError(ValueError):
    pass


def identity():
    return str(uuid.uuid4())


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def parse_utc(value):
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            raise ValueError
        return dt.astimezone(timezone.utc)
    except (TypeError, AttributeError, ValueError):
        raise DomainError("Use ISO-8601 date/time with timezone") from None


def validate_emails(recipients, domains):
    if not isinstance(recipients, list) or len(recipients) > 100:
        raise DomainError("Recipients must be an array (max 100)")
    result = []
    for addr in recipients:
        if not isinstance(addr, str) or len(addr) > 254 or not re.fullmatch(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", addr):
            raise DomainError("Invalid e-mail address")
        if addr.lower().rsplit("@", 1)[1] not in domains:
            raise DomainError("Recipient domain not allowed")
        result.append(addr.lower())
    return sorted(set(result))
