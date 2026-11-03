"""Operating-system boundaries: PDF fonts and exclusive local worker ownership.

This module never controls a remote monitoring host.  It only owns a byte-range
lock on the application's own data directory and resolves locally installed fonts.
"""

import os
from contextlib import contextmanager
from pathlib import Path


def unicode_bold_font_path() -> str:
    """Bold companion font; falls back to the regular face when none is installed."""
    explicit = os.environ.get("OPENREPORTING_PDF_BOLD_FONT_FILE", "").strip()
    if explicit and Path(explicit).is_file():
        return explicit
    candidates = [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    ]
    if os.name == "nt":
        win_dir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        candidates.extend(win_dir / "Fonts" / name for name in ("arialbd.ttf", "segoeuib.ttf", "tahomabd.ttf"))
    font = next((path for path in candidates if path.is_file()), None)
    return str(font) if font else unicode_font_path()


def unicode_font_path() -> str:
    """Resolve an embeddable TrueType font; fail closed if none is available."""
    explicit = os.environ.get("OPENREPORTING_PDF_FONT_FILE", "").strip()
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file() or path.suffix.lower() != ".ttf":
            raise RuntimeError("OPENREPORTING_PDF_FONT_FILE must point to an existing .ttf file")
        return str(path)

    candidates = [
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf"),
        Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
    ]
    if os.name == "nt":
        win_dir = Path(os.environ.get("WINDIR", r"C:\Windows"))
        candidates.extend(win_dir / "Fonts" / name for name in ("arial.ttf", "segoeui.ttf", "tahoma.ttf", "calibri.ttf"))
    font = next((path for path in candidates if path.is_file()), None)
    if font is None:
        raise RuntimeError("Unicode PDF font unavailable. Set OPENREPORTING_PDF_FONT_FILE to a valid TrueType font.")
    return str(font)


@contextmanager
def exclusive_local_lock(path: Path):
    """Acquire a non-blocking, process-scoped file lock on NT or POSIX.

    Do not delete the lock file to 'repair' a running process: the OS releases
    the lock automatically when its owning process exits.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags, 0o600)
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt

            # Windows msvcrt.locking() locks bytes, not a whole inode.  Byte 0
            # is reserved for a single owner on all Windows worker processes.
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("Another OpenReporting reporting worker is already active") from exc
        else:
            import fcntl

            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (OSError, BlockingIOError) as exc:
                raise RuntimeError("Another OpenReporting reporting worker is already active") from exc
        acquired = True
        yield
    finally:
        try:
            if acquired:
                if os.name == "nt":
                    import msvcrt

                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
