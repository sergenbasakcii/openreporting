// Dashboard template variables: server-side resolution, variable bar UI, display interpolation.
import { h, input, popover, closePopups, debounce } from './dom.js';
import { icon } from './icons.js';
import { post } from './api.js';
import { effectiveZone } from './time.js';

export const ALL = '$__all';
const PATTERN = /\$(\w+)|\[\[(\w+?)(?::(\w+))?\]\]|\$\{(\w+)(?::([^}]+))?\}/g;

function valuesOf(v) {
  if (!v) return [];
  const value = v.value;
  const list = Array.isArray(value) ? value : [value];
  if (list.includes(ALL) && v.includeAll) {
    if (v.allValue) return null;
    return (v.options || []).map((o) => o.value).filter((x) => x !== ALL);
  }
  return list.filter((x) => x !== undefined && x !== null && x !== '');
}

// `escape` (optional) is applied to every substituted value, e.g. Markdown escaping for text panels.
export function interpolate(text, variables, scoped = {}, escape = null) {
  if (typeof text !== 'string' || (!text.includes('$') && !text.includes('[['))) return text;
  const merged = { ...variables, ...scoped };
  if (escape) return text.replace(PATTERN, (match, ...groups) => {
    const value = interpolate(match, variables, scoped);
    return value === match ? match : escape(value);
  });
  return text.replace(PATTERN, (match, a, b, fmtB, c, fmtC) => {
    const name = a || b || c;
    const fmt = fmtB || fmtC;
    const v = merged[name];
    if (!v) return match;
    const values = valuesOf(v);
    if (values === null) return v.allValue;
    if (fmt === 'csv') return values.join(',');
    if (fmt === 'pipe') return values.join('|');
    if (fmt === 'text') return v.text || values.join(' + ');
    if (values.length === 1) return values[0];
    return values.length > 4 ? `${values.slice(0, 3).join(', ')} +${values.length - 3}` : values.join(', ');
  });
}

// Variables as sent with a query: option lists are only needed to expand "All".
export function requestVariables(variables) {
  const out = {};
  for (const [name, v] of Object.entries(variables || {})) {
    const list = Array.isArray(v.value) ? v.value : [v.value];
    out[name] = list.includes(ALL) ? v : { ...v, options: [] };
  }
  return out;
}

// Saved dashboards are resolved by uid so the server uses its own variable definitions.
export async function resolveVariables(dashboard, overrides, range, timezone, uid = null) {
  if (!((dashboard.templating || {}).list || []).length) return { variables: {}, warnings: [] };
  return post('/api/dashboards/variables/resolve', { dashboard, uid: uid || undefined, overrides, range, timezone: effectiveZone(timezone) });
}

export function currentOverrides(variables) {
  const out = {};
  for (const [name, v] of Object.entries(variables || {})) out[name] = v.value;
  return out;
}

export function urlOverrides(search, dashboard) {
  const params = new URLSearchParams(search);
  const out = {};
  for (const v of (dashboard.templating || {}).list || []) {
    const values = params.getAll(`var-${v.name}`);
    if (!values.length) continue;
    out[v.name] = v.multi || v.includeAll ? values.map((x) => (x === 'All' ? ALL : x)) : (values[0] === 'All' ? ALL : values[0]);
  }
  return out;
}

export function variablesToParams(variables, params) {
  for (const [name, v] of Object.entries(variables || {})) {
    params.delete(`var-${name}`);
    const list = Array.isArray(v.value) ? v.value : [v.value];
    for (const val of list) if (val !== undefined && val !== null && val !== '') params.append(`var-${name}`, val === ALL ? 'All' : val);
  }
}

function dropdown(anchor, def, v, onPick) {
  const multi = !!def.multi;
  let selected = new Set(Array.isArray(v.value) ? v.value : [v.value]);
  const opts = [...(def.includeAll ? [{ text: 'Tümü', value: ALL }] : []), ...(v.options || [])];
  const list = h('div', { class: 'opts' });
  const render = (filter = '') => {
    list.replaceChildren();
    const f = filter.toLowerCase();
    let shown = 0;
    for (const o of opts) {
      if (f && !String(o.text).toLowerCase().includes(f)) continue;
      if (++shown > 1000) { list.append(h('div', { class: 'hint', style: { padding: '6px 12px' }, text: 'İlk 1000 seçenek gösteriliyor; aramayı daraltın.' })); break; }
      const box = h('input', { type: multi ? 'checkbox' : 'radio', name: `var-${def.name}`, checked: selected.has(o.value), onchange: (e) => {
        if (!multi) { closePopups(); onPick(o.value); return; }
        if (o.value === ALL) selected = e.target.checked ? new Set([ALL]) : new Set();
        else { selected.delete(ALL); if (e.target.checked) selected.add(o.value); else selected.delete(o.value); }
        render(search.value);
      } });
      list.append(h('label', { class: 'opt' }, box, h('span', { text: o.text })));
    }
    if (!shown) list.append(h('div', { class: 'hint', style: { padding: '8px 12px' }, text: 'Seçenek yok' }));
  };
  const search = input({ placeholder: 'Ara…', onInput: (e) => render(e.target.value) });
  const footer = multi ? h('div', { style: { display: 'flex', gap: '6px', padding: '8px', borderTop: '1px solid var(--border)' } },
    h('button', { class: 'btn sm', type: 'button', text: 'Temizle', onclick: () => { selected = new Set(); render(search.value); } }),
    h('span', { class: 'spacer' }),
    h('button', { class: 'btn sm primary', type: 'button', text: 'Uygula', onclick: () => {
      closePopups();
      const values = [...selected];
      onPick(values.length ? values : (opts[0] ? [opts[0].value] : []));
    } })) : null;
  render();
  popover(anchor, [h('div', { class: 'search' }, search), list, footer], { className: 'var-dropdown', width: 320 });
  setTimeout(() => search.focus(), 10);
}

// Renders the variable bar; onChange(name, value) is called when the user picks a value.
export function variableBar(dashboard, variables, onChange) {
  const bar = h('div', { class: 'var-bar' });
  for (const def of (dashboard.templating || {}).list || []) {
    if (Number(def.hide) === 2 || def.type === 'constant') continue;
    const v = variables[def.name];
    if (!v) continue;
    const label = Number(def.hide) === 1 ? null : h('span', { class: 'var-label', text: def.label || def.name });
    let control;
    if (def.type === 'textbox') {
      // Enter commits and blurs; remember the committed value so blur does not fire a second change.
      let committed = Array.isArray(v.value) ? v.value[0] : v.value;
      const commit = (value) => { if (value === committed) return; committed = value; onChange(def.name, value); };
      control = input({ class: 'var-value', value: committed, label: def.label || def.name,
        onKeydown: (e) => { if (e.key === 'Enter') commit(e.target.value); },
        onBlur: (e) => commit(e.target.value) });
      control.classList.remove('input');
    } else {
      control = h('button', { type: 'button', class: 'var-value', title: v.text, onclick: (e) => dropdown(e.currentTarget, def, v, (value) => onChange(def.name, value)) },
        h('span', { style: { overflow: 'hidden', textOverflow: 'ellipsis' }, text: v.text || '—' }), icon('chevron-down'));
    }
    bar.append(h('div', { class: 'var-item' }, label, control));
  }
  return bar.childElementCount ? bar : null;
}

export const debouncedResolve = debounce((fn) => fn(), 150);
