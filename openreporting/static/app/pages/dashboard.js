// Dashboard view: grid layout, variables, time range, auto-refresh, drag/resize, save/versioning.
import { h, button, input, select, field, menu, modal, toast, confirmDialog, clear, copyText, downloadBlob, textarea } from '../dom.js';
import { icon } from '../icons.js';
import { api, get, post, del, ApiError, invalidate } from '../api.js';
import { timePicker, refreshPicker, resolveRange, durationMs, effectiveZone, isAbsolute } from '../time.js';
import { resolveVariables, variableBar, urlOverrides, variablesToParams, currentOverrides, interpolate } from '../variables.js';
import { expandLayout, pixelRect, gridHeight, place, compact, toGrid, syncPositions, COLS } from '../dashboard/layout.js';
import { PanelView } from '../dashboard/panelview.js';
import { openPanelEditor } from '../dashboard/editor.js';
import { openSettings } from '../dashboard/settings.js';
import { dashboardOverview } from '../dashboard/overview.js';
import { newPanel, PLUGINS, ORDER } from '../panels/registry.js';
import { navigate, setLeaveGuard, clearLeaveGuard, setBreadcrumbs } from '../router.js';

let groupSeq = 0;

export async function dashboardPage(root, { uid, query, app }) {
  const params = new URLSearchParams(query || '');
  const canEdit = ['admin', 'editor'].includes(app.user.role);
  let dash; let meta;
  if (uid) {
    try {
      const res = await get(`/api/dashboards/uid/${encodeURIComponent(uid)}`);
      dash = res.dashboard; meta = res.meta;
    } catch (err) {
      root.replaceChildren(h('div', { class: 'page' }, h('div', { class: 'alert error', text: err.message }), button('Dashboard listesine dön', { onClick: () => navigate('/dashboards') })));
      return () => {};
    }
    if (!root.isConnected) return () => {}; // the user already left this page
  } else {
    const imported = app.pendingDashboard;
    app.pendingDashboard = null;
    dash = imported || { title: 'Yeni dashboard', uid: '', tags: [], timezone: 'browser', refresh: '', time: { from: 'now-6h', to: 'now' }, templating: { list: [] }, panels: [], editable: true };
    meta = { folderUid: params.get('folderUid') || null, canEdit, version: 0, isNew: true };
  }
  const state = {
    range: { from: params.get('from') || dash.time?.from || 'now-6h', to: params.get('to') || dash.time?.to || 'now' },
    refresh: params.has('refresh') ? params.get('refresh') : (dash.refresh || ''),
    variables: {}, views: new Map(), items: [], dirty: !uid, now: Date.now(), resolved: null,
    viewPanel: params.get('viewPanel'), kiosk: params.has('kiosk'), group: `dash-${++groupSeq}`, timer: null, destroyed: false,
  };
  if (state.kiosk) document.body.classList.add('kiosk');
  const editable = () => canEdit && dash.editable !== false && !state.viewPanel;
  const markDirty = () => { state.dirty = true; saveBtn && saveBtn.classList.add('primary'); drawOverview(); };
  const leaveGuard = () => (state.dirty && canEdit ? 'Dashboard’da kaydedilmemiş değişiklikler var. Sayfadan ayrılmak istiyor musunuz?' : null);
  setLeaveGuard(leaveGuard, root);

  const page = h('div', { class: ['dash-page', state.viewPanel ? 'view-panel-mode' : ''].join(' ') });
  const toolbar = h('div', { class: 'dash-toolbar' });
  const overview = h('div', { class: 'overview-host' });
  const varHost = h('div');
  const grid = h('div', { class: ['dash-grid', editable() ? 'editable' : ''].join(' ') });
  page.append(overview, toolbar, varHost, grid);
  root.replaceChildren(page);

  const updateUrl = () => {
    if (state.destroyed || !root.isConnected) return;
    const p = new URLSearchParams();
    p.set('from', state.range.from); p.set('to', state.range.to);
    if (state.refresh) p.set('refresh', state.refresh);
    variablesToParams(state.variables, p);
    if (state.viewPanel) p.set('viewPanel', state.viewPanel);
    if (state.kiosk) p.set('kiosk', '');
    const path = dash.uid && !meta.isNew ? `/d/${dash.uid}` : location.pathname;
    history.replaceState(history.state, '', `${path}?${p.toString().replace(/kiosk=(&|$)/, 'kiosk$1')}`);
  };

  const savedUid = () => (dash.uid && !meta.isNew ? dash.uid : null);
  const ctxFor = (item) => ({ range: state.range, timezone: dash.timezone, variables: state.variables, scopedVars: item ? item.scopedVars : {},
    dashboardUid: savedUid(), dashboardTitle: dash.title, now: state.now, group: dash.graphTooltip ? state.group : null, resolvedRange: state.resolved, editable: editable(),
    onZoom: (from, to) => setRange({ from: String(from), to: String(to) }) });

  const observer = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      const view = [...state.views.values()].find((v) => v.el === e.target);
      if (view && view.needsRefresh) { view.needsRefresh = false; view.refresh(); }
    }
  }, { rootMargin: '200px' });

  // Only the latest resolution wins; an older, slower response must not overwrite newer selections.
  let variablesSeq = 0;
  async function loadVariables(overrides) {
    const seq = ++variablesSeq;
    if (!((dash.templating || {}).list || []).length) { state.variables = {}; return; }
    try {
      const res = await resolveVariables(dash, overrides, state.range, dash.timezone, savedUid());
      if (seq !== variablesSeq || state.destroyed) return;
      state.variables = res.variables || {};
      for (const w of res.warnings || []) toast(w, 'warn');
    } catch (err) { if (seq === variablesSeq && !state.destroyed) toast(`Değişkenler çözümlenemedi: ${err.message}`, 'error'); }
  }

  function drawVariables() {
    clear(varHost);
    const bar = variableBar(dash, state.variables, async (name, value) => {
      const overrides = { ...currentOverrides(state.variables), [name]: value };
      // Dependent variables re-resolve on the server from these overrides.
      const seq = variablesSeq + 1;
      await loadVariables(overrides);
      if (seq !== variablesSeq || state.destroyed) return;
      drawVariables(); updateUrl(); layout(true);
    });
    if (bar) varHost.append(bar);
  }

  function itemKey(item) { return `${item.panel.id}:${item.repeatIndex}`; }

  function rowElement(item) {
    const row = item.panel;
    const count = row.collapsed ? (row.panels || []).length : null;
    const el = h('div', { class: 'row-panel', role: 'button', tabindex: '0', 'aria-expanded': String(!row.collapsed),
      onclick: (e) => { if (!e.target.closest('button')) toggleRow(row); },
      onkeydown: (e) => {
        if ((e.key !== 'Enter' && e.key !== ' ') || e.target !== el) return;
        e.preventDefault();
        toggleRow(row);
        // layout() rebuilt the row element; keep keyboard focus on it.
        const again = grid.querySelector(`[data-key="${CSS.escape(itemKey(item))}"] .row-panel`);
        if (again) again.focus();
      } },
      icon(row.collapsed ? 'chevron-right' : 'chevron-down'), h('span', { text: item.title || 'Satır' }),
      count !== null ? h('span', { class: 'row-count', text: `(${count} panel)` }) : null,
      editable() && !item.isRepeatClone ? h('span', { class: 'row-actions' },
        button('', { icon: 'settings', variant: 'ghost', size: 'sm', title: 'Satır ayarları', onClick: () => rowSettings(row) }),
        button('', { icon: 'trash', variant: 'ghost', size: 'sm', title: 'Satırı sil', onClick: () => removeRow(row) })) : null);
    return el;
  }

  function layout(refreshAll = false) {
    const width = grid.clientWidth || root.clientWidth || 1200;
    let items = expandLayout(dash, state.variables);
    if (state.viewPanel) {
      const target = items.find((i) => String(i.panel.id) === String(state.viewPanel) || `${i.panel.id}:${i.repeatIndex}` === state.viewPanel);
      items = target ? [{ ...target, pos: { x: 0, y: 0, w: COLS, h: Math.max(8, Math.floor((window.innerHeight - 190) / 38)) } }] : [];
    }
    state.items = items;
    const keep = new Set(items.map(itemKey));
    for (const [key, view] of state.views) if (!keep.has(key)) { observer.unobserve(view.el); view.destroy(); state.views.delete(key); }
    const wrappers = new Map();
    for (const node of [...grid.children]) wrappers.set(node.dataset.key, node);
    const mobile = width < 700;
    grid.classList.toggle('mobile', mobile);
    for (const item of items) {
      const key = itemKey(item);
      let wrapper = wrappers.get(key);
      if (!wrapper) {
        wrapper = h('div', { class: 'grid-item', dataset: { key } });
        grid.append(wrapper);
      }
      wrappers.delete(key);
      const rect = pixelRect(item.pos, width);
      Object.assign(wrapper.style, mobile ? { transform: 'none', width: '100%', height: `${rect.height}px` } : { transform: `translate(${rect.left}px, ${rect.top}px)`, width: `${rect.width}px`, height: `${rect.height}px` });
      if (item.panel.type === 'row') {
        wrapper.replaceChildren(rowElement(item));
        continue;
      }
      let view = state.views.get(key);
      if (!view) {
        view = new PanelView(item.panel, ctxFor(item), panelActions(item));
        state.views.set(key, view);
        wrapper.replaceChildren(view.el);
        attachDrag(view, item, wrapper);
        observer.observe(view.el);
        view.needsRefresh = true;
      } else {
        view.panel = item.panel;
        view.setContext(ctxFor(item));
        if (refreshAll) { view.needsRefresh = true; observer.unobserve(view.el); observer.observe(view.el); }
      }
    }
    for (const node of wrappers.values()) node.remove();
    grid.style.height = mobile ? 'auto' : `${gridHeight(items) + 8}px`;
    if (!items.length) {
      grid.style.height = 'auto';
      grid.replaceChildren(h('div', { class: 'empty-state' }, h('h3', { text: 'Bu dashboard boş' }),
        h('p', { text: canEdit ? 'İlk paneli ekleyerek başlayın. Zabbix grup/host/item sorguları, ifadeler ve dönüşümler kullanabilirsiniz.' : 'Henüz panel eklenmemiş.' }),
        canEdit ? h('div', { class: 'toolbar' }, button('Görselleştirme ekle', { icon: 'plus', variant: 'primary', onClick: () => addPanel('timeseries') }),
          button('Satır ekle', { icon: 'row', onClick: addRow }), button('Dashboard içe aktar', { icon: 'import', onClick: () => navigate('/dashboards/import') })) : null));
    }
  }

  let rangeSeq = 0;
  function refreshAll() {
    state.now = Date.now();
    const seq = ++rangeSeq;
    resolveRange(state.range, dash.timezone, state.now).then((r) => { if (seq === rangeSeq) state.resolved = r; }).catch(() => {});
    for (const view of state.views.values()) { view.setContext({ now: state.now }); view.needsRefresh = true; observer.unobserve(view.el); observer.observe(view.el); }
  }

  async function setRange(range) {
    state.range = range;
    tp.setRange(range);
    updateUrl();
    if (((dash.templating || {}).list || []).some((v) => Number(v.refresh) === 2)) {
      await loadVariables(currentOverrides(state.variables));
      if (state.destroyed || state.range !== range) return;
      drawVariables();
    }
    for (const view of state.views.values()) view.setContext({ range });
    layout(false);
    refreshAll();
  }

  function setAutoRefresh(interval) {
    state.refresh = interval;
    clearInterval(state.timer);
    const ms = durationMs(interval);
    if (ms >= 5000) state.timer = setInterval(() => { if (!document.hidden) refreshAll(); }, ms);
    updateUrl();
  }

  function findPanelLocation(panelId) {
    for (const [i, p] of dash.panels.entries()) {
      if (p.id === panelId) return { list: dash.panels, index: i };
      if (p.type === 'row' && p.collapsed) {
        const j = (p.panels || []).findIndex((c) => c.id === panelId);
        if (j >= 0) return { list: p.panels, index: j };
      }
    }
    return null;
  }

  const nextId = () => 1 + Math.max(0, ...dash.panels.flatMap((p) => [p.id, ...(p.panels || []).map((c) => c.id)]).filter(Number.isFinite));

  // Views outlive layout passes, so actions resolve the item by key when they run, never from creation time.
  const liveItem = (key) => state.items.find((i) => itemKey(i) === key) || null;
  const livePanel = (key, fallback) => { const it = liveItem(key); return it ? it.panel : fallback; };

  function panelActions(item) {
    const key = itemKey(item);
    const editableItem = editable() && !item.isRepeatClone;
    return {
      onView: () => { state.viewPanel = String(livePanel(key, item.panel).id); updateUrl(); rerenderAll(); },
      onEdit: canEdit ? () => editPanel(livePanel(key, item.panel)) : null,
      onShare: () => sharePanel(livePanel(key, item.panel)),
      onDuplicate: editableItem ? () => {
        const panel = livePanel(key, item.panel);
        const copy = { ...JSON.parse(JSON.stringify(panel)), id: nextId(), gridPos: { ...panel.gridPos, y: panel.gridPos.y + panel.gridPos.h } };
        dash.panels.push(copy); markDirty(); layout(true);
      } : null,
      onCopyJson: () => copyText(JSON.stringify(livePanel(key, item.panel), null, 2)),
      onRemove: editableItem ? async () => {
        const panel = livePanel(key, item.panel);
        if (!(await confirmDialog('Paneli kaldır', `"${panel.title || 'Panel'}" kaldırılsın mı?`, { okText: 'Kaldır', danger: true }))) return;
        const loc = findPanelLocation(panel.id);
        if (loc) loc.list.splice(loc.index, 1);
        markDirty(); layout(false);
      } : null,
      onResizeStart: editableItem ? (e) => startResize(e, key) : null,
    };
  }

  function attachDrag(view, created, wrapper) {
    if (!editable() || created.isRepeatClone) return;
    const key = itemKey(created);
    view.header.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 || e.target.closest('button') || window.innerWidth < 700) return;
      const item = liveItem(key);
      if (!item || !editable()) return;
      e.preventDefault();
      const width = grid.clientWidth;
      const start = { x: e.clientX, y: e.clientY };
      const rect = pixelRect(item.pos, width);
      const items = state.items.filter((i) => !i.isRepeatClone || i === item);
      let moved = false;
      const placeholder = h('div', { class: 'grid-placeholder' });
      const move = (ev) => {
        const dx = ev.clientX - start.x; const dy = ev.clientY - start.y;
        if (!moved && Math.abs(dx) + Math.abs(dy) < 6) return;
        if (!moved) { moved = true; wrapper.classList.add('dragging'); grid.append(placeholder); }
        wrapper.style.transform = `translate(${rect.left + dx}px, ${rect.top + dy}px)`;
        const target = toGrid(rect.left + dx, rect.top + dy, width);
        place(items, item, { ...item.pos, x: target.x, y: Math.max(0, target.y) });
        const pr = pixelRect(item.pos, width);
        Object.assign(placeholder.style, { transform: `translate(${pr.left}px, ${pr.top}px)`, width: `${pr.width}px`, height: `${pr.height}px` });
        for (const other of items) {
          if (other === item) continue;
          const node = grid.querySelector(`[data-key="${CSS.escape(itemKey(other))}"]`);
          const r = pixelRect(other.pos, width);
          if (node) node.style.transform = `translate(${r.left}px, ${r.top}px)`;
        }
      };
      const up = () => {
        document.removeEventListener('pointermove', move); document.removeEventListener('pointerup', up);
        placeholder.remove(); wrapper.classList.remove('dragging');
        if (!moved) return;
        compact(items, { prefer: item });
        syncPositions(items);
        markDirty(); layout(false);
      };
      document.addEventListener('pointermove', move); document.addEventListener('pointerup', up);
    });
  }

  function startResize(e, key) {
    const item = liveItem(key);
    const wrapper = grid.querySelector(`[data-key="${CSS.escape(key)}"]`);
    if (!item || !wrapper || !editable()) return;
    e.preventDefault(); e.stopPropagation();
    const width = grid.clientWidth;
    const startPos = { ...item.pos };
    const start = { x: e.clientX, y: e.clientY };
    const rect = pixelRect(item.pos, width);
    const items = state.items.filter((i) => !i.isRepeatClone || i === item);
    wrapper.classList.add('resizing');
    const move = (ev) => {
      const w = Math.max(80, rect.width + ev.clientX - start.x); const hh = Math.max(60, rect.height + ev.clientY - start.y);
      wrapper.style.width = `${w}px`; wrapper.style.height = `${hh}px`;
      const cell = toGrid(w, hh, width);
      place(items, item, { ...startPos, w: Math.max(1, Math.min(COLS - startPos.x, cell.x)), h: Math.max(2, cell.y) });
      for (const other of items) {
        if (other === item) continue;
        const node = grid.querySelector(`[data-key="${CSS.escape(itemKey(other))}"]`);
        const r = pixelRect(other.pos, width);
        if (node) node.style.transform = `translate(${r.left}px, ${r.top}px)`;
      }
    };
    const up = () => {
      document.removeEventListener('pointermove', move); document.removeEventListener('pointerup', up);
      wrapper.classList.remove('resizing');
      compact(items, { prefer: item }); syncPositions(items); markDirty(); layout(false);
    };
    document.addEventListener('pointermove', move); document.addEventListener('pointerup', up);
  }

  function toggleRow(row) {
    const sorted = [...dash.panels].sort((a, b) => a.gridPos.y - b.gridPos.y || a.gridPos.x - b.gridPos.x);
    const index = sorted.indexOf(row);
    if (row.collapsed) {
      // Children keep their relative layout; everything below the row moves down by their block height.
      const children = row.panels || [];
      let base = Infinity; let bottom = 0;
      for (const c of children) { base = Math.min(base, c.gridPos.y); bottom = Math.max(bottom, c.gridPos.y + c.gridPos.h); }
      const height = children.length ? bottom - base : 0;
      for (const p of sorted.slice(index + 1)) p.gridPos = { ...p.gridPos, y: p.gridPos.y + height };
      for (const c of children) dash.panels.push({ ...c, gridPos: { ...c.gridPos, y: row.gridPos.y + 1 + (c.gridPos.y - base) } });
      row.panels = [];
      row.collapsed = false;
    } else {
      const members = [];
      for (const p of sorted.slice(index + 1)) { if (p.type === 'row') break; members.push(p); }
      row.panels = members;
      dash.panels = dash.panels.filter((p) => !members.includes(p));
      row.collapsed = true;
    }
    if (canEdit) markDirty();
    // Panels that stay visible keep their data; newly shown ones load when they scroll into view.
    layout(false);
  }

  async function rowSettings(row) {
    const titleIn = input({ value: row.title || '' });
    const vars = ((dash.templating || {}).list || []).map((v) => v.name);
    const repeatSel = select([{ value: '', label: 'Tekrarlama yok' }, ...vars.map((v) => ({ value: v, label: `$${v}` }))], row.repeat || '', () => {});
    const dlg = modal({ title: 'Satır ayarları', body: [field('Başlık', titleIn), field('Değişkene göre tekrarla', repeatSel, 'Örn. $host: her host için bu satır ve altındaki paneller tekrarlanır (host bazlı grup raporu).')],
      footer: [button('Vazgeç', { onClick: () => dlg.close() }), button('Uygula', { variant: 'primary', onClick: () => { row.title = titleIn.value; row.repeat = repeatSel.value || undefined; dlg.close(); markDirty(); layout(true); } })] });
  }

  async function removeRow(row) {
    const keepPanels = await confirmDialog('Satırı sil', 'Satır silinsin mi? Satırdaki paneller korunur ve bir üst seviyeye taşınır.', { okText: 'Satırı sil', danger: true });
    if (!keepPanels) return;
    if (row.collapsed) for (const c of row.panels || []) dash.panels.push(c);
    dash.panels = dash.panels.filter((p) => p !== row);
    markDirty(); layout(true);
  }

  function addPanel(type = 'timeseries') {
    for (const p of dash.panels) p.gridPos = { ...p.gridPos, y: p.gridPos.y + 8 };
    const panel = newPanel(type, nextId(), { x: 0, y: 0, w: 12, h: 8 });
    dash.panels.push(panel);
    markDirty(); layout(true);
    editPanel(panel, true);
  }

  function addRow() {
    const bottom = dash.panels.reduce((m, p) => Math.max(m, p.gridPos.y + p.gridPos.h), 0);
    dash.panels.push({ id: nextId(), type: 'row', title: 'Yeni satır', collapsed: false, gridPos: { x: 0, y: bottom, w: 24, h: 1 }, panels: [] });
    markDirty(); layout(true);
  }

  function editPanel(panel, isNew = false) {
    if (state.editor) state.editor.close();
    const vars = ((dash.templating || {}).list || []).map((v) => v.name);
    state.editor = openPanelEditor({ panel, dashboard: dash, ctx: ctxFor(null), variablesList: vars,
      onApply: (updated) => {
        state.editor = null;
        const loc = findPanelLocation(panel.id);
        if (loc) loc.list[loc.index] = updated;
        markDirty();
        const key = [...state.views.keys()].filter((k) => k.startsWith(`${panel.id}:`));
        for (const k of key) { const v = state.views.get(k); observer.unobserve(v.el); v.destroy(); state.views.delete(k); }
        layout(true);
      },
      // "Vazgeç" on a panel that was just added removes it again instead of leaving an empty panel behind.
      onCancel: () => {
        state.editor = null;
        if (!isNew) return;
        const loc = findPanelLocation(panel.id);
        if (loc) loc.list.splice(loc.index, 1);
        layout(false);
      },
      onSave: canEdit ? () => saveDashboard() : null });
  }

  function sharePanel(panel) {
    const url = new URL(location.href);
    url.searchParams.set('viewPanel', panel.id);
    shareDialog(url.toString(), `Panel: ${panel.title || ''}`);
  }

  function shareDialog(base, title) {
    let absolute = false;
    const out = input({ value: base, readonly: true });
    const build = async () => {
      const url = new URL(base);
      if (absolute && state.resolved) { url.searchParams.set('from', state.resolved.from); url.searchParams.set('to', state.resolved.to); }
      out.value = url.toString();
    };
    const dlg = modal({ title: `Paylaş · ${title}`, body: [field('Bağlantı', out), h('label', { class: 'switch' }, h('input', { type: 'checkbox', onchange: (e) => { absolute = e.target.checked; build(); } }), h('span', { class: 'track' }), h('span', { text: 'Zaman aralığını sabitle (mutlak zaman)' })),
      h('p', { class: 'hint', style: { marginTop: '10px' }, text: 'Bağlantıyı açan kişinin oturum açmış olması ve yetkisi olması gerekir.' })],
    footer: [button('Kapat', { onClick: () => dlg.close() }), button('Bağlantıyı kopyala', { variant: 'primary', icon: 'copy', onClick: () => copyText(out.value) })] });
  }

  async function saveDashboard({ saveAs = false } = {}) {
    if (!canEdit) return;
    const isNew = meta.isNew || saveAs;
    const titleIn = input({ value: saveAs ? `${dash.title} (kopya)` : dash.title });
    const folders = await get('/api/folders').catch(() => []);
    const folderSel = select([{ value: '', label: 'Genel' }, ...folders.map((f) => ({ value: f.uid, label: f.title }))], meta.folderUid || '', () => {});
    const message = textarea({ rows: 2, placeholder: 'Değişiklik notu (isteğe bağlı)' });
    const saveDefaults = h('label', { class: 'switch' }, h('input', { type: 'checkbox' }), h('span', { class: 'track' }), h('span', { text: 'Geçerli zaman aralığını ve değişkenleri varsayılan yap' }));
    const doSave = async (overwrite = false) => {
      const body = JSON.parse(JSON.stringify(dash));
      body.title = titleIn.value.trim() || body.title;
      if (saveAs) { body.uid = ''; delete body.version; }
      if (saveDefaults.querySelector('input').checked) {
        body.time = { ...state.range };
        body.refresh = state.refresh;
        for (const v of (body.templating || {}).list || []) if (state.variables[v.name]) v.current = { value: state.variables[v.name].value, text: state.variables[v.name].text };
      }
      try {
        const res = await post('/api/dashboards/db', { dashboard: body, folderUid: folderSel.value || null, message: message.value, overwrite });
        dlg.close();
        state.dirty = false;
        invalidate('search');
        toast('Dashboard kaydedildi', 'ok');
        if (isNew || res.uid !== dash.uid) navigate(`/d/${res.uid}`, { replace: true, force: true });
        else { dash.version = res.version; dash.title = body.title; meta.version = res.version; meta.folderUid = folderSel.value || null; saveBtn.classList.remove('primary'); drawToolbar(); }
      } catch (err) {
        if (err instanceof ApiError && err.status === 409 && !overwrite) {
          if (await confirmDialog('Çakışma', `${err.message}. Yine de üzerine yazılsın mı?`, { okText: 'Üzerine yaz', danger: true })) doSave(true);
        } else toast(err.message, 'error');
      }
    };
    const dlg = modal({ title: isNew ? 'Dashboard’u kaydet' : 'Değişiklikleri kaydet', body: [field('Başlık', titleIn), field('Klasör', folderSel), isNew ? null : field('Not', message), saveDefaults],
      footer: [button('Vazgeç', { onClick: () => dlg.close() }), button('Kaydet', { variant: 'primary', icon: 'save', onClick: () => doSave(false) })] });
  }

  async function restoreVersion(version) {
    try {
      await post(`/api/dashboards/uid/${encodeURIComponent(dash.uid)}/restore`, { version });
      state.dirty = false;
      toast(`Sürüm ${version} geri yüklendi`, 'ok');
      navigate(`/d/${dash.uid}`, { replace: true, force: true });
    } catch (err) { toast(err.message, 'error'); }
  }

  async function exportAs(format) {
    toast(`${format.toUpperCase()} hazırlanıyor…`, 'info', 2500);
    try {
      const res = await api('/api/dashboards/export', { method: 'POST', raw: true, body: { dashboard_uid: dash.uid, time_range: state.range,
        timezone: effectiveZone(dash.timezone), variables: currentOverrides(state.variables), format } });
      downloadBlob(`${dash.title.replace(/[^\w-]+/g, '_')}.${format}`, await res.blob());
    } catch (err) { toast(err.message, 'error'); }
  }

  let saveBtn; let tp; let rp;
  function drawOverview() {
    overview.replaceChildren(dashboardOverview({ dashboard: dash, folder: meta.folderTitle, dirty: state.dirty,
      canEdit: editable(), saved: !!savedUid(), onExport: exportAs,
      onReport: () => navigate(`/reports/new?dashboard=${encodeURIComponent(dash.uid)}`), onAdd: () => addPanel('timeseries') }));
    overview.hidden = !!state.viewPanel;
  }
  function drawToolbar() {
    drawOverview();
    clear(toolbar);
    const starBtn = meta.isNew ? null : button('', { icon: 'star', variant: 'ghost', class: meta.isStarred ? 'star-on' : '', title: meta.isStarred ? 'Yıldızı kaldır' : 'Yıldızla', onClick: async () => {
      try {
        if (meta.isStarred) await del(`/api/user/stars/dashboard/${encodeURIComponent(dash.uid)}`); else await post(`/api/user/stars/dashboard/${encodeURIComponent(dash.uid)}`);
        meta.isStarred = !meta.isStarred; drawToolbar(); invalidate('search');
      } catch (err) { toast(err.message, 'error'); }
    } });
    const titleBox = h('div', { class: 'dash-title' }, h('span', { class: 'folder hide-kiosk', text: `${meta.folderTitle || 'Genel'} /` }), h('span', { class: 't', text: dash.title, title: dash.title }), starBtn,
      state.viewPanel ? button('Dashboard’a dön', { size: 'sm', icon: 'arrow-up', onClick: () => { state.viewPanel = null; updateUrl(); rerenderAll(); } }) : null);
    tp = timePicker({ range: state.range, timezone: dash.timezone, onChange: setRange, getResolved: async () => state.resolved || (state.resolved = await resolveRange(state.range, dash.timezone, state.now)) });
    rp = refreshPicker({ value: state.refresh, onRefresh: refreshAll, onInterval: setAutoRefresh });
    saveBtn = canEdit ? button('Kaydet', { icon: 'save', class: state.dirty ? 'primary hide-kiosk' : 'hide-kiosk', onClick: () => saveDashboard() }) : null;
    const addBtn = canEdit && !state.viewPanel ? button('Ekle', { icon: 'plus', class: 'hide-kiosk', onClick: (e) => menu(e.currentTarget, [
      { title: 'Görselleştirme' }, ...ORDER.map((type) => ({ label: PLUGINS[type].name, icon: PLUGINS[type].icon, onClick: () => addPanel(type) })),
      { sep: true }, { label: 'Satır', icon: 'row', onClick: addRow },
      { label: 'Panoya kopyalanan paneli yapıştır', icon: 'copy', onClick: async () => {
        try { const text = await navigator.clipboard.readText(); const p = JSON.parse(text); p.id = nextId(); p.gridPos = { x: 0, y: 0, w: p.gridPos?.w || 12, h: p.gridPos?.h || 8 }; dash.panels.forEach((x) => { x.gridPos.y += p.gridPos.h; }); dash.panels.push(p); markDirty(); layout(true); }
        catch { toast('Panoda geçerli panel JSON’u yok', 'error'); }
      } }]) }) : null;
    const more = button('', { icon: 'dots', title: 'Diğer', class: 'hide-kiosk', onClick: (e) => menu(e.currentTarget, [
      !meta.isNew && { label: 'Paylaş', icon: 'share', onClick: () => shareDialog(location.href, dash.title) },
      { label: 'JSON dışa aktar', icon: 'download', onClick: () => downloadBlob(`${dash.title.replace(/[^\w-]+/g, '_')}.json`, JSON.stringify({ ...dash, id: undefined }, null, 2), 'application/json') },
      !meta.isNew && { label: 'PDF olarak indir', icon: 'download', onClick: () => exportAs('pdf') },
      !meta.isNew && { label: 'Excel olarak indir', icon: 'download', onClick: () => exportAs('xlsx') },
      !meta.isNew && { label: 'Bu dashboard’dan rapor oluştur', icon: 'report', onClick: () => navigate(`/reports/new?dashboard=${encodeURIComponent(dash.uid)}`) },
      { label: 'TV / kiosk modu', icon: 'tv', onClick: () => { state.kiosk = true; document.body.classList.add('kiosk'); updateUrl(); toast('Kiosk modundan çıkmak için Esc', 'info'); } },
      { label: 'Yazdır', icon: 'download', onClick: () => window.print() },
      canEdit && !meta.isNew && { label: 'Farklı kaydet…', icon: 'save', onClick: () => saveDashboard({ saveAs: true }) },
      canEdit && !meta.isNew && { sep: true },
      canEdit && !meta.isNew && { label: 'Dashboard’u sil', icon: 'trash', onClick: async () => {
        if (!(await confirmDialog('Dashboard’u sil', `"${dash.title}" ve tüm sürümleri silinecek.`, { okText: 'Sil', danger: true }))) return;
        try { await del(`/api/dashboards/uid/${encodeURIComponent(dash.uid)}`); state.dirty = false; invalidate('search'); toast('Silindi', 'ok'); navigate('/dashboards'); } catch (err) { toast(err.message, 'error'); }
      } },
    ], { align: 'right' }) });
    const settingsBtn = canEdit ? button('', { icon: 'settings', title: 'Dashboard ayarları', class: 'hide-kiosk', onClick: () => openSettings({ dashboard: dash, meta,
      onApply: async (updated, folderUid) => {
        const before = JSON.stringify(dash.templating);
        dash = { ...updated, uid: dash.uid, version: dash.version };
        meta.folderUid = folderUid;
        markDirty(); drawToolbar();
        if (JSON.stringify(dash.templating) !== before) { await loadVariables(currentOverrides(state.variables)); drawVariables(); }
        layout(true); refreshAll();
      }, onRestore: restoreVersion }) }) : null;
    toolbar.append(...[titleBox, addBtn, saveBtn, settingsBtn, more, tp, rp].filter(Boolean));
    setBreadcrumbs([{ label: 'Dashboard’lar', href: '/dashboards' }, { label: meta.folderTitle || 'Genel' }, { label: dash.title }], root);
  }

  function rerenderAll() {
    for (const view of state.views.values()) view.destroy();
    state.views.clear();
    clear(grid);
    page.classList.toggle('view-panel-mode', !!state.viewPanel);
    grid.classList.toggle('editable', editable());
    drawToolbar();
    layout(true);
  }

  const onResize = () => layout(false);
  const onKey = (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's' && canEdit && !document.querySelector('.editor-shell')) { e.preventDefault(); saveDashboard(); }
    if (e.key === 'Escape' && !document.querySelector('.modal-backdrop,.menu,.editor-shell')) {
      if (state.kiosk) { state.kiosk = false; document.body.classList.remove('kiosk'); updateUrl(); }
      else if (state.viewPanel) { state.viewPanel = null; updateUrl(); rerenderAll(); }
    }
  };
  window.addEventListener('resize', onResize);
  document.addEventListener('keydown', onKey);

  const cleanup = () => {
    state.destroyed = true;
    if (state.editor) { state.editor.close(); state.editor = null; }
    clearInterval(state.timer);
    observer.disconnect();
    for (const view of state.views.values()) view.destroy();
    window.removeEventListener('resize', onResize);
    document.removeEventListener('keydown', onKey);
    document.body.classList.remove('kiosk');
    clearLeaveGuard(leaveGuard);
  };

  await loadVariables(urlOverrides(query || '', dash));
  if (!root.isConnected) { cleanup(); return () => {}; }
  drawToolbar();
  drawVariables();
  updateUrl();
  layout(true);
  refreshAll();
  setAutoRefresh(state.refresh);
  const editId = params.get('editPanel');
  if (editId && canEdit) { const loc = findPanelLocation(Number(editId)); if (loc) editPanel(loc.list[loc.index]); }
  return cleanup;
}

export { isAbsolute, effectiveZone, interpolate };
