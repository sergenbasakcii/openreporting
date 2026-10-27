// Visualization plugins: renderers, defaults and option schemas used by the panel editor.
import { render as renderTimeseries } from './timeseries.js';
import { renderBarchart, renderPiechart, renderGauge, renderStateTimeline } from './charts.js';
import { renderStat, renderBarGauge, renderTable, renderStatusGrid, renderText } from './dompanels.js';
import { REDUCERS } from './common.js';

const calcOptions = Object.entries(REDUCERS).map(([value, label]) => ({ value, label }));
const reduceSection = [
  { path: 'options.reduceOptions.calcs', label: 'Hesaplama', type: 'calc', default: ['lastNotNull'] },
  { path: 'options.reduceOptions.values', label: 'Tüm değerler (tablo satırları)', type: 'switch', default: false },
  { path: 'options.reduceOptions.limit', label: 'Gösterim sınırı (0 = sınırsız)', type: 'number', default: 0 },
];
const legendSection = [
  { path: 'options.legend.showLegend', label: 'Göster', type: 'switch', default: true },
  { path: 'options.legend.displayMode', label: 'Mod', type: 'radio', options: [{ value: 'list', label: 'Liste' }, { value: 'table', label: 'Tablo' }], default: 'list' },
  { path: 'options.legend.placement', label: 'Konum', type: 'radio', options: [{ value: 'bottom', label: 'Alt' }, { value: 'right', label: 'Sağ' }], default: 'bottom' },
  { path: 'options.legend.calcs', label: 'Değerler', type: 'multicalc', default: [] },
];

