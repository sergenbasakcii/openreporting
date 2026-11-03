// Application bootstrap: session, theme, shell (navigation + topbar), routes.
import { h, button, input, field, menu, toast, clear } from './dom.js';
import { icon } from './icons.js';
import { get, post, setCsrf, onUnauthorized, refreshCsrf } from './api.js';
import { route, startRouter, navigate, setCrumbHost, render, teardown } from './router.js';
import { enrollmentPage } from './mfa.js';
import { loadPlugins } from './plugins.js';
import { applyThemeToDocument, resolveTheme, oppositeTheme, normalisePreference, SYSTEM } from './themes.js';

const app = { user: null, prefs: null, settings: null, pendingDashboard: null };
const NAV_KEY = 'openreporting.nav.collapsed';
const THEME_KEY = 'openreporting.theme';

// A preference is a theme id or 'system' (follows the OS light/dark setting).
function applyTheme(preference) {
  const pref = normalisePreference(preference);
  const theme = applyThemeToDocument(resolveTheme(pref).id);
  try { localStorage.setItem(THEME_KEY, pref); } catch { /* storage may be blocked */ }
  window.dispatchEvent(new CustomEvent('openreporting:themechange', { detail: theme.id }));
}
function storedTheme() {
  try { return localStorage.getItem(THEME_KEY); } catch { return null; }
}
applyTheme(storedTheme() || SYSTEM);
window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => {
  if (normalisePreference(storedTheme() || SYSTEM) === SYSTEM) applyTheme(SYSTEM);
});

function loginPage(root) {
  const user = input({ autocomplete: 'username', placeholder: 'kullanıcı adı', label: 'Kullanıcı adı' });
  const pass = input({ type: 'password', autocomplete: 'current-password', placeholder: 'parola', label: 'Parola' });
  const error = h('div', { class: 'alert error', hidden: true, role: 'alert' });
  const code = input({ autocomplete: 'one-time-code', maxlength: 128 });
  const codeField = field('Doğrulayıcı veya kurtarma kodu', code, '6 haneli güncel kodu veya tek kullanımlık kurtarma kodunu girin.');
  codeField.hidden = true;
  const submit = button('Giriş yap', { variant: 'primary', type: 'submit' });
  const form = h('form', { class: 'login-card', onsubmit: async (e) => {
    e.preventDefault();
    error.hidden = true;
    submit.disabled = true;
    try {
      const res = await post('/api/login', { username: user.value.trim(), password: pass.value, otp: codeField.hidden ? null : code.value.trim() });
      setCsrf(res.csrf);
      pass.value = ''; code.value = '';
      await boot();
    } catch (err) {
      const needsCode = err.detail?.detail?.code === 'mfa_required';
      if (needsCode) codeField.hidden = false;
      error.textContent = needsCode ? 'Devam etmek için doğrulayıcı veya kurtarma kodunuzu girin.' : err.status === 401 ? 'Giriş bilgileri veya doğrulama kodu hatalı.'
        : err.status === 429 ? 'Çok fazla deneme yapıldı; biraz sonra tekrar deneyin.'
        : err.status === 503 ? 'Giriş hizmeti şu anda yanıt veremiyor; biraz sonra tekrar deneyin.' : err.message;
      error.hidden = false;
      submit.disabled = false;
      if (!codeField.hidden) code.focus(); else pass.select();
    }
  } }, h('div', { class: 'brand-logo', text: 'O' }), h('h1', { text: 'OpenReporting' }), h('p', { text: 'Gözlem, dashboard ve raporlama platformu' }),
  error, field('Kullanıcı adı', user), field('Parola', pass), codeField, submit);
  user.addEventListener('input', () => { codeField.hidden = true; code.value = ''; });
  root.replaceChildren(h('main', { class: 'login-page' }, form));
  setTimeout(() => {
    // Do not steal focus if typing already started in a different field.
    if (form.isConnected && document.activeElement === document.body) user.focus();
  }, 20);
}

function navItem(path, label, iconName, match) {
  return h('a', { class: 'nav-item', href: path, 'data-link': '', dataset: { match: match || path } }, icon(iconName), h('span', { class: 'label', text: label }));
}

