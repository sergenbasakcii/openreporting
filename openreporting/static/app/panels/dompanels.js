// DOM visualizations: stat, bar gauge, table, status grid (group health), text.
import { h } from '../dom.js';
import { formatValue, resolveUnit } from '../units.js';
import { fieldConfigFor, color, alpha, contrastText, thresholdColor, applyMappings } from '../colors.js';
import { reducedValues, display, noData, timeSeries, tables, reduce, REDUCERS, fitText, chartTheme, minOf, maxOf } from './common.js';
import { renderMarkdown } from '../markdown.js';
import { fmtDateTime } from '../dom.js';

const nothing = { resize() {}, destroy() {} };

function sparkline(points, c) {
  const values = points.filter((p) => p[1] !== null && p[1] !== undefined);
  if (values.length < 2) return null;
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 100 30');
  svg.setAttribute('preserveAspectRatio', 'none');
  svg.classList.add('spark');
  const t0 = values[0][0]; const t1 = values[values.length - 1][0];
  const vs = values.map((p) => p[1]); const lo = minOf(vs, 0); const hi = maxOf(vs, 0);
  const xy = values.map(([t, v]) => [((t - t0) / (t1 - t0 || 1)) * 100, 30 - ((v - lo) / (hi - lo || 1)) * 26 - 2]);
  const area = document.createElementNS(ns, 'path');
  area.setAttribute('d', `M0,30 ${xy.map(([x, y]) => `L${x.toFixed(2)},${y.toFixed(2)}`).join(' ')} L100,30 Z`);
  area.setAttribute('fill', alpha(c, 0.25));
  const line = document.createElementNS(ns, 'path');
  line.setAttribute('d', `M${xy.map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(' L')}`);
  line.setAttribute('fill', 'none');
  line.setAttribute('stroke', c);
  line.setAttribute('stroke-width', '1.2');
  line.setAttribute('vector-effect', 'non-scaling-stroke');
  svg.append(area, line);
  return svg;
}

function gridDims(count, width, height, orientation) {
  if (orientation === 'horizontal') return [1, count];
  if (orientation === 'vertical') return [count, 1];
  const cols = Math.max(1, Math.min(count, Math.round(Math.sqrt(count * (width / Math.max(1, height))))));
  return [cols, Math.ceil(count / cols)];
}

export function renderStat(container, frames, panel) {
  const items = reducedValues(frames, panel);
  if (!items.length) { noData(container); return nothing; }
  const opts = panel.options || {};
  const colorMode = opts.colorMode || 'value';
  const graphMode = opts.graphMode || 'area';
  const textMode = opts.textMode || 'auto';
  const grid = h('div', { class: 'stat-grid' });
  container.replaceChildren(grid);
  const layout = () => {
    const rect = container.getBoundingClientRect();
    const [cols, rows] = gridDims(items.length, rect.width, rect.height, opts.orientation);
    grid.style.gridTemplateColumns = `repeat(${cols}, minmax(0, 1fr))`;
    grid.style.gridTemplateRows = `repeat(${rows}, minmax(0, 1fr))`;
    grid.replaceChildren();
    const cellW = rect.width / cols; const cellH = rect.height / rows;
    for (const item of items) {
      const d = display(item.value, item);
      const c = d.color ? color(d.color) : item.color;
      const showName = textMode === 'value_and_name' || textMode === 'name' || (textMode === 'auto' && items.length > 1);
      const box = h('div', { class: 'stat-box' });
      if (colorMode === 'background') { box.style.background = `linear-gradient(120deg, ${alpha(c, 0.85)}, ${c})`; box.style.color = contrastText(c); }
      if (colorMode === 'background_solid') { box.style.background = c; box.style.color = contrastText(c); }
      if (showName) box.append(h('div', { class: 'stat-name', text: item.name }));
      if (textMode !== 'name' && textMode !== 'none') {
        const size = fitText(d.text, cellW * 0.9, cellH * (showName ? 0.7 : 0.9), 96);
        box.append(h('div', { class: 'stat-value', text: d.text, style: { fontSize: `${size}px`, color: colorMode === 'value' ? c : 'inherit' } }));
      }
      if (graphMode === 'area' && item.points.length > 1 && cellH > 50) {
        const spark = sparkline(item.points, colorMode.startsWith('background') ? 'rgba(255,255,255,.75)' : c);
        if (spark) box.append(spark);
      }
      box.title = `${item.name}: ${d.text}`;
      grid.append(box);
    }
  };
  layout();
  return { resize: layout, destroy() {} };
}

