// DOM helpers: no innerHTML for data (XSS-safe by construction); CSP-friendly (no inline styles/handlers).
import { icon } from './icons.js';

export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs && (typeof attrs !== 'object' || attrs instanceof Node || Array.isArray(attrs))) {
    children.unshift(attrs);
    attrs = null;
  }
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') el.className = Array.isArray(value) ? value.filter(Boolean).join(' ') : value;
    else if (key === 'text') el.textContent = value;
    else if (key === 'style') Object.assign(el.style, value);
    else if (key === 'dataset') Object.assign(el.dataset, value);
    else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === 'value') el.value = value;
    else if (key === 'checked') el.checked = !!value;
    else if (key === 'html') throw new Error('html attribute is not allowed');
    else if (value === true) el.setAttribute(key, '');
    else el.setAttribute(key, String(value));
  }
  append(el, children);
  return el;
}

export function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

export function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
export function mount(el, ...children) { clear(el); return append(el, children); }
export const $ = (sel, root = document) => root.querySelector(sel);

export function button(label, opts = {}) {
  const cls = ['btn', opts.variant, opts.size, !label && opts.icon ? 'icon' : null, opts.class].filter(Boolean).join(' ');
  // An async handler makes the button busy until it settles: double clicks never send a second request.
  const onclick = opts.onClick && ((e) => {
    if (b.dataset.busy) return undefined;
    const result = opts.onClick(e);
    if (result && typeof result.then === 'function') {
      b.dataset.busy = '1';
      b.setAttribute('aria-busy', 'true');
      Promise.resolve(result).catch(() => {}).finally(() => { delete b.dataset.busy; b.removeAttribute('aria-busy'); });
    }
    return result;
  });
  const b = h('button', { type: opts.type || 'button', class: cls, title: opts.title, disabled: opts.disabled, onclick,
    'aria-label': opts.title || label || undefined });
  if (opts.icon) b.append(icon(opts.icon));
  if (label) b.append(h('span', { text: label }));
  return b;
}

export function input(opts = {}) {
  return h('input', { class: ['input', opts.class].filter(Boolean).join(' '), type: opts.type || 'text', value: opts.value ?? '',
    placeholder: opts.placeholder, min: opts.min, max: opts.max, step: opts.step, list: opts.list, maxlength: opts.maxlength,
    autocomplete: opts.autocomplete || 'off', spellcheck: opts.spellcheck ?? false, required: opts.required, readonly: opts.readonly,
    oninput: opts.onInput, onchange: opts.onChange, onkeydown: opts.onKeydown, onblur: opts.onBlur, title: opts.title,
    'aria-label': opts.label });
}

export function textarea(opts = {}) {
  return h('textarea', { class: ['input', opts.class].filter(Boolean).join(' '), rows: opts.rows || 6, placeholder: opts.placeholder,
    spellcheck: opts.spellcheck ?? false, value: opts.value ?? '', oninput: opts.onInput, onchange: opts.onChange, readonly: opts.readonly,
    'aria-label': opts.label });
}

export function select(options, value, onChange, opts = {}) {
  const el = h('select', { class: ['input', opts.class].filter(Boolean).join(' '), onchange: (e) => onChange && onChange(e.target.value, e),
    'aria-label': opts.label, disabled: opts.disabled });
  for (const opt of options) {
    if (opt.group) {
      const g = h('optgroup', { label: opt.group });
      for (const o of opt.options) g.append(h('option', { value: o.value, text: o.label ?? o.value }));
      el.append(g);
    } else {
      const o = typeof opt === 'object' ? opt : { value: opt, label: opt };
      el.append(h('option', { value: o.value, text: o.label ?? o.value }));
    }
  }
  el.value = value ?? '';
  return el;
}

let fieldSeq = 0;
const LABELABLE = new Set(['INPUT', 'SELECT', 'TEXTAREA']);

