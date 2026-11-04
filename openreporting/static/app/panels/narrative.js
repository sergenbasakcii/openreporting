// Smart narrative: plain-language findings from a panel's series (same rules as reporting/narrative.py).
import { h } from '../dom.js';
import { formatValue, resolveUnit } from '../units.js';
import { displayName } from '../colors.js';
import { noData } from './common.js';

const MAX_NAMES = 5;
const TREND_MIN = 0.05;
const nothing = { resize() {}, destroy() {} };
const finite = (v) => typeof v === 'number' && Number.isFinite(v);
const mean = (vs) => (vs.length ? vs.reduce((a, b) => a + b, 0) / vs.length : null);
const pct = (x, digits = 0) => `%${(Math.abs(x) * 100).toLocaleString('tr-TR', { maximumFractionDigits: digits })}`;

function names(items) {
  const shown = items.slice(0, MAX_NAMES).map(([n]) => n);
  const more = items.length - shown.length;
  return shown.join(', ') + (more > 0 ? ` ve ${more} diğer` : '');
}

export function narrativeSentences(panel, frames, tz) {
  const ts = (frames || []).filter((f) => f.type === 'timeseries');
  const current = ts.filter((f) => !(f.meta && f.meta.previous)).map((f) => [displayName(f), f.points.filter((p) => finite(p[1])), f]).filter((s) => s[1].length);
  if (!current.length) return [];
  const defaults = panel.fieldConfig?.defaults || {};
  const unit = resolveUnit(defaults.unit, current[0][2].unit);
  const fmt = (v) => formatValue(v, unit, defaults.decimals);
  const subject = panel.options?.subject || panel.title || 'Değer';
  const all = current.flatMap(([name, pts]) => pts.map(([t, v]) => [t, v, name]));
  const overall = mean(all.map((p) => p[1]));
  const peak = all.reduce((a, b) => (b[1] > a[1] ? b : a));
  const low = all.reduce((a, b) => (b[1] < a[1] ? b : a));
  let when = '';
  try { when = new Intl.DateTimeFormat('tr-TR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', timeZone: tz && tz !== 'browser' ? (tz === 'utc' ? 'UTC' : tz) : undefined }).format(new Date(peak[0])); } catch { when = new Date(peak[0]).toISOString(); }
  const out = [`${subject} dönem boyunca ortalama ${fmt(overall)}; en yüksek ${fmt(peak[1])} (${peak[2]}, ${when}), en düşük ${fmt(low[1])}.`];
  if (current.length > 1) {
    const ranked = current.map(([n, pts]) => [n, mean(pts.map((p) => p[1]))]).sort((a, b) => b[1] - a[1]);
    out.push(`En yüksek ortalama ${ranked[0][0]} (${fmt(ranked[0][1])}), en düşük ${ranked[ranked.length - 1][0]} (${fmt(ranked[ranked.length - 1][1])}); ${current.length} seri incelendi.`);
  }
  const ordered = current.flatMap(([, pts]) => pts).sort((a, b) => a[0] - b[0]);
  const half = Math.floor(ordered.length / 2);
  if (half >= 2) {
    const first = mean(ordered.slice(0, half).map((p) => p[1])); const second = mean(ordered.slice(half).map((p) => p[1]));
    if (first) {
      const change = (second - first) / Math.abs(first);
      out.push(Math.abs(change) < TREND_MIN ? 'Dönem içinde belirgin bir eğilim yok; değerler kararlı.' : `Dönemin ikinci yarısında ilk yarıya göre ${pct(change)} ${change > 0 ? 'arttı' : 'azaldı'}.`);
    }
  }
  const steps = (defaults.thresholds?.steps || []).filter((s) => s.value !== null && s.value !== undefined);
  if (steps.length) {
    const top = steps.reduce((a, b) => (Number(b.value) > Number(a.value) ? b : a));
    const breaches = current.map(([n, pts]) => [n, pts[pts.length - 1][1]]).filter(([, v]) => v >= Number(top.value)).sort((a, b) => b[1] - a[1]);
    out.push(breaches.length ? `${breaches.length} seri son değerde ${fmt(Number(top.value))} eşiğinin üzerinde: ${names(breaches)}.` : `Hiçbir seri ${fmt(Number(top.value))} eşiğini aşmıyor.`);
  }
  const prev = ts.filter((f) => f.meta && f.meta.previous).flatMap((f) => f.points.map((p) => p[1]).filter(finite));
  const before = mean(prev);
  if (prev.length && before) {
    const change = (overall - before) / Math.abs(before);
    out.push(`Önceki döneme göre ortalama ${pct(change, 1)} ${change > 0 ? 'arttı' : change < 0 ? 'azaldı' : 'değişmedi'}.`);
  }
  return out;
}

export function renderNarrative(container, frames, panel, ctx) {
  const lines = narrativeSentences(panel, frames, ctx.timezone);
  if (!lines.length) { noData(container, 'Özet için veri yok'); return nothing; }
  container.replaceChildren(h('div', { class: 'narrative', tabindex: '0', role: 'group', 'aria-label': panel.title || 'Akıllı özet' }, h('ul', lines.map((t) => h('li', { text: t })))));
  return nothing;
}
