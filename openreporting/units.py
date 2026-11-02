"""Grafana-style value formatting shared by PDF, Excel and CSV renderers.

The browser has an equivalent implementation in ``static/app/units.js``; keep
unit identifiers in sync so that a dashboard and its PDF read the same.
"""
import math
from datetime import datetime, timezone

SI_PREFIXES = ["", "k", "M", "G", "T", "P", "E"]
IEC_PREFIXES = ["", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei"]

# Zabbix unit strings mapped to Grafana unit identifiers ("auto" unit mode).
ZABBIX_UNITS = {
    "B": "bytes", "bps": "bps", "Bps": "Bps", "%": "percent", "s": "s",
    "uptime": "dtdurations", "unixtime": "dateTimeAsIso", "rpm": "rpm",
    "Hz": "hertz", "W": "watt", "V": "volt", "A": "amp", "C": "celsius",
    "°C": "celsius", "dBm": "dBm", "ms": "ms", "pps": "pps", "iops": "iops",
}

UNIT_CATALOG = {
    "Genel": [("none", "Yok"), ("short", "Kısa (k, Mn, Mr)"), ("percent", "Yüzde (0-100)"),
              ("percentunit", "Yüzde (0.0-1.0)"), ("humidity", "Nem (%H)"), ("dB", "Desibel"),
              ("dBm", "dBm")],
    "Veri": [("bytes", "bayt (IEC)"), ("decbytes", "bayt (SI)"), ("bits", "bit (IEC)"),
             ("decbits", "bit (SI)"), ("kbytes", "kibibayt"), ("mbytes", "mebibayt"),
             ("gbytes", "gibibayt")],
    "Veri hızı": [("bps", "bit/sn (SI)"), ("binbps", "bit/sn (IEC)"), ("Bps", "bayt/sn (SI)"),
                  ("binBps", "bayt/sn (IEC)"), ("pps", "paket/sn"), ("iops", "G/Ç işlem/sn"),
                  ("ops", "işlem/sn"), ("reqps", "istek/sn")],
    "Zaman": [("ns", "nanosaniye"), ("µs", "mikrosaniye"), ("ms", "milisaniye"), ("s", "saniye"),
              ("m", "dakika"), ("h", "saat"), ("d", "gün"), ("dtdurations", "süre (gün/saat)"),
              ("dateTimeAsIso", "Tarih/saat (ISO)"), ("hertz", "hertz")],
    "Fiziksel": [("celsius", "Santigrat (°C)"), ("fahrenheit", "Fahrenhayt (°F)"), ("watt", "Watt"),
                 ("kwatt", "Kilowatt"), ("volt", "Volt"), ("amp", "Amper"), ("rpm", "RPM")],
}


KNOWN_UNITS = frozenset(unit for entries in UNIT_CATALOG.values() for unit, _ in entries)


# Raw Zabbix units that collide with display time-unit ids (metres vs minutes etc.).
AMBIGUOUS_SOURCE_UNITS = {"m", "h", "d"}

def resolve_unit(unit: str | None, source_unit: str | None = None) -> str:
    """Panel unit wins; otherwise translate the Zabbix item unit."""
    if unit and unit not in ("auto",):
        return unit
    if source_unit:
        mapped = ZABBIX_UNITS.get(source_unit)
        if mapped:
            return mapped
        if (source_unit in KNOWN_UNITS and source_unit not in AMBIGUOUS_SOURCE_UNITS) or source_unit.startswith(("suffix:", "prefix:")):
            return source_unit
        return "suffix: " + source_unit
    return "short"


def _decimals(value: float, decimals) -> int:
    if decimals is not None:
        return max(0, min(int(decimals), 10))
    magnitude = abs(value)
    if magnitude == 0 or magnitude >= 100:
        return 0
    if magnitude >= 10:
        return 1
    if magnitude >= 1:
        return 2
    return 3


def _num(value: float, decimals) -> str:
    text = f"{value:.{_decimals(value, decimals)}f}"
    if decimals is None and "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _scaled(value, base, prefixes, suffix, decimals, space=True):
    index = 0
    magnitude = abs(value)
    while magnitude >= base and index < len(prefixes) - 1:
        magnitude /= base
        value /= base
        index += 1
    sep = " " if space else ""
    return f"{_num(value, decimals)}{sep}{prefixes[index]}{suffix}".rstrip()


def _short(value, decimals):
    suffixes = ["", " K", " Mn", " Mr", " Tn"]  # bin, milyon, milyar, trilyon
    index = 0
    while abs(value) >= 1000 and index < len(suffixes) - 1:
        value /= 1000
        index += 1
    return f"{_num(value, decimals)}{suffixes[index]}"


def _duration(seconds, decimals):
    sign = "-" if seconds < 0 else ""
    seconds = abs(seconds)
    if seconds < 1e-6:
        return f"{sign}{_num(seconds * 1e9, decimals)} ns"
    if seconds < 1e-3:
        return f"{sign}{_num(seconds * 1e6, decimals)} µs"
    if seconds < 1:
        return f"{sign}{_num(seconds * 1e3, decimals)} ms"
    if seconds < 60:
        return f"{sign}{_num(seconds, decimals)} s"
    if seconds < 3600:
        return f"{sign}{_num(seconds / 60, decimals)} dk"
    if seconds < 86400:
        return f"{sign}{_num(seconds / 3600, decimals)} sa"
    if seconds < 604800 * 52:
        return f"{sign}{_num(seconds / 86400, decimals)} gün"
    return f"{sign}{_num(seconds / 31536000, decimals)} yıl"


def _dtdurations(seconds):
    seconds = int(abs(seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days} gün")
    if hours:
        parts.append(f"{hours} sa")
    if minutes and not days:
        parts.append(f"{minutes} dk")
    if not parts:
        parts.append(f"{secs} sn")
    return " ".join(parts[:2])


def format_value(value, unit: str | None = "short", decimals=None, no_value: str = "Veri yok") -> str:
    if value is None:
        return no_value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return no_value
    unit = unit or "short"
    if unit.startswith("suffix:"):
        return f"{_num(number, decimals)} {unit[7:].strip()}".rstrip()
    if unit.startswith("prefix:"):
        return f"{unit[7:].strip()}{_num(number, decimals)}"
    if unit == "none":
        return _num(number, decimals)
    if unit == "short":
        return _short(number, decimals)
    if unit == "percent":
        return f"{_num(number, decimals)}%"
    if unit == "percentunit":
        return f"{_num(number * 100, decimals)}%"
    if unit == "humidity":
        return f"{_num(number, decimals)}%H"
    if unit in ("dB", "dBm"):
        return f"{_num(number, decimals)} {unit}"
    if unit == "bytes":
        return _scaled(number, 1024, IEC_PREFIXES, "B", decimals)
    if unit == "kbytes":
        return _scaled(number * 1024, 1024, IEC_PREFIXES, "B", decimals)
    if unit == "mbytes":
        return _scaled(number * 1024 ** 2, 1024, IEC_PREFIXES, "B", decimals)
    if unit == "gbytes":
        return _scaled(number * 1024 ** 3, 1024, IEC_PREFIXES, "B", decimals)
    if unit == "decbytes":
        return _scaled(number, 1000, SI_PREFIXES, "B", decimals)
    if unit == "bits":
        return _scaled(number, 1024, IEC_PREFIXES, "b", decimals)
    if unit == "decbits":
        return _scaled(number, 1000, SI_PREFIXES, "b", decimals)
    if unit == "bps":
        return _scaled(number, 1000, SI_PREFIXES, "bps", decimals)
    if unit == "binbps":
        return _scaled(number, 1024, IEC_PREFIXES, "bps", decimals)
    if unit == "Bps":
        return _scaled(number, 1000, SI_PREFIXES, "B/s", decimals)
    if unit == "binBps":
        return _scaled(number, 1024, IEC_PREFIXES, "B/s", decimals)
    if unit in ("pps", "iops", "ops", "reqps", "rpm"):
        label = {"pps": "p/s", "iops": "io/s", "ops": "ops/s", "reqps": "req/s", "rpm": "rpm"}[unit]
        return f"{_short(number, decimals)} {label}"
    if unit == "ns":
        return _duration(number / 1e9, decimals)
    if unit == "µs":
        return _duration(number / 1e6, decimals)
    if unit == "ms":
        return _duration(number / 1e3, decimals)
    if unit == "s":
        return _duration(number, decimals)
    if unit == "m":
        return _duration(number * 60, decimals)
    if unit == "h":
        return _duration(number * 3600, decimals)
    if unit == "d":
        return _duration(number * 86400, decimals)
    if unit == "dtdurations":
        return _dtdurations(number)
    if unit == "dateTimeAsIso":
        try:
            return datetime.fromtimestamp(number, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        except (OverflowError, OSError, ValueError):
            return str(number)
    if unit == "hertz":
        return _scaled(number, 1000, SI_PREFIXES, "Hz", decimals)
    if unit == "celsius":
        return f"{_num(number, decimals)}°C"
    if unit == "fahrenheit":
        return f"{_num(number, decimals)}°F"
    if unit == "watt":
        return _scaled(number, 1000, SI_PREFIXES, "W", decimals)
    if unit == "kwatt":
        return _scaled(number * 1000, 1000, SI_PREFIXES, "W", decimals)
    if unit == "volt":
        return _scaled(number, 1000, SI_PREFIXES, "V", decimals)
    if unit == "amp":
        return _scaled(number, 1000, SI_PREFIXES, "A", decimals)
    return _short(number, decimals)
