// Grafana color names, classic palette, thresholds and field config resolution.
export const NAMED = {
  green: '#73BF69', 'dark-green': '#37872D', 'semi-dark-green': '#56A64B', 'light-green': '#96D98D', 'super-light-green': '#C8F2C2',
  yellow: '#FADE2A', 'dark-yellow': '#E0B400', 'semi-dark-yellow': '#F2CC0C', 'light-yellow': '#FFEE52',
  red: '#F2495C', 'dark-red': '#C4162A', 'semi-dark-red': '#E02F44', 'light-red': '#FF7383',
  blue: '#5794F2', 'dark-blue': '#1F60C4', 'semi-dark-blue': '#3274D9', 'light-blue': '#8AB8FF',
  orange: '#FF9830', 'dark-orange': '#FA6400', 'semi-dark-orange': '#FF780A', 'light-orange': '#FFB357',
  purple: '#B877D9', 'dark-purple': '#8F3BB8', 'semi-dark-purple': '#A352CC', 'light-purple': '#CA95E5',
  transparent: 'rgba(0,0,0,0)', text: '#ccccdc', white: '#ffffff', black: '#000000',
};
export const PALETTE = ['#73BF69', '#F2CC0C', '#8AB8FF', '#FF780A', '#F2495C', '#5794F2', '#B877D9', '#705DA0', '#37872D', '#FADE2A',
  '#447EBC', '#C15C17', '#890F02', '#0A437C', '#6D1F62', '#584477', '#B7DBAB', '#F4D598', '#70DBED', '#F9BA8F', '#F29191', '#82B5D8',
  '#E5A8E2', '#AEA2E0', '#629E51', '#E5AC0E', '#64B0C8', '#E0752D', '#BF1B00', '#0A50A1', '#962D82', '#614D93'];

// Colours come from dashboard JSON and end up in chart options and tooltip markup: only named
// colours, #hex and rgb()/rgba() are accepted, anything else falls back to the first palette colour.
const SAFE_COLOR = /^(#[0-9a-f]{3,8}|rgba?\(\s*\d{1,3}%?\s*,\s*\d{1,3}%?\s*,\s*\d{1,3}%?\s*(,\s*(0|1|0?\.\d+)\s*)?\))$/i;
export function color(name) {
  if (!name) return PALETTE[0];
  if (Object.prototype.hasOwnProperty.call(NAMED, name)) return NAMED[name];
  return typeof name === 'string' && SAFE_COLOR.test(name.trim()) ? name.trim() : PALETTE[0];
}

export const DEFAULT_THRESHOLDS = { mode: 'absolute', steps: [{ color: 'green', value: null }, { color: 'red', value: 80 }] };

export function thresholdColor(value, thresholds, min = 0, max = 100) {
  const t = thresholds && thresholds.steps && thresholds.steps.length ? thresholds : DEFAULT_THRESHOLDS;
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return null;
  let v = Number(value);
  if (t.mode === 'percentage') v = max > min ? ((v - min) / (max - min)) * 100 : 0;
  let active = t.steps[0];
  for (const step of t.steps) {
    if (step.value === null || step.value === undefined || step.value === -Infinity) { active = step; continue; }
    if (v >= Number(step.value)) active = step;
  }
  return color(active.color);
}

function setPath(obj, path, value) {
  const parts = path.split('.');
  let cur = obj;
  for (const p of parts.slice(0, -1)) { cur[p] = { ...(cur[p] || {}) }; cur = cur[p]; }
  cur[parts[parts.length - 1]] = value;
}

function matches(matcher, frame, name) {
  if (!matcher) return false;
  const opt = matcher.options;
  if (matcher.id === 'byName') return name === opt;
  if (matcher.id === 'byRegexp') {
    try { const m = String(opt).match(/^\/(.*)\/([gimsuy]*)$/); return new RegExp(m ? m[1] : opt, m ? m[2] : '').test(name); } catch { return false; }
  }
  if (matcher.id === 'byFrameRefID') return frame.refId === opt;
  if (matcher.id === 'byType') return opt === 'number';
  return false;
}

export function displayName(frame) {
  return (frame.meta && frame.meta.displayName) || frame.name || frame.refId || 'seri';
}

// Field config for one series (defaults + overrides), Grafana semantics.
export function fieldConfigFor(panel, frame, name) {
  const defaults = (panel.fieldConfig && panel.fieldConfig.defaults) || {};
  const cfg = JSON.parse(JSON.stringify(defaults));
  cfg.custom = cfg.custom || {};
  for (const ov of (panel.fieldConfig && panel.fieldConfig.overrides) || []) {
    if (!matches(ov.matcher, frame, name)) continue;
    for (const prop of ov.properties || []) setPath(cfg, prop.id, prop.value);
  }
  return cfg;
}

export function seriesColor(cfg, index, lastValue) {
  const mode = cfg.color && cfg.color.mode;
  if (mode === 'fixed' || mode === 'shades') return color(cfg.color.fixedColor || 'green');
  if (mode === 'thresholds') return thresholdColor(lastValue, cfg.thresholds, cfg.min ?? 0, cfg.max ?? 100) || PALETTE[index % PALETTE.length];
  return PALETTE[index % PALETTE.length];
}

export function applyMappings(value, mappings) {
  for (const m of mappings || []) {
    if (m.type === 'value' && m.options) {
      const hit = m.options[String(value)];
      if (hit) return hit;
    }
    if (m.type === 'range' && m.options && value !== null && value !== undefined) {
      const { from, to, result } = m.options;
      if ((from === null || from === undefined || value >= from) && (to === null || to === undefined || value <= to)) return result;
    }
    if (m.type === 'special' && m.options && (value === null || value === undefined) && m.options.match === 'null') return m.options.result;
  }
  return null;
}

export function cssVar(name) { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); }

export function contrastText(hex) {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})/i.exec(hex || '');
  if (!m) return '#fff';
  const [r, g, b] = [m[1], m[2], m[3]].map((x) => parseInt(x, 16));
  return (r * 299 + g * 587 + b * 114) / 1000 > 150 ? '#111' : '#fff';
}

export function alpha(hex, a) {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})/i.exec(hex || '');
  if (!m) return hex;
  return `rgba(${parseInt(m[1], 16)},${parseInt(m[2], 16)},${parseInt(m[3], 16)},${a})`;
}
