// Dashboard overview and direct reporting actions; no additional query requests.
import { h, button } from '../dom.js';

export function dashboardOverview({ dashboard, folder, dirty, canEdit, saved, onExport, onReport, onAdd }) {
  const panels = [];
  function collect(items) {
    for (const panel of items || []) {
      if (panel.type === 'row') collect(panel.panels);
      else panels.push(panel);
    }
  }
  collect(dashboard.panels);
  const sources = new Set(panels.flatMap((p) => (p.targets || []).map((t) => {
    const source = t.datasource || p.datasource;
    return typeof source === 'string' ? source : source?.uid;
  })).filter(Boolean));
  const metric = (value, label) => h('div', { class: 'overview-metric' },
    h('strong', { text: String(value) }), h('span', { text: label }));
  return h('section', { class: 'dashboard-overview hide-kiosk', 'aria-label': 'Dashboard özeti' },
    h('div', { class: 'overview-heading' },
      h('div', { class: 'overview-eyebrow', text: `${folder || 'Genel'} / İZLEME ÇALIŞMA ALANI` }),
      h('h1', { text: dashboard.title }),
      h('p', { text: dashboard.description || 'Metriklerinizi birlikte izleyin, aynı veriden paylaşılabilir raporlar hazırlayın.' }),
      h('div', { class: 'overview-state' },
        h('span', { class: `badge ${dirty ? 'warn' : 'info'}`, text: dirty ? 'Kaydedilmemiş değişiklikler' : 'Kayıtlı dashboard' }),
        h('span', { text: 'PDF · Excel · Zamanlanmış raporlar' }))),
    h('div', { class: 'overview-side' },
      h('div', { class: 'overview-metrics' }, metric(panels.length, 'Panel'), metric(sources.size, 'Sorgu kaynağı'),
        metric(dashboard.templating?.list?.length || 0, 'Değişken')),
      h('div', { class: 'overview-actions' },
        button('PDF indir', { icon: 'download', disabled: !saved || dirty, onClick: () => onExport('pdf') }),
        button('Excel indir', { icon: 'download', disabled: !saved || dirty, onClick: () => onExport('xlsx') }),
        canEdit ? button('Rapor hazırla', { icon: 'report', variant: 'primary', disabled: !saved || dirty, onClick: onReport }) : null,
        canEdit ? button('Panel ekle', { icon: 'plus', onClick: onAdd }) : null)));
}
