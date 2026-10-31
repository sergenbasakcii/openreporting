// Panel chrome + data lifecycle shared by dashboards, the panel editor and Explore.
import { h, button, menu, toast, downloadBlob } from '../dom.js';
import { icon } from '../icons.js';
import { post, ApiError } from '../api.js';
import { plugin, withDefaults } from '../panels/registry.js';
import { effectiveZone, isAbsolute, durationMs } from '../time.js';
import { interpolate, requestVariables } from '../variables.js';
import { formatValue } from '../units.js';

function shiftRaw(value, shift) {
  if (!shift) return value;
  if (isAbsolute(value)) return String(Number(value) - durationMs(shift));
  return `${value}-${shift}`;
}

export function panelRange(panel, range) {
  let r = { ...range };
  if (panel.timeFrom) r = { from: `now-${panel.timeFrom}`, to: 'now' };
  if (panel.timeShift) r = { from: shiftRaw(r.from, panel.timeShift), to: shiftRaw(r.to, panel.timeShift) };
  return r;
}

export function buildRequest(panel, ctx, width = 800) {
  const variables = requestVariables({ ...(ctx.variables || {}), ...(ctx.scopedVars || {}) });
  // Saved-dashboard panels name themselves so viewer queries run the stored definition server-side.
  const saved = ctx.dashboardUid && Number.isFinite(Number(panel.id)) ? { dashboardUid: ctx.dashboardUid, panelId: Number(panel.id) } : {};
  return {
    ...saved,
    targets: (panel.targets || []).map((t) => ({ ...t, datasource: t.datasource || panel.datasource || undefined })),
    datasource: panel.datasource || undefined,
    range: panelRange(panel, ctx.range),
    timezone: effectiveZone(ctx.timezone),
    maxDataPoints: Math.max(50, Math.min(Number(panel.maxDataPoints) || Math.round(width) || 1000, 5000)),
    minInterval: panel.interval || null,
    variables,
    transformations: panel.transformations || [],
    dashboardTitle: ctx.dashboardTitle || '',
    now: ctx.now,
  };
}

