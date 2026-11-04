import test from 'node:test';
import assert from 'node:assert/strict';
import { EXTRA_NAMES, extendedOption } from '../openreporting/static/app/panels/extended.js';
import { ORDER, newPanel } from '../openreporting/static/app/panels/registry.js';

const series = [{ type: 'timeseries', name: 'Test', labels: {}, points: [[1000, 1], [2000, null], [3000, 3]], unit: '' }];
const panel = (type) => ({ type, options: {}, fieldConfig: { defaults: {} } });
test('20 extended plugins and 3 layout elements remain in the picker, 33 total', () => {
  assert.equal(Object.keys(EXTRA_NAMES).length, 20);
  assert.equal(ORDER.length, 33);
  assert.equal(new Set(ORDER).size, 33);
  for (const type of [...Object.keys(EXTRA_NAMES), 'image', 'divider', 'reportinfo']) assert.equal(newPanel(type, 1, {}).type, type);
});
test('histogram includes real samples, excludes missing values', () => {
  const option = extendedOption(series, panel('histogram'));
  assert.equal(option.series[0].data.reduce((a, b) => a + b, 0), 2);
});
test('step chart preserves missing points and timestamps', () => {
  assert.deepEqual(extendedOption(series, panel('stepchart')).series[0].data, series[0].points);
});
test('scatter requires actual numeric pairs, never invents coordinates', () => {
  assert.ok(extendedOption(series, panel('scatter')).message);
});
test('Sankey cycles have a clear explanation', () => {
  const frame = {type:'table',columns:[{name:'source',type:'string'},{name:'target',type:'string'},{name:'value',type:'number'}],rows:[['a','b',1],['b','a',1]]};
  assert.ok(extendedOption([frame], panel('sankey')).message);
});
test('waterfall keeps the actual signed cumulative endpoints', () => {
  const values = [10, -20, 4].map((v,i)=>({...series[0],name:String(i),points:[[1000,v]]}));
  assert.deepEqual(extendedOption(values,panel('waterfall')).series[0].data, [[0,0,10],[1,10,-10],[2,-10,-6]]);
});
test('negative pie values are explained rather than silently omitted', () => {
  const negative = [{...series[0], points:[[1000,-2]]}];
  assert.ok(extendedOption(negative,panel('donut')).message);
});
test('unrelated missing columns do not discard valid XY pairs', () => {
  const frame={type:'table',columns:[{name:'x',type:'number'},{name:'y',type:'number'},{name:'other',type:'number'}],rows:[[1,2,null]]};
  assert.equal(extendedOption([frame],panel('scatter')).series[0].data.length,1);
});

test('review fixes: integer bins, zone-aware calendar days, heatmap fallback', () => {
  const series = [{ type: 'timeseries', name: 'cpu', points: [[1_000, 1], [2_000, 2], [3_000, 9]] }];
  assert.equal(extendedOption(series, { ...panel('histogram'), options: { bins: 10.5 } }).series[0].data.length, 10);
  // 2026-10-27T22:30Z is already 28 October in Istanbul (UTC+3)
  const late = [{ type: 'timeseries', name: 'x', points: [[Date.UTC(2026, 9, 27, 22, 30), 5]] }];
  assert.equal(extendedOption(late, panel('calendarheatmap'), 'Europe/Istanbul').series[0].data[0][0], '2026-10-28');
  assert.equal(extendedOption(late, panel('calendarheatmap'), 'utc').series[0].data[0][0], '2026-10-27');
  const table = { type: 'table', columns: [{ name: 'a', type: 'number' }], rows: [[1]] };
  assert.equal(extendedOption([table], panel('heatmap')).fallback, 'timeseries');
});
