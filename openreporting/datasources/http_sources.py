"""Read-only HTTP sources with fixed origins, bounded responses and verified TLS."""
import csv
import io
import json
import ssl
import http.client
import ipaddress
from urllib.parse import urlsplit, urlencode

from .base import DataSource, DataSourceError, QueryResult
from ..frames import ts_frame, table_frame, finite

MAX_BYTES = 8_000_000

def validate_http_url(url, allow_http=False):
    try:
        p = urlsplit(url)
        if p.scheme not in (("https", "http") if allow_http else ("https",)) or not p.hostname or p.username or p.password or p.fragment or p.query:
            raise ValueError()
        _ = p.port
    except ValueError:
        raise DataSourceError("Geçerli HTTPS adresi gerekli; URL içinde parola, sorgu veya fragment kullanmayın") from None
    return url

def safe_peer(address):
    ip = ipaddress.ip_address(address.split("%")[0])
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified or str(ip) == "fd00:ec2::254" or (getattr(ip, "ipv4_mapped", None) and not safe_peer(str(ip.ipv4_mapped))):
        raise DataSourceError("Metadata/link-local adreslerine erişim engellendi")
    return True

class SafeHTTPS(http.client.HTTPSConnection):
    def connect(self):
        super().connect()
        safe_peer(self.sock.getpeername()[0])

class SafeHTTP(http.client.HTTPConnection):
    def connect(self):
        super().connect()
        safe_peer(self.sock.getpeername()[0])

class HTTPSource(DataSource):
    def fetch(self, suffix="", params=None):
        base = urlsplit(validate_http_url(self.url, self.settings.allow_http_datasources))
        # Targets cannot choose a URL, host or path; only the saved admin origin is used.
        path = base.path.rstrip("/") + suffix if suffix else base.path
        if params:
            path += "?" + urlencode(params)
        headers = {"Accept": "application/json,text/csv", "Accept-Encoding": "identity"}
        token = self.secure.get("token")
        if token:
            if any(ord(c) < 32 for c in token):
                raise DataSourceError("Geçersiz erişim anahtarı")
            headers["Authorization"] = "Bearer " + token
        cls = SafeHTTPS if base.scheme == "https" else SafeHTTP
        kwargs = {"timeout": self.options.get("timeout", 30)}
        if base.scheme == "https":
            ctx = ssl.create_default_context()
            if self.options.get("ca_pem"):
                ctx.load_verify_locations(cadata=self.options["ca_pem"])
            kwargs["context"] = ctx
        conn = cls(base.hostname, base.port, **kwargs)
        try:
            conn.request("GET", path or "/", headers=headers)
            response = conn.getresponse()
            if response.status != 200:
                raise DataSourceError(f"Veri kaynağı HTTP {response.status}; yönlendirme izlenmez")
            body = response.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                raise DataSourceError("HTTP yanıtı 8 MB sınırını aştı")
            return body.decode("utf-8-sig")
        except DataSourceError:
            raise
        except (OSError, ValueError, http.client.HTTPException, UnicodeError):
            raise DataSourceError("Veri kaynağı okunamadı; bağlantı, TLS ve yanıt biçimini kontrol edin") from None
        finally:
            conn.close()

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
            numeric = bool(present) and all(not isinstance(v, (dict, list, bool)) and finite(v) is not None for v in present)
            columns.append({"name": str(k), "type": "number" if numeric else "string"})
        for record in records:
            rows.append([finite(record.get(k)) if c["type"] == "number" else (None if record.get(k) is None else str(record[k])) for k, c in zip(keys, columns)])
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
            params.update(start=str(int(ctx.start.timestamp()*1e9)), end=str(int(ctx.end.timestamp()*1e9)), limit=min(self.settings.max_rows, 5000), direction="forward")
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
                    rows.append([int(timestamp)//1_000_000, line, json.dumps(stream.get("stream", {}), ensure_ascii=False)])
            if len(rows) >= params["limit"]:
                raise DataSourceError("Log satır sınırına ulaşıldı; zaman aralığını daraltın")
            return QueryResult([table_frame(self.name, [{"name":"time","type":"time"},"line","labels"], sorted(rows), ref_id=target.get("refId", ""))])
        if data.get("resultType") != "matrix":
            raise DataSourceError("Kaynak zaman serisi matrisi döndürmelidir")
        for item in result:
            points = [[int(float(t)*1000), finite(v)] for t, v in item.get("values", [])]
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
