// Ready-made smart dashboard layouts (portrait A4, 24 × 32 cells). Keyword targets use the Zabbix
// item names; with report filters on, host/group come from the report-wide $group / $host selection.
const kw = (word) => `/${word.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&')}/i`;

export const TEMPLATES = [
  { id: 'blank', name: 'Boş sayfa', description: 'Sıfırdan başlayın.', icon: 'plus', filters: false, panels: [] },
  {
    id: 'executive', name: 'Yönetici özeti', icon: 'report', filters: true,
    description: 'Logo, rapor bilgisi, 4 KPI kartı, CPU eğilimi ve en yoğun bellek kullanımı.',
    panels: [
      { type: 'image', pos: [0, 0, 6, 3], title: 'Logo' },
      { type: 'divider', pos: [6, 0, 18, 3], title: 'Altyapı özeti' },
      { type: 'reportinfo', pos: [0, 3, 24, 4] },
      { type: 'stat', pos: [0, 7, 6, 5], title: 'Ortalama CPU', item: 'CPU utilization', unit: 'percent', calc: 'mean', thresholds: 'high-bad', agg: 'averageSeries', compare: true },
      { type: 'stat', pos: [6, 7, 6, 5], title: 'Bellek kullanımı (ort.)', item: 'Memory utilization', unit: 'percent', calc: 'lastNotNull', thresholds: 'high-bad', agg: 'averageSeries' },
      { type: 'stat', pos: [12, 7, 6, 5], title: 'En dolu disk', item: 'Space utilization', unit: 'percent', calc: 'lastNotNull', thresholds: 'high-bad', agg: 'maxSeries' },
      { type: 'stat', pos: [18, 7, 6, 5], title: 'ICMP kayıp (ort.)', item: 'ICMP loss', unit: 'percent', calc: 'mean', thresholds: 'high-bad', agg: 'averageSeries' },
      { type: 'narrative', pos: [0, 12, 24, 5], title: 'CPU · özet', item: 'CPU utilization', unit: 'percent', thresholds: 'high-bad', compare: true },
      { type: 'timeseries', pos: [0, 17, 24, 6], title: 'CPU kullanımı', item: 'CPU utilization', unit: 'percent', compare: true, agg: 'averageSeries' },
      { type: 'bargauge', pos: [0, 23, 24, 9], title: 'En yüksek bellek kullanımı · ilk 10', item: 'Memory utilization', unit: 'percent', calc: 'lastNotNull', thresholds: 'high-bad', top: 10 },
    ],
  },
  {
    id: 'host-health', name: 'Host sağlık raporu', icon: 'activity', filters: true, splitByHost: true,
    description: 'Her host için ayrı sayfa: CPU, bellek, disk, yük ve son değerler tablosu.',
    panels: [
      { type: 'divider', pos: [0, 0, 24, 3], title: '$host sağlık durumu' },
      { type: 'stat', pos: [0, 3, 8, 5], title: 'CPU (ortalama)', item: 'CPU utilization', unit: 'percent', calc: 'mean', thresholds: 'high-bad' },
      { type: 'gauge', pos: [8, 3, 8, 5], title: 'Bellek', item: 'Memory utilization', unit: 'percent', calc: 'lastNotNull', thresholds: 'high-bad' },
      { type: 'gauge', pos: [16, 3, 8, 5], title: 'Disk', item: 'Space utilization', unit: 'percent', calc: 'lastNotNull', thresholds: 'high-bad' },
      { type: 'timeseries', pos: [0, 8, 24, 8], title: 'CPU kullanımı', item: 'CPU utilization', unit: 'percent' },
      { type: 'timeseries', pos: [0, 16, 12, 8], title: 'Bellek', item: 'Memory utilization', unit: 'percent' },
      { type: 'timeseries', pos: [12, 16, 12, 8], title: 'Yük ortalaması', item: 'Load average' },
      { type: 'table', pos: [0, 24, 24, 8], title: 'Son değerler', item: '', queryType: 'itemvalues' },
    ],
  },
  {
    id: 'network', name: 'Ağ ve erişilebilirlik', icon: 'share', filters: true,
    description: 'ICMP kayıp ve gecikme, arayüz trafiği ve erişilebilirlik ızgarası.',
    panels: [
      { type: 'divider', pos: [0, 0, 24, 3], title: 'Ağ ve erişilebilirlik' },
      { type: 'stat', pos: [0, 3, 12, 5], title: 'ICMP kayıp (ortalama)', item: 'ICMP loss', unit: 'percent', calc: 'mean', thresholds: 'high-bad', agg: 'averageSeries' },
      { type: 'stat', pos: [12, 3, 12, 5], title: 'ICMP gecikme (ort.)', item: 'ICMP response time', unit: 's', calc: 'mean', agg: 'averageSeries' },
      { type: 'timeseries', pos: [0, 8, 24, 5], title: 'Arayüz trafiği', item: 'Bits', unit: 'bps' },
      { type: 'timeseries', pos: [0, 13, 24, 5], title: 'Arayüz trafiği · son 1 yıl', item: 'Bits', unit: 'bps', agg: 'sumSeries', range: { from: 'now-1y', to: 'now' } },
      { type: 'statusgrid', pos: [0, 18, 24, 7], title: 'ICMP kayıp · host bazında', item: 'ICMP loss', unit: 'percent', calc: 'lastNotNull', thresholds: 'high-bad' },
      { type: 'reportinfo', pos: [0, 25, 24, 4] },
    ],
  },
  {
    id: 'capacity', name: 'Kapasite planlama', icon: 'chart-bar', filters: true, range: { from: 'now-30d', to: 'now' },
    description: 'Son 30 gün: disk ve bellek doluluğu, CPU eğilimi, en dolu hostlar.',
    panels: [
      { type: 'divider', pos: [0, 0, 24, 3], title: 'Kapasite görünümü · son 30 gün' },
      { type: 'bargauge', pos: [0, 3, 12, 12], title: 'Disk doluluğu', item: 'Space utilization', unit: 'percent', calc: 'max', thresholds: 'high-bad' },
      { type: 'bargauge', pos: [12, 3, 12, 12], title: 'Bellek doluluğu', item: 'Memory utilization', unit: 'percent', calc: 'max', thresholds: 'high-bad' },
      { type: 'timeseries', pos: [0, 15, 24, 10], title: 'CPU eğilimi', item: 'CPU utilization', unit: 'percent' },
      { type: 'text', pos: [0, 25, 24, 7], content: '### Değerlendirme\nBu alana kapasite yorumlarınızı ve önerilerinizi yazın.' },
    ],
  },
];

