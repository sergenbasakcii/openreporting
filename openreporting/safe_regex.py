"""User-supplied regular expressions with length caps and a per-match timeout.

Dashboard filters, variable regexes, aliases and transformations accept regexes
from editors and URL-controlled variable values. Python's ``re`` holds the GIL
during catastrophic backtracking, so one pattern could freeze a web worker. The
``regex`` module supports a hard ``timeout`` per operation.
"""

import regex

from .domain import DomainError

MAX_PATTERN = 500
MAX_SUBJECT = 20_000
# Wall-clock budget per match. Concurrent queries share the GIL, so a trivial match can be descheduled
# for tens of milliseconds; the budget leaves room for that and a timeout is retried once. A
# catastrophic pattern still fails (twice the budget at most) and never freezes other requests,
# because matching runs with ``concurrent=True`` (the GIL is released while matching).
TIMEOUT_S = 0.25
_FLAGS = {"i": regex.IGNORECASE, "m": regex.MULTILINE, "s": regex.DOTALL, "x": regex.VERBOSE}


class RegexError(DomainError):
    pass


class SafeRegex:
    __slots__ = ("pattern",)

    def __init__(self, compiled):
        self.pattern = compiled

    @property
    def groups(self):
        return self.pattern.groups

    def _run(self, method, *args):
        for attempt in (1, 2):
            try:
                return method(*args, timeout=TIMEOUT_S, concurrent=True)
            except TimeoutError as exc:
                if attempt == 2:
                    raise RegexError("Düzenli ifade çok karmaşık (zaman aşımı); sadeleştirin") from exc
        return None  # pragma: no cover - loop always returns or raises

    def search(self, text):
        return self._run(self.pattern.search, str(text)[:MAX_SUBJECT])

    def match(self, text):
        return self._run(self.pattern.match, str(text)[:MAX_SUBJECT])

    def fullmatch(self, text):
        return self._run(self.pattern.fullmatch, str(text)[:MAX_SUBJECT])

    def sub(self, replacement, text):
        try:
            return self._run(self.pattern.sub, replacement, str(text)[:MAX_SUBJECT])
        except (regex.error, IndexError) as exc:
            raise RegexError(f"Geçersiz değiştirme ifadesi: {exc}") from exc


def compile_user(pattern, flags=""):
    """Compile ``pattern`` (plain text, no slashes) with optional flag letters."""
    text = str(pattern if pattern is not None else "")
    if len(text) > MAX_PATTERN:
        raise RegexError(f"Düzenli ifade en fazla {MAX_PATTERN} karakter olabilir")
    value = regex.VERSION0
    for char in flags or "":
        if char not in _FLAGS:
            raise RegexError(f"Bilinmeyen regex bayrağı: {char}")
        value |= _FLAGS[char]
    try:
        return SafeRegex(regex.compile(text, value))
    except (regex.error, OverflowError, RecursionError) as exc:
        raise RegexError(f"Geçersiz düzenli ifade: {exc}") from exc


def compile_slashed(text, *, default_flags=""):
    """Accept Grafana style ``/pattern/flags`` or a bare pattern."""
    value = str(text or "")
    if len(value) >= 2 and value.startswith("/"):
        end = value.rfind("/")
        if end > 0 and set(value[end + 1 :]) <= set("imsx"):
            return compile_user(value[1:end], value[end + 1 :])
    return compile_user(value, default_flags)


def is_slashed(text):
    value = str(text or "")
    if len(value) >= 2 and value.startswith("/"):
        end = value.rfind("/")
        return end > 0 and set(value[end + 1 :]) <= set("imsx")
    return False
