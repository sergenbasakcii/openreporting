// Connection forms for the data lake / SQL engines and the search / time-series stores.
// `ui` carries the shared helpers of the datasource page: jd (json field), secret, model.
import { h, input, select, textarea, field } from '../dom.js';

const AUTH = {
  elasticsearch: [{ value: 'none', label: 'Yok' }, { value: 'basic', label: 'Kullanıcı + parola' }, { value: 'apikey', label: 'API key (ApiKey …)' }, { value: 'bearer', label: 'Bearer token' }],
  influxdb: [{ value: 'none', label: 'Yok' }, { value: 'basic', label: 'Kullanıcı + parola (1.x)' }, { value: 'token', label: 'API token (2.x / 3.x)' }],
  graphite: [{ value: 'none', label: 'Yok' }, { value: 'basic', label: 'Kullanıcı + parola' }, { value: 'bearer', label: 'Bearer token' }],
};

const URLS = {
  trino: 'https://trino.example.com:8443', databricks: 'https://adb-1234567890.12.azuredatabricks.net', clickhouse: 'https://clickhouse.example.com:8443',
  elasticsearch: 'https://elastic.example.com:9200', influxdb: 'https://influx.example.com:8086', graphite: 'https://graphite.example.com',
};

const NOTES = {
  trino: 'Veri gölü: Trino / Presto / Starburst üzerinden Hive, Iceberg, Delta Lake tabloları. Yalnızca SELECT yetkili bir kullanıcı kullanın; parola için Trino HTTPS gerektirir.',
  databricks: 'Kişisel erişim anahtarı (PAT) veya servis sorumlusu anahtarı kullanın; yalnızca okuma yetkili (SELECT, USE CATALOG/SCHEMA) bir kimlik önerilir.',
  clickhouse: 'Sorgular readonly=2 ayarı ve satır sınırıyla çalışır. Kullanıcı profili zaten readonly=1 ise aşağıdaki kutuyu işaretleyin.',
  elasticsearch: 'Yalnızca _search kullanılır; indeks deseni sorguda değiştirilebilir. Okuma (read, view_index_metadata) yetkili bir rol kullanın.',
  influxdb: 'InfluxQL ile okuma. InfluxDB 2.x için v1 uyumluluk eşlemesi (DBRP) gerekir; 3.x InfluxQL’i doğrudan destekler.',
  graphite: 'Graphite-web / carbonapi render API’si (format=json).',
};

function authFields(type, ui) {
  const { model, jd, secret } = ui;
  const mode = model.jsonData.auth_mode || 'none';
  return [
    field('Kimlik doğrulama', select(AUTH[type], mode, (v) => { model.jsonData.auth_mode = v; ui.redraw(); })),
    mode === 'basic' ? jd('user', 'Kullanıcı') : null,
    mode === 'basic' ? secret('password', 'Parola') : null,
    ['apikey', 'bearer', 'token'].includes(mode) ? secret('token', mode === 'apikey' ? 'API key' : 'Token') : null,
  ];
}

function specific(type, ui) {
  const { model, jd, secret } = ui;
  switch (type) {
    case 'trino':
      return [
        field('Ürün', select([{ value: 'trino', label: 'Trino / Starburst' }, { value: 'presto', label: 'PrestoDB' }], model.jsonData.flavor || 'trino', (v) => { model.jsonData.flavor = v; })),
        jd('user', 'Kullanıcı', { placeholder: 'openreporting' }), jd('catalog', 'Varsayılan katalog', { placeholder: 'iceberg' }), jd('schema', 'Varsayılan şema', { placeholder: 'analytics' }),
        secret('password', 'Parola (isteğe bağlı)'), secret('token', 'JWT / OAuth token (isteğe bağlı)'),
      ];
    case 'databricks':
      return [jd('warehouse_id', 'SQL warehouse kimliği', { placeholder: '1234567890abcdef' }), jd('catalog', 'Katalog', { placeholder: 'main' }), jd('schema', 'Şema', { placeholder: 'default' }), secret('token', 'Erişim anahtarı (PAT)')];
    case 'clickhouse':
      return [jd('user', 'Kullanıcı', { placeholder: 'readonly' }), jd('database', 'Veritabanı', { placeholder: 'default' }), secret('password', 'Parola'),
        field(null, h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: !!model.jsonData.readonly_profile, onChange: (e) => { model.jsonData.readonly_profile = e.target.checked; } }),
          h('span', { class: 'track' }), h('span', { text: 'Kullanıcı profili readonly=1 (ayar gönderme)' })))];
    case 'elasticsearch':
      return [
        field('Ürün', select([{ value: 'elasticsearch', label: 'Elasticsearch' }, { value: 'opensearch', label: 'OpenSearch' }], model.jsonData.flavor || 'elasticsearch', (v) => { model.jsonData.flavor = v; })),
        jd('index', 'Varsayılan indeks deseni', { placeholder: 'logs-*' }), jd('time_field', 'Zaman alanı', { placeholder: '@timestamp' }), ...authFields(type, ui),
      ];
    case 'influxdb':
      return [jd('database', 'Veritabanı / bucket', { placeholder: 'telegraf' }), ...authFields(type, ui)];
    case 'graphite':
      return authFields(type, ui);
    default:
      return null;
  }
}

export function engineConnectionForm(type, ui) {
  const fields = specific(type, ui);
  if (!fields) return null;
  const { model, jd } = ui;
  return h('div', { class: 'card' }, h('h2', { class: 'section-heading', text: 'Bağlantı' }),
    field('Sunucu adresi', input({ value: model.url || '', placeholder: URLS[type], onChange: (e) => { model.url = e.target.value; } }), 'Yalnızca HTTPS; sertifika doğrulanır, yönlendirmeler izlenmez.'),
    h('div', { class: 'form-grid' }, ...fields.filter(Boolean), jd('timeout', 'Zaman aşımı (sn)', { type: 'number', placeholder: '30' })),
    field('Kurum CA sertifikası (PEM, isteğe bağlı)', textarea({ value: model.jsonData.ca_pem || '', rows: 3, placeholder: '-----BEGIN CERTIFICATE-----', onChange: (e) => { model.jsonData.ca_pem = e.target.value; } })),
    h('p', { class: 'hint', text: NOTES[type] }));
}
