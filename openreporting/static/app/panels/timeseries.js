// Time series visualization (ECharts): lines/bars/points, stacking, dual axis, thresholds, legend table, drag-to-zoom.
import { h } from '../dom.js';
import { formatValue, resolveUnit } from '../units.js';
import { fieldConfigFor, displayName, PALETTE, color, alpha, thresholdColor } from '../colors.js';
import { REDUCERS, reduce, timeSeries, chartTheme, initChart, timeAxisLabel, noData } from './common.js';

function legendEl(entries, mode, calcs, onToggle, placement) {
  if (mode === 'hidden') return null;
  if (mode === 'table') {
    const table = h('table', { class: 'legend-table' },
      h('thead', h('tr', h('th', { text: 'Seri' }), calcs.map((c) => h('th', { text: REDUCERS[c] || c })))));
    const body = h('tbody');
    for (const e of entries) {
      body.append(h('tr', { class: e.hidden ? 'off' : '', onclick: (ev) => onToggle(e.key, ev) },
        h('td', { title: e.name }, h('span', { class: 'swatch', style: { background: e.color, display: 'inline-block', width: '12px', height: '4px', marginRight: '6px', verticalAlign: 'middle' } }), e.name),
        calcs.map((c) => h('td', { text: formatValue(e.calcs[c], e.unit, e.decimals) }))));
    }
    table.append(body);
    return h('div', { tabindex: '0', role: 'group', 'aria-label': 'Seri göstergesi', style: { overflow: 'auto', maxHeight: placement === 'right' ? '100%' : '40%', flex: 'none' } }, table);
  }
  // Focusable so keyboard users can scroll a long legend (WCAG 2.1.1).
  const wrap = h('div', { class: 'legend', tabindex: '0', role: 'group', 'aria-label': 'Seri göstergesi', style: placement === 'right' ? { flexDirection: 'column', flexWrap: 'nowrap', maxHeight: '100%' } : { maxHeight: '30%' } });
  for (const e of entries) {
    const calcText = calcs.map((c) => `${REDUCERS[c] || c}: ${formatValue(e.calcs[c], e.unit, e.decimals)}`).join('  ');
    wrap.append(h('span', { class: ['legend-item', e.hidden ? 'off' : ''].join(' '), title: e.name, onclick: (ev) => onToggle(e.key, ev) },
      h('span', { class: 'swatch', style: { background: e.color } }), e.name, calcText ? h('span', { class: 'faint', text: ` ${calcText}` }) : null));
  }
  return wrap;
}

