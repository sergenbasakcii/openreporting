"""Verify a SQLite backup in disposable storage, without restoring over live data."""

import hashlib
import json
from contextlib import closing
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import tarfile
import tempfile

from .config import Settings
from .db import CURRENT_VERSION, schema_version, verify_audit
from .healthchecks import database_ready
from .reporting import logos
from .secrets_store import decrypt
from PIL import Image


class BackupVerificationError(Exception):
    pass


def _hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _regular(path):
    if path.is_symlink() or not path.is_file():
        raise BackupVerificationError("Backup contains a missing or non-regular file")
    return path


def _checksums(source):
    manifest = _regular(source / "SHA256SUMS")
    if manifest.stat().st_size > 8192:
        raise BackupVerificationError("Backup checksum manifest is too large")
    allowed = {"state.sqlite3", "archive.tar.gz", "openreporting.env", "secret.key"}
    records = {}
    for line in manifest.read_text(encoding="ascii").splitlines():
        match = re.fullmatch(r"([a-f0-9]{64}) [ *](?:\./)?([A-Za-z0-9._-]+)", line)
        if not match or match[2] not in allowed or match[2] in records:
            raise BackupVerificationError("Invalid backup checksum manifest")
        records[match[2]] = match[1]
    if not {"state.sqlite3", "archive.tar.gz", "openreporting.env"} <= records.keys():
        raise BackupVerificationError("Backup is missing required components")
    for name, expected in records.items():
        if _hash(_regular(source / name)) != expected:
            raise BackupVerificationError("Backup checksum mismatch")
    return records


def _unpack(source, target, budget):
    total, count = 0, 0
    with tarfile.open(source, "r:gz") as archive:
        for member in archive:
            parts = PurePosixPath(member.name).parts
            reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
            count += 1
            if (
                not parts
                or parts[0] not in {"archive", "logos"}
                or ".." in parts
                or "\\" in member.name
                or ":" in member.name
                or len(member.name) > 4096
                or any(p.endswith((" ", ".")) or p.split(".")[0].upper() in reserved for p in parts)
                or not (member.isfile() or member.isdir())
                or member.size < 0
                or count > 100_000
            ):
                raise BackupVerificationError("Unsafe or unsupported backup archive member")
            total += member.size
            if total > budget:
                raise BackupVerificationError("Backup exceeds unpacked size budget")
            destination = target.joinpath(*parts)
            if not destination.resolve().is_relative_to(target.resolve()):
                raise BackupVerificationError("Backup archive path escapes verification directory")
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True, mode=0o700)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                # Never overwrite a previous member, follow links or restore owner/mode bits.
                with archive.extractfile(member) as reader, destination.open("xb") as writer:
                    shutil.copyfileobj(reader, writer, 1024 * 1024)
                destination.chmod(0o600)


def _archive_file(directory, name):
    if not isinstance(name, str) or name in {"", ".", ".."} or "/" in name or "\\" in name or ":" in name:
        raise BackupVerificationError("Invalid report archive filename")
    return _regular(directory / name)


