// Smart dashboards: build a report-ready dashboard on live PDF pages. Drag a visualization onto a page,
// pick group / host / keyword from drill-down popups, see real data immediately, export as PDF.
import { h, button, select, toast, modal, clear, loading, downloadBlob, confirmDialog, menu, timeAgo } from '../dom.js';
import { icon } from '../icons.js';
import { api, get, post, datasourcesList, invalidate, ApiError } from '../api.js';
import { setBreadcrumbs, navigate, setLeaveGuard, clearLeaveGuard } from '../router.js';
import { timePicker, resolveRange, effectiveZone, rangeLabel } from '../time.js';
import { resolveVariables, variableBar, currentOverrides } from '../variables.js';
import { PanelView } from '../dashboard/panelview.js';
import { PLUGINS } from '../panels/registry.js';
import { queryEditor } from '../query/editors.js';
import { preparePreviewWindow } from '../preview.js';
import { createCanvas, findSpot, ROWS, COLS } from '../smart/canvas.js';
import { keywordChips } from '../smart/keywords.js';
import { createHistory, drafts } from '../smart/history.js';
import { TEMPLATES, buildTemplate } from '../smart/templates.js';
import { createInspector, CHART_TYPES, LAYOUT_TYPES } from '../smart/inspector.js';

export const SMART_TAG = 'akıllı';
const SIZES = { timeseries: [12, 9], barchart: [12, 9], stat: [6, 5], gauge: [6, 6], bargauge: [12, 7], table: [24, 10], piechart: [8, 8], donut: [8, 8],
  statusgrid: [12, 7], heatmap: [12, 8], statetimeline: [24, 6], text: [12, 4], image: [6, 3], divider: [24, 2], reportinfo: [24, 4] };
const KEYWORD_SOURCES = ['zabbix', 'testdata'];
const ZOOMS = [{ value: 'fit', label: 'Sığdır' }, { value: '0.75', label: '%75' }, { value: '1', label: '%100' }, { value: '1.25', label: '%125' }, { value: '1.5', label: '%150' }];
const PAPER_PX = 900;

function blankModel(title, ds) {
  return { title, tags: [SMART_TAG], time: { from: 'now-24h', to: 'now' }, timezone: 'browser', templating: { list: [] }, panels: [],
    smart: { version: 1, paper: 'A4', orientation: 'portrait', rows: ROWS.portrait, pages: 1, cover: false, subtitle: '', logo_id: null, logo_on_pages: true, footer: '', filters: false },
    smartSource: ds ? { uid: ds.uid } : null };
}

function filterVariables(ds) {
  const ref = { uid: ds.uid, type: ds.type };
  return [
    { name: 'group', label: 'Grup', type: 'query', datasource: ref, query: { type: 'group', group: '/.*/' }, refresh: 1, sort: 1, includeAll: true, current: { value: '$__all' } },
    { name: 'host', label: 'Host', type: 'query', datasource: ref, query: { type: 'host', group: '$group', host: '/.*/' }, refresh: 1, sort: 1, multi: true, includeAll: true, current: { value: ['$__all'] } },
  ];
}

const makeTarget = (ds, useFilters) => (item = '', queryType = 'metrics') => {
  if (!KEYWORD_SOURCES.includes(ds?.type)) return { refId: 'A' };
  const t = { refId: 'A', queryType, group: { filter: useFilters ? '$group' : '/.*/' }, host: { filter: useFilters ? '$host' : '/.*/' }, item: { filter: item } };
  return ds.type === 'testdata' ? { ...t, scenario: 'zabbix_sim' } : t;
};

// ---- list + template gallery --------------------------------------------------------------------

