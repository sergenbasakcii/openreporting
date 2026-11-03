"""Structural, human-readable differences between two dashboard models (pure; no I/O).

Panels are matched by id (including panels inside collapsed rows) and variables by name, so a
reviewer sees "Panel 'CPU' sorgusu değişti" instead of a raw JSON diff. Runtime-only state such
as a variable's current selection or resolved options is ignored.
"""

import json

DASHBOARD_FIELDS = {
    "title": "Başlık",
    "description": "Açıklama",
    "tags": "Etiketler",
    "time": "Varsayılan zaman aralığı",
    "refresh": "Otomatik yenileme",
    "timezone": "Saat dilimi",
}
PANEL_FIELDS = {
    "title": "başlık",
    "type": "görselleştirme türü",
    "datasource": "veri kaynağı",
    "targets": "sorgular",
    "transformations": "dönüşümler",
    "fieldConfig": "alan ayarları (birim, eşik, renk)",
    "options": "görünüm seçenekleri",
    "repeat": "tekrar değişkeni",
    "description": "açıklama",
    "gridPos": "konum/boyut",
}
VARIABLE_FIELDS = {
    "type": "tür",
    "datasource": "veri kaynağı",
    "query": "sorgu",
    "regex": "regex",
    "multi": "çoklu seçim",
    "includeAll": "'Tümü' seçeneği",
    "allValue": "'Tümü' değeri",
    "label": "etiket",
    "hide": "görünürlük",
    "sort": "sıralama",
}


def _panels(model):
    out = {}
    for panel in model.get("panels") or []:
        out[panel.get("id")] = panel
        for child in panel.get("panels") or []:  # collapsed rows keep their panels inside
            out[child.get("id")] = child
    return {k: v for k, v in out.items() if k is not None}


def _variables(model):
    return {v.get("name"): v for v in (model.get("templating") or {}).get("list") or [] if v.get("name")}


def _same(a, b):
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def _label(panel):
    title = str(panel.get("title") or "").strip()
    return f"'{title}'" if title else f"#{panel.get('id')}"


def diff(old, new):
    """Return a list of {"kind", "text"} changes from ``old`` to ``new`` (kinds: added, removed, changed)."""
    changes = []
    for key, label in DASHBOARD_FIELDS.items():
        if not _same(old.get(key), new.get(key)):
            changes.append({"kind": "changed", "scope": "dashboard", "text": f"{label} değişti"})
    old_vars, new_vars = _variables(old), _variables(new)
    for name in sorted(set(old_vars) | set(new_vars)):
        if name not in new_vars:
            changes.append({"kind": "removed", "scope": "variable", "text": f"Değişken ${name} kaldırıldı"})
        elif name not in old_vars:
            changes.append({"kind": "added", "scope": "variable", "text": f"Değişken ${name} eklendi"})
        else:
            fields = [label for key, label in VARIABLE_FIELDS.items() if not _same(old_vars[name].get(key), new_vars[name].get(key))]
            if fields:
                changes.append({"kind": "changed", "scope": "variable", "text": f"Değişken ${name}: {', '.join(fields)} değişti"})
    old_panels, new_panels = _panels(old), _panels(new)
    for pid in sorted(set(old_panels) | set(new_panels), key=str):
        if pid not in new_panels:
            changes.append({"kind": "removed", "scope": "panel", "text": f"Panel {_label(old_panels[pid])} kaldırıldı"})
        elif pid not in old_panels:
            changes.append({"kind": "added", "scope": "panel", "text": f"Panel {_label(new_panels[pid])} eklendi"})
        else:
            fields = [label for key, label in PANEL_FIELDS.items() if not _same(old_panels[pid].get(key), new_panels[pid].get(key))]
            if fields:
                changes.append({"kind": "changed", "scope": "panel", "text": f"Panel {_label(new_panels[pid])}: {', '.join(fields)} değişti"})
    return changes
