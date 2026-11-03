"""Plugin discovery: datasource plugins (Python entry points) and panel plugins (browser ES modules).

Only plugins named in ``OPENREPORTING_PLUGINS`` load; a plugin runs with the application's own
privileges, so installing and allow-listing one is an operator decision. Ids always start with
``x-`` so they can never shadow a built-in type. A broken plugin is skipped and reported on the
admin Plugins page; it never stops the application from starting.

Datasource plugin contract (``[project.entry-points."openreporting.datasources"]`` ``x-name = "pkg:Class"``):
a subclass of :class:`openreporting.datasources.base.DataSource` with ``type`` equal to the entry
point name, ``display_name``, ``description``, ``secure_fields`` (list) and optionally a classmethod
``validate_config(url, json_data, settings) -> (url, clean_json_data)``.

Panel plugin contract: ``<plugin dir>/<id>/plugin.json`` = ``{"id", "type": "panel", "name", "version",
"module"}``; the module exports ``register(api)`` and calls ``api.registerPanel(id, definition)``.
"""

import json
import logging
import os
import re
from importlib import metadata
from pathlib import Path

log = logging.getLogger(__name__)

PLUGIN_ID = re.compile(r"^x-[a-z0-9][a-z0-9-]{1,39}$")
ENTRY_POINT_GROUP = "openreporting.datasources"
ASSET_TYPES = {".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png"}
MAX_MANIFEST_BYTES = 16 * 1024

_status = {}  # id -> {"kind", "name", "version", "state": "loaded"|"error"|"disabled", "error"}


def enabled_ids():
    return {item.strip() for item in os.getenv("OPENREPORTING_PLUGINS", "").split(",") if PLUGIN_ID.match(item.strip())}


def plugin_dir(settings):
    configured = os.getenv("OPENREPORTING_PLUGIN_DIR", "").strip()
    return Path(configured) if configured else settings.data_dir / "plugins"


def _record(plugin_id, **values):
    _status[plugin_id] = {"id": plugin_id, **values}


def load_datasource_plugins(entry_points=None):
    """Register allow-listed datasource plugins into the datasource registry (idempotent)."""
    from . import datasources
    from .datasources.base import DataSource

    allowed = enabled_ids()
    found = entry_points if entry_points is not None else metadata.entry_points(group=ENTRY_POINT_GROUP)
    for ep in found:
        if not PLUGIN_ID.match(ep.name):
            log.warning("Ignoring datasource plugin %r: ids must match x-name", ep.name)
            continue
        if ep.name not in allowed:
            _record(ep.name, kind="datasource", name=ep.name, version="", state="disabled", error="")
            continue
        try:
            cls = ep.load()
            if not (isinstance(cls, type) and issubclass(cls, DataSource)) or getattr(cls, "type", None) != ep.name:
                raise TypeError("must be a DataSource subclass whose type equals the entry point name")
            secure = list(getattr(cls, "secure_fields", []) or [])
            if any(not isinstance(field, str) for field in secure):
                raise TypeError("secure_fields must be a list of field names")
        except Exception as exc:  # noqa: BLE001 - a broken plugin must never stop the application
            log.exception("Datasource plugin %s failed to load", ep.name)
            _record(ep.name, kind="datasource", name=ep.name, version="", state="error", error=str(exc)[:300])
            continue
        datasources.TYPES[ep.name] = cls
        datasources.SECURE_FIELDS[ep.name] = secure
        info = {
            "type": ep.name,
            "name": getattr(cls, "display_name", ep.name),
            "description": getattr(cls, "description", ""),
            "secure_fields": secure,
            "plugin": True,
        }
        datasources.TYPE_INFO[:] = [t for t in datasources.TYPE_INFO if t["type"] != ep.name] + [info]
        version = getattr(getattr(ep, "dist", None), "version", "") or ""
        _record(ep.name, kind="datasource", name=info["name"], version=version, state="loaded", error="")


def _manifest(folder):
    path = folder / "plugin.json"
    if not path.is_file() or path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError("plugin.json missing or too large")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("type") != "panel" or data.get("id") != folder.name or not PLUGIN_ID.match(folder.name):
        raise ValueError("plugin.json must declare type 'panel' and an id equal to the folder name (x-…)")
    module = str(data.get("module") or "module.js")
    if not re.fullmatch(r"[A-Za-z0-9._-]+\.js", module):
        raise ValueError("module must be a .js file inside the plugin folder")
    style = str(data.get("style") or "")
    if style and not re.fullmatch(r"[A-Za-z0-9._-]+\.css", style):
        raise ValueError("style must be a .css file inside the plugin folder")
    return {
        "id": folder.name,
        "name": str(data.get("name") or folder.name)[:80],
        "version": str(data.get("version") or "")[:40],
        "module": module,
        "style": style,
    }


def panel_plugins(settings):
    """Allow-listed panel plugins with a valid manifest (re-read on each call; folders are small)."""
    root = plugin_dir(settings)
    allowed = enabled_ids()
    out = []
    if not root.is_dir():
        return out
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        try:
            manifest = _manifest(folder)
        except (OSError, ValueError) as exc:
            _record(folder.name, kind="panel", name=folder.name, version="", state="error", error=str(exc)[:300])
            continue
        if manifest["id"] not in allowed:
            _record(manifest["id"], kind="panel", name=manifest["name"], version=manifest["version"], state="disabled", error="")
            continue
        _record(manifest["id"], kind="panel", name=manifest["name"], version=manifest["version"], state="loaded", error="")
        out.append(
            {
                **manifest,
                "module_url": f"/plugins/{manifest['id']}/{manifest['module']}",
                "style_url": f"/plugins/{manifest['id']}/{manifest['style']}" if manifest["style"] else "",
            }
        )
    return out


def asset_path(settings, plugin_id, relative):
    """Resolve a file of an enabled panel plugin; None when it is not servable."""
    if plugin_id not in enabled_ids() or not PLUGIN_ID.match(plugin_id):
        return None
    folder = (plugin_dir(settings) / plugin_id).resolve()
    target = (folder / relative).resolve()
    if folder not in target.parents or target.suffix not in ASSET_TYPES or not target.is_file():
        return None
    return target


def status(settings):
    panel_plugins(settings)  # refresh panel entries
    return sorted(_status.values(), key=lambda s: (s["kind"], s["id"]))
