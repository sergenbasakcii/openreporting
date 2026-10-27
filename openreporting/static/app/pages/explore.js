// Explore: ad-hoc queries with chart + table, then "add to dashboard".
import { h, button, select, clear, toast } from '../dom.js';
import { icon } from '../icons.js';
import { datasourcesList } from '../api.js';
import { setBreadcrumbs, navigate } from '../router.js';
import { timePicker, resolveRange } from '../time.js';
import { PanelView } from '../dashboard/panelview.js';
import { queriesTab } from '../query/editors.js';

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
    root.append(h('div', { class: 'page' }, h('div', { class: 'empty-state' }, h('h3', { text: 'Veri kaynağı yok' }), h('p', { text: 'Önce bir veri kaynağı ekleyin.' }))));
    return () => {};
  }
  const def = sources.find((s) => s.isDefault) || sources[0];
  const panel = { id: 1, type: 'timeseries', title: 'Keşfet', datasource: { uid: def.uid }, targets: [{ refId: 'A' }],
    options: { legend: { displayMode: 'table', placement: 'bottom', calcs: ['mean', 'max', 'lastNotNull'] } }, fieldConfig: { defaults: { unit: 'auto' }, overrides: [] } };
  const state = { range: { from: 'now-6h', to: 'now' }, now: Date.now() };
  const ctx = () => ({ range: state.range, timezone: 'browser', variables: {}, scopedVars: {}, now: state.now, onZoom: (from, to) => { state.range = { from: String(from), to: String(to) }; tp.setRange(state.range); run(); } });
  const graph = new PanelView(panel, ctx(), {});
  const table = new PanelView({ ...panel, type: 'table', title: 'Tablo görünümü' }, ctx(), {});
  const run = () => {
    state.now = Date.now();
    graph.panel = { ...panel };
    table.panel = { ...panel, type: 'table', title: 'Tablo görünümü' };
    graph.setContext(ctx()); table.setContext(ctx());
    graph.refresh(); table.refresh();
  };
  const tp = timePicker({ range: state.range, timezone: 'browser', onChange: (r) => { state.range = r; run(); }, getResolved: () => resolveRange(state.range, 'browser') });
  const vizSel = select([{ value: 'timeseries', label: 'Zaman serisi' }, { value: 'barchart', label: 'Çubuk' }, { value: 'stat', label: 'Stat' }, { value: 'statusgrid', label: 'Durum ızgarası' }],
    'timeseries', (v) => { panel.type = v; run(); });
  const editors = h('div', { class: 'card' });
  editors.append(queriesTab(panel, ctx(), () => {}));
  const page = h('div', { class: 'page wide explore-layout' },
    h('div', { class: 'page-header' }, h('div', h('h1', icon('compass'), 'Keşfet'), h('p', { class: 'sub', text: 'Bir dashboard oluşturmadan metrik sorgulayın; beğendiğiniz sorguyu panele dönüştürün.' })),
      h('div', { class: 'toolbar' }, vizSel, tp, button('Sorguyu çalıştır', { icon: 'play', variant: 'primary', onClick: run }),
        ['admin', 'editor'].includes(app.user.role) ? button('Dashboard’a ekle', { icon: 'plus', onClick: () => {
          app.pendingDashboard = { title: 'Keşfet’ten yeni dashboard', tags: [], time: { ...state.range }, templating: { list: [] }, timezone: 'browser',
            panels: [{ ...JSON.parse(JSON.stringify(panel)), id: 1, title: 'Yeni panel', gridPos: { x: 0, y: 0, w: 24, h: 10 } }] };
          navigate('/dashboards/new');
        } }) : null)),
    editors,
    h('div', { class: 'card explore-graph' }, graph.el),
    h('div', { class: 'card', style: { height: '360px', position: 'relative' } }, table.el));
  root.append(page);
  const onKey = (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) run(); };
  document.addEventListener('keydown', onKey);
  return () => { graph.destroy(); table.destroy(); document.removeEventListener('keydown', onKey); clear(root); };
}

export { toast };