def _verify_copy(target, key, require_logos):
    settings = Settings(
        data_dir=target,
        secure_cookie=False,
        session_hours=1,
        max_rows=200000,
        query_timeout_ms=30000,
        mail_enabled=False,
        smtp_host="",
        smtp_port=587,
        smtp_starttls=True,
        smtp_user="",
        smtp_password="",
        smtp_from="",
        recipient_domains=(),
        secret_key_file=str(target / "secret.key"),
        provision_testdata=False,
    )
    with closing(sqlite3.connect((target / "state.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchone():
            raise BackupVerificationError("Backup database integrity check failed")
        if schema_version(db) != CURRENT_VERSION:
            raise BackupVerificationError("Use the application version matching the backup schema")
        if not database_ready(db):
            raise BackupVerificationError("Backup application tables are incomplete")
        if not verify_audit(db)[0]:
            raise BackupVerificationError("Backup audit chain is invalid")
        anchors = {
            row["object_id"]: json.loads(row["details"]).get("manifest_sha256")
            for row in db.execute(
                "SELECT object_id,details FROM audit WHERE object_type='dash_report_run' AND action IN ('report_run.completed','report_run.partial') ORDER BY id"
            )
        }
        reports, artifacts = 0, 0
        for row in db.execute("SELECT id,files_json FROM dash_report_runs WHERE status IN ('completed','partial')"):
            files = json.loads(row["files_json"])
            manifest_file = _archive_file(settings.archive_dir, files.get("manifest"))
            if _hash(manifest_file) != anchors.get(row["id"]):
                raise BackupVerificationError("Restored report manifest does not match its audit anchor")
            manifest = json.loads(manifest_file.read_text(encoding="utf8"))
            for kind, name in files.items():
                if kind == "manifest":
                    continue
                if kind not in {"pdf", "xlsx", "csv"} or _hash(_archive_file(settings.archive_dir, name)) != manifest["sha256"].get(kind):
                    raise BackupVerificationError("Restored report artifact hash mismatch")
                artifacts += 1
            reports += 1
        for row in db.execute("SELECT config_json FROM dash_reports"):
            logo_id = json.loads(row[0]).get("logo_id")
            if logo_id:
                logos.path(settings, logo_id)
        secrets = 0
        for row in db.execute("SELECT secure_json FROM datasources WHERE secure_json<>''"):
            if key is None:
                raise BackupVerificationError("Encryption key is required to verify stored credentials")
            decrypt(settings, row[0])
            secrets += 1
        factors = 0
        from .key_rotation import _valid_payload

        for row in db.execute("SELECT user_id,secret_json FROM user_mfa WHERE secret_json<>''"):
            if key is None:
                raise BackupVerificationError("Encryption key is required to verify stored factors")
            payload = decrypt(settings, row["secret_json"])
            _valid_payload(json.dumps(payload), "user_mfa", row["user_id"])
            factors += 1
        settings_secrets = 0
        for row in db.execute("SELECT scope,secure_json FROM app_settings WHERE secure_json<>''"):
            if key is None:
                raise BackupVerificationError("Encryption key is required to verify stored settings")
            _valid_payload(json.dumps(decrypt(settings, row["secure_json"])), "app_settings", row["scope"])
            settings_secrets += 1
    logo_files = list((target / "logos").glob("*.png"))
    for image_file in logo_files:
        if not re.fullmatch(r"[a-f0-9]{64}", image_file.stem) or _hash(image_file) != image_file.stem:
            raise BackupVerificationError("Restored logo content hash mismatch")
        with Image.open(image_file) as image:
            if image.format != "PNG" or max(image.size) > logos.MAX_EDGE:
                raise BackupVerificationError("Invalid restored logo image")
            image.verify()
    logo_count = len(logo_files)
    if require_logos and not logo_count:
        raise BackupVerificationError("Expected report logos are missing from backup")
    return {
        "ok": True,
        "schema_version": CURRENT_VERSION,
        "reports": reports,
        "artifacts": artifacts,
        "logos": logo_count,
        "encrypted_sources": secrets,
        "encrypted_factors": factors,
        "encrypted_settings": settings_secrets,
    }


def verify_backup(directory, *, key_file=None, max_unpacked_bytes=2 * 1024**3, require_logos=False):
    """Read backup files, verify hashes, restore only to a fresh temporary directory."""
    try:
        source = Path(directory).resolve()
        records = _checksums(source)
        source_db = source / "state.sqlite3"
        if not 1 <= max_unpacked_bytes <= 1024**4 or source_db.stat().st_size > max_unpacked_bytes:
            raise BackupVerificationError("Backup exceeds verification size budget")
        key = Path(key_file).resolve() if key_file else source / "secret.key" if "secret.key" in records else None
        with tempfile.TemporaryDirectory(prefix="openreporting-restore-check-") as work:
            target = Path(work).resolve()
            assert target.is_relative_to(Path(tempfile.gettempdir()).resolve())
            shutil.copyfile(source_db, target / "state.sqlite3")
            (target / "state.sqlite3").chmod(0o600)
            _unpack(source / "archive.tar.gz", target, max_unpacked_bytes - source_db.stat().st_size)
            if key is not None:
                shutil.copyfile(_regular(key), target / "secret.key")
                (target / "secret.key").chmod(0o600)
            return _verify_copy(target, key, require_logos)
    except BackupVerificationError:
        raise
    except Exception:
        raise BackupVerificationError("Backup verification failed; check files, schema and encryption key") from None
