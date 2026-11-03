// Service accounts, API tokens and the in-app API reference (rendered from /api/openapi.json).
import { h, button, input, select, field, toast, modal, confirmDialog, fmtDateTime, loading, clear, copyText } from '../dom.js';
import { icon } from '../icons.js';
import { get, post, patch, del } from '../api.js';
import { setBreadcrumbs } from '../router.js';

const ROLE_OPTIONS = [{ value: 'viewer', label: 'İzleyici (okuma)' }, { value: 'editor', label: 'Editör (dashboard/rapor yazma)' }];

function tokenState(t) {
  if (t.revoked_at) return h('span', { class: 'badge', text: 'iptal' });
  if (Date.parse(t.expires_at) <= Date.now()) return h('span', { class: 'badge err', text: 'süresi doldu' });
  return h('span', { class: 'badge ok', text: 'etkin' });
}

function createAccount(done) {
  const m = { username: '', role: 'viewer', display_name: '' };
  const dlg = modal({ title: 'Yeni servis hesabı', body: h('div',
    h('p', { class: 'muted', text: 'Servis hesapları yalnız API anahtarıyla çalışır; parola ile giriş yapamaz ve yönetici olamaz. Klasör izinleri insan kullanıcılarla aynı şekilde uygulanır.' }),
    field('Hesap adı', input({ placeholder: 'svc-ci', onInput: (e) => { m.username = e.target.value; } }), 'Küçük harf, rakam, . _ -'),
    field('Açıklama', input({ placeholder: 'GitLab CI dashboard senkronu', onInput: (e) => { m.display_name = e.target.value; } })),
    field('Rol', select(ROLE_OPTIONS, m.role, (v) => { m.role = v; }))),
  footer: [button('Vazgeç', { onClick: () => dlg.close() }), button('Oluştur', { variant: 'primary', onClick: async () => {
    try { await post('/api/admin/service-accounts', m); toast('Servis hesabı oluşturuldu', 'ok'); dlg.close(); done(); } catch (err) { toast(err.message, 'error'); }
  } })] });
}

function issueToken(account, done) {
  const m = { name: '', days: 90, password: '' };
  const dlg = modal({ title: `API anahtarı · ${account.username}`, body: h('div',
    field('Anahtar adı', input({ placeholder: 'ör. jenkins-prod', onInput: (e) => { m.name = e.target.value; } })),
    field('Geçerlilik (gün)', input({ type: 'number', value: 90, min: 1, max: 365, onInput: (e) => { m.days = Number(e.target.value); } }), 'En fazla 365 gün; süresi dolan anahtar çalışmaz'),
    field('Sizin mevcut parolanız', input({ type: 'password', autocomplete: 'current-password', onInput: (e) => { m.password = e.target.value; } }))),
  footer: [button('Vazgeç', { onClick: () => dlg.close() }), button('Üret', { variant: 'primary', onClick: async () => {
    try {
      const issued = await post(`/api/admin/service-accounts/${account.id}/tokens`, m);
      dlg.close();
      showToken(issued);
      done();
    } catch (err) { toast(err.message, 'error'); }
  } })] });
}

function showToken(issued) {
  const box = input({ value: issued.token, readonly: true, class: 'mono', label: 'API anahtarı' });
  const dlg = modal({ title: 'Anahtarı şimdi kopyalayın', closeOnBackdrop: false, body: h('div',
    h('div', { class: 'alert warn', text: 'Bu anahtar yalnız bir kez gösterilir ve sunucuda saklanmaz. Kaybederseniz iptal edip yenisini üretin.' }),
    box,
    h('p', { class: 'hint', text: `Geçerlilik sonu: ${fmtDateTime(issued.expires_at)}. Kullanım: Authorization: Bearer <anahtar>` })),
  footer: [button('Kopyala', { icon: 'copy', onClick: () => copyText(issued.token) }), button('Kapat', { variant: 'primary', onClick: () => dlg.close() })] });
  setTimeout(() => box.select(), 0);
}

