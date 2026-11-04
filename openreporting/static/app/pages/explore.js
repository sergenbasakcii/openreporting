// Explore: a guided way to ask one question of a datasource without building a dashboard.
// 1) pick a source, 2) build the query (results refresh as you type), 3) save it as a panel.
import { h, button, clear, toast, debounce } from '../dom.js';
import { icon } from '../icons.js';
import { datasourcesList } from '../api.js';
import { setBreadcrumbs, navigate } from '../router.js';
import { timePicker, resolveRange } from '../time.js';
import { PanelView } from '../dashboard/panelview.js';
import { queriesTab } from '../query/editors.js';

const VIEWS = [
  { type: 'timeseries', label: 'Zaman serisi', icon: 'chart-line' },
  { type: 'barchart', label: 'Çubuk', icon: 'chart-bar' },
  { type: 'stat', label: 'Tek değer', icon: 'stat' },
  { type: 'gauge', label: 'Gösterge', icon: 'gauge' },
  { type: 'piechart', label: 'Pasta', icon: 'pie' },
  { type: 'table', label: 'Tablo', icon: 'table' },
];

// What a user should type for each source family, shown under the source picker.
const HINTS = {
  testdata: 'TestData gerçek değildir: denemek için örnek veri üretir. "Örnek veri" listesinden Zabbix simülasyonu, rastgele seri veya örnek tablo seçin. Gerçek veriler için başka bir kaynak seçin.',
  zabbix: 'Grup → host → item sırasıyla seçin; her alan bir önceki seçime göre daralır. Joker için * veya /regex/ yazabilirsiniz.',
  prometheus: 'PromQL yazın, ör. rate(node_cpu_seconds_total{mode!="idle"}[5m]).',
  loki: 'LogQL yazın, ör. {app="nginx"} |= "error" veya count_over_time({app="nginx"}[5m]).',
  postgres: 'SELECT sorgusu yazın. Zaman filtresi için $__timeFilter(sütun) makrosunu kullanın.',
  trino: 'Veri gölündeki tabloları SQL ile sorgulayın (katalog.şema.tablo). $__timeFilter(sütun) zaman aralığını ekler.',
  databricks: 'Lakehouse tablolarını SQL ile sorgulayın. $__timeFilter(sütun) zaman aralığını ekler.',
  clickhouse: 'SELECT sorgusu yazın; sunucu salt-okunur modda çalıştırır. $__timeFilter(sütun) zaman aralığını ekler.',
  elasticsearch: 'İndeks deseni ve Lucene sorgusu girin (ör. level:error). Metrik veya log görünümü seçin.',
  influxdb: 'InfluxQL yazın, ör. SELECT mean("usage") FROM "cpu" WHERE $timeFilter GROUP BY time($__interval).',
  graphite: 'Graphite hedefi yazın, ör. sumSeries(servers.*.cpu.user).',
};

const TYPE_LABELS = {
  testdata: 'Örnek veri (TestData)', zabbix: 'Zabbix', prometheus: 'Prometheus', loki: 'Loki', postgres: 'PostgreSQL', httpjson: 'HTTP JSON', csv: 'HTTP CSV',
  trino: 'Veri gölü · Trino/Presto', databricks: 'Lakehouse · Databricks SQL', clickhouse: 'ClickHouse', elasticsearch: 'Elasticsearch / OpenSearch',
  influxdb: 'InfluxDB', graphite: 'Graphite',
};

function sourceCard(ds, active, onPick) {
  return h('button', { type: 'button', class: 'source-card', role: 'radio', 'aria-checked': String(active), onClick: onPick },
    h('span', { class: 'source-icon' }, icon('database')), h('span', { class: 'source-text' }, h('b', { text: ds.name }), h('span', { class: 'hint', text: TYPE_LABELS[ds.type] || ds.type })));
}

function steps() {
  const step = (n, title, text) => h('li', h('span', { class: 'step-no', text: String(n) }), h('div', h('b', { text: title }), h('span', { class: 'hint', text })));
  return h('ol', { class: 'explore-steps' },
    step(1, 'Kaynak seçin', 'Hangi sistemden veri okunacak?'),
    step(2, 'Ne görmek istediğinizi seçin', 'Sorgu alanlarını doldurun; sonuç kendiliğinden yenilenir.'),
    step(3, 'Sonucu kaydedin', 'Beğendiğiniz sorguyu tek tıkla dashboard paneline dönüştürün.'));
}

