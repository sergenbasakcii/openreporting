// Smart dashboards: build a report-ready dashboard on live PDF pages. Drag a visualization onto a page,
// pick group / host / keyword from drill-down popups, see real data immediately, export as PDF.
import { h, button, input, select, field, toast, modal, clear, loading, downloadBlob, confirmDialog } from '../dom.js';
import { icon } from '../icons.js';
import { api, get, post, datasourcesList, invalidate, ApiError } from '../api.js';
import { setBreadcrumbs, navigate, setLeaveGuard, clearLeaveGuard } from '../router.js';
import { timePicker, resolveRange, effectiveZone } from '../time.js';
import { PanelView } from '../dashboard/panelview.js';
import { PLUGINS } from '../panels/registry.js';
import { queryEditor } from '../query/editors.js';
import { createCanvas, findSpot, ROWS } from '../smart/canvas.js';
import { keywordChips } from '../smart/keywords.js';

export const SMART_TAG = 'akıllı';
const PALETTE = [
  ['timeseries', 12, 9], ['barchart', 12, 9], ['stat', 6, 5], ['gauge', 6, 6], ['bargauge', 12, 7], ['table', 24, 10],
  ['piechart', 8, 8], ['donut', 8, 8], ['statusgrid', 12, 7], ['heatmap', 12, 8], ['text', 12, 4],
];
const KEYWORD_SOURCES = ['zabbix', 'testdata'];

function blankModel(title, ds) {
  return { title, tags: [SMART_TAG], time: { from: 'now-24h', to: 'now' }, timezone: 'browser', templating: { list: [] }, panels: [],
    smart: { version: 1, paper: 'A4', orientation: 'portrait', rows: ROWS.portrait, pages: 1, cover: false, subtitle: '' }, smartSource: ds ? { uid: ds.uid } : null };
}

function newTarget(ds) {
  const base = { refId: 'A', queryType: 'metrics', group: { filter: '/.*/' }, host: { filter: '/.*/' }, item: { filter: '' } };
  return ds?.type === 'testdata' ? { ...base, scenario: 'zabbix_sim' } : KEYWORD_SOURCES.includes(ds?.type) ? base : { refId: 'A' };
}

export async function smartListPage(root, { app }) {
  setBreadcrumbs([{ label: 'Akıllı dashboard' }]);
  const page = h('div', { class: 'page' }, loading());
  root.append(page);
  const list = await get(`/api/search?tag=${encodeURIComponent(SMART_TAG)}`);
  const canEdit = ['admin', 'editor'].includes(app.user.role);
  clear(page).append(h('div', { class: 'page-header' }, h('div', h('h1', icon('report'), 'Akıllı dashboard'),
    h('p', { class: 'sub', text: 'Rapor sayfası üzerinde sürükle-bırak ile hızlı dashboard: görselleştirmeyi sayfaya bırakın, host ve anahtar kelimeyi seçin, PDF olarak indirin.' })),
  canEdit ? h('div', { class: 'toolbar' }, button('Yeni akıllı dashboard', { icon: 'plus', variant: 'primary', onClick: () => navigate('/smart/new') })) : null));
  if (!list.length) {
    page.append(h('div', { class: 'empty-state' }, h('h2', { class: 'section-heading', text: 'Henüz akıllı dashboard yok' }),
      h('p', { text: 'Teknik sorgu bilgisi gerekmez: bir grafik türünü A4 sayfaya sürükleyin, üstündeki Grup / Host / Anahtar kelime kutularından seçim yapın.' }),
      canEdit ? h('div', { class: 'toolbar' }, button('İlkini oluştur', { icon: 'plus', variant: 'primary', onClick: () => navigate('/smart/new') })) : null));
    return;
  }
  page.append(h('div', { class: 'card-grid' }, list.map((d) => h('a', { class: 'tile', href: `/smart/${d.uid}`, 'data-link': '' },
    h('span', { class: 'tile-icon' }, icon('report')), h('span', h('b', { text: d.title }), h('span', { text: d.folderTitle || 'Genel' }))))));
}

