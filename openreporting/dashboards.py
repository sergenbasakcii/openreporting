"""Dashboards, folders, versions and Grafana JSON import.

The JSON model intentionally follows Grafana's (``panels[].gridPos``,
``templating.list``, ``fieldConfig``) so existing Grafana + Zabbix-plugin
dashboards can be imported and edited here.
"""

import copy
import json
import re

from . import folder_access
from .db import audit, connect, transaction, utcnow
from .domain import DomainError, canonical, identity

EXTRA_PANEL_TYPES = {
    "donut",
    "radar",
    "calendarheatmap",
    "heatmap",
    "polarbar",
    "candlestick",
    "histogram",
    "scatter",
    "funnel",
    "treemap",
    "boxplot",
    "nodegraph",
    "stackedarea",
    "waterfall",
    "stepchart",
    "sunburst",
    "rosepie",
    "parallel",
    "bubble",
    "sankey",
}
PANEL_TYPES = EXTRA_PANEL_TYPES | {
    "timeseries",
    "barchart",
    "stat",
    "gauge",
    "bargauge",
    "table",
    "piechart",
    "text",
    "statusgrid",
    "row",
    "heatmap",
    "statetimeline",
}
TYPE_ALIASES = {
    "graph": "timeseries",
    "singlestat": "stat",
    "grafana-singlestat-panel": "stat",
    "table-old": "table",
    "grafana-piechart-panel": "piechart",
    "grafana-polystat-panel": "statusgrid",
    "status-history": "statetimeline",
    "state-timeline": "statetimeline",
    "bargraph": "barchart",
    "alexanderzobnin-zabbix-triggers-panel": "table",
    "news": "text",
    "dashlist": "text",
}
VARIABLE_TYPES = {"query", "custom", "constant", "textbox", "interval", "datasource"}
MAX_DASHBOARD_BYTES = 3_000_000
MAX_PANELS = 400
_UID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_VAR_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,49}$")


class DashboardError(DomainError):
    pass


class VersionConflict(DashboardError):
    pass


def new_uid():
    return identity().replace("-", "")[:12]


def _grid(pos, index):
    pos = pos if isinstance(pos, dict) else {}
    w = max(1, min(int(pos.get("w", 12) or 12), 24))
    x = max(0, min(int(pos.get("x", 0) or 0), 24 - w))
    h = max(1, min(int(pos.get("h", 8) or 8), 100))
    y = max(0, int(pos.get("y", index * 8) or 0))
    return {"x": x, "y": y, "w": w, "h": h}


def _graph_panel_field_config(panel):
    """Translate Grafana 'graph'/'singlestat' options into fieldConfig defaults."""
    defaults = copy.deepcopy((panel.get("fieldConfig") or {}).get("defaults") or {})
    custom = defaults.setdefault("custom", {})
    if panel.get("type") == "graph":
        yaxes = panel.get("yaxes") or []
        if yaxes and isinstance(yaxes[0], dict):
            if yaxes[0].get("format") and "unit" not in defaults:
                defaults["unit"] = yaxes[0]["format"]
            if yaxes[0].get("min") not in (None, ""):
                defaults.setdefault("min", float(yaxes[0]["min"]))
            if yaxes[0].get("max") not in (None, ""):
                defaults.setdefault("max", float(yaxes[0]["max"]))
        custom.setdefault("drawStyle", "bars" if panel.get("bars") else "line")
        custom.setdefault("fillOpacity", int(panel.get("fill", 1) or 0) * 10)
        custom.setdefault("lineWidth", int(panel.get("linewidth", 1) or 1))
        if panel.get("stack"):
            custom.setdefault("stacking", {"mode": "normal"})
    if panel.get("type") == "singlestat":
        if panel.get("format"):
            defaults.setdefault("unit", panel["format"])
        thresholds = str(panel.get("thresholds") or "")
        colors = panel.get("colors") or ["green", "orange", "red"]
        if thresholds:
            values = [float(v) for v in thresholds.split(",") if v.strip()]
            steps = [{"color": colors[0], "value": None}] + [{"color": colors[min(i + 1, len(colors) - 1)], "value": v} for i, v in enumerate(values)]
            defaults.setdefault("thresholds", {"mode": "absolute", "steps": steps})
    return defaults