// Labels and hints are tied to their control so screen readers announce them.
export function field(label, control, hint) {
  const id = `f${++fieldSeq}`;
  const labelEl = label ? h('label', { text: label, id: `${id}-l` }) : null;
  const hintEl = hint ? h('div', { class: 'hint', text: hint, id: `${id}-h` }) : null;
  if (control instanceof Element) {
    if (labelEl && LABELABLE.has(control.tagName)) {
      if (!control.id) control.id = id;
      labelEl.htmlFor = control.id;
    } else if (labelEl) {
      if (!control.getAttribute('role')) control.setAttribute('role', 'group');
      control.setAttribute('aria-labelledby', labelEl.id);
    }
    if (hintEl) control.setAttribute('aria-describedby', hintEl.id);
  }
  return h('div', { class: 'field' }, labelEl, control, hintEl);
}

export function toggle(label, checked, onChange) {
  const box = h('input', { type: 'checkbox', checked, onchange: (e) => onChange && onChange(e.target.checked) });
  return h('label', { class: 'switch' }, box, h('span', { class: 'track' }), label ? h('span', { text: label }) : null);
}

export function segmented(options, value, onChange) {
  const wrap = h('div', { class: 'segmented', role: 'radiogroup' });
  const render = (current) => {
    clear(wrap);
    for (const o of options) {
      wrap.append(h('button', { type: 'button', class: o.value === current ? 'on' : '', role: 'radio', 'aria-checked': String(o.value === current),
        title: o.title, onclick: () => { render(o.value); onChange(o.value); } }, o.icon ? icon(o.icon) : null, o.label || ''));
    }
  };
  render(value);
  return wrap;
}

export function tabs(items, active, onChange) {
  const bar = h('div', { class: 'tabs', role: 'tablist' });
  const render = (current) => {
    clear(bar);
    for (const item of items) {
      bar.append(h('button', { type: 'button', role: 'tab', class: item.id === current ? 'on' : '', 'aria-selected': String(item.id === current),
        onclick: () => { render(item.id); onChange(item.id); } }, item.label, item.count != null ? h('span', { class: 'faint', text: ` ${item.count}` }) : null));
    }
  };
  render(active);
  return bar;
}

const overlayRoot = () => document.getElementById('overlay-root');

const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
const modalStack = [];
const modalClosers = new Map();

// Page changes and session expiry close open dialogs properly (listeners removed, promises settled).
export function closeAllModals() {
  for (const box of [...modalStack].reverse()) { const close = modalClosers.get(box); if (close) close(); }
}

// Dialogs trap Tab inside, only the top-most one reacts to keys, and focus returns to the opener on close.
export function modal({ title, body, footer, size = '', onClose, closeOnBackdrop = true }) {
  const opener = document.activeElement;
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    backdrop.remove();
    modalStack.splice(modalStack.indexOf(box), 1);
    modalClosers.delete(box);
    document.removeEventListener('keydown', onKey, true);
    if (onClose) onClose();
    if (opener && opener.isConnected && typeof opener.focus === 'function') opener.focus();
  };
  const onKey = (e) => {
    if (!box.isConnected) { close(); return; } // removed from the DOM without close(): drop it
    if (modalStack[modalStack.length - 1] !== box) return;
    if (e.key === 'Escape') {
      if (openPopup) return; // the open dropdown/menu closes first
      e.stopPropagation(); close(); return;
    }
    if (e.key !== 'Tab') return;
    const items = [...box.querySelectorAll(FOCUSABLE)].filter((el) => el.offsetParent !== null);
    if (!items.length) { e.preventDefault(); box.focus(); return; }
    const first = items[0]; const last = items[items.length - 1];
    if (e.shiftKey && (document.activeElement === first || !box.contains(document.activeElement))) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && (document.activeElement === last || !box.contains(document.activeElement))) { e.preventDefault(); first.focus(); }
  };
  const box = h('div', { class: ['modal', size].join(' '), role: 'dialog', 'aria-modal': 'true', 'aria-label': title, tabindex: '-1' },
    h('div', { class: 'modal-head' }, h('h2', { text: title }), button('', { icon: 'close', variant: 'ghost', title: 'Kapat', onClick: () => close() })),
    h('div', { class: 'modal-body' }, body),
    footer ? h('div', { class: 'modal-foot' }, footer) : null);
  const backdrop = h('div', { class: 'modal-backdrop', onmousedown: (e) => { if (e.target === backdrop && closeOnBackdrop) close(); } }, box);
  overlayRoot().append(backdrop);
  modalStack.push(box);
  modalClosers.set(box, close);
  document.addEventListener('keydown', onKey, true);
  setTimeout(() => { if (!closed) (box.querySelector('input,select,textarea,button.primary') || box).focus?.(); }, 30);
  return { el: box, close };
}

