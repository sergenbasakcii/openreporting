// Keyword chips for smart dashboards: "Grup · Host · Anahtar kelime" above each visualization.
// Clicking a chip opens a drill-down popup: options come from the datasource (each level is narrowed
// by the levels before it), a typed keyword becomes a case-insensitive "contains" match.
import { h, input, clear, popover, closePopups } from '../dom.js';
import { icon } from '../icons.js';
import { post } from '../api.js';
import { effectiveZone } from '../time.js';

export const LEVELS = [
  { key: 'group', label: 'Grup', empty: 'Tüm gruplar' },
  { key: 'host', label: 'Host', empty: 'Tüm hostlar' },
  { key: 'item', label: 'Anahtar kelime', empty: 'Metrik seçin' },
];

const escapeRegex = (text) => text.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&');
export const containsFilter = (word) => `/${escapeRegex(word)}/i`;

// Human-readable text for a stored filter value.
export function describe(value, empty) {
  if (!value || value === '/.*/' || value === '*') return empty;
  if (value === '$host' || value === '$group') return 'Rapor filtresi';
  const m = /^\/(.*)\/i$/.exec(value);
  return m ? `“${m[1].replace(/\\(.)/g, '$1')}” içerenler` : value;
}

export function filters(target) {
  const f = (k) => (target[k] && typeof target[k] === 'object' ? target[k].filter : target[k]) || '';
  return { group: f('group'), host: f('host'), item: f('item') };
}

async function options(dsUid, level, current, range, variables) {
  const query = level === 'group' ? { type: 'group' } : level === 'host' ? { type: 'host', group: current.group || '/.*/' }
    : { type: 'item', group: current.group || '/.*/', host: current.host || '/.*/' };
  const res = await post(`/api/datasources/${encodeURIComponent(dsUid)}/metric-find`, { query, range, timezone: effectiveZone('browser'), variables: variables || {} });
  return [...new Set(res.values.map((v) => v.text))].sort((a, b) => a.localeCompare(b, 'tr'));
}

function openPicker(anchor, { dsUid, level, current, range, variables, filters: reportFilters, onPick }) {
  const meta = LEVELS.find((l) => l.key === level);
  const list = h('div', { class: 'kw-options', role: 'listbox', 'aria-label': meta.label });
  const search = input({ placeholder: `${meta.label} ara veya anahtar kelime yazın`, label: `${meta.label} ara` });
  let all = [];
  const choose = (value) => { closePopups(); onPick(value); };
  const draw = () => {
    const word = search.value.trim();
    const shown = all.filter((o) => !word || o.toLocaleLowerCase('tr').includes(word.toLocaleLowerCase('tr'))).slice(0, 200);
    clear(list);
    if (word) list.append(h('button', { type: 'button', role: 'option', class: 'kw-option kw-keyword', onClick: () => choose(containsFilter(word)) }, icon('search'), `“${word}” içeren tümü`));
    if (reportFilters && level !== 'item') {
      list.append(h('button', { type: 'button', role: 'option', class: ['kw-option', 'kw-keyword', current[level] === `$${level}` ? 'on' : ''].join(' '), onClick: () => choose(`$${level}`) },
        icon('filter'), `Rapor filtresini kullan ($${level})`));
    }
    if (level !== 'item') list.append(h('button', { type: 'button', role: 'option', class: 'kw-option', onClick: () => choose('/.*/') }, icon('layers'), meta.empty));
    for (const o of shown) list.append(h('button', { type: 'button', role: 'option', class: ['kw-option', o === current[level] ? 'on' : ''].join(' '), onClick: () => choose(o), text: o }));
    if (!shown.length && !word) list.append(h('p', { class: 'hint', text: 'Seçenek bulunamadı. Bir anahtar kelime yazabilirsiniz.' }));
  };
  search.addEventListener('input', draw);
  search.addEventListener('keydown', (e) => { if (e.key === 'Enter' && search.value.trim()) choose(containsFilter(search.value.trim())); });
  list.append(h('p', { class: 'hint', text: 'Yükleniyor…' }));
  popover(anchor, [h('div', { class: 'kw-pop' }, h('div', { class: 'kw-crumb' },
    LEVELS.map((l) => h('span', { class: l.key === level ? 'on' : '', text: `${l.label}: ${describe(current[l.key], '—')}` }))), search, list)], { width: 340 });
  setTimeout(() => search.focus(), 0);
  options(dsUid, level, current, range, variables).then((values) => { all = values; draw(); }).catch(() => { all = []; draw(); });
}

// Chips for one target. onChange receives the new {group, host, item} filters.
export function keywordChips(target, { dsUid, range, variables, filters: reportFilters, onChange }) {
  const current = filters(target);
  return h('div', { class: 'kw-chips' }, LEVELS.map((level, i) => h('button', {
    type: 'button', class: ['kw-chip', current[level.key] && current[level.key] !== '/.*/' ? 'set' : ''].join(' '),
    title: `${level.label} seçin`,
    onClick: (e) => openPicker(e.currentTarget, { dsUid, level: level.key, current, range, variables, filters: reportFilters, onPick: (value) => {
      const next = { ...current, [level.key]: value };
      // A new parent selection invalidates the more specific levels below it.
      LEVELS.slice(i + 1).forEach((l) => { if (l.key !== 'item') next[l.key] = next[l.key] || '/.*/'; });
      onChange(next);
    } }),
  }, h('span', { class: 'kw-label', text: level.label }), h('span', { class: 'kw-value', text: describe(current[level.key], level.empty) }), icon('chevron-down'))));
}
