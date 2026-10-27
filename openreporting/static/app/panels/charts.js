// ECharts-based categorical visualizations: bar chart, pie chart, gauge, state timeline.
import { formatValue, resolveUnit } from '../units.js';
import { fieldConfigFor, displayName, PALETTE, color, thresholdColor } from '../colors.js';
import { reducedValues, display, chartTheme, initChart, noData, timeSeries, tables, timeAxisLabel } from './common.js';
import { escapeHtml } from './timeseries.js';

function wrap(container) {
  const box = document.createElement('div');
  box.className = 'viz-chart';
  box.style.height = '100%';
  container.replaceChildren(box);
  return box;
}

function controller(chart, theme) {
  return { chart, resize() { chart.resize(); }, destroy() { chart.dispose(); },
    png() { return chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: theme.bg }); } };
}

export function renderBarchart(container, frames, panel) {
  const theme = chartTheme();
  const opts = panel.options || {};
  let categories = [];
  let series = [];
  const table = tables(frames)[0];
  if (table && !timeSeries(frames).length) {
    const catIdx = Math.max(0, table.columns.findIndex((c) => c.type === 'string'));
    categories = table.rows.map((r) => String(r[catIdx] ?? ''));
    series = table.columns.map((c, i) => ({ c, i })).filter(({ c, i }) => c.type === 'number' && i !== catIdx).map(({ c, i }, n) => {
      const cfg = fieldConfigFor(panel, table, c.name);
      return { name: c.name, unit: resolveUnit(cfg.unit, c.unit), cfg, values: table.rows.map((r) => r[i]), color: cfg.color?.mode === 'fixed' ? color(cfg.color.fixedColor) : PALETTE[n % PALETTE.length] };
    });
  } else {
    const items = reducedValues(frames, panel);
    if (opts.sort === 'desc') items.sort((a, b) => (b.value ?? -Infinity) - (a.value ?? -Infinity));
    if (opts.sort === 'asc') items.sort((a, b) => (a.value ?? Infinity) - (b.value ?? Infinity));
    categories = items.map((i) => i.name);
    const first = items[0];
    series = first ? [{ name: (opts.reduceOptions?.calcs || ['lastNotNull'])[0], unit: first.unit, cfg: first.cfg,
      values: items.map((i) => i.value), colors: items.map((i) => i.color) }] : [];
  }
  if (!categories.length || !series.length) { noData(container); return { resize() {}, destroy() {} }; }
  const chart = initChart(wrap(container));
  const horizontal = opts.orientation === 'horizontal' || (opts.orientation !== 'vertical' && categories.length > 8);
  const unit = series[0].unit;
  const valueAxis = { type: 'value', axisLabel: { color: theme.muted, fontSize: 11, formatter: (v) => formatValue(v, unit, series[0].cfg.decimals) },
    splitLine: { lineStyle: { color: theme.grid } }, min: series[0].cfg.min, max: series[0].cfg.max };
  const catAxis = { type: 'category', data: categories, axisLabel: { color: theme.text, fontSize: 11, width: horizontal ? 160 : 90, overflow: 'truncate', interval: 0, rotate: horizontal ? 0 : (categories.length > 6 ? 30 : 0) },
    axisLine: { lineStyle: { color: theme.grid } }, inverse: horizontal };
  chart.setOption({
    animation: false, grid: { left: 8, right: 24, top: 10, bottom: 8, containLabel: true },
    tooltip: { trigger: 'axis', confine: true, backgroundColor: theme.tooltipBg, borderColor: theme.border, textStyle: { color: theme.text },
      valueFormatter: (v) => formatValue(v, unit, series[0].cfg.decimals) },
    legend: series.length > 1 ? { textStyle: { color: theme.text }, top: 0 } : { show: false },
    xAxis: horizontal ? valueAxis : catAxis, yAxis: horizontal ? catAxis : valueAxis,
    series: series.map((s) => ({ type: 'bar', name: s.name, data: s.values.map((v, i) => ({ value: v, itemStyle: { color: s.colors ? s.colors[i] : s.color } })),
      stack: opts.stacking === 'normal' ? 'all' : undefined, barMaxWidth: 48,
      label: { show: opts.showValue !== 'never', position: horizontal ? 'right' : 'top', color: theme.text, fontSize: 11,
        formatter: (p) => (p.value === null || p.value === undefined ? '' : formatValue(p.value, s.unit, s.cfg.decimals)) } })),
  }, true);
  return controller(chart, theme);
}

