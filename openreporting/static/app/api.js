// Fetch wrapper: same-origin cookies + CSRF header held in memory (rotated after reload).
const state = { csrf: sessionStorage.getItem('openreporting_csrf') || '', onUnauthorized: null };

export class ApiError extends Error {
  constructor(status, message, detail) { super(message); this.status = status; this.detail = detail; }
}

export function setCsrf(token) {
  state.csrf = token || '';
  try { if (token) sessionStorage.setItem('openreporting_csrf', token); else sessionStorage.removeItem('openreporting_csrf'); } catch { /* storage may be blocked */ }
}
export function onUnauthorized(fn) { state.onUnauthorized = fn; }

function detailMessage(detail, status) {
  if (!detail) return `İstek başarısız (HTTP ${status})`;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) return detail.map((d) => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('; ');
  if (detail.blocked) return detail.blocked.join('; ');
  if (detail.errors) return detail.errors.map((e) => e.message).join('; ');
  return JSON.stringify(detail);
}

// Single-flight: concurrent panels that all see a stale token share one rotation.
let csrfInFlight = null;
export function refreshCsrf() {
  if (!csrfInFlight) {
    csrfInFlight = (async () => {
      const res = await fetch('/api/session/csrf', { method: 'POST', credentials: 'same-origin' });
      if (!res.ok) throw new ApiError(res.status, 'Oturum doğrulanamadı');
      setCsrf((await res.json()).csrf);
    })().finally(() => { csrfInFlight = null; });
  }
  return csrfInFlight;
}

export async function api(path, { method = 'GET', body, raw = false, signal, retry = true } = {}) {
  const headers = { Accept: 'application/json' };
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  if (method !== 'GET') {
    if (!state.csrf) { try { await refreshCsrf(); } catch { /* handled by request below */ } }
    headers['X-CSRF-Token'] = state.csrf;
  }
  const res = await fetch(path, { method, headers, credentials: 'same-origin', signal,
    body: body === undefined ? undefined : JSON.stringify(body) });
  if (res.status === 403 && method !== 'GET' && retry) {
    const text = await res.clone().text();
    if (text.includes('CSRF')) { await refreshCsrf(); return api(path, { method, body, raw, signal, retry: false }); }
  }
  if (res.status === 401 && !path.startsWith('/api/login')) {
    setCsrf('');
    cache.clear();
    // The start-up session probe is how a fresh visit learns it is logged out: no "session expired" notice.
    if (state.onUnauthorized && path !== '/api/session') state.onUnauthorized();
    throw new ApiError(401, 'Oturum süresi doldu; tekrar giriş yapın');
  }
  if (raw) {
    if (!res.ok) throw new ApiError(res.status, `İndirme başarısız (HTTP ${res.status})`);
    return res;
  }
  let data = null;
  const text = await res.text();
  if (text) { try { data = JSON.parse(text); } catch { data = text; } }
  if (!res.ok) throw new ApiError(res.status, detailMessage(data && data.detail !== undefined ? data.detail : data, res.status), data);
  return data;
}

export const get = (path, opts) => api(path, { ...opts, method: 'GET' });
export const post = (path, body, opts) => api(path, { ...opts, method: 'POST', body: body ?? {} });
export const put = (path, body, opts) => api(path, { ...opts, method: 'PUT', body: body ?? {} });
export const patch = (path, body, opts) => api(path, { ...opts, method: 'PATCH', body: body ?? {} });
export const del = (path, opts) => api(path, { ...opts, method: 'DELETE' });

// Small in-memory caches shared by pages, bounded so long sessions do not grow without limit.
const cache = new Map();
const CACHE_MAX_ENTRIES = 200;
export async function cached(key, loader, ttlMs = 30000) {
  const hit = cache.get(key);
  if (hit && hit.expires > Date.now()) return hit.value;
  cache.delete(key);
  const value = await loader();
  cache.set(key, { value, expires: Date.now() + ttlMs });
  while (cache.size > CACHE_MAX_ENTRIES) cache.delete(cache.keys().next().value);
  return value;
}
export function invalidate(prefix) { for (const key of cache.keys()) if (key.startsWith(prefix)) cache.delete(key); }

export const datasourcesList = () => cached('ds:list', () => get('/api/datasources'), 15000);
export const queryCatalog = () => cached('catalog', () => get('/api/query/catalog'), 3600000);