export function confirmDialog(title, message, { okText = 'Onayla', danger = false } = {}) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (v) => { if (!done) { done = true; resolve(v); } };
    const dlg = modal({ title, body: h('p', { text: message }), onClose: () => finish(false), footer: [
      button('Vazgeç', { onClick: () => { finish(false); dlg.close(); } }),
      button(okText, { variant: danger ? 'danger' : 'primary', onClick: () => { finish(true); dlg.close(); } })] });
  });
}

export function promptDialog(title, label, value = '', { okText = 'Kaydet', hint } = {}) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (v) => { if (!done) { done = true; resolve(v); } };
    const inp = input({ value, onKeydown: (e) => { if (e.key === 'Enter') { finish(inp.value); dlg.close(); } } });
    const dlg = modal({ title, body: field(label, inp, hint), onClose: () => finish(null), footer: [
      button('Vazgeç', { onClick: () => { finish(null); dlg.close(); } }),
      button(okText, { variant: 'primary', onClick: () => { finish(inp.value); dlg.close(); } })] });
  });
}

let openPopup = null;
export function closePopups() { if (openPopup) { openPopup(); openPopup = null; } }

export function popover(anchor, content, { className = '', align = 'left', width } = {}) {
  closePopups();
  const el = h('div', { class: ['menu', className].join(' ') }, content);
  if (width) el.style.width = `${width}px`;
  overlayRoot().append(el);
  const r = anchor.getBoundingClientRect();
  const w = el.offsetWidth;
  const hgt = el.offsetHeight;
  let left = align === 'right' ? r.right - w : r.left;
  left = Math.max(8, Math.min(left, window.innerWidth - w - 8));
  let top = r.bottom + 4;
  if (top + hgt > window.innerHeight - 8 && r.top - hgt - 4 > 8) top = r.top - hgt - 4;
  el.style.left = `${left}px`;
  el.style.top = `${Math.max(8, top)}px`;
  const onDown = (e) => { if (!el.contains(e.target) && !anchor.contains(e.target)) closePopups(); };
  const onKey = (e) => {
    if (e.key !== 'Escape') return;
    e.stopPropagation();
    closePopups();
    if (anchor.isConnected) anchor.focus();
  };
  setTimeout(() => { document.addEventListener('mousedown', onDown, true); document.addEventListener('keydown', onKey, true); }, 0);
  openPopup = () => { el.remove(); document.removeEventListener('mousedown', onDown, true); document.removeEventListener('keydown', onKey, true); };
  return { el, close: closePopups };
}

// Arrow keys / Home / End move between items, as in a native menu.
function menuKeys(el) {
  el.addEventListener('keydown', (e) => {
    const items = [...el.querySelectorAll('[role="menuitem"]')];
    if (!items.length) return;
    const index = items.indexOf(document.activeElement);
    let next = null;
    if (e.key === 'ArrowDown') next = items[(index + 1) % items.length];
    else if (e.key === 'ArrowUp') next = items[(index - 1 + items.length) % items.length];
    else if (e.key === 'Home') next = items[0];
    else if (e.key === 'End') next = items[items.length - 1];
    if (next) { e.preventDefault(); next.focus(); }
  });
}

