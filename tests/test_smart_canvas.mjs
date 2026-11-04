import test from 'node:test';
import assert from 'node:assert/strict';
import { arrange, compactPage, findSpot, fits, layoutFromGrid, COLS } from '../openreporting/static/app/smart/canvas.js';

const panel = (id, x, y, w, h, page = 0) => ({ id, smartPos: { page, x, y, w, h } });

test('findSpot never overlaps and opens a new page when full', () => {
  const panels = [panel(1, 0, 0, 24, 30)];
  // Only two rows are free on page 1, a four-row element goes to the next page.
  assert.deepEqual(findSpot(panels, { page: 0, x: 0, y: 0, w: 12, h: 4 }, 32, 1), { page: 1, x: 0, y: 0, w: 12, h: 4 });
  assert.deepEqual(findSpot(panels, { page: 0, x: 0, y: 0, w: 12, h: 2 }, 32, 1), { page: 0, x: 0, y: 30, w: 12, h: 2 });
  assert.equal(fits(panels, { page: 0, x: 0, y: 29, w: 4, h: 2 }, null, 32), false);
  const full = findSpot([panel(1, 0, 0, 24, 32)], { page: 0, x: 0, y: 0, w: 12, h: 8 }, 32, 1);
  assert.equal(full.page, 1);
});

test('compactPage closes vertical gaps and keeps column order', () => {
  const moved = compactPage([panel(1, 0, 4, 12, 4), panel(2, 12, 10, 12, 4), panel(3, 0, 20, 12, 4)], 0, 32);
  assert.equal(moved.get(1).y, 0);
  assert.equal(moved.get(2).y, 0);
  assert.equal(moved.get(3).y, 4);
});

test('layoutFromGrid maps a dashboard grid onto pages without overlaps', () => {
  const grid = [
    { id: 1, type: 'row', title: 'Özet', gridPos: { x: 0, y: 0, w: 24, h: 1 } },
    { id: 2, type: 'stat', gridPos: { x: 0, y: 1, w: 6, h: 4 } },
    { id: 3, type: 'timeseries', gridPos: { x: 6, y: 1, w: 18, h: 40 } },
    { id: 4, type: 'table', gridPos: { x: 0, y: 25, w: 24, h: 8 } },
  ];
  const { panels, pages } = layoutFromGrid(grid, 20);
  assert.equal(panels.find((p) => p.id === 1).type, 'divider');
  assert.ok(panels.find((p) => p.id === 3).smartPos.h <= 20);
  assert.ok(pages >= 2);
  const overlap = (a, b) => a.page === b.page && a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
  for (let i = 0; i < panels.length; i += 1) for (let j = i + 1; j < panels.length; j += 1) assert.ok(!overlap(panels[i].smartPos, panels[j].smartPos), `${panels[i].id}/${panels[j].id}`);
});

test('arrange aligns to the first element and distributes across the page', () => {
  const sel = [panel(1, 4, 6, 8, 5), panel(2, 14, 12, 6, 3), panel(3, 0, 20, 10, 4)];
  assert.equal(arrange(sel, 'left', 32).get(2).x, 4);
  assert.equal(arrange(sel, 'top', 32).get(3).y, 6);
  assert.equal(arrange(sel, 'width', 32).get(2).w, 8);
  assert.equal(arrange(sel, 'height', 32).get(3).h, 5);
  const spread = arrange(sel, 'distribute', 32);
  assert.deepEqual([...spread.values()].map((p) => [p.x, p.w]), [[0, 8], [8, 8], [16, 8]]);
  assert.ok([...spread.values()].every((p) => p.x + p.w <= COLS));
  assert.equal(arrange([sel[0]], 'left', 32).size, 0);
});
