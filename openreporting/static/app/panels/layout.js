// Layout elements without queries (used mostly by smart dashboards; also valid on normal dashboards):
// image / logo, divider and a report information card. The PDF renderer draws the same three.
import { h } from '../dom.js';
import { icon } from '../icons.js';

const nothing = { resize() {}, destroy() {} };

export function renderImage(container, frames, panel) {
  const o = panel.options || {};
  if (!o.logo_id) {
    container.replaceChildren(h('div', { class: 'layout-empty' }, icon('upload'), h('span', { text: 'Görsel seçilmedi · sağ panelden yükleyin' })));
    return nothing;
  }
  container.replaceChildren(h('div', { class: `layout-image align-${o.align || 'center'}` },
    h('img', { src: `/api/dash-reports/logos/${encodeURIComponent(o.logo_id)}`, alt: panel.title || 'Logo', draggable: 'false' })));
  return nothing;
}

export function renderDivider(container, frames, panel) {
  const o = panel.options || {};
  container.replaceChildren(h('div', { class: `layout-divider style-${o.style || 'brand'}` }, h('i')));
  return nothing;
}

const fmt = (ms, tz) => {
  try {
    return new Intl.DateTimeFormat('tr-TR', { dateStyle: 'short', timeStyle: 'short', timeZone: tz && tz !== 'browser' ? (tz === 'utc' ? 'UTC' : tz) : undefined }).format(new Date(ms));
  } catch { return new Date(ms).toISOString(); }
};

export function renderReportInfo(container, frames, panel, ctx) {
  const o = panel.options || {};
  const r = ctx.timeRange && ctx.timeRange.from ? ctx.timeRange : null;
  const rows = [
    ['Rapor dönemi', r ? `${fmt(r.from, ctx.timezone)} – ${fmt(r.to, ctx.timezone)}` : `${ctx.range?.from || ''} → ${ctx.range?.to || ''}`],
    ['Saat dilimi', ctx.timezone && ctx.timezone !== 'browser' ? ctx.timezone : Intl.DateTimeFormat().resolvedOptions().timeZone],
    ['Oluşturulma', fmt(Date.now(), ctx.timezone)],
  ];
  if (o.showVariables !== false) {
    for (const [name, v] of Object.entries(ctx.variables || {})) if (v && v.text) rows.push([name, v.text]);
  }
  if (o.note) rows.push(['Not', o.note]);
  container.replaceChildren(h('dl', { class: 'layout-info' }, rows.map(([k, v], i) => [h('dt', { text: k }), h('dd', { class: i ? '' : 'strong', text: v })])));
  return nothing;
}

export const LAYOUT_PLUGINS = {
  image: { name: 'Logo / görsel', icon: 'upload', render: renderImage, noQueries: true, layout: true, defaults: { transparent: true, options: { align: 'center' } }, sections: [] },
  divider: { name: 'Ayırıcı / bölüm başlığı', icon: 'row', render: renderDivider, noQueries: true, layout: true, defaults: { transparent: true, options: { style: 'brand' } }, sections: [] },
  reportinfo: { name: 'Rapor bilgisi', icon: 'info', render: renderReportInfo, noQueries: true, layout: true, defaults: { options: { showVariables: true } }, sections: [] },
};
