// Dashboard settings: general, variables editor (with preview), JSON model, version history.
import { h, button, input, select, textarea, field, toggle, tabs, clear, modal, toast, confirmDialog, fmtDateTime } from '../dom.js';
import { get, post, datasourcesList } from '../api.js';
import { REFRESH_INTERVALS, effectiveZone } from '../time.js';

const ZONES = ['browser', 'utc', 'Europe/Istanbul', 'Europe/London', 'Europe/Berlin', 'America/New_York', 'Asia/Dubai'];
const VAR_TYPES = [{ value: 'query', label: 'Sorgu (veri kaynağından)' }, { value: 'custom', label: 'Özel liste' }, { value: 'textbox', label: 'Metin kutusu' },
  { value: 'constant', label: 'Sabit (gizli)' }, { value: 'interval', label: 'Aralık' }, { value: 'datasource', label: 'Veri kaynağı' }];

function generalTab(dash, folders, state) {
  const tagsIn = input({ value: (dash.tags || []).join(', '), placeholder: 'network, zabbix', onChange: (e) => { dash.tags = e.target.value.split(',').map((t) => t.trim()).filter(Boolean); } });
  return h('div', { class: 'form-grid' },
    field('Başlık', input({ value: dash.title, onChange: (e) => { dash.title = e.target.value; } })),
    field('Klasör', select([{ value: '', label: 'Genel' }, ...folders.map((f) => ({ value: f.uid, label: f.title }))], state.folderUid || '', (v) => { state.folderUid = v || null; })),
    field('Açıklama', input({ value: dash.description || '', onChange: (e) => { dash.description = e.target.value; } })),
    field('Etiketler (virgülle)', tagsIn),
    field('Saat dilimi', select(ZONES.map((z) => ({ value: z, label: z === 'browser' ? 'Tarayıcı saati' : z === 'utc' ? 'UTC' : z })), dash.timezone || 'browser', (v) => { dash.timezone = v; })),
    field('Varsayılan zaman aralığı', h('div', { class: 'inline-fields' }, input({ value: dash.time?.from || 'now-6h', onChange: (e) => { dash.time = { ...(dash.time || {}), from: e.target.value }; } }),
      input({ value: dash.time?.to || 'now', onChange: (e) => { dash.time = { ...(dash.time || {}), to: e.target.value }; } }))),
    field('Otomatik yenileme', select(REFRESH_INTERVALS.map((r) => ({ value: r, label: r || 'Kapalı' })), dash.refresh || '', (v) => { dash.refresh = v; })),
    field('Grafik ipucu', select([{ value: '0', label: 'Varsayılan' }, { value: '1', label: 'Ortak imleç' }, { value: '2', label: 'Ortak ipucu' }], String(dash.graphTooltip || 0), (v) => { dash.graphTooltip = Number(v); })),
    field(null, toggle('Düzenlenebilir', dash.editable !== false, (v) => { dash.editable = v; })));
}