function shell(root) {
  const isAdmin = app.user.role === 'admin';
  const canEdit = ['admin', 'editor'].includes(app.user.role);
  const nav = h('nav', { class: 'nav-list', 'aria-label': 'Ana menü' },
    navItem('/', 'Ana sayfa', 'home', '^/$'),
    navItem('/dashboards', 'Dashboard’lar', 'apps', '^/(dashboards|d/)'),
    canEdit ? navItem('/explore', 'Keşfet (Explore)', 'compass', '^/explore') : null,
    navItem('/reports', 'Raporlar', 'report', '^/reports'),
    // The administration section only exists for admins; other roles have nothing under it.
    isAdmin ? [
      h('div', { class: 'nav-section', text: 'Yönetim' }),
      navItem('/datasources', 'Veri kaynakları', 'database', '^/datasources'),
      navItem('/admin/users', 'Kullanıcılar', 'users', '^/admin/users'),
      navItem('/admin/settings', 'Sistem ayarları', 'settings', '^/admin/settings'),
      navItem('/admin/api', 'API', 'code', '^/admin/(api-keys|api)$'),
      navItem('/admin/plugins', 'Eklentiler', 'layers', '^/admin/plugins'),
      navItem('/admin/server', 'Sunucu durumu', 'activity', '^/admin/server'),
      navItem('/admin/audit', 'Denetim kaydı', 'shield', '^/admin/audit'),
    ] : null);
  const initials = (app.user.display_name || app.user.username).slice(0, 2).toUpperCase();
  const userBtn = h('div', { class: 'nav-footer' }, h('div', { class: 'avatar', text: initials }),
    h('div', { class: 'who' }, h('b', { text: app.user.display_name || app.user.username }), h('span', { text: { admin: 'Yönetici', editor: 'Editör', viewer: 'İzleyici' }[app.user.role] || app.user.role })),
    button('', { icon: 'dots', variant: 'ghost', size: 'sm', title: 'Hesap', onClick: (e) => menu(e.currentTarget, [
      { label: 'Profil ve tercihler', icon: 'user', onClick: () => navigate('/profile') },
      { label: document.documentElement.dataset.scheme === 'dark' ? 'Açık temaya geç' : 'Koyu temaya geç', icon: document.documentElement.dataset.scheme === 'dark' ? 'sun' : 'moon',
        onClick: () => applyTheme(oppositeTheme(document.documentElement.dataset.theme)) },
      { sep: true },
      { label: 'Çıkış yap', icon: 'logout', onClick: async () => { try { await post('/api/logout'); } finally { setCsrf(''); location.href = '/'; } } },
    ]) }));
  const sidenav = h('aside', { class: 'sidenav' }, h('div', { class: 'brand' }, h('div', { class: 'brand-logo', text: 'O' }), h('div', { class: 'label' }, 'OpenReporting', h('small', { text: `v${app.settings.version}` }))), nav, userBtn);
  const crumbs = h('div', { class: 'breadcrumbs' });
  setCrumbHost(crumbs);
  const search = input({ placeholder: 'Dashboard ara…', class: 'search-box', onKeydown: (e) => { if (e.key === 'Enter') navigate(`/dashboards?query=${encodeURIComponent(e.target.value)}`); } });
  const toggleNav = button('', { icon: 'menu', variant: 'ghost', title: 'Menüyü daralt/genişlet', onClick: () => {
    document.body.classList.toggle('nav-collapsed');
    try { localStorage.setItem(NAV_KEY, document.body.classList.contains('nav-collapsed') ? '1' : ''); } catch { /* ignore */ }
    window.dispatchEvent(new Event('resize'));
  } });
  // Everything under "+" creates content, so viewers do not get the button at all.
  const topbar = h('header', { class: 'topbar' }, toggleNav, crumbs, search,
    canEdit ? button('', { icon: 'plus', variant: 'ghost', title: 'Yeni', onClick: (e) => menu(e.currentTarget, [
      { label: 'Yeni dashboard', icon: 'apps', onClick: () => navigate('/dashboards/new') },
      { label: 'Dashboard içe aktar', icon: 'import', onClick: () => navigate('/dashboards/import') },
      { label: 'Yeni rapor', icon: 'report', onClick: () => navigate('/reports/new') },
      { label: 'Keşfet', icon: 'compass', onClick: () => navigate('/explore') },
    ], { align: 'right' }) }) : null);
  const content = h('main', { class: 'app-content', id: 'content' });
  root.replaceChildren(h('div', { class: 'app-shell' }, sidenav, h('div', { class: 'app-main' }, topbar, content)));
  try { if (localStorage.getItem(NAV_KEY)) document.body.classList.add('nav-collapsed'); } catch { /* ignore */ }
  app.onRoute = (path) => {
    for (const a of nav.querySelectorAll('.nav-item[data-match]')) a.classList.toggle('active', new RegExp(a.dataset.match).test(path));
  };
  return content;
}

