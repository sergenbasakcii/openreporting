// API: one page that explains how to use the REST API, lists the endpoints (from /api/openapi.json)
// and manages access keys. Service accounts stay the server-side model but are presented as
// "applications": one key = one application with read or read/write access.
import { h, button, input, select, field, toast, modal, confirmDialog, fmtDateTime, loading, clear, copyText } from '../dom.js';
import { icon } from '../icons.js';
import { get, post, patch, del } from '../api.js';
import { setBreadcrumbs } from '../router.js';

const ACCESS = [{ value: 'viewer', label: 'Okuma (dashboard, panel verisi, rapor indirme)' }, { value: 'editor', label: 'Okuma + yazma (dashboard ve rapor oluşturma)' }];
const TABS = [{ id: 'overview', label: 'Genel bakış' }, { id: 'endpoints', label: 'Uç noktalar' }, { id: 'keys', label: 'Erişim anahtarları' }];
const METHOD_CLASS = { get: 'info', post: 'ok', put: 'warn', patch: 'warn', delete: 'err' };

const slug = (text) => text.toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '').replace(/ı/g, 'i').replace(/[^a-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 70);

function keyState(t) {
  if (t.revoked_at) return h('span', { class: 'badge', text: 'iptal edildi' });
  if (Date.parse(t.expires_at) <= Date.now()) return h('span', { class: 'badge err', text: 'süresi doldu' });
  return h('span', { class: 'badge ok', text: 'etkin' });
}

function showKey(issued) {
  const box = input({ value: issued.token, readonly: true, class: 'mono', label: 'Erişim anahtarı' });
  const dlg = modal({ title: 'Anahtarı şimdi kopyalayın', closeOnBackdrop: false, body: h('div',
    h('div', { class: 'alert warn', text: 'Anahtar yalnız bu kez gösterilir; sunucu yalnızca özetini saklar. Kaybederseniz iptal edip yenisini oluşturun.' }),
    box,
    h('pre', { class: 'code-sample', text: `curl -H "Authorization: Bearer ${issued.token.slice(0, 14)}…" ${location.origin}/api/search` }),
    h('p', { class: 'hint', text: `Geçerlilik sonu: ${fmtDateTime(issued.expires_at)}` })),
  footer: [button('Kopyala', { icon: 'copy', onClick: () => copyText(issued.token) }), button('Kapat', { variant: 'primary', onClick: () => dlg.close() })] });
  setTimeout(() => box.select(), 0);
}

// One dialog: name the application, choose access and lifetime, confirm with your password.
function newKey(accounts, done) {
  const m = { app: '', role: 'viewer', days: 90, password: '' };
  const dlg = modal({ title: 'Yeni erişim anahtarı', body: h('div',
    h('p', { class: 'muted', text: 'API’yi kullanacak uygulama veya otomasyon için bir anahtar oluşturun (ör. CI/CD, ticket sistemi, BI aracı). Anahtar insan kullanıcı gibi giriş yapamaz ve yönetim işlemlerine erişemez.' }),
    field('Uygulama adı', input({ placeholder: 'ör. Jenkins üretim', onInput: (e) => { m.app = e.target.value; } })),
    field('Yetki', select(ACCESS, m.role, (v) => { m.role = v; })),
    field('Geçerlilik (gün)', input({ type: 'number', value: 90, min: 1, max: 365, onInput: (e) => { m.days = Number(e.target.value); } }), 'En fazla 365 gün'),
    field('Parolanız (onay için)', input({ type: 'password', autocomplete: 'current-password', onInput: (e) => { m.password = e.target.value; } }))),
  footer: [button('Vazgeç', { onClick: () => dlg.close() }), button('Anahtar oluştur', { variant: 'primary', onClick: async () => {
    const username = `svc-${slug(m.app)}`;
    if (username.length < 7) { toast('Uygulama adı en az 3 harf olmalı', 'error'); return; }
    try {
      let account = accounts.find((a) => a.username === username);
      if (account && account.role !== m.role) { toast(`“${m.app}” başka bir yetkiyle zaten var; farklı bir ad verin`, 'error'); return; }
      if (!account) account = await post('/api/admin/service-accounts', { username, role: m.role, display_name: m.app });
      const issued = await post(`/api/admin/service-accounts/${account.id}/tokens`, { name: m.app, days: m.days, password: m.password });
      dlg.close(); showKey(issued); done();
    } catch (err) { toast(err.message, 'error'); }
  } })] });
}

function overview(spec, go) {
  const base = `${location.origin}/api`;
  const sample = (title, code) => h('div', h('b', { text: title }), h('pre', { class: 'code-sample', text: code }));
  return h('div',
    h('div', { class: 'card' }, h('h2', { class: 'section-heading', text: 'OpenReporting REST API' }),
      h('p', { text: 'Arayüzde yapılabilen her işin API karşılığı vardır: dashboard listeleme/okuma/kaydetme, panel verisi sorgulama, rapor oluşturma ve PDF/Excel indirme. Yanıtlar JSON’dur.' }),
      h('ol', { class: 'explore-steps' },
        h('li', h('span', { class: 'step-no', text: '1' }), h('div', h('b', { text: 'Anahtar oluşturun' }), h('span', { class: 'hint', text: 'Erişim anahtarları sekmesinden, uygulama başına bir anahtar.' }))),
        h('li', h('span', { class: 'step-no', text: '2' }), h('div', h('b', { text: 'Başlığa ekleyin' }), h('span', { class: 'hint', text: 'Authorization: Bearer ortk_…' }))),
        h('li', h('span', { class: 'step-no', text: '3' }), h('div', h('b', { text: 'Uçları çağırın' }), h('span', { class: 'hint', text: `Temel adres: ${base}` })))),
      h('div', { class: 'toolbar' }, button('Erişim anahtarı oluştur', { icon: 'key', variant: 'primary', onClick: () => go('keys') }), button('Uç noktaları gör', { icon: 'code', onClick: () => go('endpoints') }),
        button('OpenAPI JSON indir', { icon: 'download', onClick: () => {
          const a = h('a', { href: URL.createObjectURL(new Blob([JSON.stringify(spec, null, 2)], { type: 'application/json' })), download: 'openreporting-openapi.json' });
          a.click(); URL.revokeObjectURL(a.href);
        } }))),
    h('div', { class: 'card' }, h('h2', { class: 'section-heading', text: 'Örnekler' }),
      sample('Dashboard’ları listele', `curl -H "Authorization: Bearer $ORTK" ${base}/search`),
      sample('Bir dashboard’u JSON olarak al', `curl -H "Authorization: Bearer $ORTK" ${base}/dashboards/uid/<uid>`),
      sample('Raporların son çalıştırmalarını listele', `curl -H "Authorization: Bearer $ORTK" ${base}/report-runs?limit=20`),
      sample('Bir çalıştırmanın PDF dosyasını indir', `curl -H "Authorization: Bearer $ORTK" -o rapor.pdf ${base}/report-runs/<çalıştırma-id>/files/pdf`),
      h('p', { class: 'hint', text: 'OpenAPI dosyasını Postman, Insomnia veya kod üreticilere içe aktarabilirsiniz. Hesap, oturum ve yönetim uçları anahtarla kullanılamaz.' })));
}

function endpoints(spec) {
  const groups = {};
  for (const [path, methods] of Object.entries(spec.paths || {})) {
    const group = path.split('/')[2] || 'genel';
    for (const [method, op] of Object.entries(methods)) (groups[group] ||= []).push({ path, method, op });
  }
  let filter = '';
  const list = h('div');
  const draw = () => {
    clear(list);
    for (const [group, ops] of Object.entries(groups).sort()) {
      const shown = ops.filter((o) => !filter || `${o.method} ${o.path} ${o.op.summary || ''}`.toLowerCase().includes(filter));
      if (!shown.length) continue;
      list.append(h('div', { class: 'card' }, h('h2', { class: 'section-heading', text: `/api/${group}` }),
        h('table', { class: 'list' }, shown.map((o) => h('tr',
          h('td', { class: 'nowrap' }, h('span', { class: `badge ${METHOD_CLASS[o.method] || ''}`, text: o.method.toUpperCase() })),
          h('td', { class: 'mono', text: o.path }), h('td', { text: o.op.summary || '' }))))));
    }
  };
  draw();
  return h('div', h('div', { class: 'toolbar', style: { marginBottom: '12px' } },
    input({ label: 'Uç ara', placeholder: 'Uç ara (ör. dashboards)', onInput: (e) => { filter = e.target.value.toLowerCase(); draw(); } })), list);
}

async function keys(redraw) {
  const accounts = await get('/api/admin/service-accounts');
  const rows = accounts.flatMap((a) => a.tokens.map((t) => ({ a, t })))
    .sort((x, y) => String(y.t.created_at || '').localeCompare(String(x.t.created_at || '')));
  const wrap = h('div', h('div', { class: 'toolbar', style: { justifyContent: 'space-between', marginBottom: '12px' } },
    h('p', { class: 'muted', style: { margin: 0 }, text: 'Her uygulama kendi anahtarını kullanır; sızdığında yalnızca o anahtarı iptal edersiniz.' }),
    button('Yeni erişim anahtarı', { icon: 'plus', variant: 'primary', onClick: () => newKey(accounts, redraw) })));
  if (!rows.length) {
    wrap.append(h('div', { class: 'empty-state' }, h('h2', { class: 'section-heading', text: 'Henüz erişim anahtarı yok' }),
      h('p', { text: 'API’yi kullanacak her uygulama için bir anahtar oluşturun.' })));
    return wrap;
  }
  wrap.append(h('div', { class: 'card' }, h('table', { class: 'list' },
    h('tr', ['Uygulama', 'Yetki', 'Anahtar', 'Durum', 'Geçerlilik sonu', 'Son kullanım', ''].map((t) => h('th', { text: t }))),
    rows.map(({ a, t }) => h('tr',
      h('td', h('b', { text: a.display_name || a.username }), a.active ? null : h('span', { class: 'badge err', text: 'uygulama kapalı' })),
      h('td', { text: a.role === 'editor' ? 'Okuma + yazma' : 'Okuma' }),
      h('td', { class: 'mono', text: `ortk_${t.prefix}_…` }), h('td', keyState(t)),
      h('td', { text: fmtDateTime(t.expires_at) }), h('td', { text: t.last_used_at ? fmtDateTime(t.last_used_at) : 'hiç' }),
      h('td', { class: 'actions' },
        button(a.active ? 'Uygulamayı durdur' : 'Uygulamayı aç', { size: 'sm', onClick: async () => {
          try { await patch(`/api/admin/service-accounts/${a.id}`, { active: !a.active }); redraw(); } catch (err) { toast(err.message, 'error'); }
        } }),
        t.revoked_at ? null : button('İptal et', { size: 'sm', variant: 'danger', onClick: async () => {
          if (!(await confirmDialog('Anahtarı iptal et', `${a.display_name || a.username} anahtarı hemen geçersiz olur.`, { danger: true, okText: 'İptal et' }))) return;
          try { await del(`/api/admin/tokens/${t.id}`); toast('Anahtar iptal edildi', 'ok'); redraw(); } catch (err) { toast(err.message, 'error'); }
        } })))))));
  return wrap;
}

export async function apiPage(root, { tab = 'overview' } = {}) {
  setBreadcrumbs([{ label: 'Yönetim' }, { label: 'API' }]);
  const page = h('div', { class: 'page' }, loading());
  root.append(page);
  const spec = await get('/api/openapi.json');
  let current = TABS.some((t) => t.id === tab) ? tab : 'overview';
  const body = h('div');
  const tabBar = h('div', { class: 'tabs', role: 'tablist' });
  const go = (id) => { current = id; history.replaceState(history.state, '', id === 'keys' ? '/admin/api-keys' : '/admin/api'); draw(); };
  const draw = async () => {
    clear(tabBar);
    for (const t of TABS) tabBar.append(h('button', { type: 'button', role: 'tab', 'aria-selected': String(t.id === current), class: t.id === current ? 'on' : '', text: t.label, onClick: () => go(t.id) }));
    clear(body).append(loading());
    const content = current === 'overview' ? overview(spec, go) : current === 'endpoints' ? endpoints(spec) : await keys(draw);
    clear(body).append(content);
  };
  clear(page).append(h('div', { class: 'page-header' }, h('div', h('h1', icon('code'), 'API'),
    h('p', { class: 'sub', text: `${spec.info.title} · sürüm ${spec.info.version}` }))), tabBar, body);
  await draw();
}

export const apiKeysPage = (root) => apiPage(root, { tab: 'keys' });
export const apiReferencePage = (root) => apiPage(root, { tab: 'overview' });
