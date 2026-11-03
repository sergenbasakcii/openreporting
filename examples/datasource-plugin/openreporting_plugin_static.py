"""Example OpenReporting datasource plugin: a static table configured in the datasource settings.

Shows the complete contract: type id equal to the entry point name, display metadata, secure
fields, configuration validation and query/health methods returning platform frames.
"""

from openreporting.datasources.base import DataSource, DataSourceError, QueryResult
from openreporting.frames import table_frame

MAX_ROWS = 1000


class StaticTableDataSource(DataSource):
    type = "x-static-table"
    display_name = "Statik tablo (örnek eklenti)"
    description = "Ayarlarda tanımlanan sabit tabloyu döndürür; eklenti geliştirme örneğidir"
    secure_fields = []

    @classmethod
    def validate_config(cls, url, json_data, settings):
        columns = json_data.get("columns") or []
        rows = json_data.get("rows") or []
        if not isinstance(columns, list) or not all(isinstance(c, str) and c for c in columns) or not 1 <= len(columns) <= 50:
            raise DataSourceError("columns: 1-50 sütun adı listesi olmalı")
        if not isinstance(rows, list) or len(rows) > MAX_ROWS or any(not isinstance(r, list) or len(r) != len(columns) for r in rows):
            raise DataSourceError(f"rows: her satır {len(columns)} değer içermeli (en fazla {MAX_ROWS} satır)")
        return "", {"columns": columns, "rows": rows}

    def query(self, target, ctx):
        columns = self.options.get("columns") or []
        return QueryResult(frames=[table_frame(self.name, columns, self.options.get("rows") or [], ref_id=target.get("refId", "A"))])

    def health(self):
        return {"status": "ok", "message": f"Statik tablo hazır: {len(self.options.get('rows') or [])} satır"}