export async function smartListPage(root, { app }) {
  setBreadcrumbs([{ label: 'Akıllı dashboard' }]);
  const page = h('div', { class: 'page' }, loading());
  root.append(page);
  const list = await get(`/api/search?tag=${encodeURIComponent(SMART_TAG)}`);
  const canEdit = ['admin', 'editor'].includes(app.user.role);
  clear(page).append(h('div', { class: 'page-header' }, h('div', h('h1', icon('report'), 'Akıllı dashboard'),
    h('p', { class: 'sub', text: 'Rapor sayfası üzerinde sürükle-bırak: görselleştirmeyi sayfaya bırakın, grup / host / anahtar kelimeyi seçin, logonuzu ekleyin, PDF olarak indirin veya zamanlayın.' }))));
  if (canEdit) {
    page.append(h('h2', { class: 'section-heading', text: 'Şablondan başlayın' }),
      h('div', { class: 'template-grid' }, TEMPLATES.map((t) => h('a', { class: 'template-card', href: `/smart/new?template=${t.id}`, 'data-link': '' },
        h('span', { class: 'template-thumb' }, ...t.panels.slice(0, 12).map((p) => h('i', { style: { left: `${(p.pos[0] / 24) * 100}%`, top: `${(p.pos[1] / 32) * 100}%`, width: `${(p.pos[2] / 24) * 100}%`, height: `${(p.pos[3] / 32) * 100}%` }, class: `t-${p.type}` })),
          t.panels.length ? null : icon('plus')),
        h('b', { text: t.name }), h('span', { class: 'hint', text: t.description })))));
  }
  page.append(h('h2', { class: 'section-heading', text: 'Akıllı dashboard’larınız' }));
  if (!list.length) {
    page.append(h('div', { class: 'empty-state' }, h('p', { text: 'Henüz yok. Yukarıdaki şablonlardan birini seçin; teknik sorgu bilgisi gerekmez.' })));
    return;
  }
  page.append(h('div', { class: 'card-grid' }, list.map((d) => h('a', { class: 'tile', href: `/smart/${d.uid}`, 'data-link': '' },
    h('span', { class: 'tile-icon' }, icon('report')), h('span', h('b', { text: d.title }), h('span', { text: d.folderTitle || 'Genel' }))))));
}

// ---- builder ----------------------------------------------------------------------------------