export function framesToCsv(frames) {
  const lines = [];
  // Only text cells are neutralised against spreadsheet formulas; numbers such as -5 stay numeric.
  const esc = (v) => {
    const s = v === null || v === undefined ? '' : String(v);
    const safe = typeof v === 'string' && /^[=+\-@\t\r]/.test(s) ? `'${s}` : s;
    return /[",\n\r;]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
  };
  for (const f of frames) {
    if (f.type === 'table') {
      lines.push(f.columns.map((c) => esc(c.name)).join(','));
      for (const r of f.rows) lines.push(r.map((v, i) => esc(f.columns[i].type === 'time' && v ? new Date(v).toISOString() : v)).join(','));
    } else {
      lines.push(['Zaman', 'Seri', 'Değer', 'Birim'].join(','));
      for (const [t, v] of f.points) lines.push([new Date(t).toISOString(), esc(f.name), v ?? '', esc(f.unit)].join(','));
    }
    lines.push('');
  }
  return `﻿${lines.join('\n')}`;
}

export class PanelView {
  constructor(panel, ctx, actions = {}) {
    this.panel = panel;
    this.ctx = ctx; // {range, timezone, variables, scopedVars, dashboardTitle, now, group, onZoom, editable}
    this.actions = actions;
    this.frames = [];
    this.response = null;
    this.viz = null;
    this.vizState = {};
    this.seq = 0;
    this.el = h('div', { class: ['panel', panel.transparent ? 'transparent' : ''].join(' '), tabindex: '-1' });
    this.loader = h('div', { class: 'panel-loading', hidden: true });
    this.status = h('span', { class: 'panel-status', hidden: true });
    this.titleEl = h('div', { class: 'panel-title' });
    const icons = h('div', { class: 'p-icons' });
    if (panel.description) icons.append(h('span', { class: 'panel-status', title: interpolate(panel.description, ctx.variables, ctx.scopedVars) }, icon('info')));
    this.menuBtn = button('', { icon: 'dots', variant: 'ghost', size: 'sm', title: 'Panel menüsü', onClick: (e) => this.openMenu(e.currentTarget) });
    icons.append(this.menuBtn);
    this.header = h('div', { class: 'panel-header' }, this.titleEl, this.status, icons);
    this.body = h('div', { class: 'panel-body' });
    this.vizEl = h('div', { class: 'viz' });
    this.body.append(this.vizEl);
    this.el.append(this.loader, this.header, this.body);
    if (ctx.editable && actions.onResizeStart) {
      const handle = h('div', { class: 'resize-handle', title: 'Boyutlandır' });
      handle.addEventListener('pointerdown', (e) => actions.onResizeStart(e));
      this.el.append(handle);
    }
    this.updateTitle();
    this.ro = new ResizeObserver(() => { if (this.viz && this.viz.resize) this.viz.resize(); });
    this.ro.observe(this.vizEl);
    this.onThemeChange = () => { if (!this.destroyed && this.viz) this.render(); };
    window.addEventListener('openreporting:themechange', this.onThemeChange);
  }

  updateTitle() {
    const title = interpolate(this.panel.title || '', this.ctx.variables, this.ctx.scopedVars);
    this.titleEl.textContent = title;
    this.titleEl.title = title;
    this.header.hidden = !title && !this.ctx.editable && this.panel.type !== 'text' ? false : false;
  }

  setContext(ctx) { this.ctx = { ...this.ctx, ...ctx }; this.updateTitle(); }

  async refresh() {
    const panel = withDefaults(this.panel);
    const p = plugin(panel.type);
    if (p.noQueries) { this.render(); return; }
    if (!(panel.targets || []).length) { this.frames = []; this.render(); return; }
    if (this.destroyed) return;
    const seq = ++this.seq;
    if (this.abort) this.abort.abort();
    const abort = new AbortController();
    this.abort = abort;
    this.loader.hidden = false;
    try {
      const req = buildRequest(panel, this.ctx, this.vizEl.clientWidth || 800);
      const res = await post('/api/ds/query', req, { signal: abort.signal });
      if (seq !== this.seq || this.destroyed) return;
      this.response = res;
      this.frames = res.frames || [];
      this.error = null;
      this.setStatus(res);
      this.render();
    } catch (err) {
      if (seq !== this.seq || this.destroyed || err.name === 'AbortError') return;
      this.error = err instanceof ApiError ? err.message : String(err);
      this.frames = [];
      this.status.hidden = false;
      this.status.className = 'panel-status err';
      this.status.title = this.error;
      this.status.replaceChildren(icon('error'));
      this.destroyViz();
      this.vizEl.replaceChildren(h('div', { class: 'panel-error', text: this.error }));
    } finally {
      if (seq === this.seq) this.loader.hidden = true;
    }
  }

  setStatus(res) {
    const errors = Object.entries(res.results || {}).filter(([, r]) => r.error).map(([ref, r]) => `${ref}: ${r.error}`);
    const warnings = Object.entries(res.results || {}).flatMap(([ref, r]) => (r.warnings || []).map((w) => `${ref}: ${w}`));
    if (res.transformError) errors.push(`Dönüşüm: ${res.transformError}`);
    if (!errors.length && !warnings.length) { this.status.hidden = true; return; }
    this.status.hidden = false;
    this.status.className = `panel-status ${errors.length ? 'err' : 'warn'}`;
    this.status.title = [...errors, ...warnings].join('\n');
    this.status.replaceChildren(icon(errors.length ? 'error' : 'warning'));
  }

  destroyViz() { if (this.viz && this.viz.destroy) this.viz.destroy(); this.viz = null; }

  render() {
    this.destroyViz();
    const panel = withDefaults(this.panel);
    const p = plugin(panel.type);
    const errors = Object.values((this.response || {}).results || {}).filter((r) => r.error);
    if (!this.frames.length && errors.length && !p.noQueries) {
      this.vizEl.replaceChildren(h('div', { class: 'panel-error', text: errors.map((e) => e.error).join('\n') }));
      return;
    }
    const range = this.response && this.response.request ? { from: this.response.request.from, to: this.response.request.to } : this.ctx.resolvedRange;
    try {
      this.viz = p.render(this.vizEl, this.frames, panel, { ...this.vizState, timeRange: range, timezone: this.ctx.timezone, group: this.ctx.group,
        onZoom: p.zoom && this.ctx.onZoom ? this.ctx.onZoom : null, interpolate: (s) => interpolate(s, this.ctx.variables, this.ctx.scopedVars),
        hiddenSeries: this.vizState.hiddenSeries || (this.vizState.hiddenSeries = new Set()), tableSort: this.vizState.tableSort || (this.vizState.tableSort = { col: null, desc: false }) });
    } catch (err) {
      console.error(err); // eslint-disable-line no-console
      this.vizEl.replaceChildren(h('div', { class: 'panel-error', text: `Görselleştirme hatası: ${err.message}` }));
    }
  }

  openMenu(anchor) {
    const a = this.actions;
    const items = [
      a.onView && { label: 'Görüntüle', icon: 'eye', shortcut: 'v', onClick: () => a.onView() },
      a.onEdit && { label: 'Düzenle', icon: 'edit', shortcut: 'e', onClick: () => a.onEdit() },
      a.onShare && { label: 'Bağlantı paylaş', icon: 'share', onClick: () => a.onShare() },
      { label: 'İncele (veri / sorgu)', icon: 'search', shortcut: 'i', onClick: () => inspect(this) },
      { sep: true },
      { label: 'CSV indir', icon: 'download', onClick: () => downloadBlob(`${(this.panel.title || 'panel').replace(/[^\w-]+/g, '_')}.csv`, framesToCsv(this.frames), 'text/csv;charset=utf-8') },
      this.viz && this.viz.png && { label: 'PNG indir', icon: 'download', onClick: () => { const a2 = h('a', { href: this.viz.png(), download: `${(this.panel.title || 'panel').replace(/[^\w-]+/g, '_')}.png` }); document.body.append(a2); a2.click(); a2.remove(); } },
      { label: 'Yenile', icon: 'refresh', onClick: () => this.refresh() },
      a.onDuplicate && { sep: true },
      a.onDuplicate && { label: 'Çoğalt', icon: 'copy', onClick: () => a.onDuplicate() },
      a.onCopyJson && { label: 'Panel JSON kopyala', icon: 'code', onClick: () => a.onCopyJson() },
      a.onRemove && { label: 'Kaldır', icon: 'trash', onClick: () => a.onRemove() },
    ];
    menu(anchor, items, { align: 'right' });
  }

  destroy() {
    if (this.destroyed) return;
    this.destroyed = true;
    this.seq += 1;
    if (this.abort) this.abort.abort();
    this.ro.disconnect();
    window.removeEventListener('openreporting:themechange', this.onThemeChange);
    this.destroyViz();
    this.el.remove();
  }
}

export async function inspect(view) {
  const { modal, tabs, clear } = await import('../dom.js');
  const content = h('div');
  const showData = () => {
    clear(content);
    if (!view.frames.length) { content.append(h('p', { class: 'muted', text: 'Veri yok.' })); return; }
    for (const f of view.frames.slice(0, 20)) {
      content.append(h('h4', { text: `${f.name || f.refId} (${f.type === 'table' ? `${f.rows.length} satır` : `${f.points.length} nokta`})` }));
      const table = h('table', { class: 'list' });
      if (f.type === 'table') {
        table.append(h('tr', f.columns.map((c) => h('th', { text: c.name }))));
        for (const r of f.rows.slice(0, 500)) table.append(h('tr', r.map((v, i) => h('td', { text: f.columns[i].type === 'time' && v ? new Date(v).toLocaleString('tr-TR') : (v ?? '—') }))));
      } else {
        table.append(h('tr', h('th', { text: 'Zaman' }), h('th', { text: 'Değer' })));
        for (const [t, v] of f.points.slice(-500)) table.append(h('tr', h('td', { text: new Date(t).toLocaleString('tr-TR') }), h('td', { text: v === null ? 'boş' : formatValue(v, 'none') })));
      }
      content.append(h('div', { class: 'inspect-table' }, table));
      if (f.labels && Object.keys(f.labels).length) content.append(h('p', { class: 'hint', text: `Etiketler: ${Object.entries(f.labels).map(([k, v]) => `${k}=${v}`).join(', ')}` }));
    }
  };
  const showQuery = () => {
    clear(content);
    const req = buildRequest(withDefaults(view.panel), view.ctx, view.vizEl.clientWidth || 800);
    content.append(h('h4', { text: 'İstek' }), h('pre', { class: 'json-view', text: JSON.stringify(req, null, 2) }),
      h('h4', { text: 'Sonuç durumu' }), h('pre', { class: 'json-view', text: JSON.stringify({ request: view.response?.request, results: view.response?.results }, null, 2) }));
  };
  const showJson = () => { clear(content); content.append(h('pre', { class: 'json-view', text: JSON.stringify(view.panel, null, 2) })); };
  const bar = tabs([{ id: 'data', label: 'Veri' }, { id: 'query', label: 'Sorgu' }, { id: 'json', label: 'Panel JSON' }], 'data', (id) => ({ data: showData, query: showQuery, json: showJson })[id]());
  showData();
  modal({ title: `İncele: ${view.panel.title || 'Panel'}`, size: 'lg', body: [bar, content] });
}

export function notifyError(err) { toast(err instanceof Error ? err.message : String(err), 'error'); }