export function menu(anchor, items, opts = {}) {
  const nodes = items.filter(Boolean).map((item) => {
    if (item.sep) return h('div', { class: 'sep', role: 'separator' });
    if (item.title) return h('div', { class: 'menu-title', text: item.title });
    const tag = item.href ? 'a' : 'button';
    return h(tag, { href: item.href, type: item.href ? undefined : 'button', role: 'menuitem', onclick: (e) => { closePopups(); item.onClick && item.onClick(e); } },
      item.icon ? icon(item.icon) : h('span', { style: { width: '16px' } }), h('span', { text: item.label }),
      item.shortcut ? h('span', { class: 'shortcut', text: item.shortcut }) : null);
  });
  const pop = popover(anchor, nodes, opts);
  pop.el.setAttribute('role', 'menu');
  menuKeys(pop.el);
  const first = pop.el.querySelector('[role="menuitem"]');
  if (first) setTimeout(() => { if (pop.el.isConnected) first.focus({ preventScroll: true }); }, 0);
  return pop;
}

export function toast(message, kind = 'info', timeout = 4500) {
  const el = h('div', { class: `toast ${kind}`, role: kind === 'error' ? 'alert' : 'status', text: message });
  document.getElementById('toast-root').append(el);
  setTimeout(() => el.remove(), kind === 'error' ? timeout * 2 : timeout);
}

export function debounce(fn, wait = 250) {
  let timer;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), wait); };
}

export function downloadBlob(filename, data, mime = 'application/octet-stream') {
  const blob = data instanceof Blob ? data : new Blob([data], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = h('a', { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export function fmtDateTime(ms, tz) {
  if (ms == null || ms === '') return '—';
  const date = typeof ms === 'string' ? new Date(ms) : new Date(Number(ms));
  if (Number.isNaN(date.getTime())) return String(ms);
  const opts = { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false };
  if (tz && tz !== 'browser') opts.timeZone = tz === 'utc' ? 'UTC' : tz;
  try { return new Intl.DateTimeFormat('tr-TR', opts).format(date); } catch { return date.toISOString(); }
}

export function timeAgo(iso) {
  if (!iso) return '—';
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (Number.isNaN(diff)) return iso;
  if (diff < 60) return 'az önce';
  if (diff < 3600) return `${Math.floor(diff / 60)} dk önce`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} sa önce`;
  return `${Math.floor(diff / 86400)} gün önce`;
}

export function tagColor(name) {
  const palette = ['#3274d9', '#629e51', '#e5ac0e', '#bf1b00', '#8f3bb8', '#1f78c1', '#ba43a9', '#447ebc', '#c15c17', '#0a50a1', '#806eb7', '#d683ce'];
  let hash = 0;
  for (const ch of String(name)) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return palette[hash % palette.length];
}

export function tagEl(name) { return h('span', { class: 'tag', style: { background: tagColor(name) }, text: name }); }

export function loading(text = 'Yükleniyor…') { return h('div', { class: 'muted', style: { padding: '24px' } }, h('span', { class: 'spinner' }), ` ${text}`); }

export function emptyState(title, text, actions = []) {
  return h('div', { class: 'empty-state' }, h('h3', { text: title }), h('p', { text }), actions.length ? h('div', { class: 'toolbar' }, actions) : null);
}

export function section(title, body, { open = true, onToggle } = {}) {
  const sec = h('div', { class: ['opt-section', open ? '' : 'closed'].join(' ') });
  const head = h('div', { class: 'sec-head', role: 'button', tabindex: '0', 'aria-expanded': String(open), onclick: () => {
    sec.classList.toggle('closed');
    const expanded = !sec.classList.contains('closed');
    head.setAttribute('aria-expanded', String(expanded));
    onToggle && onToggle(expanded);
  }, onkeydown: (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); head.click(); } } }, icon('chevron-down'), title);
  sec.append(head, h('div', { class: 'sec-body' }, body));
  return sec;
}

export function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text).then(() => toast('Panoya kopyalandı', 'ok'));
  const ta = h('textarea', { value: text });
  document.body.append(ta); ta.select();
  try { document.execCommand('copy'); toast('Panoya kopyalandı', 'ok'); } finally { ta.remove(); }
  return Promise.resolve();
}