export const PLUGINS = {
  timeseries: {
    name: 'Zaman serisi', icon: 'chart-line', render: renderTimeseries, thresholds: true, zoom: true,
    defaults: { options: { legend: { showLegend: true, displayMode: 'list', placement: 'bottom', calcs: [] }, tooltip: { mode: 'multi' } },
      fieldConfig: { defaults: { unit: 'auto', color: { mode: 'palette-classic' }, custom: { drawStyle: 'line', lineInterpolation: 'linear', lineWidth: 1, fillOpacity: 10, showPoints: 'auto', spanNulls: false, stacking: { mode: 'none' }, axisPlacement: 'auto', thresholdsStyle: { mode: 'off' } },
        thresholds: { mode: 'absolute', steps: [{ color: 'green', value: null }, { color: 'red', value: 80 }] } }, overrides: [] } },
    sections: [
      { title: 'Lejant', items: legendSection },
      { title: 'İpucu', items: [{ path: 'options.tooltip.mode', label: 'Mod', type: 'radio', options: [{ value: 'single', label: 'Tek' }, { value: 'multi', label: 'Tümü' }, { value: 'none', label: 'Gizli' }], default: 'multi' }] },
      { title: 'Grafik stili', items: [
        { path: 'fieldConfig.defaults.custom.drawStyle', label: 'Stil', type: 'radio', options: [{ value: 'line', label: 'Çizgi' }, { value: 'bars', label: 'Çubuk' }, { value: 'points', label: 'Nokta' }], default: 'line' },
        { path: 'fieldConfig.defaults.custom.lineInterpolation', label: 'Çizgi enterpolasyonu', type: 'radio', options: [{ value: 'linear', label: 'Doğrusal' }, { value: 'smooth', label: 'Yumuşak' }, { value: 'stepAfter', label: 'Basamak' }], default: 'linear' },
        { path: 'fieldConfig.defaults.custom.lineWidth', label: 'Çizgi kalınlığı', type: 'number', min: 0, max: 10, default: 1 },
        { path: 'fieldConfig.defaults.custom.fillOpacity', label: 'Dolgu opaklığı (0-100)', type: 'number', min: 0, max: 100, default: 10 },
        { path: 'fieldConfig.defaults.custom.gradientMode', label: 'Gradyan', type: 'radio', options: [{ value: 'none', label: 'Yok' }, { value: 'opacity', label: 'Opaklık' }], default: 'none' },
        { path: 'fieldConfig.defaults.custom.showPoints', label: 'Noktaları göster', type: 'radio', options: [{ value: 'auto', label: 'Otomatik' }, { value: 'always', label: 'Her zaman' }, { value: 'never', label: 'Asla' }], default: 'auto' },
        { path: 'fieldConfig.defaults.custom.spanNulls', label: 'Boşlukları birleştir', type: 'switch', default: false },
        { path: 'fieldConfig.defaults.custom.stacking.mode', label: 'Yığınla', type: 'radio', options: [{ value: 'none', label: 'Kapalı' }, { value: 'normal', label: 'Normal' }, { value: 'percent', label: '%100' }], default: 'none' },
      ] },
      { title: 'Eksen', items: [
        { path: 'fieldConfig.defaults.custom.axisPlacement', label: 'Yerleşim', type: 'radio', options: [{ value: 'auto', label: 'Otomatik' }, { value: 'left', label: 'Sol' }, { value: 'right', label: 'Sağ' }, { value: 'hidden', label: 'Gizli' }], default: 'auto' },
        { path: 'fieldConfig.defaults.custom.axisLabel', label: 'Eksen etiketi', type: 'text', default: '' },
        { path: 'fieldConfig.defaults.custom.axisSoftMin', label: 'Yumuşak min', type: 'number', default: null },
        { path: 'fieldConfig.defaults.custom.axisSoftMax', label: 'Yumuşak max', type: 'number', default: null },
        { path: 'fieldConfig.defaults.custom.scaleDistribution.type', label: 'Ölçek', type: 'radio', options: [{ value: 'linear', label: 'Doğrusal' }, { value: 'log', label: 'Logaritmik' }], default: 'linear' },
        { path: 'fieldConfig.defaults.custom.thresholdsStyle.mode', label: 'Eşikleri göster', type: 'select', options: [{ value: 'off', label: 'Kapalı' }, { value: 'line', label: 'Çizgi' }, { value: 'area', label: 'Alan' }, { value: 'line+area', label: 'Çizgi + alan' }], default: 'off' },
      ] },
    ],
  },
  barchart: {
    name: 'Çubuk grafik', icon: 'chart-bar', render: renderBarchart, thresholds: true,
    defaults: { options: { reduceOptions: { calcs: ['mean'] }, orientation: 'auto', showValue: 'auto', sort: 'none' }, fieldConfig: { defaults: { unit: 'auto', color: { mode: 'palette-classic' } }, overrides: [] } },
    sections: [{ title: 'Değer hesaplama', items: reduceSection }, { title: 'Çubuk grafik', items: [
      { path: 'options.orientation', label: 'Yön', type: 'radio', options: [{ value: 'auto', label: 'Otomatik' }, { value: 'horizontal', label: 'Yatay' }, { value: 'vertical', label: 'Dikey' }], default: 'auto' },
      { path: 'options.showValue', label: 'Değerleri göster', type: 'radio', options: [{ value: 'auto', label: 'Otomatik' }, { value: 'never', label: 'Asla' }], default: 'auto' },
      { path: 'options.sort', label: 'Sırala', type: 'radio', options: [{ value: 'none', label: 'Yok' }, { value: 'desc', label: 'Azalan' }, { value: 'asc', label: 'Artan' }], default: 'none' },
      { path: 'options.stacking', label: 'Yığınla', type: 'radio', options: [{ value: 'none', label: 'Kapalı' }, { value: 'normal', label: 'Normal' }], default: 'none' }] }],
  },
  stat: {
    name: 'Stat', icon: 'stat', render: renderStat, thresholds: true,
    defaults: { options: { reduceOptions: { calcs: ['lastNotNull'], values: false }, colorMode: 'value', graphMode: 'area', textMode: 'auto', orientation: 'auto' },
      fieldConfig: { defaults: { unit: 'auto', color: { mode: 'thresholds' }, thresholds: { mode: 'absolute', steps: [{ color: 'green', value: null }, { color: 'red', value: 80 }] } }, overrides: [] } },
    sections: [{ title: 'Değer hesaplama', items: reduceSection }, { title: 'Stat stili', items: [
      { path: 'options.colorMode', label: 'Renk modu', type: 'radio', options: [{ value: 'value', label: 'Değer' }, { value: 'background', label: 'Arka plan' }, { value: 'none', label: 'Yok' }], default: 'value' },
      { path: 'options.graphMode', label: 'Grafik', type: 'radio', options: [{ value: 'area', label: 'Alan' }, { value: 'none', label: 'Yok' }], default: 'area' },
      { path: 'options.textMode', label: 'Metin', type: 'select', options: [{ value: 'auto', label: 'Otomatik' }, { value: 'value', label: 'Değer' }, { value: 'value_and_name', label: 'Değer ve ad' }, { value: 'name', label: 'Ad' }], default: 'auto' },
      { path: 'options.orientation', label: 'Yön', type: 'radio', options: [{ value: 'auto', label: 'Otomatik' }, { value: 'horizontal', label: 'Yatay' }, { value: 'vertical', label: 'Dikey' }], default: 'auto' }] }],
  },
  gauge: {
    name: 'Gösterge', icon: 'gauge', render: renderGauge, thresholds: true,
    defaults: { options: { reduceOptions: { calcs: ['lastNotNull'] }, showThresholdMarkers: true, showThresholdLabels: false },
      fieldConfig: { defaults: { unit: 'auto', min: 0, max: 100, color: { mode: 'thresholds' }, thresholds: { mode: 'absolute', steps: [{ color: 'green', value: null }, { color: 'orange', value: 70 }, { color: 'red', value: 85 }] } }, overrides: [] } },
    sections: [{ title: 'Değer hesaplama', items: reduceSection }, { title: 'Gösterge', items: [
      { path: 'options.showThresholdMarkers', label: 'Eşik işaretleri', type: 'switch', default: true },
      { path: 'options.showThresholdLabels', label: 'Eşik etiketleri', type: 'switch', default: false }] }],
  },
  bargauge: {
    name: 'Çubuk gösterge', icon: 'bar-gauge', render: renderBarGauge, thresholds: true,
    defaults: { options: { reduceOptions: { calcs: ['lastNotNull'] }, displayMode: 'gradient', showUnfilled: true, sort: 'none' },
      fieldConfig: { defaults: { unit: 'auto', color: { mode: 'thresholds' }, thresholds: { mode: 'absolute', steps: [{ color: 'green', value: null }, { color: 'orange', value: 70 }, { color: 'red', value: 85 }] } }, overrides: [] } },
    sections: [{ title: 'Değer hesaplama', items: reduceSection }, { title: 'Çubuk gösterge', items: [
      { path: 'options.displayMode', label: 'Görünüm', type: 'radio', options: [{ value: 'gradient', label: 'Gradyan' }, { value: 'lcd', label: 'LCD' }, { value: 'basic', label: 'Düz' }], default: 'gradient' },
      { path: 'options.showUnfilled', label: 'Dolmamış alanı göster', type: 'switch', default: true },
      { path: 'options.sort', label: 'Sırala', type: 'radio', options: [{ value: 'none', label: 'Yok' }, { value: 'desc', label: 'Azalan' }], default: 'none' }] }],
  },
  table: {
    name: 'Tablo', icon: 'table', render: renderTable, thresholds: true,
    defaults: { options: { showHeader: true, footer: { show: false, reducer: ['sum'] } }, fieldConfig: { defaults: { unit: 'auto', custom: { cellOptions: { type: 'auto' }, align: 'auto' },
      thresholds: { mode: 'absolute', steps: [{ color: 'green', value: null }, { color: 'red', value: 80 }] } }, overrides: [] } },
    sections: [{ title: 'Tablo', items: [
      { path: 'fieldConfig.defaults.custom.cellOptions.type', label: 'Hücre görünümü', type: 'select', options: [{ value: 'auto', label: 'Otomatik' }, { value: 'color-text', label: 'Renkli metin' }, { value: 'color-background', label: 'Renkli arka plan' }, { value: 'gauge', label: 'Gösterge çubuğu' }], default: 'auto' },
      { path: 'options.footer.show', label: 'Alt toplam satırı', type: 'switch', default: false },
      { path: 'options.footer.reducer', label: 'Alt satır hesaplaması', type: 'calc', default: ['sum'] }] }],
  },
  piechart: {
    name: 'Pasta grafik', icon: 'pie', render: renderPiechart,
    defaults: { options: { reduceOptions: { calcs: ['lastNotNull'] }, pieType: 'pie', displayLabels: ['percent'], legend: { showLegend: true, placement: 'right' } },
      fieldConfig: { defaults: { unit: 'auto', color: { mode: 'palette-classic' } }, overrides: [] } },
    sections: [{ title: 'Değer hesaplama', items: reduceSection }, { title: 'Pasta grafik', items: [
      { path: 'options.pieType', label: 'Tür', type: 'radio', options: [{ value: 'pie', label: 'Pasta' }, { value: 'donut', label: 'Halka' }], default: 'pie' },
      { path: 'options.displayLabels', label: 'Etiketler', type: 'multi', options: [{ value: 'name', label: 'Ad' }, { value: 'value', label: 'Değer' }, { value: 'percent', label: 'Yüzde' }], default: ['percent'] },
      { path: 'options.legend.showLegend', label: 'Lejant', type: 'switch', default: true },
      { path: 'options.legend.placement', label: 'Lejant konumu', type: 'radio', options: [{ value: 'right', label: 'Sağ' }, { value: 'bottom', label: 'Alt' }], default: 'right' }] }],
  },
  statusgrid: {
    name: 'Durum ızgarası', icon: 'status-grid', render: renderStatusGrid, thresholds: true,
    defaults: { options: { reduceOptions: { calcs: ['lastNotNull'] }, labelField: 'host', showValue: true, sort: 'name', minCellWidth: 130 },
      fieldConfig: { defaults: { unit: 'auto', color: { mode: 'thresholds' }, thresholds: { mode: 'absolute', steps: [{ color: 'green', value: null }, { color: 'orange', value: 70 }, { color: 'red', value: 85 }] } }, overrides: [] } },
    sections: [{ title: 'Değer hesaplama', items: reduceSection }, { title: 'Durum ızgarası', items: [
      { path: 'options.labelField', label: 'Hücre etiketi (seri etiketi)', type: 'select', options: [{ value: 'host', label: 'Host' }, { value: 'item', label: 'Item' }, { value: 'group', label: 'Grup' }, { value: 'name', label: 'Seri adı' }], default: 'host' },
      { path: 'options.showValue', label: 'Değeri göster', type: 'switch', default: true },
      { path: 'options.sort', label: 'Sırala', type: 'radio', options: [{ value: 'name', label: 'Ad' }, { value: 'value', label: 'Değer' }, { value: 'none', label: 'Yok' }], default: 'name' },
      { path: 'options.minCellWidth', label: 'En küçük hücre genişliği (px)', type: 'number', min: 60, max: 400, default: 130 }] }],
  },
  statetimeline: {
    name: 'Durum zaman çizelgesi', icon: 'timeline', render: renderStateTimeline, thresholds: true,
    defaults: { options: {}, fieldConfig: { defaults: { unit: 'auto', color: { mode: 'thresholds' }, thresholds: { mode: 'absolute', steps: [{ color: 'red', value: null }, { color: 'green', value: 1 }] } }, overrides: [] } },
    sections: [],
  },
  text: {
    name: 'Metin', icon: 'text', render: renderText, noQueries: true,
    defaults: { options: { mode: 'markdown', content: '# Başlık\n\nBu metin **Markdown** destekler. Değişkenler: $host' } },
    sections: [{ title: 'Metin', items: [{ path: 'options.content', label: 'İçerik (Markdown)', type: 'textarea', default: '' }] }],
  },
};