def _map_datasource(ref, ds_map):
    if ref is None:
        return None
    if isinstance(ref, str):
        if ref in ds_map:
            return {"uid": ds_map[ref]}
        if ref.startswith("${") or ref == "-- Mixed --":
            return ds_map.get("__default__") and {"uid": ds_map["__default__"]}
        return {"uid": ref}
    if isinstance(ref, dict):
        uid = ref.get("uid") or ""
        if ref.get("type") == "__expr__" or uid == "__expr__":
            return {"type": "__expr__", "uid": "__expr__"}
        if uid in ds_map:
            return {"uid": ds_map[uid]}
        kind = ref.get("type", "")
        if uid.startswith("${") or not uid or (kind and kind in ds_map):
            mapped = ds_map.get(kind) or ds_map.get("__default__")
            return {"uid": mapped} if mapped else None
        return {"uid": uid}
    return None


def _panel(panel, index, ds_map, ids):
    if not isinstance(panel, dict):
        raise DashboardError("Panel must be an object")
    original_type = str(panel.get("type") or "timeseries")
    kind = TYPE_ALIASES.get(original_type, original_type)
    out = copy.deepcopy(panel)
    if kind not in PANEL_TYPES:
        out = {
            "type": "text",
            "title": panel.get("title", ""),
            "options": {
                "mode": "markdown",
                "content": f"**Desteklenmeyen panel türü:** `{original_type}`.\n\nBu paneli desteklenen bir görselleştirmeyle yeniden oluşturun.",
            },
        }
        kind = "text"
    out["type"] = kind
    if original_type in ("graph", "singlestat"):
        out.setdefault("fieldConfig", {})["defaults"] = _graph_panel_field_config(panel)
        for key in (
            "yaxes",
            "xaxis",
            "lines",
            "bars",
            "points",
            "fill",
            "linewidth",
            "stack",
            "colors",
            "thresholds",
            "format",
            "seriesOverrides",
            "aliasColors",
        ):
            out.pop(key, None)
    if original_type == "alexanderzobnin-zabbix-triggers-panel":
        out["targets"] = [dict(t, queryType="problems") for t in panel.get("targets") or []]
    pid = panel.get("id")
    if not isinstance(pid, int) or pid in ids or pid <= 0:
        pid = max(ids, default=0) + 1
    ids.add(pid)
    out["id"] = pid
    out["title"] = str(out.get("title") or "")[:300]
    out["gridPos"] = _grid(panel.get("gridPos"), index)
    if "datasource" in out:
        out["datasource"] = _map_datasource(out.get("datasource"), ds_map)
    targets = out.get("targets") or []
    if not isinstance(targets, list) or len(targets) > 26:
        raise DashboardError(f"Panel '{out['title']}' has too many queries (max 26)")
    clean_targets = []
    for t_index, target in enumerate(targets):
        if not isinstance(target, dict):
            continue
        target = dict(target)
        target["refId"] = str(target.get("refId") or chr(65 + t_index))[:16]
        if "datasource" in target:
            target["datasource"] = _map_datasource(target.get("datasource"), ds_map)
        clean_targets.append(target)
    if kind != "row" and kind != "text":
        out["targets"] = clean_targets
    if kind == "row":
        out["collapsed"] = bool(out.get("collapsed"))
        children = out.get("panels") or []
        out["panels"] = [_panel(child, i, ds_map, ids) for i, child in enumerate(children)]
        out["gridPos"] = {"x": 0, "y": out["gridPos"]["y"], "w": 24, "h": 1}
    if out.get("repeat") is not None and not _VAR_NAME.match(str(out.get("repeat") or "x")):
        out["repeat"] = None
    if out.get("repeatDirection") not in (None, "h", "v"):
        out["repeatDirection"] = "h"
    out.pop("scopedVars", None)
    out.pop("repeatPanelId", None)
    return out


