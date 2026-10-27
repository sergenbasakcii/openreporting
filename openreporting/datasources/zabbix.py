"""Zabbix datasource: Grafana-Zabbix style group/host/item/tag queries.

Security model (unchanged from v0.4): only allow-listed read methods, TLS
verification always on, redirects refused, the token never leaves the server.
Large selections are refused with a clear message instead of being truncated.
"""
import json
import math
import re
import ssl
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit

from ..frames import finite, table_frame, ts_frame
from ..series_functions import query_option
from ..timerange import parse_duration
from .base import (DataSource, DataSourceError, QueryResult, TTLCache, bucket_average,
                   compile_filter)

READ_METHODS = frozenset({"apiinfo.version", "hostgroup.get", "host.get", "item.get", "history.get",
                          "trend.get", "trigger.get", "problem.get", "event.get", "valuemap.get"})
NUMERIC = {"0", "3"}
SEVERITIES = ["Sınıflandırılmamış", "Bilgi", "Uyarı", "Ortalama", "Yüksek", "Felaket"]
MODE_ALIASES = {"0": "metrics", "2": "itemvalues", "3": "itemid", "4": "problems", "5": "problems",
                "metrics": "metrics", "itemvalues": "itemvalues", "text": "itemvalues", "itemid": "itemid",
                "problems": "problems", "triggers": "problems"}
_META_CACHE = TTLCache(ttl=60, size=2048)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DataSourceError("Zabbix API redirect refused to protect the API token")


def validate_url(url, allow_http=False):
    try:
        parsed = urlsplit(url or "")
    except ValueError as exc:
        raise DataSourceError("Invalid Zabbix URL") from exc
    schemes = ("https", "http") if allow_http else ("https",)
    if parsed.scheme not in schemes or not parsed.hostname or parsed.username or parsed.password \
            or parsed.fragment or not parsed.path.endswith("api_jsonrpc.php"):
        raise DataSourceError("Zabbix URL must be https://<host>/.../api_jsonrpc.php"
                              + (" (http allowed by administrator)" if allow_http else ""))
    return url


