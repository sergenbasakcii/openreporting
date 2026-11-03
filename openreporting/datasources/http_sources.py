"""Read-only HTTP sources with fixed origins, bounded responses and verified TLS."""

import csv
import io
import json
import re
import ssl
import http.client
import ipaddress
import time
from urllib.parse import urlsplit, urlencode

from .base import DataSource, DataSourceError, QueryResult
from ..frames import ts_frame, table_frame, finite

MAX_BYTES = 8_000_000
# Plain decimal without leading zeros (identifiers like "007", "0532..." and "1e3" stay text).
DECIMAL = re.compile(r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$")


def _numeric(value):
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return finite(value) is not None
    return isinstance(value, str) and bool(DECIMAL.match(value.strip()))


def validate_http_url(url, allow_http=False):
    try:
        p = urlsplit(url)
        if p.scheme not in (("https", "http") if allow_http else ("https",)) or not p.hostname or p.username or p.password or p.fragment or p.query:
            raise ValueError()
        _ = p.port
    except ValueError:
        raise DataSourceError("Geçerli HTTPS adresi gerekli; URL içinde parola, sorgu veya fragment kullanmayın") from None
    return url


# Cloud metadata / host agent endpoints outside the link-local range.
METADATA_ADDRESSES = {ipaddress.ip_address(a) for a in ("100.100.100.200", "168.63.129.16", "fd00:ec2::254")}
NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _embedded_ipv4(ip):
    """IPv4 address carried inside an IPv6 address (mapped, NAT64, 6to4, Teredo), if any."""
    if ip.version != 6:
        return None
    if ip.ipv4_mapped:
        return ip.ipv4_mapped
    if ip in NAT64:
        return ipaddress.ip_address(int(ip) & 0xFFFFFFFF)
    if ip.sixtofour:
        return ip.sixtofour
    if ip.teredo:
        return ip.teredo[1]
    return None


def safe_peer(address, allow_loopback=False):
    ip = ipaddress.ip_address(address.split("%")[0])
    inner = _embedded_ipv4(ip)
    if inner is not None:
        return safe_peer(str(inner), allow_loopback)
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip in METADATA_ADDRESSES:
        raise DataSourceError("Metadata/link-local adreslerine erişim engellendi")
    if ip.is_loopback and not allow_loopback:
        # The server's own services (this API, its database, /metrics) are not data sources by default.
        raise DataSourceError("Sunucunun kendi adresine (localhost) erişim kapalı; gerekiyorsa OPENREPORTING_ALLOW_LOOPBACK_DATASOURCES=true")
    return True


class SafeHTTPS(http.client.HTTPSConnection):
    allow_loopback = False

    def connect(self):
        super().connect()
        safe_peer(self.sock.getpeername()[0], self.allow_loopback)


class SafeHTTP(http.client.HTTPConnection):
    allow_loopback = False

    def connect(self):
        super().connect()
        safe_peer(self.sock.getpeername()[0], self.allow_loopback)


def clean_header(value, what="erişim bilgisi"):
    """Header values come from admin config/secrets: refuse control characters (header injection)."""
    value = str(value)
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise DataSourceError(f"Geçersiz {what}")
    return value


class HTTPSource(DataSource):
    def auth_headers(self):
        """Default: optional bearer token. Sources with other schemes override this."""
        token = self.secure.get("token")
        return {"Authorization": "Bearer " + clean_header(token, "erişim anahtarı")} if token else {}

    def same_origin_path(self, url):
        """Follow-up URL returned by the server (paging, async results): must stay on the saved origin."""
        base = urlsplit(validate_http_url(self.url, self.settings.allow_http_datasources))
        target = urlsplit(url)
        if (target.scheme, target.hostname, target.port) != (base.scheme, base.hostname, base.port) or target.username or target.password:
            raise DataSourceError("Kaynak başka bir adrese yönlendirdi; izlenmedi")
        return target.path + ("?" + target.query if target.query else "")

    def fetch(self, suffix="", params=None, *, method="GET", body=None, headers=None, raw_path=None, ok=(200,)):
        base = urlsplit(validate_http_url(self.url, self.settings.allow_http_datasources))
        # Targets cannot choose a URL, host or path; only the saved admin origin is used.
        if raw_path is not None:
            path = raw_path
        else:
            path = base.path.rstrip("/") + suffix if suffix else base.path
            if params:
                path += "?" + urlencode(params)
        headers = {"Accept": "application/json,text/csv", "Accept-Encoding": "identity", **self.auth_headers(), **(headers or {})}
        if isinstance(body, str):
            body = body.encode("utf-8")
        cls = SafeHTTPS if base.scheme == "https" else SafeHTTP
        kwargs = {"timeout": self.options.get("timeout", 30)}
        if base.scheme == "https":
            ctx = ssl.create_default_context()
            if self.options.get("ca_pem"):
                ctx.load_verify_locations(cadata=self.options["ca_pem"])
            kwargs["context"] = ctx
        conn = cls(base.hostname, base.port, **kwargs)
        conn.allow_loopback = bool(getattr(self.settings, "allow_loopback_datasources", False))
        # The socket timeout is per operation; a slow-drip server is bounded by a total deadline too.
        deadline = time.monotonic() + float(kwargs["timeout"]) * 2
        try:
            conn.request(method, path or "/", body=body, headers=headers)
            response = conn.getresponse()
            if response.status not in ok:
                raise DataSourceError(self.http_error(response))
            chunks, size = [], 0
            while True:
                if time.monotonic() > deadline:
                    raise DataSourceError("Veri kaynağı yanıtı zaman aşımına uğradı")
                chunk = response.read(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_BYTES:
                    raise DataSourceError("HTTP yanıtı 8 MB sınırını aştı")
                chunks.append(chunk)
            return b"".join(chunks).decode("utf-8-sig")
        except DataSourceError:
            raise
        except (OSError, ValueError, http.client.HTTPException, UnicodeError):
            raise DataSourceError("Veri kaynağı okunamadı; bağlantı, TLS ve yanıt biçimini kontrol edin") from None
        finally:
            conn.close()

    def http_error(self, response):
        # Only the status is shown: response bodies can echo credentials or internal details.
        if response.status in (401, 403):
            return f"Veri kaynağı erişimi reddetti (HTTP {response.status}); kullanıcı/anahtar ve yetkileri kontrol edin"
        return f"Veri kaynağı HTTP {response.status}; yönlendirme izlenmez"

    def health(self):
        if self.type in ("httpjson", "csv"):
            self.read_table()
        else:
            self.fetch("/api/v1/status/buildinfo" if self.type == "prometheus" else "/ready")
        return {"status": "ok", "message": "Salt-okunur bağlantı başarılı"}

    def read_table(self):
        text = self.fetch()
        if self.type == "csv":
            reader = csv.DictReader(io.StringIO(text))
            records = []
            for row in reader:
                if len(records) >= self.settings.max_rows:
                    raise DataSourceError("Satır sınırı aşıldı")
                records.append(row)
        else:
            try:
                records = json.loads(text)
                for part in self.options.get("root", "").split("."):
                    if part:
                        records = records[part]
            except (ValueError, TypeError, KeyError):
                raise DataSourceError("JSON kök alanı bulunamadı veya JSON geçersiz") from None
        if not isinstance(records, list) or any(not isinstance(r, dict) for r in records):
            raise DataSourceError("JSON verisi nesne listesi olmalı; kök alanını ayarlayın")
        if len(records) > self.settings.max_rows:
            raise DataSourceError("Satır sınırı aşıldı")
        keys = list(dict.fromkeys(k for r in records for k in r))
        if len(keys) > 200:
            raise DataSourceError("En fazla 200 sütun desteklenir")
        columns, rows = [], []
        for k in keys:
            present = [r[k] for r in records if r.get(k) not in (None, "")]
            numeric = bool(present) and all(_numeric(v) for v in present)
            columns.append({"name": str(k), "type": "number" if numeric else "string"})
        for record in records:
            rows.append(
                [finite(record.get(k)) if c["type"] == "number" else (None if record.get(k) is None else str(record[k])) for k, c in zip(keys, columns)]
            )
        return table_frame(self.name, columns, rows)

    def query(self, target, ctx):
        if self.type in ("httpjson", "csv"):
            frame = self.read_table()
            frame["refId"] = target.get("refId", "")
            return QueryResult([frame])
        expression = str(target.get("expr") or "").strip()
        if not expression or len(expression) > 16000:
            raise DataSourceError("PromQL/LogQL sorgusu gerekli (en fazla 16000 karakter)")
        params = {"query": expression, "step": max(1, ctx.interval_s)}
        if self.type == "prometheus":
            params.update(start=ctx.start.timestamp(), end=ctx.end.timestamp())
            text = self.fetch("/api/v1/query_range", params)
        else:
            params.update(
                start=str(int(ctx.start.timestamp() * 1e9)),
                end=str(int(ctx.end.timestamp() * 1e9)),
                limit=min(self.settings.max_rows, 5000),
                direction="forward",
            )
            text = self.fetch("/loki/api/v1/query_range", params)
        try:
            payload = json.loads(text)
            if not isinstance(payload, dict):
                raise ValueError()
        except ValueError:
            raise DataSourceError("Kaynak geçerli JSON yanıtı döndürmedi") from None
        if payload.get("status") != "success":
            raise DataSourceError("Sorgu başarısız; sorgu ifadesini kontrol edin")
        data = payload.get("data", {})
        result = data.get("result", [])
        warnings = payload.get("warnings", [])
        if warnings:
            raise DataSourceError("Kaynak kısmi veri/uyarı döndürdü; sorguyu daraltın")
        frames, count = [], 0
        if data.get("resultType") == "streams":
            rows = []
            for stream in result:
                for timestamp, line in stream.get("values", []):
                    rows.append([int(timestamp) // 1_000_000, line, json.dumps(stream.get("stream", {}), ensure_ascii=False)])
            if len(rows) >= params["limit"]:
                raise DataSourceError("Log satır sınırına ulaşıldı; zaman aralığını daraltın")
            return QueryResult([table_frame(self.name, [{"name": "time", "type": "time"}, "line", "labels"], sorted(rows), ref_id=target.get("refId", ""))])
        if data.get("resultType") != "matrix":
            raise DataSourceError("Kaynak zaman serisi matrisi döndürmelidir")
        for item in result:
            points = [[int(float(t) * 1000), finite(v)] for t, v in item.get("values", [])]
            count += len(points)
            if count > ctx.max_series_points:
                raise DataSourceError("Nokta bütçesi aşıldı; zaman aralığını veya seri sayısını azaltın")
            labels = item.get("metric", {})
            name = str(target.get("alias") or labels.get("__name__") or json.dumps(labels, ensure_ascii=False))
            frames.append(ts_frame(name, points, labels=labels, ref_id=target.get("refId", "")))
        return QueryResult(frames)


class PrometheusDataSource(HTTPSource):
    type = "prometheus"
    default_format = "promql"


class LokiDataSource(HTTPSource):
    type = "loki"
    default_format = "promql"


class JSONDataSource(HTTPSource):
    type = "httpjson"


class CSVDataSource(HTTPSource):
    type = "csv"
