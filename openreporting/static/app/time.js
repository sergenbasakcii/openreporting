// Time range model, picker and refresh picker (Grafana semantics, server-side resolution).
import { h, button, input, popover, closePopups, fmtDateTime, field, toast } from './dom.js';
import { icon } from './icons.js';
import { get } from './api.js';

export const QUICK_RANGES = [
  ['now-5m', 'now', 'Son 5 dakika'], ['now-15m', 'now', 'Son 15 dakika'], ['now-30m', 'now', 'Son 30 dakika'],
  ['now-1h', 'now', 'Son 1 saat'], ['now-3h', 'now', 'Son 3 saat'], ['now-6h', 'now', 'Son 6 saat'],
  ['now-12h', 'now', 'Son 12 saat'], ['now-24h', 'now', 'Son 24 saat'], ['now-2d', 'now', 'Son 2 gün'],
  ['now-7d', 'now', 'Son 7 gün'], ['now-30d', 'now', 'Son 30 gün'], ['now-90d', 'now', 'Son 90 gün'],
  ['now-6M', 'now', 'Son 6 ay'], ['now-1y', 'now', 'Son 1 yıl'],
  ['now/d', 'now/d', 'Bugün'], ['now/d', 'now', 'Bugün (şu ana kadar)'], ['now-1d/d', 'now-1d/d', 'Dün'],
  ['now/w', 'now/w', 'Bu hafta'], ['now/w', 'now', 'Bu hafta (şu ana kadar)'], ['now-1w/w', 'now-1w/w', 'Geçen hafta'],
  ['now/M', 'now/M', 'Bu ay'], ['now/M', 'now', 'Bu ay (şu ana kadar)'], ['now-1M/M', 'now-1M/M', 'Geçen ay'],
  ['now/y', 'now/y', 'Bu yıl'], ['now-1y/y', 'now-1y/y', 'Geçen yıl'],
];
export const REFRESH_INTERVALS = ['', '5s', '10s', '30s', '1m', '5m', '15m', '30m', '1h', '2h', '1d'];
const UNIT_MS = { ms: 1, s: 1000, m: 60000, h: 3600000, d: 86400000, w: 604800000, M: 2592000000, y: 31536000000 };

export function durationMs(text) {
  const m = /^(\d+(?:\.\d+)?)(ms|s|m|h|d|w|M|y)$/.exec(String(text || '').trim());
  return m ? Number(m[1]) * UNIT_MS[m[2]] : 0;
}

export function browserZone() {
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'; } catch { return 'UTC'; }
}
export function effectiveZone(tz) { return !tz || tz === 'browser' ? browserZone() : tz === 'utc' ? 'UTC' : tz; }

export function isAbsolute(value) { return /^\d{10,}$/.test(String(value)); }

export function rangeLabel(range, tz) {
  const quick = QUICK_RANGES.find(([f, t]) => f === range.from && t === range.to);
  if (quick) return quick[2];
  const fmt = (v) => (isAbsolute(v) ? fmtDateTime(Number(v), tz) : v);
  return `${fmt(range.from)} → ${fmt(range.to)}`;
}

export async function resolveRange(range, tz, now) {
  const params = new URLSearchParams({ start: range.from, end: range.to, tz: effectiveZone(tz) });
  if (now) params.set('now', String(now));
  return get(`/api/time/resolve?${params}`);
}

