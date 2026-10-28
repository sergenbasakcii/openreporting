// Datasource administration (admin): list, create/edit with write-only secrets, connection test.
import { h, button, input, select, textarea, field, toggle, toast, confirmDialog, loading, timeAgo } from '../dom.js';
import { icon } from '../icons.js';
import { get, post, put, del, invalidate } from '../api.js';
import { navigate, setBreadcrumbs } from '../router.js';

const TYPE_ICON = { zabbix: 'activity', postgres: 'database', testdata: 'layers' };

export async function datasourcesPage(root) {
  setBreadcrumbs([{ label: 'Veri kaynakları' }]);
  const page = h('div', { class: 'page' });
  root.append(page);
  page.append(loading());
  const list = await get('/api/datasources');
  page.replaceChildren(h('div', { class: 'page-header' }, h('div', h('h1', icon('database'), 'Veri kaynakları'),
    h('p', { class: 'sub', text: 'Zabbix, PostgreSQL, Prometheus, Loki, HTTP JSON/CSV ve test verisi. Kimlik bilgileri sunucuda şifreli saklanır ve tarayıcıya hiçbir zaman gönderilmez.' })),
  button('Veri kaynağı ekle', { icon: 'plus', variant: 'primary', onClick: () => navigate('/datasources/new') })));
  if (!list.length) page.append(h('div', { class: 'empty-state' }, h('h3', { text: 'Veri kaynağı yok' })));
  for (const ds of list) {
    page.append(h('a', { class: 'list-row', href: ds.readOnly ? undefined : `/datasources/edit/${ds.uid}`, 'data-link': ds.readOnly ? undefined : '' },
      h('div', { class: 'tile-icon' }, icon(TYPE_ICON[ds.type] || 'database')),
      h('div', { class: 'grow' }, h('b', { text: ds.name }), h('div', { class: 'faint', text: `${ds.type} · ${ds.url || '—'} · güncellendi ${timeAgo(ds.updated_at)}` })),
      ds.isDefault ? h('span', { class: 'badge info', text: 'varsayılan' }) : null,
      ds.readOnly ? h('span', { class: 'badge', title: 'Ortam dosyasından tanımlı; arayüzden değiştirilemez', text: 'provisioned' }) : null,
      button('Test et', { size: 'sm', onClick: async (e) => { e.preventDefault(); e.stopPropagation(); await testConnection(ds.uid); } })));
  }
}

async function testConnection(uid) {
  try {
    const res = await post(`/api/datasources/${encodeURIComponent(uid)}/health`);
    toast(res.message, res.status === 'ok' ? 'ok' : 'error');
    return res;
  } catch (err) { toast(err.message, 'error'); return null; }
}