export function renderBarGauge(container, frames, panel) {
  const items = reducedValues(frames, panel);
  if (!items.length) { noData(container); return nothing; }
  const opts = panel.options || {};
  const mode = opts.displayMode || 'gradient';
  if (opts.sort === 'desc') items.sort((a, b) => (b.value ?? -Infinity) - (a.value ?? -Infinity));
  const list = h('div', { class: 'bargauge-list' });
  const autoMax = Math.max(maxOf(items.map((i) => i.value ?? 0), 0), 1);
  for (const item of items) {
    const min = item.cfg.min ?? 0;
    const max = item.cfg.max ?? (item.unit === 'percent' ? 100 : autoMax);
    const ratio = item.value === null || item.value === undefined ? 0 : Math.max(0, Math.min(1, (item.value - min) / (max - min || 1)));
    const d = display(item.value, item);
    const c = d.color ? color(d.color) : item.color;
    const fill = h('div', { class: ['bg-fill', mode === 'lcd' ? 'lcd' : ''].join(' ') });
    fill.style.width = `${ratio * 100}%`;
    if (mode === 'gradient') fill.style.background = `linear-gradient(90deg, ${alpha(c, 0.35)}, ${c})`;
    else if (mode === 'lcd') fill.style.background = `repeating-linear-gradient(90deg, ${c} 0 6px, transparent 6px 8px)`;
    else fill.style.background = c;
    const bar = h('div', { class: 'bg-bar' }, fill);
    if (opts.showUnfilled === false) bar.style.background = 'transparent';
    list.append(h('div', { class: 'bargauge-row', title: `${item.name}: ${d.text}` }, h('div', { class: 'bg-name', text: item.name }), bar,
      h('div', { class: 'bg-value', text: d.text, style: { color: c } })));
  }
  container.replaceChildren(list);
  return nothing;
}

function frameToTable(frames) {
  const table = tables(frames)[0];
  if (table) return table;
  const series = timeSeries(frames);
  if (!series.length) return null;
  const stamps = [...new Set(series.flatMap((s) => s.points.map((p) => p[0])))].sort((a, b) => b - a);
  const lookups = series.map((s) => new Map(s.points));
  return { type: 'table', name: 'Birleşik', columns: [{ name: 'Zaman', type: 'time' }, ...series.map((s) => ({ name: s.meta?.displayName || s.name, type: 'number', unit: s.unit }))],
    rows: stamps.map((t) => [t, ...lookups.map((m) => (m.has(t) ? m.get(t) : null))]), meta: {} };
}