function registerRoutes() {
  const lazy = (modulePath, exportName, extra = {}) => async (target, params) => {
    const mod = await import(modulePath);
    if (!target.isConnected) return null; // navigated away while the module loaded
    return mod[exportName](target, { ...params, ...extra });
  };
  route('/', async (target, params) => {
    const home = app.prefs && app.prefs.home_dashboard_uid;
    if (home && !params.query) {
      // A deleted or no longer visible home dashboard falls back to the regular home page.
      const exists = await get(`/api/dashboards/uid/${encodeURIComponent(home)}`).then(() => true, () => false);
      if (!target.isConnected) return null; // the user navigated elsewhere meanwhile; leave the URL alone
      if (exists) { history.replaceState({}, '', `/d/${encodeURIComponent(home)}`); return lazy('./pages/dashboard.js', 'dashboardPage')(target, { ...params, uid: home }); }
    }
    return lazy('./pages/home.js', 'homePage')(target, params);
  });
  route('/dashboards', lazy('./pages/browse.js', 'browsePage'));
  route('/dashboards/f/:folderUid', lazy('./pages/browse.js', 'browsePage'));
  route('/dashboards/new', lazy('./pages/dashboard.js', 'dashboardPage'));
  route('/dashboards/import', lazy('./pages/browse.js', 'importPage'));
  route('/d/:uid', lazy('./pages/dashboard.js', 'dashboardPage'));
  route('/d/:uid/:slug', lazy('./pages/dashboard.js', 'dashboardPage'));
  route('/explore', lazy('./pages/explore.js', 'explorePage'));
  route('/datasources', lazy('./pages/datasources.js', 'datasourcesPage'));
  route('/datasources/new', lazy('./pages/datasources.js', 'datasourceEditPage'));
  route('/datasources/edit/:uid', lazy('./pages/datasources.js', 'datasourceEditPage'));
  route('/reports', lazy('./pages/reports.js', 'reportsPage'));
  route('/reports/new', lazy('./pages/reports.js', 'reportEditPage'));
  route('/reports/:id', lazy('./pages/reports.js', 'reportEditPage'));
  route('/admin/users', lazy('./pages/admin.js', 'usersPage'));
  route('/admin/settings', lazy('./pages/settings.js', 'settingsPage'));
  route('/admin/api-keys', lazy('./pages/apikeys.js', 'apiKeysPage'));
  route('/admin/plugins', lazy('./pages/plugins.js', 'pluginsPage'));
  route('/admin/api', lazy('./pages/apikeys.js', 'apiReferencePage'));
  route('/admin/server', lazy('./pages/admin.js', 'serverPage'));
  route('/admin/audit', lazy('./pages/admin.js', 'auditPage'));
  route('/profile', lazy('./pages/admin.js', 'profilePage', { applyTheme }));
  route('/login', async () => { navigate('/', { replace: true }); });
}

async function boot() {
  const root = document.getElementById('app');
  try {
    const session = await get('/api/session');
    app.user = session.user;
    loggedOut = false;
    if (session.mfa_enrollment_required) {
      teardown();
      await refreshCsrf();
      enrollmentPage(root);
      return;
    }
  } catch (err) {
    if (err.status === 401) { loginPage(root); return; }
    root.replaceChildren(h('div', { class: 'page' }, h('div', { class: 'alert error', text: `Sunucuya ulaşılamadı: ${err.message}` })));
    return;
  }
  try { await refreshCsrf(); } catch { /* login will rotate */ }
  const [me, settings, plugins] = await Promise.all([get('/api/user'), get('/api/frontend/settings'), get('/api/plugins').catch(() => [])]);
  await loadPlugins(plugins);
  app.user = { ...app.user, ...me };
  app.prefs = me.preferences;
  app.settings = settings;
  if (me.preferences && me.preferences.theme) applyTheme(me.preferences.theme);
  const content = shell(root);
  if (!app.routesRegistered) { registerRoutes(); app.routesRegistered = true; startRouter(content, app); }
  else { startRouter(content, app); }
}

// Many panels can receive 401 at once: stop the current page (timers, refreshes) and show the login form once.
let loggedOut = false;
window.addEventListener('openreporting:factorchanged', () => { loggedOut = true; teardown(); });
onUnauthorized(() => {
  if (loggedOut) return;
  loggedOut = true;
  teardown();
  toast('Oturum sona erdi; lütfen tekrar giriş yapın', 'warn');
  setTimeout(() => loginPage(document.getElementById('app')), 300);
});

window.addEventListener('unhandledrejection', (e) => {
  const message = e.reason && e.reason.message ? e.reason.message : String(e.reason);
  if (e.reason && e.reason.status === 401) return;
  toast(message, 'error');
});

boot();

export { app, render, clear };