function variableForm(v, dash, onDone) {
  const work = JSON.parse(JSON.stringify(v));
  const box = h('div');
  const preview = h('div', { class: 'chips', style: { marginTop: '8px' } });
  const runPreview = async () => {
    clear(preview);
    try {
      const temp = { ...dash, templating: { list: [...(dash.templating?.list || []).filter((x) => x.name !== v.name && x.name !== work.name), work] } };
      const res = await post('/api/dashboards/variables/resolve', { dashboard: temp, overrides: {}, range: dash.time || { from: 'now-6h', to: 'now' }, timezone: effectiveZone(dash.timezone) });
      const opts = (res.variables[work.name] || {}).options || [];
      preview.append(h('span', { class: 'muted', text: `${opts.length} değer: ` }));
      for (const o of opts.slice(0, 60)) preview.append(h('span', { class: 'chip', text: o.text }));
      for (const w of res.warnings || []) preview.append(h('div', { class: 'alert warn', text: w }));
    } catch (err) { preview.append(h('div', { class: 'alert error', text: err.message })); }
  };
  const draw = async () => {
    clear(box);
    const ds = await datasourcesList();
    box.append(h('div', { class: 'form-grid' },
      field('Ad', input({ value: work.name || '', placeholder: 'host', onChange: (e) => { work.name = e.target.value.trim(); } }), 'Panellerde $ad olarak kullanılır'),
      field('Etiket', input({ value: work.label || '', onChange: (e) => { work.label = e.target.value; } })),
      field('Tür', select(VAR_TYPES, work.type || 'query', (t) => { work.type = t; draw(); })),
      field('Gizle', select([{ value: '0', label: 'Göster' }, { value: '1', label: 'Etiketi gizle' }, { value: '2', label: 'Değişkeni gizle' }], String(work.hide || 0), (x) => { work.hide = Number(x); }))));
    if (work.type === 'query') {
      const dsUid = (work.datasource && work.datasource.uid) || (ds.find((d) => d.isDefault) || ds[0] || {}).uid;
      work.datasource = { uid: dsUid };
      const kind = (ds.find((d) => d.uid === dsUid) || {}).type;
      box.append(field('Veri kaynağı', select(ds.map((d) => ({ value: d.uid, label: `${d.name} (${d.type})` })), dsUid, (x) => { work.datasource = { uid: x }; draw(); })));
      if (kind === 'postgres') {
        box.append(field('SQL', textarea({ value: typeof work.query === 'string' ? work.query : (work.query?.rawSql || ''), rows: 4, class: 'code-editor', onChange: (e) => { work.query = e.target.value; } }),
          '__text ve __value sütunları desteklenir; yoksa ilk sütun kullanılır.'));
      } else {
        const q = typeof work.query === 'object' && work.query ? work.query : { type: 'host', group: '', host: '', item: '' };
        if (typeof work.query === 'string') {
          box.append(field('Sorgu ({grup}{host}{item})', input({ value: work.query, onChange: (e) => { work.query = e.target.value; } }), 'Ör. {Linux servers}{*} grup içindeki hostları listeler.'));
        } else {
          work.query = q;
          box.append(h('div', { class: 'form-grid' },
            field('Sorgu türü', select([{ value: 'group', label: 'Host grubu' }, { value: 'host', label: 'Host' }, { value: 'item', label: 'Item' }, { value: 'itemTag', label: 'Item etiketi' }], q.type, (x) => { q.type = x; draw(); })),
            q.type !== 'group' || true ? field('Grup filtresi', input({ value: q.group || '', placeholder: '/.*/ veya $group', onChange: (e) => { q.group = e.target.value; } })) : null,
            q.type !== 'group' ? field('Host filtresi', input({ value: q.host || '', placeholder: '/.*/ veya $host', onChange: (e) => { q.host = e.target.value; } })) : null,
            q.type === 'item' ? field('Item filtresi', input({ value: q.item || '', placeholder: '/CPU/', onChange: (e) => { q.item = e.target.value; } })) : null));
        }
        box.append(button(typeof work.query === 'string' ? 'Yapılandırılmış editöre geç' : 'Metin sorgusu ({grup}{host}) kullan', { size: 'sm', variant: 'ghost',
          onClick: () => { work.query = typeof work.query === 'string' ? { type: 'host', group: '', host: '' } : '{/.*/}'; draw(); } }));
      }
      box.append(h('div', { class: 'form-grid' },
        field('Regex (isteğe bağlı)', input({ value: work.regex || '', placeholder: '/^srv-(.*)$/', onChange: (e) => { work.regex = e.target.value; } })),
        field('Sırala', select([{ value: '0', label: 'Kapalı' }, { value: '1', label: 'Alfabetik (artan)' }, { value: '2', label: 'Alfabetik (azalan)' }, { value: '3', label: 'Sayısal (artan)' }, { value: '4', label: 'Sayısal (azalan)' }, { value: '5', label: 'Alfabetik, büyük/küçük harf duyarsız' }],
          String(work.sort || 0), (x) => { work.sort = Number(x); })),
        field('Yenile', select([{ value: '1', label: 'Dashboard yüklenince' }, { value: '2', label: 'Zaman aralığı değişince' }], String(work.refresh || 1), (x) => { work.refresh = Number(x); }))));
    } else if (work.type === 'custom' || work.type === 'interval') {
      box.append(field('Değerler (virgülle; "metin : değer")', input({ value: work.query || '', placeholder: work.type === 'interval' ? '1m,5m,1h,1d' : 'Prod : prod, Test : test', onChange: (e) => { work.query = e.target.value; } })));
    } else if (work.type === 'datasource') {
      box.append(field('Veri kaynağı türü', select([{ value: 'zabbix', label: 'Zabbix' }, { value: 'postgres', label: 'PostgreSQL' }, { value: 'testdata', label: 'TestData' }, { value: 'prometheus', label: 'Prometheus' }, { value: 'loki', label: 'Loki' }, { value: 'httpjson', label: 'HTTP JSON' }, { value: 'csv', label: 'HTTP CSV' }], work.query || 'zabbix', (x) => { work.query = x; })));
    } else {
      box.append(field(work.type === 'textbox' ? 'Varsayılan değer' : 'Değer', input({ value: work.query || '', onChange: (e) => { work.query = e.target.value; } })));
    }
    if (['query', 'custom', 'datasource'].includes(work.type)) {
      box.append(h('div', { class: 'toolbar' }, toggle('Çoklu seçim', !!work.multi, (x) => { work.multi = x; }), toggle('"Tümü" seçeneği', !!work.includeAll, (x) => { work.includeAll = x; draw(); })));
      if (work.includeAll) box.append(field('Özel "Tümü" değeri (isteğe bağlı)', input({ value: work.allValue || '', placeholder: '/.*/', onChange: (e) => { work.allValue = e.target.value || undefined; } })));
    }
    box.append(h('h4', { style: { marginTop: '14px' }, text: 'Değer önizlemesi' }), preview, h('div', { class: 'toolbar', style: { marginTop: '12px' } },
      button('Önizle', { icon: 'eye', onClick: runPreview }), h('span', { class: 'spacer' }), button('Vazgeç', { onClick: () => onDone(null) }),
      button('Uygula', { variant: 'primary', onClick: () => {
        if (!/^[A-Za-z_][A-Za-z0-9_]{0,49}$/.test(work.name || '')) { toast('Geçerli bir değişken adı girin (harf, rakam, _)', 'error'); return; }
        onDone(work);
      } })));
  };
  draw();
  return box;
}

