"""Grafana-compatible relative time math (``now-6h``, ``now/d``, ``now-1M/M``).

Rounding (``/d``) is calendar aware and evaluated in the requested IANA time
zone so that "today" in Europe/Istanbul is not "today" in UTC. ``to`` values
round *up* to the end of the unit, exactly like Grafana's time picker.
"""

import math
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .domain import DomainError

UNIT_SECONDS = {"ms": 0.001, "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800, "M": 2592000, "y": 31536000}
_DURATION = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*(ms|s|m|h|d|w|M|y)\s*$")
_MATH = re.compile(r"([+-])(\d+)(ms|s|m|h|d|w|M|y)|/(s|m|h|d|w|M|y)")
NICE_INTERVALS = (
    0.01,
    0.02,
    0.05,
    0.1,
    0.2,
    0.5,
    1,
    2,
    5,
    10,
    15,
    20,
    30,
    60,
    120,
    300,
    600,
    900,
    1200,
    1800,
    3600,
    7200,
    10800,
    21600,
    43200,
    86400,
    604800,
    2592000,
    31536000,
)
MAX_RANGE_DAYS = 3660


class TimeRangeError(DomainError):
    pass


def zone(name: str | None):
    if not name or name in ("utc", "UTC", "browser"):
        return timezone.utc
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise TimeRangeError(f"Unknown time zone: {name}") from exc


def parse_duration(text, *, allow_zero=False) -> float:
    """Seconds for ``5m``/``1h``/``30s``; raises on garbage."""
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        value = float(text)
    else:
        match = _DURATION.match(str(text or ""))
        if not match:
            raise TimeRangeError(f"Invalid duration: {text!r}")
        value = float(match.group(1)) * UNIT_SECONDS[match.group(2)]
    if value < 0 or (value == 0 and not allow_zero) or not math.isfinite(value):
        raise TimeRangeError(f"Duration must be positive: {text!r}")
    return value


def format_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{max(1, round(seconds * 1000))}ms"
    for unit in ("y", "w", "d", "h", "m"):
        size = UNIT_SECONDS[unit]
        if seconds >= size and seconds % size == 0:
            return f"{int(seconds // size)}{unit}"
    return f"{int(round(seconds))}s"


def _round(dt: datetime, unit: str, up: bool) -> datetime:
    if unit == "s":
        start = dt.replace(microsecond=0)
        nxt = start + timedelta(seconds=1)
    elif unit == "m":
        start = dt.replace(second=0, microsecond=0)
        nxt = start + timedelta(minutes=1)
    elif unit == "h":
        start = dt.replace(minute=0, second=0, microsecond=0)
        nxt = start + timedelta(hours=1)
    elif unit == "d":
        start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        nxt = _shift_days(start, 1)
    elif unit == "w":
        day = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        start = _shift_days(day, -day.weekday())
        nxt = _shift_days(start, 7)
    elif unit == "M":
        start = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        nxt = _add_months(start, 1)
    elif unit == "y":
        start = dt.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        nxt = start.replace(year=start.year + 1)
    else:  # pragma: no cover - guarded by regex
        raise TimeRangeError("Invalid rounding unit")
    if not up:
        return start
    return nxt - timedelta(milliseconds=1)


def _shift_days(local: datetime, days: int) -> datetime:
    """Shift on the local calendar (DST-safe) keeping wall-clock time."""
    naive = local.replace(tzinfo=None) + timedelta(days=days)
    return naive.replace(tzinfo=local.tzinfo)


def _add_months(local: datetime, months: int) -> datetime:
    month_index = local.year * 12 + (local.month - 1) + months
    year, month = divmod(month_index, 12)
    month += 1
    days_in_month = [31, 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return local.replace(year=year, month=month, day=min(local.day, days_in_month))


def _apply(local: datetime, sign: str, amount: int, unit: str) -> datetime:
    amount = amount if sign == "+" else -amount
    if unit == "M":
        return _add_months(local, amount)
    if unit == "y":
        return _add_months(local, amount * 12)
    if unit in ("d", "w"):
        return _shift_days(local, amount * (7 if unit == "w" else 1))
    # Sub-day math is absolute elapsed time, not wall-clock time (DST safe).
    shifted = local.astimezone(timezone.utc) + timedelta(seconds=amount * UNIT_SECONDS[unit])
    return shifted.astimezone(local.tzinfo)


def parse(text, *, round_up=False, now: datetime | None = None, tz: str | None = "UTC") -> datetime:
    """Parse a Grafana time expression or absolute value into an aware UTC datetime."""
    if text is None or text == "":
        raise TimeRangeError("Empty time value")
    tzinfo = zone(tz)
    try:
        if isinstance(text, (int, float)) and not isinstance(text, bool):
            return datetime.fromtimestamp(float(text) / 1000, timezone.utc)
        value = str(text).strip()
        if value.isdigit() and len(value) >= 10:
            if len(value) > 16:
                raise TimeRangeError(f"Invalid epoch value: {value[:20]}")
            number = int(value)
            # 10 digits: epoch seconds, 13 digits: epoch milliseconds (Grafana URLs).
            return datetime.fromtimestamp(number / 1000 if len(value) >= 12 else number, timezone.utc)
    except (OverflowError, OSError, ValueError) as exc:
        raise TimeRangeError(f"Invalid time value: {text}") from exc
    if value.startswith("now"):
        base = (now or datetime.now(timezone.utc)).astimezone(tzinfo)
        rest = value[3:]
        position = 0
        for match in _MATH.finditer(rest):
            if match.start() != position:
                raise TimeRangeError(f"Invalid time expression: {value}")
            position = match.end()
            if match.group(4):
                base = _round(base, match.group(4), round_up)
            else:
                base = _apply(base, match.group(1), int(match.group(2)), match.group(3))
        if position != len(rest):
            raise TimeRangeError(f"Invalid time expression: {value}")
        return base.astimezone(timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError) as exc:
        raise TimeRangeError(f"Invalid time value: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tzinfo)
    return parsed.astimezone(timezone.utc)


def resolve_range(frm, to, tz=None, now=None, *, max_days=MAX_RANGE_DAYS):
    now = now or datetime.now(timezone.utc)
    start = parse(frm, now=now, tz=tz)
    end = parse(to, round_up=True, now=now, tz=tz)
    if end <= start:
        raise TimeRangeError("Time range end must be after its start")
    if end - start > timedelta(days=max_days):
        raise TimeRangeError(f"Time range is limited to {max_days} days")
    return start, end


def nice_interval(seconds: float) -> float:
    """Round a raw interval to the closest Grafana-style human interval."""
    if seconds <= NICE_INTERVALS[0]:
        return NICE_INTERVALS[0]
    for low, high in zip(NICE_INTERVALS, NICE_INTERVALS[1:]):
        if low <= seconds <= high:
            return low if seconds - low < high - seconds else high
    return NICE_INTERVALS[-1]


def calculate_interval(start: datetime, end: datetime, max_points: int, min_interval=None) -> float:
    """Query interval (seconds) for a panel, honoring a minimum interval."""
    max_points = max(1, min(int(max_points or 1000), 20000))
    raw = (end - start).total_seconds() / max_points
    interval = nice_interval(raw)
    if min_interval:
        interval = max(interval, parse_duration(min_interval))
    return interval