export async function datasourceEditPage(root, { uid }) {
  const types = await get('/api/datasources/types');
  const existing = uid ? await get(`/api/datasources/${encodeURIComponent(uid)}`) : null;
  const all = await get('/api/datasources');
  setBreadcrumbs([{ label: 'Veri kaynakları', href: '/datasources' }, { label: existing ? existing.name : 'Yeni' }], root);
  const model = existing ? { name: existing.name, type: existing.type, url: existing.url, isDefault: existing.isDefault, jsonData: { ...existing.jsonData }, secureJsonData: {}, secureJsonReset: [] }
    : { name: '', type: 'zabbix', url: '', isDefault: false, jsonData: { auth_mode: 'bearer', trends_from: '7d', trends_range: '4d', cache_ttl: 60, timeout: 30, max_items: 500 }, secureJsonData: {}, secureJsonReset: [] };
  const configured = existing ? existing.secureJsonFields : {};
  const page = h('div', { class: 'page' });
  const form = h('div');
  const jd = (key, label, opts = {}) => field(label, input({ value: model.jsonData[key] ?? '', type: opts.type, placeholder: opts.placeholder,
    onChange: (e) => { model.jsonData[key] = opts.type === 'number' ? Number(e.target.value) : e.target.value; } }), opts.hint);
  const secret = (key, label, hint) => {
    if (configured[key] && !model.secureJsonReset.includes(key)) {
      return field(label, h('div', { class: 'toolbar' }, h('span', { class: 'badge ok', text: 'yapılandırıldı' }), button('Sıfırla', { size: 'sm', onClick: () => { model.secureJsonReset.push(key); draw(); } })), hint);
    }
    return field(label, input({ type: 'password', autocomplete: 'new-password', placeholder: 'gizli değer (kaydedildikten sonra gösterilmez)', onChange: (e) => { model.secureJsonData[key] = e.target.value; } }), hint);
  };
  const draw = () => {
    form.replaceChildren();
    form.append(h('div', { class: 'card' }, h('div', { class: 'form-grid' },
      field('Ad', input({ value: model.name, onChange: (e) => { model.name = e.target.value; } })),
      field('Tür', existing ? input({ value: model.type, readonly: true }) : select(types.types.map((t) => ({ value: t.type, label: t.name })), model.type, (v) => { model.type = v; model.jsonData = v === 'postgres' ? { port: 5432, sslmode: 'verify-full', timeout_ms: 30000, max_rows: 200000 } : v === 'zabbix' ? { auth_mode: 'bearer', trends_from: '7d', trends_range: '4d', cache_ttl: 60, timeout: 30, max_items: 500 } : {}; draw(); })),
      field(null, toggle('Varsayılan veri kaynağı', model.isDefault, (v) => { model.isDefault = v; }))),
    h('p', { class: 'hint', text: (types.types.find((t) => t.type === model.type) || {}).description || '' })));
    if (model.type === 'zabbix') {
      form.append(h('div', { class: 'card' }, h('h3', { text: 'Bağlantı' }),
        field('Zabbix API URL', input({ value: model.url, placeholder: 'https://zabbix.example.com/api_jsonrpc.php', onChange: (e) => { model.url = e.target.value; } }), 'Yalnızca HTTPS; yönlendirmeler reddedilir.'),
        secret('token', 'API token', 'Zabbix → Kullanıcılar → API tokenları. Yalnızca okuma (get) yetkili, gerekli host gruplarına erişimi olan bir hesap kullanın.'),
        field('Kimlik doğrulama yöntemi', select([{ value: 'bearer', label: 'Authorization: Bearer (Zabbix 6.4+)' }, { value: 'body', label: '"auth" alanı (Zabbix < 6.4)' }], model.jsonData.auth_mode || 'bearer', (v) => { model.jsonData.auth_mode = v; })),
        field('Kurum CA sertifikası (PEM, isteğe bağlı)', textarea({ value: model.jsonData.ca_pem || '', rows: 4, placeholder: '-----BEGIN CERTIFICATE-----', onChange: (e) => { model.jsonData.ca_pem = e.target.value; } }), 'TLS doğrulaması kapatılamaz; iç CA kullanıyorsanız buraya ekleyin.')),
      h('div', { class: 'card' }, h('h3', { text: 'Sorgu ayarları' }), h('div', { class: 'form-grid' },
        jd('trends_from', 'Trend kullan: şundan eski veriler', { placeholder: '7d', hint: 'History saklama süresi (ör. 7d)' }),
        jd('trends_range', 'Trend kullan: aralık şundan uzunsa', { placeholder: '4d' }),
        jd('cache_ttl', 'Metadata önbelleği (sn)', { type: 'number' }), jd('timeout', 'API zaman aşımı (sn)', { type: 'number' }),
        jd('max_items', 'Sorgu başına en fazla item', { type: 'number', hint: 'Daha fazlası eşleşirse sorgu reddedilir (sessiz kırpma yok).' }),
        jd('time_interval', 'En küçük aralık', { placeholder: '1m' }),
        field('History kaynağı', select([{ value: 'api', label: 'Zabbix API (history.get / trend.get)' }, { value: 'sql', label: 'PostgreSQL/TimescaleDB (doğrudan SQL)' }], model.jsonData.history_source || 'api', (v) => { model.jsonData.history_source = v; draw(); }))),
      model.jsonData.history_source === 'sql' ? h('div', { class: 'form-grid' },
        field('Bağlı PostgreSQL veri kaynağı', select([{ value: '', label: 'Seçin' }, ...all.filter((d) => d.type === 'postgres').map((d) => ({ value: d.uid, label: d.name }))], model.jsonData.sql_datasource_uid || '', (v) => { model.jsonData.sql_datasource_uid = v; })),
        jd('history_table_float', 'History tablosu (float)', { placeholder: 'history' }), jd('history_table_uint', 'History tablosu (uint)', { placeholder: 'history_uint' }),
        jd('trends_table_float', 'Trend tablosu (float)', { placeholder: 'trends' }), jd('trends_table_uint', 'Trend tablosu (uint)', { placeholder: 'trends_uint' })) : null,
      h('p', { class: 'hint', text: 'Grup/host/item keşfi her zaman Zabbix API ile yapılır; SQL modu yalnızca büyük gruplarda zaman serisini hızlandırır.' })));
    } else if (['prometheus', 'loki', 'httpjson', 'csv'].includes(model.type)) {
      form.append(h('div', { class: 'card' }, h('h3', { text: 'Bağlantı' }),
        field('Sunucu / uç nokta URL', input({ value: model.url || '', placeholder: 'https://metrics.example.com', onChange: e => { model.url = e.target.value; } })),
        secret('token', 'Bearer token (isteğe bağlı)'), jd('timeout', 'Zaman aşımı (sn)', { type: 'number' }),
        model.type === 'httpjson' ? jd('root', 'JSON kök alanı (isteğe bağlı)', { placeholder: 'data.items' }) : null,
        field('CA sertifikası (PEM)', textarea({ value: model.jsonData.ca_pem || '', rows: 3, onChange: e => { model.jsonData.ca_pem = e.target.value; } })),
        h('p', { class: 'hint', text: 'Yalnızca okuma. HTTPS doğrulanır, yönlendirmeler izlenmez. JSON/CSV için tablo uç noktasının tam adresini yazın.' })));
    } else if (model.type === 'postgres') {
      form.append(h('div', { class: 'card' }, h('h3', { text: 'Bağlantı' }), h('div', { class: 'form-grid' },
        jd('host', 'Sunucu', { placeholder: 'db.example.com' }), jd('port', 'Port', { type: 'number' }), jd('database', 'Veritabanı'), jd('user', 'Kullanıcı (yalnızca SELECT yetkili)'),
        secret('password', 'Parola'),
        field('SSL modu', select(['verify-full', 'verify-ca', 'require', 'disable'].map((v) => ({ value: v, label: v })), model.jsonData.sslmode || 'verify-full', (v) => { model.jsonData.sslmode = v; })),
        jd('timeout_ms', 'Sorgu zaman aşımı (ms)', { type: 'number' }), jd('max_rows', 'En fazla satır', { type: 'number' }), jd('time_interval', 'En küçük aralık', { placeholder: '1m' })),
      field('CA sertifikası (PEM)', textarea({ value: model.jsonData.ca_pem || '', rows: 4, onChange: (e) => { model.jsonData.ca_pem = e.target.value; } })),
      h('p', { class: 'hint', text: 'Tüm sorgular READ ONLY işlemde, statement_timeout ve satır sınırı ile çalışır. Yine de yalnızca SELECT yetkili bir rol kullanın.' })));
    } else {
      form.append(h('div', { class: 'alert warn', text: 'TestData gerçek veri değildir. Deterministik sentetik değerler ve Zabbix benzeri grup/host/item envanteri üretir.' }));
    }
    form.append(h('div', { class: 'toolbar' },
      button(existing ? 'Kaydet ve test et' : 'Oluştur ve test et', { icon: 'save', variant: 'primary', onClick: save }),
      existing ? button('Sil', { icon: 'trash', variant: 'danger', onClick: async () => {
        if (!(await confirmDialog('Veri kaynağını sil', 'Bu veri kaynağını kullanan paneller çalışmayı durduracak.', { danger: true, okText: 'Sil' }))) return;
        try { await del(`/api/datasources/${encodeURIComponent(uid)}`); invalidate('ds:'); navigate('/datasources'); } catch (err) { toast(err.message, 'error'); }
      } }) : null,
      button('Geri', { onClick: () => navigate('/datasources') })));
  };
  const save = async () => {
    try {
      const body = { ...model, url: model.url || '' };
      let target = uid;
      if (existing) await put(`/api/datasources/${encodeURIComponent(uid)}`, body);
      else target = (await post('/api/datasources', body)).uid;
      invalidate('ds:');
      toast('Veri kaynağı kaydedildi', 'ok');
      await testConnection(target);
      if (!existing) navigate(`/datasources/edit/${target}`, { replace: true });
    } catch (err) { toast(err.message, 'error'); }
  };
  draw();
  page.append(h('div', { class: 'page-header' }, h('div', h('h1', icon(TYPE_ICON[model.type] || 'database'), existing ? existing.name : 'Yeni veri kaynağı'))), form);
  root.append(page);
}