export function render(container, frames, panel, ctx) {
  const series = timeSeries(frames);
  if (!series.length || series.every((s) => !s.points.length)) { noData(container, frames.length ? 'Seçilen aralıkta veri yok' : 'Veri yok'); return { resize() {}, destroy() {} }; }
  const theme = chartTheme();
  const options = panel.options || {};
  const legendOpts = options.legend || {};
  const placement = legendOpts.placement === 'right' ? 'right' : 'bottom';
  const mode = legendOpts.showLegend === false ? 'hidden' : (legendOpts.displayMode || 'list');
  const calcs = legendOpts.calcs || [];
  const hidden = ctx.hiddenSeries || (ctx.hiddenSeries = new Set());
  const root = h('div', { class: 'viz-flex', style: { flexDirection: placement === 'right' ? 'row' : 'column', gap: '6px' } });
  const chartBox = h('div', { class: 'viz-chart', style: { minWidth: '0' } });
  root.append(chartBox);
  container.replaceChildren(root);
  const chart = initChart(chartBox);
  // Shared crosshair ("graphTooltip"): charts in one group mirror each other's pointer.
  if (ctx.group) { chart.group = ctx.group; window.echarts.connect(ctx.group); }
  const entries = [];
  const echSeries = [];
  const axes = { left: null, right: null };
  const stackMode = ((panel.fieldConfig || {}).defaults || {}).custom?.stacking?.mode || 'none';
  const percentTotals = new Map();
  if (stackMode === 'percent') {
    for (const s of series) for (const [t, v] of s.points) if (v !== null) percentTotals.set(t, (percentTotals.get(t) || 0) + Math.abs(v));
  }
  let thresholdCfg = null;
  series.forEach((frame, index) => {
    const name = displayName(frame);
    const cfg = fieldConfigFor(panel, frame, name);
    const custom = cfg.custom || {};
    if (custom.hideFrom && custom.hideFrom.viz) return;
    const unit = stackMode === 'percent' ? 'percentunit' : resolveUnit(cfg.unit, frame.unit);
    const key = `${index}:${name}`;
    const label = cfg.displayName || name;
    const negative = custom.transform === 'negative-Y';
    const values = frame.points.map((p) => p[1]);
    const lastValue = reduce(values, 'lastNotNull');
    let c = PALETTE[index % PALETTE.length];
    if (cfg.color && cfg.color.mode === 'fixed') c = color(cfg.color.fixedColor);
    else if (cfg.color && cfg.color.mode === 'thresholds') c = thresholdColor(lastValue, cfg.thresholds, cfg.min ?? 0, cfg.max ?? 100) || c;
    const placementAxis = custom.axisPlacement === 'right' ? 'right' : 'left';
    if (!axes[placementAxis]) axes[placementAxis] = { unit, decimals: cfg.decimals, min: cfg.min, max: cfg.max, softMin: custom.axisSoftMin,
      softMax: custom.axisSoftMax, label: custom.axisLabel, log: custom.scaleDistribution?.type === 'log', hidden: custom.axisPlacement === 'hidden' };
    if (!thresholdCfg && custom.thresholdsStyle && custom.thresholdsStyle.mode && custom.thresholdsStyle.mode !== 'off') thresholdCfg = { cfg, axis: placementAxis };
    const draw = custom.drawStyle || 'line';
    const data = frame.points.map(([t, v]) => {
      if (v === null || v === undefined) return [t, null];
      let value = v;
      if (stackMode === 'percent') value = percentTotals.get(t) ? Math.abs(v) / percentTotals.get(t) : null;
      return [t, negative && value !== null ? -value : value];
    });
    const fill = custom.fillOpacity ?? (draw === 'bars' ? 80 : 10);
    entries.push({ key, name: label, color: c, unit, decimals: cfg.decimals, hidden: hidden.has(key),
      calcs: Object.fromEntries(calcs.map((calc) => [calc, reduce(values, calc)])) });
    echSeries.push({
      name: key, type: draw === 'bars' ? 'bar' : 'line', yAxisIndex: 0, data,
      showSymbol: custom.showPoints === 'always' || draw === 'points' || (custom.showPoints !== 'never' && data.length < 30),
      symbolSize: custom.pointSize || 4, connectNulls: !!custom.spanNulls, smooth: custom.lineInterpolation === 'smooth' ? 0.35 : false,
      step: custom.lineInterpolation === 'stepAfter' ? 'end' : custom.lineInterpolation === 'stepBefore' ? 'start' : false,
      stack: stackMode !== 'none' ? (negative ? 'neg' : 'stack') : undefined, sampling: data.length > 2000 ? 'lttb' : undefined,
      lineStyle: { width: draw === 'points' ? 0 : (custom.lineWidth ?? 1), color: c, type: custom.lineStyle?.fill === 'dash' ? 'dashed' : 'solid' },
      itemStyle: { color: draw === 'bars' ? alpha(c, Math.max(0.15, fill / 100)) : c, borderColor: c },
      areaStyle: draw !== 'bars' && fill > 0 ? { color: custom.gradientMode === 'opacity' ? new window.echarts.graphic.LinearGradient(0, 0, 0, 1,
        [{ offset: 0, color: alpha(c, fill / 100) }, { offset: 1, color: alpha(c, 0) }]) : alpha(c, fill / 100) } : undefined,
      emphasis: { focus: 'none' }, barMaxWidth: 24, large: data.length > 3000,
      _meta: { label, unit, decimals: cfg.decimals, negative, axis: placementAxis },
    });
  });
  if (!axes.left && axes.right) { axes.left = axes.right; axes.right = null; }
  echSeries.forEach((s) => { s.yAxisIndex = axes.right && s._meta.axis === 'right' ? 1 : 0; });
  if (thresholdCfg && echSeries.length) {
    const steps = (thresholdCfg.cfg.thresholds && thresholdCfg.cfg.thresholds.steps) || [];
    const styleMode = thresholdCfg.cfg.custom.thresholdsStyle.mode;
    const target = echSeries[0];
    const lines = steps.filter((s) => s.value !== null && s.value !== undefined).map((s) => ({ yAxis: Number(s.value), lineStyle: { color: color(s.color), type: 'dashed', width: 1 }, label: { show: false } }));
    if (styleMode.includes('line')) target.markLine = { silent: true, symbol: 'none', data: lines };
    if (styleMode.includes('area')) {
      const areas = [];
      steps.forEach((s, i) => {
        const from = s.value === null || s.value === undefined ? -1e15 : Number(s.value);
        const next = steps[i + 1];
        const to = next ? Number(next.value) : 1e15;
        areas.push([{ yAxis: from, itemStyle: { color: alpha(color(s.color), 0.12) } }, { yAxis: to }]);
      });
      target.markArea = { silent: true, data: areas };
    }
  }
  const yAxis = [axes.left, axes.right].filter(Boolean).map((a, i) => ({
    type: a.log ? 'log' : 'value', position: i === 0 ? 'left' : 'right', show: !a.hidden, name: a.label || '', nameTextStyle: { color: theme.muted },
    min: a.min ?? (a.softMin !== undefined && a.softMin !== null ? (v) => Math.min(v.min, a.softMin) : undefined),
    max: a.max ?? (a.softMax !== undefined && a.softMax !== null ? (v) => Math.max(v.max, a.softMax) : undefined),
    splitLine: { show: i === 0, lineStyle: { color: theme.grid } }, axisLine: { show: false },
    axisLabel: { color: theme.muted, fontSize: 11, formatter: (v) => formatValue(Math.abs(v) === 0 ? 0 : (echSeries.some((s) => s._meta.negative) ? Math.abs(v) : v), a.unit, a.decimals) },
  }));
  const span = (ctx.timeRange?.to || 0) - (ctx.timeRange?.from || 0);
  const option = {
    animation: false, backgroundColor: 'transparent',
    grid: { left: 8, right: axes.right ? 8 : 16, top: 8, bottom: 4, containLabel: true },
    legend: { show: false, data: echSeries.map((s) => s.name), selected: Object.fromEntries(entries.map((e) => [e.key, !e.hidden])) },
    xAxis: { type: 'time', min: ctx.timeRange?.from, max: ctx.timeRange?.to, axisLine: { lineStyle: { color: theme.grid } },
      splitLine: { show: true, lineStyle: { color: theme.grid } }, axisLabel: { color: theme.muted, fontSize: 11, hideOverlap: true,
        formatter: (v) => timeAxisLabel(v, span, ctx.timezone) } },
    yAxis: yAxis.length ? yAxis : [{ type: 'value' }],
    tooltip: (options.tooltip || {}).mode === 'none' ? { show: false } : {
      trigger: (options.tooltip || {}).mode === 'single' ? 'item' : 'axis', confine: true, backgroundColor: theme.tooltipBg, borderColor: theme.border,
      textStyle: { color: theme.text, fontSize: 12 }, axisPointer: { type: 'line', lineStyle: { color: theme.muted } }, order: 'valueDesc',
      formatter: (params) => {
        const list = Array.isArray(params) ? params : [params];
        if (!list.length) return '';
        const time = new Date(list[0].value[0]);
        const head = new Intl.DateTimeFormat('tr-TR', { dateStyle: 'short', timeStyle: 'medium', timeZone: ctx.timezone && ctx.timezone !== 'browser' ? (ctx.timezone === 'utc' ? 'UTC' : ctx.timezone) : undefined }).format(time);
        const rows = list.filter((p) => p.value[1] !== null && p.value[1] !== undefined).sort((a, b) => Math.abs(b.value[1]) - Math.abs(a.value[1])).slice(0, 30).map((p) => {
          const meta = echSeries[p.seriesIndex]._meta;
          const raw = meta.negative ? -p.value[1] : p.value[1];
          const dot = `<span style="display:inline-block;width:10px;height:3px;margin-right:6px;vertical-align:middle;background:${escapeHtml(typeof p.color === 'string' ? p.color : '')}"></span>`;
          return `${dot}${escapeHtml(meta.label)}: <b>${escapeHtml(formatValue(raw, meta.unit, meta.decimals))}</b>`;
        });
        return `<div style="margin-bottom:4px;opacity:.8">${escapeHtml(head)}</div>${rows.join('<br/>')}`;
      } },
    toolbox: { show: false },
    brush: ctx.onZoom ? { toolbox: ['lineX'], xAxisIndex: 0, brushStyle: { color: 'rgba(110,159,255,.15)', borderColor: 'rgba(110,159,255,.6)' }, throttleType: 'debounce' } : undefined,
    series: echSeries.map(({ _meta, ...rest }) => rest),
  };
  chart.setOption(option, true);
  if (ctx.onZoom) {
    chart.dispatchAction({ type: 'takeGlobalCursor', key: 'brush', brushOption: { brushType: 'lineX', brushMode: 'single' } });
    chart.on('brushEnd', (e) => {
      const area = e.areas && e.areas[0];
      if (area && area.coordRange && area.coordRange[1] - area.coordRange[0] > 1000) ctx.onZoom(Math.round(area.coordRange[0]), Math.round(area.coordRange[1]));
      chart.dispatchAction({ type: 'brush', areas: [] });
    });
  }
  const toggle = (key, ev) => {
    if (ev && (ev.ctrlKey || ev.metaKey)) { if (hidden.has(key)) hidden.delete(key); else hidden.add(key); }
    else {
      const onlyThis = entries.every((e) => e.key === key || hidden.has(e.key)) && !hidden.has(key);
      hidden.clear();
      if (!onlyThis) for (const e of entries) if (e.key !== key) hidden.add(e.key);
    }
    chart.setOption({ legend: { selected: Object.fromEntries(entries.map((e) => [e.key, !hidden.has(e.key)])) } });
    entries.forEach((e) => { e.hidden = hidden.has(e.key); });
    const fresh = legendEl(entries, mode, calcs, toggle, placement);
    if (legend && fresh) legend.replaceWith(fresh);
    legend = fresh;
  };
  let legend = legendEl(entries, mode, calcs, toggle, placement);
  if (legend) root.append(legend);
  chart.resize();
  return {
    chart,
    resize() { chart.resize(); },
    destroy() { chart.dispose(); },
    png() { return chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: theme.bg }); },
  };
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
export { escapeHtml };