// Offset of `tz` from UTC at the given instant, in ms (positive east of Greenwich).
function zoneOffsetMs(epochMs, tz) {
  const fmt = new Intl.DateTimeFormat('en-US', { timeZone: tz, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const p = Object.fromEntries(fmt.formatToParts(new Date(epochMs)).map((x) => [x.type, x.value]));
  const asUtc = Date.UTC(Number(p.year), Number(p.month) - 1, Number(p.day), Number(p.hour) % 24, Number(p.minute), Number(p.second));
  return asUtc - Math.floor(epochMs / 1000) * 1000;
}

// Wall-clock time in `tz` → epoch ms; the second pass settles instants next to a DST change.
function zonedEpoch([year, month, day, hour, minute, second], tz) {
  const wall = Date.UTC(year, month - 1, day, hour, minute, second);
  const check = new Date(wall);
  if (check.getUTCFullYear() !== year || check.getUTCMonth() !== month - 1 || check.getUTCDate() !== day || hour > 23 || minute > 59 || second > 59) return null;
  const first = wall - zoneOffsetMs(wall, tz);
  return wall - zoneOffsetMs(first, tz);
}

const ISO_LOCAL = /^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?$/;
const TR_LOCAL = /^(\d{1,2})\.(\d{1,2})\.(\d{4})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?$/;

// Typed absolute times are wall-clock times in the dashboard's zone, not the browser's.
export function parseUserTime(text, tz) {
  const value = String(text || '').trim();
  if (!value) return null;
  if (value.startsWith('now') || isAbsolute(value)) return value;
  const iso = ISO_LOCAL.exec(value);
  const tr = iso ? null : TR_LOCAL.exec(value);
  if (iso || tr) {
    const [y, mo, d] = iso ? [iso[1], iso[2], iso[3]] : [tr[3], tr[2], tr[1]];
    const m = iso || tr;
    const epoch = zonedEpoch([y, mo, d, m[4] || 0, m[5] || 0, m[6] || 0].map(Number), effectiveZone(tz));
    return epoch === null ? null : String(epoch);
  }
  // Explicit offsets ("2026-10-24T10:00:00+03:00", "...Z") are unambiguous.
  if (/(Z|[+-]\d{2}:?\d{2})$/i.test(value)) {
    const date = new Date(value.replace(' ', 'T'));
    return Number.isNaN(date.getTime()) ? null : String(date.getTime());
  }
  return null;
}

function toInputText(value, tz) {
  if (!isAbsolute(value)) return value;
  const d = new Date(Number(value));
  const parts = new Intl.DateTimeFormat('sv-SE', { timeZone: effectiveZone(tz), year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(d);
  return parts.replace(',', '');
}

// Picker: onChange({from,to}); getResolved() returns last absolute {from,to} ms for zoom/shift.
export function timePicker({ range, timezone, onChange, getResolved, compact = false }) {
  const wrap = h('div', { class: 'timepicker' });
  const label = h('span', { class: 'tp-label' });
  const update = (r) => { label.textContent = rangeLabel(r, timezone); trigger.setAttribute('aria-label', `${label.textContent} · Zaman aralığı`); };
  const shift = async (direction) => {
    const resolved = getResolved ? await getResolved() : null;
    if (!resolved) return;
    const span = resolved.to - resolved.from;
    const delta = direction === 0 ? 0 : (span / 2) * direction;
    if (direction === 0) {
      const center = resolved.from + span / 2;
      onChange({ from: String(Math.round(center - span)), to: String(Math.min(Date.now(), Math.round(center + span))) });
    } else {
      onChange({ from: String(Math.round(resolved.from + delta)), to: String(Math.round(resolved.to + delta)) });
    }
  };
  const open = () => {
    const fromIn = input({ value: toInputText(range.from, timezone), placeholder: 'now-6h veya 2026-10-24 10:00:00' });
    const toIn = input({ value: toInputText(range.to, timezone), placeholder: 'now' });
    const apply = () => {
      const from = parseUserTime(fromIn.value, timezone);
      const to = parseUserTime(toIn.value, timezone);
      if (!from || !to) { toast('Geçersiz zaman: "now-6h", "now/d" veya "2026-10-24 10:00" yazın', 'error'); return; }
      closePopups();
      onChange({ from, to });
    };
    const quick = h('div', { class: 'quick' }, QUICK_RANGES.map(([from, to, text]) => h('button', {
      type: 'button', class: from === range.from && to === range.to ? 'on' : '', text, onclick: () => { closePopups(); onChange({ from, to }); } })));
    const abs = h('div', { class: 'abs' }, h('h4', { text: 'Mutlak zaman aralığı' }), field('Başlangıç', fromIn), field('Bitiş', toIn),
      button('Zaman aralığını uygula', { variant: 'primary', onClick: apply }),
      h('p', { class: 'hint', style: { marginTop: '12px' } }, `Saat dilimi: ${effectiveZone(timezone)}. Örnekler: now-24h, now/d (bugün), now-1M/M (geçen ay).`));
    popover(trigger, [abs, quick], { className: 'timepicker-pop', align: 'right' });
    setTimeout(() => fromIn.focus(), 10);
  };
  const trigger = button('', { icon: 'clock', onClick: open, title: 'Zaman aralığı' });
  // Icon + text button: drop the fixed square width of icon-only buttons.
  trigger.classList.remove('icon');
  trigger.append(label);
  update(range);
  if (!compact) wrap.append(button('', { icon: 'chevron-left', title: 'Geri kaydır', onClick: () => shift(-1) }));
  wrap.append(trigger);
  if (!compact) {
    wrap.append(button('', { icon: 'chevron-right', title: 'İleri kaydır', onClick: () => shift(1) }));
    wrap.append(button('', { icon: 'zoom-out', title: 'Uzaklaştır (aralığı 2 katına çıkar)', onClick: () => shift(0) }));
  }
  wrap.setRange = (r) => { range = r; update(r); };
  return wrap;
}

export function refreshPicker({ value, onRefresh, onInterval }) {
  const wrap = h('div', { class: 'timepicker' });
  const label = h('span', { text: value || '' });
  const refresh = button('', { icon: 'refresh', title: 'Yenile', onClick: () => onRefresh() });
  const pick = button('', { icon: 'chevron-down', title: 'Otomatik yenileme', onClick: () => {
    popover(pick, REFRESH_INTERVALS.map((iv) => h('button', { type: 'button', text: iv || 'Kapalı', onclick: () => {
      closePopups(); label.textContent = iv; name(iv); onInterval(iv);
    } })), { align: 'right' });
  } });
  pick.classList.remove('icon');
  pick.prepend(label);
  // The visible interval is part of the accessible name (WCAG 2.5.3 label in name).
  const name = (v) => pick.setAttribute('aria-label', v ? `${v} otomatik yenileme` : 'Otomatik yenileme');
  name(value);
  wrap.append(refresh, pick);
  wrap.setValue = (v) => { label.textContent = v || ''; name(v); };
  return wrap;
}

export { icon };