export async function explorePage(root, { app }) {
  setBreadcrumbs([{ label: 'Keşfet' }]);
  // Ad-hoc queries are an editor capability; viewers only run saved dashboard panels.
  if (!['admin', 'editor'].includes(app.user.role)) {
    root.append(h('div', { class: 'page' }, h('div', { class: 'empty-state' }, h('h3', { text: 'Keşfet editörlere açıktır' }),
      h('p', { text: 'Serbest sorgu çalıştırmak için editör veya yönetici rolü gerekir. Kayıtlı dashboard’ları görüntüleyebilirsiniz.' }),
      h('div', { class: 'toolbar' }, button('Dashboard’lara git', { variant: 'primary', onClick: () => navigate('/dashboards') })))));
    return () => {};
  }
  const sources = await datasourcesList();
  if (!sources.length) {
    root.append(h('div', { class: 'page' }, h('div', { class: 'empty-state' }, h('h3', { text: 'Veri kaynağı yok' }), h('p', { text: 'Önce bir veri kaynağı ekleyin.' }),
      h('div', { class: 'toolbar' }, button('Veri kaynağı ekle', { variant: 'primary', onClick: () => navigate('/datasources/new') })))));
    return () => {};
  }
  const real = sources.filter((s) => s.type !== 'testdata');
  const def = real.find((s) => s.isDefault) || real[0] || sources[0];
  const panel = { id: 1, type: 'timeseries', title: 'Keşfet', datasource: { uid: def.uid }, targets: [{ refId: 'A' }],
    options: { legend: { displayMode: 'table', placement: 'bottom', calcs: ['mean', 'max', 'lastNotNull'] } }, fieldConfig: { defaults: { unit: 'auto' }, overrides: [] } };
  const state = { range: { from: 'now-6h', to: 'now' }, now: Date.now() };
  const ctx = () => ({ range: state.range, timezone: 'browser', variables: {}, scopedVars: {}, now: state.now, onZoom: (from, to) => { state.range = { from: String(from), to: String(to) }; tp.setRange(state.range); run(); } });
  const graph = new PanelView(panel, ctx(), {});
  const run = () => {
    state.now = Date.now();
    graph.panel = { ...panel, title: VIEWS.find((v) => v.type === panel.type).label };
    graph.setContext(ctx());
    graph.refresh();
  };
  const autoRun = debounce(run, 600);
  const tp = timePicker({ range: state.range, timezone: 'browser', onChange: (r) => { state.range = r; run(); }, getResolved: () => resolveRange(state.range, 'browser') });

  const viewBar = h('div', { class: 'segmented', role: 'radiogroup', 'aria-label': 'Görünüm' });
  const drawViews = () => {
    clear(viewBar);
    for (const v of VIEWS) {
      viewBar.append(h('button', { type: 'button', role: 'radio', 'aria-checked': String(panel.type === v.type), class: panel.type === v.type ? 'on' : '',
        onClick: () => { panel.type = v.type; drawViews(); run(); } }, icon(v.icon), v.label));
    }
  };
  drawViews();

  const hint = h('div', { class: 'alert', role: 'note' });
  const picker = h('div', { class: 'source-grid', role: 'radiogroup', 'aria-label': 'Veri kaynağı' });
  const editors = h('div');
  const drawSources = () => {
    clear(picker);
    for (const ds of sources) {
      picker.append(sourceCard(ds, ds.uid === panel.datasource.uid, () => {
        panel.datasource = { uid: ds.uid };
        panel.targets = [{ refId: 'A' }];
        drawSources(); drawEditors(); run();
      }));
    }
    const active = sources.find((s) => s.uid === panel.datasource.uid);
    hint.textContent = HINTS[active?.type] || 'Sorgu alanlarını doldurun; sonuç kendiliğinden yenilenir.';
    hint.className = active?.type === 'testdata' ? 'alert warn' : 'alert';
  };
  const drawEditors = () => { clear(editors); editors.append(queriesTab(panel, ctx(), autoRun)); };
  drawSources();
  drawEditors();

  const saveButton = button('Dashboard’a panel olarak kaydet', { icon: 'plus', variant: 'primary', onClick: () => {
    app.pendingDashboard = { title: 'Keşfet’ten yeni dashboard', tags: [], time: { ...state.range }, templating: { list: [] }, timezone: 'browser',
      panels: [{ ...JSON.parse(JSON.stringify(panel)), id: 1, title: 'Yeni panel', gridPos: { x: 0, y: 0, w: 24, h: 10 } }] };
    navigate('/dashboards/new');
  } });
  const page = h('div', { class: 'page wide explore-layout' },
    h('div', { class: 'page-header' }, h('div', h('h1', icon('compass'), 'Keşfet'),
      h('p', { class: 'sub', text: 'Dashboard kurmadan tek bir soruyu yanıtlayın: “Son 6 saatte web sunucularının CPU’su ne durumda?” gibi.' }))),
    steps(),
    h('section', { class: 'card', 'aria-labelledby': 'explore-src' }, h('h2', { class: 'section-heading', id: 'explore-src', text: '1 · Veri kaynağı' }), picker, hint),
    h('section', { class: 'card', 'aria-labelledby': 'explore-q' }, h('h2', { class: 'section-heading', id: 'explore-q', text: '2 · Sorgu' }), editors),
    h('section', { class: 'card', 'aria-labelledby': 'explore-r' },
      h('div', { class: 'explore-result-head' }, h('h2', { class: 'section-heading', id: 'explore-r', text: '3 · Sonuç' }), h('span', { class: 'spacer' }),
        viewBar, tp, button('Yenile', { icon: 'refresh', onClick: run }),
        button('Akıllı rapora ekle', { icon: 'report', title: 'Bu sonucu yeni bir akıllı dashboard sayfasına koy', onClick: () => {
          app.pendingSmartPanel = { ...JSON.parse(JSON.stringify(panel)), id: 1, title: VIEWS.find((v) => v.type === panel.type).label, timeRange: { ...state.range } };
          navigate('/smart/new');
        } }), saveButton),
      h('div', { class: 'explore-graph' }, graph.el)));
  root.append(page);
  run();
  const onKey = (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) run(); };
  document.addEventListener('keydown', onKey);
  return () => { graph.destroy(); document.removeEventListener('keydown', onKey); clear(root); };
}

export { toast };
