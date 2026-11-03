// Query editors for the data lake / SQL engines (Trino, Databricks, ClickHouse) and the search and
// time-series stores (Elasticsearch / OpenSearch, InfluxDB, Graphite).
import { h, input, select, textarea, field } from '../dom.js';

const SQL_EXAMPLES = {
  trino: "SELECT\n  date_trunc('minute', event_time) AS time,\n  count(*) AS value\nFROM hive.web.access_logs\nWHERE $__timeFilter(event_time)\nGROUP BY 1\nORDER BY 1",
  databricks: "SELECT\n  date_trunc('MINUTE', event_time) AS time,\n  count(*) AS value\nFROM main.default.events\nWHERE $__timeFilter(event_time)\nGROUP BY 1\nORDER BY 1",
  clickhouse: 'SELECT\n  $__timeGroup(ts, $__interval) AS time,\n  count() AS value\nFROM logs\nWHERE $__timeFilter(ts)\nGROUP BY time\nORDER BY time',
};
const SQL_HINTS = {
  trino: 'Katalog.şema.tablo adlarıyla veri gölündeki (Hive, Iceberg, Delta) tabloları sorgulayın.',
  databricks: 'Unity Catalog adlarıyla (katalog.şema.tablo) Delta tablolarını sorgulayın.',
  clickhouse: 'Sorgu sunucuda readonly ayarıyla ve satır sınırıyla çalışır.',
};

function sqlEngineEditor(target, ds, onChange) {
  const t = { ...target };
  const set = (patch) => { Object.assign(t, patch); onChange({ ...t }); };
  const sql = textarea({ value: t.rawSql || SQL_EXAMPLES[ds.type], rows: 8, class: 'code-editor', label: 'SQL sorgusu', onChange: (e) => set({ rawSql: e.target.value }) });
  if (!t.rawSql) setTimeout(() => set({ rawSql: sql.value }), 0);
  return h('div',
    h('div', { class: 'q-line' }, h('span', { class: 'q-label', text: 'Biçim' }),
      select([{ value: 'time_series', label: 'Zaman serisi' }, { value: 'table', label: 'Tablo' }], t.format || 'time_series', (v) => set({ format: v }), { label: 'Sorgu sonuç biçimi' })),
    sql,
    h('p', { class: 'hint' }, `${SQL_HINTS[ds.type]} Makrolar: $__timeFilter(sütun), $__timeGroup(sütun, 5m), $__timeFrom(), $__timeTo(), $__interval_s. `,
      'Zaman serisi için "time" sütunu, isteğe bağlı "metric" sütunu ve sayısal değer sütunları döndürün. Yalnızca tek bir SELECT / WITH sorgusuna izin verilir.'));
}

const METRICS = [
  { value: 'count', label: 'Kayıt sayısı' }, { value: 'avg', label: 'Ortalama' }, { value: 'sum', label: 'Toplam' },
  { value: 'min', label: 'En küçük' }, { value: 'max', label: 'En büyük' }, { value: 'cardinality', label: 'Benzersiz sayı' },
];

function elasticsearchEditor(target, ds, onChange) {
  const t = { mode: 'metrics', metric: 'count', ...target };
  const set = (patch) => { Object.assign(t, patch); onChange({ ...t }); };
  const wrap = h('div');
  const rerender = () => wrap.replaceWith(elasticsearchEditor(t, ds, onChange));
  const text = (key, label, placeholder) => field(label, input({ value: t[key] || '', placeholder, onChange: (e) => set({ [key]: e.target.value }) }));
  wrap.append(
    h('div', { class: 'form-grid' },
      text('index', 'İndeks deseni', ds.jsonData?.index || 'logs-*'),
      field('Görünüm', select([{ value: 'metrics', label: 'Metrik (zaman histogramı)' }, { value: 'logs', label: 'Log kayıtları (son 500)' }], t.mode, (v) => { set({ mode: v }); rerender(); }))),
    field('Sorgu (Lucene)', input({ value: t.query || '', placeholder: 'level:error AND service:checkout', onChange: (e) => set({ query: e.target.value }) }), 'Boş bırakılırsa zaman aralığındaki tüm kayıtlar.'));
  if (t.mode !== 'logs') {
    wrap.append(h('div', { class: 'form-grid' },
      field('Metrik', select(METRICS, t.metric, (v) => { set({ metric: v }); rerender(); })),
      t.metric !== 'count' ? text('field', 'Alan', 'latency_ms') : null,
      text('groupBy', 'Gruba ayır (isteğe bağlı)', 'host.keyword'),
      field('En çok grup', input({ type: 'number', value: t.size || 10, min: 1, max: 50, onChange: (e) => set({ size: Number(e.target.value) }) })),
      text('alias', 'Seri adı (isteğe bağlı)', '')));
  }
  return wrap;
}

function influxEditor(target, onChange) {
  const t = { ...target };
  return h('div',
    field('InfluxQL', textarea({ value: t.query || 'SELECT mean("usage_user") FROM "cpu" WHERE $timeFilter GROUP BY time($__interval), "host"', rows: 4, class: 'code-editor',
      onChange: (e) => onChange({ ...t, query: e.target.value }) })),
    field('Seri adı (isteğe bağlı)', input({ value: t.alias || '', onChange: (e) => onChange({ ...t, alias: e.target.value }) })),
    h('p', { class: 'hint', text: '$timeFilter seçili zaman aralığını, $__interval otomatik aralığı ekler. Yalnızca SELECT ve SHOW sorguları çalışır.' }));
}

function graphiteEditor(target, onChange) {
  const t = { ...target };
  return h('div',
    field('Graphite hedefleri (satır başına bir)', textarea({ value: t.target || '', rows: 3, class: 'code-editor', placeholder: 'aliasByNode(servers.*.cpu.user, 1)',
      onChange: (e) => onChange({ ...t, target: e.target.value }) })),
    field('Seri adı (isteğe bağlı)', input({ value: t.alias || '', onChange: (e) => onChange({ ...t, alias: e.target.value }) })));
}

export function engineEditor(target, ds, onChange) {
  if (['trino', 'databricks', 'clickhouse'].includes(ds.type)) return sqlEngineEditor(target, ds, onChange);
  if (ds.type === 'elasticsearch') return elasticsearchEditor(target, ds, onChange);
  if (ds.type === 'influxdb') return influxEditor(target, onChange);
  if (ds.type === 'graphite') return graphiteEditor(target, onChange);
  return null;
}
