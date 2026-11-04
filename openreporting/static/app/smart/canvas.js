// Smart dashboard page canvas: paper-shaped pages split into 24 columns × `rows` rows. Panels are
// positioned in percentages, so the page scales with the window and matches the PDF exactly.
import { h, clear, toast } from '../dom.js';
import { icon } from '../icons.js';

export const COLS = 24;
export const ROWS = { portrait: 32, landscape: 20 };
// PDF geometry in points (reportlab): margins and header/footer bands around the content area.
const PAPER = { A4: [595.28, 841.89], A3: [841.89, 1190.55], Letter: [612, 792] };
const MARGIN = 26, HEADER = 30, FOOTER = 16;

export function pageGeometry(smart) {
  const [w0, h0] = PAPER[smart.paper] || PAPER.A4;
  const [w, hgt] = smart.orientation === 'landscape' ? [h0, w0] : [w0, h0];
  return { ratio: w / hgt, pad: { top: (MARGIN + HEADER) / hgt, bottom: (MARGIN + FOOTER) / hgt, side: MARGIN / w } };
}

const overlaps = (a, b) => a.page === b.page && a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

export function fits(panels, pos, ignoreId, rows) {
  if (pos.x < 0 || pos.y < 0 || pos.x + pos.w > COLS || pos.y + pos.h > rows) return false;
  return !panels.some((p) => p.id !== ignoreId && overlaps(p.smartPos, pos));
}

// First free spot for a w×h block: preferred page first, then later pages, then a new page.
export function findSpot(panels, wanted, rows, pages, ignoreId) {
  if (fits(panels, wanted, ignoreId, rows)) return { ...wanted };
  for (let page = wanted.page; page < pages + 1; page += 1) {
    for (let y = 0; y + wanted.h <= rows; y += 1) {
      for (let x = 0; x + wanted.w <= COLS; x += 1) {
        const pos = { ...wanted, page, x, y };
        if (fits(panels, pos, ignoreId, rows)) return pos;
      }
    }
  }
  return { ...wanted, page: pages, x: 0, y: 0 };
}

// Close vertical gaps: every element moves up as far as it can on its page, keeping column and order.
export function compactPage(panels, page, rows) {
  const placed = [];
  const order = panels.filter((p) => p.smartPos.page === page).sort((a, b) => a.smartPos.y - b.smartPos.y || a.smartPos.x - b.smartPos.x);
  const moved = new Map();
  for (const panel of order) {
    let y = 0;
    const pos = { ...panel.smartPos };
    while (y < pos.y && !fits(placed, { ...pos, y }, null, rows)) y += 1;
    const next = { ...pos, y: Math.min(y, pos.y) };
    placed.push({ id: panel.id, smartPos: next });
    moved.set(panel.id, next);
  }
  return moved;
}

function cellAt(body, clientX, clientY, rows) {
  const r = body.getBoundingClientRect();
  return { x: Math.floor(((clientX - r.left) / r.width) * COLS), y: Math.floor(((clientY - r.top) / r.height) * rows) };
}

function placeBox(box, pos, rows) {
  Object.assign(box.style, { left: `${(pos.x / COLS) * 100}%`, top: `${(pos.y / rows) * 100}%`, width: `${(pos.w / COLS) * 100}%`, height: `${(pos.h / rows) * 100}%` });
}

/**
 * Canvas controller.
 * opts: { model, editable, header(page) -> Node, footer(page) -> Node[], pageTools(page) -> Node|null,
 *         renderItem(panel) -> {el, bar}, onAdd(type, pos), onMove(panel, pos), onSelect(panel|null) }
 */
