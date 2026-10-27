// History-API router with leave guards and breadcrumb updates.
import { h, clear, closePopups, closeAllModals } from './dom.js';

const routes = [];
let current = { cleanup: null, path: null };
let leaveGuard = null;
let crumbHost = null;
let renderTarget = null;
let appContext = null;

export function route(pattern, handler) {
  const keys = [];
  const regex = new RegExp(`^${pattern.replace(/\//g, '\\/').replace(/:(\w+)/g, (_, k) => { keys.push(k); return '([^/]+)'; })}\\/?$`);
  routes.push({ regex, keys, handler });
}

// `owner` is the page's root element: a page whose async setup finishes after the user navigated
// away is detached, and must not change the current page's guard, title or breadcrumbs.
const stale = (owner) => owner instanceof Node && !owner.isConnected;
export function setLeaveGuard(fn, owner) { if (!stale(owner)) leaveGuard = fn; }
export function clearLeaveGuard(fn) { if (leaveGuard === fn) leaveGuard = null; }
export function setCrumbHost(el) { crumbHost = el; }

export function setBreadcrumbs(items, owner) {
  if (!crumbHost || stale(owner)) return;
  clear(crumbHost);
  items.forEach((item, i) => {
    if (i) crumbHost.append(h('span', { class: 'faint', text: '›' }));
    if (item.href && i < items.length - 1) crumbHost.append(h('a', { href: item.href, 'data-link': '', text: item.label }));
    else crumbHost.append(i === items.length - 1 ? h('b', { text: item.label, title: item.label }) : h('span', { text: item.label }));
  });
  document.title = `${items[items.length - 1]?.label || 'OpenReporting'} · OpenReporting`;
}

export async function navigate(path, { replace = false, force = false } = {}) {
  if (!force && leaveGuard) {
    const message = leaveGuard();
    if (message && !window.confirm(message)) return;
  }
  if (replace) history.replaceState({}, '', path); else history.pushState({}, '', path);
  await render();
}

function runCleanup(fn) {
  if (typeof fn !== 'function') return;
  try { fn(); } catch (err) { console.error(err); } // eslint-disable-line no-console
}

// Tears down the current page (timers, listeners, overlays). Also used when the session expires.
export function teardown() {
  renderToken += 1;
  runCleanup(current.cleanup);
  current = { cleanup: null, path: current.path };
  leaveGuard = null;
  closePopups();
  closeAllModals();
  const overlay = document.getElementById('overlay-root');
  if (overlay) clear(overlay);
}

// Each render gets its own container and token: a page whose async setup finishes after the user
// already navigated away writes into a detached node and is cleaned up immediately.
let renderToken = 0;
export async function render() {
  const path = location.pathname;
  const query = location.search;
  teardown();
  const token = renderToken;
  const container = h('div', { class: 'route-view' });
  clear(renderTarget);
  renderTarget.append(container);
  for (const r of routes) {
    const m = r.regex.exec(path);
    if (!m) continue;
    let params;
    try { params = Object.fromEntries(r.keys.map((k, i) => [k, decodeURIComponent(m[i + 1])])); } catch { break; }
    appContext.onRoute && appContext.onRoute(path);
    let cleanup = null;
    try {
      cleanup = await r.handler(container, { ...params, query, app: appContext });
    } catch (err) {
      if (token !== renderToken) return;
      container.replaceChildren(h('div', { class: 'page' }, h('div', { class: 'alert error', role: 'alert', text: `Sayfa yüklenemedi: ${err.message || err}` })));
      return;
    }
    if (token !== renderToken) { runCleanup(cleanup); return; }
    current = { cleanup: typeof cleanup === 'function' ? cleanup : null, path };
    window.scrollTo(0, 0);
    return;
  }
  container.append(h('div', { class: 'page' }, h('div', { class: 'empty-state' }, h('h3', { text: 'Sayfa bulunamadı' }), h('p', { text: path }))));
}

let started = false;

export function startRouter(target, app) {
  renderTarget = target;
  appContext = app;
  if (started) return render();
  started = true;
  window.addEventListener('popstate', () => {
    if (leaveGuard) {
      const message = leaveGuard();
      if (message && !window.confirm(message)) { history.pushState({}, '', current.path); return; }
    }
    render();
  });
  window.addEventListener('beforeunload', (e) => { if (leaveGuard && leaveGuard()) { e.preventDefault(); e.returnValue = ''; } });
  document.addEventListener('click', (e) => {
    const a = e.target.closest('a[data-link], a[href^="/"]');
    if (!a || a.target === '_blank' || e.ctrlKey || e.metaKey || e.shiftKey || a.hasAttribute('download')) return;
    const href = a.getAttribute('href');
    if (!href || href.startsWith('/api/') || href.startsWith('/static/') || href.startsWith('/metrics')) return;
    e.preventDefault();
    navigate(href);
  });
  return render();
}