def _variable(var, ds_map):
    if not isinstance(var, dict) or not _VAR_NAME.match(str(var.get("name", ""))):
        raise DashboardError("Each variable needs a valid name (letters, digits, underscore)")
    kind = var.get("type", "query")
    if kind == "adhoc":
        kind = "textbox"
    if kind not in VARIABLE_TYPES:
        raise DashboardError(f"Unsupported variable type: {kind}")
    out = copy.deepcopy(var)
    out["type"] = kind
    if "datasource" in out and kind == "query":
        out["datasource"] = _map_datasource(out.get("datasource"), ds_map)
    out["multi"] = bool(out.get("multi"))
    out["includeAll"] = bool(out.get("includeAll"))
    out["hide"] = int(out.get("hide", 0) or 0) if str(out.get("hide", 0)).isdigit() else 0
    if kind == "query":
        out["refresh"] = int(out.get("refresh", 1) or 1)
    return out


def normalize(dashboard, ds_map=None):
    if not isinstance(dashboard, dict):
        raise DashboardError("Dashboard JSON must be an object")
    raw_size = len(json.dumps(dashboard, ensure_ascii=False).encode())
    if raw_size > MAX_DASHBOARD_BYTES:
        raise DashboardError("Dashboard JSON is too large (max 3 MB)")
    ds_map = ds_map or {}
    title = str(dashboard.get("title") or "").strip()
    if not 1 <= len(title) <= 200 or any(ord(c) < 32 for c in title):
        raise DashboardError("Dashboard title must be 1-200 characters")
    out = copy.deepcopy(dashboard)
    out.pop("id", None)
    out.pop("__inputs", None)
    out.pop("__requires", None)
    out.pop("__elements", None)
    out["title"] = title
    uid = str(out.get("uid") or new_uid())
    if not _UID.match(uid):
        raise DashboardError("Dashboard uid may contain letters, digits, '-' and '_' (max 40)")
    out["uid"] = uid
    tags = out.get("tags") or []
    out["tags"] = sorted({str(t).strip()[:50] for t in tags if str(t).strip()})[:30]
    time_range = out.get("time") or {}
    out["time"] = {"from": str(time_range.get("from") or "now-6h"), "to": str(time_range.get("to") or "now")}
    out["timezone"] = str(out.get("timezone") or "browser")
    out["refresh"] = str(out.get("refresh") or "")
    out["schemaVersion"] = 39
    panels = out.get("panels") or []
    if not isinstance(panels, list):
        raise DashboardError("panels must be a list")
    # Grafana < 5 'rows' format
    if not panels and isinstance(out.get("rows"), list):
        y = 0
        for row in out.pop("rows"):
            row_panels = row.get("panels") or []
            panels.append({"type": "row", "title": row.get("title", ""), "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "collapsed": False})
            y += 1
            x = 0
            for child in row_panels:
                span = int(child.get("span", 12) or 12) * 2
                height = max(4, int(str(row.get("height", "250")).rstrip("px") or 250) // 30)
                if x + span > 24:
                    x, y = 0, y + height
                child = dict(child, gridPos={"x": x, "y": y, "w": min(24, span), "h": height})
                panels.append(child)
                x += span
            y += 8
    ids = set()
    normalized = [_panel(p, i, ds_map, ids) for i, p in enumerate(panels)]
    count = sum(1 + len(p.get("panels", [])) for p in normalized)
    if count > MAX_PANELS:
        raise DashboardError(f"Dashboard has too many panels (max {MAX_PANELS})")
    out["panels"] = normalized
    templating = out.get("templating") or {}
    variables = templating.get("list") or []
    if len(variables) > 50:
        raise DashboardError("Too many variables (max 50)")
    names = set()
    clean_vars = []
    for var in variables:
        clean = _variable(var, ds_map)
        if clean["name"] in names:
            raise DashboardError(f"Duplicate variable: {clean['name']}")
        names.add(clean["name"])
        clean_vars.append(clean)
    out["templating"] = {"list": clean_vars}
    annotations = (out.get("annotations") or {}).get("list") or []
    out["annotations"] = {"list": [a for a in annotations if isinstance(a, dict)][:20]}
    out.pop("version", None)
    return out


def find_panel(model, panel_id):
    """Panel by id, including children of collapsed rows."""
    for panel in model.get("panels") or []:
        if panel.get("id") == panel_id:
            return panel
        for child in panel.get("panels") or []:
            if child.get("id") == panel_id:
                return child
    return None


def _clip(value, limit=500):
    return str(value)[:limit]


def viewer_variables(model, client_vars):
    """Runtime variables for a viewer request.

    Definitions (type, multi, includeAll, allValue) come from the *saved*
    dashboard; only the selected values and option lists come from the browser,
    and those are later formatted strictly (quoted/escaped) for the datasource.
    """
    client_vars = client_vars if isinstance(client_vars, dict) else {}
    result = {}
    for var in (model.get("templating") or {}).get("list", []):
        name = var["name"]
        sent = client_vars.get(name)
        sent = sent if isinstance(sent, dict) else {"value": sent}
        value = sent.get("value")
        if isinstance(value, list):
            value = [_clip(v) for v in value[:1000]]
        elif value is not None:
            value = _clip(value)
        options = [{"text": _clip(o.get("text", "")), "value": _clip(o.get("value", ""))} for o in (sent.get("options") or [])[:10000] if isinstance(o, dict)]
        if var.get("type") == "constant":
            value = str(var.get("query") or "")
        result[name] = {
            "value": value,
            "text": _clip(sent.get("text") or ""),
            "options": options,
            "multi": bool(var.get("multi")),
            "includeAll": bool(var.get("includeAll")),
            "allValue": var.get("allValue") or None,
            "type": var.get("type"),
        }
    return result


def import_map(settings_rows, dashboard):
    """Auto-map Grafana datasource references to our datasources by type."""
    by_type = {}
    default = None
    for row in settings_rows:
        by_type.setdefault(row["type"], row["uid"])
        if row.get("isDefault"):
            default = row["uid"]
    mapping = {"__default__": default or (settings_rows[0]["uid"] if settings_rows else None)}
    if "zabbix" in by_type:
        mapping["alexanderzobnin-zabbix-datasource"] = by_type["zabbix"]
        mapping["zabbix"] = by_type["zabbix"]
    if "postgres" in by_type:
        for key in ("postgres", "grafana-postgresql-datasource", "postgresql"):
            mapping[key] = by_type["postgres"]
    if "testdata" in by_type:
        for key in ("testdata", "grafana-testdata-datasource"):
            mapping[key] = by_type["testdata"]
    for item in dashboard.get("__inputs") or []:
        if item.get("type") == "datasource":
            plugin = item.get("pluginId", "")
            target = mapping.get(plugin) or mapping["__default__"]
            if target:
                mapping["${" + item.get("name", "") + "}"] = target
    return mapping


# --- persistence -------------------------------------------------------------


def _folder_id(db, folder_uid):
    if not folder_uid:
        return None
    row = db.execute("SELECT id FROM folders WHERE uid=?", (folder_uid,)).fetchone()
    if not row:
        raise DashboardError("Folder not found")
    return row["id"]


KEEP_FOLDER = object()


def save(settings, user, dashboard, *, folder_uid=None, message="", overwrite=False, ds_map=None):
    """Save a dashboard; ``folder_uid=KEEP_FOLDER`` leaves an existing dashboard where it is."""
    expected_version = dashboard.get("version") if isinstance(dashboard, dict) else None
    if expected_version is not None:
        try:
            expected_version = int(expected_version)
        except (TypeError, ValueError):
            raise DashboardError("Geçersiz dashboard sürümü") from None
    model = normalize(dashboard, ds_map)
    now = utcnow()
    with connect(settings) as db, transaction(db):
        if folder_uid is KEEP_FOLDER:
            existing = db.execute("SELECT folder_id FROM dashboards WHERE uid=?", (model["uid"],)).fetchone()
            folder_id = existing["folder_id"] if existing else None
        else:
            folder_id = _folder_id(db, folder_uid)
        row = db.execute("SELECT * FROM dashboards WHERE uid=?", (model["uid"],)).fetchone()
        if row:
            folder_access.require_folder(db, user, row["folder_id"], edit=True)
        folder_access.require_folder(db, user, folder_id, edit=True)
        clash = db.execute(
            "SELECT uid FROM dashboards WHERE title=? AND COALESCE(folder_id,'')=COALESCE(?,'') AND uid<>?", (model["title"], folder_id, model["uid"])
        ).fetchone()
        if clash and not overwrite:
            raise VersionConflict("Bu klasörde aynı adlı bir dashboard var")
        if row:
            if expected_version is not None and expected_version != row["version"] and not overwrite:
                raise VersionConflict("Dashboard başka biri tarafından değiştirildi; sayfayı yenileyin veya üzerine yazın")
            version = row["version"] + 1
            db.execute(
                """UPDATE dashboards SET title=?,folder_id=?,tags_json=?,data_json=?,version=?,updated_at=?,
                          updated_by=? WHERE id=?""",
                (model["title"], folder_id, json.dumps(model["tags"]), canonical(model), version, now, user["id"], row["id"]),
            )
            dashboard_id = row["id"]
        else:
            version = 1
            dashboard_id = identity()
            db.execute(
                """INSERT INTO dashboards(id,uid,title,folder_id,tags_json,data_json,version,created_at,updated_at,
                          created_by,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (dashboard_id, model["uid"], model["title"], folder_id, json.dumps(model["tags"]), canonical(model), version, now, now, user["id"], user["id"]),
            )
        db.execute("INSERT INTO dashboard_versions VALUES(?,?,?,?,?,?)", (dashboard_id, version, canonical(model), str(message or "")[:500], now, user["id"]))
        db.execute(
            """DELETE FROM dashboard_versions WHERE dashboard_id=? AND version NOT IN
                      (SELECT version FROM dashboard_versions WHERE dashboard_id=? ORDER BY version DESC LIMIT 50)""",
            (dashboard_id, dashboard_id),
        )
        audit(db, user["id"], "dashboard.saved", "dashboard", model["uid"], {"version": version, "title": model["title"]})
    return {"uid": model["uid"], "version": version, "url": f"/d/{model['uid']}"}


def get(settings, uid, user=None):
    with connect(settings) as db:
        row = db.execute(
            """SELECT d.*,f.uid AS folder_uid,f.title AS folder_title,cu.username AS created_name,
                            uu.username AS updated_name FROM dashboards d LEFT JOIN folders f ON f.id=d.folder_id
                            LEFT JOIN users cu ON cu.id=d.created_by LEFT JOIN users uu ON uu.id=d.updated_by
                            WHERE d.uid=?""",
            (uid,),
        ).fetchone()
        if not row:
            raise DashboardError("Dashboard bulunamadı")
        folder_access.require_folder(db, user, row["folder_id"])
        can_edit = folder_access.allowed(db, user, row["folder_id"], edit=True)
        starred = bool(user and db.execute("SELECT 1 FROM dashboard_stars WHERE user_id=? AND dashboard_id=?", (user["id"], row["id"])).fetchone())
    model = json.loads(row["data_json"])
    model["version"] = row["version"]
    return {
        "dashboard": model,
        "meta": {
            "folderUid": row["folder_uid"],
            "folderTitle": row["folder_title"] or "Genel",
            "created": row["created_at"],
            "updated": row["updated_at"],
            "createdBy": row["created_name"],
            "updatedBy": row["updated_name"],
            "version": row["version"],
            "isStarred": starred,
            "canEdit": can_edit,
            "canSave": can_edit,
            "url": f"/d/{uid}",
        },
    }


def delete(settings, user, uid):
    with connect(settings) as db, transaction(db):
        row = db.execute("SELECT id,title,folder_id FROM dashboards WHERE uid=?", (uid,)).fetchone()
        if not row:
            raise DashboardError("Dashboard bulunamadı")
        folder_access.require_folder(db, user, row["folder_id"], edit=True)
        if db.execute("SELECT 1 FROM dash_reports WHERE dashboard_uid=?", (uid,)).fetchone():
            raise DashboardError("Bu dashboard'u kullanan raporlar var; önce raporları silin")
        db.execute("DELETE FROM annotations WHERE dashboard_uid=?", (uid,))
        db.execute("DELETE FROM dashboard_stars WHERE dashboard_id=?", (row["id"],))
        db.execute("DELETE FROM dashboard_versions WHERE dashboard_id=?", (row["id"],))
        db.execute("DELETE FROM dashboards WHERE id=?", (row["id"],))
        audit(db, user["id"], "dashboard.deleted", "dashboard", uid, {"title": row["title"]})


def versions(settings, uid, user=None):
    with connect(settings) as db:
        folder_access.require_dashboard(db, user, uid)
        row = db.execute("SELECT id FROM dashboards WHERE uid=?", (uid,)).fetchone()
        if not row:
            raise DashboardError("Dashboard bulunamadı")
        return [
            dict(r)
            for r in db.execute(
                """SELECT v.version,v.message,v.created_at,u.username AS created_by
                    FROM dashboard_versions v LEFT JOIN users u ON u.id=v.created_by
                    WHERE v.dashboard_id=? ORDER BY v.version DESC""",
                (row["id"],),
            )
        ]


def version_data(settings, uid, version, user=None):
    with connect(settings) as db:
        folder_access.require_dashboard(db, user, uid)
        row = db.execute(
            """SELECT v.data_json FROM dashboard_versions v JOIN dashboards d ON d.id=v.dashboard_id
                            WHERE d.uid=? AND v.version=?""",
            (uid, int(version)),
        ).fetchone()
    if not row:
        raise DashboardError("Sürüm bulunamadı")
    return json.loads(row["data_json"])


def restore(settings, user, uid, version):
    model = version_data(settings, uid, version, user)
    current = get(settings, uid, user)
    model["version"] = current["dashboard"]["version"]
    return save(settings, user, model, folder_uid=current["meta"]["folderUid"], message=f"Sürüm {version} geri yüklendi")


def star(settings, user, uid, value=True):
    with connect(settings) as db, transaction(db):
        folder_access.require_dashboard(db, user, uid)
        row = db.execute("SELECT id FROM dashboards WHERE uid=?", (uid,)).fetchone()
        if not row:
            raise DashboardError("Dashboard bulunamadı")
        if value:
            db.execute(
                """INSERT INTO dashboard_stars(user_id,dashboard_id) VALUES(?,?)
                          ON CONFLICT(user_id,dashboard_id) DO NOTHING""",
                (user["id"], row["id"]),
            )
        else:
            db.execute("DELETE FROM dashboard_stars WHERE user_id=? AND dashboard_id=?", (user["id"], row["id"]))


def search(settings, user, query="", tag="", folder_uid=None, starred=False, limit=500):
    sql = """SELECT d.uid,d.title,d.tags_json,d.updated_at,f.uid AS folder_uid,f.title AS folder_title,
             EXISTS(SELECT 1 FROM dashboard_stars s WHERE s.dashboard_id=d.id AND s.user_id=?) AS starred
             FROM dashboards d LEFT JOIN folders f ON f.id=d.folder_id WHERE 1=1"""
    params = [user["id"]]
    if query:
        sql += " AND LOWER(d.title) LIKE LOWER(?) ESCAPE '\\'"
        params.append("%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    if folder_uid is not None:
        if folder_uid == "":
            sql += " AND d.folder_id IS NULL"
        else:
            sql += " AND f.uid=?"
            params.append(folder_uid)
    if starred:
        sql += " AND EXISTS(SELECT 1 FROM dashboard_stars s WHERE s.dashboard_id=d.id AND s.user_id=?)"
        params.append(user["id"])
    with connect(settings) as db:
        visible, values = folder_access.visible_sql(db, user, "d.folder_id")
        sql += " AND " + visible + " ORDER BY LOWER(d.title),d.uid LIMIT ?"
        rows = db.execute(sql, [*params, *values, max(1, min(int(limit), 5000))]).fetchall()
    results = []
    for row in rows:
        tags = json.loads(row["tags_json"])
        if tag and tag not in tags:
            continue
        results.append(
            {
                "uid": row["uid"],
                "title": row["title"],
                "tags": tags,
                "url": f"/d/{row['uid']}",
                "folderUid": row["folder_uid"],
                "folderTitle": row["folder_title"] or "Genel",
                "isStarred": bool(row["starred"]),
                "updated": row["updated_at"],
                "type": "dash-db",
            }
        )
    return results


def folders(settings, user=None):
    with connect(settings) as db:
        visible, values = folder_access.visible_sql(db, user, "f.id")
        rows = db.execute(
            """SELECT f.id,f.uid,f.title,f.updated_at,
                (SELECT COUNT(*) FROM dashboards d WHERE d.folder_id=f.id) AS dashboard_count
                FROM folders f WHERE """
            + visible
            + " ORDER BY LOWER(f.title),f.uid",
            values,
        ).fetchall()
        return [
            {**{k: r[k] for k in ("uid", "title", "updated_at", "dashboard_count")}, "canEdit": folder_access.allowed(db, user, r["id"], edit=True)}
            for r in rows
        ]


def save_folder(settings, user, title, uid=None):
    title = str(title or "").strip()
    if not 1 <= len(title) <= 120 or any(ord(c) < 32 for c in title) or title.lower() == "genel":
        raise DashboardError("Klasör adı 1-120 karakter olmalı ve 'Genel' olamaz")
    now = utcnow()
    with connect(settings) as db, transaction(db):
        folder_access.require_folder(db, user, _folder_id(db, uid) if uid else None, edit=True)
        if db.execute("SELECT 1 FROM folders WHERE title=? AND uid<>?", (title, uid or "")).fetchone():
            raise DashboardError("Bu adla bir klasör zaten var")
        if uid:
            if not db.execute("SELECT 1 FROM folders WHERE uid=?", (uid,)).fetchone():
                raise DashboardError("Klasör bulunamadı")
            db.execute("UPDATE folders SET title=?,updated_at=?,updated_by=? WHERE uid=?", (title, now, user["id"], uid))
        else:
            uid = new_uid()
            db.execute("INSERT INTO folders VALUES(?,?,?,?,?,?)", (identity(), uid, title, now, now, user["id"]))
        audit(db, user["id"], "folder.saved", "folder", uid, {"title": title})
    return {"uid": uid, "title": title}


def delete_folder(settings, user, uid):
    with connect(settings) as db, transaction(db):
        row = db.execute("SELECT id FROM folders WHERE uid=?", (uid,)).fetchone()
        if not row:
            raise DashboardError("Klasör bulunamadı")
        folder_access.require_folder(db, user, row["id"], edit=True)
        if db.execute("SELECT 1 FROM dashboards WHERE folder_id=?", (row["id"],)).fetchone():
            raise DashboardError("Klasör boş değil; önce dashboard'ları taşıyın veya silin")
        db.execute("DELETE FROM folders WHERE id=?", (row["id"],))
        audit(db, user["id"], "folder.deleted", "folder", uid)


def tags(settings, user=None):
    with connect(settings) as db:
        counts = {}
        visible, values = folder_access.visible_sql(db, user, "d.folder_id")
        for row in db.execute("SELECT tags_json FROM dashboards d WHERE " + visible, values):
            for tag in json.loads(row["tags_json"]):
                counts[tag] = counts.get(tag, 0) + 1
    return [{"term": t, "count": c} for t, c in sorted(counts.items())]
