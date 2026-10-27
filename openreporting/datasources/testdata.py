"""Synthetic TestData datasource (like Grafana's TestData DB).

Clearly labelled synthetic data for learning the UI, building dashboard
templates and testing report layouts before a real Zabbix is connected. The
"Zabbix simülasyonu" scenario mimics groups, hosts, items and tags so the very
same query editor and group functions can be exercised end to end. Values are a
deterministic function of time: refreshing never changes history.
"""
import hashlib
import math
import time

from ..frames import table_frame, ts_frame
from ..series_functions import query_option
from ..timerange import parse_duration
from .base import DataSource, DataSourceError, QueryResult, bucket_average
from .zabbix import (InventoryResolver, find_values, items_to_frames, normalize_target,
                     problems_table, value_table)

SCENARIOS = {
    "zabbix_sim": "Zabbix simülasyonu (grup/host/item)",
    "random_walk": "Rastgele yürüyüş",
    "sine": "Sinüs dalgası",
    "csv_values": "CSV değerleri",
    "table_static": "Örnek tablo",
}

_ITEM_TEMPLATES = {
    "server": [
        ("CPU utilization", "system.cpu.util", "%", 0, 60, ("component", "cpu"), (22, 18, 6)),
        ("Memory utilization", "vm.memory.utilization", "%", 0, 60, ("component", "memory"), (55, 10, 3)),
        ("Load average (1m avg)", "system.cpu.load[all,avg1]", "", 0, 60, ("component", "cpu"), (1.4, 1.0, 0.3)),
        ("/: Space utilization", "vfs.fs.dependent.size[/,pused]", "%", 0, 300, ("component", "storage"), (62, 4, 0.5)),
        ("Interface eth0: Bits received", "net.if.in[\"eth0\"]", "bps", 3, 60, ("component", "network"), (4.2e7, 3.0e7, 6e6)),
        ("Interface eth0: Bits sent", "net.if.out[\"eth0\"]", "bps", 3, 60, ("component", "network"), (2.1e7, 1.5e7, 4e6)),
        ("ICMP response time", "icmppingsec", "s", 0, 60, ("component", "health"), (0.0021, 0.0012, 0.0006)),
        ("ICMP loss", "icmppingloss", "%", 0, 60, ("component", "health"), (0.3, 0.6, 0.6)),
        ("System uptime", "system.uptime", "uptime", 3, 300, ("component", "system"), (0, 0, 0)),
    ],
    "network": [
        ("CPU utilization", "system.cpu.util[snmp]", "%", 0, 60, ("component", "cpu"), (18, 12, 4)),
        ("Memory utilization", "vm.memory.util[snmp]", "%", 0, 60, ("component", "memory"), (41, 6, 1.5)),
        ("Temperature", "sensor.temp.value[snmp]", "C", 0, 300, ("component", "environment"), (39, 4, 0.8)),
        ("Interface Gi0/1(Uplink-A): Bits received", "net.if.in[ifHCInOctets.1]", "bps", 3, 60, ("interface", "Gi0/1"), (6.5e8, 4e8, 7e7)),
        ("Interface Gi0/1(Uplink-A): Bits sent", "net.if.out[ifHCOutOctets.1]", "bps", 3, 60, ("interface", "Gi0/1"), (3.8e8, 2.5e8, 5e7)),
        ("Interface Gi0/2(Uplink-B): Bits received", "net.if.in[ifHCInOctets.2]", "bps", 3, 60, ("interface", "Gi0/2"), (2.4e8, 1.8e8, 3e7)),
        ("Interface Gi0/2(Uplink-B): Bits sent", "net.if.out[ifHCOutOctets.2]", "bps", 3, 60, ("interface", "Gi0/2"), (1.6e8, 1.1e8, 2e7)),
        ("ICMP response time", "icmppingsec", "s", 0, 60, ("component", "health"), (0.0045, 0.002, 0.001)),
        ("ICMP loss", "icmppingloss", "%", 0, 60, ("component", "health"), (0.2, 0.4, 0.5)),
        ("System uptime", "system.hw.uptime[snmp]", "uptime", 3, 300, ("component", "system"), (0, 0, 0)),
    ],
    "firewall": [
        ("CPU utilization", "system.cpu.util[fw]", "%", 0, 60, ("component", "cpu"), (35, 20, 6)),
        ("Memory utilization", "vm.memory.util[fw]", "%", 0, 60, ("component", "memory"), (63, 8, 2)),
        ("Active sessions", "fw.sessions.active", "", 3, 60, ("component", "security"), (48000, 30000, 4000)),
        ("Throughput", "fw.throughput", "bps", 3, 60, ("component", "network"), (9.5e8, 6e8, 9e7)),
        ("ICMP response time", "icmppingsec", "s", 0, 60, ("component", "health"), (0.003, 0.0015, 0.0008)),
    ],
}
_GROUPS = [
    ("101", "Linux servers", "server", ["srv-app-01", "srv-app-02", "srv-app-03", "srv-db-01", "srv-db-02",
                                        "srv-web-01", "srv-web-02", "srv-web-03"]),
    ("102", "Network Core", "network", ["core-sw-ist-01", "core-sw-ist-02", "core-rtr-ist-01", "core-rtr-ank-01"]),
    ("103", "Datacenter Switches", "network", [f"dc-sw-{n:02d}" for n in range(1, 11)]),
    ("104", "Firewalls", "firewall", ["fw-ist-01", "fw-ank-01", "fw-izm-01"]),
    ("105", "WAN Routers", "network", ["wan-rtr-ist", "wan-rtr-ank", "wan-rtr-izm", "wan-rtr-ant", "wan-rtr-bur"]),
]
# Deliberate realism: one host lacks an item, one host has an outage window.
_MISSING_ITEM = ("srv-db-02", "net.if.out[\"eth0\"]")
_OUTAGE_HOST = "dc-sw-07"