export function renderTable(container, frames, panel, ctx) {
  const table = frameToTable(frames);
  if (!table || !table.rows.length) { noData(container, table ? 'Tablo boş' : 'Veri yok'); return nothing; }
  const opts = panel.options || {};
  const state = ctx.tableSort || (ctx.tableSort = { col: null, desc: false });
  if (state.col === null && opts.sortBy && opts.sortBy[0]) {
    state.col = table.columns.findIndex((c) => c.name === opts.sortBy[0].displayName);
    state.desc = !!opts.sortBy[0].desc;
  }
  const cfgs = table.columns.map((c) => fieldConfigFor(panel, table, c.name));
  const columnMax = new Map();
  const sortBy = (ci, keepFocus = false) => {
    state.desc = state.col === ci ? !state.desc : false; state.col = ci; draw();
    if (keepFocus) { const th = container.querySelector(`th[data-col="${ci}"]`); if (th) th.focus(); }
  };
  const draw = () => {
    let rows = table.rows.map((r, i) => ({ r, i }));
    if (state.col !== null && state.col >= 0) {
      const ci = state.col;
      rows.sort((a, b) => {
        const x = a.r[ci]; const y = b.r[ci];
        if (x === null || x === undefined) return 1;
        if (y === null || y === undefined) return -1;
        const res = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y), 'tr', { numeric: true });
        return state.desc ? -res : res;
      });
    }
    const head = h('tr', table.columns.map((c, ci) => {
      if (cfgs[ci].custom?.hidden) return null;
      return h('th', { class: c.type === 'number' ? 'num' : '', tabindex: '0', scope: 'col', dataset: { col: ci },
        'aria-sort': state.col === ci ? (state.desc ? 'descending' : 'ascending') : 'none',
        onclick: () => sortBy(ci), onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); sortBy(ci, true); } } },
        cfgs[ci].displayName || c.name, state.col === ci ? h('span', { class: 'sort', text: state.desc ? '▼' : '▲' }) : null);
    }));
    const body = h('tbody');
    for (const { r, i } of rows.slice(0, 5000)) {
      body.append(h('tr', table.columns.map((c, ci) => {
        const cfg = cfgs[ci];
        if (cfg.custom?.hidden) return null;
        const v = r[ci];
        if (c.type === 'time') return h('td', { text: fmtDateTime(v, ctx.timezone) });
        if (c.type !== 'number') {
          const mapped = applyMappings(v, cfg.mappings);
          const td = h('td', { text: mapped ? mapped.text : v ?? '' });
          if (mapped && mapped.color) td.style.color = color(mapped.color);
          return td;
        }
        const rowUnit = table.meta && table.meta.rowUnits && table.meta.rowUnits[i];
        const unit = resolveUnit(cfg.unit, c.unit || rowUnit);
        const mapped = applyMappings(v, cfg.mappings);
        const text = mapped ? mapped.text : formatValue(v, unit, cfg.decimals, cfg.noValue || '—');
        const cell = cfg.custom?.cellOptions?.type || cfg.custom?.displayMode || 'auto';
        const c2 = (mapped && mapped.color && color(mapped.color)) || thresholdColor(v, cfg.thresholds, cfg.min ?? 0, cfg.max ?? 100);
        const td = h('td', { class: 'num' });
        if ((cell === 'color-background' || cell === 'color-background-solid') && v !== null && c2) { td.style.background = cell === 'color-background' ? alpha(c2, 0.75) : c2; td.style.color = contrastText(c2); td.textContent = text; }
        else if (cell === 'color-text' && c2) { td.style.color = c2; td.textContent = text; }
        else if ((cell === 'gauge' || cell === 'lcd-gauge' || cell === 'gradient-gauge') && v !== null) {
          if (!columnMax.has(ci)) columnMax.set(ci, Math.max(maxOf(table.rows.map((x) => x[ci] ?? 0), 0), 1));
          const max = cfg.max ?? (unit === 'percent' ? 100 : columnMax.get(ci));
          const bar = h('i', { style: { width: `${Math.max(2, Math.min(100, ((v - (cfg.min ?? 0)) / (max - (cfg.min ?? 0) || 1)) * 100))}%`, background: c2 || '#5794f2' } });
          td.append(h('div', { class: 'cell-gauge' }, h('div', { style: { flex: '1', display: 'flex', justifyContent: 'flex-start' } }, bar), h('span', { text })));
        } else td.textContent = text;
        if (cfg.custom?.align) td.style.textAlign = cfg.custom.align;
        return td;
      })));
    }
    const parts = [h('thead', head), body];
    if (opts.footer && opts.footer.show) {
      const reducer = (opts.footer.reducer && opts.footer.reducer[0]) || 'sum';
      parts.push(h('tfoot', h('tr', table.columns.map((c, ci) => {
        if (cfgs[ci].custom?.hidden) return null;
        if (ci === 0) return h('td', { text: REDUCERS[reducer] || reducer });
        if (c.type !== 'number') return h('td');
        const value = reduce(table.rows.map((r) => r[ci]), reducer);
        return h('td', { class: 'num', text: formatValue(value, resolveUnit(cfgs[ci].unit, c.unit), cfgs[ci].decimals) });
      }))));
    }
    container.replaceChildren(h('div', { class: 'table-viz' }, h('table', parts),
      table.rows.length > 5000 ? h('div', { class: 'hint', text: `İlk 5000 satır gösteriliyor (toplam ${table.rows.length}).` }) : null));
  };
  draw();
  return nothing;
}

export function renderStatusGrid(container, frames, panel) {
  const items = reducedValues(frames, panel);
  if (!items.length) { noData(container); return nothing; }
  const opts = panel.options || {};
  const labelField = opts.labelField || 'host';
  if (opts.sort === 'value') items.sort((a, b) => (b.value ?? -Infinity) - (a.value ?? -Infinity));
  if (opts.sort === 'name') items.sort((a, b) => String(a.labels[labelField] || a.name).localeCompare(String(b.labels[labelField] || b.name), 'tr', { numeric: true }));
  const grid = h('div', { class: 'statusgrid' });
  grid.style.gridTemplateColumns = `repeat(auto-fill, minmax(${Number(opts.minCellWidth) || 130}px, 1fr))`;
  const theme = chartTheme();
  for (const item of items) {
    const d = display(item.value, item);
    const c = d.color ? color(d.color) : item.value === null ? 'rgba(128,128,128,.35)' : item.color;
    const label = item.labels[labelField] || item.name;
    const cell = h('div', { class: 'status-cell', title: `${item.name}\n${d.text}` }, h('b', { text: label }), opts.showValue === false ? null : h('span', { text: d.text }));
    cell.style.background = c;
    cell.style.color = contrastText(c.startsWith('#') ? c : theme.bg);
    grid.append(cell);
  }
  container.replaceChildren(grid);
  return nothing;
}

export function renderText(container, frames, panel, ctx) {
  const content = (panel.options && panel.options.content) || '';
  container.replaceChildren(renderMarkdown(content, ctx.interpolate || ((s) => s)));
  return nothing;
}
