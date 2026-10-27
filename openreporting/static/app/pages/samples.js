// Sample dashboards built on the synthetic "TestData" Zabbix simulation (clearly tagged, not real data).
const DS = { uid: 'testdata' };
const q = (refId, group, host, item, functions = [], extra = {}) => ({ refId, datasource: DS, scenario: 'zabbix_sim', queryType: 'metrics',
  group: { filter: group }, host: { filter: host }, item: { filter: item }, itemTag: { filter: '' }, functions, ...extra });
const thresholds = (steps) => ({ mode: 'absolute', steps: [{ color: 'green', value: null }, ...steps] });

export function sampleDashboards() {
  const variables = [
    { name: 'group', label: 'Host grubu', type: 'query', datasource: DS, query: { type: 'group', group: '/.*/' }, refresh: 1, sort: 1, current: { value: 'Linux servers' } },
    { name: 'host', label: 'Host', type: 'query', datasource: DS, query: { type: 'host', group: '$group', host: '/.*/' }, refresh: 1, sort: 1, multi: true, includeAll: true, current: { value: ['$__all'] } },
  ];
  const noc = {
    uid: 'ornek-noc-ozet', title: 'Örnek · Ağ Operasyon Özeti', tags: ['örnek', 'testdata', 'grup-raporu'], timezone: 'browser', refresh: '1m',
    time: { from: 'now-24h', to: 'now' }, graphTooltip: 1, templating: { list: variables },
    panels: [
      { id: 1, type: 'text', title: '', gridPos: { x: 0, y: 0, w: 24, h: 3 }, transparent: true,
        options: { content: '### $group grubu · sentetik test verisi\nBu örnek **TestData** veri kaynağının Zabbix simülasyonunu kullanır. Gerçek Zabbix bağlandığında panel veri kaynağını değiştirmeniz yeterlidir.' } },
      { id: 2, type: 'stat', title: 'Grup CPU ortalaması', gridPos: { x: 0, y: 3, w: 6, h: 5 },
        targets: [q('A', '$group', '$host', 'CPU utilization', [{ name: 'aggregateBy', params: ['5m', 'avg'] }, { name: 'setAlias', params: ['Grup ortalaması'] }])],
        options: { reduceOptions: { calcs: ['mean'] }, colorMode: 'background', graphMode: 'area' }, fieldConfig: { defaults: { unit: 'percent', decimals: 1, thresholds: thresholds([{ color: 'orange', value: 60 }, { color: 'red', value: 80 }]) }, overrides: [] } },
      { id: 3, type: 'stat', title: 'En yüksek bellek kullanımı', gridPos: { x: 6, y: 3, w: 6, h: 5 },
        targets: [q('A', '$group', '$host', 'Memory utilization', [{ name: 'aggregateBy', params: ['5m', 'max'] }, { name: 'setAlias', params: ['Maksimum'] }])],
        options: { reduceOptions: { calcs: ['max'] }, colorMode: 'value', graphMode: 'area' }, fieldConfig: { defaults: { unit: 'percent', decimals: 1, thresholds: thresholds([{ color: 'orange', value: 70 }, { color: 'red', value: 90 }]) }, overrides: [] } },
      { id: 4, type: 'gauge', title: 'ICMP kayıp (ortalama)', gridPos: { x: 12, y: 3, w: 6, h: 5 },
        targets: [q('A', '$group', '$host', 'ICMP loss', [{ name: 'aggregateBy', params: ['5m', 'avg'] }])],
        options: { reduceOptions: { calcs: ['mean'] } }, fieldConfig: { defaults: { unit: 'percent', min: 0, max: 5, decimals: 2, thresholds: thresholds([{ color: 'orange', value: 1 }, { color: 'red', value: 2 }]) }, overrides: [] } },
      { id: 5, type: 'piechart', title: 'Toplam alınan trafik payı', gridPos: { x: 18, y: 3, w: 6, h: 5 },
        targets: [q('A', '$group', '$host', '/Bits received/', [{ name: 'setAlias', params: ['{{host}}'] }])],
        options: { reduceOptions: { calcs: ['mean'] }, pieType: 'donut', legend: { showLegend: false } }, fieldConfig: { defaults: { unit: 'bps' }, overrides: [] } },
      { id: 6, type: 'statusgrid', title: 'Host sağlık ızgarası · CPU', gridPos: { x: 0, y: 8, w: 24, h: 5 },
        targets: [q('A', '$group', '$host', 'CPU utilization')], options: { reduceOptions: { calcs: ['lastNotNull'] }, labelField: 'host', sort: 'name' },
        fieldConfig: { defaults: { unit: 'percent', decimals: 1, thresholds: thresholds([{ color: 'orange', value: 50 }, { color: 'red', value: 75 }]) }, overrides: [] } },
      { id: 7, type: 'timeseries', title: 'CPU kullanımı · host bazında', gridPos: { x: 0, y: 13, w: 12, h: 9 },
        targets: [q('A', '$group', '$host', 'CPU utilization', [{ name: 'setAlias', params: ['{{host}}'] }])],
        options: { legend: { displayMode: 'table', placement: 'bottom', calcs: ['mean', 'max', 'lastNotNull'] } },
        fieldConfig: { defaults: { unit: 'percent', min: 0, custom: { fillOpacity: 8, thresholdsStyle: { mode: 'line' } }, thresholds: thresholds([{ color: 'red', value: 80 }]) }, overrides: [] } },
      { id: 8, type: 'timeseries', title: 'Arayüz trafiği (giriş / çıkış)', gridPos: { x: 12, y: 13, w: 12, h: 9 },
        targets: [q('A', '$group', '$host', '/Bits received|Throughput/', [{ name: 'sumSeries' }, { name: 'setAlias', params: ['Giriş (toplam)'] }]),
          q('B', '$group', '$host', '/Bits sent/', [{ name: 'sumSeries' }, { name: 'setAlias', params: ['Çıkış (toplam)'] }])],
        fieldConfig: { defaults: { unit: 'bps', custom: { fillOpacity: 20, gradientMode: 'opacity' } },
          overrides: [{ matcher: { id: 'byFrameRefID', options: 'B' }, properties: [{ id: 'custom.transform', value: 'negative-Y' }, { id: 'color', value: { mode: 'fixed', fixedColor: '#FF9830' } }] },
            { matcher: { id: 'byFrameRefID', options: 'A' }, properties: [{ id: 'color', value: { mode: 'fixed', fixedColor: '#5794F2' } }] }] } },
      { id: 9, type: 'table', title: 'Grup özet tablosu (host × metrik, dönem ortalaması)', gridPos: { x: 0, y: 22, w: 14, h: 10 },
        targets: [q('A', '$group', '$host', '/^(CPU utilization|Memory utilization|ICMP loss)$/')],
        transformations: [{ id: 'reduceByLabel', options: { label: 'host', reducer: 'mean', columnBy: 'item' } }, { id: 'sortBy', options: { sort: [{ field: 'CPU utilization', desc: true }] } }],
        fieldConfig: { defaults: { decimals: 1, custom: { cellOptions: { type: 'color-text' } }, thresholds: thresholds([{ color: 'orange', value: 60 }, { color: 'red', value: 80 }]) }, overrides: [] } },
      { id: 10, type: 'bargauge', title: 'En yüksek 8 · bellek kullanımı', gridPos: { x: 14, y: 22, w: 10, h: 10 },
        targets: [q('A', '$group', '$host', 'Memory utilization', [{ name: 'top', params: [8, 'mean'] }, { name: 'setAlias', params: ['{{host}}'] }])],
        options: { reduceOptions: { calcs: ['mean'] }, displayMode: 'gradient', sort: 'desc' }, fieldConfig: { defaults: { unit: 'percent', min: 0, max: 100, thresholds: thresholds([{ color: 'orange', value: 60 }, { color: 'red', value: 80 }]) }, overrides: [] } },
      { id: 11, type: 'table', title: 'Aktif problemler', gridPos: { x: 0, y: 32, w: 24, h: 7 },
        targets: [{ refId: 'A', datasource: DS, scenario: 'zabbix_sim', queryType: 'problems', group: { filter: '/.*/' }, host: { filter: '/.*/' } }],
        fieldConfig: { defaults: {}, overrides: [{ matcher: { id: 'byName', options: 'Önem seviyesi' }, properties: [{ id: 'custom.hidden', value: true }] }] } },
    ],
  };
  const perHost = {
    uid: 'ornek-host-bazli', title: 'Örnek · Host Bazlı Grup Raporu', tags: ['örnek', 'testdata', 'grup-raporu'], timezone: 'browser', refresh: '',
    time: { from: 'now-7d', to: 'now' }, templating: { list: [{ ...variables[0], current: { value: 'WAN Routers' } }, variables[1]] },
    panels: [
      { id: 1, type: 'row', title: 'Host: $host', repeat: 'host', collapsed: false, gridPos: { x: 0, y: 0, w: 24, h: 1 } },
      { id: 2, type: 'stat', title: 'CPU (ort.)', gridPos: { x: 0, y: 1, w: 4, h: 5 }, targets: [q('A', '$group', '$host', 'CPU utilization')],
        options: { reduceOptions: { calcs: ['mean'] }, colorMode: 'value' }, fieldConfig: { defaults: { unit: 'percent', decimals: 1, thresholds: thresholds([{ color: 'orange', value: 50 }, { color: 'red', value: 75 }]) }, overrides: [] } },
      { id: 3, type: 'gauge', title: 'Bellek (son)', gridPos: { x: 4, y: 1, w: 4, h: 5 }, targets: [q('A', '$group', '$host', 'Memory utilization')],
        options: { reduceOptions: { calcs: ['lastNotNull'] } }, fieldConfig: { defaults: { unit: 'percent', min: 0, max: 100, thresholds: thresholds([{ color: 'orange', value: 70 }, { color: 'red', value: 85 }]) }, overrides: [] } },
      { id: 4, type: 'timeseries', title: 'Uplink trafiği', gridPos: { x: 8, y: 1, w: 16, h: 5 },
        targets: [q('A', '$group', '$host', '/Gi0\\/1.*received/', [{ name: 'setAlias', params: ['Giriş'] }]), q('B', '$group', '$host', '/Gi0\\/1.*sent/', [{ name: 'setAlias', params: ['Çıkış'] }])],
        options: { legend: { displayMode: 'list', calcs: ['mean', 'max'] } },
        fieldConfig: { defaults: { unit: 'bps', custom: { fillOpacity: 15 } }, overrides: [{ matcher: { id: 'byFrameRefID', options: 'B' }, properties: [{ id: 'custom.transform', value: 'negative-Y' }] }] } },
    ],
  };
  return [noc, perHost];
}