export async function smartBuilderPage(root, { app, uid }) {
  setBreadcrumbs([{ label: 'Akıllı dashboard', href: '/smart' }, { label: uid ? '…' : 'Yeni' }], root);
  const sources = await datasourcesList();
  const preferred = sources.find((s) => s.type === 'zabbix') || sources.find((s) => s.type === 'testdata') || sources[0];
  const existing = uid ? await get(`/api/dashboards/uid/${encodeURIComponent(uid)}`) : null;
  const model = existing ? existing.dashboard : blankModel('Yeni akıllı dashboard', preferred);
  const meta = existing ? existing.meta : { folderUid: null, canEdit: true };
  if (!model.smart) model.smart = blankModel('', preferred).smart; // a normal dashboard opened here becomes page-based
  model.tags = [...new Set([...(model.tags || []), SMART_TAG])];
  for (const [i, p] of (model.panels || []).entries()) p.smartPos ||= { page: 0, x: 0, y: (i * 8) % model.smart.rows, w: p.gridPos?.w || 12, h: Math.min(model.smart.rows, p.gridPos?.h || 8) };
  const editable = meta.canEdit !== false && ['admin', 'editor'].includes(app.user.role);
  setBreadcrumbs([{ label: 'Akıllı dashboard', href: '/smart' }, { label: model.title }], root);

  const state = { range: { ...model.time }, now: Date.now(), dirty: false, selected: null };
  const views = new Map();
  const dsOf = (panel) => sources.find((s) => s.uid === (panel.datasource?.uid || model.smartSource?.uid)) || preferred;
  const ctx = () => ({ range: state.range, timezone: model.timezone || 'browser', variables: {}, scopedVars: {}, now: state.now, dashboardTitle: model.title });
  const markDirty = () => { state.dirty = true; saveBtn.classList.add('primary'); };
  const leaveGuard = () => (state.dirty ? 'Akıllı dashboard’da kaydedilmemiş değişiklikler var. Ayrılmak istiyor musunuz?' : null);
  setLeaveGuard(leaveGuard, root);
  const nextId = () => Math.max(0, ...model.panels.map((p) => p.id || 0)) + 1;

  function view(panel) {
    let entry = views.get(panel.id);
    if (!entry) { entry = new PanelView(panel, ctx(), {}); views.set(panel.id, entry); }
    entry.panel = panel;
    entry.setContext(ctx());
    return entry;
  }
  const refresh = (panel) => { const v = views.get(panel.id); if (v) { v.panel = panel; v.setContext(ctx()); v.refresh(); } };
  const refreshAll = () => { state.now = Date.now(); for (const p of model.panels) refresh(p); };

  function itemBar(panel) {
    const ds = dsOf(panel);
    const parts = [];
    if (panel.type === 'text') parts.push(h('span', { class: 'hint', text: 'Metin kutusu · sağ panelden düzenleyin' }));
    else if (KEYWORD_SOURCES.includes(ds?.type)) {
      parts.push(keywordChips(panel.targets[0] || panel.smartDraft || {}, { dsUid: ds.uid, range: state.range, onChange: (f) => {
        const t = { ...(panel.targets[0] || panel.smartDraft || newTarget(ds)), group: { filter: f.group || '/.*/' }, host: { filter: f.host || '/.*/' }, item: { filter: f.item || '' } };
        // Nothing is queried until a keyword (metric) is chosen: "all items of all hosts" is never useful.
        if (f.item) { panel.targets = [t]; delete panel.smartDraft; } else { panel.targets = []; panel.smartDraft = t; }
        if (!panel.titleLocked) panel.title = autoTitle(f);
        markDirty(); canvas.render(); refresh(panel); inspector();
      } }));
    } else parts.push(button('Sorgu', { size: 'sm', icon: 'code', onClick: () => editQuery(panel) }));
    if (editable) parts.push(button('', { size: 'sm', variant: 'ghost', icon: 'trash', title: 'Paneli kaldır', onClick: () => removePanel(panel) }));
    return h('div', { class: 'smart-bar-content' }, parts);
  }

  const autoTitle = (f) => {
    const pick = (v) => (v && v !== '/.*/' ? v.replace(/^\/(.*)\/i$/, '$1').replace(/\\(.)/g, '$1') : '');
    return [pick(f.item), pick(f.host) || pick(f.group)].filter(Boolean).join(' · ') || 'Yeni panel';
  };

  const canvas = createCanvas({
    model,
    selectedId: () => state.selected,
    header: (page) => h('header', { class: 'paper-head' },
      h('div', h('b', { text: model.title }), model.smart.subtitle ? h('span', { text: model.smart.subtitle }) : null),
      h('span', { class: 'paper-range', text: `${state.range.from} → ${state.range.to}${page ? '' : ` · ${effectiveZone(model.timezone)}`}` })),
    renderItem: (panel) => ({ bar: itemBar(panel), el: h('div', { class: 'smart-view-inner' }, view(panel).el,
      panel.smartDraft && !panel.targets.length ? h('div', { class: 'smart-hint' }, icon('search'), h('span', { text: 'Üstteki “Anahtar kelime” kutusundan gösterilecek metriği seçin' })) : null) }),
    onAdd: (type, cell) => addPanel(type, cell),
    onChange: () => { markDirty(); inspector(); },
    onSelect: (panel) => { if (state.selected !== panel.id) { state.selected = panel.id; for (const el of canvas.el.querySelectorAll('.smart-item')) el.classList.toggle('selected', Number(el.dataset.id) === panel.id); inspector(); } },
  });

  function addPanel(type, cell = { page: 0, x: 0, y: 0 }) {
    if (!editable) return;
    const [, w, hgt] = PALETTE.find(([t]) => t === type) || [type, 12, 8];
    const pos = findSpot(model.panels, { page: cell.page, x: Math.min(cell.x, 24 - w), y: Math.min(cell.y, model.smart.rows - Math.min(hgt, model.smart.rows)), w, h: Math.min(hgt, model.smart.rows) }, model.smart.rows, model.smart.pages);
    if (pos.page >= model.smart.pages) model.smart.pages = pos.page + 1;
    const ds = sources.find((s) => s.uid === model.smartSource?.uid) || preferred;
    const panel = { id: nextId(), type, title: type === 'text' ? '' : 'Yeni panel', datasource: ds ? { uid: ds.uid } : undefined,
      targets: type === 'text' || KEYWORD_SOURCES.includes(ds?.type) ? [] : [newTarget(ds)], smartDraft: KEYWORD_SOURCES.includes(ds?.type) ? newTarget(ds) : undefined, options: type === 'text' ? { mode: 'markdown', content: '## Başlık\nAçıklama metni' } : {},
      fieldConfig: { defaults: {}, overrides: [] }, smartPos: pos, gridPos: { x: pos.x, y: pos.y, w: pos.w, h: pos.h } };
    model.panels.push(panel);
    state.selected = panel.id;
    markDirty(); canvas.render(); refresh(panel); inspector();
    if (type !== 'text' && KEYWORD_SOURCES.includes(ds?.type)) toast('Panelin üstündeki “Anahtar kelime” kutusundan ne göstereceğinizi seçin', 'info');
  }

  async function removePanel(panel) {
    model.panels = model.panels.filter((p) => p !== panel);
    views.get(panel.id)?.destroy(); views.delete(panel.id);
    if (state.selected === panel.id) state.selected = null;
    markDirty(); canvas.setModel(model); inspector();
  }

  function editQuery(panel) {
    const ds = dsOf(panel);
    let target = { ...(panel.targets[0] || { refId: 'A' }) };
    const dlg = modal({ title: `Sorgu · ${panel.title || PLUGINS[panel.type]?.name}`, size: 'lg', body: h('div', queryEditor(target, ds, ctx(), (t) => { target = t; })),
      footer: [button('Vazgeç', { onClick: () => dlg.close() }), button('Uygula', { variant: 'primary', onClick: () => { panel.targets = [target]; dlg.close(); markDirty(); refresh(panel); } })] });
  }

  // ---- inspector (right) ----
  const side = h('aside', { class: 'smart-side' });
  function inspector() {
    clear(side);
    const panel = model.panels.find((p) => p.id === state.selected);
    if (!panel) {
      side.append(h('h2', { class: 'section-heading', text: 'Sayfa ayarları' }),
        field('Başlık', input({ value: model.title, onChange: (e) => { model.title = e.target.value || 'Akıllı dashboard'; markDirty(); canvas.render(); } })),
        field('Alt başlık', input({ value: model.smart.subtitle, placeholder: 'ör. Haftalık altyapı raporu', onChange: (e) => { model.smart.subtitle = e.target.value; markDirty(); canvas.render(); } })),
        field('Varsayılan veri kaynağı', select(sources.map((s) => ({ value: s.uid, label: s.name })), model.smartSource?.uid || preferred?.uid, (v) => { model.smartSource = { uid: v }; markDirty(); })),
        field('Kâğıt', select(['A4', 'A3', 'Letter'].map((v) => ({ value: v, label: v })), model.smart.paper, (v) => { model.smart.paper = v; markDirty(); canvas.render(); })),
        field('Yön', select([{ value: 'portrait', label: 'Dikey' }, { value: 'landscape', label: 'Yatay' }], model.smart.orientation, (v) => setOrientation(v))),
        h('div', { class: 'toolbar' }, button('Sayfa ekle', { icon: 'plus', size: 'sm', onClick: () => { model.smart.pages += 1; markDirty(); canvas.render(); } }),
          button('Son sayfayı kaldır', { size: 'sm', onClick: removeLastPage })),
        h('p', { class: 'hint', text: 'Bir paneli seçmek için üzerine tıklayın. Taşımak için sol üstteki tutamaçtan, boyutlandırmak için sağ alt köşeden sürükleyin.' }));
      return;
    }
    const types = PALETTE.map(([t]) => ({ value: t, label: PLUGINS[t]?.name || t }));
    side.append(h('div', { class: 'toolbar', style: { justifyContent: 'space-between' } }, h('h2', { class: 'section-heading', style: { margin: 0 }, text: 'Panel' }),
      button('Sayfa ayarları', { size: 'sm', variant: 'ghost', onClick: () => { state.selected = null; canvas.render(); inspector(); } })),
    field('Başlık', input({ value: panel.title || '', onChange: (e) => { panel.title = e.target.value; panel.titleLocked = true; markDirty(); refresh(panel); } })),
    field('Görselleştirme', select(types, panel.type, (v) => { panel.type = v; views.get(panel.id)?.destroy(); views.delete(panel.id); markDirty(); canvas.render(); refresh(panel); })));
    if (panel.type === 'text') {
      const area = h('textarea', { class: 'input', rows: 8, value: panel.options?.content || '', onChange: (e) => { panel.options = { ...panel.options, mode: 'markdown', content: e.target.value }; markDirty(); refresh(panel); } });
      side.append(field('Metin (Markdown)', area));
    } else {
      side.append(field('Veri kaynağı', select(sources.map((s) => ({ value: s.uid, label: s.name })), dsOf(panel)?.uid, (v) => {
        const ds = sources.find((s) => s.uid === v); panel.datasource = { uid: v };
        if (KEYWORD_SOURCES.includes(ds?.type)) { panel.targets = []; panel.smartDraft = newTarget(ds); } else { panel.targets = [newTarget(ds)]; delete panel.smartDraft; } markDirty(); canvas.render(); refresh(panel); inspector();
      })),
      field('Birim', select([{ value: '', label: 'Otomatik' }, { value: 'percent', label: 'Yüzde (%)' }, { value: 'bytes', label: 'Bayt' }, { value: 'bps', label: 'bit/sn' }, { value: 'ms', label: 'Milisaniye' }, { value: 's', label: 'Saniye' }, { value: 'short', label: 'Sayı' }],
        panel.fieldConfig?.defaults?.unit || '', (v) => { panel.fieldConfig = { ...(panel.fieldConfig || {}), defaults: { ...(panel.fieldConfig?.defaults || {}), unit: v || undefined } }; markDirty(); refresh(panel); })),
      button('Gelişmiş sorgu', { icon: 'code', size: 'sm', onClick: () => editQuery(panel) }));
    }
    side.append(h('div', { class: 'toolbar', style: { marginTop: '12px' } }, button('Paneli kaldır', { icon: 'trash', size: 'sm', variant: 'danger', onClick: () => removePanel(panel) })));
  }

  function setOrientation(orientation) {
    const from = model.smart.rows; const to = ROWS[orientation];
    model.smart.orientation = orientation; model.smart.rows = to;
    for (const p of model.panels) {
      const hgt = Math.max(2, Math.min(to, Math.round((p.smartPos.h * to) / from)));
      p.smartPos = { ...p.smartPos, h: hgt, y: Math.min(to - hgt, Math.round((p.smartPos.y * to) / from)) };
    }
    markDirty(); canvas.render();
  }

  async function removeLastPage() {
    if (model.smart.pages <= 1) return;
    const last = model.smart.pages - 1;
    if (model.panels.some((p) => p.smartPos.page === last) && !(await confirmDialog('Sayfayı kaldır', 'Son sayfadaki paneller de silinecek.', { danger: true, okText: 'Kaldır' }))) return;
    model.panels = model.panels.filter((p) => p.smartPos.page !== last);
    model.smart.pages = last; markDirty(); canvas.setModel(model); inspector();
  }

  async function save() {
    const body = { ...model, time: { ...state.range }, panels: model.panels.map((p) => ({ ...p, gridPos: { x: p.smartPos.x, y: p.smartPos.page * model.smart.rows + p.smartPos.y, w: p.smartPos.w, h: p.smartPos.h } })) };
    try {
      const res = await post('/api/dashboards/db', { dashboard: body, folderUid: meta.folderUid || null, message: 'Akıllı dashboard', overwrite: false });
      model.uid = res.uid; model.version = res.version; state.dirty = false; saveBtn.classList.remove('primary'); invalidate('search');
      toast('Kaydedildi', 'ok');
      if (!uid) navigate(`/smart/${res.uid}`, { replace: true, force: true });
      return true;
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && (await confirmDialog('Çakışma', `${err.message}. Üzerine yazılsın mı?`, { okText: 'Üzerine yaz', danger: true }))) {
        await post('/api/dashboards/db', { dashboard: body, folderUid: meta.folderUid || null, overwrite: true }); state.dirty = false; return true;
      }
      toast(err.message, 'error'); return false;
    }
  }

  async function exportAs(format) {
    if ((state.dirty || !model.uid) && !(await save())) return;
    toast(`${format.toUpperCase()} hazırlanıyor…`, 'info', 2500);
    try {
      const res = await api('/api/dashboards/export', { method: 'POST', raw: true, body: { dashboard_uid: model.uid, time_range: state.range, timezone: effectiveZone(model.timezone), variables: {}, format } });
      downloadBlob(`${model.title.replace(/[^\w-]+/g, '_')}.${format}`, await res.blob());
    } catch (err) { toast(err.message, 'error'); }
  }

  // ---- palette (left) ----
  const palette = h('aside', { class: 'smart-palette', 'aria-label': 'Görselleştirmeler' }, h('h2', { class: 'section-heading', text: 'Görselleştirmeler' }),
    h('p', { class: 'hint', text: 'Sayfaya sürükleyin veya tıklayın.' }),
    PALETTE.map(([type]) => h('button', { type: 'button', class: 'smart-tool', draggable: 'true', disabled: !editable,
      onDragstart: (e) => { e.dataTransfer.setData('application/x-smart-viz', type); e.dataTransfer.effectAllowed = 'copy'; },
      onClick: () => addPanel(type) }, icon(PLUGINS[type]?.icon || 'panel'), h('span', { text: PLUGINS[type]?.name || type }))));

  const tp = timePicker({ range: state.range, timezone: model.timezone, onChange: (r) => { state.range = r; markDirty(); canvas.render(); refreshAll(); }, getResolved: () => resolveRange(state.range, model.timezone) });
  const saveBtn = button('Kaydet', { icon: 'save', onClick: save, disabled: !editable });
  const toolbar = h('div', { class: 'smart-toolbar' },
    h('h1', { class: 'smart-title' }, icon('report'), h('span', { text: model.title })), h('span', { class: 'spacer' }), tp,
    button('PDF indir', { icon: 'download', variant: 'primary', onClick: () => exportAs('pdf') }), button('Excel', { icon: 'download', onClick: () => exportAs('xlsx') }),
    model.uid ? button('Dashboard görünümü', { icon: 'apps', onClick: () => navigate(`/d/${model.uid}`) }) : null, saveBtn);

  root.append(h('div', { class: 'smart-layout' }, toolbar, h('div', { class: 'smart-main' }, palette, h('div', { class: 'smart-stage' }, canvas.el), side)));
  canvas.render();
  inspector();
  refreshAll();
  return () => { for (const v of views.values()) v.destroy(); clearLeaveGuard(leaveGuard); };
}