export function renderPiechart(container, frames, panel) {
  const theme = chartTheme();
  const items = reducedValues(frames, panel).filter((i) => i.value !== null && i.value !== undefined);
  if (!items.length) { noData(container); return { resize() {}, destroy() {} }; }
  const opts = panel.options || {};
  const chart = initChart(wrap(container));
  const total = items.reduce((a, i) => a + Math.abs(i.value), 0);
  const labels = opts.displayLabels || ['percent'];
  const legendPlacement = opts.legend?.placement === 'bottom' ? 'bottom' : 'right';
  chart.setOption({
    animation: false,
    tooltip: { trigger: 'item', confine: true, backgroundColor: theme.tooltipBg, borderColor: theme.border, textStyle: { color: theme.text },
      formatter: (p) => `${escapeHtml(p.name)}: <b>${escapeHtml(display(p.value, items[p.dataIndex]).text)}</b> (${p.percent}%)` },
    legend: opts.legend?.showLegend === false ? { show: false } : { type: 'scroll', orient: legendPlacement === 'right' ? 'vertical' : 'horizontal',
      right: legendPlacement === 'right' ? 4 : undefined, bottom: legendPlacement === 'bottom' ? 0 : undefined, top: legendPlacement === 'right' ? 'middle' : undefined,
      textStyle: { color: theme.text, fontSize: 12 },
      formatter: (name) => { const it = items.find((i) => i.name === name); return it ? `${name}  ${display(it.value, it).text}  ${total ? ((Math.abs(it.value) / total) * 100).toFixed(1) : 0}%` : name; } },
    series: [{ type: 'pie', radius: opts.pieType === 'donut' ? ['45%', '72%'] : [0, '72%'], center: legendPlacement === 'right' ? ['38%', '50%'] : ['50%', '45%'],
      avoidLabelOverlap: true, itemStyle: { borderColor: theme.bg, borderWidth: 1 },
      label: { show: labels.length > 0, color: theme.text, fontSize: 11, formatter: (p) => labels.map((l) => (l === 'name' ? p.name : l === 'value' ? display(p.value, items[p.dataIndex]).text : `${p.percent}%`)).join(' · ') },
      data: items.map((i, n) => ({ name: i.name, value: Math.abs(i.value), itemStyle: { color: i.cfg.color?.mode === 'thresholds' ? i.color : PALETTE[n % PALETTE.length] } })) }],
  }, true);
  return controller(chart, theme);
}

export function renderGauge(container, frames, panel) {
  const theme = chartTheme();
  const items = reducedValues(frames, panel);
  if (!items.length) { noData(container); return { resize() {}, destroy() {} }; }
  const box = wrap(container);
  const chart = initChart(box);
  const opts = panel.options || {};
  const count = items.length;
  const rect = container.getBoundingClientRect();
  const cols = Math.max(1, Math.min(count, Math.round(Math.sqrt(count * (rect.width / Math.max(1, rect.height))))));
  const rows = Math.ceil(count / cols);
  const series = items.map((item, i) => {
    const min = item.cfg.min ?? 0;
    const max = item.cfg.max ?? (item.unit === 'percent' ? 100 : Math.max(100, (item.value ?? 0) * 1.2));
    const steps = (item.cfg.thresholds && item.cfg.thresholds.steps) || [{ color: 'green', value: null }, { color: 'red', value: 80 }];
    const stops = [];
    steps.forEach((s, idx) => {
      const next = steps[idx + 1];
      let end = next ? Number(next.value) : max;
      if (item.cfg.thresholds?.mode === 'percentage' && next) end = min + ((max - min) * Number(next.value)) / 100;
      stops.push([Math.min(1, Math.max(0, (end - min) / (max - min || 1))), color(s.color)]);
    });
    const col = i % cols; const row = Math.floor(i / cols);
    const cx = ((col + 0.5) / cols) * 100; const cy = ((row + 0.58) / rows) * 100;
    const radius = Math.min(rect.width / cols, rect.height / rows) * 0.42;
    const d = display(item.value, item);
    return { type: 'gauge', min, max, center: [`${cx}%`, `${cy}%`], radius, startAngle: 210, endAngle: -30, progress: { show: true, width: Math.max(6, radius * 0.16), itemStyle: { color: d.color || item.color } },
      axisLine: { lineStyle: { width: Math.max(6, radius * 0.16), color: opts.showThresholdMarkers === false ? [[1, theme.grid]] : stops.map(([s, c]) => [s, c]).map(([s, c], k, arr) => [s, k === arr.length - 1 ? c : c]) } },
      pointer: { show: false }, axisTick: { show: false }, splitLine: { show: false },
      axisLabel: { show: opts.showThresholdLabels === true, color: theme.muted, fontSize: 10, distance: -radius * 0.35, formatter: (v) => formatValue(v, item.unit, item.cfg.decimals) },
      anchor: { show: false }, title: { show: true, offsetCenter: [0, '72%'], color: theme.text, fontSize: Math.max(10, Math.min(14, radius * 0.16)) },
      detail: { valueAnimation: false, offsetCenter: [0, '8%'], fontSize: Math.max(12, Math.min(36, radius * 0.38)), color: d.color || item.color, formatter: () => d.text },
      data: [{ value: item.value ?? min, name: count > 1 ? item.name : (opts.showName === false ? '' : item.name) }] };
  });
  chart.setOption({ animation: false, series }, true);
  return controller(chart, theme);
}

