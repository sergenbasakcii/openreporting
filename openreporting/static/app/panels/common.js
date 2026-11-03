// Shared helpers for visualizations: reducers, field display, echarts theming.
import { formatValue, resolveUnit } from '../units.js';
import { fieldConfigFor, displayName, seriesColor, thresholdColor, applyMappings, cssVar, PALETTE } from '../colors.js';

export const REDUCERS = {
  lastNotNull: 'Son (boş olmayan)', last: 'Son', firstNotNull: 'İlk (boş olmayan)', first: 'İlk', mean: 'Ortalama', min: 'En düşük',
  max: 'En yüksek', sum: 'Toplam', count: 'Sayı', range: 'Aralık', delta: 'Delta', diff: 'Fark', median: 'Medyan', p90: 'p90', p95: 'p95',
  p99: 'p99', stdDev: 'Std. sapma', changeCount: 'Değişim sayısı', distinctCount: 'Farklı değer', nullCount: 'Boş sayısı',
};

function pct(sorted, f) {
  if (!sorted.length) return null;
  const pos = (sorted.length - 1) * f; const lo = Math.floor(pos); const hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

// Loops instead of Math.min(...arr): spreading 100k+ points overflows the call stack.
export function minOf(values, fallback = null) {
  let out = Infinity;
  for (const v of values) if (typeof v === 'number' && v < out) out = v;
  return out === Infinity ? fallback : out;
}

export function maxOf(values, fallback = null) {
  let out = -Infinity;
  for (const v of values) if (typeof v === 'number' && v > out) out = v;
  return out === -Infinity ? fallback : out;
}

export function reduce(values, calc) {
  const clean = values.filter((v) => v !== null && v !== undefined && Number.isFinite(v));
  switch (calc) {
    case 'count': return clean.length;
    case 'nullCount': return values.length - clean.length;
    case 'last': return values.length ? values[values.length - 1] : null;
    case 'first': return values.length ? values[0] : null;
    default: break;
  }
  if (!clean.length) return null;
  switch (calc) {
    case 'lastNotNull': return clean[clean.length - 1];
    case 'firstNotNull': return clean[0];
    case 'mean': return clean.reduce((a, b) => a + b, 0) / clean.length;
    case 'min': return minOf(clean);
    case 'max': return maxOf(clean);
    case 'sum': return clean.reduce((a, b) => a + b, 0);
    case 'range': return maxOf(clean) - minOf(clean);
    case 'diff': return clean[clean.length - 1] - clean[0];
    case 'delta': { let t = 0; for (let i = 1; i < clean.length; i += 1) t += clean[i] >= clean[i - 1] ? clean[i] - clean[i - 1] : clean[i]; return t; }
    case 'median': return pct([...clean].sort((a, b) => a - b), 0.5);
    case 'p90': return pct([...clean].sort((a, b) => a - b), 0.9);
    case 'p95': return pct([...clean].sort((a, b) => a - b), 0.95);
    case 'p99': return pct([...clean].sort((a, b) => a - b), 0.99);
    case 'stdDev': { const m = clean.reduce((a, b) => a + b, 0) / clean.length; return Math.sqrt(clean.reduce((a, b) => a + (b - m) ** 2, 0) / clean.length); }
    case 'changeCount': { let c = 0; for (let i = 1; i < clean.length; i += 1) if (clean[i] !== clean[i - 1]) c += 1; return c; }
    case 'distinctCount': return new Set(clean).size;
    default: return clean[clean.length - 1];
  }
}

export const timeSeries = (frames) => frames.filter((f) => f.type === 'timeseries');
export const tables = (frames) => frames.filter((f) => f.type === 'table');

// One display value per series (or per numeric table cell when reduceOptions.values).
export function reducedValues(frames, panel) {
  const opts = (panel.options && panel.options.reduceOptions) || {};
  const calc = (opts.calcs && opts.calcs[0]) || 'lastNotNull';
  const out = [];
  let index = 0;
  for (const frame of timeSeries(frames)) {
    const name = displayName(frame);
    const cfg = fieldConfigFor(panel, frame, name);
    const values = frame.points.map((p) => p[1]);
    const value = reduce(values, calc);
    const unit = resolveUnit(cfg.unit, frame.unit);
    out.push({ name: cfg.displayName ? cfg.displayName.replace('${__field.name}', name) : name, value, unit, cfg, frame, index,
      color: colorFor(cfg, index, value), points: frame.points, labels: frame.labels || {} });
    index += 1;
  }
  for (const table of tables(frames)) {
    const labelIdx = table.columns.findIndex((c) => c.type === 'string');
    table.columns.forEach((col, ci) => {
      if (col.type !== 'number') return;
      const cfg = fieldConfigFor(panel, table, col.name);
      if (opts.values || labelIdx >= 0) {
        table.rows.forEach((row, ri) => {
          const unitRow = (table.meta && table.meta.rowUnits && table.meta.rowUnits[ri]) || col.unit;
          const label = labelIdx >= 0 ? `${row[labelIdx]}${table.columns.filter((c) => c.type === 'number').length > 1 ? ` · ${col.name}` : ''}` : `${col.name} ${ri + 1}`;
          const value = row[ci];
          out.push({ name: label, value, unit: resolveUnit(cfg.unit, unitRow), cfg, index, color: colorFor(cfg, index, value), points: [], labels: {} });
          index += 1;
        });
      } else {
        const value = reduce(table.rows.map((r) => r[ci]), calc);
        out.push({ name: col.name, value, unit: resolveUnit(cfg.unit, col.unit), cfg, index, color: colorFor(cfg, index, value), points: [], labels: {} });
        index += 1;
      }
    });
  }
  const limit = Number(opts.limit) || 0;
  return limit > 0 ? out.slice(0, limit) : out;
}

export function colorFor(cfg, index, value) {
  const mode = (cfg.color && cfg.color.mode) || 'thresholds';
  if (mode === 'palette-classic') return PALETTE[index % PALETTE.length];
  if (mode === 'fixed') return seriesColor(cfg, index, value);
  return thresholdColor(value, cfg.thresholds, cfg.min ?? 0, cfg.max ?? 100) || PALETTE[index % PALETTE.length];
}

export function display(value, item) {
  const mapped = applyMappings(value, item.cfg.mappings);
  if (mapped) return { text: mapped.text ?? String(value), color: mapped.color ? mapped.color : null };
  if (value === null || value === undefined) return { text: item.cfg.noValue || 'Veri yok', color: null };
  return { text: formatValue(value, item.unit, item.cfg.decimals), color: null };
}

// Colours for canvas charts, read from the container so a themed subtree (smart dashboard paper) wins.
export function chartTheme(container) {
  const scope = container && container.isConnected ? container : document.documentElement;
  const v = (name) => cssVar(name, scope);
  return { text: v('--text') || '#ccccdc', muted: v('--text-muted') || '#999', grid: v('--grid-line') || 'rgba(204,204,220,.1)',
    bg: v('--bg-panel') || '#181b1f', tooltipBg: v('--bg-elevated') || '#22252b', border: v('--border-strong') || '#444' };
}

export function initChart(container) {
  const chart = window.echarts.init(container, null, { renderer: 'canvas' });
  return chart;
}

export function timeAxisLabel(ms, spanMs, tz) {
  const d = new Date(ms);
  const opts = spanMs > 2 * 86400000 ? { month: '2-digit', day: '2-digit', hour: spanMs > 20 * 86400000 ? undefined : '2-digit', minute: spanMs > 20 * 86400000 ? undefined : '2-digit' }
    : { hour: '2-digit', minute: '2-digit', second: spanMs < 600000 ? '2-digit' : undefined };
  opts.hour12 = false;
  if (tz && tz !== 'browser') opts.timeZone = tz === 'utc' ? 'UTC' : tz;
  try { return new Intl.DateTimeFormat('tr-TR', opts).format(d); } catch { return d.toISOString().slice(11, 16); }
}

export function noData(container, text = 'Veri yok') {
  container.replaceChildren(Object.assign(document.createElement('div'), { className: 'panel-nodata', textContent: text }));
}

export function fitText(value, width, height, max = 80) {
  const len = Math.max(1, String(value).length);
  return Math.max(10, Math.min(max, height * 0.55, (width / len) * 1.7));
}