export async function smartBuilderPage(root, { app, uid }) {
  setBreadcrumbs([{ label: 'Akıllı dashboard', href: '/smart' }, { label: uid ? '…' : 'Yeni' }], root);
  const sources = await datasourcesList();
  const preferred = sources.find((s) => s.type === 'zabbix') || sources.find((s) => s.type === 'testdata') || sources[0];
  const existing = uid ? await get(`/api/dashboards/uid/${encodeURIComponent(uid)}`) : null;
  const meta = existing ? existing.meta : { folderUid: null, canEdit: true };
  const editable = meta.canEdit !== false && ['admin', 'editor'].includes(app.user.role);
  let model = existing ? existing.dashboard : blankModel('Yeni akıllı dashboard', preferred);
  if (!model.smart) model.smart = blankModel('', preferred).smart; // a normal dashboard opened here becomes page-based
  model.tags = [...new Set([...(model.tags || []), SMART_TAG])];
  model.panels ||= [];
  for (const [i, p] of model.panels.entries()) p.smartPos ||= { page: 0, x: 0, y: (i * 8) % model.smart.rows, w: p.gridPos?.w || 12, h: Math.min(model.smart.rows, p.gridPos?.h || 8) };

  if (!uid) {
    const template = TEMPLATES.find((t) => t.id === new URLSearchParams(location.search).get('template'));
    if (template && template.id !== 'blank') {
      model.title = template.name;
      model.smart.filters = template.filters && KEYWORD_SOURCES.includes(preferred?.type);
      if (model.smart.filters) model.templating = { list: filterVariables(preferred) };
      if (template.range) model.time = { ...template.range };
      let seq = 0;
      model.panels = buildTemplate(template, { nextId: () => (seq += 1), datasource: preferred ? { uid: preferred.uid } : undefined, makeTarget: makeTarget(preferred, model.smart.filters), rows: model.smart.rows });
    }
  }

  const draft = drafts.load(model.uid || uid);
  const state = { range: { ...model.time }, resolved: null, now: Date.now(), dirty: false, selected: null, variables: {}, zoom: 'fit', savedAt: existing ? Date.parse(existing.meta.updated) || null : null };
  const history = createHistory(model);
  const views = new Map();
  const dsOf = (panel) => sources.find((s) => s.uid === (panel.datasource?.uid || model.smartSource?.uid)) || preferred;
  const ctx = () => ({ range: state.range, resolvedRange: state.resolved, timezone: model.timezone || 'browser', variables: state.variables, scopedVars: {}, now: state.now, dashboardTitle: model.title });
  const nextId = () => Math.max(0, ...model.panels.map((p) => p.id || 0)) + 1;
  const leaveGuard = () => (state.dirty ? 'Akıllı dashboard’da kaydedilmemiş değişiklikler var. Ayrılmak istiyor musunuz?' : null);
  setLeaveGuard(leaveGuard, root);

  const status = h('span', { class: 'save-status', role: 'status' });
  const undoBtn = button('', { icon: 'history', title: 'Geri al (Ctrl+Z)', onClick: () => undo() });
  const redoBtn = button('', { icon: 'refresh', title: 'Yinele (Ctrl+Y)', onClick: () => redo() });
  const drawStatus = () => {
    status.textContent = state.dirty ? 'Kaydedilmemiş değişiklikler' : state.savedAt ? `Kaydedildi · ${timeAgo(new Date(state.savedAt).toISOString())}` : 'Yeni';
    status.classList.toggle('dirty', state.dirty);
    undoBtn.disabled = !history.canUndo(); redoBtn.disabled = !history.canRedo();
  };
  let draftTimer = null;

  // Every edit goes through change(): mutate, record history, mark dirty, re-render what is affected.
  function change(mutate, { canvas: redraw = true, refresh = null, all = false } = {}) {
    if (!editable) return;
    mutate(model);
    if (!history.push(model)) { drawStatus(); return; }
    state.dirty = true;
    clearTimeout(draftTimer);
    draftTimer = setTimeout(() => drafts.save(model.uid || uid, model), 800);
    if (redraw) canvas.render();
    if (refresh) refreshPanel(refresh);
    if (all) refreshAll();
    inspector.render(); drawStatus();
  }

  function applySnapshot(snapshot) {
    for (const v of views.values()) v.destroy();
    views.clear();
    model = snapshot;
    state.dirty = true;
    canvas.setModel(model);
    inspector.render(); drawStatus(); refreshAll();
  }
  const undo = () => { const s = history.undo(); if (s) applySnapshot(s); };
  const redo = () => { const s = history.redo(); if (s) applySnapshot(s); };

  function view(panel) {
    let entry = views.get(panel.id);
    if (!entry) { entry = new PanelView(panel, ctx(), {}); views.set(panel.id, entry); entry.refresh(); }
    entry.panel = panel;
    entry.setContext(ctx());
    return entry;
  }
  function refreshPanel(panel) { const v = views.get(panel.id); if (v) { v.panel = panel; v.setContext(ctx()); v.refresh(); } }
  async function refreshAll() {
    state.now = Date.now();
    try { const r = await resolveRange(state.range, model.timezone); state.resolved = r ? { from: r.from, to: r.to } : null; } catch { state.resolved = null; }
    for (const p of model.panels) refreshPanel(p);
  }

  const autoTitle = (f) => {
    const pick = (v) => (v && v !== '/.*/' && !v.startsWith('$') ? v.replace(/^\/(.*)\/i$/, '$1').replace(/\\(.)/g, '$1') : '');
    return [pick(f.item), pick(f.host) || pick(f.group)].filter(Boolean).join(' · ') || 'Yeni panel';
  };

  function itemBar(panel) {
    const ds = dsOf(panel);
    const parts = [];
    if (LAYOUT_TYPES.includes(panel.type)) parts.push(h('span', { class: 'smart-kind' }, icon(PLUGINS[panel.type]?.icon || 'panel'), PLUGINS[panel.type]?.name || ''));
    else if (KEYWORD_SOURCES.includes(ds?.type)) {
      parts.push(keywordChips(panel.targets[0] || panel.smartDraft || {}, { dsUid: ds.uid, range: state.range, variables: state.variables, filters: model.smart.filters, onChange: (f) => change(() => {
        const base = panel.targets[0] || panel.smartDraft || makeTarget(ds, model.smart.filters)();
        const t = { ...base, group: { filter: f.group || '/.*/' }, host: { filter: f.host || '/.*/' }, item: { filter: f.item || '' } };
        // Nothing is queried until a keyword (metric) is chosen: "all items of all hosts" is never useful.
        if (f.item) { panel.targets = [t]; delete panel.smartDraft; } else { panel.targets = []; panel.smartDraft = t; }
        if (!panel.titleLocked) panel.title = autoTitle(f);
      }, { refresh: panel }) }));
    } else parts.push(button('Sorgu', { size: 'sm', icon: 'code', onClick: () => editQuery(panel) }));
    if (!LAYOUT_TYPES.includes(panel.type)) {
      parts.push(h('button', { type: 'button', class: ['kw-chip', 'period-chip', panel.timeRange ? 'set' : ''].join(' '), title: 'Bu panelin tarih aralığı (sağ panelden değiştirin)',
        onClick: () => select(panel.id) }, icon('clock'), h('span', { class: 'kw-value', text: panel.timeRange ? rangeLabel(panel.timeRange, model.timezone) : 'Rapor aralığı' })));
    }
    if (editable) parts.push(button('', { size: 'sm', variant: 'ghost', icon: 'copy', title: 'Çoğalt (Ctrl+D)', onClick: () => duplicate(panel) }),
      button('', { size: 'sm', variant: 'ghost', icon: 'trash', title: 'Kaldır (Delete)', onClick: () => removePanel(panel) }));
    return h('div', { class: 'smart-bar-content' }, parts);
  }

  const canvas = createCanvas({
    model,
    editable,
    selectedId: () => state.selected,
    header: (page) => h('header', { class: 'paper-head' },
      model.smart.logo_id && (page === 0 || model.smart.logo_on_pages !== false) ? h('img', { class: 'paper-logo', src: `/api/dash-reports/logos/${encodeURIComponent(model.smart.logo_id)}`, alt: 'Logo' }) : h('span', { class: 'paper-mark', text: 'O' }),
      h('div', { class: 'paper-titles' }, h('b', { text: model.title }), model.smart.subtitle ? h('span', { text: model.smart.subtitle }) : null),
      h('span', { class: 'paper-range', text: `${state.range.from} → ${state.range.to}` })),
    footer: (page) => [h('span', { text: model.smart.footer || 'OpenReporting raporu' }), h('span', { text: `Sayfa ${page + 1} / ${model.smart.pages}` })],
    pageTools: editable ? (page) => h('div', { class: 'page-tools' }, h('span', { text: `Sayfa ${page + 1}` }),
      button('', { size: 'sm', variant: 'ghost', icon: 'arrow-up', title: 'Sayfayı yukarı taşı', disabled: page === 0, onClick: () => movePage(page, -1) }),
      button('', { size: 'sm', variant: 'ghost', icon: 'arrow-down', title: 'Sayfayı aşağı taşı', disabled: page === model.smart.pages - 1, onClick: () => movePage(page, 1) }),
      button('', { size: 'sm', variant: 'ghost', icon: 'copy', title: 'Sayfayı çoğalt', onClick: () => duplicatePage(page) }),
      button('', { size: 'sm', variant: 'ghost', icon: 'trash', title: 'Sayfayı sil', disabled: model.smart.pages === 1, onClick: () => deletePage(page) })) : null,
    renderItem: (panel) => ({ bar: itemBar(panel), el: h('div', { class: 'smart-view-inner' }, view(panel).el,
      panel.smartDraft && !panel.targets.length ? h('div', { class: 'smart-hint' }, icon('search'), h('span', { text: 'Üstteki “Anahtar kelime” kutusundan gösterilecek metriği seçin' })) : null) }),
    onAdd: (type, cell) => addPanel(type, cell),
    onMove: (panel, pos) => change(() => { panel.smartPos = pos; }),
    onSelect: (panel) => select(panel ? panel.id : null),
  });

  function select(id) {
    if (state.selected === id) return;
    state.selected = id;
    for (const el of canvas.el.querySelectorAll('.smart-item')) el.classList.toggle('selected', Number(el.dataset.id) === id);
    inspector.render();
  }

  function addPanel(type, cell = null) {
    if (!editable) return;
    const [w, hgt0] = SIZES[type] || [12, 8];
    const rows = model.smart.rows; const hgt = Math.min(hgt0, rows);
    const start = cell || { page: Math.max(0, model.smart.pages - 1), x: 0, y: 0 };
    const pos = findSpot(model.panels, { page: start.page, x: Math.max(0, Math.min(start.x, COLS - w)), y: Math.max(0, Math.min(start.y, rows - hgt)), w, h: hgt }, rows, model.smart.pages);
    const ds = sources.find((s) => s.uid === model.smartSource?.uid) || preferred;
    const keyword = !LAYOUT_TYPES.includes(type) && KEYWORD_SOURCES.includes(ds?.type);
    const panel = { id: nextId(), type, title: LAYOUT_TYPES.includes(type) ? '' : 'Yeni panel', datasource: ds ? { uid: ds.uid } : undefined,
      targets: LAYOUT_TYPES.includes(type) || keyword ? [] : [makeTarget(ds, false)()], smartDraft: keyword ? makeTarget(ds, model.smart.filters)() : undefined,
      options: { ...(PLUGINS[type]?.defaults?.options || {}), ...(type === 'text' ? { mode: 'markdown', content: '## Başlık\nAçıklama metni' } : {}), ...(type === 'image' && model.smart.logo_id ? { logo_id: model.smart.logo_id } : {}) },
      transparent: PLUGINS[type]?.defaults?.transparent || undefined, fieldConfig: { defaults: {}, overrides: [] }, smartPos: pos };
    change((m) => { if (pos.page >= m.smart.pages) m.smart.pages = pos.page + 1; m.panels.push(panel); });
    select(panel.id);
    if (keyword) toast('Panelin üstündeki “Anahtar kelime” kutusundan ne göstereceğinizi seçin', 'info');
    if (type === 'image' && !model.smart.logo_id) toast('Görseli sağ panelden yükleyin', 'info');
  }

  function duplicate(panel) {
    const copy = { ...JSON.parse(JSON.stringify(panel)), id: nextId() };
    const pos = findSpot(model.panels, { ...panel.smartPos, x: Math.min(COLS - panel.smartPos.w, panel.smartPos.x + panel.smartPos.w) }, model.smart.rows, model.smart.pages);
    copy.smartPos = pos;
    change((m) => { if (pos.page >= m.smart.pages) m.smart.pages = pos.page + 1; m.panels.push(copy); });
    select(copy.id);
  }

  function removePanel(panel) {
    views.get(panel.id)?.destroy(); views.delete(panel.id);
    change((m) => { m.panels = m.panels.filter((p) => p.id !== panel.id); });
    if (state.selected === panel.id) select(null);
  }

  function movePage(page, delta) {
    const other = page + delta;
    change((m) => { for (const p of m.panels) { if (p.smartPos.page === page) p.smartPos.page = other; else if (p.smartPos.page === other) p.smartPos.page = page; } });
  }
  function duplicatePage(page) {
    change((m) => {
      let id = nextId();
      const copies = m.panels.filter((p) => p.smartPos.page === page).map((p) => ({ ...JSON.parse(JSON.stringify(p)), id: id++ }));
      for (const p of m.panels) if (p.smartPos.page > page) p.smartPos.page += 1;
      for (const c of copies) c.smartPos.page = page + 1;
      m.panels.push(...copies); m.smart.pages += 1;
    });
  }
  async function deletePage(page) {
    if (model.panels.some((p) => p.smartPos.page === page) && !(await confirmDialog('Sayfayı sil', `Sayfa ${page + 1} ve üzerindeki öğeler silinecek.`, { danger: true, okText: 'Sil' }))) return;
    change((m) => {
      m.panels = m.panels.filter((p) => p.smartPos.page !== page);
      for (const p of m.panels) if (p.smartPos.page > page) p.smartPos.page -= 1;
      m.smart.pages -= 1;
    });
  }

  function setOrientation(orientation) {
    change((m) => {
      const from = m.smart.rows; const to = ROWS[orientation];
      m.smart.orientation = orientation; m.smart.rows = to;
      for (const p of m.panels) {
        const hgt = Math.max(2, Math.min(to, Math.round((p.smartPos.h * to) / from)));
        p.smartPos = { ...p.smartPos, h: hgt, y: Math.min(to - hgt, Math.round((p.smartPos.y * to) / from)) };
      }
    });
  }

  async function toggleFilters(on) {
    const ds = sources.find((s) => s.uid === model.smartSource?.uid) || preferred;
    if (on && !KEYWORD_SOURCES.includes(ds?.type)) { toast('Rapor filtresi Zabbix veya TestData kaynağıyla çalışır', 'warn'); inspector.render(); return; }
    change((m) => {
      m.smart.filters = on;
      m.templating = { list: on ? filterVariables(ds) : (m.templating?.list || []).filter((v) => !['group', 'host'].includes(v.name)) };
      // Panels that showed "all" follow the report filter when it is switched on, and fall back when it is switched off.
      for (const p of m.panels) for (const t of [...(p.targets || []), ...(p.smartDraft ? [p.smartDraft] : [])]) {
        if (!t.host) continue;
        if (on && t.host.filter === '/.*/' && t.group?.filter === '/.*/') { t.group = { filter: '$group' }; t.host = { filter: '$host' }; }
        if (!on) { if (t.group?.filter === '$group') t.group = { filter: '/.*/' }; if (t.host.filter === '$host') t.host = { filter: '/.*/' }; }
      }
    }, { canvas: false });
    await loadVariables();
    drawFilterBar(); canvas.render(); refreshAll();
  }

  function changeSource(panel, uidValue) {
    const ds = sources.find((s) => s.uid === uidValue);
    change(() => {
      panel.datasource = { uid: uidValue };
      if (KEYWORD_SOURCES.includes(ds?.type)) { panel.targets = []; panel.smartDraft = makeTarget(ds, model.smart.filters)(); } else { panel.targets = [makeTarget(ds, false)()]; delete panel.smartDraft; }
    }, { refresh: panel });
  }
  function changeType(panel, type) {
    views.get(panel.id)?.destroy(); views.delete(panel.id);
    change(() => { panel.type = type; });
  }

  function editQuery(panel) {
    const ds = dsOf(panel);
    let target = { ...(panel.targets[0] || panel.smartDraft || { refId: 'A' }) };
    const dlg = modal({ title: `Sorgu · ${panel.title || PLUGINS[panel.type]?.name}`, size: 'lg', body: h('div', queryEditor(target, ds, ctx(), (t) => { target = t; })),
      footer: [button('Vazgeç', { onClick: () => dlg.close() }), button('Uygula', { variant: 'primary', onClick: () => { dlg.close(); change(() => { panel.targets = [target]; delete panel.smartDraft; }, { refresh: panel }); } })] });
  }

  const inspector = createInspector({ getModel: () => model, getSelected: () => state.selected, sources, preferred, dsOf, change, select, setOrientation, toggleFilters, removePanel, duplicate, editQuery, changeSource, changeType });

  // ---- report filter (variables) ----
  const filterHost = h('div', { class: 'smart-filters' });
  async function loadVariables(overrides) {
    if (!(model.templating?.list || []).length) { state.variables = {}; return; }
    try { state.variables = (await resolveVariables(model, overrides, state.range, model.timezone)).variables || {}; } catch (err) { toast(`Filtre değerleri alınamadı: ${err.message}`, 'error'); }
  }
  function drawFilterBar() {
    clear(filterHost);
    filterHost.hidden = !model.smart.filters;
    if (!model.smart.filters) return;
    const bar = variableBar(model, state.variables, async (name, value) => {
      await loadVariables({ ...currentOverrides(state.variables), [name]: value });
      for (const v of model.templating.list) if (state.variables[v.name]) v.current = { value: state.variables[v.name].value, text: state.variables[v.name].text };
      drawFilterBar(); refreshAll();
    });
    filterHost.append(h('span', { class: 'smart-filters-label' }, icon('filter'), 'Rapor filtresi'), bar || h('span', { class: 'hint', text: 'Değerler yükleniyor…' }));
  }

  // ---- save / export ----
  async function save() {
    if (!editable) return false;
    const body = { ...model, time: { ...state.range }, panels: model.panels.map((p) => ({ ...p, gridPos: { x: p.smartPos.x, y: p.smartPos.page * model.smart.rows + p.smartPos.y, w: p.smartPos.w, h: p.smartPos.h } })) };
    const send = (overwrite) => post('/api/dashboards/db', { dashboard: body, folderUid: meta.folderUid || null, message: 'Akıllı dashboard', overwrite });
    try {
      let res;
      try { res = await send(false); } catch (err) {
        if (!(err instanceof ApiError && err.status === 409 && (await confirmDialog('Çakışma', `${err.message}. Üzerine yazılsın mı?`, { okText: 'Üzerine yaz', danger: true })))) throw err;
        res = await send(true);
      }
      drafts.clear(model.uid || uid); drafts.clear(res.uid);
      model.uid = res.uid; model.version = res.version; state.dirty = false; state.savedAt = Date.now(); invalidate('search');
      drawStatus(); toast('Kaydedildi', 'ok');
      if (!uid) navigate(`/smart/${res.uid}`, { replace: true, force: true });
      return true;
    } catch (err) { toast(err.message, 'error'); return false; }
  }

  async function exportBlob(format, splitByHost) {
    if ((state.dirty || !model.uid) && !(await save())) return null;
    const res = await api('/api/dashboards/export', { method: 'POST', raw: true, body: { dashboard_uid: model.uid, time_range: state.range, timezone: effectiveZone(model.timezone),
      variables: currentOverrides(state.variables), format, split_by: splitByHost ? 'host' : undefined } });
    return res.blob();
  }
  async function exportAs(format, splitByHost = false) {
    toast(`${format.toUpperCase()} hazırlanıyor…`, 'info', 2500);
    try { const blob = await exportBlob(format, splitByHost); if (blob) downloadBlob(`${model.title.replace(/[^\w-]+/g, '_')}${splitByHost ? '_host-bazinda' : ''}.${format}`, blob); } catch (err) { toast(err.message, 'error'); }
  }
  async function preview() {
    const win = window.open('', '_blank');
    preparePreviewWindow(win);
    try {
      const blob = await exportBlob('pdf', false);
      if (!blob) { win?.close(); return; }
      if (win) win.location.href = URL.createObjectURL(blob);
    } catch (err) { win?.close(); toast(err.message, 'error'); }
  }

  // ---- palette ----
  const tool = (type) => h('button', { type: 'button', class: 'smart-tool', draggable: 'true', disabled: !editable,
    onDragstart: (e) => { e.dataTransfer.setData('application/x-smart-viz', type); e.dataTransfer.effectAllowed = 'copy'; },
    onClick: () => addPanel(type) }, icon(PLUGINS[type]?.icon || 'panel'), h('span', { text: PLUGINS[type]?.name || type }));
  const palette = h('aside', { class: 'smart-palette', 'aria-label': 'Öğeler' },
    h('h2', { class: 'section-heading', text: 'Grafikler' }), h('p', { class: 'hint', text: 'Sayfaya sürükleyin veya tıklayın.' }),
    CHART_TYPES.map(tool), h('h2', { class: 'section-heading', text: 'Sayfa öğeleri' }), LAYOUT_TYPES.map(tool));

  // ---- toolbar ----
  const tp = timePicker({ range: state.range, timezone: model.timezone, onChange: (r) => { state.range = r; change((m) => { m.time = { ...r }; }); loadVariables(currentOverrides(state.variables)).then(refreshAll); }, getResolved: () => resolveRange(state.range, model.timezone) });
  const stage = h('div', { class: 'smart-stage' });
  const applyZoom = () => { canvas.el.style.setProperty('--paper-w', state.zoom === 'fit' ? `min(100%, ${PAPER_PX}px)` : `${PAPER_PX * Number(state.zoom)}px`); };
  const zoomSel = select(ZOOMS, state.zoom, (v) => { state.zoom = v; applyZoom(); }, { label: 'Yakınlaştırma', class: 'auto-width' });
  const pdfBtn = button('İndir', { icon: 'download', variant: 'primary', onClick: (e) => menu(e.currentTarget, [
    { label: 'PDF indir', icon: 'download', onClick: () => exportAs('pdf') },
    model.smart.filters && { label: 'PDF · her host için ayrı sayfalar', icon: 'layers', onClick: () => exportAs('pdf', true) },
    { label: 'Excel (veri tabloları)', icon: 'table', onClick: () => exportAs('xlsx') },
    { label: 'CSV', icon: 'list', onClick: () => exportAs('csv') },
  ]) });
  const toolbar = h('div', { class: 'smart-toolbar' },
    h('h1', { class: 'smart-title' }, icon('report'), h('span', { text: model.title })), status, h('span', { class: 'spacer' }),
    editable ? undoBtn : null, editable ? redoBtn : null, zoomSel, tp,
    button('Önizle', { icon: 'eye', onClick: preview }), pdfBtn,
    button('Zamanla', { icon: 'calendar', title: 'Bu raporu e-postayla düzenli gönder', onClick: async () => { if ((state.dirty || !model.uid) && !(await save())) return; navigate(`/reports/new?dashboard=${encodeURIComponent(model.uid)}`); } }),
    model.uid ? button('', { icon: 'apps', title: 'Normal dashboard görünümü', onClick: () => navigate(`/d/${model.uid}`) }) : null,
    editable ? button('Kaydet', { icon: 'save', onClick: save }) : null);

  // ---- keyboard ----
  const onKey = (e) => {
    const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || '') || document.activeElement?.isContentEditable;
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === 's') { e.preventDefault(); save(); return; }
    if (typing || !editable || document.querySelector('.modal-backdrop')) return;
    const panel = model.panels.find((p) => p.id === state.selected);
    if (mod && e.key.toLowerCase() === 'z') { e.preventDefault(); if (e.shiftKey) redo(); else undo(); return; }
    if (mod && e.key.toLowerCase() === 'y') { e.preventDefault(); redo(); return; }
    if (!panel) return;
    if (mod && e.key.toLowerCase() === 'd') { e.preventDefault(); duplicate(panel); return; }
    if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); removePanel(panel); return; }
    if (e.key === 'Escape') { select(null); return; }
    const step = e.shiftKey ? 4 : 1;
    const delta = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key];
    if (delta) {
      e.preventDefault();
      const p = panel.smartPos;
      const next = { ...p, x: Math.max(0, Math.min(COLS - p.w, p.x + delta[0])), y: Math.max(0, Math.min(model.smart.rows - p.h, p.y + delta[1])) };
      if (!canvas.fits(next, panel.id)) return;
      change(() => { panel.smartPos = next; });
    }
  };
  document.addEventListener('keydown', onKey);

  stage.append(filterHost, canvas.el);
  root.append(h('div', { class: 'smart-layout' }, toolbar, h('div', { class: 'smart-main' }, palette, stage, inspector.el)));
  applyZoom();
  if (draft && draft.model && (!state.savedAt || draft.at > state.savedAt) && JSON.stringify(draft.model) !== JSON.stringify(model)) {
    stage.prepend(h('div', { class: 'alert warn draft-banner' }, h('span', { text: `Kaydedilmemiş bir taslak bulundu (${timeAgo(new Date(draft.at).toISOString())}).` }),
      button('Taslağı geri yükle', { size: 'sm', variant: 'primary', onClick: (e) => { e.currentTarget.closest('.draft-banner').remove(); applySnapshot(draft.model); history.push(model); drawFilterBar(); } }),
      button('Sil', { size: 'sm', onClick: (e) => { drafts.clear(model.uid || uid); e.currentTarget.closest('.draft-banner').remove(); } })));
  }
  setBreadcrumbs([{ label: 'Akıllı dashboard', href: '/smart' }, { label: model.title }], root);
  if (!uid && model.panels.length) state.dirty = true;
  await loadVariables();
  drawFilterBar();
  canvas.render();
  inspector.render();
  drawStatus();
  refreshAll();
  const ticker = setInterval(drawStatus, 30000);
  return () => { clearInterval(ticker); clearTimeout(draftTimer); document.removeEventListener('keydown', onKey); for (const v of views.values()) v.destroy(); clearLeaveGuard(leaveGuard); };
}