function variablesTab(dash, refreshTab) {
  const list = dash.templating?.list || [];
  const wrap = h('div');
  const editing = (v, index) => {
    clear(wrap);
    wrap.append(h('h3', { text: index === -1 ? 'Yeni değişken' : `Değişken: $${v.name}` }), variableForm(v, dash, (result) => {
      if (result) {
        if (list.some((x, i) => x.name === result.name && i !== index)) { toast('Bu adla bir değişken var', 'error'); return; }
        if (index === -1) list.push(result); else list[index] = result;
        dash.templating = { list };
      }
      refreshTab();
    }));
  };
  if (!list.length) wrap.append(h('div', { class: 'empty-state' }, h('h3', { text: 'Değişken yok' }),
    h('p', { text: 'Değişkenler grup/host seçimini dashboard üzerinden yapmayı ve panelleri hosta göre tekrarlamayı sağlar.' })));
  else {
    const table = h('table', { class: 'list' }, h('tr', h('th', { text: 'Değişken' }), h('th', { text: 'Tür' }), h('th', { text: 'Tanım' }), h('th')));
    list.forEach((v, i) => table.append(h('tr', h('td', h('b', { text: `$${v.name}` })), h('td', { text: v.type }),
      h('td', { class: 'muted', text: typeof v.query === 'object' ? JSON.stringify(v.query) : (v.query || '') }),
      h('td', { class: 'actions' }, button('', { icon: 'arrow-up', variant: 'ghost', size: 'sm', title: 'Yukarı', onClick: () => { if (i > 0) { [list[i - 1], list[i]] = [list[i], list[i - 1]]; refreshTab(); } } }),
        button('', { icon: 'edit', variant: 'ghost', size: 'sm', title: 'Düzenle', onClick: () => editing(v, i) }),
        button('', { icon: 'copy', variant: 'ghost', size: 'sm', title: 'Çoğalt', onClick: () => { list.splice(i + 1, 0, { ...JSON.parse(JSON.stringify(v)), name: `${v.name}_copy` }); refreshTab(); } }),
        button('', { icon: 'trash', variant: 'ghost', size: 'sm', title: 'Sil', onClick: () => { list.splice(i, 1); refreshTab(); } })))));
    wrap.append(table);
  }
  wrap.append(h('div', { class: 'toolbar', style: { marginTop: '12px' } }, button('Değişken ekle', { icon: 'plus', variant: 'primary', onClick: () => editing({ name: '', type: 'query', query: { type: 'host', group: '', host: '' }, refresh: 1, sort: 1 }, -1) })));
  return wrap;
}