export function renderStateTimeline(container, frames, panel, ctx) {
  const theme = chartTheme();
  const series = timeSeries(frames);
  if (!series.length) { noData(container); return { resize() {}, destroy() {} }; }
  const chart = initChart(wrap(container));
  const names = series.map((s) => displayName(s));
  const data = [];
  series.forEach((frame, row) => {
    const cfg = fieldConfigFor(panel, frame, names[row]);
    const unit = resolveUnit(cfg.unit, frame.unit);
    const pts = frame.points;
    for (let i = 0; i < pts.length; i += 1) {
      const [t, v] = pts[i];
      const end = i + 1 < pts.length ? pts[i + 1][0] : (ctx.timeRange?.to || t);
      const mapped = (cfg.mappings || []).length ? display(v, { cfg, unit }) : null;
      const c = v === null ? 'rgba(128,128,128,.25)' : (mapped && mapped.color) || thresholdColor(v, cfg.thresholds, cfg.min ?? 0, cfg.max ?? 100) || PALETTE[0];
      data.push({ value: [row, t, end, v], itemStyle: { color: color(c) }, label: mapped ? mapped.text : formatValue(v, unit, cfg.decimals) });
    }
  });
  const span = (ctx.timeRange?.to || 0) - (ctx.timeRange?.from || 0);
  chart.setOption({
    animation: false, grid: { left: 8, right: 16, top: 8, bottom: 4, containLabel: true },
    tooltip: { confine: true, backgroundColor: theme.tooltipBg, borderColor: theme.border, textStyle: { color: theme.text },
      formatter: (p) => `${escapeHtml(names[p.value[0]])}<br/>${escapeHtml(new Date(p.value[1]).toLocaleString('tr-TR'))}: <b>${escapeHtml(p.data.label)}</b>` },
    xAxis: { type: 'time', min: ctx.timeRange?.from, max: ctx.timeRange?.to, axisLabel: { color: theme.muted, fontSize: 11, formatter: (v) => timeAxisLabel(v, span, ctx.timezone) }, splitLine: { show: false } },
    yAxis: { type: 'category', data: names, inverse: true, axisLabel: { color: theme.text, fontSize: 11, width: 150, overflow: 'truncate' }, axisLine: { show: false }, axisTick: { show: false } },
    series: [{ type: 'custom', encode: { x: [1, 2], y: 0 }, data,
      renderItem: (params, api) => {
        const row = api.value(0);
        const start = api.coord([api.value(1), row]);
        const end = api.coord([api.value(2), row]);
        const height = api.size([0, 1])[1] * 0.7;
        const shape = window.echarts.graphic.clipRectByRect({ x: start[0], y: start[1] - height / 2, width: Math.max(1, end[0] - start[0]), height },
          { x: params.coordSys.x, y: params.coordSys.y, width: params.coordSys.width, height: params.coordSys.height });
        return shape && { type: 'rect', shape, style: api.style() };
      } }],
  }, true);
  return controller(chart, theme);
}