class ZabbixApi:
    def __init__(self, url, token="", *, auth_mode="bearer", ca_pem="", timeout=30,
                 max_bytes=64_000_000, allow_http=False, transport=None):
        self.url = validate_url(url, allow_http) if transport is None else url
        self.token = token
        self.auth_mode = auth_mode if auth_mode in ("bearer", "body") else "bearer"
        self.ca_pem = ca_pem or ""
        self.timeout = max(3, min(int(timeout or 30), 300))
        self.max_bytes = max_bytes
        self.transport = transport

    def call(self, method, params=None):
        if method not in READ_METHODS:
            raise DataSourceError(f"Zabbix method not allowed: {method}")
        params = params or {}
        if self.transport is not None:
            return self.transport(method, params)
        body = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
        headers = {"Content-Type": "application/json-rpc"}
        if method != "apiinfo.version":
            if not self.token:
                raise DataSourceError("Zabbix API token is not configured")
            if self.auth_mode == "body":
                body["auth"] = self.token
            else:
                headers["Authorization"] = "Bearer " + self.token
        request = urllib.request.Request(self.url, json.dumps(body, separators=(",", ":")).encode(),
                                         headers, method="POST")
        handlers = [_NoRedirect()]
        if self.url.startswith("https://"):
            try:
                context = ssl.create_default_context(cadata=self.ca_pem or None)
            except (ssl.SSLError, ValueError) as exc:
                raise DataSourceError("Zabbix CA sertifikası okunamadı (PEM biçimini kontrol edin)") from exc
            handlers.append(urllib.request.HTTPSHandler(context=context))
        opener = urllib.request.build_opener(*handlers)
        try:
            with opener.open(request, timeout=self.timeout) as response:
                raw = response.read(self.max_bytes + 1)
        except urllib.error.HTTPError as exc:
            raise DataSourceError(f"Zabbix API HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise DataSourceError(f"Zabbix API'ye ulaşılamadı: {reason}") from exc
        if len(raw) > self.max_bytes:
            raise DataSourceError("Zabbix response exceeds the configured size limit; narrow the query")
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise DataSourceError("Zabbix API returned invalid JSON") from exc
        if "error" in data:
            error = data["error"] or {}
            raise DataSourceError(f"Zabbix API hatası: {error.get('message', '')} {error.get('data', '')}".strip())
        if "result" not in data:
            raise DataSourceError("Unexpected Zabbix API response")
        return data["result"]


def normalize_target(target):
    """Accept Grafana-Zabbix plugin JSON and our own query model."""
    out = dict(target)
    out["queryType"] = MODE_ALIASES.get(str(target.get("queryType", "metrics")), "metrics")
    for key in ("group", "host", "item", "itemTag", "application", "trigger"):
        value = target.get(key)
        if isinstance(value, str):
            out[key] = {"filter": value}
        elif not isinstance(value, dict):
            out[key] = {"filter": ""}
    if not out["itemTag"].get("filter") and out["application"].get("filter"):
        out["itemTag"] = {"filter": out["application"]["filter"]}
    options = dict(target.get("options") or {})
    use_trends = options.get("useTrends", target.get("mode"))
    options["mode"] = {"true": "trends", True: "trends", "false": "history", False: "history",
                       "trends": "trends", "history": "history", "raw": "history"}.get(use_trends, "auto")
    out["options"] = options
    out["functions"] = list(target.get("functions") or [])
    return out


def _tag_filter(text):
    """``tag``, ``tag: value`` or ``/regex/`` matched against "tag: value"."""
    text = (text or "").strip()
    if not text:
        return lambda tags: True
    predicate = compile_filter(text)
    def match(tags):
        for tag in tags or []:
            label = f"{tag.get('tag', '')}: {tag.get('value', '')}" if tag.get("value") else tag.get("tag", "")
            if predicate(label) or predicate(tag.get("tag", "")):
                return True
        return False
    return match


class InventoryResolver:
    """Shared filter resolution for Zabbix and the Zabbix simulator."""

    def groups(self):  # pragma: no cover - interface
        raise NotImplementedError

    def hosts(self, groupids):  # pragma: no cover - interface
        raise NotImplementedError

    def items(self, hostids):  # pragma: no cover - interface
        raise NotImplementedError

    def resolve(self, target, *, numeric_only=True, max_items=500, include_disabled=False):
        group_ok = compile_filter(target["group"].get("filter"))
        host_ok = compile_filter(target["host"].get("filter"))
        item_ok = compile_filter(target["item"].get("filter"))
        tag_ok = _tag_filter(target["itemTag"].get("filter"))
        groups = [g for g in self.groups() if group_ok(g["name"])]
        if not groups:
            return [], {}, ["Filtreyle eşleşen host grubu yok"]
        group_names = {g["groupid"]: g["name"] for g in groups}
        hosts = [h for h in self.hosts(tuple(sorted(group_names))) if host_ok(h["name"]) or host_ok(h.get("host", ""))]
        if not hosts:
            return [], {}, ["Filtreyle eşleşen host yok"]
        host_map = {h["hostid"]: h for h in hosts}
        items = []
        for item in self.items(tuple(sorted(host_map))):
            if item["hostid"] not in host_map:
                continue
            if not include_disabled and str(item.get("status", "0")) != "0":
                continue
            if numeric_only and str(item.get("value_type")) not in NUMERIC:
                continue
            if not (item_ok(item.get("name", "")) or item_ok(item.get("key_", ""))):
                continue
            if not tag_ok(item.get("tags")):
                continue
            items.append(item)
        if len(items) > max_items:
            raise DataSourceError(f"Sorgu {len(items)} item ile eşleşti; güvenlik sınırı {max_items}. "
                                  "Grup/host/item filtresini daraltın veya fonksiyonlarla toplulaştırın.")
        for host in hosts:
            host["_groups"] = [group_names[g] for g in host.get("_groupids", []) if g in group_names]
        return items, host_map, [] if items else ["Filtreyle eşleşen sayısal item yok"]


def series_labels(item, host):
    groups = host.get("_groups") or []
    return {"host": host.get("name", ""), "host_technical": host.get("host", ""), "hostid": str(host["hostid"]),
            "item": item.get("name", ""), "item_key": item.get("key_", ""), "itemid": str(item["itemid"]),
            **({"group": groups[0]} if groups else {})}


def items_to_frames(items, host_map, points_by_item, ref_id, resolution, interval_ms, max_points, consolidate,
                    anchor_ms=0):
    frames = []
    for item in items:
        host = host_map[item["hostid"]]
        points = points_by_item.get(str(item["itemid"]), [])
        if len(points) > max_points * 1.2:
            points = bucket_average(points, interval_ms, consolidate, anchor_ms)
        frames.append(ts_frame(f"{host.get('name', '')}: {item.get('name', '')}", points,
                               labels=series_labels(item, host), unit=item.get("units", ""), ref_id=ref_id,
                               meta={"resolution": resolution, "itemid": str(item["itemid"]),
                                     "delay": item.get("delay", ""), "value_type": str(item.get("value_type"))}))
    return frames


def value_table(items, host_map, ref_id):
    rows = []
    for item in sorted(items, key=lambda i: (host_map[i["hostid"]].get("name", ""), i.get("name", ""))):
        host = host_map[item["hostid"]]
        raw = item.get("lastvalue")
        value = finite(raw) if str(item.get("value_type")) in NUMERIC else raw
        clock = int(item.get("lastclock") or 0)
        rows.append([host.get("name", ""), item.get("name", ""), value if clock else None,
                     item.get("units", ""), clock * 1000 if clock else None, item.get("key_", "")])
    return table_frame("Son değerler", [
        {"name": "Host", "type": "string"}, {"name": "Item", "type": "string"},
        {"name": "Değer", "type": "number"}, {"name": "Birim", "type": "string"},
        {"name": "Son veri", "type": "time"}, {"name": "Anahtar", "type": "string"}], rows, ref_id=ref_id,
        meta={"rowUnits": [r[3] for r in rows]})


def problems_table(triggers, ref_id, now_ms):
    rows = []
    for trigger in sorted(triggers, key=lambda t: (-int(t.get("priority", 0)), -int(t.get("lastchange", 0)))):
        hosts = ", ".join(h.get("name", "") for h in trigger.get("hosts", []))
        since = int(trigger.get("lastchange") or 0) * 1000
        priority = int(trigger.get("priority", 0))
        rows.append([since, hosts, trigger.get("description", ""), SEVERITIES[min(priority, 5)],
                     priority, (now_ms - since) / 1000 if since else None])
    return table_frame("Aktif problemler", [
        {"name": "Başlangıç", "type": "time"}, {"name": "Host", "type": "string"},
        {"name": "Problem", "type": "string"}, {"name": "Önem", "type": "string"},
        {"name": "Önem seviyesi", "type": "number"}, {"name": "Süre", "type": "number", "unit": "dtdurations"}],
        rows, ref_id=ref_id)


def parse_find_query(query):
    """``{group}{host}{item}`` text or structured ``{"type": "host", ...}``."""
    if isinstance(query, dict):
        return {"type": query.get("type", "group"), "group": query.get("group", ""),
                "host": query.get("host", ""), "item": query.get("item", ""),
                "itemTag": query.get("itemTag", "")}
    parts = re.findall(r"\{([^}]*)\}", str(query or ""))
    kinds = {1: "group", 2: "host", 3: "item", 4: "item"}
    if not parts:
        return {"type": "group", "group": "", "host": "", "item": "", "itemTag": ""}
    parsed = {"type": kinds.get(len(parts), "item"), "group": parts[0],
              "host": parts[1] if len(parts) > 1 else "", "itemTag": parts[2] if len(parts) == 4 else "",
              "item": parts[3] if len(parts) == 4 else (parts[2] if len(parts) == 3 else "")}
    return parsed


def find_values(resolver, query):
    spec = parse_find_query(query)
    group_ok = compile_filter(spec["group"] or "")
    groups = [g for g in resolver.groups() if group_ok(g["name"])]
    if spec["type"] == "group":
        names = sorted({g["name"] for g in groups}, key=str.casefold)
        return [{"text": n, "value": n} for n in names]
    hosts = resolver.hosts(tuple(sorted(g["groupid"] for g in groups))) if groups else []
    host_ok = compile_filter(spec["host"] or "")
    hosts = [h for h in hosts if host_ok(h["name"])]
    if spec["type"] == "host":
        names = sorted({h["name"] for h in hosts}, key=str.casefold)
        return [{"text": n, "value": n} for n in names]
    items = resolver.items(tuple(sorted(h["hostid"] for h in hosts))) if hosts else []
    if spec["type"] in ("itemTag", "application"):
        tags = sorted({f"{t['tag']}: {t['value']}" if t.get("value") else t["tag"]
                       for i in items for t in (i.get("tags") or [])}, key=str.casefold)
        return [{"text": t, "value": t} for t in tags]
    item_ok = compile_filter(spec["item"] or "")
    tag_ok = _tag_filter(spec["itemTag"])
    names = sorted({i["name"] for i in items if item_ok(i["name"]) and tag_ok(i.get("tags"))}, key=str.casefold)
    return [{"text": n, "value": n} for n in names]


class _ApiInventory(InventoryResolver):
    def __init__(self, ds):
        self.ds = ds

    def groups(self):
        return self.ds.cached("hostgroup.get", {"output": ["groupid", "name"], "sortfield": "name"})

    def hosts(self, groupids):
        if not groupids:
            return []
        select = "selectHostGroups" if self.ds.version() >= (6, 2) else "selectGroups"
        rows = self.ds.cached("host.get", {"groupids": list(groupids), "output": ["hostid", "host", "name", "status"],
                                           "monitored_hosts": True, select: ["groupid"]})
        hosts = []
        for row in rows:
            membership = row.get("hostgroups") or row.get("groups") or []
            hosts.append({**row, "hostid": str(row["hostid"]), "_groupids": [str(g["groupid"]) for g in membership]})
        return hosts

    def items(self, hostids):
        if not hostids:
            return []
        params = {"hostids": list(hostids), "monitored": True, "webitems": True,
                  "output": ["itemid", "hostid", "name", "key_", "units", "value_type", "status", "state",
                             "delay", "lastvalue", "lastclock"]}
        if self.ds.version() >= (5, 4):
            params["selectTags"] = ["tag", "value"]
        rows = self.ds.cached("item.get", params)
        return [{**row, "itemid": str(row["itemid"]), "hostid": str(row["hostid"])} for row in rows]


class ZabbixDataSource(DataSource):
    type = "zabbix"
    default_format = "zabbix"

    def __init__(self, record, secure, settings, *, transport=None, resolver=None):
        super().__init__(record, secure, settings)
        token = self.secure.get("token", "")
        token_file = self.options.get("token_file")
        if not token and token_file:
            try:
                token = Path(token_file).read_text(encoding="utf8").strip()
            except OSError as exc:
                raise DataSourceError("Zabbix token file unavailable") from exc
        self.api = ZabbixApi(self.url, token, auth_mode=self.options.get("auth_mode", "bearer"),
                             ca_pem=self.options.get("ca_pem", ""), timeout=self.options.get("timeout", 30),
                             allow_http=bool(getattr(settings, "allow_http_datasources", False)),
                             transport=transport)
        self.cache_ttl = float(self.options.get("cache_ttl", 60))
        self.max_items = int(self.options.get("max_items", 500))
        self.resolver = resolver
        self.inventory = _ApiInventory(self)

    def cached(self, method, params):
        key = (self.uid, self.url, method, json.dumps(params, sort_keys=True))
        if self.cache_ttl > 0:
            hit = _META_CACHE.get(key)
            if hit is not None:
                return hit
        value = self.api.call(method, params)
        if self.cache_ttl > 0:
            _META_CACHE.put(key, value)
        return value

    def version(self):
        try:
            text = self.cached("apiinfo.version", {})
            return tuple(int(x) for x in re.findall(r"\d+", str(text))[:2]) or (7, 0)
        except DataSourceError:
            return (7, 0)

    # -- metric queries -------------------------------------------------
    def _use_trends(self, mode, ctx):
        if mode == "trends":
            return True
        if mode == "history":
            return False
        trends_from = parse_duration(self.options.get("trends_from", "7d"))
        trends_range = parse_duration(self.options.get("trends_range", "4d"))
        age = time.time() - ctx.start.timestamp()
        return age > trends_from or (ctx.end - ctx.start).total_seconds() > trends_range

    def _history_api(self, items, start, end, max_rows):
        points = defaultdict(list)
        by_type = defaultdict(list)
        for item in items:
            by_type[str(item["value_type"])].append(str(item["itemid"]))
        fetched = 0
        for value_type, ids in by_type.items():
            for offset in range(0, len(ids), 200):
                rows = self.api.call("history.get", {
                    "history": int(value_type), "itemids": ids[offset:offset + 200],
                    "time_from": int(start), "time_till": int(end) - 1, "sortfield": "clock",
                    "sortorder": "ASC", "output": ["itemid", "clock", "value"], "limit": max_rows + 1})
                fetched += len(rows)
                if len(rows) > max_rows or fetched > max_rows:
                    raise DataSourceError("Ham history satır sınırı aşıldı; trend kullanın veya aralığı daraltın "
                                          "(eksik grafik üretilmez).")
                for row in rows:
                    points[str(row["itemid"])].append([int(row["clock"]) * 1000, finite(row["value"])])
        return points

    def _trends_api(self, items, start, end, max_rows, column):
        points = defaultdict(list)
        ids = [str(i["itemid"]) for i in items]
        fetched = 0
        for offset in range(0, len(ids), 200):
            rows = self.api.call("trend.get", {
                "itemids": ids[offset:offset + 200], "time_from": int(start), "time_till": int(end) - 1,
                "output": ["itemid", "clock", "num", "value_min", "value_avg", "value_max"], "limit": max_rows + 1})
            fetched += len(rows)
            if fetched > max_rows:
                raise DataSourceError("Trend satır sınırı aşıldı; aralığı veya item sayısını azaltın.")
            for row in rows:
                if column == "count":
                    value = finite(row.get("num"))
                elif column == "sum":
                    avg, num = finite(row.get("value_avg")), finite(row.get("num"))
                    value = avg * num if avg is not None and num is not None else None
                else:
                    value = finite(row.get(f"value_{column}"))
                points[str(row["itemid"])].append([int(row["clock"]) * 1000, value])
        for values in points.values():
            values.sort(key=lambda p: p[0])
        return points

    def _history_sql(self, items, start, end, interval_s, trends, column, consolidate="avg", anchor_s=0):
        if not self.resolver:
            raise DataSourceError("SQL history source is not available")
        sql_ds = self.resolver(self.options.get("sql_datasource_uid"))
        if sql_ds is None or sql_ds.type != "postgres":
            raise DataSourceError("Zabbix SQL history requires a linked PostgreSQL datasource")
        tables = {
            ("0", False): self.options.get("history_table_float", "history"),
            ("3", False): self.options.get("history_table_uint", "history_uint"),
            ("0", True): self.options.get("trends_table_float", "trends"),
            ("3", True): self.options.get("trends_table_uint", "trends_uint"),
        }
        by_type = defaultdict(list)
        for item in items:
            by_type[str(item["value_type"])].append(int(item["itemid"]))
        points = defaultdict(list)
        bucket = max(1, int(interval_s))
        for value_type, ids in by_type.items():
            table = tables[(value_type, trends)]
            mode = f"trend_{column}" if trends else f"history_{consolidate}"
            for itemid, ts, value in sql_ds.bucketed_history(table, mode, ids, int(start), int(end), bucket, anchor_s):
                points[str(itemid)].append([int(ts) * 1000, finite(value)])
        return points

    def query(self, target, ctx):
        target = normalize_target(target)
        ref_id = target.get("refId", "A")
        mode = target["queryType"]
        warnings = []
        if mode == "problems":
            items_target = dict(target, item={"filter": ""}, itemTag={"filter": ""})
            group_ok = compile_filter(items_target["group"].get("filter"))
            groups = [g["groupid"] for g in self.inventory.groups() if group_ok(g["name"])]
            if not groups:
                return QueryResult([problems_table([], ref_id, int(ctx.end.timestamp() * 1000))],
                                   ["Filtreyle eşleşen host grubu yok"])
            host_ok = compile_filter(items_target["host"].get("filter"))
            hosts = [h["hostid"] for h in self.inventory.hosts(tuple(sorted(groups)))
                     if host_ok(h["name"])]
            params = {"output": ["triggerid", "description", "priority", "lastchange", "value"],
                      "selectHosts": ["hostid", "name"], "filter": {"value": 1}, "monitored": True,
                      "skipDependent": True, "expandDescription": True, "sortfield": "lastchange",
                      "sortorder": "DESC", "limit": 2000,
                      "min_severity": int((target.get("options") or {}).get("minSeverity", 0))}
            if not hosts:
                return QueryResult([problems_table([], ref_id, int(ctx.end.timestamp() * 1000))],
                                   ["Filtreyle eşleşen host yok"])
            params["hostids"] = hosts
            text_ok = compile_filter((target.get("trigger") or {}).get("filter", ""))
            triggers = [t for t in self.api.call("trigger.get", params) if text_ok(t.get("description", ""))]
            return QueryResult([problems_table(triggers, ref_id, int(ctx.end.timestamp() * 1000))])
        if mode == "itemid":
            ids = [i.strip() for i in str(target.get("itemids", "")).split(",") if i.strip()]
            if not ids or not all(i.isdigit() for i in ids) or len(ids) > self.max_items:
                raise DataSourceError("Item ID modu virgülle ayrılmış sayısal item ID'leri ister")
            rows = self.api.call("item.get", {"itemids": ids, "output": ["itemid", "hostid", "name", "key_", "units",
                                 "value_type", "status", "delay", "lastvalue", "lastclock"],
                                 "selectHosts": ["hostid", "host", "name"]})
            items = [{**r, "itemid": str(r["itemid"]), "hostid": str(r["hostid"])} for r in rows
                     if str(r.get("value_type")) in NUMERIC]
            host_map = {}
            for r in rows:
                for h in r.get("hosts", []):
                    host_map[str(h["hostid"])] = {**h, "hostid": str(h["hostid"])}
            missing = set(ids) - {i["itemid"] for i in items}
            if missing:
                warnings.append(f"Bulunamayan veya sayısal olmayan item: {', '.join(sorted(missing))}")
        else:
            items, host_map, notes = self.inventory.resolve(
                target, numeric_only=mode == "metrics", max_items=self.max_items,
                include_disabled=bool(target["options"].get("showDisabledItems")))
            warnings.extend(notes)
            if mode == "itemvalues":
                return QueryResult([value_table(items, host_map, ref_id)], warnings)
        if not items:
            return QueryResult([], warnings)
        start = ctx.start.timestamp()
        end = ctx.end.timestamp()
        trends = self._use_trends(target["options"]["mode"], ctx)
        column = query_option(target["functions"], "trendValue", "avg")
        consolidate = query_option(target["functions"], "consolidateBy", "avg")
        max_rows = max(10_000, int(ctx.max_series_points))
        if self.options.get("history_source") == "sql":
            points = self._history_sql(items, start, end, ctx.interval_s, trends, column, consolidate,
                                       ctx.anchor_ms // 1000)
            resolution = "sql_trends" if trends else "sql_history"
        elif trends:
            points = self._trends_api(items, start, end, max_rows, column)
            resolution = "trends"
        else:
            points = self._history_api(items, start, end, max_rows)
            resolution = "history"
        frames = items_to_frames(items, host_map, points, ref_id, resolution, ctx.interval_ms, ctx.max_points,
                                 consolidate, ctx.anchor_ms)
        empty = [f["labels"]["host"] for f in frames if not f["points"]]
        if empty:
            warnings.append(f"{len(empty)} seri için seçilen aralıkta veri yok (NO DATA)")
        return QueryResult(frames, warnings, {"resolution": resolution, "items": len(items)})

    def metric_find(self, query, ctx=None):
        return find_values(self.inventory, query)

    def health(self):
        version = self.api.call("apiinfo.version", {})
        groups = self.api.call("hostgroup.get", {"output": ["groupid"], "limit": 1})
        return {"status": "ok", "message": f"Zabbix API {version} bağlantısı başarılı; "
                                           f"{'host grupları okunabiliyor' if groups else 'görünür host grubu yok'}"}