export const THRESHOLDS = {
  none: null,
  'high-bad': { mode: 'absolute', steps: [{ color: 'green', value: null }, { color: '#EAB839', value: 70 }, { color: 'red', value: 90 }] },
  'low-bad': { mode: 'absolute', steps: [{ color: 'red', value: null }, { color: '#EAB839', value: 10 }, { color: 'green', value: 30 }] },
};

// Build panels for a template. `makeTarget(item, queryType)` returns the datasource-specific target.
export function buildTemplate(template, { nextId, datasource, makeTarget, rows }) {
  return template.panels.map((spec) => {
    const [x, y, w, h] = spec.pos;
    const panel = { id: nextId(), type: spec.type, title: spec.title || '', datasource, targets: [], options: {}, fieldConfig: { defaults: {}, overrides: [] },
      smartPos: { page: 0, x, y: Math.min(y, rows - h), w, h: Math.min(h, rows) } };
    if (['image', 'divider', 'reportinfo'].includes(spec.type)) panel.transparent = spec.type !== 'reportinfo';
    if (spec.type === 'divider') panel.options = { style: 'brand' };
    if (spec.type === 'reportinfo') panel.options = { showVariables: true };
    if (spec.type === 'text') panel.options = { mode: 'markdown', content: spec.content || '' };
    if (spec.range) panel.timeRange = { ...spec.range };
    if (spec.item !== undefined) {
      const target = makeTarget(spec.item ? kw(spec.item) : '/.*/', spec.queryType || 'metrics');
      if (spec.agg) target.functions = [{ name: spec.agg, params: [] }];
      panel.targets = [target];
      panel.titleLocked = true;
      if (spec.unit) panel.fieldConfig.defaults.unit = spec.unit;
      if (spec.thresholds && THRESHOLDS[spec.thresholds]) {
        panel.fieldConfig.defaults.thresholds = THRESHOLDS[spec.thresholds];
        panel.fieldConfig.defaults.color = { mode: 'thresholds' };
      }
      if (spec.calc) panel.options.reduceOptions = { calcs: [spec.calc] };
      if (spec.compare) panel.options.compare = 'previous';
      if (spec.top) panel.options.topN = spec.top;
      if (spec.compare && spec.type === 'stat') panel.options.compareGood = 'down';
    }
    return panel;
  });
}