export function createCanvas(opts) {
  const root = h('div', { class: 'smart-pages' });
  const bodies = [];
  let model = opts.model;

  const smart = () => model.smart;
  const rows = () => smart().rows;

  function pageAt(clientX, clientY) {
    return bodies.findIndex((b) => { const r = b.getBoundingClientRect(); return clientX >= r.left && clientX <= r.right && clientY >= r.top && clientY <= r.bottom; });
  }

  function dragItem(panel, box, mode, start) {
    const origin = { ...panel.smartPos };
    const startCell = cellAt(bodies[origin.page], start.clientX, start.clientY, rows());
    box.classList.add('dragging');
    let next = origin;
    const move = (e) => {
      if (mode === 'move') {
        const page = pageAt(e.clientX, e.clientY);
        const target = page >= 0 ? page : next.page;
        const cell = cellAt(bodies[target], e.clientX, e.clientY, rows());
        const dx = target === origin.page ? cell.x - startCell.x : cell.x - Math.floor(origin.w / 2);
        const dy = target === origin.page ? cell.y - startCell.y : cell.y;
        next = { ...origin, page: target, x: Math.max(0, Math.min(COLS - origin.w, (target === origin.page ? origin.x : 0) + dx)), y: Math.max(0, Math.min(rows() - origin.h, (target === origin.page ? origin.y : 0) + dy)) };
        if (next.page !== origin.page && box.parentElement !== bodies[next.page]) bodies[next.page].append(box);
      } else {
        const cell = cellAt(bodies[origin.page], e.clientX, e.clientY, rows());
        next = { ...origin, w: Math.max(2, Math.min(COLS - origin.x, cell.x - origin.x + 1)), h: Math.max(2, Math.min(rows() - origin.y, cell.y - origin.y + 1)) };
      }
      box.classList.toggle('blocked', !fits(model.panels, next, panel.id, rows()));
      placeBox(box, next, rows());
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      box.classList.remove('dragging', 'blocked');
      const moved = JSON.stringify(next) !== JSON.stringify(origin);
      if (moved && fits(model.panels, next, panel.id, rows())) opts.onMove(panel, next);
      else { if (moved) toast('Bu alan dolu; öğe eski yerine döndü', 'warn'); render(); }
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  }

  function itemBox(panel) {
    const { el, bar } = opts.renderItem(panel);
    const box = h('div', { class: ['smart-item', opts.selectedId?.() === panel.id ? 'selected' : ''].join(' '), dataset: { id: panel.id },
      onPointerdown: (e) => { e.stopPropagation(); opts.onSelect(panel); } });
    if (opts.editable === false) {
      box.append(h('div', { class: 'smart-bar' }, bar), h('div', { class: 'smart-view' }, el));
    } else {
      const grip = h('button', { type: 'button', class: 'smart-grip', title: 'Taşı (sürükleyin) · ok tuşlarıyla kaydırın', 'aria-label': 'Öğeyi taşı' }, icon('drag'));
      grip.addEventListener('pointerdown', (e) => { e.preventDefault(); dragItem(panel, box, 'move', e); });
      const resize = h('div', { class: 'smart-resize', title: 'Boyutlandır' });
      resize.addEventListener('pointerdown', (e) => { e.preventDefault(); e.stopPropagation(); dragItem(panel, box, 'resize', e); });
      box.append(h('div', { class: 'smart-bar' }, grip, bar), h('div', { class: 'smart-view' }, el), resize);
    }
    placeBox(box, panel.smartPos, rows());
    return box;
  }

  function render() {
    clear(root);
    bodies.length = 0;
    const geo = pageGeometry(smart());
    for (let page = 0; page < smart().pages; page += 1) {
      const body = h('div', { class: 'paper-body', style: { backgroundSize: `${100 / COLS}% ${100 / rows()}%` } });
      body.addEventListener('dragover', (e) => { if (e.dataTransfer.types.includes('application/x-smart-viz')) { e.preventDefault(); body.classList.add('drop'); } });
      body.addEventListener('dragleave', () => body.classList.remove('drop'));
      body.addEventListener('drop', (e) => {
        e.preventDefault(); body.classList.remove('drop');
        const type = e.dataTransfer.getData('application/x-smart-viz');
        if (type) { const cell = cellAt(body, e.clientX, e.clientY, rows()); opts.onAdd(type, { page, x: cell.x, y: cell.y }); }
      });
      bodies.push(body);
      const paper = h('section', { class: 'paper', 'data-theme': 'porcelain', 'data-scheme': 'light', 'aria-label': `Sayfa ${page + 1}`,
        style: { aspectRatio: String(geo.ratio), paddingTop: `${geo.pad.top * 100 / geo.ratio}%`, paddingBottom: `${geo.pad.bottom * 100 / geo.ratio}%`, paddingLeft: `${geo.pad.side * 100}%`, paddingRight: `${geo.pad.side * 100}%` } },
      opts.header(page), body, h('footer', { class: 'paper-foot' }, ...(opts.footer ? opts.footer(page) : [h('span', { text: `Sayfa ${page + 1}` })])));
      paper.addEventListener('pointerdown', () => opts.onSelect(null));
      root.append(h('div', { class: 'page-wrap' }, opts.pageTools ? opts.pageTools(page) : null, paper));
    }
    for (const panel of model.panels) bodies[panel.smartPos.page]?.append(itemBox(panel));
  }

  return {
    el: root,
    render,
    fits: (pos, ignoreId) => fits(model.panels, pos, ignoreId, rows()),
    setModel(next) { model = next; render(); },
  };
}
