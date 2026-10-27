"""Single-purpose worker: no web server and no in-process APScheduler."""
import logging
import os
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .db import connect, transaction, utcnow
from .domain import identity, parse_utc
from .portable import exclusive_local_lock

log = logging.getLogger(__name__)


def schedule_next(cadence, tz_name, hour, minute, reference=None):
    """Next local calendar trigger strictly after reference, persisted as UTC."""
    tz = ZoneInfo(tz_name)
    ref = (reference or datetime.now(timezone.utc)).astimezone(tz)
    current = ref.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if cadence == "daily":
        day = ref.date() if current > ref else ref.date() + timedelta(days=1)
    elif cadence == "weekly":
        days = (-ref.weekday()) % 7
        day = ref.date() + timedelta(days=days)
        if day == ref.date() and current <= ref:
            day += timedelta(days=7)
    elif cadence == "monthly":
        day = ref.date().replace(day=1)
        if day < ref.date() or current <= ref:
            y = day.year + (day.month == 12)
            m = 1 if day.month == 12 else day.month + 1
            day = day.replace(year=y, month=m)
    elif cadence == "yearly":
        day = ref.date().replace(month=1, day=1)
        if day < ref.date() or current <= ref:
            day = day.replace(year=day.year + 1)
    else:
        raise ValueError("Invalid cadence")
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz).astimezone(timezone.utc).isoformat(timespec="seconds")


def completed_period(cadence, tz_name, due):
    """Complete calendar interval before the scheduled local calendar boundary."""
    tz = ZoneInfo(tz_name)
    local = parse_utc(due).astimezone(tz)
    boundary = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if cadence == "daily":
        start = boundary - timedelta(days=1)
    elif cadence == "weekly":
        boundary -= timedelta(days=boundary.weekday())
        start = boundary - timedelta(days=7)
    elif cadence == "monthly":
        boundary = boundary.replace(day=1)
        start = (boundary - timedelta(days=1)).replace(day=1)
    elif cadence == "yearly":
        boundary = boundary.replace(month=1, day=1)
        start = boundary.replace(year=boundary.year - 1)
    else:
        raise ValueError("Invalid cadence")
    return start.astimezone(timezone.utc).isoformat(), boundary.astimezone(timezone.utc).isoformat()


def _atomic_write(target: Path, data: bytes):
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".pending-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextmanager
def exclusive_worker(settings):
    """One scheduler/SMTP owner per local NTFS/ext4 application data volume."""
    with exclusive_local_lock(settings.data_dir / "worker.lock"):
        yield


def update_worker_heartbeat(settings, worker_id, started_at, error=""):
    with connect(settings) as db, transaction(db):
        db.execute("""INSERT INTO worker_runtime(singleton_id,worker_id,started_at,last_tick,tick_count,last_error)
              VALUES(1,?,?,?,1,?) ON CONFLICT(singleton_id) DO UPDATE SET
              worker_id=excluded.worker_id,started_at=excluded.started_at,last_tick=excluded.last_tick,
              tick_count=CASE WHEN worker_id=excluded.worker_id THEN tick_count+1 ELSE 1 END,
              last_error=excluded.last_error""",
              (worker_id,started_at,utcnow(),error[:400]))


def run_forever(settings, once=False, interval=10):
    from .db import init_db
    from .reporting import service as dash_reports
    init_db(settings)
    with exclusive_worker(settings):
        # Exclusive ownership means unfinished jobs predate this worker. An
        # uncertain SMTP exchange must NEVER be silently resumed or replayed.
        dash_reports.mark_interrupted(settings, force=True)
        return _run_locked(settings, once, interval)


class _Heartbeat:
    """Keeps worker_runtime fresh while a long PDF/Excel render is in progress."""

    def __init__(self, settings, worker_id, started_at, period=30):
        import threading
        self.settings, self.worker_id, self.started_at, self.period = settings, worker_id, started_at, period
        self.error = ""
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="openreporting-heartbeat", daemon=True)

    def _loop(self):
        while not self._stop.wait(self.period):
            try:
                update_worker_heartbeat(self.settings, self.worker_id, self.started_at, self.error)
            except Exception:  # noqa: BLE001 - a missed heartbeat is reported by its age
                log.warning("Heartbeat update failed", exc_info=True)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=5)


def _run_locked(settings, once, interval):
    from .reporting import service as dash_reports
    worker_id = identity()
    started_at = utcnow()
    last_retention = 0.0
    with _Heartbeat(settings, worker_id, started_at) as heartbeat:
        while True:
            ran = []
            errors = []

            def phase(name, func, *args):
                # Each phase is isolated: a failing schedule never blocks report runs.
                try:
                    return func(*args)
                except Exception as exc:  # noqa: BLE001 - recorded in the heartbeat row
                    log.exception("Worker phase %s failed", name)
                    errors.append(f"{name}: {exc}"[:200])
                    if once:
                        raise
                    return None

            update_worker_heartbeat(settings, worker_id, started_at, heartbeat.error)
            phase("mark_interrupted", dash_reports.mark_interrupted, settings)
            phase("tick_schedules", dash_reports.tick_schedules, settings)
            run_id = phase("claim", dash_reports.claim, settings)
            if run_id:
                ran.append(run_id)
                phase("execute", dash_reports.execute, settings, run_id)
            if time.monotonic() - last_retention > 3600:
                last_retention = time.monotonic()
                phase("retention", dash_reports.apply_retention, settings)
            heartbeat.error = "; ".join(errors)[:400]
            if once:
                return
            time.sleep(0.2 if ran else interval)