def _seed(*parts):
    digest = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _noise(seed, index):
    """Deterministic pseudo-random value in [-1, 1] for (seed, bucket)."""
    return (_seed(seed, index) % 20001) / 10000 - 1


def _smooth(seed, t):
    phase1 = (seed % 628) / 100
    phase2 = ((seed >> 10) % 628) / 100
    daily = math.sin(2 * math.pi * (t % 86400) / 86400 - math.pi / 2 + phase1 * 0.15)
    hourly = math.sin(2 * math.pi * t / (3 * 3600) + phase2)
    weekly = math.sin(2 * math.pi * t / (7 * 86400) + phase1)
    return 0.65 * daily + 0.2 * hourly + 0.15 * weekly


def _inventory():
    groups, hosts, items = [], {}, []
    hostid = 10100
    for groupid, group_name, kind, names in _GROUPS:
        groups.append({"groupid": groupid, "name": group_name})
        for name in names:
            if name not in hosts:
                hostid += 1
                hosts[name] = {"hostid": str(hostid), "host": name, "name": name, "status": "0",
                               "_groupids": [], "_kind": kind}
            hosts[name]["_groupids"].append(groupid)
    for host in hosts.values():
        for index, (item_name, key, units, value_type, delay, tag, shape) in enumerate(_ITEM_TEMPLATES[host["_kind"]]):
            if (host["name"], key) == _MISSING_ITEM:
                continue
            items.append({"itemid": f"{host['hostid']}{index:03d}", "hostid": host["hostid"], "name": item_name,
                          "key_": key, "units": units, "value_type": str(value_type), "status": "0",
                          "delay": f"{delay}s", "tags": [{"tag": tag[0], "value": tag[1]}],
                          "_shape": shape, "_delay": delay})
    return groups, hosts, items


GROUPS, HOSTS, ITEMS = _inventory()
HOSTS_BY_ID = {h["hostid"]: h for h in HOSTS.values()}