function jsonTab(dash, onReplace) {
  const area = textarea({ value: JSON.stringify(dash, null, 2), rows: 28, class: 'code-editor' });
  return h('div', area, h('div', { class: 'toolbar', style: { marginTop: '10px' } }, button('JSON’u uygula', { variant: 'primary', onClick: () => {
    try { onReplace(JSON.parse(area.value)); toast('JSON modeli uygulandı; kaydetmeyi unutmayın', 'ok'); } catch (err) { toast(`Geçersiz JSON: ${err.message}`, 'error'); }
  } }), button('Panoya kopyala', { onClick: () => navigator.clipboard && navigator.clipboard.writeText(area.value).then(() => toast('Kopyalandı', 'ok')) })));
}

async function versionsTab(uid, onRestore) {
  const wrap = h('div');
  if (!uid) { wrap.append(h('p', { class: 'muted', text: 'Dashboard henüz kaydedilmedi.' })); return wrap; }
  const list = await get(`/api/dashboards/uid/${encodeURIComponent(uid)}/versions`);
  const table = h('table', { class: 'list' }, h('tr', h('th', { text: 'Sürüm' }), h('th', { text: 'Tarih' }), h('th', { text: 'Kullanıcı' }), h('th', { text: 'Not' }), h('th')));
  list.forEach((v, i) => table.append(h('tr', h('td', { text: v.version }), h('td', { text: fmtDateTime(v.created_at) }), h('td', { text: v.created_by || '—' }), h('td', { text: v.message || '' }),
    h('td', { class: 'actions' }, i === 0 ? h('span', { class: 'badge ok', text: 'güncel' }) : button('Geri yükle', { size: 'sm', onClick: async () => {
      if (await confirmDialog('Sürümü geri yükle', `Sürüm ${v.version} yeni bir sürüm olarak geri yüklenecek.`)) onRestore(v.version);
    } })))));
  wrap.append(table);
  return wrap;
}

export async function openSettings({ dashboard, meta, onApply, onRestore }) {
  const dash = JSON.parse(JSON.stringify(dashboard));
  const state = { folderUid: meta.folderUid || null };
  const folders = (await get('/api/folders').catch(() => [])).filter(f => f.canEdit !== false);
  const content = h('div');
  let current = 'general';
  const show = async (id) => {
    current = id;
    clear(content);
    if (id === 'general') content.append(generalTab(dash, folders, state));
    if (id === 'variables') content.append(variablesTab(dash, () => show('variables')));
    if (id === 'json') content.append(jsonTab(dash, (replacement) => { Object.keys(dash).forEach((k) => delete dash[k]); Object.assign(dash, replacement); }));
    if (id === 'versions') content.append(await versionsTab(dashboard.uid && meta.version ? dashboard.uid : null, (version) => { dlg.close(); onRestore(version); }));
  };
  const bar = tabs([{ id: 'general', label: 'Genel' }, { id: 'variables', label: 'Değişkenler' }, { id: 'json', label: 'JSON modeli' }, { id: 'versions', label: 'Sürümler' }], current, show);
  await show('general');
  const dlg = modal({ title: 'Dashboard ayarları', size: 'xl', body: [bar, content], footer: [button('Kapat', { onClick: () => dlg.close() }),
    button('Değişiklikleri uygula', { variant: 'primary', onClick: () => { dlg.close(); onApply(dash, state.folderUid); } })] });
}