export const ORDER = ['timeseries', 'barchart', 'stat', 'gauge', 'bargauge', 'table', 'piechart', 'statusgrid', 'statetimeline', 'text'];
export const CALC_OPTIONS = calcOptions;

export function plugin(type) { return PLUGINS[type] || PLUGINS.timeseries; }

export function getPath(obj, path) {
  return path.split('.').reduce((cur, key) => (cur === undefined || cur === null ? undefined : cur[key]), obj);
}

export function setPathImmutable(obj, path, value) {
  const parts = path.split('.');
  const out = Array.isArray(obj) ? [...obj] : { ...(obj || {}) };
  let cur = out;
  for (let i = 0; i < parts.length - 1; i += 1) {
    cur[parts[i]] = { ...(cur[parts[i]] || {}) };
    cur = cur[parts[i]];
  }
  cur[parts[parts.length - 1]] = value;
  return out;
}

function deepMerge(base, extra) {
  if (Array.isArray(base) || Array.isArray(extra) || typeof base !== 'object' || typeof extra !== 'object' || !base || !extra) return extra === undefined ? base : extra;
  const out = { ...base };
  for (const [k, v] of Object.entries(extra)) out[k] = k in base ? deepMerge(base[k], v) : v;
  return out;
}

export function withDefaults(panel) {
  const p = plugin(panel.type);
  const defaults = JSON.parse(JSON.stringify(p.defaults || {}));
  return { ...panel, options: deepMerge(defaults.options || {}, panel.options || {}), fieldConfig: deepMerge(defaults.fieldConfig || { defaults: {}, overrides: [] }, panel.fieldConfig || {}) };
}

export function newPanel(type, id, gridPos) {
  const p = plugin(type);
  return { id, type, title: 'Yeni panel', gridPos, datasource: null, targets: p.noQueries ? undefined : [{ refId: 'A' }],
    ...JSON.parse(JSON.stringify(p.defaults || {})) };
}