def item_value(item, t):
    host = HOSTS_BY_ID[item["hostid"]]
    if host["name"] == _OUTAGE_HOST and (t // 3600) % 48 in (20, 21, 22):
        return None
    base, amplitude, jitter = item["_shape"]
    seed = _seed(item["itemid"])
    if item["key_"].startswith(("system.uptime", "system.hw.uptime")):
        boot = 86400 * (5 + seed % 90)
        return float(t % (boot * 2) + 3600)
    host_bias = 0.6 + (seed % 900) / 1000
    value = base * host_bias + amplitude * _smooth(seed, t) + jitter * _noise(seed, int(t // max(60, item["_delay"])))
    if item["units"] == "%":
        value = min(100.0, max(0.0, value))
    elif item["key_"] == "icmppingloss":
        value = max(0.0, value)
    else:
        value = max(0.0, value)
    return round(value, 6) if item["value_type"] == "0" else float(round(value))


class _SimInventory(InventoryResolver):
    def groups(self):
        return [dict(g) for g in GROUPS]

    def hosts(self, groupids):
        wanted = set(groupids)
        return [dict(h) for h in HOSTS.values() if wanted & set(h["_groupids"])]

    def items(self, hostids):
        wanted = set(hostids)
        result = []
        now = int(time.time())
        for item in ITEMS:
            if item["hostid"] in wanted:
                last_clock = now // item["_delay"] * item["_delay"]
                value = item_value(item, last_clock)
                result.append({**item, "lastvalue": "" if value is None else str(value),
                               "lastclock": str(last_clock if value is not None else 0)})
        return result


def _series_points(item, start, end, step):
    step = max(step, item["_delay"])
    first = int(math.ceil(start / step) * step)
    return [[t * 1000, item_value(item, t)] for t in range(first, int(end), int(step))]


class TestDataSource(DataSource):
    type = "testdata"
    default_format = "zabbix"

    def __init__(self, record, secure, settings, **_):
        super().__init__(record, secure, settings)
        self.inventory = _SimInventory()

    def query(self, target, ctx):
        scenario = target.get("scenario") or "zabbix_sim"
        ref_id = target.get("refId", "A")
        start, end = ctx.start.timestamp(), ctx.end.timestamp()
        step = max(1, ctx.interval_s)
        if (end - start) / step > 20000:
            raise DataSourceError("Too many synthetic points requested")
        if scenario == "zabbix_sim":
            normalized = normalize_target(target)
            mode = normalized["queryType"]
            if mode == "problems":
                triggers = []
                for host in self.inventory.hosts(tuple(g["groupid"] for g in GROUPS)):
                    for item in ITEMS:
                        if item["hostid"] != host["hostid"] or not item["units"] == "%":
                            continue
                        value = item_value(item, int(end) // 60 * 60)
                        if value is not None and value > 85:
                            triggers.append({"description": f"{item['name']} yüksek (>85%)", "priority": "4",
                                             "lastchange": str(int(end) - 1800), "hosts": [host]})
                return QueryResult([problems_table(triggers, ref_id, int(end * 1000))], [], {"synthetic": True})
            items, host_map, notes = self.inventory.resolve(normalized, numeric_only=mode != "itemvalues",
                                                            max_items=2000)
            if mode == "itemvalues":
                return QueryResult([value_table(items, host_map, ref_id)], notes)
            points = {item["itemid"]: _series_points(item, start, end, step) for item in items}
            frames = items_to_frames(items, host_map, points, ref_id, "synthetic", ctx.interval_ms,
                                     ctx.max_points, query_option(normalized["functions"], "consolidateBy", "avg"),
                                     ctx.anchor_ms)
            return QueryResult(frames, notes, {"synthetic": True})
        count = max(1, min(int(target.get("seriesCount", 1) or 1), 50))
        frames = []
        for index in range(count):
            seed = _seed(self.uid, ref_id, scenario, index, target.get("alias", ""))
            name = (target.get("alias") or f"{scenario}-{index + 1}").replace("$seriesIndex", str(index + 1))
            first = int(math.ceil(start / step) * step)
            stamps = range(first, int(end), int(step))
            if scenario == "random_walk":
                low = float(target.get("min", 0) or 0)
                high = float(target.get("max", 100) or 100)
                mid = (low + high) / 2
                spread = (high - low) / 2
                pts = [[t * 1000, round(min(high, max(low, mid + spread * (0.75 * _smooth(seed, t) +
                                                                          0.25 * _noise(seed, t // step)))), 3)]
                       for t in stamps]
            elif scenario == "sine":
                amplitude = float(target.get("amplitude", 10) or 10)
                period = parse_duration(target.get("period", "1h"))
                offset_value = float(target.get("offset", 0) or 0)
                pts = [[t * 1000, round(offset_value + amplitude * math.sin(2 * math.pi * t / period + index), 4)]
                       for t in stamps]
            elif scenario == "csv_values":
                raw = [v.strip() for v in str(target.get("csvValues", "1,20,90,30,5,0")).split(",")]
                values = [None if v.lower() in ("null", "") else float(v) for v in raw][:10000]
                if not values:
                    raise DataSourceError("CSV values are empty")
                span = (end - start) / max(1, len(values) - 1)
                pts = [[int((start + i * span) * 1000), v] for i, v in enumerate(values)]
            elif scenario == "table_static":
                rows = [[h["name"], GROUPS[[g["groupid"] for g in GROUPS].index(h["_groupids"][0])]["name"],
                         h["hostid"]] for h in HOSTS.values()]
                return QueryResult([table_frame("Envanter", ["Host", "Grup", "Host ID"], rows, ref_id=ref_id)])
            else:
                raise DataSourceError(f"Unknown TestData scenario: {scenario}")
            frames.append(ts_frame(name, bucket_average(pts, ctx.interval_ms) if len(pts) > ctx.max_points else pts,
                                   labels={"series": str(index + 1)}, unit=target.get("unit", ""), ref_id=ref_id,
                                   meta={"synthetic": True}))
        return QueryResult(frames, [], {"synthetic": True})

    def metric_find(self, query, ctx=None):
        return find_values(self.inventory, query)

    def health(self):
        return {"status": "ok", "message": f"Sentetik veri kaynağı hazır: {len(GROUPS)} grup, {len(HOSTS)} host, "
                                           f"{len(ITEMS)} item (gerçek veri değildir)."}