export async function apiKeysPage(root) {
  setBreadcrumbs([{ label: 'Yönetim' }, { label: 'API anahtarları' }]);
  const page = h('div', { class: 'page' });
  root.append(page);
  const draw = async () => {
    clear(page).append(loading());
    const accounts = await get('/api/admin/service-accounts');
    clear(page);
    page.append(h('div', { class: 'page-header' }, h('div', h('h1', icon('key'), 'API anahtarları'),
      h('p', { class: 'sub', text: 'Otomasyon (CI/CD, ticket sistemleri, dashboard-as-code) için servis hesapları ve süreli API anahtarları.' })),
      h('div', { class: 'toolbar' }, h('a', { class: 'btn', href: '/admin/api', 'data-link': '' }, icon('code'), h('span', { text: 'API başvurusu' })),
        button('Servis hesabı ekle', { icon: 'plus', variant: 'primary', onClick: () => createAccount(draw) }))));
    if (!accounts.length) {
      page.append(h('div', { class: 'empty-state' }, h('h2', { class: 'section-heading', text: 'Henüz servis hesabı yok' }),
        h('p', { text: 'Bir servis hesabı oluşturun, ardından ona süreli bir API anahtarı üretin.' })));
      return;
    }
    for (const account of accounts) {
      const rows = account.tokens.map((t) => h('tr', h('td', { text: t.name }), h('td', { class: 'mono', text: `ortk_${t.prefix}_…` }), h('td', tokenState(t)),
        h('td', { text: fmtDateTime(t.expires_at) }), h('td', { text: t.last_used_at ? fmtDateTime(t.last_used_at) : 'hiç' }),
        h('td', { class: 'actions' }, t.revoked_at ? null : button('İptal et', { size: 'sm', variant: 'danger', onClick: async () => {
          if (!(await confirmDialog('Anahtarı iptal et', `${t.name} anahtarı hemen geçersiz olur.`, { danger: true, okText: 'İptal et' }))) return;
          try { await del(`/api/admin/tokens/${t.id}`); toast('Anahtar iptal edildi', 'ok'); draw(); } catch (err) { toast(err.message, 'error'); }
        } }))));
      page.append(h('div', { class: 'card' },
        h('div', { class: 'toolbar', style: { justifyContent: 'space-between' } },
          h('h2', { class: 'section-heading', style: { margin: '0' } }, account.username, ' ',
            h('span', { class: 'badge info', text: account.role === 'editor' ? 'Editör' : 'İzleyici' }),
            account.active ? null : h('span', { class: 'badge err', text: 'devre dışı' })),
          h('div', { class: 'toolbar' },
            button(account.active ? 'Devre dışı bırak' : 'Etkinleştir', { size: 'sm', onClick: async () => {
              try { await patch(`/api/admin/service-accounts/${account.id}`, { active: !account.active }); draw(); } catch (err) { toast(err.message, 'error'); }
            } }),
            button('Anahtar üret', { size: 'sm', icon: 'key', onClick: () => issueToken(account, draw) }))),
        account.display_name ? h('p', { class: 'muted', text: account.display_name }) : null,
        rows.length ? h('table', { class: 'list' }, h('tr', ['Ad', 'Önek', 'Durum', 'Geçerlilik sonu', 'Son kullanım', ''].map((t) => h('th', { text: t }))), rows)
          : h('p', { class: 'muted', text: 'Bu hesabın anahtarı yok.' })));
    }
  };
  await draw();
}

const METHOD_CLASS = { get: 'info', post: 'ok', put: 'warn', patch: 'warn', delete: 'err' };

export async function apiReferencePage(root) {
  setBreadcrumbs([{ label: 'Yönetim' }, { label: 'API başvurusu' }]);
  const page = h('div', { class: 'page' }, loading());
  root.append(page);
  const spec = await get('/api/openapi.json');
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
  clear(page).append(h('div', { class: 'page-header' }, h('div', h('h1', icon('code'), spec.info.title),
    h('p', { class: 'sub', text: `Sürüm ${spec.info.version} · ${spec.info.description || ''}` })),
    h('div', { class: 'toolbar' }, input({ label: 'Uç ara', placeholder: 'Uç ara (ör. dash-reports)', onInput: (e) => { filter = e.target.value.toLowerCase(); draw(); } }),
      button('OpenAPI JSON indir', { icon: 'download', onClick: () => {
        const blob = new Blob([JSON.stringify(spec, null, 2)], { type: 'application/json' });
        const a = h('a', { href: URL.createObjectURL(blob), download: 'openreporting-openapi.json' }); a.click(); URL.revokeObjectURL(a.href);
      } }))),
  h('div', { class: 'alert', text: 'Kimlik doğrulama: tarayıcı oturumu veya Yönetim → API anahtarları sayfasında üretilen anahtar ile "Authorization: Bearer ortk_…" başlığı. Anahtarlar hesap, oturum ve yönetim uçlarında kullanılamaz.' }),
  list);
  draw();
}
