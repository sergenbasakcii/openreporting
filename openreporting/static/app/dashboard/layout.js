// 24-column grid (Grafana: 30px rows, 8px gaps) with drag, resize, collision push-down and compaction.
import { interpolate, ALL } from '../variables.js';

export const COLS = 24;
export const ROW_H = 30;
export const GAP = 8;

const overlap = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

// Float items up. `fixed` keeps its position (the item being dragged); `prefer` wins ties on the same row.
export function compact(items, { fixed = null, prefer = null } = {}) {
  const first = (a, b) => (a === prefer ? -1 : b === prefer ? 1 : 0);
  const sorted = items.filter((it) => it !== fixed).sort((a, b) => a.pos.y - b.pos.y || first(a, b) || a.pos.x - b.pos.x);
  const placed = fixed ? [fixed.pos] : [];
  for (const it of sorted) {
    if (it.static) { placed.push(it.pos); continue; }
    let y = 0;
    for (;;) {
      const probe = { ...it.pos, y };
      const hit = placed.find((p) => overlap(p, probe));
      if (!hit) break;
      y = hit.y + hit.h;
    }
    it.pos = { ...it.pos, y };
    placed.push(it.pos);
  }
  return items;
}

// Move/resize an item then push colliding items down and compact.
export function place(items, moving, nextPos) {
  moving.pos = { ...nextPos, x: Math.max(0, Math.min(COLS - nextPos.w, nextPos.x)), y: Math.max(0, nextPos.y) };
  const others = items.filter((i) => i !== moving).sort((a, b) => a.pos.y - b.pos.y);
  const placed = [moving.pos];
  for (const it of others) {
    let pos = { ...it.pos };
    while (placed.some((p) => overlap(p, pos))) pos = { ...pos, y: pos.y + 1 };
    it.pos = pos;
    placed.push(pos);
  }
  // Others float up around the moving item, which stays exactly where the pointer is.
  compact(items, { fixed: moving });
  return items;
}

export function pixelRect(pos, width) {
  const colW = (width - GAP * (COLS - 1)) / COLS;
  return { left: pos.x * (colW + GAP), top: pos.y * (ROW_H + GAP), width: pos.w * colW + (pos.w - 1) * GAP, height: pos.h * ROW_H + (pos.h - 1) * GAP };
}

export function gridHeight(items) {
  const bottom = items.reduce((m, i) => Math.max(m, i.pos.y + i.pos.h), 0);
  return bottom * (ROW_H + GAP);
}

export function toGrid(px, py, width) {
  const colW = (width - GAP * (COLS - 1)) / COLS;
  return { x: Math.round(px / (colW + GAP)), y: Math.round(py / (ROW_H + GAP)) };
}

function expandedValues(v) {
  if (!v) return [];
  const list = Array.isArray(v.value) ? v.value : [v.value];
  if (list.includes(ALL)) return (v.options || []).map((o) => o.value).filter((x) => x !== ALL);
  return list.filter((x) => x !== undefined && x !== null && x !== '');
}

function scopedVar(variables, name, value) {
  const v = variables[name] || {};
  const text = ((v.options || []).find((o) => o.value === value) || {}).text || value;
  return { ...v, value, text, multi: false, includeAll: false };
}

// Expand repeated rows/panels for display (mirror of dashboard_runtime.expand); rows keep collapse state.
export function expandLayout(dashboard, variables) {
  const top = [...(dashboard.panels || [])].sort((a, b) => a.gridPos.y - b.gridPos.y || a.gridPos.x - b.gridPos.x);
  const sections = [];
  let current = { row: null, panels: [] };
  for (const p of top) {
    if (p.type === 'row') { sections.push(current); current = { row: p, panels: p.collapsed ? [] : [] }; }
    else current.panels.push(p);
  }
  sections.push(current);
  const out = [];
  let y = 0;
  for (const { row, panels } of sections) {
    if (!row && !panels.length) continue;
    const repeat = row && row.repeat;
    const values = repeat && variables[repeat] ? expandedValues(variables[repeat]) : [null];
    values.forEach((value, rIndex) => {
      const scoped = value !== null ? { [repeat]: scopedVar(variables, repeat, value) } : {};
      if (row) {
        out.push({ panel: row, source: row, pos: { x: 0, y, w: COLS, h: 1 }, scopedVars: scoped, repeatIndex: rIndex,
          title: interpolate(row.title || '', variables, scoped), isRepeatClone: rIndex > 0 });
        y += 1;
      }
      if (row && row.collapsed) return;
      const baseY = Math.min(...panels.map((p) => p.gridPos.y), Infinity);
      let height = 0;
      for (const p of panels) {
        const rv = p.repeat && (scoped[p.repeat] || variables[p.repeat]);
        const pvs = rv ? expandedValues(rv) : [null];
        const perRow = Number(p.maxPerRow) || Math.max(1, Math.floor(COLS / Math.max(1, p.gridPos.w)));
        const count = pvs.length;
        const width = p.repeatDirection === 'v' || count === 1 ? p.gridPos.w : Math.max(1, Math.floor(COLS / Math.min(count, perRow)));
        pvs.forEach((pv, index) => {
          const local = pv !== null ? { ...scoped, [p.repeat]: scopedVar(variables, p.repeat, pv) } : scoped;
          let pos;
          if (p.repeatDirection === 'v') pos = { ...p.gridPos, y: y + (p.gridPos.y - baseY) + index * p.gridPos.h };
          else {
            const line = Math.floor(index / Math.min(count, perRow)); const col = index % Math.min(count, perRow);
            pos = { x: count === 1 ? p.gridPos.x : col * width, y: y + (p.gridPos.y - baseY) + line * p.gridPos.h, w: width, h: p.gridPos.h };
          }
          height = Math.max(height, pos.y - y + pos.h);
          out.push({ panel: p, source: p, pos, scopedVars: local, repeatIndex: index + rIndex * 1000, repeatCount: count, isRepeatClone: index > 0 || rIndex > 0,
            title: interpolate(p.title || '', variables, local) });
        });
      }
      y += height;
    });
  }
  return compact(out);
}

// Write positions of non-clone items back to the dashboard model after a drag (rows reflow in order).
// A horizontally repeated panel's x/w are derived from the repeat count, so only y/h are persisted for it.
export function syncPositions(items) {
  for (const it of items) {
    if (it.isRepeatClone) continue;
    const derivedWidth = it.source.repeat && it.source.repeatDirection !== 'v' && (it.repeatCount || 1) > 1;
    it.source.gridPos = derivedWidth ? { ...it.source.gridPos, y: it.pos.y, h: it.pos.h } : { ...it.pos };
  }
}
